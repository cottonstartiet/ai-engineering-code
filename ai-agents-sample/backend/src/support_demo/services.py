from collections.abc import Mapping

from opentelemetry import propagate, trace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from support_demo.contracts import Assessment, Citation, DomainError, Information, RunInput
from support_demo.db import (
    Customer,
    Event,
    Job,
    Order,
    Policy,
    Proposal,
    Resolution,
    Run,
    now,
    transaction,
    uid,
)
from support_demo.domain import evaluate
from support_demo.telemetry import approval_wait, logger, outcomes, span

TERMINAL = {"completed", "escalated", "rejected", "cancelled", "interrupted", "failed"}


async def require_run(session: AsyncSession, run_id: str, *, lock: bool = False) -> Run:
    query = select(Run).where(Run.id == run_id)
    if lock:
        query = query.with_for_update()
    run = await session.scalar(query)
    if run is None:
        raise DomainError("Run not found", 404)
    return run


async def append(
    session: AsyncSession,
    run: Run,
    kind: str,
    text: str = "",
    *,
    actor: str = "system",
    node: str = "",
    data: dict | None = None,
) -> None:
    run.updated_at = now()
    logger.info(
        "support.event %s",
        kind,
        extra={
            "support.run_id": run.id,
            "support.case_id": run.case_id,
            "support.event.kind": kind,
            "support.actor": actor,
            "support.node": node,
        },
    )
    session.add(
        Event(
            run_id=run.id,
            kind=kind,
            text=text,
            actor=actor,
            node=node,
            data=data or {},
        )
    )


async def emit(
    run_id: str,
    kind: str,
    text: str = "",
    *,
    actor: str = "system",
    node: str = "",
    data: dict | None = None,
) -> None:
    async with transaction() as session:
        run = await require_run(session, run_id, lock=True)
        if run.status in TERMINAL:
            return
        await append(session, run, kind, text, actor=actor, node=node, data=data)


async def scoped_order(
    session: AsyncSession,
    customer_id: str,
    order_id: str,
    *,
    lock: bool = False,
) -> Order:
    query = select(Order).where(Order.id == order_id, Order.customer_id == customer_id)
    if lock:
        query = query.with_for_update()
    order = await session.scalar(query)
    if order is None:
        raise DomainError("Order is not available for the selected demo customer.", 404)
    return order


def order_dict(order: Order) -> dict:
    return {
        "id": order.id,
        "customer_id": order.customer_id,
        "status": order.status,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        **order.details,
    }


def proposal_dict(proposal: Proposal) -> dict:
    return {column.name: getattr(proposal, column.name) for column in Proposal.__table__.columns}


async def run_dict(session: AsyncSession, run: Run) -> dict:
    proposal = await session.scalar(select(Proposal).where(Proposal.run_id == run.id))
    return {
        **run.request,
        "id": run.id,
        "case_id": run.case_id,
        "parent_run_id": run.parent_run_id,
        "status": run.status,
        "result": run.result,
        "trace_id": run.trace_id,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "proposal": proposal_dict(proposal) if proposal else None,
    }


def event_dict(event: Event) -> dict:
    return {column.name: getattr(event, column.name) for column in Event.__table__.columns}


async def insert_run(session: AsyncSession, request: RunInput, parent: Run | None = None) -> str:
    if await session.get(Customer, request.customer_id) is None:
        raise DomainError("Demo customer not found", 404)
    if request.order_id:
        order = await scoped_order(session, request.customer_id, request.order_id)
        if request.item_id and not any(
            item["id"] == request.item_id for item in order.details["items"]
        ):
            raise DomainError("Item does not belong to this order.", 422)
    context: dict[str, str] = {}
    propagate.inject(context)
    run = Run(
        id=uid(),
        case_id=parent.case_id if parent else uid(),
        parent_run_id=parent.id if parent else None,
        customer_id=request.customer_id,
        desk=request.desk,
        request=request.model_dump(),
        trace_context=context,
        trace_id=f"{trace.get_current_span().get_span_context().trace_id:032x}",
    )
    session.add(run)
    await session.flush()
    session.add(Job(run_id=run.id, kind="investigate"))
    await append(session, run, "status", "Investigation queued.", data={"status": "queued"})
    return run.id


async def create_run(request: RunInput) -> str:
    async with transaction() as session:
        return await insert_run(session, request)


async def continue_run(run_id: str, information: Information | None = None) -> str:
    async with transaction() as session:
        parent = await require_run(session, run_id, lock=True)
        expected = {"awaiting_customer"} if information else {"failed", "interrupted"}
        if parent.status not in expected:
            raise DomainError("This run cannot be continued in its current state.")
        values = dict(parent.request)
        if information:
            updates = information.model_dump(exclude_none=True)
            values.update(updates)
            combined = parent.request["message"] + "\nCustomer update: " + information.message
            if len(combined) > 4000:
                raise DomainError(
                    "Combined case context exceeds 4000 characters. Shorten the update "
                    "or start a new case; existing details have not been discarded.",
                    422,
                )
            values["message"] = combined
        child_id = await insert_run(session, RunInput.model_validate(values), parent)
        parent.status = "completed"
        parent.result = {
            **(parent.result or {}),
            "summary": "Continued in a linked investigation.",
            "continuation_run_id": child_id,
        }
        await append(
            session,
            parent,
            "status",
            "Linked continuation created.",
            data={"status": "completed", "continuation_run_id": child_id},
        )
        return child_id


async def finish(run_id: str, status: str, result: Mapping) -> None:
    async with transaction() as session:
        run = await require_run(session, run_id, lock=True)
        if run.status in TERMINAL:
            return
        run.status, run.result = status, dict(result)
        outcomes.add(1, {"desk": run.desk, "status": status})
        await append(
            session, run, "status", str(result.get("summary", "")), data={"status": status}
        )


async def eligibility_for(session: AsyncSession, run: Run, action: str):
    order = await scoped_order(session, run.customer_id, run.request["order_id"], lock=True)
    resolved = await session.scalar(
        select(func.coalesce(func.sum(Resolution.quantity), 0)).where(
            Resolution.order_id == order.id,
            Resolution.item_id == run.request["item_id"],
        )
    )
    policies = {p.id: p for p in (await session.scalars(select(Policy))).all()}
    return evaluate(
        run,
        order,
        policies,
        int(resolved or 0),
        action,
        checked_delivery_locations=run.request.get("delivery_checks_confirmed", False),
    )


async def propose(run_id: str, assessment: Assessment, citations: list[Citation]) -> None:
    valid_ids = {citation.id for citation in citations}
    if not assessment.citations or not set(assessment.citations) <= valid_ids:
        raise DomainError("Model supplied missing or unsupported policy citations.", 422)
    async with transaction() as session:
        run = await require_run(session, run_id, lock=True)
        if run.status != "running":
            raise DomainError("Run is not active.")
        eligible = await eligibility_for(session, run, assessment.action)
        if not eligible.eligible:
            run.status, run.result = "escalated", {"summary": eligible.reason}
            await append(session, run, "status", eligible.reason, data={"status": "escalated"})
            return
        if eligible.policy_id not in assessment.citations:
            raise DomainError("The proposal must cite the applicable authorization policy.", 422)
        proposal = Proposal(
            id=uid(),
            run_id=run.id,
            case_id=run.case_id,
            customer_id=run.customer_id,
            order_id=run.request["order_id"],
            item_id=run.request["item_id"],
            action=assessment.action,
            quantity=run.request["quantity"],
            amount_cents=eligible.amount_cents,
            citations=assessment.citations,
            explanation=assessment.summary,
        )
        session.add(proposal)
        run.status = "awaiting_approval"
        run.result = {
            "summary": assessment.summary,
            "citations": [c.model_dump() for c in citations],
            "termination_reason": "resolution_proposed",
        }
        await append(
            session,
            run,
            "approval",
            "Human approval required before any simulated action.",
            node="approval",
            data={"state": "waiting", "proposal_id": proposal.id},
        )
        await append(session, run, "status", "Awaiting reviewer.", data={"status": run.status})


async def decide(proposal_id: str, decision: str) -> dict:
    with span("approval.decide", decision=decision):
        async with transaction() as session:
            initial = await session.get(Proposal, proposal_id)
            if initial is None:
                raise DomainError("Proposal not found", 404)
            run = await require_run(session, initial.run_id, lock=True)
            proposal = await session.get(Proposal, proposal_id, with_for_update=True)
            assert proposal is not None
            if run.status != "awaiting_approval" or proposal.status != "pending":
                raise DomainError("Approval is stale or already decided.")
            if decision == "approved":
                eligible = await eligibility_for(session, run, proposal.action)
                if not eligible.eligible or eligible.amount_cents != proposal.amount_cents:
                    raise DomainError("Proposal is no longer eligible. Start a new investigation.")
                run.status = "queued"
                session.add(Job(run_id=run.id, kind="execute"))
            else:
                run.status = "rejected"
                run.result = {
                    **(run.result or {}),
                    "summary": "Reviewer rejected the proposed action.",
                }
            proposal.status, proposal.decided_at = decision, now()
            approval_wait.record(
                (now() - proposal.created_at).total_seconds(),
                {"decision": decision},
            )
            await append(
                session,
                run,
                "approval",
                f"Reviewer {decision} the exact proposed action.",
                node="approval",
                data={"state": "completed", "decision": decision},
            )
            await append(session, run, "status", data={"status": run.status})
            return proposal_dict(proposal)


async def execute_resolution(run_id: str) -> None:
    with span("resolution.execute"):
        async with transaction() as session:
            run = await require_run(session, run_id, lock=True)
            proposal = await session.scalar(
                select(Proposal).where(Proposal.run_id == run_id).with_for_update()
            )
            if proposal is not None and proposal.status == "executed":
                return
            if run.status == "cancelled":
                return
            if proposal is None or proposal.status != "approved":
                raise DomainError("A valid human approval is required.")
            eligible = await eligibility_for(session, run, proposal.action)
            if not eligible.eligible or eligible.amount_cents != proposal.amount_cents:
                run.status = "escalated"
                run.result = {"summary": "Approved proposal became stale; no action was executed."}
                proposal.status = "cancelled"
                await append(session, run, "error", run.result["summary"])
                return
            await append(session, run, "node", node="execute", data={"state": "running"})
            resolution = Resolution(
                proposal_id=proposal.id,
                order_id=proposal.order_id,
                item_id=proposal.item_id,
                quantity=proposal.quantity,
                action=proposal.action,
                amount_cents=proposal.amount_cents,
            )
            session.add(resolution)
            await session.flush()
            stored = await session.scalar(
                select(Resolution).where(Resolution.proposal_id == proposal.id)
            )
            if stored is None:
                raise RuntimeError("Simulated action verification failed")
            proposal.status, run.status = "executed", "completed"
            run.result = {
                **(run.result or {}),
                "summary": (
                    f"Simulated {proposal.action} recorded for {proposal.quantity} item(s). "
                    "No real payment or shipment was created."
                ),
                "resolution_id": stored.id,
            }
            for node in ("execute", "verify", "confirmation"):
                await append(
                    session,
                    run,
                    "node",
                    node=node,
                    data={"state": "completed"},
                )
            await append(
                session, run, "action", run.result["summary"], data={"resolution_id": stored.id}
            )
            await append(session, run, "status", data={"status": "completed"})
            outcomes.add(1, {"desk": run.desk, "status": "completed"})


async def cancel(run_id: str) -> None:
    async with transaction() as session:
        run = await require_run(session, run_id, lock=True)
        if run.status in TERMINAL:
            raise DomainError("Terminal runs cannot be cancelled.")
        run.status = "cancelled"
        run.result = {"summary": "Cancelled. No pending action will execute."}
        proposal = await session.scalar(select(Proposal).where(Proposal.run_id == run_id))
        if proposal and proposal.status in {"pending", "approved"}:
            proposal.status = "cancelled"
        await append(session, run, "status", run.result["summary"], data={"status": "cancelled"})

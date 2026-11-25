import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Never

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from support_demo.agents import assess, investigate_delivery, model_client
from support_demo.contracts import Assessment, Citation, Eligibility
from support_demo.db import transaction
from support_demo.retrieval import search_policies
from support_demo.services import (
    eligibility_for,
    emit,
    execute_resolution,
    finish,
    order_dict,
    propose,
    require_run,
    scoped_order,
)


@dataclass
class ReturnState:
    run_id: str
    request: dict
    order: dict = field(default_factory=dict)
    policies: list[Citation] = field(default_factory=list)
    eligibility: Eligibility | None = None
    assessment: Assessment | None = None
    question: str = ""


async def node(run_id: str, name: str, state: str = "completed", text: str = "") -> None:
    await emit(run_id, "node", text, node=name, data={"state": state})


async def retrieve(state: ReturnState) -> ReturnState:
    async def get_order() -> dict:
        async with transaction() as session:
            order = await scoped_order(
                session,
                state.request["customer_id"],
                state.request["order_id"],
            )
            return order_dict(order)

    order, policies = await asyncio.gather(
        get_order(),
        search_policies(state.request["message"], state.request["desk"]),
    )
    state.order, state.policies = order, policies
    await emit(
        state.run_id,
        "evidence",
        f"Retrieved {len(policies)} applicable policy sections.",
        node="retrieve",
        data={"citations": [p.model_dump() for p in policies]},
    )
    return state


async def complete_assessment(state: ReturnState, assessment: Assessment) -> None:
    valid = {p.id for p in state.policies}
    if not set(assessment.citations) <= valid:
        raise ValueError("Assessment cites unavailable policy evidence")
    if assessment.outcome == "propose":
        await propose(state.run_id, assessment, state.policies)
    elif assessment.outcome == "clarify":
        if not assessment.question.strip():
            raise ValueError("Clarification requires a customer question")
        await emit(state.run_id, "clarification", assessment.question, node="clarification")
        await finish(
            state.run_id,
            "awaiting_customer",
            {
                "summary": assessment.summary,
                "question": assessment.question,
                "citations": [p.model_dump() for p in state.policies],
            },
        )
    else:
        status = "escalated" if assessment.outcome == "escalate" else "completed"
        await finish(
            state.run_id,
            status,
            {
                "summary": assessment.summary,
                "citations": [p.model_dump() for p in state.policies],
            },
        )


def missing_details(request: dict) -> str:
    if not request.get("order_id"):
        return "Select the affected order."
    if not request.get("item_id"):
        return "Select the affected item."
    reason = request.get("reason") or ""
    if request["desk"] == "returns" and not (
        reason.lower().startswith(("defective:", "damaged:")) and reason.split(":", 1)[1].strip()
    ):
        return "Describe the issue as 'defective: description' or 'damaged: description'."
    return ""


def build_returns_workflow(client: Any):
    @executor(id="intake")
    async def intake(state: ReturnState, ctx: WorkflowContext[ReturnState]) -> None:
        await node(state.run_id, "intake")
        state.question = missing_details(state.request)
        await node(state.run_id, "identify")
        await ctx.send_message(state)

    @executor(id="clarification")
    async def clarification(state: ReturnState, ctx: WorkflowContext[Never, str]) -> None:
        await node(state.run_id, "clarification", "waiting")
        await complete_assessment(
            state,
            Assessment(
                outcome="clarify",
                summary="Additional customer information is required.",
                question=state.question,
            ),
        )
        await ctx.yield_output("awaiting_customer")

    @executor(id="retrieve")
    async def retrieval(state: ReturnState, ctx: WorkflowContext[ReturnState]) -> None:
        await node(state.run_id, "retrieve", "running")
        await retrieve(state)
        await node(state.run_id, "retrieve")
        await ctx.send_message(state)

    @executor(id="eligibility")
    async def eligibility(state: ReturnState, ctx: WorkflowContext[ReturnState]) -> None:
        async with transaction() as session:
            run = await require_run(session, state.run_id)
            state.eligibility = await eligibility_for(session, run, "refund")
        await node(state.run_id, "eligibility", text=state.eligibility.reason)
        await ctx.send_message(state)

    @executor(id="escalated")
    async def escalated(state: ReturnState, ctx: WorkflowContext[Never, str]) -> None:
        assert state.eligibility is not None
        await node(state.run_id, "escalated")
        await finish(
            state.run_id,
            "escalated",
            {
                "summary": state.eligibility.reason,
                "citations": [p.model_dump() for p in state.policies],
            },
        )
        await ctx.yield_output("escalated")

    @executor(id="proposal")
    async def proposal(state: ReturnState, ctx: WorkflowContext[Never, str]) -> None:
        if not state.policies:
            await finish(
                state.run_id, "escalated", {"summary": "No applicable policy evidence found."}
            )
            await ctx.yield_output("escalated")
            return
        await node(state.run_id, "proposal", "running")
        response = await assess(
            client,
            json.dumps(
                {
                    "request": state.request,
                    "order": state.order,
                    "policies": [p.model_dump() for p in state.policies],
                    "eligibility": state.eligibility.model_dump() if state.eligibility else None,
                }
            ),
            instructions=(
                "The deterministic eligibility service has accepted the item and quantity. "
                "Propose a refund, or replacement only if explicitly requested. "
                "Cite returns-30-day. Money is calculated by application code. "
                "If evidence is insufficient, clarify or escalate; never claim an action occurred."
            ),
        )
        await node(state.run_id, "proposal")
        await complete_assessment(state, response)
        await ctx.yield_output(response.outcome)

    return (
        WorkflowBuilder(
            name="ReturnsRefundsDesk",
            start_executor=intake,
            output_from=[clarification, escalated, proposal],
        )
        .add_edge(intake, clarification, condition=lambda s: bool(s.question))
        .add_edge(intake, retrieval, condition=lambda s: not s.question)
        .add_edge(retrieval, eligibility)
        .add_edge(
            eligibility,
            proposal,
            condition=lambda s: s.eligibility is not None and s.eligibility.eligible,
        )
        .add_edge(
            eligibility,
            escalated,
            condition=lambda s: s.eligibility is not None and not s.eligibility.eligible,
        )
        .build()
    )


def build_action_workflow():
    @executor(id="approval")
    async def approval(run_id: str, ctx: WorkflowContext[str]) -> None:
        from sqlalchemy import select

        from support_demo.contracts import DomainError
        from support_demo.db import Proposal

        async with transaction() as session:
            proposal = await session.scalar(select(Proposal).where(Proposal.run_id == run_id))
            if proposal is None or proposal.status not in {"approved", "executed"}:
                raise DomainError("Approved action workflow requires persisted human approval.")
        await ctx.send_message(run_id)

    @executor(id="execute")
    async def execute(run_id: str, ctx: WorkflowContext[str]) -> None:
        await execute_resolution(run_id)
        await ctx.send_message(run_id)

    @executor(id="verify")
    async def verify(run_id: str, ctx: WorkflowContext[Never, str]) -> None:
        async with transaction() as session:
            run = await require_run(session, run_id)
            if run.status not in {"completed", "cancelled", "escalated"}:
                raise RuntimeError("Approved action did not reach a verified terminal state")
            await ctx.yield_output(run.status)

    return (
        WorkflowBuilder(
            name="ApprovedResolutionContinuation",
            start_executor=approval,
            output_from=[verify],
        )
        .add_edge(approval, execute)
        .add_edge(execute, verify)
        .build()
    )


async def execute_approved(run_id: str) -> None:
    await build_action_workflow().run(run_id)


async def investigate(run_id: str) -> None:
    async with transaction() as session:
        run = await require_run(session, run_id)
        request = dict(run.request)
    state = ReturnState(run_id=run_id, request=request)
    async with model_client() as client:
        if request["desk"] == "returns":
            await build_returns_workflow(client).run(state)
            return
        question = missing_details(request)
        if question:
            await complete_assessment(
                state,
                Assessment(
                    outcome="clarify",
                    summary="Identify the affected order/item.",
                    question=question,
                ),
            )
            return
        await retrieve(state)
        if not state.policies:
            await finish(run_id, "escalated", {"summary": "No applicable delivery evidence found."})
            return
        if state.order["status"] == "delivered" and not request.get("delivery_checks_confirmed"):
            await complete_assessment(
                state,
                Assessment(
                    outcome="clarify",
                    summary="Delivery checks must be confirmed by the customer.",
                    question="Have you checked household members and safe delivery locations? "
                    "Confirm using the delivery-checks checkbox.",
                ),
            )
            return
        assessment = await investigate_delivery(
            run_id,
            request,
            state.order,
            state.policies,
            client=client,
        )
        await complete_assessment(state, assessment)

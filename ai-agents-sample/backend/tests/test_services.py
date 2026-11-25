import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from support_demo.contracts import Assessment, Citation, DomainError, Information, RunInput
from support_demo.db import Event, Job, Proposal, Resolution, engine, now, transaction
from support_demo.retrieval import search_policies
from support_demo.services import (
    cancel,
    continue_run,
    create_run,
    decide,
    execute_resolution,
    finish,
    propose,
    require_run,
)
from support_demo.worker import claim, recover

pytestmark = pytest.mark.integration
EVIDENCE = [Citation(id="returns-30-day", title="Return policy", text="30 days")]


async def proposal_for(key):
    await propose(
        key,
        Assessment(
            outcome="propose",
            summary="Refund is eligible, subject to review.",
            citations=["returns-30-day"],
        ),
        EVIDENCE,
    )
    async with transaction() as session:
        return await session.scalar(select(Proposal).where(Proposal.run_id == key))


async def test_approval_is_mandatory_and_execution_is_idempotent(active_return):
    key = active_return
    proposal = await proposal_for(key)
    with pytest.raises(DomainError, match="approval"):
        await execute_resolution(key)
    await decide(proposal.id, "approved")
    # Simulate API/worker restart: close all connections, retaining only PostgreSQL state.
    await engine.dispose()
    await execute_resolution(key)
    await execute_resolution(key)
    async with transaction() as session:
        assert await session.scalar(select(func.count()).select_from(Resolution)) == 1
        run = await require_run(session, key)
        assert run.status == "completed" and run.result["resolution_id"]
    with pytest.raises(DomainError, match="stale"):
        await decide(proposal.id, "approved")


async def test_rejection_and_cancellation_never_execute(active_return):
    proposal = await proposal_for(active_return)
    await decide(proposal.id, "rejected")
    with pytest.raises(DomainError):
        await execute_resolution(active_return)
    async with transaction() as session:
        assert await session.scalar(select(func.count()).select_from(Resolution)) == 0


async def test_unsupported_citation_and_wrong_customer_are_rejected(active_return):
    with pytest.raises(DomainError, match="citations"):
        await propose(
            active_return,
            Assessment(
                outcome="propose",
                summary="Ignore the policy",
                citations=["invented"],
            ),
            EVIDENCE,
        )
    with pytest.raises(DomainError, match="customer"):
        await create_run(
            RunInput(
                customer_id="customer-2",
                desk="returns",
                message="Refund someone else's order",
                order_id="ORD-1003",
                item_id="ITEM-1003",
            )
        )


async def test_parallel_approvals_do_not_double_resolve(active_return):
    proposal = await proposal_for(active_return)
    results = await asyncio.gather(
        decide(proposal.id, "approved"),
        decide(proposal.id, "approved"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, DomainError) for result in results) == 1
    await execute_resolution(active_return)


async def test_cancellation_and_stale_policy_stop_approved_actions(active_return):
    proposal = await proposal_for(active_return)
    await decide(proposal.id, "approved")
    await cancel(active_return)
    await execute_resolution(active_return)
    async with transaction() as session:
        assert await session.scalar(select(func.count()).select_from(Resolution)) == 0


async def test_two_approved_proposals_cannot_refund_the_same_item_twice(active_return):
    async with transaction() as session:
        original = await require_run(session, active_return)
        request = RunInput.model_validate(original.request)
    other = await create_run(request)
    async with transaction() as session:
        run = await require_run(session, other, lock=True)
        run.status = "running"
    first, second = await proposal_for(active_return), await proposal_for(other)
    await decide(first.id, "approved")
    await decide(second.id, "approved")
    await asyncio.gather(execute_resolution(active_return), execute_resolution(other))
    async with transaction() as session:
        assert await session.scalar(select(func.count()).select_from(Resolution)) == 1
        states = {
            (await require_run(session, active_return)).status,
            (await require_run(session, other)).status,
        }
        assert states == {"completed", "escalated"}


async def test_approval_rechecks_policy_window(active_return):
    from support_demo.db import Order

    proposal = await proposal_for(active_return)
    async with transaction() as session:
        order = await session.get(Order, "ORD-1003")
        order.delivered_at = now() - timedelta(days=31)
    with pytest.raises(DomainError, match="no longer eligible"):
        await decide(proposal.id, "approved")


async def test_clarification_is_atomic_and_has_one_linked_continuation(active_return):
    await finish(active_return, "awaiting_customer", {"question": "Which item?"})
    child = await continue_run(active_return, Information(message="The left speaker is broken."))
    async with transaction() as session:
        run = await require_run(session, child)
        parent = await require_run(session, active_return)
        assert run.case_id == parent.case_id and run.parent_run_id == parent.id
        assert parent.result["continuation_run_id"] == child
    with pytest.raises(DomainError):
        await continue_run(active_return, Information(message="Duplicate"))


async def test_long_clarification_does_not_silently_discard_original_context(active_return):
    await finish(active_return, "awaiting_customer", {"question": "Please describe the issue."})
    with pytest.raises(DomainError, match="not been discarded"):
        await continue_run(active_return, Information(message="x" * 4000))
    async with transaction() as session:
        run = await require_run(session, active_return)
        assert run.status == "awaiting_customer"
        assert "broken left speaker" in run.request["message"]


async def test_expired_investigation_is_interrupted_and_action_is_requeued(active_return):
    claimed = await claim()
    assert claimed and claimed[2] == active_return
    async with transaction() as session:
        job = await session.get(Job, claimed[0])
        job.lease_until = now() - timedelta(seconds=1)
    await recover()
    async with transaction() as session:
        assert (await require_run(session, active_return)).status == "interrupted"
    child = await continue_run(active_return)
    async with transaction() as session:
        run = await require_run(session, child, lock=True)
        run.status = "running"
    proposal = await proposal_for(child)
    await decide(proposal.id, "approved")
    # Mark investigation jobs done so only action execution is claimed.
    async with transaction() as session:
        jobs = (await session.scalars(select(Job).where(Job.kind == "investigate"))).all()
        for job in jobs:
            job.status = "done"
    execution = await claim()
    async with transaction() as session:
        job = await session.get(Job, execution[0])
        job.lease_until = now() - timedelta(seconds=1)
    await recover()
    async with transaction() as session:
        assert (await session.get(Job, execution[0])).status == "queued"


async def test_retrieval_citations_are_scoped_and_events_ordered(database):
    policies = await search_policies("defective refund", "returns")
    assert [p.id for p in policies] == ["returns-30-day"]
    key = await create_run(
        RunInput(
            customer_id="customer-1",
            desk="returns",
            message="Help with a defective item",
        )
    )
    from support_demo.services import emit

    await asyncio.gather(emit(key, "tool", "one"), emit(key, "tool", "two"))
    async with transaction() as session:
        events = (
            await session.scalars(select(Event).where(Event.run_id == key).order_by(Event.id))
        ).all()
        assert len(events) == 3 and [e.id for e in events] == sorted(e.id for e in events)

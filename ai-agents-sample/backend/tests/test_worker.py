import asyncio
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from support_demo.contracts import RunInput
from support_demo.db import Job, Proposal, Resolution, transaction, uid
from support_demo.services import create_run, decide, require_run
from support_demo.worker import claim, fail_owned_job, process

from .fakes import ScriptedClient

pytestmark = pytest.mark.integration


async def test_two_desks_process_and_approved_action_continues_after_restart(
    database, monkeypatch, observed
):
    @asynccontextmanager
    async def fake_client():
        yield ScriptedClient()

    monkeypatch.setattr("support_demo.workflows.model_client", fake_client)
    delivery = await create_run(
        RunInput(
            customer_id="customer-1",
            desk="delivery",
            message="Delivered but missing; household and safe locations checked.",
            order_id="ORD-1001",
            item_id="ITEM-1001",
            delivery_checks_confirmed=True,
        )
    )
    returns = await create_run(
        RunInput(
            customer_id="customer-1",
            desk="returns",
            message="Refund defective headphones",
            order_id="ORD-1003",
            item_id="ITEM-1003",
            reason="defective: broken left speaker",
        )
    )
    first, second = await asyncio.gather(claim(), claim())
    assert first and second and first[0] != second[0]
    await asyncio.gather(process(*first), process(*second))
    async with transaction() as session:
        assert (await require_run(session, delivery)).status == "awaiting_approval"
        assert (await require_run(session, returns)).status == "awaiting_approval"
        proposal = await session.scalar(select(Proposal).where(Proposal.run_id == returns))
    await decide(proposal.id, "approved")
    from support_demo.db import engine

    await engine.dispose()
    job = await claim()
    assert job and job[2] == returns
    await process(*job)
    async with transaction() as session:
        assert (await require_run(session, returns)).status == "completed"
        assert (await session.scalar(select(Resolution))).amount_cents == 8999
    spans = observed.get_finished_spans()
    names = {span.name for span in spans}
    assert "support.job" in names and "resolution.execute" in names
    assert any("invoke_workflow" in name for name in names)
    assert any("invoke_agent" in name for name in names)
    assert any("policy.search" in name for name in names)
    assert not any("synthetic-test-key" in repr(span.attributes) for span in spans)


async def test_stale_worker_cannot_fail_a_new_owners_run(active_return):
    claimed = await claim()
    async with transaction() as session:
        job = await session.get(Job, claimed[0], with_for_update=True)
        job.owner = uid()
    await fail_owned_job(
        claimed[0],
        claimed[1],
        "interrupted",
        {"summary": "Old worker lost ownership"},
    )
    async with transaction() as session:
        assert (await require_run(session, active_return)).status == "running"

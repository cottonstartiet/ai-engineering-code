import pytest
from sqlalchemy import select

from support_demo.agents import investigate_delivery
from support_demo.contracts import Citation, RunInput
from support_demo.db import Event, Proposal, transaction
from support_demo.services import create_run, order_dict, require_run, scoped_order
from support_demo.workflows import ReturnState, build_returns_workflow

from .fakes import ScriptedClient

pytestmark = pytest.mark.integration


async def test_real_maf_directed_graph_produces_approval_not_execution(active_return):
    async with transaction() as session:
        run = await require_run(session, active_return)
        request = dict(run.request)
    result = await build_returns_workflow(ScriptedClient()).run(ReturnState(active_return, request))
    assert result.get_outputs() == ["propose"]
    async with transaction() as session:
        run = await require_run(session, active_return)
        assert run.status == "awaiting_approval"
        assert (await session.scalar(select(Proposal))).amount_cents == 8999
        nodes = (
            await session.scalars(
                select(Event.node).where(Event.run_id == run.id, Event.kind == "node")
            )
        ).all()
        assert {"intake", "identify", "retrieve", "eligibility", "proposal"} <= set(nodes)


async def test_real_graph_clarifies_before_retrieval(database):
    key = await create_run(
        RunInput(
            customer_id="customer-1",
            desk="returns",
            message="I need a refund",
        )
    )
    async with transaction() as session:
        run = await require_run(session, key, lock=True)
        run.status = "running"
        request = dict(run.request)
    client = ScriptedClient()
    result = await build_returns_workflow(client).run(ReturnState(key, request))
    assert result.get_outputs() == ["awaiting_customer"]
    assert client.calls == 0


async def test_real_graph_escalates_expired_return_without_model(database):
    key = await create_run(
        RunInput(
            customer_id="customer-1",
            desk="returns",
            message="Defective keyboard refund",
            order_id="ORD-1005",
            item_id="ITEM-1005",
            reason="defective: keys broken",
        )
    )
    async with transaction() as session:
        run = await require_run(session, key, lock=True)
        run.status = "running"
        request = dict(run.request)
    client = ScriptedClient()
    result = await build_returns_workflow(client).run(ReturnState(key, request))
    assert result.get_outputs() == ["escalated"] and client.calls == 0


async def test_real_group_chat_coordinates_three_specialists(database):
    request = RunInput(
        customer_id="customer-1",
        desk="delivery",
        message="Delivered but missing. Household and safe locations checked.",
        order_id="ORD-1001",
        item_id="ITEM-1001",
        delivery_checks_confirmed=True,
    )
    key = await create_run(request)
    async with transaction() as session:
        run = await require_run(session, key, lock=True)
        run.status = "running"
        order = order_dict(await scoped_order(session, run.customer_id, request.order_id))
    assessment = await investigate_delivery(
        key,
        request.model_dump(),
        order,
        [
            Citation(
                id="delivery-missing", title="Missing shipment", text="Review missing delivery."
            )
        ],
        client=ScriptedClient(),
    )
    assert assessment.action == "replacement" and assessment.citations == ["delivery-missing"]
    async with transaction() as session:
        speakers = set(
            (
                await session.scalars(
                    select(Event.actor).where(Event.run_id == key, Event.kind == "speaker_selected")
                )
            ).all()
        )
        assert speakers == {"OrderSpecialist", "DeliverySpecialist", "PolicySpecialist"}

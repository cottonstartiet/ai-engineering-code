import httpx
import pytest

from support_demo.main import app

pytestmark = pytest.mark.integration


async def test_api_customer_scoping_and_input_validation(database):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        health = await client.get("/api/health")
        assert health.status_code == 200 and health.json()["policies_indexed"] == 3
        orders = await client.get("/api/orders", params={"customer_id": "customer-2"})
        assert [o["id"] for o in orders.json()] == ["ORD-2001"]
        response = await client.post(
            "/api/runs",
            json={
                "customer_id": "customer-2",
                "desk": "returns",
                "message": "Refund",
                "order_id": "ORD-1003",
            },
        )
        assert response.status_code == 404
        invalid = await client.post(
            "/api/runs",
            json={
                "customer_id": "customer-1",
                "desk": "returns",
                "message": "Refund",
                "quantity": -1,
            },
        )
        assert invalid.status_code == 422


async def test_api_cancel_and_stale_retry_errors(database):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/runs",
            json={
                "customer_id": "customer-1",
                "desk": "delivery",
                "message": "My package is missing",
            },
        )
        assert response.status_code == 201
        key = response.json()["id"]
        cancelled = await client.post(f"/api/runs/{key}/cancel")
        assert cancelled.json()["status"] == "cancelled"
        assert (await client.post(f"/api/runs/{key}/retry")).status_code == 409
        assert (await client.get("/api/runs/does-not-exist")).status_code == 404


async def test_sse_replays_only_events_after_durable_cursor(active_return):
    import json

    from sqlalchemy import select

    from support_demo.db import Event, transaction
    from support_demo.main import events
    from support_demo.services import emit

    await emit(active_return, "tool", "first")
    await emit(active_return, "tool", "second")
    async with transaction() as session:
        stored = (
            await session.scalars(
                select(Event).where(Event.run_id == active_return).order_by(Event.id)
            )
        ).all()

    class Connected:
        async def is_disconnected(self):
            return False

    response = await events(active_return, Connected(), after=0, last_event_id=str(stored[-2].id))
    body = response.body_iterator
    try:
        event = await anext(body)
        payload = json.loads(event.split("data: ", 1)[1])
        assert payload["id"] == stored[-1].id and payload["text"] == "second"
        assert f"id: {stored[-1].id}" in event
    finally:
        await body.aclose()

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy import func, select, text

from support_demo.config import settings
from support_demo.contracts import Decision, DomainError, Information, RunInput
from support_demo.db import (
    Customer,
    Event,
    IndexConfig,
    Order,
    Policy,
    Proposal,
    Run,
    engine,
    transaction,
)
from support_demo.seed import load_json
from support_demo.services import (
    cancel,
    continue_run,
    create_run,
    decide,
    event_dict,
    order_dict,
    proposal_dict,
    require_run,
    run_dict,
)
from support_demo.telemetry import configure, shutdown


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure("support-api")
    yield
    shutdown()
    await engine.dispose()


app = FastAPI(title="Retail Support Agents - synthetic local demo", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app, excluded_urls="/api/health")
SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine, enable_commenter=False)


@app.exception_handler(DomainError)
async def domain_error(request: Request, exc: DomainError):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.get("/api/health")
async def health():
    async with transaction() as session:
        await session.execute(text("SELECT 1"))
        index = await session.get(IndexConfig, "policies")
        count = await session.scalar(
            select(func.count())
            .select_from(Policy)
            .where(
                Policy.embedding.is_not(None),
            )
        )
        ready = bool(
            index
            and count
            and index.dimensions == settings().embedding_dimensions
            and index.model == settings().azure_openai_embedding_deployment
        )
        return JSONResponse(
            {
                "status": "ready" if ready else "setup_required",
                "database": "connected",
                "policies_indexed": count or 0,
            },
            status_code=200 if ready else 503,
        )


@app.get("/api/customers")
async def customers():
    async with transaction() as session:
        return [
            {"id": c.id, "name": c.name}
            for c in (await session.scalars(select(Customer).order_by(Customer.id))).all()
        ]


@app.get("/api/scenarios")
async def scenarios(customer_id: str | None = None, desk: str | None = None):
    result = []
    for source in load_json("scenarios/scenarios.json"):
        if customer_id and source["customer_id"] != customer_id:
            continue
        if desk and source["desk"] != desk:
            continue
        result.append(
            {
                **source,
                "delivery_checks_confirmed": source["id"] == "missing-package",
            }
        )
    return result


@app.get("/api/orders")
async def orders(customer_id: str):
    async with transaction() as session:
        return [
            order_dict(o)
            for o in (
                await session.scalars(select(Order).where(Order.customer_id == customer_id))
            ).all()
        ]


@app.post("/api/runs", status_code=201)
async def start_run(request: RunInput):
    key = await create_run(request)
    return await get_run(key)


@app.get("/api/runs")
async def list_runs(customer_id: str | None = None):
    async with transaction() as session:
        query = select(Run).order_by(Run.created_at.desc()).limit(100)
        if customer_id:
            query = query.where(Run.customer_id == customer_id)
        return [await run_dict(session, run) for run in (await session.scalars(query)).all()]


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    async with transaction() as session:
        return await run_dict(session, await require_run(session, run_id))


@app.get("/api/runs/{run_id}/events")
async def events(
    run_id: str,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
):
    async with transaction() as session:
        await require_run(session, run_id)
    if last_event_id is not None:
        try:
            after = max(after, int(last_event_id))
        except ValueError as exc:
            raise DomainError("Last-Event-ID must be an integer.", 422) from exc

    async def stream():
        cursor = after
        while not await request.is_disconnected():
            async with transaction() as session:
                batch = (
                    await session.scalars(
                        select(Event)
                        .where(Event.run_id == run_id, Event.id > cursor)
                        .order_by(Event.id)
                        .limit(100)
                    )
                ).all()
            for event in batch:
                cursor = event.id
                data = json.dumps(jsonable_encoder(event_dict(event)), ensure_ascii=True)
                yield f"id: {event.id}\nevent: activity\ndata: {data}\n\n"
            if not batch:
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs/{run_id}/information")
async def information(run_id: str, body: Information):
    return await get_run(await continue_run(run_id, body))


@app.post("/api/runs/{run_id}/retry")
async def retry(run_id: str):
    return await get_run(await continue_run(run_id))


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    await cancel(run_id)
    return await get_run(run_id)


@app.get("/api/approvals")
async def approvals():
    async with transaction() as session:
        return [
            proposal_dict(p)
            for p in (
                await session.scalars(
                    select(Proposal)
                    .where(Proposal.status == "pending")
                    .order_by(Proposal.created_at)
                )
            ).all()
        ]


@app.post("/api/approvals/{proposal_id}/decision")
async def approval_decision(proposal_id: str, body: Decision):
    return await decide(proposal_id, body.decision)

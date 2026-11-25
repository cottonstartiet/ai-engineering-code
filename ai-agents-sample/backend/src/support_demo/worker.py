import asyncio
import logging
import time
from contextlib import suppress
from datetime import timedelta

from opentelemetry import context, propagate
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.trace import Status, StatusCode
from sqlalchemy import select

from support_demo.accounting import UsageLedger, ledger
from support_demo.asyncio_support import run
from support_demo.config import settings
from support_demo.db import Job, engine, now, transaction, uid
from support_demo.services import TERMINAL, append, require_run
from support_demo.telemetry import configure, duration, shutdown, span
from support_demo.workflows import execute_approved, investigate

logger = logging.getLogger("support_demo.worker")


async def recover() -> None:
    async with transaction() as session:
        expired = (
            await session.scalars(
                select(Job)
                .where(Job.status == "running", Job.lease_until < now())
                .with_for_update(skip_locked=True)
            )
        ).all()
        for job in expired:
            run = await require_run(session, job.run_id, lock=True)
            if job.kind == "execute" and run.status not in TERMINAL:
                job.status, job.owner = "queued", None
                await append(
                    session, run, "status", "Approved action recovered for safe execution."
                )
            else:
                job.status = "interrupted"
                if run.status == "running":
                    run.status = "interrupted"
                    run.result = {
                        "summary": "Investigation interrupted. Explicit retry is available."
                    }
                    await append(
                        session,
                        run,
                        "status",
                        run.result["summary"],
                        data={"status": "interrupted"},
                    )


async def claim() -> tuple[str, str, str, dict] | None:
    async with transaction() as session:
        job = await session.scalar(
            select(Job)
            .where(Job.status == "queued")
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        run = await require_run(session, job.run_id, lock=True)
        if run.status in TERMINAL:
            job.status = "cancelled"
            return None
        job.status, job.owner = "running", uid()
        job.lease_until = now() + timedelta(seconds=settings().job_lease_seconds)
        run.status = "running"
        await append(session, run, "status", "Worker started.", data={"status": "running"})
        return job.id, job.owner, job.run_id, run.trace_context


async def heartbeat(job_id: str, owner: str, work: asyncio.Task) -> None:
    while not work.done():
        await asyncio.sleep(5)
        async with transaction() as session:
            job = await session.get(Job, job_id)
            if job is None or job.owner != owner or job.status != "running":
                work.cancel()
                return
            run = await require_run(session, job.run_id)
            if run.status == "cancelled":
                work.cancel()
                return
            job.lease_until = now() + timedelta(seconds=settings().job_lease_seconds)


async def fail_owned_job(job_id: str, owner: str, status: str, result: dict) -> None:
    async with transaction() as session:
        job = await session.get(Job, job_id, with_for_update=True)
        if job is None or job.owner != owner or job.status != "running":
            return
        run = await require_run(session, job.run_id, lock=True)
        if run.status == "running":
            run.status, run.result = status, result
            await append(session, run, "error", result["summary"], data={"status": status})


async def process(job_id: str, owner: str, run_id: str, carrier: dict) -> None:
    token = context.attach(propagate.extract(carrier))
    accounting_token = ledger.set(UsageLedger())
    started = time.monotonic()
    try:
        with span("support.job", **{"support.run_id": run_id}) as active:
            async with transaction() as session:
                job = await session.get(Job, job_id)
                assert job is not None
                kind = job.kind
                run = await require_run(session, run_id, lock=True)
                run.trace_id = f"{active.get_span_context().trace_id:032x}"
            task = asyncio.create_task(
                execute_approved(run_id) if kind == "execute" else investigate(run_id)
            )
            monitor = asyncio.create_task(heartbeat(job_id, owner, task))
            try:
                async with asyncio.timeout(settings().investigation_timeout_seconds):
                    await task
            except asyncio.CancelledError:
                await fail_owned_job(
                    job_id,
                    owner,
                    "interrupted",
                    {
                        "summary": "Worker ownership was lost. Explicit retry may be required.",
                    },
                )
            except Exception as exc:
                active.set_status(Status(StatusCode.ERROR))
                active.set_attribute("error.type", type(exc).__name__)
                logger.error("Run %s failed [%s]", run_id, type(exc).__name__)
                await fail_owned_job(
                    job_id,
                    owner,
                    "failed",
                    {
                        "summary": "Investigation failed. Check configuration and correlated telemetry; "
                        "explicit retry is available.",
                        "error_type": type(exc).__name__,
                    },
                )
            finally:
                monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor
                async with transaction() as session:
                    job = await session.get(Job, job_id, with_for_update=True)
                    if job and job.owner == owner and job.status == "running":
                        run = await require_run(session, run_id, lock=True)
                        usage = ledger.get()
                        if usage is not None:
                            previous = (run.result or {}).get("usage", {})
                            if kind != "execute" or not previous:
                                run.result = {**(run.result or {}), "usage": usage.summary()}
                        job.status, job.lease_until = "done", None
    finally:
        duration.record(time.monotonic() - started)
        ledger.reset(accounting_token)
        context.detach(token)


async def serve() -> None:
    settings().require_azure()
    configure("support-worker")
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine, enable_commenter=False)
    active: set[asyncio.Task] = set()
    try:
        while True:
            for completed in [task for task in active if task.done()]:
                active.remove(completed)
                await completed
            await recover()
            job = await claim() if len(active) < settings().worker_concurrency else None
            if job is not None:
                active.add(asyncio.create_task(process(*job)))
            else:
                await asyncio.sleep(1)
    finally:
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        shutdown()
        await engine.dispose()


if __name__ == "__main__":
    run(serve())

import asyncio
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://support:support-local-demo@127.0.0.1:55432/support_test",
)
os.environ.setdefault("TELEMETRY_ENABLED", "false")
os.environ.setdefault("DATA_DIRECTORY", str(Path(__file__).resolve().parents[2] / "data"))
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/openai/v1")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "synthetic-test-key")
os.environ.setdefault("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "test-embedding")
os.environ.setdefault("EMBEDDING_DIMENSIONS", "8")

from support_demo.db import Base, engine, transaction  # noqa: E402
from support_demo.seed import index_policies, seed_data  # noqa: E402


@pytest.fixture(scope="session")
def observed():
    from agent_framework.observability import enable_instrumentation
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    enable_instrumentation(enable_sensitive_data=False)
    yield exporter
    provider.shutdown()


@pytest.fixture
async def database(monkeypatch):
    if not engine.url.database or not engine.url.database.endswith("_test"):
        raise RuntimeError("Integration tests require a dedicated database ending in _test")

    async def fake_embed(texts):
        return [[1.0, 0.1, 0.2, 0.1, 0.0, 0.1, 0.1, 0.1] for _ in texts]

    monkeypatch.setattr("support_demo.seed.embed", fake_embed)
    monkeypatch.setattr("support_demo.retrieval.embed", fake_embed)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await seed_data()
        await index_policies()
        yield
    finally:
        await engine.dispose()


@pytest.fixture
async def active_return(database):
    from support_demo.contracts import RunInput
    from support_demo.services import create_run, require_run

    key = await create_run(
        RunInput(
            customer_id="customer-1",
            desk="returns",
            message="My headphones have a broken left speaker. Refund please.",
            order_id="ORD-1003",
            item_id="ITEM-1003",
            reason="defective: broken left speaker",
        )
    )
    async with transaction() as session:
        run = await require_run(session, key, lock=True)
        run.status = "running"
    return key

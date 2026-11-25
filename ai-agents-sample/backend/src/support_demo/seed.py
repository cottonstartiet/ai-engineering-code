import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from support_demo.asyncio_support import run
from support_demo.config import settings
from support_demo.db import Customer, IndexConfig, Order, Policy, engine, now, transaction
from support_demo.retrieval import embed
from support_demo.telemetry import configure, shutdown


def load_json(relative: str) -> list[dict]:
    return json.loads((Path(settings().data_directory) / relative).read_text(encoding="utf-8"))


async def seed_data() -> None:
    async with transaction() as session:
        for key, name in (("customer-1", "Alex (demo)"), ("customer-2", "Sam (demo)")):
            if await session.get(Customer, key) is None:
                session.add(Customer(id=key, name=name))
        await session.flush()
        definitions = [
            ("1001", "customer-1", "delivered", 2, "Headphones", 8999, 1),
            ("1002", "customer-1", "in_transit", None, "Monitor", 24999, 1),
            ("1003", "customer-1", "delivered", 10, "Headphones", 8999, 1),
            ("1004", "customer-1", "delivered", 5, "Speaker", 4999, 2),
            ("1005", "customer-1", "delivered", 45, "Keyboard", 6999, 1),
            ("1006", "customer-1", "delivered", 8, "Mouse", 2999, 1),
            ("2001", "customer-2", "delivered", 3, "Webcam", 5999, 1),
        ]
        for suffix, customer, status, days, name, cents, quantity in definitions:
            key = f"ORD-{suffix}"
            if await session.get(Order, key) is not None:
                continue
            delivered = now() - timedelta(days=days) if days is not None else None
            session.add(
                Order(
                    id=key,
                    customer_id=customer,
                    status=status,
                    delivered_at=delivered,
                    details={
                        "promised_date": (now() - timedelta(days=3)).date().isoformat(),
                        "tracking": [
                            {
                                "status": status,
                                "at": (delivered or now()).isoformat(),
                                "detail": "Synthetic delivery scan; not proof of receipt."
                                if delivered
                                else "Delayed at regional depot. No confirmed revised ETA.",
                            }
                        ],
                        "items": [
                            {
                                "id": f"ITEM-{suffix}",
                                "name": name,
                                "quantity": quantity,
                                "unit_price_cents": cents,
                                "resolved_quantity": 1 if suffix == "1006" else 0,
                            }
                        ],
                    },
                )
            )


async def index_policies(reindex: bool = False) -> None:
    config = settings()
    config.require_azure()
    async with transaction() as session:
        current = await session.get(IndexConfig, "policies")
        if (
            current
            and (
                current.dimensions != config.embedding_dimensions
                or current.model != config.azure_openai_embedding_deployment
            )
            and not reindex
        ):
            raise ValueError("Embedding configuration changed. Explicitly run setup --reindex.")
    for source in load_json("policies/policies.json"):
        digest = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
        async with transaction() as session:
            existing = await session.get(Policy, source["id"])
            unchanged = (
                existing is not None
                and existing.content_hash == digest
                and existing.embedding_model == config.azure_openai_embedding_deployment
                and existing.embedding is not None
                and not reindex
            )
        if unchanged:
            continue
        vector = (await embed([source["text"]]))[0]
        async with transaction() as session:
            existing = await session.get(Policy, source["id"])
            row = existing or Policy(id=source["id"])
            row.title, row.desk, row.text = source["title"], source["desk"], source["text"]
            row.version, row.rules = source["version"], source["rules"]
            row.effective_at = datetime(2020, 1, 1, tzinfo=UTC)
            row.content_hash, row.embedding_model, row.embedding = (
                digest,
                config.azure_openai_embedding_deployment,
                vector,
            )
            session.add(row)
    async with transaction() as session:
        all_policies = (await session.scalars(select(Policy))).all()
        if any(
            p.embedding is None or len(p.embedding) != config.embedding_dimensions
            for p in all_policies
        ):
            raise ValueError("Mixed embedding dimensions; reindex all policies")
        await session.merge(
            IndexConfig(
                id="policies",
                model=config.azure_openai_embedding_deployment,
                dimensions=config.embedding_dimensions,
            )
        )


async def setup(reindex: bool = False) -> None:
    await seed_data()
    await index_policies(reindex)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reindex", action="store_true")
    args = parser.parse_args()
    configure("support-setup")

    async def execute() -> None:
        try:
            await setup(args.reindex)
        finally:
            shutdown()
            await engine.dispose()

    run(execute())


if __name__ == "__main__":
    main()

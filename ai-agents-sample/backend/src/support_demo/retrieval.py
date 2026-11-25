import asyncio

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from sqlalchemy import func, select

from support_demo.config import settings
from support_demo.contracts import Citation, DomainError
from support_demo.db import IndexConfig, Policy, now, transaction
from support_demo.telemetry import retries, retrieval_hits, span


def azure_client() -> AsyncOpenAI:
    config = settings()
    config.require_azure()
    return AsyncOpenAI(
        base_url=config.azure_base_url,
        api_key=config.azure_openai_api_key.get_secret_value(),
        max_retries=0,
        timeout=30,
    )


async def embed(texts: list[str]) -> list[list[float]]:
    config = settings()
    with span("policy.embed", **{"embedding.batch_size": len(texts)}):
        async with azure_client() as client:
            for attempt in range(config.transient_retries + 1):
                try:
                    response = await client.embeddings.create(
                        model=config.azure_openai_embedding_deployment,
                        input=texts,
                        dimensions=config.embedding_dimensions,
                    )
                    vectors = [entry.embedding for entry in response.data]
                    if len(vectors) != len(texts) or any(
                        len(vector) != config.embedding_dimensions for vector in vectors
                    ):
                        raise ValueError(
                            "Embedding response dimensions/count do not match configuration"
                        )
                    return vectors
                except (APIConnectionError, APIStatusError) as exc:
                    transient = isinstance(exc, (APIConnectionError, RateLimitError)) or (
                        isinstance(exc, APIStatusError) and exc.status_code >= 500
                    )
                    if not transient or attempt == config.transient_retries:
                        raise
                    retries.add(1, {"operation": "embedding"})
                    await asyncio.sleep(min(2**attempt, 4))
    raise RuntimeError("Embedding request exhausted without result")


async def search_policies(query: str, desk: str) -> list[Citation]:
    with span("policy.search", desk=desk):
        vector = (await embed([query]))[0]
        async with transaction() as session:
            config = await session.get(IndexConfig, "policies")
            if (
                config is None
                or config.model != settings().azure_openai_embedding_deployment
                or config.dimensions != settings().embedding_dimensions
            ):
                raise DomainError("Policy index is missing/incompatible. Run setup --reindex.", 503)
            distance = Policy.embedding.cosine_distance(vector)
            vector_rows = (
                await session.execute(
                    select(Policy, distance.label("distance"))
                    .where(
                        Policy.desk == desk,
                        Policy.effective_at <= now(),
                        Policy.embedding.is_not(None),
                    )
                    .order_by(distance)
                    .limit(5)
                )
            ).all()
            lexical = (
                await session.scalars(
                    select(Policy)
                    .where(
                        Policy.desk == desk,
                        Policy.effective_at <= now(),
                        func.to_tsvector("english", Policy.text).op("@@")(
                            func.plainto_tsquery("english", query)
                        ),
                    )
                    .limit(5)
                )
            ).all()
            scores: dict[str, float] = {}
            policies: dict[str, Policy] = {}
            qualified = [policy for policy, d in vector_rows if 1 - float(d) >= config.threshold]
            for ranking in (qualified, list(lexical)):
                for rank, policy in enumerate(ranking):
                    scores[policy.id] = scores.get(policy.id, 0) + 1 / (60 + rank + 1)
                    policies[policy.id] = policy
            selected = sorted(scores, key=lambda key: scores[key], reverse=True)[:4]
            retrieval_hits.record(len(selected), {"desk": desk})
            return [
                Citation(id=key, title=policies[key].title, text=policies[key].text)
                for key in selected
            ]

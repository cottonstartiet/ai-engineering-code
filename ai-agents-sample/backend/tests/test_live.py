import os

import pytest

from support_demo.agents import assess, model_client

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AZURE_CHAT") != "1",
    reason="Opt in with RUN_LIVE_AZURE_CHAT=1 and Azure settings",
)
async def test_live_azure_responses_and_structured_maf_output():
    from support_demo.accounting import UsageLedger, ledger

    usage = UsageLedger()
    token = ledger.set(usage)
    try:
        async with model_client() as client:
            result = await assess(
                client,
                "Synthetic smoke test: no order or evidence exists. Return outcome clarify, "
                "summary 'Order needed', question 'Which order?', empty citations. Do not propose action.",
            )
            assert result.outcome == "clarify" and result.question and not result.citations
            assert usage.calls > 0
    finally:
        ledger.reset(token)


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AZURE_EMBEDDINGS") != "1",
    reason="Opt in with RUN_LIVE_AZURE_EMBEDDINGS=1 and a real embedding deployment",
)
async def test_live_azure_embeddings():
    from support_demo.retrieval import embed

    vectors = await embed(["Synthetic defective product policy."])
    assert len(vectors) == 1


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AZURE_GROUP") != "1",
    reason="Opt in with RUN_LIVE_AZURE_GROUP=1; makes multiple Azure model/tool calls",
)
async def test_live_azure_group_chat_and_custom_tools():
    import asyncio

    from support_demo.agents import build_delivery_group

    called = set()

    async def order_facts() -> dict:
        """Return the selected synthetic customer's order facts."""
        called.add("order")
        return {
            "id": "SYNTHETIC-ORDER",
            "status": "delivered",
            "items": [{"id": "SYNTHETIC-ITEM", "quantity": 1}],
        }

    async def tracking_facts() -> dict:
        """Return synthetic tracking and explicit customer confirmation."""
        called.add("tracking")
        return {
            "tracking": "Delivered yesterday; scan is not proof of receipt.",
            "delivery_checks_confirmed": True,
        }

    async def policy_evidence() -> list[dict]:
        """Return the applicable delivery policy with its stable citation ID."""
        called.add("policy")
        return [
            {
                "id": "delivery-missing",
                "text": "Missing shipments reported within 7 days, after confirmed household and "
                "safe-location checks, may receive a human-approved replacement or refund.",
            }
        ]

    async with model_client() as client:
        workflow = build_delivery_group(
            client,
            [order_facts, tracking_facts, policy_evidence],
            max_rounds=6,
        )
        async with asyncio.timeout(120):
            result = await workflow.run(
                "Synthetic support request: SYNTHETIC-ORDER / SYNTHETIC-ITEM is marked delivered "
                "yesterday but missing. Customer confirmed household and safe-location checks. "
                "Investigate using your tools, have all specialists contribute, cite the policy, "
                "and recommend a replacement for human approval. Do not execute anything.",
            )
        assert result.get_outputs() and called == {"order", "tracking", "policy"}

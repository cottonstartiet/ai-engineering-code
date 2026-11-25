from agent_framework import ChatResponse

from support_demo.accounting import UsageLedger


def test_missing_usage_is_not_reported_as_zero():
    ledger = UsageLedger()
    ledger.record(ChatResponse())
    assert ledger.summary()["input_tokens"] is None
    assert ledger.summary()["estimated_cost_usd"] is None


def test_reported_usage_is_aggregated_and_pricing_is_explicit(monkeypatch):
    from support_demo.config import settings

    monkeypatch.setattr(settings(), "input_price_per_million", 2)
    monkeypatch.setattr(settings(), "output_price_per_million", 4)
    ledger = UsageLedger()
    ledger.record(ChatResponse(usage_details={"input_token_count": 100, "output_token_count": 50}))
    ledger.record(ChatResponse(usage_details={"input_token_count": 200, "output_token_count": 100}))
    assert ledger.summary() == {
        "model_calls": 2,
        "reported_calls": 2,
        "usage_complete": True,
        "input_tokens": 300,
        "output_tokens": 150,
        "estimated_cost_usd": 0.0012,
    }

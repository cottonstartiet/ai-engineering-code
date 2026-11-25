from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from support_demo.config import Settings
from support_demo.contracts import RunInput
from support_demo.db import Order, Policy, Run
from support_demo.domain import evaluate

AT = datetime(2026, 11, 23, tzinfo=UTC)


def objects(age=30, quantity=1, desk="returns", reason="defective: broken speaker"):
    order = Order(
        id="order",
        customer_id="customer",
        status="delivered",
        delivered_at=AT - timedelta(days=age),
        details={"items": [{"id": "item", "quantity": 2, "unit_price_cents": 4999}]},
    )
    run = Run(
        customer_id="customer",
        desk=desk,
        request={
            "item_id": "item",
            "quantity": quantity,
            "reason": reason,
        },
    )
    policy_id = "returns-30-day" if desk == "returns" else "delivery-missing"
    policies = {
        policy_id: Policy(
            id=policy_id,
            effective_at=AT - timedelta(days=365),
            rules={
                "window_days": 30 if desk == "returns" else 7,
                "reasons": ["defective", "damaged"],
            },
        )
    }
    return run, order, policies


def test_window_inclusive_and_partial_refund_exact_cents():
    result = evaluate(*objects(), 1, "refund", at=AT)
    assert result.eligible and result.amount_cents == 4999
    assert not evaluate(*objects(age=31), 0, "refund", at=AT).eligible


def test_previously_resolved_quantities_and_customer_scoping():
    assert not evaluate(*objects(quantity=2), 1, "refund", at=AT).eligible
    run, order, policies = objects()
    run.customer_id = "another-customer"
    assert not evaluate(run, order, policies, 0, "refund", at=AT).eligible


def test_missing_description_and_authoritative_policy_cannot_be_bypassed():
    assert not evaluate(*objects(reason="defective"), 0, "refund", at=AT).eligible
    run, order, _ = objects()
    assert not evaluate(run, order, {}, 0, "refund", at=AT).eligible


def test_delivery_requires_explicit_customer_checks_and_valid_window():
    args = objects(age=2, desk="delivery")
    assert not evaluate(*args, 0, "replacement", at=AT).eligible
    assert evaluate(
        *args,
        0,
        "replacement",
        at=AT,
        checked_delivery_locations=True,
    ).eligible
    assert not evaluate(
        *objects(age=8, desk="delivery"),
        0,
        "replacement",
        at=AT,
        checked_delivery_locations=True,
    ).eligible


def test_configuration_accepts_resource_endpoint_or_full_v1_url():
    root = Settings(azure_openai_endpoint="https://example.services.ai.azure.com")
    full = Settings(azure_openai_endpoint="https://example.services.ai.azure.com/openai/v1")
    assert root.azure_base_url == full.azure_base_url
    with pytest.raises(ValidationError):
        RunInput(customer_id="c", desk="returns", message="help", quantity=0)

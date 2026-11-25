from datetime import UTC, datetime

from support_demo.contracts import Eligibility
from support_demo.db import Order, Policy, Run, now


def evaluate(
    run: Run,
    order: Order,
    policies: dict[str, Policy],
    resolved_quantity: int,
    action: str,
    *,
    checked_delivery_locations: bool = False,
    at: datetime | None = None,
) -> Eligibility:
    request = run.request
    item = next((i for i in order.details["items"] if i["id"] == request.get("item_id")), None)
    if order.customer_id != run.customer_id or item is None:
        return Eligibility(eligible=False, reason="Order/item is not available for this customer.")
    if action not in ("refund", "replacement"):
        return Eligibility(eligible=False, reason="Unsupported resolution action.")
    remaining = item["quantity"] - item.get("resolved_quantity", 0) - resolved_quantity
    quantity = request["quantity"]
    if quantity <= 0 or quantity > remaining:
        return Eligibility(
            eligible=False, reason="Requested quantity is already resolved or unavailable."
        )
    if order.delivered_at is None or order.status != "delivered":
        return Eligibility(
            eligible=False, reason="Shipment is not delivered; manual review is required."
        )
    date = (at or now()).astimezone(UTC).date()
    age = (date - order.delivered_at.astimezone(UTC).date()).days
    policy_id = "returns-30-day" if run.desk == "returns" else "delivery-missing"
    policy = policies.get(policy_id)
    if policy is None or policy.effective_at > (at or now()):
        return Eligibility(eligible=False, reason="No applicable authoritative policy; escalate.")
    if age < 0 or age > policy.rules["window_days"]:
        return Eligibility(eligible=False, reason="Outside the applicable policy window; escalate.")
    if run.desk == "returns":
        reason = request.get("reason", "").lower()
        if not any(
            reason.startswith(prefix + ":") and reason.split(":", 1)[1].strip()
            for prefix in policy.rules["reasons"]
        ):
            return Eligibility(
                eligible=False,
                reason="Supply a reason as 'defective: description' or 'damaged: description'.",
            )
    elif not checked_delivery_locations:
        return Eligibility(
            eligible=False, reason="Customer must confirm household/safe-location checks."
        )
    return Eligibility(
        eligible=True,
        reason="Eligible subject to human approval.",
        amount_cents=item["unit_price_cents"] * quantity if action == "refund" else 0,
        policy_id=policy_id,
    )

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Desk = Literal["delivery", "returns"]
Action = Literal["refund", "replacement"]
Status = Literal[
    "queued",
    "running",
    "awaiting_customer",
    "awaiting_approval",
    "completed",
    "escalated",
    "rejected",
    "cancelled",
    "interrupted",
    "failed",
]


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: str = Field(min_length=1, max_length=80)
    desk: Desk
    message: str = Field(min_length=1, max_length=4000)
    order_id: str | None = Field(default=None, max_length=80)
    item_id: str | None = Field(default=None, max_length=80)
    reason: str | None = Field(default=None, max_length=1000)
    quantity: int = Field(default=1, ge=1, le=20)
    delivery_checks_confirmed: bool = False


class Information(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    order_id: str | None = Field(default=None, max_length=80)
    item_id: str | None = Field(default=None, max_length=80)
    reason: str | None = Field(default=None, max_length=1000)
    quantity: int | None = Field(default=None, ge=1, le=20)
    delivery_checks_confirmed: bool | None = None


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]


class Citation(BaseModel):
    id: str
    title: str
    text: str


class Assessment(BaseModel):
    outcome: Literal["propose", "clarify", "escalate", "inform"]
    summary: str
    question: str = ""
    action: Action = "refund"
    citations: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    order: dict
    policies: list[Citation]


class Eligibility(BaseModel):
    eligible: bool
    reason: str
    amount_cents: int = 0
    policy_id: str = ""


class DomainError(Exception):
    def __init__(self, detail: str, status_code: int = 409) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)

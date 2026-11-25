from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass

from agent_framework import ChatContext, ChatMiddleware, ChatResponse, ResponseStream

from support_demo.config import settings


@dataclass
class UsageLedger:
    calls: int = 0
    reported_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def record(self, response: ChatResponse) -> None:
        self.calls += 1
        usage = response.usage_details or {}
        incoming, outgoing = usage.get("input_token_count"), usage.get("output_token_count")
        if incoming is not None and outgoing is not None:
            self.reported_calls += 1
            self.input_tokens += incoming
            self.output_tokens += outgoing

    def summary(self) -> dict:
        complete = self.calls > 0 and self.calls == self.reported_calls
        config = settings()
        cost = None
        if (
            complete
            and config.input_price_per_million is not None
            and config.output_price_per_million is not None
        ):
            cost = (
                self.input_tokens * config.input_price_per_million
                + self.output_tokens * config.output_price_per_million
            ) / 1_000_000
        return {
            "model_calls": self.calls,
            "reported_calls": self.reported_calls,
            "usage_complete": complete,
            "input_tokens": self.input_tokens if complete else None,
            "output_tokens": self.output_tokens if complete else None,
            "estimated_cost_usd": cost,
        }


ledger: ContextVar[UsageLedger | None] = ContextVar("usage_ledger", default=None)


class UsageAccounting(ChatMiddleware):
    async def process(self, context: ChatContext, call_next: Callable[[], Awaitable[None]]) -> None:
        await call_next()
        current = ledger.get()
        if current is None:
            return
        if isinstance(context.result, ResponseStream):
            context.result = context.result.with_result_hook(current.record)
        elif isinstance(context.result, ChatResponse):
            current.record(context.result)

import json

from agent_framework import (
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    Message,
    ResponseStream,
)

from support_demo.contracts import Assessment


class ScriptedClient(BaseChatClient):
    """Test-only model responses routed through real MAF agents and workflows."""

    STORES_BY_DEFAULT = True

    def __init__(self):
        super().__init__()
        self.selections = 0
        self.calls = 0

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        if not any(message.role in {"user", "assistant", "tool"} for message in messages):
            raise ValueError("Responses API requires non-empty input, including on repeated turns")
        self.calls += 1
        fmt = options.get("response_format")
        name = getattr(fmt, "__name__", "")
        if name == "AgentOrchestrationOutput":
            speakers = [
                "OrderSpecialist",
                "OrderSpecialist",
                "DeliverySpecialist",
                "PolicySpecialist",
            ]
            done = self.selections >= len(speakers)
            output = {
                "terminate": done,
                "reason": "Evidence reviewed",
                "next_speaker": None if done else speakers[self.selections],
                "final_message": "Recommend replacement with delivery-missing policy.",
            }
            self.selections += 1
            text = json.dumps(output)
        elif fmt is Assessment:
            delivery = any("delivery-missing" in m.text for m in messages)
            output = {
                "outcome": "propose",
                "summary": "Policy-supported resolution requires review.",
                "action": "replacement" if delivery else "refund",
                "citations": ["delivery-missing" if delivery else "returns-30-day"],
            }
            text = json.dumps(output)
        else:
            text = "Reviewed synthetic evidence. Policy supports a resolution subject to review."

        async def response():
            return ChatResponse(
                messages=[Message("assistant", [text])],
                response_id=f"response-{self.calls}",
            )

        async def updates():
            yield ChatResponseUpdate(
                contents=[Content.from_text(text)],
                role="assistant",
                response_id=f"response-{self.calls}",
                message_id=f"message-{self.calls}",
            )

        if stream:
            return ResponseStream(updates(), finalizer=ChatResponse.from_updates)
        return response()

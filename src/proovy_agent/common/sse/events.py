"""SSE event type definitions."""

from typing import Literal

from pydantic import BaseModel

EventType = Literal[
    "page_start",
    "solve_progress",
    "token",
    "tool_start",
    "tool_result",
    "image_placeholder",
    "image_result",
    "node_result",
    "credit_settled",
    "error",
]


class SSEEvent(BaseModel):
    event: EventType
    data: dict

    def to_sse(self) -> dict:
        """Return dict compatible with sse-starlette ServerSentEvent."""
        import json

        return {"event": self.event, "data": json.dumps(self.data, ensure_ascii=False)}

"""SSE 이벤트 타입 정의."""

import json
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
        """sse-starlette ServerSentEvent 호환 dict를 반환한다."""
        return {"event": self.event, "data": json.dumps(self.data, ensure_ascii=False)}

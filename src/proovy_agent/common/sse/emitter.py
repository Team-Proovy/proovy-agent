"""SSE event emitter."""

import asyncio

from proovy_agent.common.sse.events import EventType, SSEEvent


class SSEEmitter:
    """Collects SSE events and streams them via an async queue."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue()

    async def emit(self, event: EventType, data: dict) -> None:
        """Enqueue an event for streaming."""
        await self._queue.put(SSEEvent(event=event, data=data))

    async def close(self) -> None:
        """Signal stream end."""
        await self._queue.put(None)

    async def stream(self):
        """Yield sse-starlette-compatible dicts until closed."""
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield item.to_sse()

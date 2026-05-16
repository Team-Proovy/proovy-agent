"""SSE 이벤트 이미터."""

import asyncio
from collections.abc import AsyncIterator
import logging

from proovy_agent.common.sse.events import EventType, SSEEvent

logger = logging.getLogger(__name__)

_QUEUE_MAX_SIZE = 256


class SSEEmitter:
    """비동기 큐를 통해 SSE 이벤트를 수집하고 스트리밍한다."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        self._closed: bool = False
        self._close_lock: asyncio.Lock = asyncio.Lock()

    async def emit(self, event: EventType, data: dict) -> None:
        """이벤트를 큐에 추가한다. close() 이후에는 무시한다."""
        async with self._close_lock:
            if self._closed:
                logger.debug("emit() 무시됨 — 이미 닫힌 이미터 (event=%s)", event)
                return
            await self._queue.put(SSEEvent(event=event, data=data))

    async def close(self) -> None:
        """스트림 종료를 알리는 sentinel을 큐에 삽입한다."""
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            await self._queue.put(None)

    async def stream(self) -> AsyncIterator[dict[str, str]]:
        """sentinel(None)을 받을 때까지 sse-starlette 호환 dict를 yield한다."""
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield item.to_sse()

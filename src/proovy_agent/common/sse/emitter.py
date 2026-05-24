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
        # 락 해제 후 non-blocking put — 큐 가득 차면 드롭 (best-effort 정책)
        try:
            self._queue.put_nowait(SSEEvent(event=event, data=data))
        except asyncio.QueueFull:
            logger.warning("SSE 큐 포화 — 이벤트 드롭 (event=%s)", event)

    async def close(self) -> None:
        """스트림 종료를 알리는 sentinel을 큐에 삽입한다."""
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
        # 락 밖에서 동기적으로 드레인 후 sentinel 삽입 — 큐 포화로 인한 블로킹 없음
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._queue.put_nowait(None)

    async def stream(self) -> AsyncIterator[dict[str, str]]:
        """sentinel(None)을 받을 때까지 sse-starlette 호환 dict를 yield한다."""
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield item.to_sse()

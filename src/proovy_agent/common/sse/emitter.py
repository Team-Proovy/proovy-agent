"""SSE 이벤트 이미터."""

import asyncio
from collections.abc import AsyncIterator
import contextlib
import logging

from pydantic import BaseModel, ValidationError

from proovy_agent.common.sse.context import EmitContext, current_emit_context
from proovy_agent.common.sse.events import (
    CreditSettledEvent,
    CreditSettledPayload,
    DoneEvent,
    DonePayload,
    ErrorEvent,
    ErrorPayload,
    ImagePlaceholderEvent,
    ImagePlaceholderPayload,
    ImageResultEvent,
    ImageResultPayload,
    NodeResultEvent,
    NodeResultPayload,
    PageStartEvent,
    PageStartPayload,
    SolveProgressEvent,
    SolveProgressPayload,
    TokenEvent,
    TokenPayload,
    ToolResultEvent,
    ToolResultPayload,
    ToolStartEvent,
    ToolStartPayload,
    _EnvelopeBase,
    to_sse,
)

logger = logging.getLogger(__name__)

_QUEUE_MAX_SIZE = 256

# payload 클래스 → envelope 클래스 매핑
_PAYLOAD_TO_ENVELOPE: dict[type[BaseModel], type[_EnvelopeBase]] = {
    PageStartPayload: PageStartEvent,
    SolveProgressPayload: SolveProgressEvent,
    TokenPayload: TokenEvent,
    ToolStartPayload: ToolStartEvent,
    ToolResultPayload: ToolResultEvent,
    ImagePlaceholderPayload: ImagePlaceholderEvent,
    ImageResultPayload: ImageResultEvent,
    NodeResultPayload: NodeResultEvent,
    CreditSettledPayload: CreditSettledEvent,
    ErrorPayload: ErrorEvent,
    DonePayload: DoneEvent,
}

# 종료 신호 — QueueFull이어도 드롭하지 않고 자리를 만들어 전달한다.
# 이게 유실되면 클라이언트가 정상/오류 종료를 인지하지 못한다.
_TERMINAL_PAYLOADS = (DonePayload, ErrorPayload)


class SSEEmitter:
    """비동기 큐를 통해 SSE 이벤트를 수집하고 스트리밍한다."""

    def __init__(self, thread_id: str) -> None:
        self._thread_id = thread_id
        self._seq = 0
        self._queue: asyncio.Queue[_EnvelopeBase | None] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        self._closed: bool = False
        self._close_lock: asyncio.Lock = asyncio.Lock()

    async def emit(self, payload: BaseModel) -> None:
        """payload를 envelope으로 감싸 큐에 넣는다. 절대 raise하지 않는다 (best-effort).

        seq 증가·envelope 생성·enqueue를 모두 close_lock 임계구역 안에서 처리한다.
        enqueue가 락 밖에 있으면 그 사이 close()가 sentinel을 먼저 넣어, 승인된
        이벤트가 sentinel 뒤로 밀려 stream()에서 영원히 소비되지 않을 수 있다.
        """
        ctx = current_emit_context.get() or EmitContext()
        async with self._close_lock:
            if self._closed:
                logger.debug(
                    "emit() 무시됨 — 이미 닫힌 이미터 (payload=%s)", type(payload).__name__
                )
                return
            seq = self._seq
            self._seq += 1

            try:
                envelope_cls = _PAYLOAD_TO_ENVELOPE[type(payload)]
                event = envelope_cls(
                    thread_id=self._thread_id,
                    seq=seq,
                    step_idx=ctx.step_idx,
                    node=ctx.node,
                    payload=payload,
                )
            except (KeyError, ValidationError) as exc:
                # 코드 버그 — ERROR 로그 후 드롭. seq는 이미 소비됨(클라이언트 gap 감지)
                # payload 본문(사용자 입력·모델 출력)은 로그에 남기지 않고 타입만 기록한다
                logger.error(
                    "SSE payload 검증 실패 — 이벤트 드롭 (seq=%d, payload_type=%s): %s",
                    seq,
                    type(payload).__name__,
                    exc,
                )
                return

            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                if isinstance(payload, _TERMINAL_PAYLOADS):
                    # 종료 신호는 드롭 금지 — 가장 오래된 이벤트 1개를 버리고 자리를 만든다
                    with contextlib.suppress(asyncio.QueueEmpty):
                        self._queue.get_nowait()
                    with contextlib.suppress(asyncio.QueueFull):
                        self._queue.put_nowait(event)
                    logger.warning(
                        "SSE 큐 포화 — terminal 이벤트 보존 위해 1건 evict (type=%s, seq=%d)",
                        event.type,
                        seq,
                    )
                else:
                    logger.warning("SSE 큐 포화 — 이벤트 드롭 (type=%s, seq=%d)", event.type, seq)

    async def close(self) -> None:
        """스트림 종료 sentinel(None)을 큐에 넣는다. 기존 이벤트는 드레인하지 않는다."""
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            # 큐가 가득 차면 가장 오래된 이벤트 1개를 버리고 sentinel을 보장한다
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            self._queue.put_nowait(None)

    async def stream(self) -> AsyncIterator[dict[str, str]]:
        """sentinel(None)을 받을 때까지 sse-starlette 호환 dict를 yield한다."""
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield to_sse(item)

# SSE 스트리밍 Payload 구조 설계 v1

> **대상 위치**: `src/proovy_agent/common/sse/`, `src/proovy_agent/app/schemas/events.py`
> **연관 모듈**: `SSEEmitter`, `SSEEvent`, `EventType`, `solve.py` 엔드포인트
> **상태**: 제안 (제안 → 채택은 PR 머지 시점 기준)

---

## 0. 핵심 원칙

| 원칙 | 설명 |
|------|------|
| **한 이벤트 = 한 JSON 객체** | `data` 필드는 항상 단일 JSON 직렬화 문자열로 전송. 멀티라인 `data:` 금지 |
| **공통 envelope + payload 분리** | 모든 이벤트가 동일한 메타 필드(`type`, `thread_id`, `seq`, `ts`)를 갖고, 이벤트별 본문은 `payload`에 격리 |
| **best-effort 전달** | 큐 포화 시 이벤트 드롭 가능. 정합성은 messages durable store가 책임짐 (issue #9 방향) |
| **재연결 친화** | `id`(Last-Event-ID 복구용) + `thread_id` + `seq` 3중 식별자로 클라이언트가 중복/누락 판단 가능 |
| **타입 안전성** | `EventType` Literal과 Pydantic `discriminated union`으로 payload 스키마 강제 |

---

## 1. 현재 구조 한계

`src/proovy_agent/common/sse/events.py` 현재 구조:

```python
class SSEEvent(BaseModel):
    event: EventType  # Literal 10종 (done 도입 전)
    data: dict        # 자유 dict — 노드마다 키 다름
```

문제:
- `data` 스키마가 emit 호출 지점마다 달라 클라이언트가 모든 분기를 알아야 함
  - `token` → `{"content": str}`
  - `solve_progress` → `{"text": str}`
  - `tool_result` → `{"name": str, "output": str, "success": bool}`
  - `error` → `{"message": str}` 또는 `{"name": str, "message": str}`
- 재연결 복구용 `id`, 시퀀스 보장용 `seq`, 서버 시점 `ts` 없음
- LangGraph 병렬 브랜치(video/pdf)가 동시에 emit할 때 클라이언트가 어느 브랜치/스텝 이벤트인지 구분 불가

---

## 2. 권장 Envelope 스키마

모든 이벤트는 동일한 envelope을 따른다. `payload`만 이벤트 타입별로 다르다.

```jsonc
{
  "type": "token",              // EventType — discriminator
  "thread_id": "th-abc-123",    // 풀이 세션 ID (input.md의 requestId 역할)
  "seq": 42,                    // 0부터 단조 증가, 이벤트당 +1
  "ts": "2026-05-25T08:14:00.123Z",  // ISO8601 UTC
  "step_idx": 0,                // 현재 실행 중인 plan step index (병렬 브랜치 식별용)
  "node": "core_solver",        // emit한 노드 이름 (디버깅/필터링용)
  "payload": { ... }            // 이벤트별 본문
}
```

추가 SSE 프레임 필드:
- `event: <type>` — SSE 헤더, 클라이언트 `EventSource.addEventListener(type, ...)` 호환
- `id: <thread_id>:<seq>` — `Last-Event-ID` 복구 키. `:` 구분자로 thread_id와 seq 분리
- `retry: 3000` — 최초 응답에 1회만 전송, 클라이언트 재연결 지연 권장값

직렬화 예시:

```text
event: token
id: th-abc-123:42
data: {"type":"token","thread_id":"th-abc-123","seq":42,"ts":"2026-05-25T08:14:00.123Z","step_idx":0,"node":"core_solver","payload":{"delta":"안녕"}}

```

---

## 3. 이벤트 타입별 payload 스키마

`EventType` 11종을 4개 카테고리로 분류한다. 각 payload는 Pydantic `BaseModel` 서브클래스로 정의해 타입 안전성을 보장한다 (§4.3 discriminated union).

**중복 제거 원칙**: envelope에 이미 있는 필드(`thread_id`, `node`, `step_idx`, `seq`, `ts`)는 payload에서 제외한다. payload는 "그 이벤트의 본문"만 담는다.

### 3.1 Lifecycle — 세션 경계 이벤트

| event | 발생 시점 | payload 스키마 |
|---|---|---|
| `page_start` | planner가 plan 확정 직후 | `{"plan": [PlanStep], "selected_model": str, "difficulty": str, "route": str, "use_page": bool}` |
| `credit_settled` | 모든 노드 종료, credit_settler에서 | `{"reserved": float, "actual": float, "refunded": float, "log": [CreditEntry]}` |
| `error` | 노드/도구 실패 시 | `{"code": ErrorCode, "message": str, "recoverable": bool, "tool_call_id": str \| null}` |
| `done` *(신규)* | 그래프 실행 완료 직후 (성공 경로 only) | `{"final": true}` |

- `done`은 클라이언트가 정상 종료를 EventSource `onerror`(연결 끊김)에 의존하지 않고 명시적으로 인지할 수 있게 추가한다. 에러/취소 경로에서는 emit 되지 않는다 (§5.3 참조).
- `credit_settled.total`은 `reserved/actual/refunded` 3분할로 대체. 환불 UX와 디버깅에 필요한 정보를 명시한다.
- `error.code`는 Literal로 좁힌다: `internal_error | tool_error | model_error | credit_exhausted | timeout | invalid_input`.

### 3.2 Progress — 진행 상태 이벤트

| event | 발생 시점 | payload 스키마 |
|---|---|---|
| `solve_progress` | core_solver iteration 단위 | `{"text": str, "iteration": int, "phase": "verify" \| "explain"}` |
| `node_result` | 각 노드 종료 직후 | `{"status": "done" \| "error", "duration_ms": int, "error_code": str \| null}` |

`node_result.node` 필드는 제거 — envelope의 `node`가 단일 소스다.

### 3.3 Streaming — 토큰 증분 이벤트

| event | 발생 시점 | payload 스키마 |
|---|---|---|
| `token` | LLM 스트리밍 chunk마다 | `{"delta": str, "final": false}` |

input.md의 권장 스키마와 일치시켜 `content` → `delta`로 키 이름 변경. 마지막 chunk는 `final: true`로 표시해 클라이언트가 버퍼 flush 시점을 알 수 있게 한다.

### 3.4 Tool & Media — 도구 실행 / 시각 자료

| event | 발생 시점 | payload 스키마 |
|---|---|---|
| `tool_start` | 도구 호출 직전 | `{"name": str, "label": str, "tool_call_id": str}` |
| `tool_result` | 도구 호출 종료 직후 | `{"name": str, "tool_call_id": str, "output": str, "success": bool}` |
| `image_placeholder` | 이미지 생성 시작 시 | `{"placeholder_id": str, "label": str}` |
| `image_result` | 이미지 생성 완료 시 | `{"placeholder_id": str, "url": str, "width": int, "height": int, "mime_type": str}` |

- `tool_call_id`는 LangGraph `ToolMessage.tool_call_id`와 매칭해 start↔result 쌍을 명확히 한다.
- 도구 emit 시점에도 envelope.node는 step 책임 노드(`core_solver` 등)로 유지하고, 도구 식별은 `name`이 담당한다 (§5.4 참조).
- `image_result.mime_type`은 PNG/SVG/WebP 분기를 위한 클라이언트 디코딩 힌트. 기본값 `"image/png"`.

---

## 4. Pydantic 모델 구조

`src/proovy_agent/common/sse/events.py`를 다음 구조로 확장한다. 각 이벤트는 `type` 필드를 discriminator로 갖는 envelope이며, `payload` 필드는 타입별 모델로 강제된다 (§0 원칙 이행).

### 4.1 EventType과 ErrorCode

```python
from datetime import UTC, datetime
from typing import Annotated, Literal
from pydantic import BaseModel, Field

EventType = Literal[
    "page_start", "solve_progress", "token",
    "tool_start", "tool_result",
    "image_placeholder", "image_result",
    "node_result", "credit_settled",
    "error", "done",
]

ErrorCode = Literal[
    "internal_error", "tool_error", "model_error",
    "credit_exhausted", "timeout", "invalid_input",
]
```

### 4.2 Payload 모델 (10종)

```python
# state.py에서 import
# from proovy_agent.graph.state import PlanStep, CreditEntry

# --- Lifecycle ---
class PageStartPayload(BaseModel):
    plan: list[PlanStep]
    selected_model: Literal["flash", "sonnet", "opus"]
    difficulty: Literal["easy", "medium", "hard"]
    route: Literal["general_chat", "math_task"]
    use_page: bool


class CreditSettledPayload(BaseModel):
    reserved: float            # 예약된 양 (state.credit_reserved)
    actual: float              # 실제 소비 합계 (sum of log.cost)
    refunded: float            # max(reserved - actual, 0)
    log: list[CreditEntry]


class ErrorPayload(BaseModel):
    code: ErrorCode = "internal_error"
    message: str
    recoverable: bool = False
    tool_call_id: str | None = None   # 도구 오류일 때만


class DonePayload(BaseModel):
    final: Literal[True] = True


# --- Progress ---
class SolveProgressPayload(BaseModel):
    text: str
    iteration: int = 0
    phase: Literal["verify", "explain"] = "verify"


class NodeResultPayload(BaseModel):
    status: Literal["done", "error"]
    duration_ms: int
    error_code: str | None = None    # status == "error"일 때만 채움


# --- Streaming ---
class TokenPayload(BaseModel):
    delta: str
    final: bool = False


# --- Tool & Media ---
class ToolStartPayload(BaseModel):
    name: str
    label: str
    tool_call_id: str = ""


class ToolResultPayload(BaseModel):
    name: str
    tool_call_id: str = ""
    output: str
    success: bool


class ImagePlaceholderPayload(BaseModel):
    placeholder_id: str
    label: str


class ImageResultPayload(BaseModel):
    placeholder_id: str
    url: str
    width: int
    height: int
    mime_type: str = "image/png"
```

### 4.3 Envelope — discriminated union

각 (type, payload) 쌍을 별도 envelope 클래스로 묶고, `type` 필드를 discriminator로 union한다. 잘못된 조합(예: `type="token"`인데 `payload`가 `ToolResultPayload`)은 Pydantic이 거절한다.

```python
class _EnvelopeBase(BaseModel):
    thread_id: str
    seq: int
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    step_idx: int = 0
    node: str = ""


class TokenEvent(_EnvelopeBase):
    type: Literal["token"] = "token"
    payload: TokenPayload


class SolveProgressEvent(_EnvelopeBase):
    type: Literal["solve_progress"] = "solve_progress"
    payload: SolveProgressPayload


class PageStartEvent(_EnvelopeBase):
    type: Literal["page_start"] = "page_start"
    payload: PageStartPayload


class ToolStartEvent(_EnvelopeBase):
    type: Literal["tool_start"] = "tool_start"
    payload: ToolStartPayload


class ToolResultEvent(_EnvelopeBase):
    type: Literal["tool_result"] = "tool_result"
    payload: ToolResultPayload


class ImagePlaceholderEvent(_EnvelopeBase):
    type: Literal["image_placeholder"] = "image_placeholder"
    payload: ImagePlaceholderPayload


class ImageResultEvent(_EnvelopeBase):
    type: Literal["image_result"] = "image_result"
    payload: ImageResultPayload


class NodeResultEvent(_EnvelopeBase):
    type: Literal["node_result"] = "node_result"
    payload: NodeResultPayload


class CreditSettledEvent(_EnvelopeBase):
    type: Literal["credit_settled"] = "credit_settled"
    payload: CreditSettledPayload


class ErrorEvent(_EnvelopeBase):
    type: Literal["error"] = "error"
    payload: ErrorPayload


class DoneEvent(_EnvelopeBase):
    type: Literal["done"] = "done"
    payload: DonePayload


SSEEvent = Annotated[
    TokenEvent | SolveProgressEvent | PageStartEvent
    | ToolStartEvent | ToolResultEvent
    | ImagePlaceholderEvent | ImageResultEvent
    | NodeResultEvent | CreditSettledEvent
    | ErrorEvent | DoneEvent,
    Field(discriminator="type"),
]


def to_sse(event: SSEEvent) -> dict[str, str]:
    """sse-starlette ServerSentEvent 호환 dict."""
    return {
        "event": event.type,
        "id": f"{event.thread_id}:{event.seq}",
        "data": event.model_dump_json(),
    }
```

### 4.4 EmitContext

ContextVar로 `node`/`step_idx`를 전파한다 (§5.1 참조). PlanExecutor만 set/reset 책임을 가지며, 노드/도구 코드는 emit 호출만 한다.

```python
# src/proovy_agent/common/sse/context.py
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class EmitContext:
    node: str = ""
    step_idx: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


current_emit_context: ContextVar[EmitContext] = ContextVar(
    "current_emit_context",
    default=EmitContext(),
)
```

- `started_at`: `NodeResultPayload.duration_ms` 자동 계산용. PlanExecutor가 step 종료 시 `(now - ctx.started_at)` 으로 계산해 emit.
- `node`는 **현재 step의 책임 노드**(`core_solver`, `video_solver`, ...). 도구 호출 시에도 갈아끼우지 않으며, 도구 식별은 `ToolStartPayload.name`이 담당한다.
- asyncio.Task 격리로 LangGraph 병렬 브랜치(video/pdf)는 자동으로 독립된 EmitContext를 갖는다.

---

## 5. SSEEmitter 변경 사항

emit 호출부는 **payload만 넘긴다**. `type`/`thread_id`/`seq`/`ts`는 emitter가 자동 계산하고, `node`/`step_idx`는 `current_emit_context` ContextVar에서 자동 주입된다.

### 5.1 변경 전 vs 변경 후

```python
# 변경 전 (현재)
await emitter.emit("token", {"content": chunk_content})

# 변경 후
await emitter.emit(TokenPayload(delta=chunk_content))
```

이벤트 타입은 payload 클래스 → envelope 클래스 매핑으로 결정된다.

### 5.2 SSEEmitter 내부 구현

```python
class SSEEmitter:
    def __init__(self, thread_id: str) -> None:
        self._thread_id = thread_id
        self._seq = 0
        self._queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        self._closed: bool = False
        self._close_lock: asyncio.Lock = asyncio.Lock()

    async def emit(self, payload: BaseModel) -> None:
        """이벤트를 큐에 추가한다. 절대 raise하지 않는다 (§0 best-effort)."""
        async with self._close_lock:
            if self._closed:
                logger.debug("emit() 무시됨 — 이미 닫힌 이미터")
                return
            seq = self._seq
            self._seq += 1

        ctx = current_emit_context.get()

        try:
            envelope_cls = _PAYLOAD_TO_ENVELOPE[type(payload)]
            sse_event = envelope_cls(
                thread_id=self._thread_id,
                seq=seq,
                step_idx=ctx.step_idx,
                node=ctx.node,
                payload=payload,
            )
        except (KeyError, ValidationError) as exc:
            # 코드 버그 — ERROR 로그 후 드롭. seq는 이미 소비됨 (gap 신호)
            logger.error(
                "SSE payload 검증 실패 — 이벤트 드롭 (seq=%d, payload=%r): %s",
                seq, payload, exc,
            )
            return

        try:
            self._queue.put_nowait(sse_event)
        except asyncio.QueueFull:
            logger.warning(
                "SSE 큐 포화 — 이벤트 드롭 (type=%s, seq=%d)",
                sse_event.type, seq,
            )


# payload 클래스 → envelope 클래스 매핑 (4.3에서 정의된 envelope들로)
_PAYLOAD_TO_ENVELOPE: dict[type[BaseModel], type[BaseModel]] = {
    TokenPayload: TokenEvent,
    SolveProgressPayload: SolveProgressEvent,
    PageStartPayload: PageStartEvent,
    ToolStartPayload: ToolStartEvent,
    ToolResultPayload: ToolResultEvent,
    ImagePlaceholderPayload: ImagePlaceholderEvent,
    ImageResultPayload: ImageResultEvent,
    NodeResultPayload: NodeResultEvent,
    CreditSettledPayload: CreditSettledEvent,
    ErrorPayload: ErrorEvent,
    DonePayload: DoneEvent,
}
```

### 5.3 실패 모드별 처리 (§0 best-effort 원칙)

| 실패 모드 | 처리 | 로그 레벨 | seq |
|---|---|---|---|
| 큐 포화 (`QueueFull`) | 드롭 | WARNING | **소비됨** (클라이언트가 gap 감지 → durable store 재조회 트리거) |
| payload 검증 실패 (`ValidationError`, 미등록 클래스) | 드롭 | ERROR (코드 버그 신호) | **소비됨** |
| close 후 호출 | 무시 | DEBUG | 미증가 |

**emit()은 절대 raise하지 않는다**. 한 emit의 실패가 풀이 로직을 중단시키면 안 된다. ERROR 레벨로 모니터링 가능하되 사용자 영향은 0.

### 5.4 `done` event emit 흐름

`done`은 **성공 경로에서만** 명시적으로 emit한다. close()는 sentinel만 책임진다.

```python
# solve.py (개념적)
async def _run() -> None:
    token = current_emitter.set(emitter)
    try:
        await get_graph().ainvoke(state)
        await emitter.emit(DonePayload())                # ← 성공 시에만
    except asyncio.CancelledError:
        # 클라이언트 이미 끊김 — done/error 둘 다 안 보냄
        raise
    except Exception as exc:
        logger.exception("solve 실행 중 오류")
        if not getattr(exc, "sse_emitted", False):
            await emitter.emit(ErrorPayload(
                code="internal_error",
                message="풀이 중 오류가 발생했습니다.",
            ))
    finally:
        await emitter.close()                            # sentinel만 (done은 안 보냄)
        current_emitter.reset(token)
```

| 종료 경로 | 클라이언트가 받는 마지막 이벤트 | sentinel |
|---|---|---|
| 정상 완료 | `done` | 그 후 큐에 None |
| 그래프 예외 | `error` | 그 후 큐에 None |
| 클라이언트 disconnect | (이미 끊김) | 큐에만 |

### 5.5 PlanExecutor의 EmitContext 책임

step별 set/reset과 `node_result` 자동 emit은 PlanExecutor 한 곳에 모은다. 노드 함수 내부에는 EmitContext 코드가 없다.

```python
# graph/executor.py (개념적)
async def execute_step(self, step_idx: int, step: PlanStep) -> None:
    node_name = self._node_for(step.action)   # "core_solver" / "video_solver" / "pdf_solver"
    ctx = EmitContext(node=node_name, step_idx=step_idx)
    token = current_emit_context.set(ctx)
    try:
        await self._invoke_node(step)
        duration_ms = int((datetime.now(UTC) - ctx.started_at).total_seconds() * 1000)
        await self._emitter.emit(NodeResultPayload(
            status="done",
            duration_ms=duration_ms,
        ))
    except Exception as exc:
        duration_ms = int((datetime.now(UTC) - ctx.started_at).total_seconds() * 1000)
        await self._emitter.emit(NodeResultPayload(
            status="error",
            duration_ms=duration_ms,
            error_code=type(exc).__name__,
        ))
        raise
    finally:
        current_emit_context.reset(token)
```

도구(`code_execute`, `code_generate`)는 EmitContext를 건드리지 않고 그대로 상속한다 — envelope.node는 `"core_solver"`로 유지, 도구 식별은 `ToolStartPayload.name`이 담당한다.

---

## 6. 하트비트와 재연결

### 6.1 하트비트

`SSEEmitter.stream()` 안에서 일정 주기(예: 15초)마다 SSE 코멘트 라인을 보낸다. sse-starlette은 `ping` 옵션을 제공하므로 별도 구현 없이 `EventSourceResponse(..., ping=15)`로 처리 가능하다.

### 6.2 재연결 — Last-Event-ID

클라이언트가 끊긴 뒤 재연결 시 `Last-Event-ID: <thread_id>:<seq>` 헤더로 마지막 본 seq를 전달한다. 별도 엔드포인트가 아니라 `/solve` 응답 흐름의 일부로 처리한다.

#### 6.2.1 클라이언트 동작

- EventSource 끊김 시 자동 재연결, 마지막 본 `id`를 `Last-Event-ID` 헤더에 자동 첨부 (브라우저 기본 동작)
- 재연결 후 받은 첫 이벤트의 `seq`가 `last_seq + 1`보다 크면 **gap 발생** — UI에 손실 경고 표시 (이벤트 일부 드롭됨을 사용자에게 알림)

#### 6.2.2 서버 contract (구현은 issue #9 messages durable store에서)

| # | 항목 | 동작 |
|---|---|---|
| 1 | **헤더 파싱** | `<thread_id>:<seq>` 형식. 불일치 시 200 OK + 새 세션 취급 (silent fallback) |
| 2 | **인증 검증** | 요청 user_id ↔ thread_id 소유자 매칭. 불일치 시 **403** (도청 방지) |
| 3 | **replay 단계** | store에서 `thread_id == X AND seq > last_seq`인 이벤트를 seq 순으로 즉시 일괄 전송 |
| 4 | **합류** | replay 종료 직후 실시간 큐 합류. replay 마지막 seq 이후 실시간 이벤트만 송신 |
| 5 | **재전송 윈도우** | 최대 **1시간**. 윈도우 밖 요청 시 가장 오래된 보존 이벤트부터 전송, 클라이언트가 gap 경고 표시 |
| 6 | **순서 보장** | replay → 실시간 전환 시 thread_id별 단조 증가 seq 유지. 이를 위해 store와 emitter가 **공통 seq counter**를 공유해야 함 (issue #9 설계) |

#### 6.2.3 issue #9에 위임할 항목

- store 백엔드 선택 (Redis Stream / Postgres / in-memory + persistence)
- replay 도중 새 emit 발생 시 race 처리 (lock vs append-only)
- seq counter 영속화 방식 (재기동 시 복구)
- 1시간 보존 윈도우의 정확한 GC 정책

---

## 7. 마이그레이션 절차

emit 호출부가 14군데로 한정적이므로 **호환성 shim 없이 단일 PR로 일괄 전환한다**. 점진 전환 코드(`data` vs `payload` 이중 직렬화, `BaseModel | dict` union 시그니처)의 복잡도가 전환 비용을 초과한다.

### 7.1 단일 PR 구성

| # | 변경 | 파일 |
|---|---|---|
| 1 | `events.py`에 10종 Payload + 11종 Envelope + discriminated union 정의 | `src/proovy_agent/common/sse/events.py` |
| 2 | `context.py`에 `EmitContext` + `current_emit_context` ContextVar 추가 | `src/proovy_agent/common/sse/context.py` |
| 3 | `emitter.py`: `__init__(thread_id)`, `emit(payload)` 새 시그니처, `_PAYLOAD_TO_ENVELOPE` 매핑 | `src/proovy_agent/common/sse/emitter.py` |
| 4 | PlanExecutor에 EmitContext set/reset + 자동 `node_result` emit 추가 | `src/proovy_agent/graph/executor.py` |
| 5 | 14개 emit 호출부를 새 Payload 모델로 일괄 전환 | `solve.py`, `code_generate.py`, `code_execute.py`, `general_node.py`, `planner.py`, `credit_settler.py`, `core_solver/agent.py` |
| 6 | `/solve` 엔드포인트에서 `SSEEmitter(thread_id=...)` 주입, 성공 경로 `DonePayload` emit | `src/proovy_agent/app/api/v1/solve.py` |
| 7 | 통합 테스트: envelope 형태, discriminator 검증, gap 신호, done emit 시점 | `tests/` |

### 7.2 프론트엔드 동시 배포

`event:` 헤더 이름은 동일하지만 `data` 내부 구조가 완전히 바뀐다 (`{type, thread_id, seq, ts, step_idx, node, payload: {...}}`). 백/프론트는 같은 release에 배포한다 — SSE는 connection-per-request이므로 백엔드 재기동 시점에 클라이언트도 새 연결을 맺어 자연스럽게 교체된다.

### 7.3 롤백 전략

- 단일 PR이므로 `git revert <merge-commit>`으로 즉시 롤백 가능
- 백엔드만 롤백할 경우 프론트엔드도 동시 롤백 필요 (envelope 호환 불가)

---

## 8. 추후 결정 사항

| 항목 | 상태 | 비고 |
|---|---|---|
| Last-Event-ID durable store | **contract 확정** (§6.2), 구현은 issue #9 | seq 영속화, 1h 윈도우, 공통 counter, 인증 검증 |
| 토큰 chunk 배칭 | **보류** | 측정 후 결정 — envelope 영향 0, emitter 내부만 변경 |
| TypeScript 클라이언트 SDK | **별도 트랙** | OpenAPI에서 discriminated union 자동 export 활용 |
| 클라이언트 gap UI | **이번 PR 범위 외** | §6.2 gap 감지 신호의 UX 처리 (경고 토스트 등) |

### 8.1 토큰 배칭 도입 trigger

다음 중 하나라도 충족 시 배칭 설계 재검토:

- 토큰 emit > 100/s 지속 (sustained)
- p50 SSE 페이로드 > 측정 임계 (TBD by 로그 분석)
- 모바일 클라이언트에서 frame drop 사용자 보고

배칭 도입 시에도 **첫 토큰(TTFB)은 무조건 즉시 송신**한다 — 사용자 체감 latency 보호.

### 8.2 클라이언트 SDK 자동 생성 경로

§4.3의 discriminated union 구조 덕분에 OpenAPI 스키마는 `oneOf` + `discriminator: { propertyName: "type" }`로 export된다. TypeScript SDK는 이를 입력으로:

1. payload 타입 자동 생성 (`TokenPayload`, `ToolStartPayload`, ...)
2. discriminated union (`type SSEEvent = TokenEvent | ...`) 자동 생성
3. EventSource 래퍼가 `event:` 헤더 → 타입 좁히기 (TypeScript narrowing)

별도 트랙으로 진행하며 이번 PR 범위 외.

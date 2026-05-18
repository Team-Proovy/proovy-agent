# Daytona 샌드박스 계층 설계 v13

> **대상 위치**: `src/proovy_agent/common/sandbox/`
> **Daytona SDK**: `daytona` (v0.173, Python, Async)
> **이번 작업 범위**: common/sandbox/ 계층만 구현. 도구/노드 구현은 별도 작업.

---

## 0. 핵심 원칙 — 1 Turn = 1 Sandbox

샌드박스는 **1회 API 요청(1 Turn) 동안만 존재하는 일회용 자원**입니다.

| 원칙 | 설명 |
|------|------|
| **턴 단위 수명** | 요청 시작 시 생성, 응답 완료 시 삭제. 턴 간 재사용 없음 |
| **DB 저장 금지** | `sandbox_id`, `executor_status` 등을 LangGraph State(=DB)에 영구 저장하지 않음 |
| **메모리 전용** | sandbox 상태는 `RequestExecutorContext`(메모리)에서만 관리 |
| **문맥 연속성** | sandbox는 초기화되지만, 대화 기록(Chat History)이 DB에 있으므로 대화는 자연스럽게 이어짐 |
| **최후 보루** | 서버 장애로 삭제 실패 시 Daytona `auto_stop`(5분)이 자동 정리 |

---

## 1. 역할과 구현 범위

sandbox 계층은 **실행 프리미티브만 제공**합니다. 도구/노드는 별도 개발.

| 사용처 | Daytona 기능 | 이번 구현 | 추후 구현 |
|--------|-------------|:-:|:-:|
| **수학 검증** | `code_interpreter.run_code` | ✅ `run_python()` | `code_execute` 도구 |
| **시각화** | `process.code_run` + charts | ⬜ 설계만 | 시각화 도구 |
| **영상 생성** | `process.exec` | ⬜ 설계만 | VideoNode |

---

## 2. 핵심 설계 결정

### 2.1. 실행 방식 선택

| | `code_interpreter.run_code` | `process.code_run` |
|---|---|---|
| **상태 유지** | ✅ context 내 변수/import 유지 | ❌ 매번 독립 |
| **스트리밍** | ✅ `on_stdout`/`on_stderr` 콜백 | ❌ 한 번에 반환 |
| **차트 감지** | ❌ | ✅ matplotlib 자동 추출 |

```
CoreSolver 검증 코드 → CodeInterpreter (상태 유지 + 스트리밍)  ← MVP 1차
시각화(matplotlib)  → process.code_run (차트 자동 추출)         ← 추후
영상 생성           → process.exec (셸 커맨드)                 ← 추후
```

### 2.2. CodeInterpreter 상태 유지 — 내부 편의용

같은 context에서 실행하면 이전 변수/import가 유지됩니다 (Jupyter와 동일).
**MVP에서는 내부 편의용으로만** 사용합니다 (사용자 노출 X).

#### 상태 오염(State Contamination) 방지

에이전트가 변수명 충돌이나 에러 루프에 빠질 수 있으므로,
**`reset_context()`로 context를 초기화**할 수 있는 복구 경로를 제공합니다.

### 2.3. 샌드박스 수명 전략

**요청별 생성/삭제** + 유형별 auto_stop/timeout 차등:

| 요청 유형 | auto_stop | code timeout | 이유 |
|----------|-----------|-------------|------|
| 수학 검증 (MVP) | 5분 | 60초 | 짧은 계산 |
| 시각화 (추후) | 5분 | 30초 | matplotlib 렌더링 |
| 영상 생성 (추후) | 15분 | 300초 | manim 렌더링 |

#### Sandbox 생성 시점 — SandboxGate 노드 (통과형)

Planner가 `code_needed` 플래그만 설정하고, **SandboxGate 노드**가 sandbox 생성을 트리거합니다.
SandboxGate는 **통과형(pass-through) 노드**로, 생성 완료를 기다리지 않고 즉시 다음 노드로 전달합니다.

```
Planner → SandboxGate → CoreSolver
              ↓ (side-effect, non-blocking)
              asyncio.create_task(create_executor())
```

**SandboxGate의 역할**:
1. `state.code_needed` 확인
2. `True` → `asyncio.create_task()` 발사 + SSE `preparing` 전송
3. `False` → 아무 것도 하지 않고 통과
4. **즉시 CoreSolver로 전달** (대기 없음, 실제 `await`는 `code_execute` Tool에서)

**비용 최적화**: 단순 질문에는 Planner가 `code_needed=False` → SandboxGate 통과 → sandbox 미생성 → 비용 0.

#### sandbox 상태 관리 — RequestExecutorContext (메모리 전용)

**sandbox 관련 모든 상태는 메모리(RequestExecutorContext)에서만 관리합니다.**
LangGraph State(=DB checkpoint)에는 sandbox 메타데이터를 저장하지 않습니다.

```python
from dataclasses import dataclass, field

@dataclass
class RequestExecutorContext:
    """1턴 동안만 메모리에 존재. 턴 종료 시 흔적 없이 소멸."""
    task: asyncio.Task[CodeExecutor] | None = None
    status: ExecutorStatus = ExecutorStatus.NONE
    error: str | None = None
    recovery_count: int = 0   # hybrid reset 횟수 추적
```

> **왜 State에 넣지 않는가?**
> LangGraph는 State를 DB에 checkpoint합니다. 다음 턴에서 `executor_status="ready"`를
> 복원하면 이미 삭제된 sandbox에 접근하려다 치명적 에러가 발생합니다.
> sandbox는 "1턴 일회용"이므로 메모리에서만 관리하는 것이 무결합니다.

### 2.4. 보안 정책

MVP: 기본 Daytona 격리 + 기본 제한. 실행 시간/출력 제한은 `SandboxConfig`로 오버라이드 가능.
Daytona SDK v0.173의 `CreateSandboxFromSnapshotParams`는 `resources` 필드를 지원하지 않으므로,
snapshot 기반 생성에서는 CPU/Memory/Disk를 런타임에 오버라이드하지 않습니다.

| 항목 | MVP 설정 | 이유 |
|------|---------|------|
| **네트워크** | `network_block_all=True` | 스냅샷에 패키지 사전 설치 |
| **실행 시간** | 유형별 timeout | 무한 루프 방지 |
| **stdout 버퍼** | 10,000자 제한 | OOM 방어 (무한 print 방지) |
| **리소스** | snapshot/provider 기본값 | SDK v0.173 snapshot 생성은 런타임 리소스 오버라이드 미지원 |

### 2.5. 도구 주입 — RunnableConfig + Request Context

SandboxGate가 `asyncio.Task`를 Request Context에 저장하고,
Tool은 RunnableConfig를 통해 Request Context에 접근합니다.

```python
# SandboxGate 노드에서:
req_ctx = config["configurable"]["request_context"]
req_ctx.task = asyncio.create_task(
    manager.create_executor(thread_id)
)
req_ctx.status = ExecutorStatus.CREATING
await sse.emit("sandbox_status", {"status": "preparing", ...})

# Tool 내부에서:
@tool
async def code_execute(code: str, config: RunnableConfig) -> str:
    req_ctx = config["configurable"]["request_context"]
    manager = config["configurable"]["sandbox_manager"]
    thread_id = config["configurable"].get("thread_id", "default")

    # Fallback: SandboxGate를 거치지 않은 경우 즉석 생성
    if req_ctx.task is None:
        req_ctx.task = asyncio.create_task(
            manager.create_executor(thread_id)
        )
        req_ctx.status = ExecutorStatus.CREATING

    executor = await req_ctx.task
    req_ctx.status = ExecutorStatus.READY
    result = await executor.run_python(code)

    # Hybrid reset: 상태 오염 감지 시 Tool 내부에서 자동 복구
    if result.recovery_hint == RecoveryHint.RESET_RECOMMENDED:
        req_ctx.recovery_count += 1
        if req_ctx.recovery_count <= 1:
            await executor.reset_context()
            return (
                f"❌ {result.error.name}: {result.error.value}\n"
                f"(환경 변수가 오염된 것으로 감지되어 샌드박스를 자동 초기화했습니다. "
                f"코드를 수정하여 다시 시도해주세요.)"
            )

    # 에러 포매팅: LLM이 에러 내용을 이해하고 수정할 수 있도록
    if not result.success:
        return f"❌ {result.error.name}: {result.error.value}\n{result.error.traceback}"

    # truncation 메시지는 executor.run_python() 내부에서 이미 처리됨
    return result.stdout
```

> **Tool이 모든 실행 로직을 캐슐화**: executor 접근, 실행, 에러 포매팅, recovery 처리까지
> Tool이 str을 반환하므로 Graph 노드는 `CodeExecutionResult`에 접근할 수 없음 → Tool 내부에서 처리가 필수

### 2.6. code_generate — 제거, 시스템 프롬프트로 대체

코드 작성 가이드라인(패키지 선택, 주의사항)은 `dynamic_prompt`에 포함합니다.
별도 도구 호출 불필요 → 비용 절감.

---

## 3. 디렉토리 구조

```
src/proovy_agent/common/sandbox/
├── __init__.py
├── client.py          # AsyncDaytona 싱글턴
├── manager.py         # SandboxManager: 생성/삭제/cancel-safe cleanup
├── executor.py        # CodeExecutor: 코드 실행 + 에러 분류
├── models.py          # 설정 + 결과 Pydantic 모델
└── exceptions.py      # 커스텀 예외
```

---

## 4. 상세 코드

### `exceptions.py`

```python
class SandboxError(Exception):
    """샌드박스 관련 기본 예외."""

class SandboxCreationError(SandboxError):
    """샌드박스 생성 실패."""

class SandboxUnavailableError(SandboxError):
    """checkpoint/resume 후 sandbox context가 사라진 경우."""

class CodeExecutionError(SandboxError):
    """코드 실행 실패 (런타임 에러 등)."""

class SandboxTimeoutError(CodeExecutionError):
    """코드 실행 타임아웃."""
```

### `models.py`

```python
from enum import Enum
from pydantic import BaseModel
from typing import Optional, Literal

# ── 설정 ──

class SandboxConfig(BaseModel):
    """sandbox 생성 시 설정. from_settings()로 생성 권장."""
    snapshot: str
    cpu: int = 2
    memory: int = 2
    disk: int = 5
    auto_stop_interval: int = 5
    code_timeout: int = 60
    max_output_chars: int = 10_000
    network_block_all: bool = True
    preamble_code: str = ""

    @classmethod
    def from_settings(cls, settings) -> "SandboxConfig":
        """settings에서 명시적으로 config를 생성. 테스트 시 mock settings 주입 가능."""
        return cls(
            snapshot=settings.DAYTONA_SNAPSHOT,
            cpu=settings.DAYTONA_SANDBOX_CPU,
            memory=settings.DAYTONA_SANDBOX_MEMORY,
            disk=settings.DAYTONA_SANDBOX_DISK,
            code_timeout=settings.DAYTONA_CODE_TIMEOUT,
            max_output_chars=settings.DAYTONA_MAX_OUTPUT_CHARS,
            preamble_code=get_whitelisted_preamble(settings.SANDBOX_PREAMBLE_NAME),
        )

# ── 에러 복구 힌트 (hybrid reset 지원) ──

class RecoveryHint(str, Enum):
    """CodeExecutor가 Graph에 전달하는 복구 제안."""
    NONE = "none"                    # 정상 실패, LLM이 스스로 수정
    RESET_RECOMMENDED = "reset_recommended"  # 상태 오염 의심, reset 권장
    UNRECOVERABLE = "unrecoverable"  # 재시도 불가

# ── 실행 결과 ──

class CodeError(BaseModel):
    name: str
    value: str
    traceback: str

class CodeExecutionResult(BaseModel):
    stdout: str
    stderr: str = ""
    error: Optional[CodeError] = None
    success: bool
    truncated: bool = False
    recovery_hint: RecoveryHint = RecoveryHint.NONE  # Executor가 분류한 복구 힌트

class ShellResult(BaseModel):
    stdout: str
    exit_code: int
    success: bool

# ── executor 상태 (RequestExecutorContext 전용, DB 저장 안 함) ──

class ExecutorStatus(str, Enum):
    NONE = "none"
    CREATING = "creating"
    READY = "ready"
    FAILED = "failed"
    CLEANED = "cleaned"
```

> `SandboxConfig`는 `default_factory` 대신 **`from_settings()` factory**를 사용합니다.
> 테스트 시 mock settings를 주입할 수 있고, 설정 누락을 즉시 감지합니다.
> `preamble_code`는 whitelist 기반 함수(`get_whitelisted_preamble`)를 통해서만 주입됩니다.

### `client.py`

```python
"""
앱 전체에서 공유하는 AsyncDaytona 인스턴스.
FastAPI lifespan에서 1회 초기화하여 Race Condition 방지.
"""
from daytona import AsyncDaytona, DaytonaConfig
from proovy_agent.common.config import settings

_client: AsyncDaytona | None = None

async def init_daytona_client() -> None:
    """FastAPI lifespan에서 앱 시작 시 1회 호출. Race condition 없음."""
    global _client
    config = DaytonaConfig(
        api_key=settings.DAYTONA_API_KEY,
        api_url=settings.DAYTONA_API_URL,
        target=settings.DAYTONA_TARGET,
    )
    _client = AsyncDaytona(config)

def get_daytona_client() -> AsyncDaytona:
    """초기화된 클라이언트 반환. lifespan 이후에만 호출."""
    if _client is None:
        raise RuntimeError("Daytona client not initialized. Call init_daytona_client() first.")
    return _client

async def close_daytona_client() -> None:
    """앱 종료 시 정리."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None

# FastAPI lifespan 예시:
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     await init_daytona_client()
#     yield
#     await close_daytona_client()
```

> **Race Condition 방지**: `get_daytona_client()`는 더 이상 async가 아닙니다.
> lifespan에서 1회 초기화하므로 동시 접근 문제가 없습니다.

### `manager.py`

```python
"""
그래프 실행 단위로 sandbox/executor를 생성/삭제합니다.
create_executor()는 sandbox 생성 + CodeExecutor 래핑을 한 번에 처리합니다.
"""
import asyncio
import logging
from daytona import AsyncDaytona, AsyncSandbox, CreateSandboxFromSnapshotParams
from .models import SandboxConfig
from .executor import CodeExecutor
from .exceptions import SandboxCreationError

logger = logging.getLogger(__name__)

class SandboxManager:
    def __init__(self, client: AsyncDaytona):
        self._client = client

    async def create_executor(
        self,
        thread_id: str,
        config: SandboxConfig | None = None,
    ) -> CodeExecutor:
        """
        sandbox 생성 + CodeExecutor 래핑을 한 번에 처리합니다.
        asyncio.create_task()로 호출하여 비동기 생성을 시작합니다.
        """
        from proovy_agent.common.config import settings
        cfg = config or SandboxConfig.from_settings(settings)
        try:
            params = CreateSandboxFromSnapshotParams(
                snapshot=cfg.snapshot,
                labels={"thread_id": thread_id},
                auto_stop_interval=cfg.auto_stop_interval,
                network_block_all=cfg.network_block_all,
            )
            sandbox = await self._client.create(params)
        except Exception as e:
            raise SandboxCreationError(f"Sandbox 생성 실패: {e}") from e

        return CodeExecutor(
            sandbox=sandbox,
            code_timeout=cfg.code_timeout,
            max_output_chars=cfg.max_output_chars,
            preamble_code=cfg.preamble_code,
        )

    async def destroy_executor(self, executor: CodeExecutor, *, timeout: float = 10.0) -> None:
        """
        cancel-safe cleanup: cleanup 실패와 무관하게 sandbox 삭제를 반드시 시도.
        전체 timeout을 두어 hang을 방지합니다.

        NOTE: sandbox.delete()는 SDK 버전에 따라 self._client.remove(sandbox)로
              대체될 수 있습니다. 구현 시 SDK 인터페이스를 반드시 검증하세요.
        """
        sandbox = executor.sandbox

        async def _destroy() -> None:
            try:
                await asyncio.wait_for(executor.cleanup(), timeout=3.0)
            except Exception as e:
                logger.exception(f"executor cleanup 실패: {e}")
            finally:
                # cleanup 실패와 무관하게 sandbox 삭제는 반드시 시도합니다.
                # caller cancellation이 들어와도 delete 작업 자체는 중단하지 않습니다.
                delete_task = asyncio.create_task(sandbox.delete())
                try:
                    await asyncio.wait_for(asyncio.shield(delete_task), timeout=5.0)
                except asyncio.CancelledError:
                    await asyncio.wait_for(delete_task, timeout=5.0)
                    raise
                except Exception as e:
                    logger.warning(f"Sandbox 삭제 실패 (auto_stop이 fallback): {e}")

        try:
            await asyncio.wait_for(_destroy(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(f"destroy_executor 전체 timeout ({timeout}초) — auto_stop이 처리")
```

### `executor.py`

```python
"""
Daytona sandbox 위에서 코드를 실행하는 통합 인터페이스.
MVP: run_python()만 구현. 에러 분류(recovery_hint)를 통해 Graph에 복구 제안 전달.
"""
import asyncio
import logging
from daytona import AsyncSandbox
from daytona.common.errors import DaytonaTimeoutError, DaytonaError
from .models import CodeExecutionResult, CodeError, ShellResult, SandboxConfig, RecoveryHint
from .exceptions import CodeExecutionError, SandboxTimeoutError

logger = logging.getLogger(__name__)

_DEFAULT_MAX_OUTPUT = 10_000

# 상태 오염 의심 에러 유형 (reset 권장)
_CONTAMINATION_ERRORS = {"NameError", "ImportError", "ModuleNotFoundError", "UnboundLocalError"}


class CodeExecutor:
    """
    하나의 그래프 실행(= 1문제) 동안 재사용되는 코드 실행기.

    - run_python(): CodeInterpreter로 Python 실행 (상태 유지)
    - reset_context(): 상태 오염 시 context 초기화 + preamble 재실행
    - cleanup(): 그래프 종료 시 리소스 정리
    """

    def __init__(
        self,
        sandbox: AsyncSandbox,
        code_timeout: int = 60,
        max_output_chars: int = _DEFAULT_MAX_OUTPUT,
        preamble_code: str = "",
    ):
        self._sandbox = sandbox
        self._code_timeout = code_timeout
        self._max_output_chars = max_output_chars
        self._preamble_code = preamble_code
        self._context = None  # InterpreterContext, lazy 생성
        self._lock = asyncio.Lock()  # 병렬 도구 호출 시 context 중복 생성 방지

    # ── Context 관리 ──

    async def _ensure_context(self):
        """격리된 interpreter context를 lazy 생성. Lock으로 race condition 방지.
        Preamble 실패 시 context를 None으로 롤백하여 dirty state를 방지합니다.
        """
        async with self._lock:
            if self._context is None:
                ctx = await self._sandbox.code_interpreter.create_context()
                self._context = ctx
                try:
                    await self._run_preamble()
                except Exception:
                    self._context = None  # preamble 실패 → 다음 호출 시 재생성 보장
                    raise
        return self._context

    async def _run_preamble(self) -> None:
        """preamble 코드(import 등)를 context에 실행합니다.
        실패 시 CodeExecutionError를 발생시켜 LLM이 자기 코드 탓으로 오해하지 않게 합니다.
        """
        if not self._preamble_code:
            return
        try:
            result = await self._sandbox.code_interpreter.run_code(
                code=self._preamble_code,
                context=self._context,
                timeout=30,
            )
            if result.error:
                raise CodeExecutionError(
                    f"Preamble 초기화 실패 (시스템 오류): {result.error.name}: {result.error.value}"
                )
            logger.debug("Preamble 코드 실행 완료")
        except DaytonaError as e:
            raise CodeExecutionError(f"Preamble 실행 중 시스템 오류: {e}") from e

    async def reset_context(self) -> None:
        """
        상태 오염 시 context를 초기화합니다.
        기존 context 삭제 → 새 context 생성 → preamble 재실행.
        Lock으로 run_python()과의 race condition을, timeout으로 hang을 방지합니다.
        """
        async with self._lock:
            if self._context:
                try:
                    await asyncio.wait_for(
                        self._sandbox.code_interpreter.delete_context(self._context),
                        timeout=5.0,
                    )
                except Exception as e:
                    logger.warning(f"Context 삭제 실패 (reset 중): {e}")
            self._context = await asyncio.wait_for(
                self._sandbox.code_interpreter.create_context(),
                timeout=10.0,
            )
            await self._run_preamble()
        logger.info("CodeExecutor context 초기화 완료 (preamble 재실행됨)")

    # ── 코드 실행 ──

    async def run_python(
        self,
        code: str,
        timeout: int | None = None,
    ) -> CodeExecutionResult:
        """
        Python 코드를 실행합니다. 같은 context 내에서 변수가 유지됩니다.

        Args:
            code: 실행할 Python 코드
            timeout: 타임아웃 (초). None이면 기본값 사용.

        Returns:
            CodeExecutionResult: stdout, stderr, error, success, truncated
        """
        ctx = await self._ensure_context()
        effective_timeout = timeout or self._code_timeout
        max_chars = self._max_output_chars

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        stdout_len = 0
        stderr_len = 0
        truncated = False

        def on_stdout(msg):
            nonlocal stdout_len, truncated
            if stdout_len < max_chars:
                stdout_chunks.append(getattr(msg, 'output', None) or getattr(msg, 'data', ''))
                stdout_len += len(stdout_chunks[-1])
            else:
                truncated = True

        def on_stderr(msg):
            nonlocal stderr_len
            if stderr_len < max_chars:
                stderr_chunks.append(getattr(msg, 'output', None) or getattr(msg, 'data', ''))
                stderr_len += len(stderr_chunks[-1])

        try:
            result = await self._sandbox.code_interpreter.run_code(
                code=code,
                context=ctx,
                on_stdout=on_stdout,
                on_stderr=on_stderr,
                timeout=effective_timeout,
            )
        except DaytonaTimeoutError as e:
            raise SandboxTimeoutError(
                f"코드 실행 시간 초과 ({effective_timeout}초)"
            ) from e
        except DaytonaError as e:
            raise CodeExecutionError(f"코드 실행 실패: {e}") from e

        error = None
        if result.error:
            error = CodeError(
                name=result.error.name,
                value=result.error.value,
                traceback=result.error.traceback,
            )

        stdout = "".join(stdout_chunks)
        if truncated:
            stdout = stdout[:max_chars] + f"\n... [출력이 {max_chars}자로 잘림]"

        return CodeExecutionResult(
            stdout=stdout,
            stderr="".join(stderr_chunks),
            error=error,
            success=result.error is None,
            truncated=truncated,
            recovery_hint=self._classify_error(error),
        )

    # ── 에러 분류 (hybrid reset 지원) ──

    @staticmethod
    def _classify_error(error: CodeError | None) -> RecoveryHint:
        """
        에러 유형을 분류하여 Graph에 복구 힌트를 전달합니다.
        Graph는 이 힌트를 보고 reset_context() 호출 여부를 결정합니다.
        """
        if error is None:
            return RecoveryHint.NONE
        if error.name in _CONTAMINATION_ERRORS:
            return RecoveryHint.RESET_RECOMMENDED
        return RecoveryHint.NONE

    # ── 추후 구현 ──

    async def run_shell(self, command: str, timeout: int = 120) -> ShellResult:
        """셸 커맨드 실행. VideoNode에서 manim/ffmpeg 등에 사용. (추후 구현)"""
        raise NotImplementedError("run_shell은 추후 구현 예정입니다.")

    # ── 정리 ──

    async def cleanup(self) -> None:
        """context를 정리합니다. 그래프 종료 시 호출."""
        if self._context:
            try:
                await self._sandbox.code_interpreter.delete_context(self._context)
            except Exception as e:
                logger.warning(f"Context 삭제 실패 (cleanup): {e}")
            self._context = None

    @property
    def sandbox(self) -> AsyncSandbox:
        """내부 sandbox 인스턴스 접근 (추후 확장용)."""
        return self._sandbox
```

---

## 5. 수명주기 — 1 Turn = 1 Sandbox

> **핵심**: sandbox는 **FastAPI 라우터의 `try/finally`** 에서 생성~삭제를 보장합니다.
> SSE 연결이 끊겨도 `anyio.CancelScope(shield=True)`로 cleanup을 보호합니다.

### 개념 코드 (FastAPI 라우터)

```python
async def handle_solve_request(request):
    manager = SandboxManager(get_daytona_client())
    req_ctx = RequestExecutorContext()  # 메모리 전용, 이 턴에서만 존재

    try:
        async for event in graph.astream(
            state,
            config={"configurable": {
                "request_context": req_ctx,
                "sandbox_manager": manager,  # Tool fallback용
            }},
        ):
            await sse.send(event)
    except SandboxError as e:
        # sandbox 생성/초기화/SDK 통신 실패 → 사용자에게 안내 (LLM이 해결할 수 없음)
        logger.error(f"샌드박스 오류: {e}")
        await sse.send(event="sandbox_status", data={
            "status": "failed",
            "message": "시스템 오류가 발생했어요. 다시 시도해 주세요 🔄"
        })
    except (asyncio.CancelledError, ConnectionResetError):
        logger.info("SSE 연결 끊김 — cleanup 진행")
        raise  # ASGI 서버에 취소 상태를 정상적으로 알리기 위해 재발생
    finally:
        # anyio.CancelScope: 이미 cancelled된 태스크에서도 cleanup 완료 보장
        # (asyncio.shield는 cancelled 태스크에서 await 시 즉시 CancelledError 재발생)
        with anyio.CancelScope(shield=True):
            await _cleanup_sandbox(req_ctx, manager)

async def _cleanup_sandbox(req_ctx, manager):
    """cancel-safe cleanup: 어떤 상황에서도 sandbox.delete를 시도."""
    if req_ctx.task is None:
        return
    try:
        executor = await asyncio.wait_for(req_ctx.task, timeout=5.0)
        await manager.destroy_executor(executor)  # cancel-safe (내부 timeout 10초)
    except asyncio.TimeoutError:
        req_ctx.task.cancel()
        logger.error("Executor task timeout — auto_stop이 처리")
    except SandboxCreationError:
        pass  # 생성 자체가 실패 → 정리할 것 없음
```

### 계층적 Cleanup 정책

| 계층 | 방식 | 타이밍 | 역할 |
|------|------|--------|------|
| **1차** | `anyio.CancelScope(shield=True)` + `destroy_executor` | finally 진입 시 | cancelled 상태에서도 cleanup 보장 |
| **2차** | `destroy_executor` 전체 timeout (10초) | destroy 내부 | hang 방지 |
| **3차** | Daytona auto_stop | 5분 후 | 서버 장애 시 최후 보루 |

### executor_status 상태 기계 (RequestExecutorContext 내부)

```
[*] → none
none → creating        (SandboxGate)
creating → ready       (Tool에서 await 성공)
creating → failed      (task 에러/cancel/timeout)
ready → cleaned        (cleanup 성공)
failed → cleaned       (best-effort cleanup)
cleaned → [*]          (턴 종료, 메모리에서 소멸)
```

### SSE `sandbox_status` 이벤트

```python
event: sandbox_status
data: {"status": "preparing", "message": "풀이 검증 환경을 준비하고 있어요..."}

event: sandbox_status
data: {"status": "ready", "message": "실행 환경 준비 완료"}

event: sandbox_status
data: {"status": "failed", "message": "풀이 검증 환경을 준비하지 못했어요. 다시 시도해 주세요 🔄"}
```

---

## 6. 환경 설정 (.env)

```bash
DAYTONA_API_KEY=your-api-key
DAYTONA_API_URL=https://app.daytona.io/api
DAYTONA_TARGET=us
DAYTONA_SNAPSHOT=proovy-math-sandbox
DAYTONA_SANDBOX_CPU=2
DAYTONA_SANDBOX_MEMORY=2
DAYTONA_SANDBOX_DISK=5
DAYTONA_CODE_TIMEOUT=60
DAYTONA_MAX_OUTPUT_CHARS=10000
SANDBOX_PREAMBLE_NAME=math_v1
```

---

## 7. 스냅샷 패키지 (`proovy-math-sandbox`)

`network_block_all=True`이므로 필요한 패키지를 모두 사전 포함.

```
# MVP: 수학 검증
sympy>=1.13
numpy>=1.26
scipy>=1.14

# 추후: 시각화
matplotlib>=3.9
pillow>=10.0

# 추후: 영상 생성
manim>=0.19
ffmpeg              # 시스템 패키지
```

---

## 8. 에러 처리

### 에러 분류

| 분류 | 예외 | 심각도 | 재시도 가능 |
|------|------|:------:|:---------:|
| **코드 런타임 에러** | `CodeExecutionResult.error` | 낮음 | ✅ LLM이 수정 |
| **타임아웃** | `SandboxTimeoutError` | 중간 | ✅ 코드 최적화 후 |
| **SDK 통신 에러** | `CodeExecutionError` | 높음 | ⚠️ 1회 재시도 |
| **sandbox 생성 실패** | `SandboxCreationError` | 치명적 | ❌ 사용자 에러 |
| **sandbox 삭제 실패** | 로그만 | 낮음 | - (auto_stop fallback) |

### 시나리오별 처리 흐름

#### 시나리오 1: 코드 런타임 에러 (가장 빈번)
```
LLM → code_execute("1/0") → executor.run_python()
  → result.error = {name: "ZeroDivisionError", value: "division by zero", traceback: "..."}
  → CodeExecutionResult(success=False, error=CodeError(...))
  → 도구 반환: "❌ ZeroDivisionError: division by zero\n[traceback]"
  → LLM이 코드 수정 후 재시도 (ReAct 루프)
```
> sandbox 계층은 예외를 던지지 않고 `CodeExecutionResult.error`에 담아 반환합니다.
> 이것은 "정상적인 실패"이므로 LLM이 스스로 처리할 수 있어야 합니다.

#### 시나리오 2: 타임아웃
```
LLM → code_execute(무한루프 코드) → executor.run_python()
  → DaytonaTimeoutError 발생
  → except DaytonaTimeoutError → raise SandboxTimeoutError
  → 도구 레벨에서 catch → "⏱️ 코드 실행 시간 초과 (60초). 코드를 최적화하세요."
  → LLM이 코드 재작성
```
> `SandboxTimeoutError`는 도구 레벨에서 catch하여 LLM에게 안내합니다.

#### 시나리오 3: 에러 루프 (hybrid reset — Tool 내부에서 처리)
```
LLM → code_execute(코드A) → 에러
  → CodeExecutor._classify_error() → recovery_hint = "reset_recommended"
  → Tool 내부에서 recovery_count 확인
  → recovery_count ≤ 1이면 executor.reset_context() 호출
  → LLM에게 "샌드박스 자동 초기화" 안내 + 코드 수정 요청
  → recovery_count > 1이면 일반 에러로 반환 (더 이상 reset 안 함)
```

```python
# code_execute Tool 내부 (hybrid reset 패턴)
result = await executor.run_python(code)

if result.recovery_hint == RecoveryHint.RESET_RECOMMENDED:
    req_ctx.recovery_count += 1  # 메모리에서만 추적 (DB 저장 금지)
    if req_ctx.recovery_count <= 1:
        await executor.reset_context()
        return f"❌ {result.error.name}: ... (샌드박스 자동 초기화됨)"

if not result.success:
    return f"❌ {result.error.name}: {result.error.value}\n{result.error.traceback}"
return result.stdout
```

> **hybrid 책임 분리**: CodeExecutor가 에러 유형을 분류(`recovery_hint`)하고,
> Tool이 정책적으로 reset을 승인(`recovery_count` 기반)합니다.
> Tool이 str을 반환하므로 Graph 노드에서는 `CodeExecutionResult`에 접근할 수 없어
> 복구 로직은 Tool 내부에서 처리합니다.
> 오염 분류 대상: `NameError`, `ImportError`, `ModuleNotFoundError`, `UnboundLocalError`

#### 시나리오 4: Sandbox 생성 실패 (치명적)
```
SandboxGate → sandbox 생성 요청
  → Daytona API 에러 (quota 초과, 네트워크 등)
  → SandboxCreationError 발생
  → 즉시 보상 cleanup 시도 (생성된 리소스가 있다면)
  → FastAPI finally에서 catch
  → 사용자에게 친근한 메시지 + 재시도 CTA:
    "풀이 검증 환경을 준비하는 중 문제가 발생했어요. 다시 시도해 주세요 🔄"
```
> 이 에러는 LLM이 해결할 수 없으므로 사용자에게 직접 전달합니다.
> 내부 오류 세부사항은 structured log에만 남기고 사용자에겐 노출하지 않습니다.

#### 시나리오 5: Sandbox 삭제 실패 (비치명적)
```
그래프 완료 → finally 블록
  → sandbox.delete() 실패
  → logger.warning("Sandbox 삭제 실패")
  → auto_stop_interval(5분) 후 자동 중지
  → auto_archive 후 자동 정리
```
> 삭제 실패는 비용이 약간 더 발생할 수 있지만 치명적이지 않습니다.

### exceptions.py에서의 처리 원칙

```python
# executor.py 내부:
#   DaytonaTimeoutError  → SandboxTimeoutError  (명시적 변환)
#   DaytonaError         → CodeExecutionError   (명시적 변환)
#   런타임 에러           → CodeExecutionResult.error (결과에 포함, 예외 아님)

# manager.py 내부:
#   sandbox 생성 실패     → SandboxCreationError (명시적 변환)
#   sandbox 삭제 실패     → logger.warning (예외 삼키기, auto_stop fallback)
```

---

## 9. 확정 사항

| 항목 | 결정 |
|------|------|
| **핵심 원칙** | 1 Turn = 1 Sandbox (턴 단위 생성/삭제, DB 저장 금지) |
| 이번 구현 | `run_python()`만. `run_shell()`, 시각화는 설계만 |
| **생성 트리거** | SandboxGate 노드 (통과형, fire-and-forget) |
| **상태 관리** | RequestExecutorContext(메모리) 전용. State(DB)에 sandbox 필드 없음 |
| **Cleanup** | `anyio.CancelScope(shield=True)` + cancel-safe `destroy_executor` (timeout 10초) |
| **상태 오염 복구** | hybrid: Executor가 recovery_hint 분류, Graph가 정책적 reset 승인 |
| 설정 | `SandboxConfig.from_settings()` factory |
| Preamble | whitelist 기반 `get_whitelisted_preamble()`로만 주입 |
| **UX 톤** | 친근한 진행 메시지 + 재시도 CTA, 기술 용어 미노출 |

---

## 10. MVP 검증 게이트 (구현 전 필수)

| 항목 | 내용 | 필수 |
|------|------|:---:|
| **SDK API 검증** | Daytona SDK v0.173 실제 호출 (create/run_code/delete 또는 remove 메서드명 확정) | ✅ |
| **Quota 확인** | Daytona 계정 quota, rate limit, 동시 생성 한도 확인 | ✅ |
| **Settings 검증** | config.py 필수 필드 존재 확인, from_settings() 동작 확인 | ✅ |
| **Preamble Whitelist** | preamble_code 출처 whitelist 정의 + 보안 검토 | ✅ |
| **통합 테스트** | sandbox 생성→실행→삭제 E2E + preamble 실패 시나리오 | ✅ |
| **Snapshot 문서화** | 빌드 스크립트 + 버전 관리 | ✅ |
| 관측 대시보드 | sandbox 사용량, 비용 모니터링 | ⬜ Phase 2 |

---

## 11. 향후 구현

| 단계 | 항목 | 이 계층과의 관계 |
|------|------|--------------|
| **Phase 1** | `code_execute` 도구 | `executor.run_python()` + recovery_hint 활용 |
| **Phase 1** | SandboxGate 노드 | `req_ctx.task = create_task(create_executor())` |
| **Phase 1** | CoreSolver 노드 | `req_ctx.task` await |
| **Phase 2** | 시각화 실행 | `process.code_run` + charts 메서드 추가 |
| **Phase 2** | VideoNode | `run_shell()` 구현 |
| **Phase 2** | Warm Pool | SandboxManager 확장 |
| **Phase 2** | Orphan Sweeper | auto_stop 보완 (장기 운영용) |
| **Phase 2** | `ephemeral=True` 전환 | sandbox stop 시 자동 삭제로 orphan 문제 근본 해결 |

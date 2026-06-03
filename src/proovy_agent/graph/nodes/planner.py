"""Planner 노드 — plan 생성 + 난이도 선택 (모델 매핑은 코드에서 관리)."""

from decimal import Decimal
import logging
from typing import Literal
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from proovy_agent.common.config import settings
from proovy_agent.common.llm.client import get_llm
from proovy_agent.common.sse.context import current_emitter
from proovy_agent.common.sse.events import ErrorPayload, PageStartPayload
from proovy_agent.features.credits import (
    CreditAccountNotFoundError,
    CreditHoldNotFoundError,
    CreditLedgerClient,
    InsufficientCreditsError,
    create_credit_ledger_client,
)
from proovy_agent.features.video.jobs import create_video_job_client
from proovy_agent.features.video.models import UserErrorCode, VideoJobStatus, user_error_message
from proovy_agent.graph.credit_pricing import estimate_plan_hold_amount, format_credit_amount
from proovy_agent.graph.runtime import current_credit_ledger_client, current_video_job_client
from proovy_agent.graph.state import CreditEntry, PlanStep, ProovyState

# difficulty → selected_model 매핑은 운영 정책이므로 코드에서 관리
_DIFFICULTY_TO_MODEL: dict[str, str] = {
    "easy": "flash",
    "medium": "sonnet",
    "hard": "opus",
}
logger = logging.getLogger(__name__)
_VIDEO_ONLY_HINTS = (
    "@해설영상",
    "해설영상",
    "해설 영상",
    "영상으로",
    "영상만",
    "동영상으로",
    "동영상만",
    "비디오로",
    "비디오만",
)
_FULL_INTENT_HINTS = (
    "풀이도",
    "풀이와",
    "풀이랑",
    "텍스트",
    "글로",
    "답도",
    "해설지도",
    "pdf",
    "함께",
    "같이",
    "둘 다",
    "둘다",
    "풀고",
)

_SYSTEM = """당신은 수학 문제 풀이 계획을 세우는 Planner입니다.
사용자 메시지를 분석하여 JSON 형식으로 풀이 계획을 작성하세요.

steps 결정 기준:
- 수학 문제 풀이 → action: "solve", description에 목표 명시
- 해설 영상 요청(@해설영상, "영상 만들어줘") → action: "video" (solve 완료 후 실행)
- 해설지 PDF 요청(@해설지, "해설지 만들어줘") → action: "pdf" (solve 완료 후 실행)

difficulty 기준:
- easy: 사칙연산, 간단한 대수
- medium: 방정식, 확률/통계 기초, 수열
- hard: 미적분, 선형대수, 고급 통계, 증명

explanation_mode 기준:
- "brief": 영상이 유일한 결과물인 요청. 예: "영상으로 설명해줘", "해설 영상 만들어줘", "영상만 보여줘"
- "full": 텍스트 풀이가 결과물인 요청. 예: "풀어줘", "자세히 설명해줘", "답 알려줘"
- 텍스트 풀이와 영상을 모두 원하는 요청 또는 모호한 요청은 반드시 "full"

use_page: 이미지·그래프·코드 포함 예상이면 true, 짧은 풀이면 false"""


class _StepInput(BaseModel):
    action: Literal["solve", "video", "pdf"]
    description: str


class _PlannerOutput(BaseModel):
    steps: list[_StepInput]
    difficulty: Literal["easy", "medium", "hard"]
    use_page: bool
    explanation_mode: Literal["full", "brief"] = "full"


class PlannerPreflightError(RuntimeError):
    """Raised when planner preflight rejects the request before execution."""


def _resolve_explanation_mode(
    requested: Literal["full", "brief"],
    plan: list[PlanStep],
    user_text: str = "",
) -> Literal["full", "brief"]:
    if requested == "brief" and any(step.action == "video" for step in plan):
        return "brief"
    if any(step.action == "video" for step in plan) and _is_video_only_request(user_text):
        return "brief"
    return "full"


def _content_to_text(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    return str(content)


def _latest_human_message(state: ProovyState) -> HumanMessage | None:
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            return msg
    return None


def _latest_human_text(state: ProovyState) -> str:
    msg = _latest_human_message(state)
    return _content_to_text(msg.content) if msg else ""


async def _raise_preflight_error(code: str, message: str) -> None:
    emitter = current_emitter.get()
    if emitter:
        await emitter.emit(ErrorPayload(code=code, message=message))
    exc = PlannerPreflightError(message)
    exc.sse_emitted = True  # type: ignore[attr-defined]
    raise exc


def _retry_action_payload(state: ProovyState) -> tuple[bool, str | None]:
    latest = _latest_human_message(state)
    if latest is None:
        return False, None
    if latest.additional_kwargs.get("action") != "video_retry":
        return False, None
    retry_source = latest.additional_kwargs.get("retry_source_job_id")
    if retry_source is None:
        return True, None
    retry_source_text = str(retry_source).strip()
    return True, retry_source_text or None


async def _preflight_video_retry(state: ProovyState) -> None:
    is_retry, retry_source_job_id = _retry_action_payload(state)
    if not is_retry:
        return
    if retry_source_job_id is None:
        await _raise_preflight_error(
            "invalid_input",
            user_error_message(UserErrorCode.INVALID_RETRY_SOURCE),
        )

    client = _get_video_job_client()
    if client is None:
        await _raise_preflight_error(
            "invalid_input",
            user_error_message(UserErrorCode.INVALID_RETRY_SOURCE),
        )

    job = await client.get_progress(retry_source_job_id, user_id=state.user_id)
    if job is None or job.thread_id != state.thread_id:
        await _raise_preflight_error(
            "invalid_input",
            user_error_message(UserErrorCode.INVALID_RETRY_SOURCE),
        )
    if job.status not in {VideoJobStatus.FAILED, VideoJobStatus.CANCELED}:
        await _raise_preflight_error(
            "invalid_input",
            user_error_message(UserErrorCode.INVALID_RETRY_SOURCE),
        )
    if job.retry_source_job_id is not None:
        await _raise_preflight_error(
            "invalid_input",
            user_error_message(UserErrorCode.INVALID_RETRY_SOURCE),
        )
    if not await client.can_user_retry(job):
        await _raise_preflight_error(
            "invalid_input",
            user_error_message(UserErrorCode.RETRY_ALREADY_USED),
        )


def _get_video_job_client() -> object | None:
    client = current_video_job_client.get()
    if client is not None:
        return client
    if not settings.database_url:
        return None
    return create_video_job_client(settings)


def _get_credit_ledger_client() -> CreditLedgerClient | None:
    return current_credit_ledger_client.get() or create_credit_ledger_client()


async def _release_stale_hold(state: ProovyState) -> None:
    if not state.hold_id:
        return

    ledger = _get_credit_ledger_client()
    if ledger is None:
        return

    try:
        hold_id = UUID(state.hold_id)
    except ValueError:
        logger.warning("잘못된 stale credit hold_id를 무시합니다: hold_id=%s", state.hold_id)
        return

    try:
        await ledger.release_hold(state.user_id, hold_id)
    except CreditHoldNotFoundError:
        logger.info("이미 없는 stale credit hold를 무시합니다: hold_id=%s", hold_id)


def _credit_exhausted_message(required: Decimal, available: Decimal) -> str:
    return (
        "크레딧이 부족합니다. "
        f"이 작업을 시작하려면 {format_credit_amount(required)} cr 필요합니다. "
        f"현재 사용 가능: {format_credit_amount(available)} cr."
    )


async def _reserve_plan_hold(
    state: ProovyState,
    plan: list[PlanStep],
    *,
    selected_model: str,
    explanation_mode: Literal["full", "brief"],
    planner_credit: CreditEntry,
) -> str | None:
    ledger = _get_credit_ledger_client()
    if ledger is None:
        return None

    required = estimate_plan_hold_amount(
        plan,
        selected_model=selected_model,
        explanation_mode=explanation_mode,
        accrued_log=[*state.credit_log, planner_credit],
    )
    try:
        hold = await ledger.hold(state.user_id, required, plan_id=state.thread_id)
    except InsufficientCreditsError as exc:
        await _raise_preflight_error(
            "credit_exhausted",
            _credit_exhausted_message(exc.required, exc.available),
        )
    except CreditAccountNotFoundError:
        await _raise_preflight_error(
            "credit_exhausted",
            _credit_exhausted_message(required, Decimal("0")),
        )
    return str(hold.id)


def _is_video_only_request(user_text: str) -> bool:
    normalized = user_text.lower()
    has_video_intent = any(hint.lower() in normalized for hint in _VIDEO_ONLY_HINTS)
    has_full_intent = any(hint.lower() in normalized for hint in _FULL_INTENT_HINTS)
    return has_video_intent and not has_full_intent


async def planner(state: ProovyState) -> dict:
    await _release_stale_hold(state)
    await _preflight_video_retry(state)

    llm = get_llm("flash")
    structured = llm.with_structured_output(_PlannerOutput)
    result = await structured.ainvoke([SystemMessage(_SYSTEM), *state.messages])

    plan = [PlanStep(action=s.action, description=s.description) for s in result.steps]

    if not any(s.action == "solve" for s in plan):
        plan.insert(0, PlanStep(action="solve", description="수학 문제 풀이"))

    selected_model = _DIFFICULTY_TO_MODEL[result.difficulty]
    explanation_mode = _resolve_explanation_mode(
        result.explanation_mode,
        plan,
        _latest_human_text(state),
    )

    planner_credit = CreditEntry(node="planner", action="llm_call", model="flash", cost=1.0)
    hold_id = await _reserve_plan_hold(
        state,
        plan,
        selected_model=selected_model,
        explanation_mode=explanation_mode,
        planner_credit=planner_credit,
    )

    emitter = current_emitter.get()
    if emitter and result.use_page:
        await emitter.emit(
            PageStartPayload(
                plan=plan,
                selected_model=selected_model,
                difficulty=result.difficulty,
                route=state.route,
                use_page=result.use_page,
            )
        )

    return {
        "plan": plan,
        "difficulty": result.difficulty,
        "selected_model": selected_model,
        "use_page": result.use_page,
        "explanation_mode": explanation_mode,
        "hold_id": hold_id,
        "credit_log": [planner_credit],
    }

"""VideoNode — Mode B asynchronous video launcher."""

from __future__ import annotations

import logging
from uuid import UUID

from langchain_core.messages import AIMessage, HumanMessage

from proovy_agent.common.config import settings
from proovy_agent.common.sse.context import current_emitter
from proovy_agent.common.sse.events import ErrorPayload, TokenPayload
from proovy_agent.features.credits import CreditLedgerClient, create_credit_ledger_client
from proovy_agent.features.video.hint_extractor import extract_video_inputs
from proovy_agent.features.video.jobs import (
    InvalidRetrySourceError,
    RetryAlreadyUsedError,
    VideoCreditCapture,
    VideoJobClient,
    VideoJobEnqueueError,
    create_video_job_client,
)
from proovy_agent.features.video.models import (
    UserErrorCode,
    VideoJobInput,
    VideoOptions,
    user_error_message,
)
from proovy_agent.graph.credit_pricing import VIDEO_FLAT_COST
from proovy_agent.graph.runtime import current_credit_ledger_client, current_video_job_client
from proovy_agent.graph.state import CreditEntry, ProovyState, VideoJobRef

logger = logging.getLogger(__name__)


class VideoNodePreflightError(RuntimeError):
    """Raised when VideoNode rejects a request before job/capture commit."""


def _video_options() -> VideoOptions:
    return VideoOptions(
        voice_id=settings.video_tts_voice,
        speaking_rate=settings.video_tts_speaking_rate,
    )


def _mark_current_step(plan: list, status: str, step_idx: int) -> list:
    updated = [s.model_copy() for s in plan]
    if updated and 0 <= step_idx < len(updated):
        updated[step_idx] = updated[step_idx].model_copy(update={"status": status})
    return updated


def _get_video_job_client() -> VideoJobClient:
    client = current_video_job_client.get()
    if client is not None:
        return client
    return create_video_job_client(settings)


def _get_credit_ledger_client() -> CreditLedgerClient | None:
    return current_credit_ledger_client.get() or create_credit_ledger_client()


def _latest_video_retry_payload(state: ProovyState) -> tuple[bool, str | None]:
    for msg in reversed(state.messages):
        if not isinstance(msg, HumanMessage):
            continue
        if msg.additional_kwargs.get("action") != "video_retry":
            return False, None
        retry_source = msg.additional_kwargs.get("retry_source_job_id")
        if retry_source is None:
            return True, None
        retry_source_text = str(retry_source).strip()
        return True, retry_source_text or None
    return False, None


async def _require_credit_capture(state: ProovyState) -> VideoCreditCapture:
    hold_id_text = state.hold_id
    if hold_id_text is None:
        await _raise_video_preflight_error(
            UserErrorCode.INVALID_INPUT,
            "영상 생성 크레딧 예약을 확인하지 못했어요. 다시 시도해 주세요.",
        )
    try:
        hold_id = UUID(hold_id_text)
    except ValueError:
        await _raise_video_preflight_error(
            UserErrorCode.INVALID_INPUT,
            "영상 생성 크레딧 예약을 확인하지 못했어요. 다시 시도해 주세요.",
        )
    return VideoCreditCapture(
        hold_id=hold_id,
        amount=VIDEO_FLAT_COST,
    )


async def _release_current_hold(state: ProovyState) -> None:
    if state.hold_id is None:
        return

    ledger = _get_credit_ledger_client()
    if ledger is None:
        return

    try:
        hold_id = UUID(state.hold_id)
    except ValueError:
        logger.warning(
            "잘못된 video credit hold_id를 release하지 않습니다: hold_id=%s", state.hold_id
        )
        return

    try:
        await ledger.release_hold(state.user_id, hold_id)
    except Exception:
        logger.exception("video retry pre-capture 실패 후 hold release 실패: hold_id=%s", hold_id)


async def _raise_video_preflight_error(code: UserErrorCode, message: str) -> None:
    emitter = current_emitter.get()
    if emitter:
        await emitter.emit(ErrorPayload(code=code.value, message=message))
    exc = VideoNodePreflightError(message)
    exc.sse_emitted = True  # type: ignore[attr-defined]
    raise exc


def _target_label(input_snapshot: VideoJobInput) -> str:
    title = input_snapshot.solution_plan.title if input_snapshot.solution_plan else "해설 영상"
    preview = " ".join(input_snapshot.problem_text.split())
    if len(preview) > 48:
        preview = f"{preview[:48]}..."
    return f"{title} - {preview}"


def _anchor_message(input_snapshot: VideoJobInput, job_id: str) -> AIMessage:
    metadata = {
        "display": "tool",
        "tool_name": "video_generate",
        "click_action": "open_video_viewer",
        "job_id": job_id,
        "status": "queued",
        "progress_url": f"/api/v1/video-jobs/{job_id}",
    }
    return AIMessage(
        content=f"'{_target_label(input_snapshot)}' 해설 영상을 만들고 있어요",
        id=f"video-job-{job_id}",
        metadata=metadata,
        additional_kwargs=metadata,
    )


async def _new_video_input(state: ProovyState) -> VideoJobInput:
    extraction = await extract_video_inputs(state.messages)
    return VideoJobInput(
        problem_text=extraction.problem_text,
        solution_plan=extraction.solution_plan,
        video_hints=extraction.video_hints,
        options=_video_options(),
    )


async def video_node(state: ProovyState) -> dict:
    """Create a queued video job, capture the flat video credit, and return an anchor."""
    client = _get_video_job_client()
    is_retry, retry_source_job_id = _latest_video_retry_payload(state)
    if is_retry and retry_source_job_id is None:
        await _release_current_hold(state)
        await _raise_video_preflight_error(
            UserErrorCode.INVALID_RETRY_SOURCE,
            user_error_message(UserErrorCode.INVALID_RETRY_SOURCE),
        )
    credit_capture = await _require_credit_capture(state)
    input_snapshot = None if is_retry else await _new_video_input(state)

    try:
        job = await client.create_and_enqueue(
            user_id=state.user_id,
            thread_id=state.thread_id,
            input_snapshot=input_snapshot,
            retry_source_job_id=retry_source_job_id,
            credit_capture=credit_capture,
        )
    except RetryAlreadyUsedError:
        await _release_current_hold(state)
        await _raise_video_preflight_error(
            UserErrorCode.RETRY_ALREADY_USED,
            user_error_message(UserErrorCode.RETRY_ALREADY_USED),
        )
    except InvalidRetrySourceError:
        await _release_current_hold(state)
        await _raise_video_preflight_error(
            UserErrorCode.INVALID_RETRY_SOURCE,
            user_error_message(UserErrorCode.INVALID_RETRY_SOURCE),
        )
    except VideoJobEnqueueError:
        raise

    anchor = _anchor_message(job.input_snapshot, job.id)
    emitter = current_emitter.get()
    if emitter:
        await emitter.emit(TokenPayload(delta=anchor.content, metadata=anchor.metadata))

    return {
        "messages": [anchor],
        "credit_log": [CreditEntry(node="video_node", action="video", cost=float(VIDEO_FLAT_COST))],
        "plan": _mark_current_step(state.plan, "done", state.executing_step_idx),
        "video_jobs": [
            VideoJobRef(
                job_id=job.id,
                status=job.status.value,
                progress=job.progress,
            )
        ],
    }

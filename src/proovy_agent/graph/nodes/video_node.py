"""VideoNode — Phase A inline video scaffold."""

from __future__ import annotations

from uuid import uuid4

from langchain_core.messages import AIMessage

from proovy_agent.common.config import settings
from proovy_agent.common.sse.context import current_emitter
from proovy_agent.common.sse.events import TokenPayload
from proovy_agent.features.video.hint_extractor import extract_video_inputs
from proovy_agent.features.video.models import VideoJobInput, VideoOptions, VideoPipelineJob
from proovy_agent.features.video.pipeline import (
    InlineVideoArtifactUploader,
    InlineVideoRunner,
    LocalInlineArtifactUploader,
    PhaseAInlineRunner,
    StageContext,
)
from proovy_agent.graph.state import CreditEntry, ProovyState, VideoJobRef

_inline_runner: InlineVideoRunner | None = None
_inline_uploader: InlineVideoArtifactUploader | None = None


def get_inline_runner() -> InlineVideoRunner:
    """Return the Phase A inline runner.

    The default implementation is intentionally throwaway: it runs local
    Manim/ffmpeg from the API process only for Phase A smoke validation.
    """
    global _inline_runner
    if _inline_runner is None:
        _inline_runner = PhaseAInlineRunner()
    return _inline_runner


def get_inline_uploader() -> InlineVideoArtifactUploader:
    """Return the Phase A inline artifact uploader."""
    global _inline_uploader
    if _inline_uploader is None:
        _inline_uploader = LocalInlineArtifactUploader()
    return _inline_uploader


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


def _success_message(
    *,
    title: str,
    final_video_url: str | None,
    output_path: str,
) -> str:
    location = final_video_url or output_path
    return f"{title} 해설 영상이 준비되었습니다: {location}"


async def video_node(state: ProovyState) -> dict:
    """Generate one video inline for Phase A and attach the artifact result."""
    job_id = f"inline-{uuid4()}"
    extraction = await extract_video_inputs(state.messages)
    input_snapshot = VideoJobInput(
        problem_text=extraction.problem_text,
        solution_plan=extraction.solution_plan,
        video_hints=extraction.video_hints,
        options=_video_options(),
    )
    pipeline_job = VideoPipelineJob(job_id=job_id, input_snapshot=input_snapshot)
    result = await get_inline_runner().run_now(pipeline_job, ctx=StageContext())
    artifact = await get_inline_uploader().upload_final_video(
        job_id=job_id,
        output_path=result.final_video.output_path,
    )

    message = _success_message(
        title=result.solution_plan.title,
        final_video_url=artifact.url,
        output_path=result.final_video.output_path,
    )
    emitter = current_emitter.get()
    if emitter:
        await emitter.emit(TokenPayload(delta=message))

    return {
        "messages": [
            AIMessage(
                message,
                metadata={
                    "display": "video_success",
                    "mode": "phase_a_inline",
                    "job_id": job_id,
                    "artifact_object_key": artifact.object_key,
                    "final_video_url": artifact.url,
                    "output_path": result.final_video.output_path,
                },
            )
        ],
        "credit_log": [CreditEntry(node="video_node", action="video", cost=0.0)],
        "plan": _mark_current_step(state.plan, "done", state.executing_step_idx),
        "video_jobs": [
            VideoJobRef(
                job_id=job_id,
                status="succeeded",
                progress={
                    "segments_done": len(result.rendered_segments),
                    "segments_total": len(result.script.segments),
                },
            )
        ],
    }

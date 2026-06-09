"""VideoNode Phase A inline scaffold tests."""

import asyncio
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
import pytest

from proovy_agent.features.video.hint_extractor import HintExtractionResult
from proovy_agent.features.video.models import (
    DirectorBriefPolicy,
    FinalVideoArtifact,
    RenderedSegment,
    ScriptSegment,
    SegmentTTSResult,
    SolutionPlan,
    SolutionStep,
    TargetSelection,
    VideoHints,
    VideoPipelineJob,
    VideoPipelineResult,
    VideoScript,
)
from proovy_agent.features.video.pipeline import InlineVideoArtifact
from proovy_agent.graph.nodes import video_node as video_node_module
from proovy_agent.graph.state import PlanStep, ProovyState


def _solution_plan() -> SolutionPlan:
    return SolutionPlan(
        title="일차방정식",
        steps=[
            SolutionStep(
                step_number=1,
                explanation="양변에 3을 더해 x=5를 얻습니다.",
                latex_expression="x = 5",
            )
        ],
        final_answer="x = 5",
    )


def _video_hints() -> VideoHints:
    return VideoHints(
        visualization_hints=["최종 답 x=5 강조"],
        emphasis_targets=["x = 5"],
        director_policy=DirectorBriefPolicy(brief_template="objects / layout / animation order"),
    )


def _extraction_result() -> HintExtractionResult:
    return HintExtractionResult(
        problem_text="x - 3 = 2를 풀어라.",
        target_selection=TargetSelection(
            target_turn_idx=0,
            problem_text="x - 3 = 2를 풀어라.",
            target_confidence=0.9,
            reasoning="최신 검증 풀이",
        ),
        solution_plan=_solution_plan(),
        video_hints=_video_hints(),
    )


def _pipeline_result(job_id: str, output_path: Path) -> VideoPipelineResult:
    script = VideoScript(
        title="일차방정식",
        segments=[
            ScriptSegment(
                segment_id="step-1",
                order=1,
                visual_type="equation_write",
                narration="양변에 3을 더합니다.",
                params={
                    "latex_expression": "x = 5",
                    "visual_description": "핵심 식을 표시합니다.",
                },
                source_step_number=1,
            )
        ],
        final_answer="x = 5",
    )
    return VideoPipelineResult(
        job_id=job_id,
        solution_plan=_solution_plan(),
        script=script,
        tts_results=[SegmentTTSResult(segment_id="step-1", narration="양변에 3을 더합니다.")],
        rendered_segments=[
            RenderedSegment(
                segment_id="step-1",
                visual_type="equation_write",
                video_path=str(output_path),
            )
        ],
        final_video=FinalVideoArtifact(
            output_path=str(output_path),
            rendered_segment_count=1,
        ),
    )


class _FakeRunner:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.jobs: list[VideoPipelineJob] = []

    async def run_now(
        self,
        job: VideoPipelineJob,
        *,
        ctx: object | None = None,
    ) -> VideoPipelineResult:
        _ = ctx
        self.jobs.append(job)
        return _pipeline_result(job.job_id, self.output_path)


class _FakeUploader:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str]] = []

    async def upload_final_video(
        self,
        *,
        job_id: str,
        output_path: str,
    ) -> InlineVideoArtifact:
        assert await asyncio.to_thread(Path(output_path).exists)
        self.uploads.append((job_id, output_path))
        return InlineVideoArtifact(
            object_key=f"video-jobs/{job_id}/attempts/inline/final.mp4",
            url="https://storage.example/final.mp4",
        )


def test_mark_current_step_ignores_negative_index() -> None:
    plan = [
        PlanStep(action="solve", description="풀이", status="done"),
        PlanStep(action="video", description="영상", status="pending"),
    ]

    result = video_node_module._mark_current_step(plan, "done", -1)

    assert [step.status for step in result] == ["done", "pending"]


@pytest.mark.asyncio
async def test_video_node_runs_inline_runner_uploads_mp4_and_displays_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "final.mp4"
    await asyncio.to_thread(output_path.write_bytes, b"fake mp4 bytes")
    runner = _FakeRunner(output_path)
    uploader = _FakeUploader()

    async def fake_extract_video_inputs(messages: object) -> HintExtractionResult:
        assert messages
        return _extraction_result()

    monkeypatch.setattr(video_node_module, "extract_video_inputs", fake_extract_video_inputs)
    monkeypatch.setattr(video_node_module, "get_inline_runner", lambda: runner)
    monkeypatch.setattr(video_node_module, "get_inline_uploader", lambda: uploader)

    state = ProovyState(
        user_id="user-1",
        thread_id="thread-1",
        messages=[
            HumanMessage(content="x - 3 = 2를 풀어라."),
            AIMessage(
                content="x=5입니다.",
                metadata={"kind": "verified_solution", "display": "hidden"},
            ),
        ],
        plan=[
            PlanStep(action="solve", description="풀이", status="done"),
            PlanStep(action="video", description="영상", status="running"),
        ],
        executing_step_idx=1,
    )

    result = await video_node_module.video_node(state)

    assert len(runner.jobs) == 1
    job = runner.jobs[0]
    assert job.input_snapshot.problem_text == "x - 3 = 2를 풀어라."
    assert job.input_snapshot.solution_plan == _solution_plan()
    assert job.input_snapshot.video_hints == _video_hints()
    assert uploader.uploads == [(job.job_id, str(output_path))]

    assert result["plan"][1].status == "done"
    assert result["video_jobs"][0].status == "succeeded"
    assert result["video_jobs"][0].progress == {"segments_done": 1, "segments_total": 1}
    message = result["messages"][0]
    assert "해설 영상이 준비되었습니다" in message.content
    assert "https://storage.example/final.mp4" in message.content
    assert message.metadata["display"] == "video_success"
    assert message.metadata["mode"] == "phase_a_inline"
    assert message.metadata["artifact_object_key"].endswith("/final.mp4")
    assert result["credit_log"][0].cost == 0.0

"""Render stage integration with the worker sandbox boundary."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from proovy_agent.features.video.exceptions import InvalidStageOutputError
from proovy_agent.features.video.models import (
    ScriptSegment,
    SegmentTTSResult,
    VideoJobInput,
    VideoPipelineJob,
    VideoScript,
)
from proovy_agent.features.video.pipeline import StageContext
from proovy_agent.features.video.pipeline.stages import stage_render
from proovy_agent.features.video.visual_types import VisualTypeRegistry


@dataclass(frozen=True, slots=True)
class _FakeSandboxResult:
    output_path: str
    diagnostics: dict[str, object]


class _RecordingSandbox:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def render_manim_source(
        self,
        *,
        manim_source: str,
        scene_class_name: str,
        job_id: str,
        segment_id: str,
    ) -> _FakeSandboxResult:
        self.calls.append(
            {
                "manim_source": manim_source,
                "scene_class_name": scene_class_name,
                "job_id": job_id,
                "segment_id": segment_id,
            }
        )
        return _FakeSandboxResult(
            output_path="/sandbox/rendered.mp4",
            diagnostics={"boundary": "subprocess", "secret_env_forwarded": False},
        )


def _registry(source: str) -> VisualTypeRegistry:
    registry = VisualTypeRegistry()
    registry.register(
        "custom_template",
        schema={"type": "object", "additionalProperties": False},
        prompt_snippet="custom template",
        render_fn=lambda **_kwargs: {
            "kind": "manim_source",
            "visual_type": "custom_template",
            "scene_class_name": "CustomScene",
            "manim_source": source,
        },
        narration_alignment_rule="align with narration",
    )
    return registry


def _script() -> VideoScript:
    return VideoScript(
        title="풀이",
        segments=[
            ScriptSegment(
                segment_id="segment-1",
                order=1,
                visual_type="custom_template",
                narration="풀이를 보여줍니다.",
            )
        ],
    )


async def test_stage_render_uses_sandbox_boundary_when_available() -> None:
    sandbox = _RecordingSandbox()
    rendered_segments = await stage_render(
        _script(),
        [SegmentTTSResult(segment_id="segment-1", narration="풀이를 보여줍니다.")],
        job=VideoPipelineJob(job_id="job-1", input_snapshot=VideoJobInput(problem_text="문제")),
        ctx=StageContext(
            registry=_registry("from manim import *\nclass CustomScene(Scene): pass"),
            sandbox=sandbox,
        ),
    )

    rendered = rendered_segments[0]
    template = rendered.diagnostics["template"]
    assert rendered.video_path == "/sandbox/rendered.mp4"
    assert rendered.diagnostics["render_mode"] == "sandbox_subprocess"
    assert template["latex_validation_errors"] == []
    assert template["sandbox"] == {"boundary": "subprocess", "secret_env_forwarded": False}
    assert sandbox.calls == [
        {
            "manim_source": "from manim import *\nclass CustomScene(Scene): pass",
            "scene_class_name": "CustomScene",
            "job_id": "job-1",
            "segment_id": "segment-1",
        }
    ]


async def test_stage_render_rejects_dangerous_latex_with_diagnostics() -> None:
    with pytest.raises(InvalidStageOutputError) as exc_info:
        await stage_render(
            _script(),
            [SegmentTTSResult(segment_id="segment-1", narration="풀이를 보여줍니다.")],
            job=VideoPipelineJob(
                job_id="job-1",
                input_snapshot=VideoJobInput(problem_text="문제"),
            ),
            ctx=StageContext(
                registry=_registry(r"MathTex(r'\input{/etc/passwd}')"),
                sandbox=_RecordingSandbox(),
            ),
        )

    latex_errors = exc_info.value.details["latex_validation_errors"]
    diagnostics = exc_info.value.details["diagnostics"]
    assert isinstance(latex_errors, list)
    assert latex_errors[0]["error_code"] == "latex_file_read"
    assert diagnostics["template"]["latex_validation_errors"] == latex_errors

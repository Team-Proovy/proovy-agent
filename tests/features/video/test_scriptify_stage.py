"""Scriptify stage tests."""

import pytest

from proovy_agent.features.video.exceptions import InvalidStageOutputError
from proovy_agent.features.video.models import (
    DirectorBriefPolicy,
    ScriptSegment,
    SolutionPlan,
    SolutionStep,
    VideoHints,
    VideoJobInput,
    VideoPipelineJob,
    VideoScript,
)
from proovy_agent.features.video.pipeline import StageContext
from proovy_agent.features.video.pipeline.stages.scriptify import (
    SCRIPTIFY_CONSERVATIVE_DEFAULTS,
    stage_scriptify,
)
from proovy_agent.features.video.visual_types import (
    PHASE_A_DETERMINISTIC_VISUAL_TYPES,
    create_phase_a_visual_type_registry,
)


def _sample_plan() -> SolutionPlan:
    return SolutionPlan(
        title="일차방정식 풀이",
        steps=[
            SolutionStep(
                step_number=1,
                explanation="양변에서 1을 뺍니다.",
                latex_expression="2x = 6",
            ),
            SolutionStep(
                step_number=2,
                explanation="양변을 2로 나누어 x를 구합니다.",
                latex_expression="x = 3",
            ),
        ],
        final_answer="x = 3",
    )


def _sample_hints() -> VideoHints:
    return VideoHints(
        visualization_hints=["좌변과 우변을 나란히 배치", "마지막 x=3을 크게 강조"],
        suggested_segments=5,
        emphasis_targets=["x = 3"],
        director_policy=DirectorBriefPolicy(
            brief_template="objects / layout / animation order",
            examples=["Good: show the equation before highlighting the operation"],
        ),
    )


def _job(video_hints: VideoHints | None = None) -> VideoPipelineJob:
    return VideoPipelineJob(
        job_id="job-1",
        input_snapshot=VideoJobInput(
            problem_text="2x + 1 = 7을 풀어라.",
            solution_plan=_sample_plan(),
            video_hints=video_hints,
        ),
    )


def _one_step_script(visual_type: str = "equation_write") -> VideoScript:
    return VideoScript(
        title="일차방정식 풀이",
        segments=[
            ScriptSegment(
                segment_id="step-1",
                order=1,
                visual_type=visual_type,
                narration="양변에서 1을 뺍니다.",
                params={
                    "latex_expression": "2x = 6",
                    "visual_description": "핵심 식을 한 줄로 표시합니다.",
                }
                if visual_type == "equation_write"
                else {},
                source_step_number=1,
            ),
            ScriptSegment(
                segment_id="step-2",
                order=2,
                visual_type="equation_derivation",
                narration="양변을 2로 나누어 x를 구합니다.",
                params={
                    "latex_steps": ["2x = 6", "x = 3"],
                    "visual_description": "이전 식에서 최종 식으로 변환합니다.",
                },
                source_step_number=2,
            ),
        ],
        final_answer="x = 3",
    )


async def test_stage_scriptify_builds_registry_valid_deterministic_script() -> None:
    registry = create_phase_a_visual_type_registry()
    ctx = StageContext(registry=registry)

    script = await stage_scriptify(_sample_plan(), job=_job(_sample_hints()), ctx=ctx)

    assert script.title == "일차방정식 풀이"
    assert [segment.visual_type for segment in script.segments] == [
        "intro_problem",
        "equation_write",
        "equation_derivation",
        "highlight_result",
        "outro_summary",
    ]
    assert [segment.source_step_number for segment in script.segments] == [
        None,
        1,
        2,
        None,
        None,
    ]
    assert all(
        segment.visual_type in PHASE_A_DETERMINISTIC_VISUAL_TYPES for segment in script.segments
    )
    for segment in script.segments:
        registry.validate_params(segment.visual_type, segment.params)
    assert script.segments[0].params["hints"] == [
        "좌변과 우변을 나란히 배치",
        "마지막 x=3을 크게 강조",
    ]


async def test_stage_scriptify_injects_director_policy_into_structured_llm_prompt() -> None:
    class CapturingStructuredLLM:
        def __init__(self) -> None:
            self.messages: list[object] | None = None

        async def ainvoke(self, messages: list[object]) -> VideoScript:
            self.messages = messages
            return _one_step_script()

    class CapturingLLM:
        def __init__(self) -> None:
            self.structured = CapturingStructuredLLM()
            self.schema: type[VideoScript] | None = None

        def with_structured_output(self, schema: type[VideoScript]) -> CapturingStructuredLLM:
            self.schema = schema
            return self.structured

    llm = CapturingLLM()
    ctx = StageContext(llm=llm)

    script = await stage_scriptify(_sample_plan(), job=_job(_sample_hints()), ctx=ctx)

    assert script == _one_step_script()
    assert llm.schema is VideoScript
    assert llm.structured.messages is not None
    system_prompt = llm.structured.messages[0].content
    assert "objects / layout / animation order" in system_prompt
    assert "Good: show the equation before highlighting the operation" in system_prompt
    assert "disable_equation_chain" in system_prompt
    assert "scene_bridge_enabled" in system_prompt
    assert "Do not emit visual_scene" in system_prompt


async def test_stage_scriptify_rejects_non_deterministic_visual_types_from_llm() -> None:
    class NonDeterministicLLM:
        def with_structured_output(self, schema: type[VideoScript]) -> object:
            class Structured:
                async def ainvoke(self, messages: list[object]) -> VideoScript:
                    _ = messages
                    return _one_step_script(visual_type="visual_scene")

            _ = schema
            return Structured()

    ctx = StageContext(llm=NonDeterministicLLM())

    with pytest.raises(InvalidStageOutputError, match="non-deterministic"):
        await stage_scriptify(_sample_plan(), job=_job(_sample_hints()), ctx=ctx)


async def test_stage_scriptify_rejects_params_that_do_not_match_registry_schema() -> None:
    invalid_script = _one_step_script()
    invalid_script.segments[0].params = {
        "latex": "2x = 6",
        "visual_description": "잘못된 키를 사용합니다.",
    }

    class InvalidParamsLLM:
        def with_structured_output(self, schema: type[VideoScript]) -> object:
            class Structured:
                async def ainvoke(self, messages: list[object]) -> VideoScript:
                    _ = messages
                    return invalid_script

            _ = schema
            return Structured()

    ctx = StageContext(llm=InvalidParamsLLM())

    with pytest.raises(InvalidStageOutputError, match="params"):
        await stage_scriptify(_sample_plan(), job=_job(_sample_hints()), ctx=ctx)


def test_scriptify_conservative_defaults_remain_locked() -> None:
    assert dict(SCRIPTIFY_CONSERVATIVE_DEFAULTS) == {
        "disable_equation_chain": True,
        "disable_prev_scene_state": True,
        "scene_bridge_enabled": False,
    }

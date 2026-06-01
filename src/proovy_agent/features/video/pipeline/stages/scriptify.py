"""Script generation stage for render-ready video segments."""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from proovy_agent.features.video.exceptions import InvalidStageOutputError
from proovy_agent.features.video.models import (
    ScriptSegment,
    StageName,
    UserErrorCode,
    VideoScript,
)
from proovy_agent.features.video.visual_types import PHASE_A_DETERMINISTIC_VISUAL_TYPES

if TYPE_CHECKING:
    from collections.abc import Mapping

    from proovy_agent.features.video.models import (
        SolutionPlan,
        SolutionStep,
        VideoHints,
        VideoPipelineJob,
    )
    from proovy_agent.features.video.pipeline.stage_context import StageContext
    from proovy_agent.features.video.visual_types import VisualTypeRegistry

SCRIPTIFY_CONSERVATIVE_DEFAULTS: Mapping[str, bool] = MappingProxyType(
    {
        "disable_equation_chain": True,
        "disable_prev_scene_state": True,
        "scene_bridge_enabled": False,
    }
)


def _invalid_scriptify_output(
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> InvalidStageOutputError:
    return InvalidStageOutputError(
        message,
        stage=StageName.SCRIPTIFY,
        user_error_code=UserErrorCode.UNKNOWN,
        details=details,
    )


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _coerce_video_script(value: object) -> VideoScript:
    if isinstance(value, VideoScript):
        return value
    try:
        return VideoScript.model_validate(value)
    except ValidationError as exc:
        raise _invalid_scriptify_output(
            "scriptify output is not a valid VideoScript",
            details={"errors": exc.errors(include_url=False)},
        ) from exc


def _phase_a_visual_type_names(registry: VisualTypeRegistry) -> tuple[str, ...]:
    registered_names = {definition.visual_type for definition in registry}
    return tuple(
        visual_type
        for visual_type in PHASE_A_DETERMINISTIC_VISUAL_TYPES
        if visual_type in registered_names
    )


def _phase_a_prompt_catalog(registry: VisualTypeRegistry) -> str:
    snippets: list[str] = []
    for visual_type in _phase_a_visual_type_names(registry):
        definition = registry.require(visual_type)
        snippets.append(f"## {visual_type}\n{definition.prompt_snippet}")
    return "\n\n".join(snippets)


def _director_policy_prompt(video_hints: VideoHints | None) -> str:
    if video_hints is None:
        return "DirectorBriefPolicy: not provided."
    return (
        "DirectorBriefPolicy:\n"
        f"- brief_template: {video_hints.director_policy.brief_template}\n"
        f"- examples: {_json_dumps(video_hints.director_policy.examples)}"
    )


def _build_scriptify_messages(
    plan: SolutionPlan,
    *,
    job: VideoPipelineJob,
    video_hints: VideoHints | None,
    registry: VisualTypeRegistry,
) -> list[SystemMessage | HumanMessage]:
    allowed_visual_types = _phase_a_visual_type_names(registry)
    system_content = "\n\n".join(
        [
            "You generate a render-ready VideoScript for a Korean math solution video.",
            (
                "Phase A allows only deterministic visual types. "
                f"Allowed visual_type values: {', '.join(allowed_visual_types)}."
            ),
            "Do not emit visual_scene, graph_plot, free-form code, or unregistered params.",
            (
                "Each SolutionPlan step must appear in at least one segment with the matching "
                "source_step_number."
            ),
            (
                "Each segment params object must satisfy the selected visual_type schema from "
                "the catalog."
            ),
            f"Conservative defaults: {_json_dumps(dict(SCRIPTIFY_CONSERVATIVE_DEFAULTS))}.",
            _director_policy_prompt(video_hints),
            f"Visual type catalog:\n{_phase_a_prompt_catalog(registry)}",
        ]
    )
    human_content = "\n\n".join(
        [
            f"Problem text:\n{job.input_snapshot.problem_text}",
            f"SolutionPlan JSON:\n{plan.model_dump_json()}",
            (
                "VideoHints JSON:\n"
                f"{video_hints.model_dump_json() if video_hints is not None else 'null'}"
            ),
        ]
    )
    return [SystemMessage(content=system_content), HumanMessage(content=human_content)]


async def _generate_script_with_llm(
    plan: SolutionPlan,
    *,
    job: VideoPipelineJob,
    ctx: StageContext,
    video_hints: VideoHints | None,
) -> VideoScript:
    structured_llm = ctx.llm.with_structured_output(VideoScript)
    result = await structured_llm.ainvoke(
        _build_scriptify_messages(plan, job=job, video_hints=video_hints, registry=ctx.registry)
    )
    return _coerce_video_script(result)


def _video_hints_list(video_hints: VideoHints | None) -> list[str]:
    if video_hints is None:
        return []
    return video_hints.visualization_hints


def _emphasis_targets(video_hints: VideoHints | None, final_answer: str | None) -> list[str]:
    targets = list(video_hints.emphasis_targets) if video_hints is not None else []
    if final_answer is not None and final_answer not in targets:
        targets.append(final_answer)
    return targets


def _visual_description(base: str, video_hints: VideoHints | None) -> str:
    hints = _video_hints_list(video_hints)
    if not hints:
        return base
    return f"{base} 반영할 화면 힌트: {' / '.join(hints[:3])}."


def _with_optional_list(
    params: dict[str, Any],
    *,
    key: str,
    values: list[str],
) -> dict[str, Any]:
    if values:
        params[key] = values
    return params


def _intro_segment(
    plan: SolutionPlan,
    *,
    job: VideoPipelineJob,
    order: int,
    video_hints: VideoHints | None,
) -> ScriptSegment:
    params: dict[str, Any] = {
        "title": plan.title,
        "problem_text": job.input_snapshot.problem_text,
        "visual_description": _visual_description(
            "문제 문장을 먼저 보여주고 풀이에서 사용할 핵심 조건을 정돈합니다.",
            video_hints,
        ),
    }
    _with_optional_list(params, key="hints", values=_video_hints_list(video_hints))
    _with_optional_list(
        params,
        key="emphasis_targets",
        values=_emphasis_targets(video_hints, plan.final_answer),
    )
    return ScriptSegment(
        segment_id="intro",
        order=order,
        visual_type="intro_problem",
        narration=f"{plan.title} 문제를 단계별로 풀어보겠습니다.",
        params=params,
    )


def _step_segment(
    step: SolutionStep,
    *,
    order: int,
    previous_latex: str | None,
    video_hints: VideoHints | None,
    final_answer: str | None,
) -> ScriptSegment:
    emphasis_targets = _emphasis_targets(video_hints, final_answer)
    if step.latex_expression is None:
        params = {
            "summary": [step.explanation],
            "visual_description": _visual_description(
                f"{step.step_number}번 단계의 설명을 짧은 요약 문장으로 보여줍니다.",
                video_hints,
            ),
        }
        if final_answer is not None:
            params["final_answer"] = final_answer
        _with_optional_list(params, key="emphasis_targets", values=emphasis_targets)
        return ScriptSegment(
            segment_id=f"step-{step.step_number}",
            order=order,
            visual_type="outro_summary",
            narration=step.explanation,
            params=params,
            source_step_number=step.step_number,
        )

    if previous_latex is not None:
        params = {
            "latex_steps": [previous_latex, step.latex_expression],
            "visual_description": _visual_description(
                f"{step.step_number}번 단계에서 이전 식이 현재 식으로 바뀌는 과정을 보여줍니다.",
                video_hints,
            ),
        }
        _with_optional_list(params, key="emphasis_targets", values=emphasis_targets)
        return ScriptSegment(
            segment_id=f"step-{step.step_number}",
            order=order,
            visual_type="equation_derivation",
            narration=step.explanation,
            params=params,
            source_step_number=step.step_number,
        )

    params = {
        "latex_expression": step.latex_expression,
        "visual_description": _visual_description(
            f"{step.step_number}번 단계의 핵심 식을 한 줄로 크게 표시합니다.",
            video_hints,
        ),
    }
    _with_optional_list(params, key="emphasis_targets", values=emphasis_targets)
    return ScriptSegment(
        segment_id=f"step-{step.step_number}",
        order=order,
        visual_type="equation_write",
        narration=step.explanation,
        params=params,
        source_step_number=step.step_number,
    )


def _final_answer_segment(
    plan: SolutionPlan,
    *,
    order: int,
    video_hints: VideoHints | None,
) -> ScriptSegment | None:
    if plan.final_answer is None:
        return None
    params = {
        "result_latex": plan.final_answer,
        "visual_description": _visual_description(
            "마지막 정답을 화면 중앙에서 명확하게 강조합니다.",
            video_hints,
        ),
    }
    _with_optional_list(
        params,
        key="emphasis_targets",
        values=_emphasis_targets(video_hints, plan.final_answer),
    )
    return ScriptSegment(
        segment_id="final-answer",
        order=order,
        visual_type="highlight_result",
        narration=f"따라서 정답은 {plan.final_answer}입니다.",
        params=params,
    )


def _outro_segment(
    plan: SolutionPlan,
    *,
    order: int,
    video_hints: VideoHints | None,
) -> ScriptSegment:
    summary = [step.explanation for step in plan.steps[-3:]]
    params: dict[str, Any] = {
        "summary": summary,
        "visual_description": _visual_description(
            "풀이 흐름을 짧게 다시 정리하고 영상의 마지막 장면을 구성합니다.",
            video_hints,
        ),
    }
    if plan.final_answer is not None:
        params["final_answer"] = plan.final_answer
    _with_optional_list(
        params,
        key="emphasis_targets",
        values=_emphasis_targets(video_hints, plan.final_answer),
    )
    return ScriptSegment(
        segment_id="outro",
        order=order,
        visual_type="outro_summary",
        narration="풀이 과정을 정리하면 위와 같습니다.",
        params=params,
    )


def _build_deterministic_script(
    plan: SolutionPlan,
    *,
    job: VideoPipelineJob,
    video_hints: VideoHints | None,
) -> VideoScript:
    segments: list[ScriptSegment] = [
        _intro_segment(plan, job=job, order=1, video_hints=video_hints)
    ]
    previous_latex: str | None = None
    for step in plan.steps:
        segment = _step_segment(
            step,
            order=len(segments) + 1,
            previous_latex=previous_latex,
            video_hints=video_hints,
            final_answer=plan.final_answer,
        )
        segments.append(segment)
        if step.latex_expression is not None:
            previous_latex = step.latex_expression

    final_answer_segment = _final_answer_segment(
        plan,
        order=len(segments) + 1,
        video_hints=video_hints,
    )
    if final_answer_segment is not None:
        segments.append(final_answer_segment)
    segments.append(_outro_segment(plan, order=len(segments) + 1, video_hints=video_hints))
    return VideoScript(title=plan.title, segments=segments, final_answer=plan.final_answer)


def _build_dry_run_script(plan: SolutionPlan, *, ctx: StageContext) -> VideoScript:
    segments = [
        ScriptSegment(
            segment_id=f"step-{step.step_number}",
            order=index,
            visual_type=ctx.default_visual_type,
            narration=step.explanation,
            params={"latex_expression": step.latex_expression}
            if step.latex_expression is not None
            else {},
            source_step_number=step.step_number,
        )
        for index, step in enumerate(plan.steps, start=1)
    ]
    return VideoScript(
        title=plan.title,
        segments=segments,
        final_answer=plan.final_answer,
    )


def _validate_script_contract(
    script: VideoScript,
    *,
    plan: SolutionPlan,
    registry: VisualTypeRegistry,
) -> VideoScript:
    if script.final_answer != plan.final_answer:
        raise _invalid_scriptify_output(
            "script final_answer must match SolutionPlan final_answer",
            details={
                "script_final_answer": script.final_answer,
                "plan_final_answer": plan.final_answer,
            },
        )

    if len(registry) == 0:
        return script

    allowed_visual_types = set(_phase_a_visual_type_names(registry))
    if not allowed_visual_types:
        raise _invalid_scriptify_output("registry has no Phase A deterministic visual types")

    for segment in script.segments:
        if segment.visual_type not in allowed_visual_types:
            raise _invalid_scriptify_output(
                "script segment uses a non-deterministic or unregistered visual_type",
                details={
                    "segment_id": segment.segment_id,
                    "visual_type": segment.visual_type,
                    "allowed_visual_types": sorted(allowed_visual_types),
                },
            )
        try:
            registry.validate_params(segment.visual_type, segment.params)
        except (KeyError, ValueError) as exc:
            raise _invalid_scriptify_output(
                "script segment params do not satisfy visual_type schema",
                details={"segment_id": segment.segment_id, "visual_type": segment.visual_type},
            ) from exc

    expected_step_numbers = {step.step_number for step in plan.steps}
    covered_step_numbers = {
        segment.source_step_number
        for segment in script.segments
        if segment.source_step_number is not None
    }
    missing_step_numbers = sorted(expected_step_numbers - covered_step_numbers)
    if missing_step_numbers:
        raise _invalid_scriptify_output(
            "script must include every SolutionPlan step",
            details={"missing_step_numbers": missing_step_numbers},
        )
    return script


async def stage_scriptify(
    plan: SolutionPlan,
    *,
    job: VideoPipelineJob,
    ctx: StageContext,
) -> VideoScript:
    """Produce a render-ready script with deterministic Phase A visual types."""
    if len(ctx.registry) == 0:
        return _build_dry_run_script(plan, ctx=ctx)

    video_hints = job.input_snapshot.video_hints
    if ctx.llm is None:
        script = _build_deterministic_script(plan, job=job, video_hints=video_hints)
    else:
        script = await _generate_script_with_llm(plan, job=job, ctx=ctx, video_hints=video_hints)
    return _validate_script_contract(script, plan=plan, registry=ctx.registry)

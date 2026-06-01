"""Evidence-based extraction layer for video inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage

from proovy_agent.common.config import get_settings
from proovy_agent.common.llm.client import get_llm
from proovy_agent.features.video.exceptions import InvalidSolutionPlanError
from proovy_agent.features.video.models import (
    SolutionPlan,
    TargetSelection,
    VideoHints,
)

_STRICT_TOOL_MESSAGE_LIMIT = 100
_TRIM_SUFFIX = "... [TRIMMED]"
_CATALOG_TEXT_LIMIT = 800

_TARGET_SYSTEM = """당신은 Proovy 영상 생성 요청의 대상 풀이 라우터입니다.
전체 대화에서 사용자가 영상으로 만들고 싶은 검증된 풀이 turn을 고르세요.

규칙:
- 아래 catalog의 target_turn_idx는 0부터 시작하는 solve turn 번호입니다.
- 사용자가 "아까 1번", "첫 번째", "전에 푼 문제"처럼 과거 풀이를 지칭하면 해당 turn을 선택합니다.
- 최신 HumanMessage가 새 문제가 아니라 영상 요청일 수 있으므로, 최신 메시지만 문제로 간주하지 마세요.
- target_confidence는 로깅 신호입니다. 낮더라도 가장 그럴듯한 선택을 반환하세요.
- target_turn_idx=null은 현재 요청이 아직 검증된 풀이가 없는 새 문제라고 판단할 때만 사용하세요.

검증된 풀이 catalog:
{catalog}
"""

_PLAN_SYSTEM = """당신은 Proovy 영상 입력용 풀이 추출기입니다.
제공된 target slice에는 대상 문제, CoreSolver의 code/stdout evidence, verified_solution이 들어 있습니다.

규칙:
- 새 풀이를 만들거나 재계산하지 말고, target slice에 있는 검증된 근거만 SolutionPlan으로 옮기세요.
- final_answer와 핵심 숫자는 verified_solution과 code/stdout evidence에 있는 값을 보존하세요.
- ToolMessage stdout이 답을 결정했다면 그 숫자를 final_answer와 관련 단계 설명에 반드시 유지하세요.
- 영상 표현 힌트는 만들지 마세요. SolutionPlan만 반환하세요.
"""

_VIDEO_HINTS_SYSTEM = """당신은 Proovy 영상 연출 힌트 작성기입니다.
입력으로 받은 problem_text와 SolutionPlan만 사용해 VideoHints를 작성하세요.
전체 messages나 이전 대화를 추측하지 말고, 검증된 풀이 단계에 필요한 시각화 힌트만 생성하세요.
"""


@dataclass(frozen=True)
class _SolutionTurn:
    turn_idx: int
    start_idx: int
    end_idx: int
    problem_message: HumanMessage
    verified_message: AIMessage


@dataclass(frozen=True)
class HintExtractionResult:
    """Output bundle produced by the video hint extractor."""

    problem_text: str
    target_selection: TargetSelection
    solution_plan: SolutionPlan
    video_hints: VideoHints


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    return str(content)


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= len(_TRIM_SUFFIX):
        return value[:limit]
    return value[: limit - len(_TRIM_SUFFIX)] + _TRIM_SUFFIX


def _is_verified_solution_message(message: AnyMessage) -> bool:
    return (
        isinstance(message, AIMessage)
        and getattr(message, "metadata", {}).get("kind") == "verified_solution"
    )


def trim_tool_messages_strict(
    messages: list[AnyMessage],
    *,
    limit: int = _STRICT_TOOL_MESSAGE_LIMIT,
) -> list[AnyMessage]:
    """Return a copy with ToolMessage content capped for Stage 1a routing."""
    trimmed: list[AnyMessage] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            content = _truncate_text(str(message.content), limit)
            if content != message.content:
                message = message.model_copy(update={"content": content})
        trimmed.append(message)
    return trimmed


def _solution_turns(messages: list[AnyMessage]) -> list[_SolutionTurn]:
    turns: list[_SolutionTurn] = []
    latest_human_idx: int | None = None

    for idx, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            latest_human_idx = idx
        elif _is_verified_solution_message(message) and latest_human_idx is not None:
            turns.append(
                _SolutionTurn(
                    turn_idx=len(turns),
                    start_idx=latest_human_idx,
                    end_idx=idx,
                    problem_message=messages[latest_human_idx],
                    verified_message=message,
                )
            )

    return turns


def _latest_human_idx(messages: list[AnyMessage]) -> int | None:
    for idx in range(len(messages) - 1, -1, -1):
        if isinstance(messages[idx], HumanMessage):
            return idx
    return None


def _format_turn_catalog(turns: list[_SolutionTurn]) -> str:
    if not turns:
        return "검증된 풀이 turn이 없습니다."

    lines: list[str] = []
    for turn in turns:
        problem = _truncate_text(_message_text(turn.problem_message), _CATALOG_TEXT_LIMIT)
        verified = _truncate_text(_message_text(turn.verified_message), _CATALOG_TEXT_LIMIT)
        lines.append(
            "\n".join(
                [
                    f"- target_turn_idx={turn.turn_idx}",
                    f"  problem_text: {problem}",
                    f"  verified_solution: {verified}",
                ]
            )
        )
    return "\n".join(lines)


def _target_turn(
    messages: list[AnyMessage],
    selection: TargetSelection,
) -> _SolutionTurn:
    turns = _solution_turns(messages)
    if selection.target_turn_idx is None:
        raise InvalidSolutionPlanError(
            "target_turn_idx is required to extract a video SolutionPlan",
            details={"target_confidence": selection.target_confidence},
        )
    if selection.target_turn_idx >= len(turns):
        raise InvalidSolutionPlanError(
            "target_turn_idx does not match a verified solution turn",
            details={
                "target_turn_idx": selection.target_turn_idx,
                "available_turns": len(turns),
                "target_confidence": selection.target_confidence,
            },
        )
    return turns[selection.target_turn_idx]


def build_target_slice(
    messages: list[AnyMessage],
    selection: TargetSelection,
) -> list[AnyMessage]:
    """Build the full-evidence target slice for Stage 1b."""
    turn = _target_turn(messages, selection)
    target_slice = list(messages[turn.start_idx : turn.end_idx + 1])

    request_idx = _latest_human_idx(messages)
    if request_idx is not None and request_idx > turn.end_idx:
        target_slice.append(messages[request_idx])

    return target_slice


async def select_target_turn(
    messages: list[AnyMessage],
    *,
    llm: Any | None = None,
) -> TargetSelection:
    """Stage 1a: resolve which verified solve turn the video request targets."""
    settings = get_settings()
    model = llm or get_llm(settings.video_hint_target_model)
    structured = model.with_structured_output(TargetSelection)
    system_message = SystemMessage(
        _TARGET_SYSTEM.format(catalog=_format_turn_catalog(_solution_turns(messages)))
    )
    result = await structured.ainvoke([system_message, *trim_tool_messages_strict(messages)])
    if isinstance(result, TargetSelection):
        return result
    return TargetSelection.model_validate(result)


async def extract_solution_plan(
    target_slice: list[AnyMessage],
    *,
    llm: Any | None = None,
) -> SolutionPlan:
    """Stage 1b: extract a SolutionPlan from the selected full-evidence slice."""
    settings = get_settings()
    model = llm or get_llm(settings.video_hint_plan_model)
    structured = model.with_structured_output(SolutionPlan)
    result = await structured.ainvoke([SystemMessage(_PLAN_SYSTEM), *target_slice])
    if isinstance(result, SolutionPlan):
        return result
    return SolutionPlan.model_validate(result)


async def extract_video_hints(
    problem_text: str,
    solution_plan: SolutionPlan,
    *,
    llm: Any | None = None,
) -> VideoHints:
    """Step 2: generate video hints from the extracted plan only."""
    settings = get_settings()
    model = llm or get_llm(settings.video_hint_videohints_model)
    structured = model.with_structured_output(VideoHints)
    prompt = (
        "[problem_text]\n"
        f"{problem_text}\n\n"
        "[solution_plan]\n"
        f"{solution_plan.model_dump_json(indent=2)}"
    )
    result = await structured.ainvoke([SystemMessage(_VIDEO_HINTS_SYSTEM), HumanMessage(prompt)])
    if isinstance(result, VideoHints):
        return result
    return VideoHints.model_validate(result)


async def extract_video_inputs(
    messages: list[AnyMessage],
    *,
    target_llm: Any | None = None,
    plan_llm: Any | None = None,
    video_hints_llm: Any | None = None,
) -> HintExtractionResult:
    """Run Stage 1a, Stage 1b, and Step 2 without wiring the video node."""
    selection = await select_target_turn(messages, llm=target_llm)
    target_slice = build_target_slice(messages, selection)
    problem_text = _message_text(target_slice[0])
    solution_plan = await extract_solution_plan(target_slice, llm=plan_llm)
    video_hints = await extract_video_hints(
        problem_text,
        solution_plan,
        llm=video_hints_llm,
    )
    return HintExtractionResult(
        problem_text=problem_text,
        target_selection=selection,
        solution_plan=solution_plan,
        video_hints=video_hints,
    )

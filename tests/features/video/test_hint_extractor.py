"""Video hint extractor tests."""

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from proovy_agent.features.video.hint_extractor import (
    build_target_slice,
    extract_solution_plan,
    extract_video_hints,
    extract_video_inputs,
    select_target_turn,
)
from proovy_agent.features.video.models import (
    DirectorBriefPolicy,
    SolutionPlan,
    SolutionStep,
    TargetSelection,
    VideoHints,
)


class _StructuredLLM:
    def __init__(self, factory: Callable[[list[AnyMessage]], object]) -> None:
        self.factory = factory
        self.calls: list[list[AnyMessage]] = []

    async def ainvoke(self, messages: list[AnyMessage]) -> object:
        self.calls.append(messages)
        return self.factory(messages)


class _FakeLLM:
    def __init__(self, factory: Callable[[list[AnyMessage]], object]) -> None:
        self.schema: type[Any] | None = None
        self.structured = _StructuredLLM(factory)

    def with_structured_output(self, schema: type[Any]) -> _StructuredLLM:
        self.schema = schema
        return self.structured


def _solve_turn(
    *,
    problem: str,
    code: str,
    stdout: str,
    verified: str,
    tool_call_id: str,
) -> list[AnyMessage]:
    return [
        HumanMessage(content=problem),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": tool_call_id,
                    "name": "code_execute",
                    "args": {"code": code},
                }
            ],
        ),
        ToolMessage(
            content=stdout,
            tool_call_id=tool_call_id,
            name="code_execute",
        ),
        AIMessage(
            content=verified,
            metadata={"kind": "verified_solution", "display": "hidden"},
        ),
    ]


async def test_select_target_turn_uses_strict_metaview_without_confidence_gate() -> None:
    long_stdout = "stdout:\n" + "1234567890" * 30
    messages = [
        *_solve_turn(
            problem="x + 1 = 3을 풀어라.",
            code="print(2)",
            stdout=long_stdout,
            verified="x=2입니다.",
            tool_call_id="tc-1",
        ),
        HumanMessage(content="아까 1번 문제 영상으로 만들어줘."),
    ]
    fake_llm = _FakeLLM(
        lambda _messages: TargetSelection(
            target_turn_idx=0,
            problem_text="x + 1 = 3을 풀어라.",
            target_confidence=0.14,
            reasoning="낮은 confidence지만 과거 1번 풀이를 지칭한다.",
        )
    )

    selection = await select_target_turn(messages, llm=fake_llm)

    assert selection.target_turn_idx == 0
    assert selection.target_confidence == 0.14
    assert fake_llm.schema is TargetSelection
    tool_messages = [
        message for message in fake_llm.structured.calls[0] if isinstance(message, ToolMessage)
    ]
    assert len(tool_messages) == 1
    assert len(str(tool_messages[0].content)) <= 100
    assert str(tool_messages[0].content).endswith("... [TRIMMED]")
    assert messages[2].content == long_stdout


def test_build_target_slice_selects_requested_verified_turn() -> None:
    messages = [
        *_solve_turn(
            problem="1번: x + 1 = 3을 풀어라.",
            code="print(2)",
            stdout="stdout:\n2\n",
            verified="1단계로 x=2를 확인했습니다. 최종 답은 x=2입니다.",
            tool_call_id="tc-1",
        ),
        AIMessage(content="학생용 설명", metadata={"display": "content"}),
        *_solve_turn(
            problem="2번: y - 4 = 5를 풀어라.",
            code="print(9)",
            stdout="stdout:\n9\n",
            verified="1단계로 y=9를 확인했습니다. 최종 답은 y=9입니다.",
            tool_call_id="tc-2",
        ),
        HumanMessage(content="아까 1번 문제 영상으로 만들어줘."),
    ]
    selection = TargetSelection(
        target_turn_idx=0,
        problem_text="1번: x + 1 = 3을 풀어라.",
        target_confidence=0.38,
        reasoning="사용자가 1번을 지칭했다.",
    )

    target_slice = build_target_slice(messages, selection)

    assert target_slice[0].content == "1번: x + 1 = 3을 풀어라."
    assert target_slice[-1].content == "아까 1번 문제 영상으로 만들어줘."
    assert any(
        isinstance(message, ToolMessage) and "stdout:\n2" in str(message.content)
        for message in target_slice
    )
    assert any(
        isinstance(message, AIMessage)
        and any(call["args"]["code"] == "print(2)" for call in message.tool_calls)
        for message in target_slice
    )
    assert all("y=9" not in str(message.content) for message in target_slice)


async def test_extract_solution_plan_sees_full_stdout_evidence_for_final_answer() -> None:
    stdout = "stdout:\n" + ("trace line\n" * 30) + "final_answer=6.67\n"
    target_slice = _solve_turn(
        problem="20 / 3을 소수 둘째 자리까지 구해라.",
        code="print(round(20 / 3, 2))",
        stdout=stdout,
        verified="코드 실행 결과 6.67이므로 최종 답은 6.67입니다.",
        tool_call_id="tc-division",
    )

    def _factory(messages: list[AnyMessage]) -> SolutionPlan:
        tool_message = next(message for message in messages if isinstance(message, ToolMessage))
        assert tool_message.content == stdout
        assert "[TRIMMED]" not in str(tool_message.content)
        return SolutionPlan(
            title="나눗셈 결과 확인",
            steps=[
                SolutionStep(
                    step_number=1,
                    explanation="stdout의 final_answer=6.67을 근거로 값을 확정합니다.",
                    latex_expression="20 \\div 3 \\approx 6.67",
                )
            ],
            final_answer="6.67",
        )

    fake_llm = _FakeLLM(_factory)

    plan = await extract_solution_plan(target_slice, llm=fake_llm)

    assert plan.final_answer == "6.67"
    assert "6.67" in plan.steps[0].explanation
    assert fake_llm.schema is SolutionPlan


async def test_extract_video_hints_consumes_problem_and_plan_not_messages() -> None:
    plan = SolutionPlan(
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
    decoy_message_text = "이전 대화의 잘못된 답 x=999"

    def _factory(messages: list[AnyMessage]) -> VideoHints:
        combined = "\n".join(str(message.content) for message in messages)
        assert decoy_message_text not in combined
        assert "x - 3 = 2" in combined
        assert "x = 5" in combined
        return VideoHints(
            visualization_hints=["양변에 같은 값을 더하는 장면", "최종 답 x=5 강조"],
            suggested_segments=2,
            emphasis_targets=["x = 5"],
            director_policy=DirectorBriefPolicy(
                brief_template="objects / layout / animation order",
                examples=["Good: show the equation before highlighting x=5"],
            ),
        )

    fake_llm = _FakeLLM(_factory)

    hints = await extract_video_hints("x - 3 = 2를 풀어라.", plan, llm=fake_llm)

    assert hints.emphasis_targets == ["x = 5"]
    assert fake_llm.schema is VideoHints
    assert len(fake_llm.structured.calls[0]) == 2


async def test_extract_video_inputs_uses_target_turn_problem_as_canonical_text() -> None:
    canonical_problem = "1번: x - 3 = 2를 풀어라."
    wrong_selection_problem = "2번: 다른 문제"
    messages = [
        *_solve_turn(
            problem=canonical_problem,
            code="print(5)",
            stdout="stdout:\n5\n",
            verified="x=5입니다.",
            tool_call_id="tc-1",
        ),
        HumanMessage(content="아까 1번 문제 영상으로 만들어줘."),
    ]
    plan = SolutionPlan(
        title="일차방정식",
        steps=[SolutionStep(step_number=1, explanation="x=5를 확인합니다.")],
        final_answer="x=5",
    )
    target_llm = _FakeLLM(
        lambda _messages: TargetSelection(
            target_turn_idx=0,
            problem_text=wrong_selection_problem,
            target_confidence=0.92,
            reasoning="1번을 지칭했다.",
        )
    )
    plan_llm = _FakeLLM(lambda _messages: plan)

    def _video_hints_factory(messages: list[AnyMessage]) -> VideoHints:
        combined = "\n".join(str(message.content) for message in messages)
        assert canonical_problem in combined
        assert wrong_selection_problem not in combined
        return VideoHints(
            visualization_hints=["x=5 강조"],
            director_policy=DirectorBriefPolicy(brief_template="objects / layout / animation"),
        )

    result = await extract_video_inputs(
        messages,
        target_llm=target_llm,
        plan_llm=plan_llm,
        video_hints_llm=_FakeLLM(_video_hints_factory),
    )

    assert result.problem_text == canonical_problem
    assert result.target_selection.problem_text == wrong_selection_problem

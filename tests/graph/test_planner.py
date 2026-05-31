"""Planner 노드 단위 테스트."""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage
import pytest

from proovy_agent.graph.nodes import planner as planner_module
from proovy_agent.graph.state import ProovyState


def _state(content: str) -> ProovyState:
    return ProovyState(user_id="u", thread_id="t", messages=[HumanMessage(content=content)])


def _mock_llm(result: object) -> MagicMock:
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=result)
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


@pytest.mark.asyncio
async def test_video_only_intent_sets_brief_explanation_mode() -> None:
    result = planner_module._PlannerOutput(
        steps=[
            planner_module._StepInput(action="video", description="해설 영상 생성"),
        ],
        difficulty="easy",
        use_page=False,
        explanation_mode="brief",
    )

    with patch("proovy_agent.graph.nodes.planner.get_llm", return_value=_mock_llm(result)):
        update = await planner_module.planner(_state("영상으로 설명해줘"))

    assert update["explanation_mode"] == "brief"
    assert [step.action for step in update["plan"]] == ["solve", "video"]


@pytest.mark.asyncio
async def test_general_solution_intent_sets_full_explanation_mode() -> None:
    result = planner_module._PlannerOutput(
        steps=[
            planner_module._StepInput(action="solve", description="수학 문제 풀이"),
        ],
        difficulty="easy",
        use_page=False,
        explanation_mode="full",
    )

    with patch("proovy_agent.graph.nodes.planner.get_llm", return_value=_mock_llm(result)):
        update = await planner_module.planner(_state("자세히 풀어줘"))

    assert update["explanation_mode"] == "full"


@pytest.mark.asyncio
async def test_ambiguous_intent_defaults_to_full_explanation_mode() -> None:
    result = planner_module._PlannerOutput(
        steps=[
            planner_module._StepInput(action="video", description="해설 영상 생성"),
        ],
        difficulty="easy",
        use_page=False,
    )

    with patch("proovy_agent.graph.nodes.planner.get_llm", return_value=_mock_llm(result)):
        update = await planner_module.planner(_state("풀이도 보고 영상도 만들어줘"))

    assert update["explanation_mode"] == "full"


@pytest.mark.asyncio
async def test_video_only_text_forces_brief_when_model_defaults_to_full() -> None:
    result = planner_module._PlannerOutput(
        steps=[
            planner_module._StepInput(action="video", description="해설 영상 생성"),
        ],
        difficulty="easy",
        use_page=False,
        explanation_mode="full",
    )

    with patch("proovy_agent.graph.nodes.planner.get_llm", return_value=_mock_llm(result)):
        update = await planner_module.planner(_state("이 문제 영상으로 설명해줘"))

    assert update["explanation_mode"] == "brief"


@pytest.mark.asyncio
async def test_brief_without_video_falls_back_to_full_explanation_mode() -> None:
    result = planner_module._PlannerOutput(
        steps=[
            planner_module._StepInput(action="solve", description="수학 문제 풀이"),
        ],
        difficulty="easy",
        use_page=False,
        explanation_mode="brief",
    )

    with patch("proovy_agent.graph.nodes.planner.get_llm", return_value=_mock_llm(result)):
        update = await planner_module.planner(_state("답만 알려줘"))

    assert update["explanation_mode"] == "full"

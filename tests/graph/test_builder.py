"""LangGraph 빌더 — lazy singleton 테스트."""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
import pytest

from proovy_agent.graph import builder as builder_module
from proovy_agent.graph.state import PlanStep, ProovyState


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder_module, "_graph", None)


def test_get_graph_builds_only_once() -> None:
    mock_graph = MagicMock()
    with patch.object(builder_module, "_build", return_value=mock_graph) as mock_build:
        g1 = builder_module.get_graph()
        g2 = builder_module.get_graph()

    assert g1 is g2
    assert mock_build.call_count == 1


def test_get_graph_returns_build_result() -> None:
    sentinel = object()
    with patch.object(builder_module, "_build", return_value=sentinel):
        assert builder_module.get_graph() is sentinel


@pytest.mark.asyncio
async def test_builder_graph_dispatches_video_only_after_solve_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Planner의 [solve, video] plan은 solve 완료 후 VideoNode로 이어진다."""
    from proovy_agent.graph.agents.core_solver import agent as core_solver_module
    from proovy_agent.graph.nodes import credit_settler as credit_settler_module
    from proovy_agent.graph.nodes import planner as planner_module
    from proovy_agent.graph.nodes import router as router_module
    from proovy_agent.graph.nodes import video_node as video_node_module

    calls: list[str] = []

    async def fake_router(_state: ProovyState) -> dict:
        return {"route": "math_task"}

    def fake_router_edge(_state: ProovyState) -> str:
        return "math_task"

    async def fake_planner(_state: ProovyState) -> dict:
        calls.append("planner")
        return {
            "plan": [
                PlanStep(action="solve", description="문제 풀이"),
                PlanStep(action="video", description="해설 영상"),
            ],
            "difficulty": "easy",
            "selected_model": "flash",
            "explanation_mode": "brief",
            "credit_log": [],
        }

    async def fake_core_solver(state: ProovyState) -> dict:
        assert state.executing_step_idx == 0
        assert [step.status for step in state.plan] == ["running", "pending"]
        calls.append("solve")
        plan = [step.model_copy() for step in state.plan]
        plan[0] = plan[0].model_copy(update={"status": "done"})
        return {
            "plan": plan,
            "messages": [
                AIMessage(
                    content="검증된 풀이입니다.",
                    metadata={"kind": "verified_solution", "display": "hidden"},
                )
            ],
            "credit_log": [],
        }

    async def fake_video_node(state: ProovyState) -> dict:
        assert state.executing_step_idx == 1
        assert [step.status for step in state.plan] == ["done", "running"]
        assert any(
            isinstance(message, AIMessage) and message.metadata.get("kind") == "verified_solution"
            for message in state.messages
        )
        calls.append("video")
        plan = [step.model_copy() for step in state.plan]
        plan[1] = plan[1].model_copy(update={"status": "done"})
        return {
            "plan": plan,
            "messages": [AIMessage(content="영상 완료", metadata={"display": "video_success"})],
            "credit_log": [],
        }

    async def fake_credit_settler(_state: ProovyState) -> dict:
        calls.append("credit_settler")
        return {}

    monkeypatch.setattr(router_module, "router", fake_router)
    monkeypatch.setattr(router_module, "router_edge", fake_router_edge)
    monkeypatch.setattr(planner_module, "planner", fake_planner)
    monkeypatch.setattr(core_solver_module, "core_solver", fake_core_solver)
    monkeypatch.setattr(video_node_module, "video_node", fake_video_node)
    monkeypatch.setattr(credit_settler_module, "credit_settler", fake_credit_settler)

    graph = builder_module._build()
    final = await graph.ainvoke(
        ProovyState(
            raw_input={"problem": "x - 3 = 2를 영상으로 설명해줘."},
            user_id="user-1",
            thread_id="thread-1",
            messages=[HumanMessage(content="x - 3 = 2를 영상으로 설명해줘.")],
        )
    )

    assert calls == ["planner", "solve", "video", "credit_settler"]
    assert [step.status for step in final["plan"]] == ["done", "done"]

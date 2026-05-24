"""PlanExecutor 노드 단위 테스트."""

from langgraph.types import Command, Send
import pytest

from proovy_agent.graph.nodes.plan_executor import _find_ready_steps, plan_executor
from proovy_agent.graph.state import PlanStep, ProovyState


def _step(action: str, status: str = "pending") -> PlanStep:
    return PlanStep(action=action, description="test", status=status)


def _state(**kwargs: object) -> ProovyState:
    return ProovyState(user_id="u", thread_id="t", **kwargs)


# ── _find_ready_steps ────────────────────────────────────────────────────────


def test_solve_has_no_deps() -> None:
    plan = [_step("solve")]
    ready = _find_ready_steps(plan)
    assert len(ready) == 1
    assert ready[0][1].action == "solve"


def test_pdf_waits_for_solve() -> None:
    plan = [_step("solve"), _step("pdf")]
    assert len(_find_ready_steps(plan)) == 1
    assert _find_ready_steps(plan)[0][1].action == "solve"


def test_pdf_ready_after_solve_done() -> None:
    plan = [_step("solve", "done"), _step("pdf")]
    ready = _find_ready_steps(plan)
    assert len(ready) == 1
    assert ready[0][1].action == "pdf"


def test_video_and_pdf_both_ready_after_solve() -> None:
    plan = [_step("solve", "done"), _step("video"), _step("pdf")]
    assert len(_find_ready_steps(plan)) == 2


def test_running_step_is_not_ready() -> None:
    plan = [_step("solve", "running")]
    assert _find_ready_steps(plan) == []


# ── plan_executor routing ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_done_routes_to_credit_settler() -> None:
    state = _state(plan=[_step("solve", "done")])
    result = await plan_executor(state)
    assert isinstance(result, Command)
    assert result.goto == "credit_settler"


@pytest.mark.asyncio
async def test_single_step_routes_to_correct_node() -> None:
    state = _state(plan=[_step("solve")])
    result = await plan_executor(state)
    assert isinstance(result, Command)
    assert result.goto == "core_solver"


@pytest.mark.asyncio
async def test_parallel_steps_wrapped_in_command() -> None:
    """list[Send] 대신 Command(goto=[Send(...)]) 형태로 반환해야 한다."""
    state = _state(plan=[_step("solve", "done"), _step("video"), _step("pdf")])
    result = await plan_executor(state)
    assert isinstance(result, Command)
    assert isinstance(result.goto, list)
    assert len(result.goto) == 2
    assert all(isinstance(s, Send) for s in result.goto)


@pytest.mark.asyncio
async def test_running_step_does_not_transition_to_credit_settler() -> None:
    """병렬 브랜치 실행 중(running)이면 credit_settler로 가지 않는다."""
    state = _state(plan=[_step("solve", "done"), _step("pdf", "running")])
    result = await plan_executor(state)
    assert isinstance(result, Command)
    assert result.goto != "credit_settler"

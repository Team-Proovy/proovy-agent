"""PlanExecutor 노드 — Command API로 순차/병렬 라우팅."""

from langgraph.types import Command, Send

from proovy_agent.graph.state import PlanStep, ProovyState

_ACTION_TO_NODE: dict[str, str] = {
    "solve": "core_solver",
    "video": "video_node",
    "pdf": "pdf_node",
}
_DEPENDS_ON_SOLVE: set[str] = {"video", "pdf"}


def _find_ready_steps(plan: list[PlanStep]) -> list[tuple[int, PlanStep]]:
    solve_done = any(s.action == "solve" and s.status == "done" for s in plan)
    ready = []
    for i, step in enumerate(plan):
        if step.status != "pending":
            continue
        if step.action in _DEPENDS_ON_SOLVE and not solve_done:
            continue
        ready.append((i, step))
    return ready


async def plan_executor(state: ProovyState) -> Command | list[Send]:
    plan = [s.model_copy() for s in state.plan]
    ready = _find_ready_steps(plan)

    if not ready:
        return Command(goto="credit_settler")

    if len(ready) == 1:
        idx, step = ready[0]
        plan[idx] = step.model_copy(update={"status": "running"})
        return Command(
            update={"plan": plan, "executing_step_idx": idx},
            goto=_ACTION_TO_NODE[step.action],
        )

    # 복수 ready → Send API로 병렬 실행
    for idx, step in ready:
        plan[idx] = step.model_copy(update={"status": "running"})

    return [
        Send(
            _ACTION_TO_NODE[step.action],
            {
                **state.model_dump(),
                "plan": [s.model_dump() for s in plan],
                "executing_step_idx": idx,
            },
        )
        for idx, step in ready
    ]

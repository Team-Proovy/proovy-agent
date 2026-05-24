"""LangGraph StateGraph 빌드."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from proovy_agent.graph.state import ProovyState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

_graph: CompiledStateGraph | None = None


def get_graph() -> CompiledStateGraph:
    """그래프를 처음 호출 시 빌드하고 이후에는 캐시를 반환합니다."""
    global _graph
    if _graph is None:
        _graph = _build()
    return _graph


def _pdf_step_done_wrapper(pdf_callable: object) -> object:
    """PDFNode 실행 후 plan step 상태를 done으로 갱신하는 래퍼.

    PDFNode는 plan step 상태를 직접 갱신하지 않으므로, 해당 step을
    done으로 표시해 PlanExecutor가 올바르게 다음 단계로 진행할 수 있도록 합니다.
    """
    from proovy_agent.graph.state import CreditEntry

    async def _wrapped(state: ProovyState) -> dict:
        result = await pdf_callable(state)  # type: ignore[operator]
        plan = [s.model_copy() for s in state.plan]
        if plan and state.executing_step_idx < len(plan):
            plan[state.executing_step_idx] = plan[state.executing_step_idx].model_copy(
                update={"status": "done"}
            )
        credit = result.get("credit_log", []) if isinstance(result, dict) else []
        if not credit:
            credit = [CreditEntry(node="pdf_node", action="pdf", cost=1.0)]
        updates: dict = {**(result if isinstance(result, dict) else {}), "plan": plan}
        updates["credit_log"] = credit
        return updates

    return _wrapped


def _build() -> CompiledStateGraph:
    import logging

    from proovy_agent.graph.agents.core_solver.agent import core_solver
    from proovy_agent.graph.nodes.credit_settler import credit_settler
    from proovy_agent.graph.nodes.general_node import general_node
    from proovy_agent.graph.nodes.plan_executor import plan_executor
    from proovy_agent.graph.nodes.planner import planner
    from proovy_agent.graph.nodes.preprocessor import preprocessor
    from proovy_agent.graph.nodes.router import router, router_edge
    from proovy_agent.graph.nodes.video_node import video_node

    try:
        from proovy_agent.graph.nodes.pdf_node.pdf_node import PDFNode

        pdf_node = _pdf_step_done_wrapper(PDFNode())
    except (ImportError, ModuleNotFoundError, OSError) as e:
        logging.getLogger(__name__).warning("PDFNode 로드 실패 — 스텁으로 대체합니다. 원인: %s", e)
        pdf_node = _pdf_stub

    builder = StateGraph(ProovyState)

    builder.add_node("preprocessor", preprocessor)
    builder.add_node("router", router)
    builder.add_node("general_node", general_node)
    builder.add_node("planner", planner)
    builder.add_node("plan_executor", plan_executor)
    builder.add_node("core_solver", core_solver)
    builder.add_node("video_node", video_node)
    builder.add_node("pdf_node", pdf_node)
    builder.add_node("credit_settler", credit_settler)

    builder.add_edge(START, "preprocessor")
    builder.add_edge("preprocessor", "router")

    builder.add_conditional_edges(
        "router",
        router_edge,
        {"general_chat": "general_node", "math_task": "planner"},
    )

    builder.add_edge("planner", "plan_executor")

    for node in ["core_solver", "video_node", "pdf_node"]:
        builder.add_edge(node, "plan_executor")

    builder.add_edge("general_node", END)
    builder.add_edge("credit_settler", END)

    return builder.compile()


async def _pdf_stub(state: ProovyState) -> dict:
    """weasyprint 미설치 환경용 PDFNode 스텁."""
    from langchain_core.messages import AIMessage

    from proovy_agent.graph.state import CreditEntry

    plan = [s.model_copy() for s in state.plan]
    if plan and state.executing_step_idx < len(plan):
        plan[state.executing_step_idx] = plan[state.executing_step_idx].model_copy(
            update={"status": "done"}
        )
    return {
        "messages": [
            AIMessage(
                "PDF 해설지 기능은 이 환경에서 사용할 수 없습니다.",
                metadata={"display": "content"},
            )
        ],
        "credit_log": [CreditEntry(node="pdf_node", action="pdf", cost=0.0)],
        "plan": plan,
    }

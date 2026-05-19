"""LangGraph StateGraph 빌드."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from proovy_agent.graph.state import ProovyState

_graph: StateGraph | None = None


def get_graph() -> StateGraph:
    """그래프를 처음 호출 시 빌드하고 이후에는 캐시를 반환합니다."""
    global _graph
    if _graph is None:
        _graph = _build()
    return _graph


def _build() -> StateGraph:
    from proovy_agent.graph.agents.core_solver.agent import core_solver
    from proovy_agent.graph.nodes.credit_settler import credit_settler
    from proovy_agent.graph.nodes.general_node import general_node
    from proovy_agent.graph.nodes.pdf_node.pdf_node import PDFNode
    from proovy_agent.graph.nodes.plan_executor import plan_executor
    from proovy_agent.graph.nodes.planner import planner
    from proovy_agent.graph.nodes.preprocessor import preprocessor
    from proovy_agent.graph.nodes.router import router, router_edge
    from proovy_agent.graph.nodes.video_node import video_node

    builder = StateGraph(ProovyState)

    builder.add_node("preprocessor", preprocessor)
    builder.add_node("router", router)
    builder.add_node("general_node", general_node)
    builder.add_node("planner", planner)
    builder.add_node("plan_executor", plan_executor)
    builder.add_node("core_solver", core_solver)
    builder.add_node("video_node", video_node)
    builder.add_node("pdf_node", PDFNode())
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

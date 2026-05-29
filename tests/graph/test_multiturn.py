"""체크포인터 배선 및 멀티턴 동작 테스트."""

from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
import pytest
from typing_extensions import TypedDict

from proovy_agent.graph import builder as builder_module
from proovy_agent.graph.builder import build_graph


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder_module, "_graph", None)


# ── build_graph 체크포인터 주입 ──────────────────────────────────────────────


def test_build_graph_attaches_checkpointer() -> None:
    """build_graph(saver)가 컴파일된 그래프에 체크포인터를 부착한다."""
    saver = InMemorySaver()
    graph = build_graph(saver)
    assert graph.checkpointer is saver


def test_build_graph_without_checkpointer_is_none() -> None:
    """체크포인터 미주입 시 그래프에 체크포인터가 없다."""
    graph = build_graph(None)
    assert graph.checkpointer is None


# ── 멀티턴 동작 (InMemorySaver + 미니 그래프) ─────────────────────────────────


class _MiniState(TypedDict):
    messages: Annotated[list, add_messages]


def _mini_graph(checkpointer: InMemorySaver):
    """messages를 누적하는 최소 그래프 — 체크포인터 메커니즘 검증용."""

    def echo(_state: _MiniState) -> dict:
        return {"messages": [AIMessage(content="ack")]}

    builder = StateGraph(_MiniState)
    builder.add_node("echo", echo)
    builder.add_edge(START, "echo")
    return builder.compile(checkpointer=checkpointer)


async def test_multiturn_accumulates_with_same_thread_id() -> None:
    """같은 thread_id로 재호출하면 이전 턴 메시지가 누적된다."""
    graph = _mini_graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}

    await graph.ainvoke({"messages": [HumanMessage(content="turn1")]}, config=cfg)
    final = await graph.ainvoke({"messages": [HumanMessage(content="turn2")]}, config=cfg)

    contents = [m.content for m in final["messages"]]
    assert contents == ["turn1", "ack", "turn2", "ack"]


async def test_multiturn_isolated_by_thread_id() -> None:
    """다른 thread_id는 서로의 히스토리를 보지 않는다."""
    graph = _mini_graph(InMemorySaver())

    await graph.ainvoke(
        {"messages": [HumanMessage(content="turn1")]},
        config={"configurable": {"thread_id": "a"}},
    )
    final = await graph.ainvoke(
        {"messages": [HumanMessage(content="other")]},
        config={"configurable": {"thread_id": "b"}},
    )

    contents = [m.content for m in final["messages"]]
    assert contents == ["other", "ack"]


async def test_no_checkpointer_does_not_persist() -> None:
    """체크포인터가 없으면 매 호출이 빈 상태로 시작한다 (멀티턴 미동작 대조군)."""
    graph = _mini_graph(None)

    await graph.ainvoke({"messages": [HumanMessage(content="turn1")]})
    final = await graph.ainvoke({"messages": [HumanMessage(content="turn2")]})

    contents = [m.content for m in final["messages"]]
    assert contents == ["turn2", "ack"]

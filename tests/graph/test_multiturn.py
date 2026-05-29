"""체크포인터 배선 및 멀티턴 동작 테스트."""

from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
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


# ── 턴 단위 크레딧 정산 (실제 ProovyState + credit_settler + 체크포인터) ───────


async def test_multiturn_credit_settled_per_turn() -> None:
    """멀티턴에서 credit_settler가 누적이 아닌 이번 턴 비용만 정산한다."""
    from proovy_agent.graph.nodes.credit_settler import credit_settler
    from proovy_agent.graph.state import CreditEntry, ProovyState

    async def stub_solver(_state: ProovyState) -> dict:
        return {
            "credit_log": [
                CreditEntry(node="core_solver", action="llm", cost=2.0),
                CreditEntry(node="core_solver", action="exec", cost=3.0),
            ]
        }

    builder = StateGraph(ProovyState)
    builder.add_node("solver", stub_solver)
    builder.add_node("settler", credit_settler)
    builder.add_edge(START, "solver")
    builder.add_edge("solver", "settler")
    builder.add_edge("settler", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    cfg = {"configurable": {"thread_id": "t"}}
    await graph.ainvoke(ProovyState(user_id="u", thread_id="t"), config=cfg)
    s2 = await graph.ainvoke(ProovyState(user_id="u", thread_id="t"), config=cfg)

    # credit_log는 reducer라 누적, total_credit_cost는 스레드 누적 합계
    assert s2["total_credit_cost"] == 10.0
    # 정산 경계가 누적되어 다음 턴 시작점을 가리킴
    assert s2["settled_count"] == 4
    # 턴마다 정산 메시지 1개, 마지막(turn2)은 누적(10)이 아닌 이번 턴 비용(5)
    settler_msgs = [m for m in s2["messages"] if "cr 사용" in str(m.content)]
    assert len(settler_msgs) == 2
    assert settler_msgs[-1].content == "총 5.0cr 사용"


# ── 병렬 브랜치 EmitContext 격리 (_with_emit_context) ─────────────────────────


async def test_with_emit_context_isolates_parallel_branches() -> None:
    """동시 실행되는 두 브랜치가 서로의 node/step_idx를 오염시키지 않는다."""
    import asyncio
    import json

    from proovy_agent.common.sse.context import current_emit_context, current_emitter
    from proovy_agent.common.sse.emitter import SSEEmitter
    from proovy_agent.graph.builder import _with_emit_context
    from proovy_agent.graph.state import ProovyState

    seen: dict[str, tuple] = {}

    async def stub(_state: ProovyState) -> dict:
        before = current_emit_context.get()
        await asyncio.sleep(0.01)  # 두 브랜치 인터리브 유도
        after = current_emit_context.get()
        seen[before.node] = (before.node, before.step_idx, after.node, after.step_idx)
        return {}

    emitter = SSEEmitter(thread_id="t")
    tok = current_emitter.set(emitter)
    try:
        video = _with_emit_context("video_node", stub)
        pdf = _with_emit_context("pdf_node", stub)
        await asyncio.gather(
            video(ProovyState(executing_step_idx=1)),  # type: ignore[operator]
            pdf(ProovyState(executing_step_idx=2)),  # type: ignore[operator]
        )
    finally:
        current_emitter.reset(tok)

    # sleep 전후로 각 브랜치가 자기 컨텍스트 유지 — 상호 오염 없음
    assert seen["video_node"] == ("video_node", 1, "video_node", 1)
    assert seen["pdf_node"] == ("pdf_node", 2, "pdf_node", 2)

    # 자동 emit된 node_result도 브랜치별 올바른 node/step_idx를 가짐
    await emitter.close()
    events = [json.loads(e["data"]) async for e in emitter.stream()]
    node_results = {(e["node"], e["step_idx"]) for e in events if e["type"] == "node_result"}
    assert ("video_node", 1) in node_results
    assert ("pdf_node", 2) in node_results

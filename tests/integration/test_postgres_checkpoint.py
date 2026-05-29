"""Postgres 체크포인터 통합 테스트.

실제 AsyncPostgresSaver로 연결·setup()·serde 역직렬화·멀티턴 복원을 검증한다.
DATABASE_URL 미설정 시 skip — docker-compose.test.yml의 postgres 서비스로 실행한다:

    docker compose -f docker-compose.test.yml run --rm test-pg
"""

import os
import uuid

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
import pytest

from proovy_agent.common.checkpoint.saver import open_checkpointer
from proovy_agent.graph.nodes.credit_settler import credit_settler
from proovy_agent.graph.state import CreditEntry, PlanStep, ProovyState

pytestmark = pytest.mark.postgres


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL 미설정 — Postgres 통합 테스트 건너뜀")
    return url


async def _stub_solver(_state: ProovyState) -> dict:
    return {
        "credit_log": [
            CreditEntry(node="core_solver", action="llm", cost=2.0),
            CreditEntry(node="core_solver", action="exec", cost=3.0),
        ],
        "plan": [PlanStep(action="solve", description="검증", status="done")],
    }


def _build(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    builder = StateGraph(ProovyState)
    builder.add_node("solver", _stub_solver)
    builder.add_node("settler", credit_settler)
    builder.add_edge(START, "solver")
    builder.add_edge("solver", "settler")
    builder.add_edge("settler", END)
    return builder.compile(checkpointer=checkpointer)


async def _run_turn(database_url: str, thread_id: str) -> dict:
    # 매 턴 새 연결 — turn2는 Postgres에서 역직렬화로 state를 복원해야 한다.
    # 체크포인트 키는 프로덕션(solve.py)과 동일하게 user_id로 네임스페이스한다.
    async with open_checkpointer(database_url) as saver:
        graph = _build(saver)
        return await graph.ainvoke(
            ProovyState(user_id="u", thread_id=thread_id),
            config={"configurable": {"thread_id": f"u:{thread_id}"}},
        )


async def test_postgres_multiturn_restore_and_per_turn_settlement(database_url: str) -> None:
    """새 연결로 2턴 — PG 복원(타입 보존) + 멀티턴 누적 + 턴 단위 정산."""
    thread_id = f"pgtest-{uuid.uuid4()}"

    await _run_turn(database_url, thread_id)
    s2 = await _run_turn(database_url, thread_id)

    # 멀티턴 누적 (credit_log reducer가 Postgres 체크포인트로 유지)
    assert s2["total_credit_cost"] == 10.0
    assert s2["settled_count"] == 4

    # PG에서 복원된 커스텀 타입이 dict가 아닌 정상 Pydantic 타입 (serde allowlist)
    assert all(isinstance(e, CreditEntry) for e in s2["credit_log"])
    assert all(isinstance(p, PlanStep) for p in s2["plan"])

    # 턴 단위 정산 — turn2는 누적(10)이 아닌 이번 턴 비용(5)
    settler_msgs = [m for m in s2["messages"] if "cr 사용" in str(m.content)]
    assert len(settler_msgs) == 2  # PG 복원 후 메시지 중복/누락 없이 턴당 1개
    assert settler_msgs[-1].content == "총 5.0cr 사용"


async def test_postgres_threads_isolated(database_url: str) -> None:
    """다른 thread_id는 서로의 체크포인트를 공유하지 않는다."""
    tid_a = f"pgtest-{uuid.uuid4()}"
    tid_b = f"pgtest-{uuid.uuid4()}"

    await _run_turn(database_url, tid_a)
    s_b = await _run_turn(database_url, tid_b)

    # b는 첫 턴이므로 누적이 아닌 단일 턴 비용만
    assert s_b["total_credit_cost"] == 5.0
    assert s_b["settled_count"] == 2

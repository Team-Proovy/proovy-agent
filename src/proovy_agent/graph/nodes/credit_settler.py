"""CreditSettler 노드 — 크레딧 정산."""

from langchain_core.messages import AIMessage

from proovy_agent.common.sse.context import current_emitter
from proovy_agent.common.sse.events import CreditSettledPayload
from proovy_agent.graph.state import ProovyState


async def credit_settler(state: ProovyState) -> dict:
    emitter = current_emitter.get()

    # 이번 턴에 새로 쌓인 항목만 정산한다. 이전 턴은 settled_count까지 정산 완료.
    # settled_count는 operator.add reducer라 멀티턴 입력 덮어쓰기에도 살아남는다.
    turn_log = state.credit_log[state.settled_count :]
    turn_cost = sum(e.cost for e in turn_log)
    cumulative = sum(e.cost for e in state.credit_log)

    # 예약 흐름이 있을 때만 reserved/refunded를 채운다 (없으면 None — actual만 신뢰)
    reserved = state.credit_reserved or None
    refunded = max(state.credit_reserved - turn_cost, 0.0) if state.credit_reserved else None

    if emitter:
        await emitter.emit(
            CreditSettledPayload(
                actual=turn_cost,
                log=turn_log,
                reserved=reserved,
                refunded=refunded,
            )
        )

    return {
        "total_credit_cost": cumulative,
        # operator.add → settled_count + len(turn_log) = len(credit_log) (다음 턴 경계)
        "settled_count": len(turn_log),
        "messages": [AIMessage(f"총 {turn_cost}cr 사용", metadata={"display": "system"})],
    }

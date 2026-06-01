"""CreditSettler 노드 — 크레딧 정산."""

from decimal import Decimal
from uuid import UUID

from langchain_core.messages import AIMessage

from proovy_agent.common.sse.context import current_emitter
from proovy_agent.common.sse.events import CreditSettledPayload
from proovy_agent.features.credits import create_credit_ledger_client
from proovy_agent.graph.credit_pricing import synchronous_credit_amount
from proovy_agent.graph.runtime import current_credit_ledger_client
from proovy_agent.graph.state import ProovyState


async def credit_settler(state: ProovyState) -> dict:
    emitter = current_emitter.get()

    # 이번 턴에 새로 쌓인 항목만 정산한다. 이전 턴은 settled_count까지 정산 완료.
    # settled_count는 operator.add reducer라 멀티턴 입력 덮어쓰기에도 살아남는다.
    turn_log = state.credit_log[state.settled_count :]
    sync_cost = synchronous_credit_amount(turn_log)
    cumulative = sum(e.cost for e in state.credit_log)
    reserved: float | None = None
    refunded: float | None = None

    if state.hold_id:
        ledger = current_credit_ledger_client.get() or create_credit_ledger_client()
        if ledger is not None:
            finalized = await ledger.finalize_hold(
                state.user_id,
                UUID(state.hold_id),
                sync_cost,
            )
            reserved_amount = finalized.amount
            refunded_amount = max(reserved_amount - sync_cost, Decimal("0"))
            reserved = float(reserved_amount)
            refunded = float(refunded_amount)

    if emitter:
        await emitter.emit(
            CreditSettledPayload(
                actual=float(sync_cost),
                log=turn_log,
                reserved=reserved,
                refunded=refunded,
            )
        )

    return {
        "total_credit_cost": cumulative,
        # operator.add → settled_count + len(turn_log) = len(credit_log) (다음 턴 경계)
        "settled_count": len(turn_log),
        "messages": [
            AIMessage(
                f"총 {float(sync_cost)}cr 사용",
                metadata={"display": "system"},
            )
        ],
    }

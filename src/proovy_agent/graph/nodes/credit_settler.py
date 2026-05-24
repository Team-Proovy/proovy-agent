"""CreditSettler 노드 — 크레딧 정산."""

from langchain_core.messages import AIMessage

from proovy_agent.common.sse.context import current_emitter
from proovy_agent.graph.state import ProovyState


async def credit_settler(state: ProovyState) -> dict:
    emitter = current_emitter.get()
    total = sum(e.cost for e in state.credit_log)

    if emitter:
        await emitter.emit(
            "credit_settled",
            {"total": total, "log": [e.model_dump() for e in state.credit_log]},
        )

    return {
        "total_credit_cost": total,
        "messages": [AIMessage(f"총 {total}cr 사용", metadata={"display": "system"})],
    }

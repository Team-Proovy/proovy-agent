"""GeneralNode — 일반 대화 응답."""

from langchain_core.messages import AIMessage, SystemMessage

from proovy_agent.common.llm.client import get_llm
from proovy_agent.common.sse.context import current_emitter
from proovy_agent.common.sse.events import TokenPayload
from proovy_agent.graph.state import CreditEntry, ProovyState

_SYSTEM = "당신은 Proovy의 AI 어시스턴트입니다. 친절하고 간결하게 답변하세요."


async def general_node(state: ProovyState) -> dict:
    emitter = current_emitter.get()
    llm = get_llm("flash")

    content_chunks: list[str] = []
    async for chunk in llm.astream([SystemMessage(_SYSTEM), *state.messages]):
        chunk_text = chunk.content
        if isinstance(chunk_text, list):
            chunk_text = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in chunk_text
            )
        if chunk_text:
            if emitter:
                await emitter.emit(TokenPayload(delta=chunk_text))
            content_chunks.append(chunk_text)

    return {
        "messages": [AIMessage("".join(content_chunks), metadata={"display": "content"})],
        "credit_log": [
            CreditEntry(node="general_node", action="llm_call", model="flash", cost=0.5)
        ],
    }

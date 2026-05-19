"""Router 노드 — 의도 분류 (general_chat / math_task)."""

from typing import Literal

from langchain_core.messages import SystemMessage
from pydantic import BaseModel

from proovy_agent.common.llm.client import get_llm
from proovy_agent.graph.state import ProovyState

_SYSTEM = """당신은 사용자 메시지를 분류하는 분류기입니다.
메시지가 수학 문제 풀이 요청이면 'math_task', 일반 대화면 'general_chat'으로 분류하세요.

수학 문제: 계산, 방정식, 확률, 통계, 미적분, 기하 등 수학적 풀이가 필요한 모든 것
일반 대화: 인사, 날씨, 잡담, 수학이 아닌 모든 질문"""


class _RouterOutput(BaseModel):
    route: Literal["general_chat", "math_task"]


async def router(state: ProovyState) -> dict:
    llm = get_llm("flash")
    structured = llm.with_structured_output(_RouterOutput)
    result = await structured.ainvoke([SystemMessage(_SYSTEM), *state.messages])
    return {"route": result.route}


def router_edge(state: ProovyState) -> str:
    return state.route

"""Planner 노드 — plan 생성 + 모델/난이도 선택."""

from typing import Literal

from langchain_core.messages import SystemMessage
from pydantic import BaseModel

from proovy_agent.common.llm.client import get_llm
from proovy_agent.common.sse.context import current_emitter
from proovy_agent.graph.state import PlanStep, ProovyState

_SYSTEM = """당신은 수학 문제 풀이 계획을 세우는 Planner입니다.
사용자 메시지를 분석하여 JSON 형식으로 풀이 계획을 작성하세요.

steps 결정 기준:
- 수학 문제 풀이 → action: "solve", description에 목표 명시
- 해설 영상 요청(@해설영상, "영상 만들어줘") → action: "video" (solve 완료 후 실행)
- 해설지 PDF 요청(@해설지, "해설지 만들어줘") → action: "pdf" (solve 완료 후 실행)

difficulty 기준:
- easy: 사칙연산, 간단한 대수
- medium: 방정식, 확률/통계 기초, 수열
- hard: 미적분, 선형대수, 고급 통계, 증명

selected_model 기준:
- flash → easy
- sonnet → medium
- opus → hard

use_page: 이미지·그래프·코드 포함 예상이면 true, 짧은 풀이면 false"""


class _StepInput(BaseModel):
    action: Literal["solve", "video", "pdf"]
    description: str


class _PlannerOutput(BaseModel):
    steps: list[_StepInput]
    difficulty: Literal["easy", "medium", "hard"]
    selected_model: Literal["flash", "sonnet", "opus"]
    use_page: bool


async def planner(state: ProovyState) -> dict:
    llm = get_llm("flash")
    structured = llm.with_structured_output(_PlannerOutput)
    result = await structured.ainvoke([SystemMessage(_SYSTEM), *state.messages])

    plan = [PlanStep(action=s.action, description=s.description) for s in result.steps]

    emitter = current_emitter.get()
    if emitter and result.use_page:
        await emitter.emit("page_start", {"thread_id": state.thread_id})

    return {
        "plan": plan,
        "difficulty": result.difficulty,
        "selected_model": result.selected_model,
        "use_page": result.use_page,
    }

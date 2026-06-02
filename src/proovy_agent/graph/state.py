"""LangGraph state definitions."""

import operator
from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field


class PlanStep(BaseModel):
    action: Literal["solve", "video", "pdf"]
    description: str
    status: Literal["pending", "running", "done", "error"] = "pending"


_STATUS_RANK: dict[str, int] = {"pending": 0, "running": 1, "done": 2, "error": 2}


def _merge_plan(left: list[PlanStep], right: list[PlanStep]) -> list[PlanStep]:
    """병렬 브랜치 plan 업데이트를 스텝별로 가장 진행된 status로 병합한다."""
    if len(left) != len(right):
        return right
    return [
        r if _STATUS_RANK.get(r.status, 0) >= _STATUS_RANK.get(lo.status, 0) else lo
        for lo, r in zip(left, right, strict=True)
    ]


class CreditEntry(BaseModel):
    node: str
    action: str
    model: str | None = None
    cost: float


class VideoJobRef(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "canceled"]
    progress: dict[str, int] = Field(default_factory=dict)


class ProovyState(BaseModel):
    # Older checkpoints can contain retired state channels. Ignore them so
    # schema cleanup does not break existing threads.
    model_config = ConfigDict(extra="ignore")

    raw_input: dict = Field(default_factory=dict)
    user_id: str = ""
    thread_id: str = ""

    # Preprocessor
    ocr_text: str = ""
    ocr_confidence: float = 0.0
    tags: list[str] = Field(default_factory=list)
    user_solution: str | None = None

    # Router
    route: Literal["general_chat", "math_task"] = "math_task"
    use_page: bool = False

    # Planner
    plan: Annotated[list[PlanStep], _merge_plan] = Field(default_factory=list)
    executing_step_idx: int = 0
    selected_model: str = "flash"
    difficulty: Literal["easy", "medium", "hard"] = "easy"
    explanation_mode: Literal["full", "brief"] = "full"

    # CoreSolver
    current_phase: Literal["verify", "explain"] = "verify"

    # 크레딧
    hold_id: str | None = None
    credit_log: Annotated[list[CreditEntry], operator.add] = Field(default_factory=list)
    total_credit_cost: float = 0.0
    # 멀티턴에서 이미 정산한 credit_log 항목 수. operator.add reducer라 매 턴
    # 전체 state 입력(기본값 0)에 덮어써지지 않고 누적된다 — 턴 단위 정산 경계.
    settled_count: Annotated[int, operator.add] = 0

    # 영상 잡 참조 — state에는 job handle만 누적한다. 재접속/진행/결과 URL은
    # status API가 DB의 video_jobs 원본을 조회해 응답한다.
    video_jobs: Annotated[list[VideoJobRef], operator.add] = Field(default_factory=list)

    # 표시 데이터 단일 소스
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)

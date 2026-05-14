"""LangGraph state definitions."""

import operator
from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    action: Literal["solve", "video", "pdf"]
    description: str
    status: Literal["pending", "running", "done", "error"] = "pending"


class CreditEntry(BaseModel):
    node: str
    action: str
    model: str | None = None
    cost: float


class ProovyState(BaseModel):
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
    plan: list[PlanStep] = Field(default_factory=list)
    executing_step_idx: int = 0
    selected_model: str = "flash"
    difficulty: Literal["easy", "medium", "hard"] = "easy"

    # CoreSolver
    current_phase: Literal["verify", "explain"] = "verify"

    # 크레딧
    reservation_id: str = ""
    credit_reserved: float = 0.0
    credit_log: Annotated[list[CreditEntry], operator.add] = Field(default_factory=list)
    total_credit_cost: float = 0.0

    # 표시 데이터 단일 소스
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)

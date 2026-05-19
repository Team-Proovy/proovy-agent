"""문제 풀이 요청 스키마."""

from pydantic import BaseModel, Field


class SolveRequest(BaseModel):
    problem: str = Field(..., description="풀어야 할 수학 문제")
    user_id: str = Field(..., description="사용자 ID")
    thread_id: str | None = Field(None, description="대화 쓰레드 ID (없으면 자동 생성)")

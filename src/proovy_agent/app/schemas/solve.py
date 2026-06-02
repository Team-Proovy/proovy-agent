"""문제 풀이 요청 스키마."""

from pydantic import BaseModel, Field, field_validator


class SolveRequest(BaseModel):
    problem: str = Field(..., description="풀어야 할 수학 문제")
    user_id: str = Field(..., description="사용자 ID")
    thread_id: str | None = Field(None, description="대화 쓰레드 ID (없으면 자동 생성)")

    @field_validator("user_id")
    @classmethod
    def _no_colon_in_user_id(cls, v: str) -> str:
        # 체크포인트 키 f"{user_id}:{thread_id}"에서 user_id에 ':'가 있으면
        # (a:b, c)와 (a, b:c)가 같은 키로 충돌한다. user_id에서 ':'를 금지하면
        # 첫 ':'가 항상 경계를 명확히 가르므로 충돌이 불가능해진다.
        if ":" in v:
            raise ValueError("user_id must not contain ':'")
        return v

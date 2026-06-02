"""백엔드(Proovy-server) `/stream/v2` 요청 스키마.

백엔드 `ProovyAiRequest`(StreamInput 계약)와 동일한 lowerCamelCase 필드를 받는다.
AI 내부는 `message→problem`, `threadId→thread_id`, `userId→user_id`로 매핑한다.
files/credit/auth 관련 필드는 v1에서 수용만 하고 사용하지 않는다(백엔드 책임).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StreamInput(BaseModel):
    """백엔드가 `POST /stream/v2`로 보내는 요청 본문."""

    # 백엔드는 lowerCamelCase로 보낸다. alias로 받되 내부 snake_case 이름도 허용한다.
    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(..., description="사용자 입력(문제)")
    thread_id: str | None = Field(None, alias="threadId", description="대화 맥락 ID (없으면 생성)")
    user_id: str = Field("", alias="userId", description="사용자 ID")

    # v1 미사용 — 수용만 (백엔드가 크레딧·인증·파일을 책임)
    files_url: list[str] = Field(default_factory=list, alias="filesUrl")
    chosen_features: list[str] = Field(default_factory=list, alias="chosenFeatures")
    stream_tokens: bool = Field(True, alias="streamTokens")
    agent_config: dict[str, Any] = Field(default_factory=dict, alias="agentConfig")
    auth_token: str | None = Field(None, alias="authToken")

    @field_validator("user_id")
    @classmethod
    def _no_colon_in_user_id(cls, v: str) -> str:
        # 체크포인트 키 f"{user_id}:{thread_id}"의 첫 ':' 경계를 보호한다
        # (solve.py SolveRequest와 동일 규칙).
        if ":" in v:
            raise ValueError("userId must not contain ':'")
        return v

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
    # 필수·비공백. 빈 user_id면 체크포인트 키가 ":{thread_id}"로 수렴해 threadId를 아는
    # 호출자끼리 멀티턴 상태가 공유될 수 있다(/solve와 동일하게 필수로 강제).
    user_id: str = Field(..., alias="userId", min_length=1, description="사용자 ID")

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

    # 백엔드(Jackson)는 미선택 optional 필드를 null로 직렬화한다(예: 기능 미선택 시
    # chosenFeatures:null). null이 와도 422로 깨지지 않게 기본값으로 흡수한다.
    @field_validator("files_url", "chosen_features", mode="before")
    @classmethod
    def _null_list_to_empty(cls, v: object) -> object:
        return [] if v is None else v

    @field_validator("agent_config", mode="before")
    @classmethod
    def _null_dict_to_empty(cls, v: object) -> object:
        return {} if v is None else v

    @field_validator("stream_tokens", mode="before")
    @classmethod
    def _null_bool_to_default(cls, v: object) -> object:
        return True if v is None else v

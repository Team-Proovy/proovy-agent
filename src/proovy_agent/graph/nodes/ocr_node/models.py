"""OCR 데이터 모델 및 Pydantic 스키마 - VLM 기반."""


from pydantic import BaseModel, Field, field_validator


class OCROptions(BaseModel):
    """OCR 처리 옵션 및 설정."""

    # VLM 모델 설정
    primary_model: str = Field(
        default="flash",
        description="주 VLM 모델 (flash, sonnet, opus)",
    )
    fallback_model: str = Field(
        default="sonnet",
        description="폴백 VLM 모델",
    )
    target_language: str = Field(
        default="auto",
        description="목표 언어 ('ko', 'en', 'auto')",
    )

    # 기능 설정
    enable_math_mode: bool = Field(
        default=True,
        description="수학 수식 인식 모드 활성화",
    )
    enable_command_parsing: bool = Field(
        default=True,
        description="@커맨드 파싱 활성화",
    )

    # 품질 및 성능 설정
    quality_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="최소 품질 임계값",
    )
    max_processing_time: float = Field(
        default=30.0,
        gt=0,
        description="최대 처리 시간 (초)",
    )

    @field_validator("primary_model", "fallback_model")
    @classmethod
    def validate_model_names(cls, v: str) -> str:
        """VLM 모델명 유효성 검증."""
        valid_models = {"flash", "sonnet", "opus", "gpt4o-mini"}
        if v not in valid_models:
            raise ValueError(f"지원하지 않는 모델: {v}. 지원 모델: {valid_models}")
        return v


class VLMResult(BaseModel):
    """VLM 처리 결과."""

    model_name: str = Field(description="사용된 VLM 모델명")
    raw_text: str = Field(description="추출된 원본 텍스트")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="신뢰도 점수",
    )
    processing_time: float = Field(
        ge=0.0,
        description="처리 시간 (초)",
    )
    token_usage: dict[str, int] = Field(
        default_factory=dict,
        description="토큰 사용량 정보",
    )


class ProcessedImage(BaseModel):
    """전처리된 이미지 정보."""

    image_data: bytes = Field(description="처리된 이미지 데이터")
    format: str = Field(description="이미지 형식")
    width: int = Field(ge=1, description="이미지 너비")
    height: int = Field(ge=1, description="이미지 높이")
    dpi: int = Field(ge=1, description="이미지 DPI")
    preprocessing_applied: list[str] = Field(
        default_factory=list,
        description="적용된 전처리 단계들",
    )


class CommandTag(BaseModel):
    """파싱된 @커맨드 정보."""

    command: str = Field(description="정규화된 커맨드명")
    original_text: str = Field(description="원본 텍스트")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="파싱 신뢰도",
    )
    position: int = Field(
        ge=0,
        description="텍스트 내 위치",
    )


class MathExpression(BaseModel):
    """수학 수식 정보."""

    latex: str = Field(description="LaTeX 형식 수식")
    original: str = Field(description="원본 텍스트")
    position: tuple[int, int] = Field(description="텍스트 내 시작-끝 위치")

    @field_validator("position")
    @classmethod
    def validate_position(cls, v: tuple[int, int]) -> tuple[int, int]:
        """위치 정보 유효성 검증."""
        start, end = v
        if start < 0 or end < 0 or start > end:
            raise ValueError("잘못된 위치 범위입니다")
        return v


class PageResult(BaseModel):
    """PDF 페이지별 OCR 결과."""

    page_number: int = Field(ge=1, description="페이지 번호")
    text: str = Field(description="추출된 텍스트")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="페이지 신뢰도",
    )
    math_expressions: list[MathExpression] = Field(
        default_factory=list,
        description="페이지 내 수학 수식들",
    )


class ProcessingMetadata(BaseModel):
    """OCR 처리 메타데이터."""

    total_processing_time: float = Field(
        ge=0.0,
        description="전체 처리 시간 (초)",
    )
    model_used: str = Field(description="사용된 주 모델")
    fallback_used: bool = Field(
        default=False,
        description="폴백 모델 사용 여부",
    )
    pages_processed: int = Field(
        ge=1,
        description="처리된 페이지 수",
    )
    quality_score: float = Field(
        ge=0.0,
        le=1.0,
        description="전체 품질 점수",
    )
    language_detected: str = Field(description="감지된 언어")


class OCRRequest(BaseModel):
    """OCR 처리 요청 데이터."""

    raw_input: dict = Field(description="원본 입력 데이터")
    user_id: str = Field(description="사용자 ID")
    thread_id: str = Field(description="스레드 ID")
    options: OCROptions = Field(
        default_factory=OCROptions,
        description="OCR 처리 옵션",
    )

    @field_validator("raw_input")
    @classmethod
    def validate_raw_input(cls, v: dict) -> dict:
        """입력 데이터 유효성 검증."""
        if not v:
            raise ValueError("입력 데이터가 비어있습니다")
        return v


class OCRResult(BaseModel):
    """최종 OCR 처리 결과."""

    extracted_text: str = Field(description="통합된 추출 텍스트")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="전체 신뢰도",
    )
    command_tags: list[CommandTag] = Field(
        default_factory=list,
        description="파싱된 @커맨드들",
    )
    math_expressions: list[MathExpression] = Field(
        default_factory=list,
        description="수학 수식들",
    )
    pages: list[PageResult] | None = Field(
        default=None,
        description="PDF 페이지별 결과",
    )
    language: str = Field(description="감지된 주 언어")
    processing_metadata: ProcessingMetadata = Field(description="처리 메타데이터")

    @field_validator("extracted_text")
    @classmethod
    def validate_text_content(cls, v: str) -> str:
        """추출된 텍스트 유효성 검증."""
        if not v.strip():
            raise ValueError("추출된 텍스트가 비어있습니다")
        return v

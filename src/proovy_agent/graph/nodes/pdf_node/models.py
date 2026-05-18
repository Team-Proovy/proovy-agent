"""PDF 해설지 생성 관련 데이터 모델."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ContentSection(BaseModel):
    """해설 섹션 구조화 데이터."""

    title: str
    content_type: Literal["text", "math", "image", "code"]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    order: int = 0  # 섹션 순서

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        """콘텐츠가 비어있지 않은지 검증."""
        if not v.strip():
            raise ValueError("콘텐츠는 비어있을 수 없습니다")
        return v.strip()


class PDFConfig(BaseModel):
    """PDF 생성 설정."""

    page_size: str = "A4"
    margin: dict[str, str] = Field(
        default_factory=lambda: {"top": "2cm", "bottom": "2cm", "left": "2cm", "right": "2cm"}
    )
    dpi: int = 300
    optimize_images: bool = True
    template_name: str = "solution.html"
    css_file: str = "solution.css"
    additional_css: str | None = None

    @field_validator("dpi")
    @classmethod
    def dpi_valid_range(cls, v: int) -> int:
        """DPI가 유효 범위 내에 있는지 검증."""
        if v < 72 or v > 600:
            raise ValueError("DPI는 72-600 범위여야 합니다")
        return v


class PDFRequest(BaseModel):
    """PDF 생성 요청 데이터."""

    thread_id: str
    user_id: str
    content_sections: list[ContentSection]
    config: PDFConfig = Field(default_factory=PDFConfig)
    request_id: str | None = None

    @property
    def sections(self) -> list[ContentSection]:
        """content_sections의 별칭 (backwards compatibility)."""
        return self.content_sections

    @field_validator("thread_id", "user_id")
    @classmethod
    def ids_not_empty(cls, v: str) -> str:
        """ID가 비어있지 않은지 검증."""
        if not v.strip():
            raise ValueError("thread_id와 user_id는 필수입니다")
        return v.strip()

    @field_validator("content_sections")
    @classmethod
    def sections_not_empty(cls, v: list[ContentSection]) -> list[ContentSection]:
        """섹션이 최소 하나 이상 있는지 검증."""
        if not v:
            raise ValueError("최소 하나의 콘텐츠 섹션이 필요합니다")
        return v

    def to_template_data(self) -> "TemplateData":
        """PDFRequest를 TemplateData로 변환.

        Returns:
            템플릿 렌더링에 사용할 TemplateData 인스턴스
        """
        # 첫 번째 섹션의 제목을 사용하거나 기본값 사용
        title = "이차방정식 해법 테스트"
        if self.content_sections and self.content_sections[0].title:
            title = self.content_sections[0].title

        return TemplateData(
            title=title,
            thread_id=self.thread_id,
            user_id=self.user_id,
            sections=self.content_sections,
        )


class PDFResult(BaseModel):
    """PDF 생성 결과."""

    pdf_data: bytes
    file_size: int
    generation_time_ms: float = 0.0
    request_id: str | None = None
    success: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    file_path: str | None = None
    download_url: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)

    @field_validator("file_size")
    @classmethod
    def file_size_positive(cls, v: int, values) -> int:
        """파일 크기가 양수인지 검증 (실패 시에는 0 허용)."""
        success = values.data.get("success", True)
        if not success and v == 0:
            return v  # 실패 시 file_size=0 허용
        if v <= 0:
            raise ValueError("파일 크기는 양수여야 합니다")
        return v

    @field_validator("generation_time_ms")
    @classmethod
    def generation_time_positive(cls, v: float) -> float:
        """생성 시간이 양수인지 검증."""
        if v < 0:
            raise ValueError("생성 시간은 음수일 수 없습니다")
        return v

    @property
    def file_size_mb(self) -> float:
        """파일 크기를 MB 단위로 반환."""
        return self.file_size / (1024 * 1024)

    @property
    def file_size_display(self) -> str:
        """사용자 친화적 파일 크기 표시."""
        if self.file_size < 1024:
            return f"{self.file_size}B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f}KB"
        else:
            return f"{self.file_size_mb:.1f}MB"


class TemplateData(BaseModel):
    """템플릿 렌더링용 데이터."""

    title: str
    thread_id: str
    user_id: str
    sections: list[ContentSection]
    generated_at: datetime = Field(default_factory=datetime.now)

    @property
    def formatted_date(self) -> str:
        """한국어 형식의 생성 일시."""
        return self.generated_at.strftime("%Y년 %m월 %d일 %H:%M")

"""PDF 해설지 생성 관련 예외 처리."""

from typing import Any


class PDFError(Exception):
    """PDF 생성 관련 베이스 예외."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """예외 초기화.

        Args:
            message: 사용자 친화적 에러 메시지
            details: 디버깅용 상세 정보
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        """사용자 친화적 에러 메시지 반환."""
        return self.message

    @property
    def recovery_suggestion(self) -> str:
        """복구 제안 메시지."""
        return "잠시 후 다시 시도해주세요."


class ContentParsingError(PDFError):
    """State.messages 파싱 실패."""

    def __init__(self, message: str = "풀이 내용을 처리하는 중 오류가 발생했습니다",
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details)

    @property
    def recovery_suggestion(self) -> str:
        """파싱 실패 시 복구 제안."""
        return "원본 텍스트로 PDF를 생성하거나, 풀이를 다시 요청해주세요."


class TemplateRenderingError(PDFError):
    """HTML 템플릿 렌더링 실패."""

    def __init__(self, template_name: str = "unknown",
                 message: str = "PDF 템플릿 처리 중 오류가 발생했습니다",
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details)
        self.template_name = template_name

    @property
    def recovery_suggestion(self) -> str:
        """템플릿 렌더링 실패 시 복구 제안."""
        return "기본 템플릿으로 다시 시도하거나, 관리자에게 문의해주세요."


class PDFGenerationError(PDFError):
    """HTML → PDF 변환 실패."""

    def __init__(self, message: str = "PDF 파일 생성 중 오류가 발생했습니다",
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details)

    @property
    def recovery_suggestion(self) -> str:
        """PDF 생성 실패 시 복구 제안."""
        return "HTML 파일로 다운로드하거나, 잠시 후 다시 시도해주세요."


class FileStorageError(PDFError):
    """파일 저장/접근 실패."""

    def __init__(self, file_path: str = "",
                 message: str = "파일 저장 중 오류가 발생했습니다",
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details)
        self.file_path = file_path

    @property
    def recovery_suggestion(self) -> str:
        """파일 저장 실패 시 복구 제안."""
        return "디스크 공간을 확인하거나, 잠시 후 다시 시도해주세요."


class PDFConfigurationError(PDFError):
    """PDF 설정 오류."""

    def __init__(self, config_key: str = "",
                 message: str = "PDF 생성 설정에 오류가 있습니다",
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details)
        self.config_key = config_key

    @property
    def recovery_suggestion(self) -> str:
        """설정 오류 시 복구 제안."""
        return "기본 설정으로 다시 시도하거나, 설정 값을 확인해주세요."


class PDFValidationError(PDFError):
    """PDF 유효성 검증 실패."""

    def __init__(self, validation_type: str = "general",
                 message: str = "생성된 PDF 파일에 문제가 있습니다",
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details)
        self.validation_type = validation_type

    @property
    def recovery_suggestion(self) -> str:
        """유효성 검증 실패 시 복구 제안."""
        return "다른 형식으로 다운로드하거나, 관리자에게 문의해주세요."


def handle_pdf_error(error: Exception) -> PDFError:
    """일반 예외를 PDF 예외로 변환.

    Args:
        error: 발생한 원본 예외

    Returns:
        적절한 PDFError 하위 클래스 인스턴스
    """
    if isinstance(error, PDFError):
        return error

    # 일반적인 에러 타입별 분류
    error_message = str(error)
    error_type = type(error).__name__

    details = {
        "original_error": error_message,
        "error_type": error_type
    }

    # 파일 관련 에러
    if "permission" in error_message.lower() or "access" in error_message.lower():
        return FileStorageError(
            message="파일 접근 권한 오류가 발생했습니다",
            details=details
        )

    # 메모리 관련 에러
    if "memory" in error_message.lower() or "out of memory" in error_message.lower():
        return PDFGenerationError(
            message="메모리 부족으로 PDF 생성에 실패했습니다",
            details=details
        )

    # 템플릿 관련 에러
    if "template" in error_message.lower() or "jinja" in error_message.lower():
        return TemplateRenderingError(
            message="템플릿 처리 중 오류가 발생했습니다",
            details=details
        )

    # 기본 PDF 에러로 래핑
    return PDFError(
        message=f"알 수 없는 오류가 발생했습니다: {error_message}",
        details=details
    )

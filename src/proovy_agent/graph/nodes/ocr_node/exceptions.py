"""OCR system exception classes."""


class OCRError(Exception):
    """Base exception for all OCR-related errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (Details: {self.details})"
        return self.message


class ImageProcessingError(OCRError):
    """Raised when image preprocessing fails."""

    def __init__(
        self,
        message: str = "Image preprocessing failed",
        details: dict | None = None,
        recovery_suggestion: str | None = None,
    ) -> None:
        super().__init__(message, details)
        self.recovery_suggestion = (
            recovery_suggestion or "Try with a different image format or quality"
        )

    def __str__(self) -> str:
        base_msg = super().__str__()
        return f"{base_msg}. Suggestion: {self.recovery_suggestion}"


class VLMProcessingError(OCRError):
    """VLM 처리 실패 예외."""

    def __init__(
        self,
        model_name: str,
        message: str = "VLM 처리에 실패했습니다",
        details: dict | None = None,
        is_recoverable: bool = True,
    ) -> None:
        super().__init__(message, details)
        self.model_name = model_name
        self.is_recoverable = is_recoverable

    def __str__(self) -> str:
        base_msg = super().__str__()
        recovery_msg = (
            "폴백 모델 사용 가능" if self.is_recoverable else "폴백 불가능"
        )
        return f"{base_msg} (모델: {self.model_name}, {recovery_msg})"


class FileConversionError(OCRError):
    """파일 변환 실패 예외."""

    def __init__(
        self,
        file_type: str,
        message: str | None = None,
        details: dict | None = None,
    ) -> None:
        if message is None:
            message = f"{file_type} 파일 변환에 실패했습니다"
        super().__init__(message, details)
        self.file_type = file_type


class QualityThresholdError(OCRError):
    """품질 기준 미달 예외."""

    def __init__(
        self,
        threshold: float,
        actual_score: float,
        message: str | None = None,
        details: dict | None = None,
    ) -> None:
        if message is None:
            message = "OCR 품질이 기준에 미달합니다"
        super().__init__(message, details)
        self.threshold = threshold
        self.actual_score = actual_score

    def __str__(self) -> str:
        base_msg = super().__str__()
        return f"{base_msg} (기준: {self.threshold}, 실제: {self.actual_score})"


class LanguageDetectionError(OCRError):
    """언어 감지 실패 예외."""

    def __init__(
        self,
        message: str = "언어 감지에 실패했습니다",
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details)


class MathParsingError(OCRError):
    """Raised when mathematical expression post-processing fails."""

    def __init__(
        self,
        message: str = "Mathematical expression parsing failed",
        details: dict | None = None,
        original_text: str | None = None,
    ) -> None:
        super().__init__(message, details)
        self.original_text = original_text

    def __str__(self) -> str:
        base_msg = super().__str__()
        if self.original_text:
            return f"{base_msg} (Original text: '{self.original_text[:100]}...')"
        return base_msg


class CommandParsingError(OCRError):
    """Raised when @command parsing fails."""

    def __init__(
        self,
        message: str = "Command parsing failed",
        details: dict | None = None,
        invalid_commands: list[str] | None = None,
    ) -> None:
        super().__init__(message, details)
        self.invalid_commands = invalid_commands or []

    def __str__(self) -> str:
        base_msg = super().__str__()
        if self.invalid_commands:
            return f"{base_msg} (Invalid commands: {', '.join(self.invalid_commands)})"
        return base_msg


class ConfidenceThresholdError(OCRError):
    """Raised when all OCR results fall below confidence threshold."""

    def __init__(
        self,
        threshold: float,
        highest_confidence: float,
        message: str | None = None,
        details: dict | None = None,
    ) -> None:
        if message is None:
            message = f"All OCR results below confidence threshold {threshold}"
        super().__init__(message, details)
        self.threshold = threshold
        self.highest_confidence = highest_confidence

    def __str__(self) -> str:
        base_msg = super().__str__()
        return f"{base_msg} (Threshold: {self.threshold}, Highest: {self.highest_confidence})"


class OCRTimeoutError(OCRError):
    """OCR 처리 시간 초과 예외."""

    def __init__(
        self,
        timeout_seconds: float,
        message: str | None = None,
        details: dict | None = None,
    ) -> None:
        if message is None:
            message = f"OCR 처리가 {timeout_seconds}초 후 시간 초과되었습니다"
        super().__init__(message, details)
        self.timeout_seconds = timeout_seconds

    def __str__(self) -> str:
        base_msg = super().__str__()
        return f"{base_msg}. 제안: 이미지 복잡도를 줄이거나 시간 제한을 늘려보세요"


class OCRResourceError(OCRError):
    """리소스 제약으로 인한 OCR 처리 실패 예외."""

    def __init__(
        self,
        resource_type: str,
        message: str | None = None,
        details: dict | None = None,
    ) -> None:
        if message is None:
            message = f"{resource_type} 리소스 제약으로 OCR 처리에 실패했습니다"
        super().__init__(message, details)
        self.resource_type = resource_type

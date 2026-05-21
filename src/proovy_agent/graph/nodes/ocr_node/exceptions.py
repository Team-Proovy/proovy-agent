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


class OCREngineError(OCRError):
    """Raised when a specific OCR engine fails."""

    def __init__(
        self,
        engine_name: str,
        message: str = "OCR engine processing failed",
        details: dict | None = None,
        is_recoverable: bool = True,
    ) -> None:
        super().__init__(message, details)
        self.engine_name = engine_name
        self.is_recoverable = is_recoverable

    def __str__(self) -> str:
        base_msg = super().__str__()
        recovery_msg = (
            "Can try fallback engines" if self.is_recoverable else "No fallback available"
        )
        return f"{base_msg} (Engine: {self.engine_name}, {recovery_msg})"


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
    """Raised when OCR processing exceeds time limit."""

    def __init__(
        self, timeout_seconds: float, message: str | None = None, details: dict | None = None
    ) -> None:
        if message is None:
            message = f"OCR processing timed out after {timeout_seconds} seconds"
        super().__init__(message, details)
        self.timeout_seconds = timeout_seconds


class OCRResourceError(OCRError):
    """Raised when OCR processing fails due to resource constraints."""

    def __init__(
        self, resource_type: str, message: str | None = None, details: dict | None = None
    ) -> None:
        if message is None:
            message = f"OCR processing failed due to {resource_type} constraints"
        super().__init__(message, details)
        self.resource_type = resource_type

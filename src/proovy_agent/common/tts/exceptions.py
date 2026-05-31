"""Text-to-speech exception hierarchy."""


class TTSError(Exception):
    """Base exception for TTS provider failures."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "tts",
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.detail = detail


class InworldTimestampFormatError(TTSError):
    """Raised when Inworld timestamp metadata does not match the expected schema."""

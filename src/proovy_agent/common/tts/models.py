"""Text-to-speech result models."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from pydantic import BaseModel, Field, model_validator


class WordTimestamp(BaseModel):
    """Timing metadata for one spoken token."""

    word: str = Field(..., min_length=1)
    start: float = Field(..., ge=0.0)
    end: float = Field(..., ge=0.0)

    @model_validator(mode="after")
    def validate_time_order(self) -> WordTimestamp:
        """Ensure the token ends after it starts."""
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class TTSResult(BaseModel):
    """Output of TTS synthesis for one narration segment."""

    audio_path: Path
    duration_seconds: float = Field(..., ge=0.0)
    word_timestamps: list[WordTimestamp] = Field(default_factory=list)

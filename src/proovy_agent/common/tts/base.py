"""TTS provider abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from proovy_agent.common.tts.models import TTSResult


class TTSProvider(ABC):
    """Pluggable text-to-speech provider."""

    @abstractmethod
    async def synthesize(self, text: str, *, output_path: Path) -> TTSResult:
        """Synthesize speech to a file and return timing metadata."""

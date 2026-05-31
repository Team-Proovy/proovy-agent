"""Inworld TTS client and WORD timestamp mapping."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping, Sequence
import json
import logging
import subprocess
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from proovy_agent.common.tts.base import TTSProvider
from proovy_agent.common.tts.exceptions import InworldTimestampFormatError, TTSError
from proovy_agent.common.tts.models import TTSResult, WordTimestamp

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

INWORLD_VOICE_URL = "https://api.inworld.ai/tts/v1/voice"


class _InworldSettingsProtocol(Protocol):
    """Settings fields required by the Inworld TTS client."""

    inworld_tts_api_key: str
    video_tts_model: str
    video_tts_voice: str
    video_tts_speaking_rate: float
    video_tts_temperature: float
    video_tts_timestamp_type: str
    video_tts_timeout_seconds: float


def _ffprobe_duration_seconds(path: Path) -> float:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        meta = json.loads(completed.stdout)
        return float(meta["format"]["duration"])
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        KeyError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        logger.warning("ffprobe failed, using fallback duration: %s", exc)
        return 1.0


def _ffmpeg_convert_to_wav(src: Path, dst: Path) -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), str(dst)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise TTSError(
            "ffmpeg is required to convert Inworld TTS audio to WAV.",
            detail=str(exc),
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise TTSError(
            "ffmpeg failed while converting Inworld TTS audio",
            detail=(exc.stderr or "")[:500],
        ) from exc


def _build_payload(settings: _InworldSettingsProtocol, text: str) -> dict[str, Any]:
    """Build the Inworld synthesize request payload."""
    payload: dict[str, Any] = {
        "text": text,
        "voiceId": (settings.video_tts_voice or "Hyunwoo").strip() or "Hyunwoo",
        "modelId": (settings.video_tts_model or "inworld-tts-1.5-max").strip()
        or "inworld-tts-1.5-max",
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": float(settings.video_tts_speaking_rate),
        },
        "temperature": float(settings.video_tts_temperature),
    }
    timestamp_type = (settings.video_tts_timestamp_type or "WORD").strip()
    if timestamp_type:
        payload["timestampType"] = timestamp_type
    return payload


def _parse_inworld_word_timestamps(
    timestamp_info: Mapping[str, Any] | None,
) -> list[WordTimestamp]:
    """Map Inworld WORD alignment metadata into WordTimestamp models."""
    if timestamp_info is None:
        return []

    alignment = _mapping_value(
        timestamp_info,
        "wordAlignment",
        "word_alignment",
    )
    if alignment is not None:
        return _parse_parallel_word_alignment(alignment)

    legacy_words = timestamp_info.get("words")
    if isinstance(legacy_words, Sequence) and not isinstance(
        legacy_words,
        str | bytes,
    ):
        return _parse_legacy_word_objects(legacy_words)

    raise InworldTimestampFormatError("Inworld WORD timestamp metadata is missing wordAlignment")


def _parse_parallel_word_alignment(
    alignment: Mapping[str, Any],
) -> list[WordTimestamp]:
    words = _sequence_value(alignment, "words")
    starts = _sequence_value(
        alignment,
        "wordStartTimeSeconds",
        "word_start_time_seconds",
    )
    ends = _sequence_value(
        alignment,
        "wordEndTimeSeconds",
        "word_end_time_seconds",
    )

    if words is None or starts is None or ends is None:
        raise InworldTimestampFormatError(
            "Inworld WORD timestamp alignment is missing words/start/end arrays"
        )
    if len(words) != len(starts) or len(words) != len(ends):
        raise InworldTimestampFormatError(
            "Inworld WORD timestamp arrays must have the same length",
            detail=f"words={len(words)}, starts={len(starts)}, ends={len(ends)}",
        )

    timestamps: list[WordTimestamp] = []
    for word, start, end in zip(words, starts, ends, strict=True):
        normalized_word = _normalize_word(word)
        if not normalized_word:
            continue
        timestamps.append(
            WordTimestamp(
                word=normalized_word,
                start=float(start),
                end=float(end),
            )
        )
    return timestamps


def _parse_legacy_word_objects(words: Sequence[Any]) -> list[WordTimestamp]:
    timestamps: list[WordTimestamp] = []
    for item in words:
        if not isinstance(item, Mapping):
            continue
        normalized_word = _normalize_word(item.get("word") or item.get("token") or item.get("text"))
        if not normalized_word:
            continue
        start = item.get("startTime", item.get("start_time", item.get("start", 0)))
        end = item.get("endTime", item.get("end_time", item.get("end", 0)))
        timestamps.append(
            WordTimestamp(
                word=normalized_word,
                start=float(start),
                end=float(end),
            )
        )
    return timestamps


def _mapping_value(
    data: Mapping[str, Any],
    *keys: str,
) -> Mapping[str, Any] | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _sequence_value(
    data: Mapping[str, Any],
    *keys: str,
) -> Sequence[Any] | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            return value
    return None


def _normalize_word(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


class InworldTTS(TTSProvider):
    """Inworld non-streaming TTS with WORD timestamp mapping."""

    def __init__(self, settings: _InworldSettingsProtocol) -> None:
        api_key = (settings.inworld_tts_api_key or "").strip()
        if not api_key:
            raise TTSError("Inworld TTS requires INWORLD_TTS_API_KEY")
        self._settings = settings
        self._auth_header = f"Basic {api_key}"

    async def synthesize(self, text: str, *, output_path: Path) -> TTSResult:
        """Synthesize text and return audio metadata with word timestamps."""
        if not text.strip():
            raise TTSError("TTS text is empty")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = _build_payload(self._settings, text)
        data = await self._post_synthesize(payload)

        b64 = data.get("audioContent")
        if not isinstance(b64, str) or not b64.strip():
            raise TTSError(
                "Inworld TTS response missing audioContent",
                detail=str(data)[:500],
            )

        try:
            audio_bytes = base64.b64decode(b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise TTSError(
                "Inworld TTS audioContent is not valid base64",
                detail=str(exc)[:800],
            ) from exc
        if not audio_bytes:
            raise TTSError("Inworld TTS returned empty audio")

        timestamp_info = data.get("timestampInfo")
        if payload.get("timestampType") == "WORD" and not isinstance(
            timestamp_info,
            Mapping,
        ):
            raise TTSError("Inworld TTS response missing timestampInfo.wordAlignment")
        word_timestamps = _parse_inworld_word_timestamps(timestamp_info)

        mp3_path = output_path.with_suffix(".mp3")
        await asyncio.to_thread(mp3_path.write_bytes, audio_bytes)
        try:
            duration = await asyncio.to_thread(_ffprobe_duration_seconds, mp3_path)
            await asyncio.to_thread(_ffmpeg_convert_to_wav, mp3_path, output_path)
        finally:
            await asyncio.to_thread(mp3_path.unlink, missing_ok=True)

        return TTSResult(
            audio_path=output_path,
            duration_seconds=duration,
            word_timestamps=word_timestamps,
        )

    async def _post_synthesize(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
            "User-Agent": "proovy-agent",
        }
        timeout = httpx.Timeout(self._settings.video_tts_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    INWORLD_VOICE_URL,
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise TTSError(
                f"Inworld TTS request failed: {exc}",
                detail=str(exc)[:800],
            ) from exc

        if response.status_code >= 400:
            raise TTSError(
                f"Inworld TTS HTTP {response.status_code}",
                detail=(response.text or "")[:800],
            )

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise TTSError(
                "Inworld TTS returned invalid JSON",
                detail=str(exc)[:800],
            ) from exc
        if not isinstance(data, dict):
            raise TTSError(
                "Inworld TTS returned an unexpected JSON value",
                detail=repr(type(data)),
            )
        return data

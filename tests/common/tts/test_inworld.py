"""Tests for Inworld TTS timestamp mapping."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proovy_agent.common.config import Settings
from proovy_agent.common.tts.exceptions import InworldTimestampFormatError, TTSError
from proovy_agent.common.tts.inworld import (
    InworldTTS,
    _build_payload,
    _parse_inworld_word_timestamps,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "inworld_word_timestamp_response.json"


def _load_response_dump() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def test_parse_inworld_word_alignment_dump_maps_words() -> None:
    """Fixture dump maps Inworld WORD arrays into WordTimestamp values."""
    dump = _load_response_dump()

    timestamps = _parse_inworld_word_timestamps(dump["timestampInfo"])

    assert [timestamp.model_dump() for timestamp in timestamps] == [
        {"word": "이차방정식은", "start": 0.2, "end": 1.32},
        {"word": "영입니다", "start": 1.32, "end": 2.0},
        {"word": ".", "start": 2.0, "end": 2.25},
    ]


def test_parse_inworld_word_alignment_supports_sdk_snake_case_dump() -> None:
    """Snake-case SDK dumps are normalized to the same word timestamp model."""
    timestamp_info = {
        "word_alignment": {
            "words": ["엑스", " ", "제곱"],
            "word_start_time_seconds": [0.1, 0.4, 0.4],
            "word_end_time_seconds": [0.4, 0.4, 0.9],
        }
    }

    timestamps = _parse_inworld_word_timestamps(timestamp_info)

    assert [timestamp.model_dump() for timestamp in timestamps] == [
        {"word": "엑스", "start": 0.1, "end": 0.4},
        {"word": "제곱", "start": 0.4, "end": 0.9},
    ]


def test_parse_inworld_word_alignment_rejects_array_length_mismatch() -> None:
    """Array length changes fail loudly so response-format regressions are visible."""
    timestamp_info = {
        "wordAlignment": {
            "words": ["엑스", "제곱"],
            "wordStartTimeSeconds": [0.1],
            "wordEndTimeSeconds": [0.4, 0.9],
        }
    }

    with pytest.raises(InworldTimestampFormatError, match="same length"):
        _parse_inworld_word_timestamps(timestamp_info)


def test_parse_inworld_word_alignment_rejects_unknown_shape() -> None:
    """Unknown timestamp shapes fail instead of silently losing word timings."""
    with pytest.raises(InworldTimestampFormatError, match="missing wordAlignment"):
        _parse_inworld_word_timestamps({"characterAlignment": {"characters": ["x"]}})


def test_parse_inworld_word_alignment_rejects_empty_timestamp_info() -> None:
    """Empty timestampInfo is a malformed WORD response, not a valid no-op."""
    with pytest.raises(InworldTimestampFormatError, match="missing wordAlignment"):
        _parse_inworld_word_timestamps({})


def test_parse_inworld_word_alignment_supports_legacy_word_objects() -> None:
    """The design-doc object-array shape remains accepted for compatibility."""
    timestamp_info = {
        "words": [
            {"word": "엑스", "startTime": 0.1, "endTime": 0.4},
            {"token": " ", "startTime": 0.4, "endTime": 0.4},
            {"token": "제곱", "start": 0.4, "end": 0.9},
        ]
    }

    timestamps = _parse_inworld_word_timestamps(timestamp_info)

    assert [timestamp.model_dump() for timestamp in timestamps] == [
        {"word": "엑스", "start": 0.1, "end": 0.4},
        {"word": "제곱", "start": 0.4, "end": 0.9},
    ]


def test_build_payload_uses_word_timestamp_defaults() -> None:
    """Inworld requests enable WORD timestamps with the Korean default voice."""
    settings = Settings(_env_file=None)

    payload = _build_payload(settings, "이차방정식은 영입니다.")

    assert payload["voiceId"] == "Hyunwoo"
    assert payload["modelId"] == "inworld-tts-1.5-max"
    assert payload["audioConfig"]["audioEncoding"] == "MP3"
    assert payload["audioConfig"]["speakingRate"] == 0.95
    assert payload["timestampType"] == "WORD"


@pytest.mark.asyncio
async def test_synthesize_maps_word_timestamps_from_response_dump(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Client synthesis returns TTSResult.word_timestamps from the dump response."""
    monkeypatch.setenv("INWORLD_TTS_API_KEY", "dummy")
    settings = Settings(_env_file=None)
    dump = _load_response_dump()

    monkeypatch.setattr(
        "proovy_agent.common.tts.inworld._ffprobe_duration_seconds",
        lambda _path: 2.25,
    )

    def _fake_convert(src: Path, dst: Path) -> None:
        assert src.read_bytes() == b"fake-mp3-bytes"
        dst.write_bytes(b"fake-wav")

    monkeypatch.setattr(
        "proovy_agent.common.tts.inworld._ffmpeg_convert_to_wav",
        _fake_convert,
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = ""
    mock_response.json.return_value = dump

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    output_path = tmp_path / "segment.wav"
    with patch(
        "proovy_agent.common.tts.inworld.httpx.AsyncClient",
        return_value=mock_client,
    ):
        result = await InworldTTS(settings).synthesize(
            "이차방정식은 영입니다.",
            output_path=output_path,
        )

    assert result.audio_path == output_path
    assert result.duration_seconds == 2.25
    assert output_path.read_bytes() == b"fake-wav"
    assert [timestamp.model_dump() for timestamp in result.word_timestamps] == [
        {"word": "이차방정식은", "start": 0.2, "end": 1.32},
        {"word": "영입니다", "start": 1.32, "end": 2.0},
        {"word": ".", "start": 2.0, "end": 2.25},
    ]
    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["json"]["timestampType"] == "WORD"


@pytest.mark.asyncio
async def test_synthesize_requires_timestamp_info_for_word_requests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A WORD request without timestampInfo is treated as a provider contract break."""
    monkeypatch.setenv("INWORLD_TTS_API_KEY", "dummy")
    settings = Settings(_env_file=None)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = ""
    mock_response.json.return_value = {"audioContent": "ZmFrZS1tcDMtYnl0ZXM="}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "proovy_agent.common.tts.inworld.httpx.AsyncClient",
            return_value=mock_client,
        ),
        pytest.raises(TTSError, match="missing timestampInfo"),
    ):
        await InworldTTS(settings).synthesize(
            "이차방정식은 영입니다.",
            output_path=tmp_path / "segment.wav",
        )

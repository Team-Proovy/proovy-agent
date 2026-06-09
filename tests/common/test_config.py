"""Application settings tests."""

import pytest

from proovy_agent.common.config import Settings


def test_settings_has_daytona_sandbox_defaults() -> None:
    """Settings exposes default Daytona sandbox values."""
    settings = Settings(_env_file=None)

    assert settings.daytona_snapshot == "proovy-math-sandbox"
    assert settings.daytona_sandbox_cpu == 2
    assert settings.daytona_sandbox_memory == 2
    assert settings.daytona_sandbox_disk == 5
    assert settings.daytona_auto_stop_interval == 5
    assert settings.daytona_code_timeout == 60
    assert settings.daytona_max_output_chars == 10_000
    assert settings.sandbox_preamble_name == "math_v1"


def test_settings_reads_daytona_sandbox_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings reads Daytona sandbox values from environment variables."""
    monkeypatch.setenv("DAYTONA_SNAPSHOT", "custom-snapshot")
    monkeypatch.setenv("DAYTONA_SANDBOX_CPU", "4")
    monkeypatch.setenv("DAYTONA_SANDBOX_MEMORY", "8")
    monkeypatch.setenv("DAYTONA_SANDBOX_DISK", "20")
    monkeypatch.setenv("DAYTONA_AUTO_STOP_INTERVAL", "10")
    monkeypatch.setenv("DAYTONA_CODE_TIMEOUT", "120")
    monkeypatch.setenv("DAYTONA_MAX_OUTPUT_CHARS", "12345")
    monkeypatch.setenv("SANDBOX_PREAMBLE_NAME", "math_v1")

    settings = Settings(_env_file=None)

    assert settings.daytona_snapshot == "custom-snapshot"
    assert settings.daytona_sandbox_cpu == 4
    assert settings.daytona_sandbox_memory == 8
    assert settings.daytona_sandbox_disk == 20
    assert settings.daytona_auto_stop_interval == 10
    assert settings.daytona_code_timeout == 120
    assert settings.daytona_max_output_chars == 12_345
    assert settings.sandbox_preamble_name == "math_v1"


def test_settings_reads_inworld_tts_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings accepts current and legacy Inworld TTS env names."""
    monkeypatch.setenv("INWORLD_API_KEY", "legacy-key")
    monkeypatch.setenv("INWORLD_TTS_MODEL_ID", "inworld-tts-custom")
    monkeypatch.setenv("INWORLD_TTS_VOICE_ID", "Mihyun")

    settings = Settings(_env_file=None)

    assert settings.inworld_tts_api_key == "legacy-key"
    assert settings.video_tts_model == "inworld-tts-custom"
    assert settings.video_tts_voice == "Mihyun"


def test_settings_reads_video_hint_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings exposes the three hint extractor model aliases."""
    monkeypatch.setenv("VIDEO_HINT_TARGET_MODEL", "flash-custom")
    monkeypatch.setenv("VIDEO_HINT_PLAN_MODEL", "sonnet-custom")
    monkeypatch.setenv("VIDEO_HINT_VIDEOHINTS_MODEL", "flash-hints")

    settings = Settings(_env_file=None)

    assert settings.video_hint_target_model == "flash-custom"
    assert settings.video_hint_plan_model == "sonnet-custom"
    assert settings.video_hint_videohints_model == "flash-hints"


def test_settings_reads_video_lazy_detection_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings exposes lazy detection thresholds for video jobs."""
    monkeypatch.setenv("VIDEO_STUCK_JOB_THRESHOLD_SECONDS", "3600")
    monkeypatch.setenv("VIDEO_QUEUED_TASK_CHECK_SECONDS", "1200")

    settings = Settings(_env_file=None)

    assert settings.video_stuck_job_threshold_seconds == 3600
    assert settings.video_queued_task_check_seconds == 1200

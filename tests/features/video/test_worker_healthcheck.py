"""Video worker runtime health check tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from proovy_agent.common.config import Settings
from proovy_agent.features.video.worker import healthcheck as healthcheck_module
from proovy_agent.features.video.worker.healthcheck import (
    RuntimeCommandResult,
    run_runtime_command,
    runtime_healthcheck,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pytest


def _settings(tmp_path, **overrides: object) -> Settings:
    values = {
        "database_url": "postgres://user:pass@localhost:5432/proovy",
        "video_render_workspace_root": str(tmp_path / "render"),
        "video_render_require_non_root": False,
        "video_render_require_landlock": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


async def _healthy_command_runner(
    command: Sequence[str],
    _timeout_seconds: float,
) -> RuntimeCommandResult:
    executable = command[0]
    if executable == "kpsewhich":
        return RuntimeCommandResult(returncode=0, stdout=f"/texmf/{command[1]}")
    if executable == "fc-list":
        return RuntimeCommandResult(returncode=0, stdout="Noto Sans CJK KR")
    return RuntimeCommandResult(returncode=0, stdout=f"{executable} ok")


async def test_runtime_healthcheck_passes_when_worker_dependencies_are_present(tmp_path) -> None:
    report = await runtime_healthcheck(
        _settings(tmp_path),
        command_runner=_healthy_command_runner,
        include_landlock=False,
    )

    assert report.status == "ok"
    assert {check.name for check in report.checks} >= {
        "ffmpeg",
        "ffprobe",
        "manim",
        "latex",
        "xelatex",
        "dvisvgm",
        "tex_file:standalone.cls",
        "tex_file:preview.sty",
        "tex_file:xeCJK.sty",
        "tex_file:ctexhook.sty",
        "cjk_font",
        "manim_import",
    }


async def test_run_runtime_command_reports_missing_executable() -> None:
    result = await run_runtime_command(("proovy-healthcheck-command-that-does-not-exist",))

    assert result.returncode == 127
    assert "proovy-healthcheck-command-that-does-not-exist" in result.stderr


async def test_runtime_healthcheck_uses_configured_manim_binary_for_version_and_smoke(
    tmp_path,
) -> None:
    seen_commands: list[tuple[str, ...]] = []

    async def command_runner(
        command: Sequence[str],
        timeout_seconds: float,
    ) -> RuntimeCommandResult:
        command_tuple = tuple(command)
        seen_commands.append(command_tuple)
        if "--media_dir" in command_tuple:
            media_dir = Path(command_tuple[command_tuple.index("--media_dir") + 1])
            rendered_path = media_dir / "videos" / "smoke" / "480p15" / "CjkSmokeScene.mp4"
            rendered_path.parent.mkdir(parents=True, exist_ok=True)
            rendered_path.write_bytes(b"mp4")
        return await _healthy_command_runner(command, timeout_seconds)

    report = await runtime_healthcheck(
        _settings(
            tmp_path,
            VIDEO_RENDER_MANIM="/opt/bin/custom-manim",
            video_render_manim_quality_flag="-qm",
        ),
        command_runner=command_runner,
        include_cjk_smoke=True,
        include_landlock=False,
    )

    assert report.status == "ok"
    assert ("/opt/bin/custom-manim", "--version") in seen_commands
    assert any(
        command[:2] == ("/opt/bin/custom-manim", "-qm") and "CjkSmokeScene" in command
        for command in seen_commands
    )


async def test_runtime_healthcheck_fails_when_manim_cli_is_missing(tmp_path) -> None:
    async def command_runner(
        command: Sequence[str],
        timeout_seconds: float,
    ) -> RuntimeCommandResult:
        if command[0] == "manim":
            return RuntimeCommandResult(returncode=127, stderr="manim: not found")
        return await _healthy_command_runner(command, timeout_seconds)

    report = await runtime_healthcheck(
        _settings(tmp_path),
        command_runner=command_runner,
        include_landlock=False,
    )

    assert report.status == "failed"
    assert _check_detail(report, "manim") == "manim: not found"


async def test_runtime_healthcheck_fails_when_configured_cjk_font_is_missing(tmp_path) -> None:
    async def command_runner(
        command: Sequence[str],
        timeout_seconds: float,
    ) -> RuntimeCommandResult:
        if command[0] == "fc-list":
            return RuntimeCommandResult(returncode=0, stdout="DejaVu Sans")
        return await _healthy_command_runner(command, timeout_seconds)

    report = await runtime_healthcheck(
        _settings(tmp_path, video_cjk_font="Noto Sans CJK KR"),
        command_runner=command_runner,
        include_landlock=False,
    )

    assert report.status == "failed"
    assert "Noto Sans CJK KR" in _check_detail(report, "cjk_font")


async def test_runtime_healthcheck_fails_when_tex_package_is_missing(tmp_path) -> None:
    async def command_runner(
        command: Sequence[str],
        timeout_seconds: float,
    ) -> RuntimeCommandResult:
        if command == ("kpsewhich", "xeCJK.sty"):
            return RuntimeCommandResult(returncode=1, stderr="not found")
        return await _healthy_command_runner(command, timeout_seconds)

    report = await runtime_healthcheck(
        _settings(tmp_path),
        command_runner=command_runner,
        include_landlock=False,
    )

    assert report.status == "failed"
    assert _check_detail(report, "tex_file:xeCJK.sty") == "not found"


async def test_runtime_healthcheck_fails_when_landlock_smoke_cannot_install(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenSandboxedCommandRunner:
        def __init__(self, _config) -> None:
            pass

        async def run(self, *_args, **_kwargs) -> None:
            raise OSError("landlock sandbox unavailable")

    monkeypatch.setattr(
        healthcheck_module,
        "sandbox_runtime_summary",
        lambda _config: {"landlock_available": True},
    )
    monkeypatch.setattr(
        healthcheck_module,
        "SandboxedCommandRunner",
        BrokenSandboxedCommandRunner,
    )

    report = await runtime_healthcheck(
        _settings(tmp_path, video_render_require_landlock=True),
        command_runner=_healthy_command_runner,
        include_landlock=True,
    )

    assert report.status == "failed"
    assert _check_detail(report, "landlock_available") == "landlock sandbox unavailable"


async def test_runtime_healthcheck_enforces_non_root_when_required(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(healthcheck_module, "_current_euid", lambda: 0)

    report = await runtime_healthcheck(
        _settings(tmp_path, video_render_require_non_root=True),
        command_runner=_healthy_command_runner,
        include_landlock=False,
    )

    assert report.status == "failed"
    assert _check_detail(report, "non_root_runtime") == "worker is running as root"


def _check_detail(report, name: str) -> str:
    return next(check.detail for check in report.checks if check.name == name)

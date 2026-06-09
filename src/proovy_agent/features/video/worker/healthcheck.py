"""Runtime health checks for the video worker image."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from proovy_agent.common.config import settings as default_settings
from proovy_agent.features.video.worker.sandbox import (
    RenderSandboxConfig,
    RenderSandboxError,
    SandboxedCommandRunner,
    sandbox_runtime_summary,
)

if TYPE_CHECKING:
    from proovy_agent.common.config import Settings

CheckStatus = Literal["ok", "failed"]
CommandRunner = Callable[[Sequence[str], float], Awaitable["RuntimeCommandResult"]]

_DEFAULT_COMMAND_TIMEOUT_SECONDS = 30.0
_DEFAULT_CJK_SMOKE_TIMEOUT_SECONDS = 180.0
_REQUIRED_TEX_FILES = ("standalone.cls", "preview.sty", "xeCJK.sty", "ctexhook.sty")
_BASE_VERSION_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ffmpeg", ("ffmpeg", "-version")),
    ("ffprobe", ("ffprobe", "-version")),
    ("latex", ("latex", "--version")),
    ("xelatex", ("xelatex", "--version")),
    ("dvisvgm", ("dvisvgm", "--version")),
)


class WorkerHealthCheck(BaseModel):
    """One worker runtime readiness check."""

    name: str
    status: CheckStatus
    detail: str = ""


class WorkerHealthReport(BaseModel):
    """Startup/readiness report for the video worker."""

    status: CheckStatus
    checks: list[WorkerHealthCheck] = Field(default_factory=list)

    @property
    def healthy(self) -> bool:
        """Return whether all required worker checks passed."""
        return self.status == "ok"

    @classmethod
    def from_checks(cls, checks: list[WorkerHealthCheck]) -> WorkerHealthReport:
        """Build a report from check results."""
        status: CheckStatus = "ok" if all(check.status == "ok" for check in checks) else "failed"
        return cls(status=status, checks=checks)


@dataclass(frozen=True, slots=True)
class RuntimeCommandResult:
    """Captured output from a health-check command."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def output(self) -> str:
        """Return stdout/stderr joined for diagnostics."""
        return "\n".join(part for part in (self.stdout, self.stderr) if part).strip()


async def runtime_healthcheck(
    settings: Settings = default_settings,
    *,
    command_runner: CommandRunner | None = None,
    include_cjk_smoke: bool = False,
    include_landlock: bool = True,
) -> WorkerHealthReport:
    """Check that the worker runtime can render Manim/TeX/CJK videos."""
    runner = command_runner or run_runtime_command
    sandbox_config = _sandbox_config(settings)
    checks: list[WorkerHealthCheck] = [
        _check_non_root_required(sandbox_config),
        await _check_workspace_writable(sandbox_config.resolved_workspace_root),
    ]
    if include_landlock:
        checks.append(await _check_landlock_required(sandbox_config))

    for name, command in _version_commands(sandbox_config.manim_binary):
        checks.append(await _check_command(name, command, runner))

    for tex_file in _REQUIRED_TEX_FILES:
        checks.append(await _check_kpsewhich(tex_file, runner))

    checks.append(await _check_cjk_font(settings.video_cjk_font, runner))
    checks.append(await _check_manim_import(runner))
    if include_cjk_smoke:
        checks.append(
            await _check_cjk_smoke_render(
                sandbox_config.resolved_workspace_root,
                sandbox_config.manim_binary,
                sandbox_config.manim_quality_flag,
                settings.video_cjk_font,
                runner,
            )
        )
    return WorkerHealthReport.from_checks(checks)


async def run_runtime_command(
    command: Sequence[str],
    timeout_seconds: float = _DEFAULT_COMMAND_TIMEOUT_SECONDS,
) -> RuntimeCommandResult:
    """Run a bounded command for worker health diagnostics."""
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        return RuntimeCommandResult(returncode=127, stderr=str(exc))
    except OSError as exc:
        return RuntimeCommandResult(returncode=126, stderr=str(exc))
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_seconds)
    except TimeoutError:
        process.kill()
        await process.wait()
        return RuntimeCommandResult(
            returncode=124,
            stderr=f"command timed out after {timeout_seconds:.1f}s",
        )
    return RuntimeCommandResult(
        returncode=process.returncode or 0,
        stdout=stdout.decode(errors="replace").strip(),
        stderr=stderr.decode(errors="replace").strip(),
    )


def _sandbox_config(settings: Settings) -> RenderSandboxConfig:
    return RenderSandboxConfig(
        workspace_root=settings.video_render_workspace_root,
        manim_binary=settings.video_render_manim_binary,
        manim_quality_flag=settings.video_render_manim_quality_flag,
        timeout_seconds=settings.video_render_timeout_seconds,
        memory_limit_mb=settings.video_render_memory_limit_mb,
        file_size_limit_mb=settings.video_render_file_size_limit_mb,
        process_limit=settings.video_render_process_limit,
        workspace_size_limit_mb=settings.video_render_workspace_size_limit_mb,
        require_non_root=settings.video_render_require_non_root,
        require_landlock=settings.video_render_require_landlock,
    )


def _version_commands(manim_binary: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        ("manim", (manim_binary, "--version")),
        *_BASE_VERSION_COMMANDS,
    )


def _check_non_root_required(config: RenderSandboxConfig) -> WorkerHealthCheck:
    if not config.require_non_root:
        return WorkerHealthCheck(name="non_root_runtime", status="ok", detail="not required")
    euid = _current_euid()
    if euid is None:
        return WorkerHealthCheck(
            name="non_root_runtime",
            status="failed",
            detail="effective uid is unavailable",
        )
    if euid == 0:
        return WorkerHealthCheck(
            name="non_root_runtime",
            status="failed",
            detail="worker is running as root",
        )
    return WorkerHealthCheck(
        name="non_root_runtime",
        status="ok",
        detail=f"uid={euid}",
    )


async def _check_workspace_writable(workspace_root: Path) -> WorkerHealthCheck:
    try:
        await asyncio.to_thread(workspace_root.mkdir, parents=True, exist_ok=True)
        probe_path = workspace_root / f".proovy-healthcheck-{os.getpid()}-{uuid4().hex}"
        await asyncio.to_thread(probe_path.write_text, "ok", encoding="utf-8")
        await asyncio.to_thread(probe_path.unlink, missing_ok=True)
    except OSError as exc:
        return WorkerHealthCheck(
            name="render_workspace_writable",
            status="failed",
            detail=str(exc),
        )
    return WorkerHealthCheck(
        name="render_workspace_writable",
        status="ok",
        detail=str(workspace_root),
    )


async def _check_landlock_required(config: RenderSandboxConfig) -> WorkerHealthCheck:
    if not config.require_landlock:
        return WorkerHealthCheck(name="landlock_available", status="ok", detail="not required")
    summary = sandbox_runtime_summary(config)
    if not summary["landlock_available"]:
        return WorkerHealthCheck(
            name="landlock_available",
            status="failed",
            detail="Linux Landlock is unavailable for the render sandbox",
        )

    smoke_dir = (
        config.resolved_workspace_root / f".proovy-landlock-smoke-{os.getpid()}-{uuid4().hex}"
    )
    try:
        await asyncio.to_thread(smoke_dir.mkdir, parents=True, exist_ok=True)
        runner = SandboxedCommandRunner(config)
        await runner.run(
            (
                sys.executable,
                "-c",
                "from pathlib import Path; Path('landlock-smoke.txt').write_text('ok')",
            ),
            workspace=smoke_dir,
        )
    except (OSError, RenderSandboxError) as exc:
        return WorkerHealthCheck(
            name="landlock_available",
            status="failed",
            detail=str(exc),
        )
    finally:
        await asyncio.to_thread(shutil.rmtree, smoke_dir, ignore_errors=True)

    return WorkerHealthCheck(name="landlock_available", status="ok", detail="available")


async def _check_command(
    name: str,
    command: Sequence[str],
    command_runner: CommandRunner,
) -> WorkerHealthCheck:
    result = await command_runner(command, _DEFAULT_COMMAND_TIMEOUT_SECONDS)
    if result.returncode == 0:
        return WorkerHealthCheck(name=name, status="ok", detail=_first_output_line(result))
    return WorkerHealthCheck(
        name=name,
        status="failed",
        detail=_failure_detail(result),
    )


async def _check_kpsewhich(tex_file: str, command_runner: CommandRunner) -> WorkerHealthCheck:
    result = await command_runner(("kpsewhich", tex_file), _DEFAULT_COMMAND_TIMEOUT_SECONDS)
    name = f"tex_file:{tex_file}"
    if result.returncode == 0 and result.stdout.strip():
        return WorkerHealthCheck(
            name=name, status="ok", detail=result.stdout.strip().splitlines()[0]
        )
    return WorkerHealthCheck(name=name, status="failed", detail=_failure_detail(result))


async def _check_cjk_font(font_name: str, command_runner: CommandRunner) -> WorkerHealthCheck:
    result = await command_runner(
        ("fc-list", ":lang=ko", "family"),
        _DEFAULT_COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return WorkerHealthCheck(name="cjk_font", status="failed", detail=_failure_detail(result))

    output = result.stdout.casefold()
    if font_name.casefold() in output:
        return WorkerHealthCheck(name="cjk_font", status="ok", detail=font_name)
    return WorkerHealthCheck(
        name="cjk_font",
        status="failed",
        detail=f"{font_name!r} was not found in Korean fontconfig families",
    )


async def _check_manim_import(command_runner: CommandRunner) -> WorkerHealthCheck:
    result = await command_runner(
        (
            sys.executable,
            "-c",
            "from manim import MathTex, TexTemplate; print('manim import ok')",
        ),
        _DEFAULT_COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode == 0:
        return WorkerHealthCheck(name="manim_import", status="ok", detail=result.stdout.strip())
    return WorkerHealthCheck(name="manim_import", status="failed", detail=_failure_detail(result))


async def _check_cjk_smoke_render(
    workspace_root: Path,
    manim_binary: str,
    manim_quality_flag: str,
    font_name: str,
    command_runner: CommandRunner,
) -> WorkerHealthCheck:
    await asyncio.to_thread(workspace_root.mkdir, parents=True, exist_ok=True)
    smoke_dir = Path(
        await asyncio.to_thread(
            tempfile.mkdtemp,
            prefix="proovy-cjk-smoke-",
            dir=str(workspace_root),
        )
    )
    media_dir = smoke_dir / "media"
    scene_path = smoke_dir / "cjk_smoke_scene.py"
    try:
        await asyncio.to_thread(
            scene_path.write_text,
            _cjk_smoke_scene(font_name),
            encoding="utf-8",
        )
        result = await command_runner(
            (
                manim_binary,
                manim_quality_flag,
                "--media_dir",
                str(media_dir),
                str(scene_path),
                "CjkSmokeScene",
            ),
            _DEFAULT_CJK_SMOKE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return WorkerHealthCheck(
                name="cjk_smoke_render",
                status="failed",
                detail=_failure_detail(result),
            )
        rendered = await asyncio.to_thread(lambda: list(media_dir.rglob("*.mp4")))
        if not rendered:
            return WorkerHealthCheck(
                name="cjk_smoke_render",
                status="failed",
                detail="manim finished without producing an mp4",
            )
        return WorkerHealthCheck(
            name="cjk_smoke_render",
            status="ok",
            detail=str(rendered[0]),
        )
    finally:
        await asyncio.to_thread(shutil.rmtree, smoke_dir, ignore_errors=True)


def _cjk_smoke_scene(font_name: str) -> str:
    return f"""
from manim import MathTex, Scene, TexTemplate

FONT_NAME = {font_name!r}

tex_template = TexTemplate(tex_compiler="xelatex", output_format=".xdv")
tex_template.add_to_preamble(r"\\usepackage{{xeCJK}}")
tex_template.add_to_preamble(r"\\setCJKmainfont{{" + FONT_NAME + "}}")


class CjkSmokeScene(Scene):
    def construct(self):
        formula = MathTex(r"\\text{{한국어 수식 }} x^2 + 1", tex_template=tex_template)
        self.add(formula)
        self.wait(0.1)
""".lstrip()


def _first_output_line(result: RuntimeCommandResult) -> str:
    output = result.output
    return output.splitlines()[0] if output else "ok"


def _failure_detail(result: RuntimeCommandResult) -> str:
    output = result.output
    if not output:
        return f"command exited with status {result.returncode}"
    return output[-1000:]


def _current_euid() -> int | None:
    return os.geteuid() if hasattr(os, "geteuid") else None


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint used by Docker build and container health checks."""
    parser = argparse.ArgumentParser(description="Check video worker runtime dependencies.")
    parser.add_argument(
        "--build",
        action="store_true",
        help="include the build-time CJK smoke render and skip startup-only Landlock checks",
    )
    parser.add_argument(
        "--startup",
        action="store_true",
        help="run startup checks only; this is the default",
    )
    args = parser.parse_args(argv)

    report = asyncio.run(
        runtime_healthcheck(
            default_settings,
            include_cjk_smoke=args.build,
            include_landlock=not args.build,
        )
    )
    print(report.model_dump_json(indent=2))
    return 0 if report.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())

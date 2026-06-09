"""Worker render sandbox smoke tests."""

from __future__ import annotations

import os
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from proovy_agent.features.video.worker.sandbox import (
    ManimRenderSandbox,
    RenderSandboxConfig,
    RenderSandboxPolicyViolationError,
    RenderSandboxResourceLimitError,
    SandboxedCommandRunner,
)
from proovy_agent.features.video.worker.sandbox import executor as executor_module

if TYPE_CHECKING:
    from pathlib import Path


def _config(tmp_path: Path, **overrides: object) -> RenderSandboxConfig:
    values = {
        "workspace_root": tmp_path,
        "timeout_seconds": 3.0,
        "memory_limit_mb": 256,
        "file_size_limit_mb": 64,
        "process_limit": 16,
        "workspace_size_limit_mb": 64,
    }
    values.update(overrides)
    return RenderSandboxConfig(**values)


async def test_sandbox_does_not_forward_secret_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "super-secret")
    runner = SandboxedCommandRunner(_config(tmp_path))

    result = await runner.run(
        [sys.executable, "-c", "import os; print(os.environ.get('OPENROUTER_API_KEY'))"],
        workspace=tmp_path / "secret-env",
    )

    assert result.stdout == "None"


async def test_manim_sandbox_requires_non_root_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(executor_module, "_current_euid", lambda: 0)
    sandbox = ManimRenderSandbox(_config(tmp_path))

    with pytest.raises(RenderSandboxPolicyViolationError):
        await sandbox.render_manim_source(
            manim_source="from manim import *",
            scene_class_name="Scene",
            job_id="job-1",
            segment_id="segment-1",
        )


async def test_sandbox_blocks_python_write_outside_workspace(tmp_path: Path) -> None:
    outside_path = tmp_path / "outside.txt"
    runner = SandboxedCommandRunner(_config(tmp_path))

    with pytest.raises(RenderSandboxPolicyViolationError):
        await runner.run(
            [
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(outside_path)!r}).write_text('leak')",
            ],
            workspace=tmp_path / "outside-write",
        )

    assert not outside_path.exists()


async def test_sandbox_blocks_shell_write_outside_workspace(tmp_path: Path) -> None:
    outside_path = tmp_path / "shell-outside.txt"
    runner = SandboxedCommandRunner(_config(tmp_path, process_limit=512))

    with pytest.raises(RenderSandboxPolicyViolationError):
        await runner.run(
            [
                sys.executable,
                "-c",
                (
                    "import subprocess; "
                    f"subprocess.run(['sh', '-c', 'printf leak > {outside_path}'], check=True)"
                ),
            ],
            workspace=tmp_path / "shell-outside-write",
        )

    assert not outside_path.exists()


async def test_sandbox_times_out_long_running_process(tmp_path: Path) -> None:
    runner = SandboxedCommandRunner(_config(tmp_path, timeout_seconds=0.5))

    with pytest.raises(RenderSandboxResourceLimitError):
        await runner.run(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            workspace=tmp_path / "timeout",
        )


async def test_sandbox_reports_memory_limit_failure(tmp_path: Path) -> None:
    runner = SandboxedCommandRunner(_config(tmp_path, memory_limit_mb=192, timeout_seconds=5.0))
    script = "chunks=[]\nwhile True:\n    chunks.append(bytearray(32 * 1024 * 1024))"

    with pytest.raises(RenderSandboxResourceLimitError):
        await runner.run([sys.executable, "-c", script], workspace=tmp_path / "memory")


async def test_sandbox_keeps_only_bounded_output_tail(tmp_path: Path) -> None:
    runner = SandboxedCommandRunner(_config(tmp_path, stdout_stderr_limit=32))

    result = await runner.run(
        [sys.executable, "-c", "print('a' * 1000 + 'tail')"],
        workspace=tmp_path / "output-tail",
    )

    assert len(result.stdout.encode()) <= 32
    assert result.stdout.endswith("tail")


async def test_sandbox_applies_process_limit_for_fork_bomb_smoke(tmp_path: Path) -> None:
    runner = SandboxedCommandRunner(_config(tmp_path, process_limit=8))

    result = await runner.run(
        [
            sys.executable,
            "-c",
            "import resource; print(resource.getrlimit(resource.RLIMIT_NPROC)[0])",
        ],
        workspace=tmp_path / "process-limit",
    )

    assert int(result.stdout) <= 8


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="RLIMIT_NPROC is not enforced for root users",
)
async def test_sandbox_blocks_fork_bomb_for_non_root_runtime(tmp_path: Path) -> None:
    runner = SandboxedCommandRunner(_config(tmp_path, process_limit=8, timeout_seconds=5.0))
    script = textwrap.dedent(
        """
        import subprocess
        import sys

        processes = []
        try:
            for _ in range(128):
                processes.append(
                    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
                )
        except OSError as exc:
            print(exc)
            raise SystemExit(1)
        finally:
            for process in processes:
                process.kill()
        """
    )

    with pytest.raises(RenderSandboxResourceLimitError):
        await runner.run([sys.executable, "-c", script], workspace=tmp_path / "fork-bomb")

"""Sub-process sandbox used by the video worker render boundary."""

from __future__ import annotations

import asyncio
import ctypes
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import shutil
import signal
import tempfile
from typing import TYPE_CHECKING
import uuid

from proovy_agent.features.video.exceptions import PermanentFailure
from proovy_agent.features.video.models import StageName, UserErrorCode
from proovy_agent.features.video.worker.sandbox.tex_sanitizer import audit_latex_source

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_SAFE_PATH_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_DEFAULT_WORKSPACE_ROOT = Path(tempfile.gettempdir()) / "proovy-video-worker-render"
_LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
_LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
_LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
_LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
_LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
_LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
_LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
_LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
_LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
_LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
_LANDLOCK_ACCESS_FS_REFER = 1 << 13
_LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14
_LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
_LANDLOCK_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38
_SYS_LANDLOCK_CREATE_RULESET = 444
_SYS_LANDLOCK_ADD_RULE = 445
_SYS_LANDLOCK_RESTRICT_SELF = 446
_ALLOWED_ENV_KEYS = {
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "TZ",
}
_SECRET_ENV_MARKERS = (
    "API_KEY",
    "AUTH",
    "CREDENTIAL",
    "DATABASE_URL",
    "DAYTONA",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "INWORLD",
    "OPENROUTER",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)
_PYTHON_GUARD = r"""
from __future__ import annotations

import os
from pathlib import Path
import sys

_ALLOWED_WORKSPACE = Path(os.environ["PROOVY_RENDER_WORKSPACE"]).resolve()


def _is_write_mode(mode: object, flags: object) -> bool:
    if isinstance(mode, str) and any(marker in mode for marker in ("w", "a", "x", "+")):
        return True
    try:
        flag_value = int(flags)
    except (TypeError, ValueError):
        return False
    return bool(
        flag_value
        & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC)
    )


def _resolve_path(value: object) -> Path | None:
    if value is None or isinstance(value, int):
        return None
    try:
        raw_path = os.fsdecode(value)
    except TypeError:
        return None
    if not raw_path or raw_path.startswith("<"):
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False)


def _inside_workspace(path: Path) -> bool:
    return _ALLOWED_WORKSPACE == path or _ALLOWED_WORKSPACE in path.parents


def _audit(event: str, args: tuple[object, ...]) -> None:
    if event != "open":
        return
    path = _resolve_path(args[0] if len(args) >= 1 else None)
    if path is None or _inside_workspace(path):
        return
    mode = args[1] if len(args) >= 2 else None
    flags = args[2] if len(args) >= 3 else None
    if _is_write_mode(mode, flags):
        raise PermissionError(f"write outside sandbox workspace is not allowed: {path}")


sys.addaudithook(_audit)
"""


class RenderSandboxError(PermanentFailure):
    """Base failure raised by the worker render sandbox."""

    stage = StageName.RENDER
    user_error_code = UserErrorCode.RENDER_UNRECOVERABLE

    def __init__(self, message: str, *, details: Mapping[str, object] | None = None) -> None:
        super().__init__(
            message,
            stage=self.stage,
            user_error_code=self.user_error_code,
            details=details,
        )


class RenderSandboxValidationError(RenderSandboxError):
    """Raised when render source fails pre-execution validation."""


class RenderSandboxPolicyViolationError(RenderSandboxError):
    """Raised when the sub-process tries to cross the sandbox policy boundary."""


class RenderSandboxExecutionError(RenderSandboxError):
    """Raised when the render sub-process exits unsuccessfully."""


class RenderSandboxResourceLimitError(RenderSandboxError):
    """Raised when timeout, memory, process, or file-size limits stop the render."""

    user_error_code = UserErrorCode.RENDER_RESOURCE_LIMIT


@dataclass(frozen=True, slots=True)
class RenderSandboxConfig:
    """Runtime limits and command settings for a render sandbox."""

    workspace_root: Path | str | None = None
    manim_binary: str = "manim"
    manim_quality_flag: str = "-ql"
    timeout_seconds: float = 120.0
    memory_limit_mb: int = 1024
    file_size_limit_mb: int = 512
    process_limit: int = 128
    workspace_size_limit_mb: int = 512
    stdout_stderr_limit: int = 8000
    require_non_root: bool = True
    require_landlock: bool = True

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        for name in (
            "memory_limit_mb",
            "file_size_limit_mb",
            "process_limit",
            "workspace_size_limit_mb",
            "stdout_stderr_limit",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

    @property
    def resolved_workspace_root(self) -> Path:
        """Return the root directory used for sandbox workspaces."""
        if self.workspace_root is None:
            return _DEFAULT_WORKSPACE_ROOT
        return Path(self.workspace_root)


@dataclass(frozen=True, slots=True)
class SandboxedCommandResult:
    """Captured result from a sandboxed sub-process."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    workspace: Path

    def output_tail(self, limit: int = 3000) -> str:
        """Return a bounded stdout/stderr tail for internal diagnostics."""
        output = "\n".join(part for part in (self.stdout, self.stderr) if part)
        return output[-limit:]


@dataclass(frozen=True, slots=True)
class ManimRenderResult:
    """Successful Manim render result from the sandbox."""

    output_path: str
    diagnostics: dict[str, object]


class SandboxedCommandRunner:
    """Run commands with scrubbed env, workspace write guard, and rlimits."""

    def __init__(self, config: RenderSandboxConfig | None = None) -> None:
        self._config = config or RenderSandboxConfig()

    async def run(
        self,
        command: Sequence[str],
        *,
        workspace: Path,
        check: bool = True,
        extra_env: Mapping[str, str] | None = None,
    ) -> SandboxedCommandResult:
        """Run one command inside the provided workspace."""
        if not command:
            raise ValueError("command must contain at least one argument")

        await asyncio.to_thread(workspace.mkdir, parents=True, exist_ok=True)
        await self._prepare_workspace_env_dirs(workspace)
        env = await asyncio.to_thread(self._build_env, workspace, extra_env)
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=workspace,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=_build_preexec(self._config, workspace) if os.name == "posix" else None,
            start_new_session=os.name == "posix",
        )
        stdout_task = asyncio.create_task(
            _read_stream_tail(process.stdout, self._config.stdout_stderr_limit)
        )
        stderr_task = asyncio.create_task(
            _read_stream_tail(process.stderr, self._config.stdout_stderr_limit)
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=self._config.timeout_seconds)
            stdout_bytes, stderr_bytes = await asyncio.gather(stdout_task, stderr_task)
        except TimeoutError as exc:
            await _kill_process_group(process)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise RenderSandboxResourceLimitError(
                "render sub-process exceeded timeout",
                details={
                    "limit": "timeout",
                    "timeout_seconds": self._config.timeout_seconds,
                    "workspace": str(workspace),
                },
            ) from exc

        result = SandboxedCommandResult(
            command=tuple(command),
            returncode=process.returncode or 0,
            stdout=stdout_bytes.decode(errors="replace").strip(),
            stderr=stderr_bytes.decode(errors="replace").strip(),
            workspace=workspace,
        )
        workspace_size = await asyncio.to_thread(_directory_size, workspace)
        if workspace_size > self._config.workspace_size_limit_mb * 1024 * 1024:
            raise RenderSandboxResourceLimitError(
                "render workspace exceeded size limit",
                details={
                    "limit": "workspace_size",
                    "workspace_size_bytes": workspace_size,
                    "workspace_size_limit_mb": self._config.workspace_size_limit_mb,
                },
            )
        if check and result.returncode != 0:
            raise _command_failure(result)
        return result

    async def _prepare_workspace_env_dirs(self, workspace: Path) -> None:
        for relative_path in ("home", "tmp", ".cache", ".config", "matplotlib"):
            await asyncio.to_thread((workspace / relative_path).mkdir, parents=True, exist_ok=True)
        guard_dir = workspace / "_python_guard"
        await asyncio.to_thread(guard_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            (guard_dir / "sitecustomize.py").write_text,
            _PYTHON_GUARD,
            encoding="utf-8",
        )

    def _build_env(self, workspace: Path, extra_env: Mapping[str, str] | None) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key in _ALLOWED_ENV_KEYS and not _is_secret_env_name(key)
        }
        env.update(
            {
                "HOME": str(workspace / "home"),
                "MPLCONFIGDIR": str(workspace / "matplotlib"),
                "PROOVY_RENDER_WORKSPACE": str(workspace.resolve()),
                "PYTHONNOUSERSITE": "1",
                "PYTHONPATH": str((workspace / "_python_guard").resolve()),
                "TMPDIR": str(workspace / "tmp"),
                "XDG_CACHE_HOME": str(workspace / ".cache"),
                "XDG_CONFIG_HOME": str(workspace / ".config"),
            }
        )
        for key, value in (extra_env or {}).items():
            if not _is_secret_env_name(key):
                env[key] = value
        return env


class ManimRenderSandbox:
    """Render Manim source through the sandboxed sub-process boundary."""

    def __init__(self, config: RenderSandboxConfig | None = None) -> None:
        self._config = config or RenderSandboxConfig()
        self._runner = SandboxedCommandRunner(self._config)

    async def render_manim_source(
        self,
        *,
        manim_source: str,
        scene_class_name: str,
        job_id: str,
        segment_id: str,
    ) -> ManimRenderResult:
        """Write source to an isolated workspace and run the Manim CLI."""
        if self._config.require_non_root and _current_euid() == 0:
            raise RenderSandboxPolicyViolationError(
                "render sandbox requires a non-root runtime user",
                details={"runtime_uid": 0},
            )

        latex_errors = audit_latex_source(manim_source)
        if latex_errors:
            raise RenderSandboxValidationError(
                "render template failed LaTeX safety validation",
                details={"latex_validation_errors": latex_errors},
            )

        workspace = self._workspace(job_id=job_id, segment_id=segment_id)
        await asyncio.to_thread(workspace.mkdir, parents=True, exist_ok=True)
        source_path = workspace / "scene.py"
        media_dir = workspace / "media"
        await asyncio.to_thread(source_path.write_text, manim_source, encoding="utf-8")

        result = await self._runner.run(
            [
                self._config.manim_binary,
                self._config.manim_quality_flag,
                "--media_dir",
                str(media_dir),
                str(source_path),
                scene_class_name,
            ],
            workspace=workspace,
            extra_env={"MANIM_DISABLE_CACHING": "1"},
        )
        rendered_mp4 = await asyncio.to_thread(
            _latest_rendered_mp4,
            media_dir,
            scene_class_name,
        )
        if rendered_mp4 is None:
            raise RenderSandboxExecutionError(
                "manim render completed without producing an mp4",
                details={"scene_class_name": scene_class_name, "workspace": str(workspace)},
            )
        return ManimRenderResult(
            output_path=str(rendered_mp4),
            diagnostics={
                "boundary": "subprocess",
                "command": "manim",
                "returncode": result.returncode,
                "timeout_seconds": self._config.timeout_seconds,
                "memory_limit_mb": self._config.memory_limit_mb,
                "file_size_limit_mb": self._config.file_size_limit_mb,
                "process_limit": self._config.process_limit,
                "workspace_size_limit_mb": self._config.workspace_size_limit_mb,
                "workspace": str(workspace),
                "secret_env_forwarded": False,
                "landlock_required": self._config.require_landlock,
                "non_root_runtime": _current_euid() != 0 if _current_euid() is not None else None,
            },
        )

    def _workspace(self, *, job_id: str, segment_id: str) -> Path:
        root = self._config.resolved_workspace_root
        return (
            root
            / _safe_path_part(job_id)
            / f"{_safe_path_part(segment_id)}-{uuid.uuid4().hex[:12]}"
        )


class _LandlockRulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _LandlockPathBeneathAttr(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


def _build_preexec(config: RenderSandboxConfig, workspace: Path):
    def _apply_limits() -> None:
        import resource

        os.umask(0o077)
        _set_resource_limit(resource.RLIMIT_AS, config.memory_limit_mb * 1024 * 1024)
        _set_resource_limit(resource.RLIMIT_CPU, math.ceil(config.timeout_seconds) + 1)
        _set_resource_limit(resource.RLIMIT_FSIZE, config.file_size_limit_mb * 1024 * 1024)
        if hasattr(resource, "RLIMIT_NPROC"):
            _set_resource_limit(resource.RLIMIT_NPROC, config.process_limit)
        if hasattr(resource, "RLIMIT_NOFILE"):
            _set_resource_limit(resource.RLIMIT_NOFILE, 256)
        if config.require_landlock:
            try:
                _apply_landlock_write_allowlist(workspace)
            except OSError as exc:
                os.write(2, f"landlock sandbox unavailable: {exc}\n".encode())
                os._exit(126)

    return _apply_limits


def _set_resource_limit(resource_name: int, value: int) -> None:
    import resource

    try:
        _soft, hard = resource.getrlimit(resource_name)
        if hard == resource.RLIM_INFINITY:
            hard = value
        resource.setrlimit(resource_name, (min(value, hard), hard))
    except (OSError, ValueError):
        return


async def _kill_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        return
    await process.wait()


def _command_failure(result: SandboxedCommandResult) -> RenderSandboxError:
    output = result.output_tail()
    details = {
        "returncode": result.returncode,
        "workspace": str(result.workspace),
        "output_tail": output,
    }
    if "outside sandbox workspace is not allowed" in output:
        return RenderSandboxPolicyViolationError(
            "render sub-process attempted a disallowed filesystem write",
            details=details,
        )
    if "permission denied" in output.casefold():
        return RenderSandboxPolicyViolationError(
            "render sub-process attempted a disallowed filesystem operation",
            details=details,
        )
    if "landlock sandbox unavailable" in output:
        return RenderSandboxPolicyViolationError(
            "render sub-process sandbox could not be installed",
            details=details,
        )
    if _looks_like_resource_limit(result):
        return RenderSandboxResourceLimitError(
            "render sub-process exceeded a resource limit",
            details=details,
        )
    return RenderSandboxExecutionError("render sub-process failed", details=details)


def _looks_like_resource_limit(result: SandboxedCommandResult) -> bool:
    if result.returncode < 0:
        return True
    output = result.output_tail().casefold()
    markers = (
        "cannot allocate memory",
        "memoryerror",
        "resource temporarily unavailable",
        "too many open files",
        "file too large",
    )
    return any(marker in output for marker in markers)


async def _read_stream_tail(
    stream: asyncio.StreamReader | None,
    limit: int,
) -> bytes:
    if stream is None:
        return b""
    buffer = bytearray()
    while chunk := await stream.read(4096):
        buffer.extend(chunk)
        if len(buffer) > limit:
            del buffer[: len(buffer) - limit]
    return bytes(buffer)


def _directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def _latest_rendered_mp4(media_dir: Path, scene_class_name: str) -> Path | None:
    matches = list(media_dir.rglob(f"{scene_class_name}.mp4"))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def _safe_path_part(value: str) -> str:
    safe = _SAFE_PATH_RE.sub("-", value.strip()).strip(".-")
    return safe or "video-job"


def _is_secret_env_name(name: str) -> bool:
    upper_name = name.upper()
    return any(marker in upper_name for marker in _SECRET_ENV_MARKERS)


def _current_euid() -> int | None:
    return os.geteuid() if hasattr(os, "geteuid") else None


def _apply_landlock_write_allowlist(workspace: Path) -> None:
    access_mask = _landlock_write_access_mask()
    if access_mask is None:
        raise OSError("Linux Landlock is not available")

    libc = ctypes.CDLL(None, use_errno=True)
    ruleset_attr = _LandlockRulesetAttr(access_mask)
    ruleset_fd = _syscall(
        libc,
        _SYS_LANDLOCK_CREATE_RULESET,
        ctypes.byref(ruleset_attr),
        ctypes.sizeof(ruleset_attr),
        0,
    )
    parent_fd = -1
    try:
        open_flags = getattr(os, "O_PATH", os.O_RDONLY) | getattr(os, "O_CLOEXEC", 0)
        parent_fd = os.open(workspace, open_flags)
        path_beneath_attr = _LandlockPathBeneathAttr(access_mask, parent_fd)
        _syscall(
            libc,
            _SYS_LANDLOCK_ADD_RULE,
            ruleset_fd,
            _LANDLOCK_RULE_PATH_BENEATH,
            ctypes.byref(path_beneath_attr),
            0,
        )
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))
        _syscall(libc, _SYS_LANDLOCK_RESTRICT_SELF, ruleset_fd, 0)
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)
        os.close(ruleset_fd)


def _landlock_write_access_mask() -> int | None:
    abi_version = _landlock_abi_version()
    if abi_version is None or abi_version < 1:
        return None
    access_mask = (
        _LANDLOCK_ACCESS_FS_WRITE_FILE
        | _LANDLOCK_ACCESS_FS_REMOVE_DIR
        | _LANDLOCK_ACCESS_FS_REMOVE_FILE
        | _LANDLOCK_ACCESS_FS_MAKE_CHAR
        | _LANDLOCK_ACCESS_FS_MAKE_DIR
        | _LANDLOCK_ACCESS_FS_MAKE_REG
        | _LANDLOCK_ACCESS_FS_MAKE_SOCK
        | _LANDLOCK_ACCESS_FS_MAKE_FIFO
        | _LANDLOCK_ACCESS_FS_MAKE_BLOCK
        | _LANDLOCK_ACCESS_FS_MAKE_SYM
    )
    if abi_version >= 2:
        access_mask |= _LANDLOCK_ACCESS_FS_REFER
    if abi_version >= 3:
        access_mask |= _LANDLOCK_ACCESS_FS_TRUNCATE
    return access_mask


def _landlock_abi_version() -> int | None:
    if os.name != "posix":
        return None
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.syscall(
        _SYS_LANDLOCK_CREATE_RULESET,
        None,
        0,
        _LANDLOCK_CREATE_RULESET_VERSION,
    )
    if result < 0:
        return None
    return int(result)


def _syscall(libc: ctypes.CDLL, number: int, *args: object) -> int:
    result = libc.syscall(number, *args)
    if result < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))
    return int(result)


def sandbox_runtime_summary(config: RenderSandboxConfig) -> dict[str, object]:
    """Return deployment-facing sandbox settings for diagnostics and tests."""
    manim_binary = shutil.which(config.manim_binary) or config.manim_binary
    return {
        "boundary": "subprocess",
        "manim_binary": manim_binary,
        "workspace_root": str(config.resolved_workspace_root),
        "timeout_seconds": config.timeout_seconds,
        "memory_limit_mb": config.memory_limit_mb,
        "file_size_limit_mb": config.file_size_limit_mb,
        "process_limit": config.process_limit,
        "workspace_size_limit_mb": config.workspace_size_limit_mb,
        "secret_env_forwarded": False,
        "require_non_root": config.require_non_root,
        "require_landlock": config.require_landlock,
        "landlock_available": _landlock_abi_version() is not None,
        "non_root_runtime": _current_euid() != 0 if _current_euid() is not None else None,
    }

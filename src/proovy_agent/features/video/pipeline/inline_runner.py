"""Phase A throwaway inline video runner.

This module is the only place where Phase A allows the API process to perform
local Manim/ffmpeg work. Phase B must replace this with the worker path.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import tempfile
from typing import TYPE_CHECKING, Protocol

from proovy_agent.features.video.pipeline.orchestrator import run_job

if TYPE_CHECKING:
    from collections.abc import Sequence

    from proovy_agent.features.video.models import VideoPipelineJob, VideoPipelineResult
    from proovy_agent.features.video.pipeline.stage_context import StageContext

from proovy_agent.features.video.pipeline.stage_context import StageContext

_SAFE_PATH_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_DEFAULT_WORKSPACE_ROOT = Path(tempfile.gettempdir()) / "proovy-video-inline"


class PhaseAInlineRenderError(RuntimeError):
    """Raised when Phase A inline rendering cannot produce an mp4."""


class InlineVideoRunner(Protocol):
    """Runs a video pipeline job synchronously from the graph's point of view."""

    async def run_now(
        self,
        job: VideoPipelineJob,
        *,
        ctx: StageContext | None = None,
    ) -> VideoPipelineResult:
        """Run the job now and return the final pipeline result."""


@dataclass(frozen=True, slots=True)
class InlineVideoArtifact:
    """Uploaded inline video artifact handle."""

    object_key: str
    url: str | None = None


class InlineVideoArtifactUploader(Protocol):
    """Uploads a rendered inline mp4 and returns the user-visible handle."""

    async def upload_final_video(
        self,
        *,
        job_id: str,
        output_path: str,
    ) -> InlineVideoArtifact:
        """Upload the final mp4 for one inline job."""


class PhaseAInlineRunner:
    """Run the deterministic Phase A pipeline and render template scenes locally."""

    def __init__(
        self,
        *,
        workspace_root: Path | str | None = None,
        manim_quality_flag: str = "-ql",
    ) -> None:
        self._workspace_root = Path(workspace_root) if workspace_root is not None else None
        self._manim_quality_flag = manim_quality_flag

    async def run_now(
        self,
        job: VideoPipelineJob,
        *,
        ctx: StageContext | None = None,
    ) -> VideoPipelineResult:
        workspace = await asyncio.to_thread(self._job_workspace, job.job_id)
        final_path = workspace / "final.mp4"
        effective_ctx = ctx or StageContext()
        if effective_ctx.dry_run_output_path == "dry-run.mp4":
            effective_ctx.dry_run_output_path = str(final_path)

        result = await run_job(job, ctx=effective_ctx)
        output_path = Path(result.final_video.output_path)
        if await asyncio.to_thread(output_path.exists):
            return result

        await self._render_templates_to_final(result, workspace=workspace, final_path=output_path)
        return result

    def _job_workspace(self, job_id: str) -> Path:
        workspace_root = self._workspace_root or _DEFAULT_WORKSPACE_ROOT
        workspace = workspace_root / _safe_path_part(job_id)
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    async def _render_templates_to_final(
        self,
        result: VideoPipelineResult,
        *,
        workspace: Path,
        final_path: Path,
    ) -> None:
        manim_bin = shutil.which("manim")
        if manim_bin is None:
            raise PhaseAInlineRenderError(
                "Phase A inline render requires manim in PATH "
                "(plus TeX Live, xelatex, ffmpeg, and Noto Sans CJK KR for Korean math videos)."
            )

        segment_paths: list[Path] = []
        for index, segment in enumerate(result.rendered_segments, start=1):
            template = segment.diagnostics.get("template")
            if not isinstance(template, dict):
                continue
            source = template.get("manim_source")
            scene_class_name = template.get("scene_class_name")
            if not isinstance(source, str) or not isinstance(scene_class_name, str):
                continue
            safe_segment_id = _safe_path_part(segment.segment_id)
            segment_paths.append(
                await self._render_template_segment(
                    manim_bin,
                    source,
                    scene_class_name,
                    workspace=workspace / "segments" / f"{index:03d}-{safe_segment_id}",
                )
            )

        if not segment_paths:
            raise PhaseAInlineRenderError(
                "Phase A inline render found no deterministic template Manim source."
            )

        await asyncio.to_thread(final_path.parent.mkdir, parents=True, exist_ok=True)
        if len(segment_paths) == 1:
            await asyncio.to_thread(shutil.copyfile, segment_paths[0], final_path)
            return

        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin is None:
            raise PhaseAInlineRenderError(
                "Phase A inline render requires ffmpeg in PATH to compose multiple segments."
            )
        await self._compose_segments(ffmpeg_bin, segment_paths, final_path=final_path)

    async def _render_template_segment(
        self,
        manim_bin: str,
        manim_source: str,
        scene_class_name: str,
        *,
        workspace: Path,
    ) -> Path:
        await asyncio.to_thread(workspace.mkdir, parents=True, exist_ok=True)
        source_path = workspace / "scene.py"
        await asyncio.to_thread(source_path.write_text, manim_source, encoding="utf-8")
        media_dir = workspace / "media"

        await _run_command(
            [
                manim_bin,
                self._manim_quality_flag,
                "--media_dir",
                str(media_dir),
                str(source_path),
                scene_class_name,
            ],
            cwd=workspace,
            error_prefix=f"manim render failed for {scene_class_name}",
        )

        rendered_mp4 = await asyncio.to_thread(
            _latest_rendered_mp4,
            media_dir,
            scene_class_name,
        )
        if rendered_mp4 is None:
            raise PhaseAInlineRenderError(
                f"manim finished but no mp4 was produced for {scene_class_name}"
            )
        return rendered_mp4

    async def _compose_segments(
        self,
        ffmpeg_bin: str,
        segment_paths: Sequence[Path],
        *,
        final_path: Path,
    ) -> None:
        concat_file = final_path.parent / "segments.txt"
        await asyncio.to_thread(
            concat_file.write_text,
            "\n".join(_ffmpeg_concat_line(path) for path in segment_paths) + "\n",
            encoding="utf-8",
        )
        await _run_command(
            [
                ffmpeg_bin,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                str(final_path),
            ],
            cwd=final_path.parent,
            error_prefix="ffmpeg compose failed for Phase A inline video",
        )


class LocalInlineArtifactUploader:
    """Development uploader that stores mp4 files under a local artifact root."""

    def __init__(self, artifact_root: Path | str | None = None) -> None:
        self._artifact_root = Path(artifact_root) if artifact_root is not None else None

    async def upload_final_video(
        self,
        *,
        job_id: str,
        output_path: str,
    ) -> InlineVideoArtifact:
        source = Path(output_path)
        if not await asyncio.to_thread(source.exists):
            raise PhaseAInlineRenderError(f"final mp4 does not exist: {source}")
        artifact_root = self._artifact_root or Path.cwd() / "uploads" / "video-inline"
        safe_job_id = _safe_path_part(job_id)
        destination = artifact_root / safe_job_id / "final.mp4"
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, source, destination)
        return InlineVideoArtifact(
            object_key=f"inline-video-jobs/{safe_job_id}/final.mp4",
            url=destination.resolve().as_uri(),
        )


async def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    error_prefix: str,
) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        return
    output = "\n".join(
        part.decode(errors="replace").strip() for part in (stdout, stderr) if part.strip()
    )
    raise PhaseAInlineRenderError(f"{error_prefix}: {output[-3000:]}")


def _safe_path_part(value: str) -> str:
    safe = _SAFE_PATH_RE.sub("-", value.strip()).strip(".-")
    return safe or "video-job"


def _ffmpeg_concat_line(path: Path) -> str:
    escaped = str(path.resolve()).replace("'", "'\\''")
    return f"file '{escaped}'"


def _latest_rendered_mp4(media_dir: Path, scene_class_name: str) -> Path | None:
    matches = list(media_dir.rglob(f"{scene_class_name}.mp4"))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


__all__ = [
    "InlineVideoArtifact",
    "InlineVideoArtifactUploader",
    "InlineVideoRunner",
    "LocalInlineArtifactUploader",
    "PhaseAInlineRenderError",
    "PhaseAInlineRunner",
]

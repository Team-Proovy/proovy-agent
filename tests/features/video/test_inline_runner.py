"""Phase A inline runner boundary tests."""

import asyncio
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from proovy_agent.features.video.models import (
    FinalVideoArtifact,
    RenderedSegment,
    ScriptSegment,
    SegmentTTSResult,
    SolutionPlan,
    SolutionStep,
    VideoJobInput,
    VideoPipelineJob,
    VideoPipelineResult,
    VideoScript,
)
from proovy_agent.features.video.pipeline import inline_runner as inline_runner_module
from proovy_agent.features.video.pipeline.inline_runner import (
    LocalInlineArtifactUploader,
    PhaseAInlineRenderError,
    PhaseAInlineRunner,
)
from proovy_agent.features.video.pipeline.stage_context import StageContext


def _job() -> VideoPipelineJob:
    return VideoPipelineJob(
        job_id="job-1",
        input_snapshot=VideoJobInput(
            problem_text="x - 3 = 2를 풀어라.",
            solution_plan=SolutionPlan(
                title="일차방정식",
                steps=[SolutionStep(step_number=1, explanation="x=5를 확인합니다.")],
                final_answer="x=5",
            ),
        ),
    )


def _skip_without_manim_stack() -> None:
    manim = shutil.which("manim")
    ffmpeg = shutil.which("ffmpeg")
    xelatex = shutil.which("xelatex")
    kpsewhich = shutil.which("kpsewhich")
    if manim is None or ffmpeg is None or xelatex is None or kpsewhich is None:
        pytest.skip("manim/ffmpeg/xelatex/kpsewhich stack is not installed")

    xe_cjk = subprocess.run(
        [kpsewhich, "xeCJK.sty"],
        capture_output=True,
        text=True,
        check=False,
    )
    if xe_cjk.returncode != 0:
        pytest.skip("xeCJK.sty is not installed")


def _pipeline_result(job_id: str, output_path: Path) -> VideoPipelineResult:
    plan = _job().input_snapshot.solution_plan
    assert plan is not None
    script = VideoScript(
        title=plan.title,
        segments=[
            ScriptSegment(
                segment_id="step-1",
                order=1,
                visual_type="equation_write",
                narration="x=5를 확인합니다.",
                params={},
                source_step_number=1,
            )
        ],
        final_answer=plan.final_answer,
    )
    return VideoPipelineResult(
        job_id=job_id,
        solution_plan=plan,
        script=script,
        tts_results=[SegmentTTSResult(segment_id="step-1", narration="x=5를 확인합니다.")],
        rendered_segments=[
            RenderedSegment(
                segment_id="step-1",
                visual_type="equation_write",
                diagnostics={
                    "template": {
                        "scene_class_name": "EquationWriteScene",
                        "manim_source": "from manim import *\n",
                    }
                },
            )
        ],
        final_video=FinalVideoArtifact(
            output_path=str(output_path),
            rendered_segment_count=1,
        ),
    )


@pytest.mark.asyncio
async def test_phase_a_inline_runner_names_local_render_preconditions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake_run_job(
        job: VideoPipelineJob,
        *,
        ctx: object,
    ) -> VideoPipelineResult:
        _ = ctx
        return _pipeline_result(job.job_id, tmp_path / "final.mp4")

    monkeypatch.setattr(inline_runner_module, "run_job", fake_run_job)
    monkeypatch.setattr(inline_runner_module.shutil, "which", lambda _name: None)

    with pytest.raises(PhaseAInlineRenderError, match="Phase A inline render requires manim"):
        await PhaseAInlineRunner(workspace_root=tmp_path).run_now(_job())


@pytest.mark.asyncio
async def test_local_inline_artifact_uploader_copies_mp4_and_returns_file_url(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"mp4")
    uploader = LocalInlineArtifactUploader(artifact_root=tmp_path / "artifacts")

    artifact = await uploader.upload_final_video(job_id="job-1", output_path=str(source))

    uploaded = tmp_path / "artifacts" / "job-1" / "final.mp4"
    assert uploaded.read_bytes() == b"mp4"
    assert artifact.object_key == "inline-video-jobs/job-1/final.mp4"
    assert artifact.url == uploaded.resolve().as_uri()


def test_phase_a_inline_smoke_renders_mp4_and_uploads_when_stack_available(
    tmp_path: Path,
) -> None:
    _skip_without_manim_stack()

    result = asyncio.run(
        PhaseAInlineRunner(workspace_root=tmp_path / "workspace").run_now(
            _job(),
            ctx=StageContext(),
        )
    )
    output_path = Path(result.final_video.output_path)

    assert output_path.exists()
    assert output_path.suffix == ".mp4"
    assert output_path.stat().st_size > 0

    artifact = asyncio.run(
        LocalInlineArtifactUploader(artifact_root=tmp_path / "artifacts").upload_final_video(
            job_id=result.job_id,
            output_path=str(output_path),
        )
    )

    uploaded = tmp_path / "artifacts" / result.job_id / "final.mp4"
    assert uploaded.exists()
    assert uploaded.stat().st_size == output_path.stat().st_size
    assert artifact.url == uploaded.resolve().as_uri()


def test_phase_a_inline_smoke_renders_mp4_and_uploads_with_fake_manim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_manim = fake_bin / "manim"
    fake_manim.write_text(
        """#!/usr/bin/env python3
from pathlib import Path
import shutil
import subprocess
import sys

media_dir = Path(sys.argv[sys.argv.index("--media_dir") + 1])
scene_class_name = sys.argv[-1]
output_path = media_dir / "videos" / "scene" / "480p15" / f"{scene_class_name}.mp4"
output_path.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(
    [
        shutil.which("ffmpeg") or "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=16x16:d=0.2",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ],
    check=True,
)
""",
        encoding="utf-8",
    )
    fake_manim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")

    result = asyncio.run(
        PhaseAInlineRunner(workspace_root=tmp_path / "workspace").run_now(
            _job(),
            ctx=StageContext(),
        )
    )
    output_path = Path(result.final_video.output_path)

    assert output_path.exists()
    assert output_path.suffix == ".mp4"
    assert output_path.stat().st_size > 0

    artifact = asyncio.run(
        LocalInlineArtifactUploader(artifact_root=tmp_path / "artifacts").upload_final_video(
            job_id=result.job_id,
            output_path=str(output_path),
        )
    )

    uploaded = tmp_path / "artifacts" / result.job_id / "final.mp4"
    assert uploaded.exists()
    assert uploaded.stat().st_size == output_path.stat().st_size
    assert artifact.object_key == f"inline-video-jobs/{result.job_id}/final.mp4"
    assert artifact.url == uploaded.resolve().as_uri()

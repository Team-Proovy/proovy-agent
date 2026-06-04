"""Phase A deterministic visual template smoke tests."""

from __future__ import annotations

import ast
from collections.abc import Mapping
import shutil
import subprocess

import pytest

from proovy_agent.features.video.exceptions import InvalidStageOutputError
from proovy_agent.features.video.models import (
    ScriptSegment,
    SegmentTTSResult,
    VideoJobInput,
    VideoPipelineJob,
    VideoScript,
)
from proovy_agent.features.video.pipeline import StageContext
from proovy_agent.features.video.pipeline.stages import stage_render
from proovy_agent.features.video.visual_types import (
    PHASE_A_DETERMINISTIC_VISUAL_TYPES,
    DeterministicTemplateRender,
    create_phase_a_visual_type_registry,
)
from proovy_agent.features.video.visual_types.templates import render_equation_write


def _sample_params(visual_type: str) -> dict[str, object]:
    params: dict[str, dict[str, object]] = {
        "intro_problem": {
            "title": "일차방정식 풀이",
            "problem_text": "한국어 문제: 2x + 1 = 7을 풀어라.",
            "visual_description": "문제와 핵심 조건을 안정적으로 배치합니다.",
            "hints": ["양변을 비교", "정답 x = 3 강조"],
            "emphasis_targets": ["x = 3"],
        },
        "equation_write": {
            "latex_expression": r"\text{정답은 } x = 3",
            "visual_description": "한국어와 수식이 함께 있는 핵심 식을 표시합니다.",
            "emphasis_targets": ["x = 3"],
        },
        "equation_derivation": {
            "latex_steps": [r"2x + 1 = 7", r"2x = 6", r"x = 3"],
            "visual_description": "수식 전개를 위에서 아래로 정렬합니다.",
            "emphasis_targets": ["x = 3"],
        },
        "highlight_result": {
            "result_latex": r"\boxed{x = 3}",
            "visual_description": "최종 결과를 박스로 강조합니다.",
            "emphasis_targets": ["x = 3"],
        },
        "outro_summary": {
            "summary": ["양변에서 1을 뺍니다.", "양변을 2로 나눕니다.", "정답은 x = 3입니다."],
            "final_answer": r"x = 3",
            "visual_description": "풀이 흐름을 짧게 요약합니다.",
            "emphasis_targets": ["x = 3"],
        },
    }
    return params[visual_type]


def _assert_only_manim_imports(source: str) -> None:
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_roots.add(node.module.split(".", maxsplit=1)[0])
    assert imported_roots == {"manim"}


def _assert_smoke_source(output: DeterministicTemplateRender) -> None:
    ast.parse(output.manim_source)
    _assert_only_manim_imports(output.manim_source)
    assert f"class {output.scene_class_name}(Scene)" in output.manim_source
    assert 'TexTemplate(tex_compiler="xelatex"' in output.manim_source
    assert "\\usepackage{xeCJK}" in output.manim_source
    assert "Noto Sans CJK KR" in output.manim_source
    assert "\\setmainfont{Noto Sans CJK KR}" in output.manim_source
    assert "\\setmainfont{Noto Sans}" not in output.manim_source
    assert "visual_scene" not in output.manim_source
    assert "graph_plot" not in output.manim_source


def test_phase_a_registry_registers_renderable_template_contracts() -> None:
    registry = create_phase_a_visual_type_registry()

    assert tuple(definition.visual_type for definition in registry) == tuple(
        sorted(PHASE_A_DETERMINISTIC_VISUAL_TYPES)
    )
    for visual_type in PHASE_A_DETERMINISTIC_VISUAL_TYPES:
        params = _sample_params(visual_type)
        registry.validate_params(visual_type, params)

        output = registry.require(visual_type).render_fn(**params)

        assert isinstance(output, DeterministicTemplateRender)
        assert output.visual_type == visual_type
        assert output.scene_class_name.endswith("Scene")
        assert output.as_diagnostics()["kind"] == "manim_source"
        assert output.diagnostics["uses_cjk_tex_template"] is True
        _assert_smoke_source(output)

    with pytest.raises(ValueError, match=r"params.hints must contain at most 3 items"):
        registry.validate_params(
            "intro_problem",
            {
                **_sample_params("intro_problem"),
                "hints": ["조건 1", "조건 2", "조건 3", "조건 4"],
            },
        )

    with pytest.raises(ValueError, match=r"params.summary must contain at least 1 items"):
        registry.validate_params(
            "outro_summary",
            {
                **_sample_params("outro_summary"),
                "summary": [],
            },
        )

    with pytest.raises(ValueError, match=r"params.summary must contain at most 4 items"):
        registry.validate_params(
            "outro_summary",
            {
                **_sample_params("outro_summary"),
                "summary": ["1", "2", "3", "4", "5"],
            },
        )


def test_phase_a_template_smoke_sources_cover_cjk_and_math() -> None:
    registry = create_phase_a_visual_type_registry()
    outputs = [
        registry.require(visual_type).render_fn(**_sample_params(visual_type))
        for visual_type in PHASE_A_DETERMINISTIC_VISUAL_TYPES
    ]

    assert all(isinstance(output, DeterministicTemplateRender) for output in outputs)
    assert any("한국어" in output.manim_source for output in outputs)
    assert all(output.diagnostics["contains_cjk_text"] is True for output in outputs)
    assert sum(int(output.diagnostics["math_expression_count"]) for output in outputs) >= 5


async def test_stage_render_attaches_phase_a_template_diagnostics() -> None:
    script = VideoScript(
        title="일차방정식 풀이",
        segments=[
            ScriptSegment(
                segment_id=visual_type,
                order=index,
                visual_type=visual_type,
                narration="템플릿 smoke narration",
                params=_sample_params(visual_type),
            )
            for index, visual_type in enumerate(PHASE_A_DETERMINISTIC_VISUAL_TYPES, start=1)
        ],
        final_answer="x = 3",
    )

    rendered_segments = await stage_render(
        script,
        [
            SegmentTTSResult(
                segment_id=segment.segment_id,
                narration=segment.narration,
                duration_seconds=1.0,
            )
            for segment in script.segments
        ],
        job=VideoPipelineJob(
            job_id="job-1",
            input_snapshot=VideoJobInput(problem_text="한국어 문제: 2x + 1 = 7을 풀어라."),
        ),
        ctx=StageContext(),
    )

    assert [segment.visual_type for segment in rendered_segments] == list(
        PHASE_A_DETERMINISTIC_VISUAL_TYPES
    )
    for rendered_segment in rendered_segments:
        assert rendered_segment.diagnostics["dry_run"] is True
        assert rendered_segment.diagnostics["render_mode"] == "template_source"
        template = rendered_segment.diagnostics["template"]
        assert isinstance(template, Mapping)
        assert template["kind"] == "manim_source"
        assert template["visual_type"] == rendered_segment.visual_type
        assert "class " in str(template["manim_source"])


async def test_stage_render_includes_template_render_error_details() -> None:
    script = VideoScript(
        title="일차방정식 풀이",
        segments=[
            ScriptSegment(
                segment_id="outro",
                order=1,
                visual_type="outro_summary",
                narration="풀이를 요약합니다.",
                params={
                    "summary": [],
                    "visual_description": "빈 요약은 렌더할 수 없습니다.",
                },
            )
        ],
    )

    with pytest.raises(InvalidStageOutputError) as exc_info:
        await stage_render(
            script,
            [SegmentTTSResult(segment_id="outro", narration="풀이를 요약합니다.")],
            job=VideoPipelineJob(
                job_id="job-1",
                input_snapshot=VideoJobInput(problem_text="한국어 문제: 2x + 1 = 7을 풀어라."),
            ),
            ctx=StageContext(),
        )

    assert exc_info.value.details == {
        "segment_id": "outro",
        "visual_type": "outro_summary",
        "error": "params.summary must contain at least 1 items",
        "error_type": "ValueError",
    }


def test_phase_a_cjk_mathtex_smoke_render_when_manim_stack_available(tmp_path) -> None:
    manim = shutil.which("manim")
    xelatex = shutil.which("xelatex")
    kpsewhich = shutil.which("kpsewhich")
    if manim is None or xelatex is None or kpsewhich is None:
        pytest.skip("manim/xelatex/kpsewhich stack is not installed")

    xe_cjk = subprocess.run(
        [kpsewhich, "xeCJK.sty"],
        capture_output=True,
        text=True,
        check=False,
    )
    if xe_cjk.returncode != 0:
        pytest.skip("xeCJK.sty is not installed")

    output = render_equation_write(
        latex_expression=r"\text{정답은 } x = 3",
        visual_description="한국어 MathTex smoke 렌더입니다.",
        emphasis_targets=["x = 3"],
    )
    scene_path = tmp_path / "phase_a_cjk_smoke.py"
    scene_path.write_text(output.manim_source, encoding="utf-8")

    completed = subprocess.run(
        [manim, "-ql", "-s", str(scene_path), output.scene_class_name],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-2000:]
    assert list(tmp_path.rglob("*.png"))

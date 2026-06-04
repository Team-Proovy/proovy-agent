"""Phase A deterministic visual type catalog."""

from __future__ import annotations

from typing import Any

from proovy_agent.features.video.visual_types.registry import VisualTypeRegistry

PHASE_A_DETERMINISTIC_VISUAL_TYPES: tuple[str, ...] = (
    "intro_problem",
    "equation_write",
    "equation_derivation",
    "highlight_result",
    "outro_summary",
)

_STRING_ARRAY_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string"},
}


def _placeholder_render_fn(**kwargs: Any) -> dict[str, Any]:
    """Keep registry render_fn callable until deterministic templates land."""
    return dict(kwargs)


def register_phase_a_visual_types(registry: VisualTypeRegistry) -> None:
    """Register the deterministic Phase A template metadata."""
    registry.register(
        "intro_problem",
        schema={
            "type": "object",
            "required": ["title", "problem_text", "visual_description"],
            "properties": {
                "title": {"type": "string"},
                "problem_text": {"type": "string"},
                "visual_description": {"type": "string"},
                "hints": _STRING_ARRAY_SCHEMA,
                "emphasis_targets": _STRING_ARRAY_SCHEMA,
            },
            "additionalProperties": False,
        },
        prompt_snippet=(
            "Introduce the original problem text and its key givens. "
            "Use only static text layout and deterministic emphasis."
        ),
        render_fn=_placeholder_render_fn,
        fallback_candidates=["equation_write"],
        narration_alignment_rule=(
            "Narration must state what problem is being solved before any transformation."
        ),
    )
    registry.register(
        "equation_write",
        schema={
            "type": "object",
            "required": ["latex_expression", "visual_description"],
            "properties": {
                "latex_expression": {"type": "string"},
                "visual_description": {"type": "string"},
                "emphasis_targets": _STRING_ARRAY_SCHEMA,
            },
            "additionalProperties": False,
        },
        prompt_snippet=(
            "Display one LaTeX equation clearly. Use this for a single equation or "
            "a step that should not depend on previous scene state."
        ),
        render_fn=_placeholder_render_fn,
        fallback_candidates=["highlight_result"],
        narration_alignment_rule="Narration must mention the equation being written.",
    )
    registry.register(
        "equation_derivation",
        schema={
            "type": "object",
            "required": ["latex_steps", "visual_description"],
            "properties": {
                "latex_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 5,
                },
                "visual_description": {"type": "string"},
                "emphasis_targets": _STRING_ARRAY_SCHEMA,
            },
            "additionalProperties": False,
        },
        prompt_snippet=(
            "Show a deterministic 2-5 line derivation. Do not rely on previous scene "
            "objects; each line must be self-contained."
        ),
        render_fn=_placeholder_render_fn,
        fallback_candidates=["equation_write"],
        narration_alignment_rule="Narration must describe the transformation between lines.",
    )
    registry.register(
        "highlight_result",
        schema={
            "type": "object",
            "required": ["result_latex", "visual_description"],
            "properties": {
                "result_latex": {"type": "string"},
                "visual_description": {"type": "string"},
                "emphasis_targets": _STRING_ARRAY_SCHEMA,
            },
            "additionalProperties": False,
        },
        prompt_snippet=(
            "Highlight the final answer or the current result. Use deterministic text "
            "and box emphasis only."
        ),
        render_fn=_placeholder_render_fn,
        fallback_candidates=["equation_write"],
        narration_alignment_rule="Narration must match the highlighted result.",
    )
    registry.register(
        "outro_summary",
        schema={
            "type": "object",
            "required": ["summary", "visual_description"],
            "properties": {
                "summary": _STRING_ARRAY_SCHEMA,
                "final_answer": {"type": "string"},
                "visual_description": {"type": "string"},
                "emphasis_targets": _STRING_ARRAY_SCHEMA,
            },
            "additionalProperties": False,
        },
        prompt_snippet=(
            "Summarize the completed solution in short deterministic text lines. "
            "Do not introduce new mathematical claims."
        ),
        render_fn=_placeholder_render_fn,
        fallback_candidates=["highlight_result"],
        narration_alignment_rule="Narration must summarize only steps present in the plan.",
    )
    registry.validate_fallback_candidates()


def create_phase_a_visual_type_registry() -> VisualTypeRegistry:
    """Return a fresh registry containing only Phase A deterministic templates."""
    registry = VisualTypeRegistry()
    register_phase_a_visual_types(registry)
    return registry

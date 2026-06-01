"""VisualTypeRegistry contract tests."""

import pytest

from proovy_agent.features.video.visual_types import VisualTypeRegistry


def _render_stub(**kwargs: object) -> dict[str, object]:
    return kwargs


def test_empty_visual_type_registry_has_empty_catalog() -> None:
    registry = VisualTypeRegistry()

    assert len(registry) == 0
    assert list(registry) == []
    assert registry.prompt_catalog() == ""
    assert ["not_hashable"] not in registry


def test_registry_keeps_core_five_visual_type_fields() -> None:
    registry = VisualTypeRegistry()

    definition = registry.register(
        "equation_write",
        schema={"type": "object", "properties": {"latex": {"type": "string"}}},
        prompt_snippet="Write one equation clearly.",
        render_fn=_render_stub,
        fallback_candidates=["highlight_result"],
        narration_alignment_rule="Narration must mention the equation being written.",
    )

    assert registry.get("equation_write") == definition
    assert registry.require("equation_write").render_fn(latex="x=3") == {"latex": "x=3"}
    assert definition.schema["type"] == "object"
    assert definition.prompt_snippet == "Write one equation clearly."
    assert definition.fallback_candidates == ("highlight_result",)
    assert definition.narration_alignment_rule.startswith("Narration must")
    assert registry.prompt_catalog() == "## equation_write\nWrite one equation clearly."

    with pytest.raises(KeyError, match="equation_write->highlight_result"):
        registry.validate_fallback_candidates()

    registry.register(
        "highlight_result",
        schema={"type": "object"},
        prompt_snippet="Highlight the final result.",
        render_fn=_render_stub,
        fallback_candidates=[],
        narration_alignment_rule="Narration must mention the result being highlighted.",
    )

    registry.validate_fallback_candidates()


def test_registry_rejects_duplicate_or_blank_metadata() -> None:
    registry = VisualTypeRegistry()
    registry.register(
        "equation_write",
        schema={},
        prompt_snippet="Snippet",
        render_fn=_render_stub,
        fallback_candidates=[],
        narration_alignment_rule="Rule",
    )

    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            "equation_write",
            schema={},
            prompt_snippet="Snippet",
            render_fn=_render_stub,
            fallback_candidates=[],
            narration_alignment_rule="Rule",
        )

    with pytest.raises(ValueError, match="prompt_snippet must not be empty"):
        VisualTypeRegistry().register(
            "highlight_result",
            schema={},
            prompt_snippet=" ",
            render_fn=_render_stub,
            fallback_candidates=[],
            narration_alignment_rule="Rule",
        )

"""Single source of truth for video visual_type metadata."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


class RenderFunction(Protocol):
    """Callable contract for a visual_type renderer."""

    def __call__(self, **kwargs: Any) -> object: ...


def _strip_required(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


def _normalize_fallback_candidates(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = tuple(candidate.strip() for candidate in values)
    if any(not candidate for candidate in normalized):
        raise ValueError("fallback_candidates must not contain blank items")
    return normalized


@dataclass(frozen=True, slots=True)
class VisualTypeDefinition:
    """Core metadata for one visual_type.

    The five fields here are intentionally the complete MVP registry contract:
    schema, prompt snippet, render function, fallback candidates, and narration
    alignment rule.
    """

    visual_type: str
    schema: Mapping[str, Any]
    prompt_snippet: str
    render_fn: RenderFunction
    fallback_candidates: tuple[str, ...]
    narration_alignment_rule: str

    @classmethod
    def create(
        cls,
        *,
        visual_type: str,
        schema: Mapping[str, Any],
        prompt_snippet: str,
        render_fn: RenderFunction,
        fallback_candidates: tuple[str, ...] | list[str],
        narration_alignment_rule: str,
    ) -> VisualTypeDefinition:
        """Validate and freeze visual_type metadata at registration time."""
        return cls(
            visual_type=_strip_required(visual_type, "visual_type"),
            schema=MappingProxyType(dict(schema)),
            prompt_snippet=_strip_required(prompt_snippet, "prompt_snippet"),
            render_fn=render_fn,
            fallback_candidates=_normalize_fallback_candidates(fallback_candidates),
            narration_alignment_rule=_strip_required(
                narration_alignment_rule, "narration_alignment_rule"
            ),
        )


class VisualTypeRegistry:
    """Registry used by scriptify, validators, render, and fallback code."""

    def __init__(self) -> None:
        self._definitions: dict[str, VisualTypeDefinition] = {}

    def register(
        self,
        visual_type: str,
        *,
        schema: Mapping[str, Any],
        prompt_snippet: str,
        render_fn: RenderFunction,
        fallback_candidates: tuple[str, ...] | list[str] = (),
        narration_alignment_rule: str,
    ) -> VisualTypeDefinition:
        """Register a visual_type definition with the core five metadata fields."""
        definition = VisualTypeDefinition.create(
            visual_type=visual_type,
            schema=schema,
            prompt_snippet=prompt_snippet,
            render_fn=render_fn,
            fallback_candidates=fallback_candidates,
            narration_alignment_rule=narration_alignment_rule,
        )
        if definition.visual_type in self._definitions:
            raise ValueError(f"visual_type already registered: {definition.visual_type}")
        self._definitions[definition.visual_type] = definition
        return definition

    def get(self, visual_type: str) -> VisualTypeDefinition | None:
        """Return a registered definition, or None if the visual_type is unknown."""
        return self._definitions.get(visual_type)

    def require(self, visual_type: str) -> VisualTypeDefinition:
        """Return a definition or raise KeyError with a stable message."""
        try:
            return self._definitions[visual_type]
        except KeyError as exc:
            raise KeyError(f"unknown visual_type: {visual_type}") from exc

    def validate_fallback_candidates(self) -> None:
        """Fail fast when registered fallbacks reference missing visual_types."""
        missing: list[str] = []
        for definition in self._definitions.values():
            for candidate in definition.fallback_candidates:
                if candidate not in self._definitions:
                    missing.append(f"{definition.visual_type}->{candidate}")
        if missing:
            raise KeyError(f"unknown fallback_candidates: {', '.join(sorted(missing))}")

    def prompt_catalog(self) -> str:
        """Render deterministic scriptify catalog text from registered snippets."""
        return "\n\n".join(
            f"## {visual_type}\n{definition.prompt_snippet}"
            for visual_type, definition in sorted(self._definitions.items())
        )

    def __contains__(self, visual_type: object) -> bool:
        return visual_type in self._definitions

    def __iter__(self) -> Iterator[VisualTypeDefinition]:
        for visual_type in sorted(self._definitions):
            yield self._definitions[visual_type]

    def __len__(self) -> int:
        return len(self._definitions)

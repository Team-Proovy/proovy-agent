"""Single source of truth for video visual_type metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator


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


def _is_json_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _validate_schema_type(schema_type: object, value: object, path: str) -> None:
    if schema_type == "object":
        if not isinstance(value, Mapping):
            raise ValueError(f"{path} must be an object")
        return
    if schema_type == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        return
    if schema_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string")
        if not value.strip():
            raise ValueError(f"{path} must not be blank")
        return
    if schema_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{path} must be an integer")
        return
    if schema_type == "number":
        if not _is_json_number(value):
            raise ValueError(f"{path} must be a number")
        return
    if schema_type == "boolean" and not isinstance(value, bool):
        raise ValueError(f"{path} must be a boolean")


def _validate_schema_subset(schema: Mapping[str, Any], value: object, path: str) -> None:
    """Validate the small JSON-schema subset used by visual type params."""
    schema_type = schema.get("type")
    if schema_type is not None:
        _validate_schema_type(schema_type, value, path)

    enum_values = schema.get("enum")
    if enum_values is not None and value not in enum_values:
        raise ValueError(f"{path} must be one of {enum_values}")

    if schema_type == "object" or "properties" in schema:
        if not isinstance(value, Mapping):
            raise ValueError(f"{path} must be an object")
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise ValueError(f"{path} schema properties must be an object")
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise ValueError(f"{path} schema required must be an array")
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError(f"{path} missing required fields: {', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise ValueError(f"{path} contains unsupported fields: {', '.join(extras)}")
        for key, item_schema in properties.items():
            if key in value and isinstance(item_schema, Mapping):
                _validate_schema_subset(item_schema, value[key], f"{path}.{key}")
        return

    if schema_type == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            raise ValueError(f"{path} must contain at least {min_items} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate_schema_subset(item_schema, item, f"{path}[{index}]")


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

    def validate_params(self, visual_type: str, params: Mapping[str, Any]) -> None:
        """Validate segment params against a registered visual_type schema subset."""
        definition = self.require(visual_type)
        _validate_schema_subset(definition.schema, params, "params")

    def prompt_catalog(self) -> str:
        """Render deterministic scriptify catalog text from registered snippets."""
        return "\n\n".join(
            f"## {visual_type}\n{definition.prompt_snippet}"
            for visual_type, definition in sorted(self._definitions.items())
        )

    def __contains__(self, visual_type: object) -> bool:
        try:
            return visual_type in self._definitions
        except TypeError:
            return False

    def __iter__(self) -> Iterator[VisualTypeDefinition]:
        for visual_type in sorted(self._definitions):
            yield self._definitions[visual_type]

    def __len__(self) -> int:
        return len(self._definitions)

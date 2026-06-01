"""Visual type registry contracts."""

from proovy_agent.features.video.visual_types.phase_a import (
    PHASE_A_DETERMINISTIC_VISUAL_TYPES,
    create_phase_a_visual_type_registry,
    register_phase_a_visual_types,
)
from proovy_agent.features.video.visual_types.registry import (
    RenderFunction,
    VisualTypeDefinition,
    VisualTypeRegistry,
)

__all__ = [
    "PHASE_A_DETERMINISTIC_VISUAL_TYPES",
    "RenderFunction",
    "VisualTypeDefinition",
    "VisualTypeRegistry",
    "create_phase_a_visual_type_registry",
    "register_phase_a_visual_types",
]

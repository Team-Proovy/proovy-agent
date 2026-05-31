"""Shared resources and progress seam for video pipeline stages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import inspect
from typing import TYPE_CHECKING, Any, Literal

from proovy_agent.features.video.visual_types import VisualTypeRegistry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from proovy_agent.features.video.models import StageName

StageEventStatus = Literal["started", "completed", "failed"]


@dataclass(frozen=True, slots=True)
class StageEvent:
    """Observable stage boundary event emitted by the orchestrator."""

    stage: StageName
    status: StageEventStatus


type StageProgressHandler = Callable[[StageEvent], Awaitable[None] | None]


@dataclass(slots=True)
class StageContext:
    """Resource bundle shared across pipeline stages.

    Most fields are optional so Phase A inline execution and tests can use the
    same contract before worker-only resources exist.
    """

    registry: VisualTypeRegistry = field(default_factory=VisualTypeRegistry)
    settings: Any | None = None
    llm: Any | None = None
    tts: Any | None = None
    db: Any | None = None
    workspace: Any | None = None
    sandbox: Any | None = None
    cancel_event: asyncio.Event | None = None
    progress_handler: StageProgressHandler | None = None
    stage_events: list[StageEvent] = field(default_factory=list)
    default_visual_type: str = "dry_run"
    dry_run_output_path: str = "dry-run.mp4"

    async def emit_stage_event(self, stage: StageName, status: StageEventStatus) -> None:
        """Record and optionally forward one stage boundary event."""
        event = StageEvent(stage=stage, status=status)
        self.stage_events.append(event)
        if self.progress_handler is None:
            return
        maybe_awaitable = self.progress_handler(event)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable

    def raise_if_cancelled(self) -> None:
        """Check cooperative cancellation at stage boundaries."""
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise asyncio.CancelledError

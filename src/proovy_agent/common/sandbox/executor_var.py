"""Context variable for the current sandbox executor."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from proovy_agent.common.sandbox.executor import CodeExecutor

current_executor: ContextVar[CodeExecutor | None] = ContextVar("current_executor", default=None)

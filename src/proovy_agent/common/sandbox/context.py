"""Request-scoped sandbox context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from proovy_agent.common.sandbox.models import ExecutorStatus

if TYPE_CHECKING:
    import asyncio

    from proovy_agent.common.sandbox.executor import CodeExecutor


@dataclass
class RequestExecutorContext:
    """1턴 동안만 메모리에 존재. 턴 종료 시 흔적 없이 소멸."""

    task: asyncio.Task[CodeExecutor] | None = None
    status: ExecutorStatus = ExecutorStatus.NONE
    error: str | None = None
    recovery_count: int = 0

"""Sandbox request context tests."""

from proovy_agent.common.sandbox.context import RequestExecutorContext
from proovy_agent.common.sandbox.models import ExecutorStatus


def test_request_executor_context_defaults_are_memory_only_state() -> None:
    """RequestExecutorContext starts without an executor task or error."""
    context = RequestExecutorContext()

    assert context.task is None
    assert context.status is ExecutorStatus.NONE
    assert context.error is None
    assert context.recovery_count == 0

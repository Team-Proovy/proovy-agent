"""code_execute tool — Daytona 샌드박스에서 Python 코드 실행."""

from langchain_core.tools import tool

from proovy_agent.common.sandbox.executor_var import current_executor
from proovy_agent.common.sse.context import current_emitter

_MAX_OUTPUT = 500


@tool
async def code_execute(code: str) -> str:
    """Python 코드를 Daytona 샌드박스에서 실행하고 결과를 반환합니다.
    실행 결과의 stdout/stderr/exit_code를 포함합니다.

    Args:
        code: 실행할 Python 코드 (print()로 결과 출력 필요)
    """
    emitter = current_emitter.get()
    executor = current_executor.get()

    if emitter:
        await emitter.emit("tool_start", {"name": "code_execute", "label": "코드 실행 중..."})

    if executor is None:
        raise RuntimeError("Sandbox executor not initialized")

    result = await executor.run_python(code)

    parts: list[str] = []
    if result.stdout:
        parts.append(f"stdout:\n{result.stdout}")
    if result.stderr:
        parts.append(f"stderr:\n{result.stderr}")
    if result.error:
        parts.append(f"error: {result.error.name}: {result.error.value}")
    if not result.success:
        parts.append("exit_code: 1")
    output = "\n".join(parts) if parts else "(no output)"

    if len(output) > _MAX_OUTPUT:
        output = output[:_MAX_OUTPUT] + "... [TRIMMED]"

    if emitter:
        await emitter.emit(
            "tool_result",
            {"name": "code_execute", "output": output, "success": result.success},
        )

    return output

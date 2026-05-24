"""code_generate tool — 수학 문제 검증용 Python 코드 생성."""

from langchain_core.tools import tool

from proovy_agent.common.llm.client import get_llm
from proovy_agent.common.sse.context import current_emitter

_SYSTEM_PROMPT = """당신은 수학 문제 검증용 Python 코드를 작성하는 전문가입니다.
주어진 문제와 풀이 방향을 바탕으로 결과를 검증할 수 있는 Python 코드를 작성하세요.

규칙:
- 코드만 반환하세요. 설명이나 마크다운 코드블록(```) 없이 순수 Python 코드만 작성하세요.
- 계산 결과는 반드시 print()로 출력하세요.
- numpy, scipy, sympy 등 수학 라이브러리를 활용하세요.
- 코드는 바로 실행 가능한 완전한 형태여야 합니다."""


@tool
async def code_generate(problem: str, approach: str) -> str:
    """수학 문제 검증용 Python 코드를 생성합니다.
    생성된 코드는 code_execute 도구로 실행해 결과를 검증하세요.

    Args:
        problem: 풀어야 할 수학 문제
        approach: 풀이 방향 및 사용할 공식/방법
    """
    emitter = current_emitter.get()
    if emitter:
        await emitter.emit("tool_start", {"name": "code_generate", "label": "검증 코드 생성 중..."})

    try:
        llm = get_llm("flash")
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"문제: {problem}\n\n풀이 방향: {approach}"},
        ]
        response = await llm.ainvoke(messages)
        raw = response.content
        if isinstance(raw, list):
            code = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block) for block in raw
            ).strip()
        else:
            code = str(raw).strip()
    except Exception as exc:
        if emitter:
            await emitter.emit("error", {"name": "code_generate", "message": str(exc)})
        raise

    if emitter:
        await emitter.emit("tool_result", {"name": "code_generate", "output": code})

    return code

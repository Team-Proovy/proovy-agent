"""CoreSolver 에이전트 — 2-Phase 수학 풀이 (verify → explain)."""

from __future__ import annotations

import logging
import re
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from proovy_agent.common.llm.client import get_llm
from proovy_agent.common.sandbox.client import get_daytona_client
from proovy_agent.common.sandbox.executor_var import current_executor
from proovy_agent.common.sandbox.manager import SandboxManager
from proovy_agent.common.sse.context import current_emitter, current_tool_call_id
from proovy_agent.common.sse.events import ErrorPayload, SolveProgressPayload, TokenPayload
from proovy_agent.graph.state import CreditEntry, PlanStep, ProovyState
from proovy_agent.graph.tools.code_execute import code_execute
from proovy_agent.graph.tools.code_generate import code_generate

logger = logging.getLogger(__name__)

_TOOLS = [code_generate, code_execute]
_TOOLS_BY_NAME = {t.name: t for t in _TOOLS}

_MODEL_COST: dict[str, float] = {"flash": 1.0, "sonnet": 3.0, "opus": 8.0}
_MAX_ITERATIONS = 5
_TRIM_THRESHOLD = 500


def _build_verify_system(state: ProovyState) -> str:
    step_desc = "수학 문제 풀이"
    if state.plan and state.executing_step_idx < len(state.plan):
        step_desc = state.plan[state.executing_step_idx].description

    return (
        "당신은 Proovy의 수학 전문 AI입니다. 풀이 후 반드시 코드로 검증하세요.\n\n"
        f"이번 단계의 목표: {step_desc}\n"
        f"난이도: {state.difficulty}\n\n"
        "단계:\n"
        "1. 문제를 분석하고 풀이 방향을 결정합니다.\n"
        "2. code_generate 도구로 검증 코드를 생성합니다.\n"
        "3. code_execute 도구로 코드를 실행해 결과를 검증합니다.\n"
        "4. 검증이 완료되면 내부 검증 결과를 요약합니다.\n\n"
        f"검증 실패 시 다른 접근 방식으로 재시도하세요 (최대 {_MAX_ITERATIONS}회)."
    )


def _build_explain_system(state: ProovyState, verified_summary: str) -> str:
    return (
        "당신은 Proovy의 수학 전문 AI입니다.\n"
        "아래 검증된 풀이를 바탕으로 학생이 이해하기 쉽게 단계별로 설명하세요.\n\n"
        f"[검증된 풀이 요약]\n{verified_summary}\n\n"
        f"난이도: {state.difficulty}\n\n"
        "규칙:\n"
        "- 검증된 내용만 설명합니다. 추측하지 마세요.\n"
        "- 공식, 계산 과정, 결론을 명확히 제시합니다.\n"
        "- 자연스럽고 단계적으로 설명합니다."
    )


def _trim_tool_messages(messages: list) -> list:
    """LLM 전달 직전 긴 ToolMessage를 잘라냅니다. State 원본은 유지됩니다."""
    trimmed = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and len(str(msg.content)) > _TRIM_THRESHOLD:
            msg = msg.model_copy(
                update={"content": str(msg.content)[:_TRIM_THRESHOLD] + "... [TRIMMED]"}
            )
        trimmed.append(msg)
    return trimmed


def _content_to_str(content: object) -> str:
    """LLM 메시지 content를 downstream이 소비하기 쉬운 문자열로 정규화한다."""
    if content is None:
        return ""
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    return str(content)


def _code_execute_succeeded(result: str) -> bool:
    """code_execute 결과 문자열에서 성공 여부를 판단합니다."""
    if "error:" in result.lower():
        return False
    m = re.search(r"exit_code:\s*(-?\d+)", result)
    return not (m and int(m.group(1)) != 0)


def _build_verified_solution_message(
    content: object,
    explanation_mode: Literal["full", "brief"],
) -> AIMessage:
    """CoreSolver의 검증 산출물을 downstream이 찾을 수 있는 메시지로 남긴다."""
    display = "content" if explanation_mode == "brief" else "hidden"
    return AIMessage(
        content=_content_to_str(content),
        metadata={"kind": "verified_solution", "display": display},
    )


async def _phase1_verify(
    state: ProovyState,
    emitter: object | None,
) -> tuple[str, list, int, bool, int, int]:
    """Phase 1: 내부 풀이 + 코드 검증.

    Returns:
        (verified_summary, new_messages, execute_count, verified, llm_call_count, codegen_count)
        verified: 최소 1회 code_execute 성공 여부
    """
    llm = get_llm(state.selected_model)
    llm_with_tools = llm.bind_tools(_TOOLS)

    system_msg = SystemMessage(_build_verify_system(state))
    messages: list = list(state.messages)
    execute_count = 0
    codegen_count = 0
    llm_call_count = 0
    verified = False

    if emitter:
        await emitter.emit(
            SolveProgressPayload(text="수학 문제를 분석하고 코드로 검증하는 중입니다...")
        )

    for iteration in range(_MAX_ITERATIONS):
        trimmed = _trim_tool_messages(messages)
        response = await llm_with_tools.ainvoke([system_msg, *trimmed])
        llm_call_count += 1
        messages.append(response)

        if not response.tool_calls:
            # 도구 호출 없이 LLM이 응답 → 검증 없이 종료
            content = _content_to_str(response.content)
            return content, messages, execute_count, verified, llm_call_count, codegen_count

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool = _TOOLS_BY_NAME.get(tool_name)
            if tool is None:
                result = f"Unknown tool: {tool_name}"
            else:
                # tool 함수가 SSE 이벤트에 넣을 수 있도록 현재 tool_call_id를 노출한다.
                tool_id_token = current_tool_call_id.set(tool_call["id"])
                try:
                    result = await tool.ainvoke(tool_call["args"])
                    if tool_name == "code_generate":
                        codegen_count += 1
                    elif tool_name == "code_execute":
                        execute_count += 1
                        if _code_execute_succeeded(str(result)):
                            verified = True
                except Exception as exc:
                    result = f"Tool error: {exc}"
                finally:
                    current_tool_call_id.reset(tool_id_token)

            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))

        if emitter and iteration > 0:
            await emitter.emit(
                SolveProgressPayload(
                    text=f"검증 재시도 중... ({iteration + 1}/{_MAX_ITERATIONS})",
                    iteration=iteration + 1,
                )
            )

    # 최대 반복 도달 — 마지막 AI 메시지를 결과로 사용
    last_ai = next(
        (m for m in reversed(messages) if isinstance(m, AIMessage) and not m.tool_calls),
        None,
    )
    summary = _content_to_str(last_ai.content) if last_ai else "검증 결과를 확인하지 못했습니다."
    return summary, messages, execute_count, verified, llm_call_count, codegen_count


async def _phase2_explain(
    state: ProovyState,
    verified_summary: str,
    emitter: object | None,
) -> AIMessage:
    """Phase 2: 검증된 결과 기반 설명 스트리밍."""
    llm = get_llm(state.selected_model)
    system_msg = SystemMessage(_build_explain_system(state, verified_summary))

    user_messages = [m for m in state.messages if isinstance(m, HumanMessage)]

    content_chunks: list[str] = []
    async for chunk in llm.astream([system_msg, *user_messages]):
        chunk_content = _content_to_str(chunk.content)
        if chunk_content:
            if emitter:
                await emitter.emit(TokenPayload(delta=chunk_content))
            content_chunks.append(chunk_content)

    return AIMessage(
        content="".join(content_chunks),
        metadata={"display": "content"},
    )


async def core_solver(state: ProovyState) -> dict:
    """CoreSolver LangGraph 노드."""
    emitter = current_emitter.get()
    manager = SandboxManager(get_daytona_client())
    executor = await manager.create_executor(state.thread_id or "default")
    executor_token = current_executor.set(executor)

    new_messages: list = []
    credit_entries: list[CreditEntry] = []

    try:
        # Phase 1: verify
        (
            verified_summary,
            p1_messages,
            execute_count,
            verified,
            llm_call_count,
            codegen_count,
        ) = await _phase1_verify(state, emitter)

        # 최소 1회 code_execute 성공 필수 (Proof by Code 원칙)
        if not verified:
            err_msg = "코드 검증에 실패했습니다. 풀이를 확인할 수 없습니다."
            if emitter:
                await emitter.emit(ErrorPayload(code="tool_error", message=err_msg))
            _exc = RuntimeError(err_msg)
            _exc.sse_emitted = True  # type: ignore[attr-defined]
            raise _exc

        # Phase 1 검증 산출물은 video/pdf가 재사용하는 중립 verified_solution이다.
        last_ai = next(
            (m for m in reversed(p1_messages) if isinstance(m, AIMessage) and not m.tool_calls),
            None,
        )
        verified_content = last_ai.content if last_ai else verified_summary
        new_messages.append(
            _build_verified_solution_message(verified_content, state.explanation_mode)
        )

        # Phase 2: explain. 영상 중심 brief 모드는 중복 텍스트 스트리밍을 생략한다.
        if state.explanation_mode == "full":
            explain_msg = await _phase2_explain(state, verified_summary, emitter)
            new_messages.append(explain_msg)

        # 크레딧: Phase 1 LLM 반복 횟수
        model_cost = _MODEL_COST.get(state.selected_model, 1.0)
        credit_entries.append(
            CreditEntry(
                node="core_solver",
                action="llm_call_verify",
                model=state.selected_model,
                cost=model_cost * llm_call_count,
            )
        )
        if state.explanation_mode == "full":
            credit_entries.append(
                CreditEntry(
                    node="core_solver",
                    action="llm_call_explain",
                    model=state.selected_model,
                    cost=model_cost,
                )
            )
        # code_generate Flash 호출 (도구 내부 LLM)
        for _ in range(codegen_count):
            credit_entries.append(
                CreditEntry(node="core_solver", action="code_generate", model="flash", cost=1.0)
            )
        # code_execute Daytona 실행
        for _ in range(execute_count):
            credit_entries.append(CreditEntry(node="core_solver", action="code_execute", cost=1.0))

    except Exception as exc:
        logger.exception("CoreSolver 실행 중 오류 발생")
        if emitter and not getattr(exc, "sse_emitted", False):
            await emitter.emit(
                ErrorPayload(message="풀이 중 오류가 발생했습니다. 다시 시도해 주세요.")
            )
            exc.sse_emitted = True  # type: ignore[attr-defined]
        raise
    finally:
        current_executor.reset(executor_token)
        await manager.destroy_executor(executor)

    # plan 상태 업데이트
    plan = list(state.plan)
    if plan and state.executing_step_idx < len(plan):
        step = plan[state.executing_step_idx]
        plan[state.executing_step_idx] = PlanStep(
            action=step.action,
            description=step.description,
            status="done",
        )

    return {
        "messages": new_messages,
        "credit_log": credit_entries,
        "current_phase": "explain" if state.explanation_mode == "full" else "verify",
        "plan": plan,
    }

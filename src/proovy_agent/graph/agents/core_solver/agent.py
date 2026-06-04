"""CoreSolver 에이전트 — 2-Phase 수학 풀이 (verify → explain)."""

from __future__ import annotations

from contextvars import ContextVar
import logging
import re
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from proovy_agent.common.llm.client import get_llm
from proovy_agent.common.sandbox.client import get_daytona_client
from proovy_agent.common.sandbox.executor_var import current_executor
from proovy_agent.common.sandbox.manager import SandboxManager
from proovy_agent.common.sse.context import current_emitter, current_tool_call_id
from proovy_agent.common.sse.events import ErrorPayload, SolveProgressPayload, TokenPayload
from proovy_agent.graph.credit_pricing import CORE_SOLVER_MAX_ITERATIONS, MODEL_CREDIT_COST
from proovy_agent.graph.state import CreditEntry, PlanStep, ProovyState
from proovy_agent.graph.tools.code_execute import code_execute
from proovy_agent.graph.tools.code_generate import code_generate

logger = logging.getLogger(__name__)

_TOOLS = [code_generate, code_execute]

_MAX_ITERATIONS = CORE_SOLVER_MAX_ITERATIONS
_TRIM_THRESHOLD = 500
_phase1_execute_count: ContextVar[int] = ContextVar("phase1_execute_count", default=0)


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
        "4. 검증이 완료되면 도구를 더 호출하지 말고 최종 메시지로 끝냅니다.\n\n"
        "최종 메시지 규칙:\n"
        "- 반드시 단계, 핵심 수식, 최종 답을 모두 포함한 자연스러운 프로즈로 작성하세요.\n"
        "- 코드 실행 결과로 확인한 내용만 요약하고 추측하지 마세요.\n"
        "- 영상/PDF 등 하류 노드가 재사용할 수 있도록 문제 풀이만 깨끗하게 남기세요.\n\n"
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


class _ToolEvidenceTrimMiddleware(AgentMiddleware):
    """모델 호출 요청에서만 ToolMessage를 trim하고 agent state 원본은 보존합니다."""

    async def awrap_model_call(
        self,
        request: Any,
        handler: Any,
    ) -> Any:
        return await handler(request.override(messages=_trim_tool_messages(request.messages)))


class _ToolCallIdMiddleware(AgentMiddleware):
    """Tool 실행 중 SSE payload가 LangGraph tool_call_id를 참조할 수 있게 합니다."""

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Any,
    ) -> Any:
        token = current_tool_call_id.set(str(request.tool_call.get("id", "")))
        try:
            if request.tool_call.get("name") == "code_execute":
                count = _phase1_execute_count.get() + 1
                _phase1_execute_count.set(count)
                emitter = current_emitter.get()
                if emitter and count > 1:
                    await emitter.emit(
                        SolveProgressPayload(
                            text=f"검증 재시도 중... ({count}/{_MAX_ITERATIONS})",
                            iteration=count,
                        )
                    )
            return await handler(request)
        finally:
            current_tool_call_id.reset(token)


def _code_execute_succeeded(result: str) -> bool:
    """code_execute 결과 문자열에서 성공 여부를 판단합니다."""
    if "error:" in result.lower():
        return False
    m = re.search(r"exit_code:\s*(-?\d+)", result)
    return not (m and int(m.group(1)) != 0)


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    return str(content)


def _is_iteration_limit_message(message: AIMessage) -> bool:
    content = _message_text(message)
    return content.startswith("Model call limits exceeded")


def _with_metadata(message: Any, metadata: dict[str, str]) -> Any:
    current = dict(getattr(message, "metadata", {}) or {})
    return message.model_copy(update={"metadata": {**current, **metadata}})


def _message_signature(message: Any) -> tuple[Any, ...]:
    if isinstance(message, AIMessage):
        tool_calls = tuple(
            (call.get("id"), call.get("name"), repr(call.get("args", {})))
            for call in message.tool_calls
        )
        return (AIMessage, _message_text(message), tool_calls)
    if isinstance(message, ToolMessage):
        return (ToolMessage, _message_text(message), message.tool_call_id, message.name)
    return (type(message), _message_text(message))


def _extract_generated_messages(input_messages: list, output_messages: list) -> list:
    """Agent 출력에서 입력 히스토리를 제외하고 새 AI/Tool 메시지만 반환합니다."""
    input_ids = {msg.id for msg in input_messages if getattr(msg, "id", None)}
    input_signatures = [_message_signature(msg) for msg in input_messages]
    consumed_signatures: set[int] = set()
    generated: list = []

    for msg in output_messages:
        msg_id = getattr(msg, "id", None)
        if msg_id and msg_id in input_ids:
            continue

        signature = _message_signature(msg)
        matched_idx = next(
            (
                idx
                for idx, input_signature in enumerate(input_signatures)
                if idx not in consumed_signatures and input_signature == signature
            ),
            None,
        )
        if matched_idx is not None:
            consumed_signatures.add(matched_idx)
            continue

        if isinstance(msg, AIMessage | ToolMessage):
            generated.append(msg)

    return generated


def _collect_phase1_stats(messages: list) -> tuple[int, bool, int, int]:
    """Agent가 생성한 메시지에서 실행 횟수와 검증 성공 여부를 계산합니다."""
    tool_call_names: dict[str, str] = {}
    execute_count = 0
    codegen_count = 0
    llm_call_count = 0
    last_execute_verified = False

    for msg in messages:
        if isinstance(msg, AIMessage):
            if not _is_iteration_limit_message(msg):
                llm_call_count += 1
            for tool_call in msg.tool_calls:
                tool_call_names[str(tool_call["id"])] = str(tool_call["name"])
        elif isinstance(msg, ToolMessage):
            tool_name = msg.name or tool_call_names.get(str(msg.tool_call_id), "")
            if tool_name == "code_generate":
                codegen_count += 1
            elif tool_name == "code_execute":
                execute_count += 1
                last_execute_verified = getattr(
                    msg, "status", "success"
                ) != "error" and _code_execute_succeeded(str(msg.content))

    return execute_count, last_execute_verified, llm_call_count, codegen_count


def _current_result_summary(messages: list) -> str:
    return (
        "최대 검증 반복에 도달했습니다. "
        "마지막 코드 실행은 성공했으며, 원본 code/stdout evidence는 함께 보존되어 있습니다. "
        "현재 확인된 실행 결과를 기준으로 풀이를 종료합니다."
    )


def _needs_limit_summary(messages: list, verified: bool) -> bool:
    if not verified:
        return False
    return not any(
        isinstance(msg, AIMessage) and not msg.tool_calls and not _is_iteration_limit_message(msg)
        for msg in messages
    )


async def _build_limit_summary_message(state: ProovyState, messages: list) -> AIMessage:
    """반복 제한 종료 시 보존된 evidence만 근거로 verified_solution 프로즈를 만듭니다."""
    llm = get_llm(state.selected_model)
    system_msg = SystemMessage(
        "당신은 Proovy의 수학 검증 결과 요약기입니다.\n"
        "새 풀이를 만들거나 재계산하지 말고, 아래 대화와 code/stdout evidence에 이미 있는 "
        "내용만 근거로 요약하세요.\n"
        "반드시 단계, 핵심 수식, 최종 답을 포함한 자연스러운 프로즈로 작성하세요.\n"
        "반복 제한 때문에 정보가 부족하면, 확인된 범위와 한계를 짧게 밝히세요.\n"
        "도구 출력 원문을 그대로 복사하지 마세요."
    )
    response = await llm.ainvoke([system_msg, *state.messages, *_trim_tool_messages(messages)])
    content = _message_text(response).strip() or _current_result_summary(messages)
    return AIMessage(content=content, metadata=getattr(response, "metadata", {}) or {})


def _tag_phase1_messages(messages: list, state: ProovyState, verified: bool) -> tuple[list, str]:
    """Phase 1 산출 메시지를 evidence로 보존하고 verified_solution을 태깅합니다."""
    tagged = [
        _with_metadata(msg, {"display": "hidden"})
        if isinstance(msg, AIMessage | ToolMessage)
        else msg
        for msg in messages
    ]

    last_ai_idx = next(
        (
            idx
            for idx in range(len(tagged) - 1, -1, -1)
            if isinstance(tagged[idx], AIMessage)
            and not tagged[idx].tool_calls
            and not _is_iteration_limit_message(tagged[idx])
        ),
        None,
    )

    if not verified:
        summary_msg = tagged[last_ai_idx] if last_ai_idx is not None else None
        return tagged, _message_text(
            summary_msg
        ) if summary_msg else "검증 결과를 확인하지 못했습니다."

    display = "content" if state.explanation_mode == "brief" else "hidden"
    if last_ai_idx is None:
        summary = _current_result_summary(tagged)
        tagged.append(
            AIMessage(
                content=summary,
                metadata={"kind": "verified_solution", "display": display},
            )
        )
        return tagged, summary

    summary = _message_text(tagged[last_ai_idx])
    tagged[last_ai_idx] = _with_metadata(
        tagged[last_ai_idx],
        {"kind": "verified_solution", "display": display},
    ).model_copy(update={"content": summary})
    return tagged, summary


def _build_phase1_agent(state: ProovyState) -> Any:
    """Phase 1 검증 agent를 LangChain create_agent 계약으로 생성합니다."""
    return create_agent(
        model=get_llm(state.selected_model),
        tools=_TOOLS,
        system_prompt=_build_verify_system(state),
        middleware=[
            _ToolEvidenceTrimMiddleware(),
            _ToolCallIdMiddleware(),
            ModelCallLimitMiddleware(run_limit=_MAX_ITERATIONS, exit_behavior="end"),
        ],
        name="core_solver_phase1",
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
    messages: list = list(state.messages)

    if emitter:
        await emitter.emit(
            SolveProgressPayload(text="수학 문제를 분석하고 코드로 검증하는 중입니다...")
        )

    agent = _build_phase1_agent(state)
    execute_count_token = _phase1_execute_count.set(0)
    try:
        result = await agent.ainvoke({"messages": messages})
    finally:
        _phase1_execute_count.reset(execute_count_token)
    all_messages = list(result["messages"])
    generated_messages = _extract_generated_messages(state.messages, all_messages)

    execute_count, verified, llm_call_count, codegen_count = _collect_phase1_stats(
        generated_messages
    )
    if _needs_limit_summary(generated_messages, verified):
        generated_messages.append(await _build_limit_summary_message(state, generated_messages))
        llm_call_count += 1

    tagged_messages, verified_summary = _tag_phase1_messages(generated_messages, state, verified)
    return (
        verified_summary,
        tagged_messages,
        execute_count,
        verified,
        llm_call_count,
        codegen_count,
    )


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
        chunk_content = _message_text(chunk)
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

        # Phase 1 evidence는 trim 없이 state.messages에 원본 그대로 보존한다.
        new_messages.extend(p1_messages)

        if state.explanation_mode == "full":
            # Phase 2: explain
            explain_msg = await _phase2_explain(state, verified_summary, emitter)
            new_messages.append(explain_msg)

        # 크레딧: Phase 1 LLM 반복 횟수
        model_cost = float(MODEL_CREDIT_COST.get(state.selected_model, MODEL_CREDIT_COST["flash"]))
        credit_entries.append(
            CreditEntry(
                node="core_solver",
                action="llm_call_verify",
                model=state.selected_model,
                cost=model_cost * llm_call_count,
            )
        )
        if state.explanation_mode == "full":
            # Phase 2 LLM 호출
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

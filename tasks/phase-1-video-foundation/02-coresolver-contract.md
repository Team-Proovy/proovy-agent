---
id: "1.02"
phase: 1
title: "CoreSolver Phase 1 생산 계약 (create_agent + evidence + verified_solution 태깅)"
spec: "specs/phase-1/01-video-phase-a-skeleton.md"
issue: "74"
depends_on: ["1.01"]
blocks: ["1.05", "1.10"]
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 1.02 — CoreSolver Phase 1 생산 계약

> Spec: [`specs/phase-1/01-video-phase-a-skeleton.md`](../../specs/phase-1/01-video-phase-a-skeleton.md)
>
> Issue: [#74](https://github.com/Team-Proovy/proovy-agent/issues/74)

## 의존성

- 1.01 (state.py 필드 정리) — `explanation_mode` 등 state 필드가 있어야 brief 분기·display 모드 처리 가능

## 사전 준비

- [ ] `code_generate` / `code_execute` 도구 존재 확인
- [ ] `before_model` trim 미들웨어 위치 확인 (ADR 0006 — LLM 전달 시점만 trim, state 원본 유지)

## 구현 체크리스트

- [ ] `core_solver/agent.py` Phase 1을 `create_agent(tools=[code_generate, code_execute], max_iter=5, before_model=trim)`로 구현
- [ ] code/stdout을 `state.messages`에 **풀텍스트 persist** (ADR 0006 evidence)
- [ ] verify 시스템 프롬프트가 마지막 메시지를 "단계+수식+답" 프로즈로 유도 + `kind="verified_solution"` 태깅
- [ ] display 모드: full=hidden / brief=content (1.03과 연동)
- [ ] (회귀 가드) 한 solve 후 messages에 `code_execute.args.code` + stdout ToolMessage + `kind="verified_solution"` AIMessage **셋 다** 존재 테스트

## Definition of Done

- [ ] 회귀 가드 테스트 통과 (ADR 0006 evidence 3종 존재)
- [ ] 자동화된 테스트 통과
- [ ] max_iter 초과 시 현재 결과 반환 (무한 루프 없음)

## 리스크 / 메모

- 마지막 메시지가 프로즈가 아니라 도구 호출로 끝나는 경우 — 프롬프트로 강제, 가드가 잡음
- 순수 파서 `solver_adapter` / 재-solve fallback 도입 금지 (ADR 0001 Update)
- `create_agent` = LangGraph 2.0 `langchain.agents.create_agent`(deprecated `create_react_agent` 대체, implementation_plan §3.1) — 기존 수동 루프 `_phase1_verify`를 이걸로 **리팩터**(파라미터만 조정 아님)

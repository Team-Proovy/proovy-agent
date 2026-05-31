---
status: superseded by 0006
---

# 0005 — 최종답 충실성 anchor: 실행된 ground truth에 박는다

> **Superseded by [ADR 0006](./0006-evidence-based-video-input.md) (2026-05).** 본 ADR은 답 형식이 단일 수식/숫자일 때(`x=3`)만 적용 가능한 좁은 anchor였다. "k>5 조건", "귀무가설 기각", "f(x)는 [0,5]에서 증가" 같이 *조건·논리적 결론·성질 주장* 형태의 답에서는 sympy 동치 검사 자체가 적용 불가능 — 수학 문제 답의 다수 형태를 못 받친다. 0006은 anchor(하드 동치 게이트)를 폐기하고 *코드 실행 증거(code+stdout)를 LLM에 그대로 제공*해 정보량으로 환각을 줄이는 방식으로 대체한다.

## Context

검증된 계산값이 화면에 뜨기까지 LLM이 4번 변환한다: CoreSolver 프로즈 요약(`verified_solution`) → hint_extractor 구조화(`SolutionPlan`) → scriptify(narration) → codegen(Manim 코드). consistency validator는 **narration ↔ 화면 *일치*** 만 보지, 화면값이 **실제 계산값과 맞는지(correctness)** 는 아무도 검증하지 않는다. 한 hop에서 값이 흐르면(예: 3→5) narration·화면이 같이 흘러 consistency는 통과하고 **답이 틀린 채 자신만만하게 렌더**된다 — 수학 해설 영상에서 가장 치명적인 실패. [ADR 0001](./0001-video-input-contract.md)은 이 드리프트를 인정만 하고(soft anchor) hard 체크가 없다.

## Decision

**최종답(+소수의 핵심값)을 실행된 ground truth에 hard-anchor한다.**

- **CoreSolver의 검증 코드가 답을 파싱 가능한 형태로 출력**한다(예: stdout `ANSWER: x=3` 또는 JSON). `code_generate` 프롬프트가 이 출력을 강제하고, CoreSolver가 stdout을 **결정적으로 파싱**(LLM 아님)해 `verified_values`(최소 `final_answer`)로 만든다 — 이게 진짜 anchor(프로즈 요약 hop을 우회).
- `verified_values`는 `verified_solution`(프로즈)와 함께 히스토리의 검증 산출물에 포함된다.
- **충실성 게이트**: `SolutionPlan.final_answer` ↔ `verified_values.final_answer` 기호 동치(sympy — 이미 의존성, [§8.3](../architecture/video-generation-design.md)) + 최종답 표시 segment(`highlight_result`)의 렌더 수식이 anchor를 포함하는지 확인. 불일치 → `script_repair` / 실패.
- 범위는 **최종답(+소수 핵심 중간값)** 만. 답 형태가 없는 문제(증명 등)는 anchor 생략(게이트 skip).
- **성공 기준 추가**: "최종답 충실성 = 100%"(렌더된 최종답이 실행 검증값과 일치).

## Considered Options

- **(B) 현행 soft anchor**: `verified_solution` anchor + `narration-화면 일치 ≥95%`만. 단순하나 "자신만만하게 틀린 답" 여지 — 수학 영상엔 부적합. 기각.
- **(C) full golden-values**: 모든 단계값을 ground truth와 대조. 가장 엄밀하나 구조화·체크를 전 계층에 깔아야 해 무겁고 과설계. 기각.
- **(A) 최종답 hard anchor (채택)**: 치명적 실패 지점(최종답)만 실행 ground truth에 박음. 추가 LLM 0(코드 출력 형식 + 결정적 파싱 + 기호 동치). 좁고 싸고 효과적.

## Consequences

- CoreSolver 출력 계약 확장: verify 코드가 답을 파싱 가능 형태로 print + 결정적 파서. (`code_generate`/verify 프롬프트가 강제)
- consistency validator(narration↔화면 *일치*)와 **별개의 correctness 게이트**가 생긴다 — 둘은 다른 것을 본다(혼동 금지).
- 핵심 중간값까지 anchor를 넓힐지는 후속(실패 데이터 보고 결정). 잘못된 problem 해소(멀티턴 "1번"을 3번으로 짚음)는 값-anchor가 못 잡는 **별개 리스크** — consistency가 1차로 거른다.

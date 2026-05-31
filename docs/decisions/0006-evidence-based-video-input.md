---
status: accepted
---

# 0006 — 코드 실행 증거 기반 영상 입력 검증 (verified_values anchor 폐기)

## Context

[ADR 0005](./0005-final-answer-faithfulness-anchor.md)는 CoreSolver의 검증 코드가 `ANSWER: x=3` 같은 *결정적 파싱 가능 형식*으로 답을 print하면 결정적 파서가 `verified_values.final_answer`를 추출하고, `SolutionPlan.final_answer`와 sympy 동치 검사로 hard-anchor한다고 결정했다. 이는 답이 **단일 수식·숫자**일 때만 잘 동작한다 — 다음 형태에서는 적용 자체가 어렵거나 불가능:

| 답 형태 | sympy 동치 검사 가능성 |
|---|---|
| `x = 3` | ✅ |
| `(x, y) = (1, 2), (3, 4)` (다중 교점) | ⚠️ 복잡 |
| `k > 5일 때 해 존재` (조건) | ❌ 적용 어색 |
| `귀무가설 기각 (p=0.012 < 0.05)` (논리 결론) | ❌ |
| `f(x)는 [0, 5]에서 증가` (성질) | ❌ |

수능·내신 수학 문제는 ②~⑤ 형태가 절반 이상이라 ADR 0005의 anchor가 닿는 영역이 *좁다*. 한편 hint_extractor는 `verified_solution` 프로즈만 보고 SolutionPlan으로 옮기므로, *옮기는 LLM hop에서 미세 왜곡*(반올림 `6.67 → 6.7`, 부호 누락 `-1.753 → 1.753`)이 일어날 여지가 있고 ADR 0005의 anchor는 *최종답만* 검사하므로 중간 단계 환각은 잡지 못한다.

근본 원인: anchor 방식은 "검사할 형식이 일정해야" 성립한다. 수학 답의 다양성이 이 전제를 깬다.

## Decision

**anchor(하드 동치 게이트)를 폐기하고, 코드 실행 *증거*를 LLM에 그대로 제공해 정보량으로 환각을 줄인다.**

- **CoreSolver는 LangGraph `create_agent` 표준 패턴**대로 동작한다 — `code_execute` 도구 호출의 입력(`code`)은 `AIMessage.tool_calls`에, 출력(`stdout`)은 `ToolMessage.content`에 자동 적재된다. 별도 `verified_values` 필드·결정적 파서·"ANSWER: ..." 형식 강제 모두 **삭제**.
- **저장은 풀텍스트** — DB checkpoint(`state.messages`)에 `code`와 풀 `stdout`이 영구. trim은 *LLM 전달 시점*에만, *노드별 미들웨어 정책*으로.
- **CoreSolver 도구 루프**는 도구 반복 중 context 폭주 방지를 위해 `before_model: trim_messages_middleware`(ToolMessage 500자 cap)를 유지한다.
- **hint_extractor의 LLM 호출**은 `create_agent`가 아닌 단일 `with_structured_output` 호출이라 **미들웨어를 부착·미부착 조합으로 evidence 노출 범위를 제어**한다. Step 1은 추가 분리(ADR 0001 Update 3)되어 두 stage가 다른 입력 모양을 받는다:
  - **Stage 1a**(대상 식별, Flash): `state.messages` 풀텍스트지만 `before_model: trim_tool_messages_strict`(ToolMessage.content ≤100자)로 *code/stdout은 거의 제거된 메타뷰*. evidence를 안 봐도 되는 라우팅 task. thread 길이와 비용이 약하게 비례(verified_solution prose만 누적).
  - **Stage 1b**(SolutionPlan 추출, Sonnet): video_node가 `target_turn_idx`로 잘라낸 **슬라이스** — target turn의 HumanMessage + AIMessage(verified_solution + tool_calls.args.code) + ToolMessage(stdout) + 현재 요청 HumanMessage. 미들웨어 미부착(슬라이스 작음). **이 stage가 evidence를 풀텍스트로 본다** — *target turn의 code+stdout*만으로 환각률을 낮춤. thread 길이와 비용 무관.
  - 환각이 일어나려면 *target turn의* 프로즈와 stdout 두 곳에 동시에 같은 왜곡이 필요 — 단일 turn에서의 동시 왜곡은 LLM 추론 한 hop 안의 일관된 사실 처리라 빈도가 매우 낮다.
- 충실성 검사는 강제 게이트가 아니라 **Phase D frame 회귀**(§9.4)가 *영상 최종 산출물*에서 측정한다. MVP에서 별도 substring 매칭·동치 검사 가드는 두지 않는다.
- 범위는 영상 입력 빌드 hop(verified_solution → SolutionPlan)에 한정. scriptify/codegen hop의 검증은 별개 메커니즘(consistency validator, AST allowlist, smoke render — §8).

## Considered Options

- **(A) ADR 0005 유지 (final_answer hard anchor)**: 단일 수식 답에서만 잘 됨. 조건/주장형 답 적용 불가 + format 강제(`ANSWER: ...`)가 CoreSolver 프롬프트 결합도를 높임. 기각.
- **(B) 답 형태별 적용 분기 (단순 답 → 동치 검사, 조건/주장 → 다른 방식)**: 분기 자체가 복잡성. 답 분류 LLM이 또 필요. 기각.
- **(C) 모든 단계값을 검증 (full golden-values)**: 가장 엄밀하나 전 계층 구조화 + 단계별 검사가 무거움. 기각.
- **(D) Evidence-based (채택)**: anchor 폐기, code+stdout을 LLM에 제공. 정보량 증가로 환각률 감소를 노림. 강제력은 약하나 답 형태에 무관하게 작동. 인프라 단순화(파서·sympy 검사 모듈 제거).

## Consequences

**감소하는 인프라**:
- `verified_values` Pydantic 필드와 결정적 파서
- CoreSolver의 "ANSWER: ..." 출력 형식 강제 프롬프트
- sympy 동치 검사 모듈 (영상 입력 hop 한정 — scriptify의 expression DSL 검증 등은 별개)
- 충실성 게이트(repair/실패 분기)

**추가되는 것**:
- 없음 — LangGraph 표준 동작 활용. 미들웨어 부착 *생략*만으로 hint_extractor가 풀 evidence를 보게 됨.

**Trade-off**:
- (-) Anchor의 *강제력*은 잃는다. 환각이 일어나도 *늦게* 잡힘(Phase D frame 회귀).
- (-) hint_extractor Step 1 입력 토큰 +750~3000 (code/stdout 한 set, 호출당 +$0.003~0.01 수준).
- (+) 답 형태 자유 (조건/주장/성질 OK).
- (+) 인프라 감소 — 파서·동치 검사·게이트 모두 폐기.
- (+) 멀티턴 다중 문제에서도 LLM이 *대상 verified_solution과 그 코드를 함께* 봐서 짚기 정확도 향상.

**ADR 0005와의 관계**:
- 0005의 *문제 의식*(narration↔화면 일치만 보면 자신만만하게 틀린 답 risk)은 유효. 0006은 그 risk를 *anchor 게이트*가 아니라 *증거 제공으로 환각률 자체를 낮추는* 방식으로 해결.
- 0005의 §0.5 MVP 성공 기준 "최종답 충실성 = 100%" 항목은 0006에 맞춰 "Phase D frame 회귀의 *측정 항목*"으로 갱신.

**후속 작업**:
- `video-generation-design.md` §0 #27, §0.5, §2.2.1, §10.4 정정
- `CONTEXT.md`의 `verified_values` 정의 삭제, *code execution evidence* 추가
- CoreSolver 구현에서 결정적 파서·verified_values 분기 제거
- hint_extractor 구현: **1b만** trim 미들웨어 *미부착*(풀텍스트 evidence), **1a는 `trim_tool_messages_strict`**(라우팅용 메타뷰) — 1a/1b 분리는 [ADR 0001 Update 3](./0001-video-input-contract.md)
- (관련) hint_extractor 2-step 분리는 [ADR 0001 Update](./0001-video-input-contract.md) 참조.

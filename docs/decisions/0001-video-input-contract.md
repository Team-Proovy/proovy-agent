---
status: accepted
---

# 0001 — 영상 입력 계약: verified_solution 경유, 구조화는 video가

## Context

VideoNode는 영상을 만들 "풀이"를 입력으로 받아야 한다. 원 설계(video-generation-design.md §2.2.1)는 CoreSolver의 explain 메시지를 순수 파서로 `\n\n`·LaTeX 단위로 잘라 SolutionPlan을 역추출하고, 실패 시 워커가 LLM으로 풀이를 재생성하는 fallback을 두었다. 코드 확인 결과 explain(`_phase2_explain`)은 구조 보장이 없는 **스트리밍된 단일 프로즈**라 파서가 거의 항상 깨지고, 재-solve는 비용 2배 + 영상이 글 설명과 다른 풀이를 보여줄 위험(§2.2.1이 피하려던 바로 그것)을 부른다.

## Decision

- **CoreSolver**는 solve를 돌 때마다 Phase 1 검증 결과를 단계+수식+최종답이 담긴 프로즈 요약 **`verified_solution`** 으로 만들어 **대화 내역(`messages`)에 깨끗한 산출물로 남긴다**(hidden/tagged — 단일 state 필드 아님, 멀티턴 다중 문제 대응). SolutionPlan 같은 영상 전용 구조는 만들지 않는다.
- **video**는 hint_extractor 1회로 **전체 대화 내역 + 현재 요청**을 읽어 대상 문제와 그 `verified_solution`을 짚고(예: "아까 1번"), 이를 **`SolutionPlan` + `VideoHints`** 로 구조화한다. (단일 필드를 읽는 게 아니라 히스토리에서 대상 해소)
- **plan 게이트**: video는 *이번 plan에 pending solve가 있을 때만* 대기한다. 이전 턴 풀이를 참조하는 `[video]`-단독 plan은 즉시 진행(히스토리에서 대상 해소) — "in-plan solve done" 기준이 아니다.
- 원 설계의 순수 파서 `solver_adapter`와 "<2 step 재-solve" fallback은 **삭제**한다.
- 텍스트 풀이가 결과물이 아닐 때(영상 요청)는 `explanation_mode=brief` — Phase 2 전체 설명을 생략하고 verified_solution을 완성 메시지로 노출한다.

## Considered Options

- **CoreSolver가 SolutionPlan 직접 생산** (+flash 1회): faithfulness 최고지만 CoreSolver가 video 개념을 알아야 해 레이어가 거꾸로 되고 비용 증가. 영상-풀이 정확성 제약이 극강일 때만 가치 있어 기각.
- **explain 프로즈를 순수 파서로 역추출** (원 설계): 단일 프로즈에 깨지고 재-solve를 유발 — 기각.

## Consequences

- CoreSolver↔video 경계가 깔끔해진다 (pdf도 같은 verified_solution 재사용 가능).
- 시스템 전체 추가 LLM 호출 0 (구조화는 hint_extractor에 흡수).
- Trade-off: 구조화가 검증 시점이 아니라 video 시점에 일어나 LLM 재해석에 의한 미세 왜곡 여지 — verified_solution을 anchor로 써서 완화. 문제되면 CoreSolver 구조화(+1 호출)로 전환 가능.
- 후속 작업: **checkpointer 배선**(멀티턴 — messages 턴 간 누적), CoreSolver가 solve마다 `verified_solution`을 히스토리에 적재, `explanation_mode` state 필드 + planner 분류, plan 게이트를 "pending in-plan solve" 기준으로, hint_extractor가 full history에서 대상 해소, SSE `node_result`·`video_status`/`video_progress` 배선.

## Update (멀티턴 — 2026-05)

원안은 `verified_solution`을 **단일 state 필드**로 두고 video가 그것(+latest message의 문제)을 읽는다고 했다. 이는 암묵적으로 **"한 스레드 = 한 문제"** 를 가정한다 — 멀티턴에서 깨진다: 1번을 풀고 3번을 푼 뒤 "아까 **1번** 영상으로"라고 하면 단일 필드는 3번으로 덮어써져 있어 잘못된 영상을 만든다.

표준 멀티턴 방식으로 정정: **대화 내역(`messages`) 전체가 컨텍스트**이고(길면 compact/요약), solve마다 깨끗한 `verified_solution`이 히스토리에 남으며, video의 hint_extractor가 **전체 히스토리 + 요청**에서 대상 문제·풀이를 짚는다. plan 게이트도 "in-plan solve done" → "pending in-plan solve가 있으면 대기"로 바꿔 `[video]`-단독 후속 턴이 동작하게 한다. ADR 0001의 핵심(깨끗한 산출물 anchor, explain prose 재파싱 금지, 구조화는 video 시점)은 그대로 유지된다.

## Update (hint_extractor 2-step 분리 + evidence — 2026-05)

원안은 hint_extractor를 **1회의 `with_structured_output` 호출**로 두고 `SolutionPlan` + `VideoHints`를 한 번에 만들었다. 두 작업이 *다른 종류의 추론*임이 드러나 분리한다:

- **Step 1 — SolutionPlan + 대상 해소** (모델: `$VIDEO_HINT_PLAN_MODEL`, 보수적 — 정확성 우선)
  - 입력: `state.messages` 전체 (대화 내역 + verified_solution 프로즈 + code+stdout이 ToolMessage로 영구)
  - 출력: `{ problem_text, solution_plan, target_confidence }`
  - 역할: verified_solution을 잃지 않고 `steps[]`로 옮기기. 멀티턴 대상 해소("아까 1번")를 흡수.
  - `target_confidence`는 출력만 하고 가드 게이트로 쓰지 않음 — 로그 메트릭 용도.

- **Step 2 — VideoHints** (모델: `$VIDEO_HINT_VIDEOHINTS_MODEL`, 약간 고온 — 설계 우선)
  - 입력: `problem_text + solution_plan` (messages 다시 안 봄 — 가벼움)
  - 출력: `VideoHints { visualization_hints, suggested_segments, emphasis_targets, director_policy }`
  - 역할: 어디 강조·몇 컷·어떤 시각화 (교수법/시각 디자인 추론).

**Step 1이 evidence를 보는 방식**은 [ADR 0006](./0006-evidence-based-video-input.md)으로 분리: `create_agent`가 아닌 단일 LLM 호출이라 `before_model` 미들웨어를 부착하지 않으면 *자동으로 풀텍스트 stdout/code를 LLM이 본다*. 별도 metadata 필드 없음.

**Trade-off**:
- (+) 관심사 분리: 정확성 추론(Step 1) vs 설계 추론(Step 2)이 다른 모델·온도로 튜닝 가능.
- (+) 실패 격리: VideoHints가 실패해도 SolutionPlan은 살아 영상 fallback 가능.
- (+) Step 2가 작은 입력만 받아 저비용 모델(flash) 사용 가능 — 비용 ↓ 또는 동일.
- (-) Latency +1 round-trip (~1~2초).

ADR 0001의 핵심(verified_solution anchor, explain prose 재파싱 금지, 구조화는 video 시점)은 그대로 유지.

## Update (Step 1 내부 분리: 라우팅 1a + 추출 1b — 2026-05)

위 Update가 정의한 **Step 1**은 messages 전체를 Sonnet에 풀텍스트로 넘기는 단일 호출이었다. 멀티턴에서 *thread 길이에 비례해 비용·지연이 폭증*한다: 10턴 thread = ~45K tok × Sonnet ≈ $0.135/call, 30턴 ≈ $0.3+. evidence-based 환각률 감소(ADR 0006)는 *대상 turn의 evidence 1세트*만 있으면 달성되므로, 전 history를 Sonnet으로 통과시킬 필요가 없다.

Step 1을 두 stage로 분리해 *라우팅*과 *추출*을 다른 모델·다른 입력 모양으로 처리한다:

- **Stage 1a — 대상 식별** (모델: `$VIDEO_HINT_TARGET_MODEL`, Flash 권장)
  - 입력: `state.messages` 풀텍스트 — 단 ToolMessage.content는 `before_model: trim_tool_messages_strict`로 ≤100자 강제 trim(code/stdout 거의 제거 → 메타 뷰). verified_solution AIMessage 본문과 HumanMessage는 풀텍스트 유지.
  - 출력: `TargetSelection { target_turn_idx: int | None, problem_text: str, target_confidence: float, reasoning: str }`. `target_turn_idx == None`은 "현재 HumanMessage에 새 문제, 이전 풀이 참조 아님" 의미.
  - 역할: "아까 1번 영상으로" → 어느 turn의 verified_solution을 가리키는가. *라우팅 추론*.
  - 비용: thread 길이에 약하게 비례(verified_solution prose만 누적, evidence는 trim). 30턴도 Flash 기준 $0.005 미만.

- **Stage 1b — SolutionPlan 추출** (모델: `$VIDEO_HINT_PLAN_MODEL`, Sonnet 권장)
  - 입력: video_node가 `target_turn_idx`로 잘라낸 **슬라이스** — `[target turn의 HumanMessage(problem), target turn의 AIMessage(verified_solution + tool_calls.args.code), target turn의 ToolMessage(stdout), 현재 HumanMessage(영상 요청)]`. 미들웨어 미부착(슬라이스가 작아 풀텍스트 봐도 ~3500 tok).
  - 출력: `SolutionPlan` (problem_text는 Stage 1a 결과를 그대로 전달, Step 1b는 plan만 책임).
  - 역할: 대상 evidence 옆에서 verified_solution을 `steps[]`로 옮기기. *추출 추론*. ADR 0006의 evidence-based 환각률 감소가 여기서 작동(target turn의 code+stdout 풀텍스트로 봄).
  - 비용: thread 길이와 무관(한 turn 슬라이스만) → ~3500 tok × Sonnet ≈ $0.011/call.

`target_turn_idx == None`이면 Stage 1b 슬라이스는 현재 HumanMessage만(아직 풀이 없음 → 입력 계약 오류, 잡 실패 — Planner가 이런 plan을 만들지 않는다는 전제는 [§1.4](../architecture/video-generation-design.md#14-proovystate-변경)에 명시).

**Trade-off**:
- (+) **비용 천장**: thread 길이와 무관 — 30턴 thread도 Stage 1b는 target turn 1개만. 10턴 영상 요청 시 $0.135 → $0.012 (10x↓).
- (+) **모델 최적화**: 라우팅은 Flash로 충분(분류 task), 추출은 Sonnet로 정확성 확보.
- (+) 실패 격리: Stage 1a 라우팅이 틀려도 Stage 1b는 잘못된 슬라이스로 SolutionPlan을 만든 뒤 오류가 명시적으로 드러남(target_confidence 로그). 단일 호출에선 안 보이는 신호.
- (-) Latency +1 round-trip (Flash는 빠름 → ~0.5~1초 추가).
- (-) Stage 1a가 대상을 잘못 짚으면 영상이 다른 문제로 나옴. 가드는 `target_confidence` 로그 + Phase D nightly. 잦은 오작동이 측정되면 refinement loop(Stage 1b가 confidence 낮으면 Stage 1a 재호출 with feedback) 도입.

ADR 0006 evidence-based 동기는 그대로 유지 — *target turn의 code+stdout*을 풀텍스트로 Stage 1b가 봄. ADR 0006이 "Step 1이 전체 messages를 본다"고 표현한 부분은 이 Update로 "Stage 1a가 메타뷰, Stage 1b가 target slice 풀텍스트"로 정정된다.

CONTEXT.md의 **hint_extractor 2-step**은 표면 구조 그대로(Step 1 + Step 2 = 정확성 + 설계의 2 카테고리). Step 1 내부가 1a + 1b로 분리됐을 뿐이며 외부 인터페이스는 변하지 않는다.

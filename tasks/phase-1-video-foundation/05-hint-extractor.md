---
id: "1.05"
phase: 1
title: "hint_extractor 2-step (1a 라우팅 / 1b 추출 / 2 VideoHints)"
spec: "specs/phase-1/01-video-phase-a-skeleton.md"
issue: "77"
depends_on: ["1.02", "1.04"]
blocks: ["1.10"]
estimate: "M"
status: "done"
completed_at: "2026-06-01"
owner: ""
sprint: ""
---

# Task 1.05 — hint_extractor 2-step

> Spec: [`specs/phase-1/01-video-phase-a-skeleton.md`](../../specs/phase-1/01-video-phase-a-skeleton.md)
>
> Issue: [#77](https://github.com/Team-Proovy/proovy-agent/issues/77)

## 의존성

- 1.02 (CoreSolver 생산 계약) — messages의 `verified_solution` + code/stdout evidence를 소비
- 1.04 (features/video 모델) — `SolutionPlan` / `VideoHints` 출력 스키마

## 사전 준비

- [x] env: `VIDEO_HINT_TARGET_MODEL`(Flash) / `VIDEO_HINT_PLAN_MODEL`(Sonnet) / `VIDEO_HINT_VIDEOHINTS_MODEL`(Flash)
- [x] `trim_tool_messages_strict`(ToolMessage ≤100자) 미들웨어 확인

## 구현 체크리스트

- [x] Stage 1a `select_target_turn(messages)` → `TargetSelection` (Flash, 메타뷰 trim — 라우팅만)
- [x] Stage 1b `extract_solution_plan(target_slice)` → `SolutionPlan` (Sonnet, **미들웨어 미부착** 풀 evidence — ADR 0006)
- [x] Step 2 `extract_video_hints(problem_text, solution_plan)` → `VideoHints` (Flash, messages 다시 안 봄)
- [x] 단위 테스트: 1a 대상 식별 정확도 + 1b 환각 회귀(stdout 숫자가 `final_answer`에 보존)

## Definition of Done

- [x] 멀티턴 "아까 N번" 대상 해소 테스트 통과
- [x] 1b 환각 회귀 테스트 통과 (evidence-based 충실성)
- [x] 자동화된 테스트 통과

## 리스크 / 메모

- `target_confidence`는 로그 메트릭일 뿐 가드 게이트 아님 (오타겟은 anchor echo로 사용자 점검)
- 비용이 thread 길이에 비례하지 않게 — 1a만 약하게 비례, 1b는 슬라이스 1 set

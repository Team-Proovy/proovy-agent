---
id: "1.03"
phase: 1
title: "Planner explanation_mode 분류 (full/brief)"
spec: "specs/phase-1/01-video-phase-a-skeleton.md"
issue: "75"
depends_on: ["1.01"]
blocks: ["1.10"]
estimate: "S"
status: "done"
completed_at: "2026-05-31"
owner: ""
sprint: ""
---

# Task 1.03 — Planner explanation_mode 분류

> Spec: [`specs/phase-1/01-video-phase-a-skeleton.md`](../../specs/phase-1/01-video-phase-a-skeleton.md)
>
> Issue: [#75](https://github.com/Team-Proovy/proovy-agent/issues/75)

## 의존성

- 1.01 (state.py 필드 정리) — `explanation_mode` 필드에 분류 결과를 채움

## 사전 준비

- [x] Planner 의도 분석 출력 스키마 확인

## 구현 체크리스트

- [x] Planner가 의도에서 `full`/`brief` 분류 (영상만 결과물 = brief, 텍스트 풀이가 결과물 = full)
- [x] brief일 때 CoreSolver Phase 2 설명 생략 배선 (1.02 display=content와 연동)
- [x] 분류 단위 테스트 (영상 단독 → brief, 풀이 결과물 → full)

## Definition of Done

- [x] brief 모드에서 Phase 2 토큰 스트리밍이 발생하지 않고 verified_solution이 `display="content"`로 노출
- [x] 자동화된 테스트 통과

## 리스크 / 메모

- 모호한 의도(풀이+영상 동시)는 `full` 기본값으로 안전 처리
- ADR 0001 / `explanation_mode`는 Planner가 정하고 CoreSolver가 소비 (CONTEXT.md)

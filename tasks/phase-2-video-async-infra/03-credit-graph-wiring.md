---
id: "2.03"
phase: 2
title: "크레딧 그래프 배선 (Planner hold + CreditSettler + solve/pdf)"
spec: "specs/phase-2/01-video-phase-b-async-infra.md"
issue: "85"
depends_on: ["2.02"]
blocks: []
estimate: "M"
status: "done"
completed_at: 2026-06-01
owner: ""
sprint: ""
---

# Task 2.03 — 크레딧 그래프 배선

> Spec: [`specs/phase-2/01-video-phase-b-async-infra.md`](../../specs/phase-2/01-video-phase-b-async-infra.md)
>
> Issue: [#85](https://github.com/Team-Proovy/proovy-agent/issues/85)

## 의존성

- 2.02 (크레딧 스키마 + 원자적 연산) — hold/capture/refund 함수를 그래프 노드에 배선

## 사전 준비

- [x] 비용 테이블(implementation_plan §9) 확인 (Flash 1 / Sonnet 3 / Opus 8 / code 1 / image 2 / video 10 / general 0.5)

## 구현 체크리스트

- [x] Planner가 plan 전체 예상치 `hold` (부족 시 요청 통째 거절 = all-or-nothing)
- [x] CreditSettler가 그래프 끝 동기작업(solve/pdf)분 `capture` finalize
- [x] solve/pdf도 같은 balance에서 차감하도록 배선 (시스템 전반 단일 원장)
- [x] 사용자 재시도 preflight (`retry_source_job_id` 검증 → hold 전, 실패 시 hold 안 만듦)

## Definition of Done

- [x] plan hold → solve/pdf capture → 초과예상 환불 흐름 통합 테스트
- [x] 가용 부족 시 요청 거절 ("N cr 필요")
- [x] 자동화된 테스트 통과

## 리스크 / 메모

- 영상 capture는 여기 아님 — video_node가 2.06에서 enqueue 직전 동기 capture. CreditSettler는 동기작업(변동비용)만 합산
- 작은 초과는 마이너스 허용 (cap/최악값 예약 없음 — 단순화)

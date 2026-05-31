---
id: "2.02"
phase: 2
title: "크레딧 스키마 + 원자적 hold/capture/refund + TTL-on-read"
spec: "specs/phase-2/01-video-phase-b-async-infra.md"
issue: "84"
depends_on: ["1.01"]
blocks: ["2.03", "2.06"]
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 2.02 — 크레딧 스키마 + 원자적 연산

> Spec: [`specs/phase-2/01-video-phase-b-async-infra.md`](../../specs/phase-2/01-video-phase-b-async-infra.md)
>
> Issue: [#84](https://github.com/Team-Proovy/proovy-agent/issues/84)

## 의존성

- 1.01 (state.py 필드 정리) — `hold_id`로 plan 단일 hold row를 참조 **[cross-phase]**

## 사전 준비

- [ ] env `CREDIT_HOLD_TTL_SECONDS=1200`(20분) 확인
- [ ] ADR 0004 단일 원장 모델 재확인

## 구현 체크리스트

- [ ] `credits` + `credit_holds` 테이블 (id/amount/status/expires_at/plan_id) + alembic
- [ ] 가용잔액 쿼리 — `status='pending' AND expires_at > NOW()` 필터 (TTL-on-read)
- [ ] 원자적 `hold` (SELECT FOR UPDATE, all-or-nothing) / `capture` (단일 row amount 부분차감) / `refund` (idempotent + `status != 'succeeded'` 가드)
- [ ] 동시 요청 합산 + orphan hold 자동 회복 테스트

## Definition of Done

- [ ] hold/capture/refund 원자성 테스트 통과
- [ ] TTL-on-read orphan hold 자동 회복 테스트 (sweep cron 없음)
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- **단일 hold row의 amount 부분차감** (split row 아님 — ADR 0004 `hold −= 10`). `video_hold_id`/`sync_hold_id` 분리 금지
- refund의 `status != 'succeeded'` 가드가 무료 영상 race를 막는 핵심

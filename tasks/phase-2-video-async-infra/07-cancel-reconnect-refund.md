---
id: "2.07"
phase: 2
title: "취소 + 재접속 복구 + permanent/transient 환불 분류 + lazy detection"
spec: "specs/phase-2/01-video-phase-b-async-infra.md"
issue: "89"
depends_on: ["2.05", "2.06"]
blocks: ["2.09"]
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 2.07 — 취소 / 재접속 / 환불 분류

> Spec: [`specs/phase-2/01-video-phase-b-async-infra.md`](../../specs/phase-2/01-video-phase-b-async-infra.md)
>
> Issue: [#89](https://github.com/Team-Proovy/proovy-agent/issues/89)

## 의존성

- 2.05 (sandbox) — running 취소가 render sub-process를 종료
- 2.06 (Mode B + capture) — 환불은 capture된 잡의 terminal에서만

## 사전 준비

- [ ] 설계 §3.4.1 lazy detection / §3.4.2 permanent vs transient / §3.5.1 취소·환불 재확인

## 구현 체크리스트

- [ ] 취소: queued = API terminal+refund / running = `cancel_requested=true` → 워커 감지 → sub-process 종료 + terminal+refund (**잡은 주체가 환불**)
- [ ] permanent vs transient 실패 분류 (permanent = 환불 + ack 200 / transient = 환불 X + lease release + 503 retry)
- [ ] 재접속 복구 (`api/v1/threads.py` `video_jobs[-1]` 상태 응답)
- [ ] lazy detection (running heartbeat stale / queued `getTask` NOT_FOUND → 사용자 활동 endpoint에서 정리)

## Definition of Done

- [ ] 취소·실패 분류·재접속 시나리오 테스트 (무료 영상 race 차단)
- [ ] refund idempotency 테스트
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- 미분류 예외는 보수적 permanent 처리 (transient 후 retry 성공 시 무료 영상 방지)
- status 폴링(hot)은 단일행 체크, thread 조회(저빈도)는 광역 sweep — 쓰기 증폭 회피
- 최종 보고에 Cloud Tasks retry/cancel 권한, lazy detection의 GCP 조회 권한, 환불 운영 절차 등 사용자 조치 필요 항목이 있으면 2.09 Real GCP integration E2E에 누적한다.

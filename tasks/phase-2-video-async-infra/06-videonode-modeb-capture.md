---
id: "2.06"
phase: 2
title: "VideoNode Mode B 전환 + 영상 10cr 동기 capture"
spec: "specs/phase-2/01-video-phase-b-async-infra.md"
issue: "88"
depends_on: ["2.01", "2.02", "1.10"]
blocks: ["2.07", "2.09"]
estimate: "M"
status: "done"
owner: ""
sprint: ""
---

# Task 2.06 — VideoNode Mode B + 영상 capture

> Spec: [`specs/phase-2/01-video-phase-b-async-infra.md`](../../specs/phase-2/01-video-phase-b-async-infra.md)
>
> Issue: [#88](https://github.com/Team-Proovy/proovy-agent/issues/88)

## 의존성

- 2.01 (잡 모델·Cloud Tasks 클라이언트) — enqueue
- 2.02 (크레딧 원자 연산) — 영상 10cr 동기 capture
- 1.10 (inline 스캐폴드) — 이 노드를 **제거하고** Mode B로 교체 **[cross-phase, throwaway 경계]**

## 사전 준비

- [x] ADR 0002/0004 낙관적 차감 + best-effort/lazy reconciliation 재확인

## 구현 체크리스트

- [x] `graph/nodes/video.py`: Phase A inline runner **제거** → 잡 enqueue + 즉시 반환 (Mode B)
- [x] 영상 10cr **동기 capture** (createTask 직전, `balance −10` · `hold.amount −10`) — DB INSERT + capture **single transaction**
- [x] deterministic `cloud_tasks_name`(`video-{job_id}`) + best-effort `createTask` + lazy reconciliation(getTask 보상)
- [x] anchor 메시지 1건 (`display=tool`, `job_id`, `click_action=open_video_viewer`) — 영상 박스 UX

## Definition of Done

- [x] enqueue 후 즉시 반환 (§0.5 API thread 점유 0)
- [x] capture가 createTask보다 happen-before 보장 테스트
- [x] 자동화된 테스트 통과

## 리스크 / 메모

- createTask 실패 보상: `NOT_FOUND` + `queued` + `lease_holder=NULL`일 때만 failed+환불. 확인 불가는 lazy detection(2.07)에서 재확인
- 워커는 messages 무관여 — anchor + DB(휘발성 상태)가 진실의 원천 ("messages 단일 소스" 문서화된 예외)
- 최종 보고에 Cloud Tasks enqueue, capture transaction, worker URL/env 등 사용자 조치 필요 항목이 있으면 2.09 Real GCP integration E2E에 누적한다.
- 완료 메모(2.06): 실제 운영에서는 `DATABASE_URL`, `VIDEO_CLOUD_TASKS_QUEUE_PATH`,
  `VIDEO_WORKER_URL`, `VIDEO_WORKER_AUTH_TOKEN`이 모두 설정되어야 API startup이
  통과한다. 실제 queue/worker/GCP 인증 E2E는 2.09에서 검증한다.

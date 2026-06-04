---
id: "2.04"
phase: 2
title: "워커 서비스 (http_handler + runner + progress + cancel poll)"
spec: "specs/phase-2/01-video-phase-b-async-infra.md"
issue: "86"
depends_on: ["2.01", "1.07", "1.08"]
blocks: ["2.05", "3.06"]
estimate: "M"
status: "review"
completed_at: 2026-06-04
owner: ""
sprint: ""
---

# Task 2.04 — 워커 서비스

> Spec: [`specs/phase-2/01-video-phase-b-async-infra.md`](../../specs/phase-2/01-video-phase-b-async-infra.md)
>
> Issue: [#86](https://github.com/Team-Proovy/proovy-agent/issues/86)

## 의존성

- 2.01 (잡 모델·progress API) — 워커가 progress write / status 갱신
- 1.07 (scriptify) · 1.08 (템플릿) — 워커가 실행하는 파이프라인 stage 본체 **[cross-phase]**

## 사전 준비

- [ ] Cloud Run gen2(microVM) 서비스 + instance concurrency=1 확인
- [x] 설계 §3.4 타임아웃 사다리 / §3.6 stage 분해 재확인

## 구현 체크리스트

- [x] `features/video/worker/` http_handler (`/jobs/run`, gen2) + runner
- [x] 잡 시작 시 progress-staleness 체크 (succeeded skip / progress stale면 전체 재실행)
- [x] 10초 cancel poll + stage 경계 `cancel_requested` 확인
- [x] stage/segment마다 progress write + lease heartbeat(60초, asyncio 병렬)

## Definition of Done

- [x] 잡 1건이 워커에서 stage 순회 + progress 갱신 (sandbox 실행은 2.05)
- [x] lease 만료/탈취 + self-fence 테스트
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- heartbeat(lease 생존 신호)와 progress write(SSE 진행률)는 **독립** — 혼동 금지 (CONTEXT.md)
- 1 instance = 1 job (concurrency=1). 재시도 = 전체 재실행 (캐시/checkpoint 없음)

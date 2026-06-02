---
id: "1.06"
phase: 1
title: "파이프라인 스켈레톤 (VisualTypeRegistry + StageContext + stage 함수 5)"
spec: "specs/phase-1/01-video-phase-a-skeleton.md"
issue: "78"
depends_on: ["1.04"]
blocks: ["1.07", "1.08", "3.02", "3.03", "3.07", "3.08"]
estimate: "M"
status: "done"
completed_at: "2026-05-31"
owner: ""
sprint: ""
---

# Task 1.06 — 파이프라인 스켈레톤

> Spec: [`specs/phase-1/01-video-phase-a-skeleton.md`](../../specs/phase-1/01-video-phase-a-skeleton.md)
>
> Issue: [#78](https://github.com/Team-Proovy/proovy-agent/issues/78)

## 의존성

- 1.04 (features/video 모델) — SolutionPlan/VideoOptions를 입력으로 받는 stage 시그니처

## 사전 준비

- [x] 설계 §3.6 워커 내부 구조(stage 명시 분해) / §5.1 VisualTypeRegistry 재확인

## 구현 체크리스트

- [x] `VisualTypeRegistry` 통합 구조 — visual_type별 core 5필드(`schema`/`prompt_snippet`/`render_fn`/`fallback_candidates`/`narration_alignment_rule`)
- [x] `StageContext` + orchestrator — `stage_solve/scriptify/tts/render/compose` 함수 분해 (checkpoint 없음)
- [x] `stage_solve`: 주입된 SolutionPlan **검증만** (재-solve 없음)
- [x] thin `stage_tts/render/compose` (실제 로직은 1.07/1.08/1.09)
- [x] ffprobe 1초 fallback **제거**

## Definition of Done

- [x] 빈 registry + StageContext로 orchestrator dry-run 통과 (stage 경계 테스트 seam 확인)
- [x] 자동화된 테스트 통과

## 리스크 / 메모

- PoC `generate_video()` 재현이 아니라 신규 — Send/checkpoint 모델과 안 엮이게 (메인 그래프 밖 async pipeline)
- cross-invocation 캐시/재개는 MVP 제외 (잡 실패 시 전체 재실행)

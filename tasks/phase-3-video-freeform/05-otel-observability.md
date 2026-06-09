---
id: "3.05"
phase: 3
title: "관측성 (OpenTelemetry span + 메트릭)"
spec: "specs/phase-3/01-video-phase-c-hardening.md"
issue: "95"
depends_on: ["2.05", "2.09"]
blocks: []
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 3.05 — 관측성 (OTel)

> Spec: [`specs/phase-3/01-video-phase-c-hardening.md`](../../specs/phase-3/01-video-phase-c-hardening.md)
>
> Issue: [#95](https://github.com/Team-Proovy/proovy-agent/issues/95)

## 의존성

- 2.05 (sandbox/워커) — stage 단위로 span을 계측 **[cross-phase]**
- 2.09 (Real GCP integration E2E) — 실제 Cloud Run/GCS 실행 경로가 확인된 뒤 운영 계측 추가 **[cross-phase]**

## 사전 준비

- [ ] OTel exporter / collector 엔드포인트 확인

## 구현 체크리스트

- [ ] OpenTelemetry span (stage 단위)
- [ ] 메트릭: `render_fallback_rate` · `llm_codegen_failure_rate` · `visual_type_distribution`

## Definition of Done

- [ ] stage별 span + 메트릭 export 확인
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- 메트릭 카디널리티 — `visual_type` 라벨 범위 제한
- 이 메트릭들이 Phase D 품질 회귀의 입력 신호

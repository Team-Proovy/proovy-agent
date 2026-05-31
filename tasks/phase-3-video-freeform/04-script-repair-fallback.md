---
id: "3.04"
phase: 3
title: "script_repair intent-preserving fallback"
spec: "specs/phase-3/01-video-phase-c-hardening.md"
issue: "94"
depends_on: ["3.03"]
blocks: []
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 3.04 — script_repair intent-preserving fallback

> Spec: [`specs/phase-3/01-video-phase-c-hardening.md`](../../specs/phase-3/01-video-phase-c-hardening.md)
>
> Issue: [#94](https://github.com/Team-Proovy/proovy-agent/issues/94)

## 의존성

- 3.03 (visual_scene) — visual_scene 실패 경로를 감싸는 fallback

## 사전 준비

- [ ] 설계 §5.4 intent-preserving fallback 재확인

## 구현 체크리스트

- [ ] `features/video/fallback/script_repair.py`: visual_scene 3회 실패 시 script_repair LLM이 narration에 맞는 visual_type/params로 재작성
- [ ] 재작성 → consistency 검증 → 실패면 `equation_write`/`highlight_result` + SKIPPED
- [ ] `fallback_reason` 기록 (`internal.json` — 집계 쿼리는 Phase D)

## Definition of Done

- [ ] visual_scene 실패가 잡 전체 실패 없이 복구 또는 SKIPPED로 안전 처리 (§0.5 자유형 복구율 ≥80%의 토대)
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- 규칙기반 IntentRouter 대신 LLM — 더 유연하나 비결정적, consistency가 가드
- 복구율 본격 측정은 Phase D nightly (`fallback_reason` 집계)

---
id: "3.07"
phase: 3
title: "word-timestamp 시각 강조 동기 (timeline.py)"
spec: "specs/phase-3/01-video-phase-c-hardening.md"
issue: "97"
depends_on: ["1.09", "1.06"]
blocks: []
estimate: "M"
status: "done"
completed_at: 2026-06-01
owner: ""
sprint: ""
---

# Task 3.07 — word-timestamp 시각 강조 동기

> Spec: [`specs/phase-3/01-video-phase-c-hardening.md`](../../specs/phase-3/01-video-phase-c-hardening.md)
>
> Issue: [#97](https://github.com/Team-Proovy/proovy-agent/issues/97)

## 의존성

- 1.09 (TTS word-timestamp 매핑) — `word_timestamps`를 소비 **[cross-phase]**
- 1.06 (파이프라인 스켈레톤) — render stage에서 타임라인 적용 **[cross-phase]**

## 사전 준비

- [x] 설계 §4.2.2 시각 강조와 단어 동기 재확인

## 구현 체크리스트

- [x] `common/video/timeline.py`: word-timestamp 기반 `Indicate(t)` 시각 강조 동기
- [x] `emphasis_targets`(VideoHints) → 발화 시점 정렬
- [x] 자막 정밀 동기 (낮은 위험)

## Definition of Done

- [x] 시각 강조가 해당 단어 발화 시점에 정렬 (프레임 타이밍 검증)
- [x] 자동화된 테스트 통과

## 리스크 / 메모

- timestamp 정밀도가 Inworld WORD 단위에 의존 (§4 핵심 가치)

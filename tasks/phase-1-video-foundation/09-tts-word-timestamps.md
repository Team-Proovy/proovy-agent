---
id: "1.09"
phase: 1
title: "Inworld TTS word-timestamp 매핑"
spec: "specs/phase-1/01-video-phase-a-skeleton.md"
issue: "81"
depends_on: []
blocks: ["1.10", "3.07", "3.08"]
estimate: "S"
status: "todo"
owner: ""
sprint: ""
---

# Task 1.09 — Inworld TTS word-timestamp 매핑

> Spec: [`specs/phase-1/01-video-phase-a-skeleton.md`](../../specs/phase-1/01-video-phase-a-skeleton.md)
>
> Issue: [#81](https://github.com/Team-Proovy/proovy-agent/issues/81)

## 의존성

- 없음 (독립 task — `common/tts/` 모듈, 다른 영상 작업과 병렬 가능)

## 사전 준비

- [ ] Inworld API 키 (secret manager) + `inworld-tts-1.5-max` 한국어 보이스 확인
- [ ] 실제 응답 dump 확보 (테스트 fixture)

## 구현 체크리스트

- [ ] `common/tts/inworld.py`: `timestampType=WORD` 응답 → `TTSResult.word_timestamps` 매핑
- [ ] 실제 응답 dump 기반 단위 테스트

## Definition of Done

- [ ] `word_timestamps`가 (단어, start, end)로 매핑
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- Inworld 응답 포맷 변경 — dump fixture로 고정
- 시각 강조 동기(`Indicate(t)`)와 자막 정밀도 향상의 입력 (소비처: 3.07)

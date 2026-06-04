---
id: "3.08"
phase: 3
title: "TTS-first 양방향 적응 (미세 동작·압축 화이트리스트·narration band)"
spec: "specs/phase-3/01-video-phase-c-hardening.md"
issue: "98"
depends_on: ["1.09", "1.06"]
blocks: []
estimate: "S"
status: "done"
completed_at: 2026-06-03
owner: ""
sprint: ""
---

# Task 3.08 — TTS-first 양방향 적응

> Spec: [`specs/phase-3/01-video-phase-c-hardening.md`](../../specs/phase-3/01-video-phase-c-hardening.md)
>
> Issue: [#98](https://github.com/Team-Proovy/proovy-agent/issues/98)

## 의존성

- 1.09 (TTS 매핑) — TTS 길이/타임스탬프 기반 적응 **[cross-phase]**
- 1.06 (파이프라인 스켈레톤) — scriptify/stage 연동 **[cross-phase]**

## 사전 준비

- [x] PoC §5.3~5.5 TTS-first 양방향 적응 재확인

## 구현 체크리스트

- [x] TTS-first 양방향 적응 (미세 동작, 압축 화이트리스트, narration 길이 band)
- [x] band 밖일 때 처리 (speakingRate 재합성은 Phase D 보류)

## Definition of Done

- [x] narration 길이 band 내 수렴 + 압축 화이트리스트 적용
- [x] 자동화된 테스트 통과

## 리스크 / 메모

- 재합성 비용 2배 — MVP는 band 조정만, speakingRate 재합성은 Phase D

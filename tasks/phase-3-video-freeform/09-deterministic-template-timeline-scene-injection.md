---
id: "3.09"
phase: 3
title: "deterministic template timeline→scene 주입 계약"
spec: "specs/phase-3/01-video-phase-c-hardening.md"
issue: "123"
depends_on: ["1.08", "3.07", "2.09"]
blocks: []
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 3.09 — deterministic template timeline→scene 주입 계약

> Spec: [`specs/phase-3/01-video-phase-c-hardening.md`](../../specs/phase-3/01-video-phase-c-hardening.md)
>
> Issue: [#123](https://github.com/Team-Proovy/proovy-agent/issues/123)

## 의존성

- 1.08 (deterministic 템플릿) — template `manim_source` 생성 경로
- 3.07 (word-timestamp 시각 강조 동기) — `stage_render`의 `diagnostics["timeline"]`
- 2.09 (Real GCP integration E2E) — 실제 renderer/worker 소비 경로 확정 후 timeline 주입 계약 검증 **[cross-phase]**

## 사전 준비

- [ ] PR #122의 deterministic template source와 timeline diagnostics 계약 재확인
- [ ] 실제 renderer/worker가 template `manim_source`를 소비하는 경로 확정

## 구현 체크리스트

- [ ] `stage_render`가 만든 `diagnostics["timeline"]` events를 deterministic template scene
      builder 또는 renderer/worker 주입 단계가 소비
- [ ] `manim_source`에 `self.wait(...)` / `Indicate(...)` 등 timeline 기반 호출 생성,
      또는 동등한 scene 조립 계약 구현
- [ ] renderer/worker가 template `manim_source`와 timeline diagnostics를 함께 처리하는
      계약 명시
- [ ] 단위/통합 테스트: timeline event가 source 또는 renderer 호출로 반영되는지 검증
- [ ] smoke render: 강조 대상이 있는 segment에서 timeline event가 누락되지 않는지 확인

## Definition of Done

- [ ] renderer/worker가 deterministic template `manim_source`를 소비하면서
      `diagnostics["timeline"]` 기반 강조 동기를 반영한다
- [ ] `self.wait(...)` / `Indicate(...)` 주입 또는 동등한 scene 조립 결과가 테스트로
      검증된다
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- PR #122는 deterministic template source 생성과 timeline diagnostics 생성을 분리해 둔다
- 관련 코드 심볼: `stage_render`, `diagnostics["timeline"]`, `manim_source`,
  `self.wait(...)`, `Indicate(...)`

---
id: "3.03"
phase: 3
title: "visual_scene visual_type (LLM-codegen + AST 통합 + smoke render)"
spec: "specs/phase-3/01-video-phase-c-hardening.md"
issue: "93"
depends_on: ["3.01", "1.06"]
blocks: ["3.04"]
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 3.03 — visual_scene visual_type

> Spec: [`specs/phase-3/01-video-phase-c-hardening.md`](../../specs/phase-3/01-video-phase-c-hardening.md)
>
> Issue: [#93](https://github.com/Team-Proovy/proovy-agent/issues/93)

## 의존성

- 3.01 (AST allowlist) — visual_scene LLM 코드를 검증
- 1.06 (파이프라인 스켈레톤) — VisualTypeRegistry 등록 **[cross-phase]**

## 사전 준비

- [ ] 설계 §8 보안 spine(#13~15) / retry taxonomy 재확인

## 구현 체크리스트

- [ ] `visual_scene` visual_type (LLM-codegen) Registry 등록
- [ ] codegen → AST 검증 → smoke render → retry taxonomy (3회)
- [ ] consistency 검증 (narration ↔ 화면 일치)

## Definition of Done

- [ ] visual_scene 정상 케이스 렌더 + AST 통과 코드만 실행
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- LLM codegen 실패율이 핵심 risk — fallback은 3.04(script_repair)가 담당
- consistency는 일치만 봄(정확성 아님) — 정확성은 hint_extractor의 code+stdout evidence

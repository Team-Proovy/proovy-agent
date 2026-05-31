---
id: "1.08"
phase: 1
title: "deterministic 템플릿 5종 (intro/equation_write/derivation/highlight/outro)"
spec: "specs/phase-1/01-video-phase-a-skeleton.md"
issue: "80"
depends_on: ["1.06"]
blocks: ["1.10", "2.04"]
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 1.08 — deterministic 템플릿 5종

> Spec: [`specs/phase-1/01-video-phase-a-skeleton.md`](../../specs/phase-1/01-video-phase-a-skeleton.md)
>
> Issue: [#80](https://github.com/Team-Proovy/proovy-agent/issues/80)

## 의존성

- 1.06 (파이프라인 스켈레톤) — VisualTypeRegistry에 template render_fn 등록

## 사전 준비

- [ ] dev 환경 manim / TeX Live / CJK 폰트 설치

## 구현 체크리스트

- [ ] `intro_problem` / `equation_write` / `equation_derivation` / `highlight_result` / `outro_summary` render_fn
- [ ] 각 템플릿 `VisualTypeRegistry` 등록 (core 5필드)
- [ ] CJK MathTex 안전 렌더 확인
- [ ] 템플릿별 smoke render 테스트

## Definition of Done

- [ ] 5종 모두 manim 렌더로 프레임 산출
- [ ] 자동화된 테스트(smoke render) 통과

## 리스크 / 메모

- `visual_scene`(LLM-codegen) / `graph_plot`(expression DSL)은 **Phase C** — 여기선 deterministic만
- CJK 폰트/MathTex fit 깨짐(tofu)은 frame 회귀(Phase D)로 본격 측정

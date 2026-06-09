---
id: "3.02"
phase: 3
title: "graph_plot expression DSL (func_python lambda 제거 + sympy 파서)"
spec: "specs/phase-3/01-video-phase-c-hardening.md"
issue: "92"
depends_on: ["1.06", "2.05", "2.09"]
blocks: []
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 3.02 — graph_plot expression DSL

> Spec: [`specs/phase-3/01-video-phase-c-hardening.md`](../../specs/phase-3/01-video-phase-c-hardening.md)
>
> Issue: [#92](https://github.com/Team-Proovy/proovy-agent/issues/92)

## 의존성

- 1.06 (파이프라인 스켈레톤) — `graph_plot` visual_type을 VisualTypeRegistry에 등록 **[cross-phase]**
- 2.05 (sandbox) — graph_plot도 manim 렌더를 sandbox sub-process에서 실행 **[cross-phase]**
- 2.09 (Real GCP integration E2E) — 실제 worker/GCS 결과 표시 경로 검증 후 graph_plot 확장 **[cross-phase]**

## 사전 준비

- [ ] 설계 §8.3 expression DSL 설계 재확인

## 구현 체크리스트

- [ ] `func_python` lambda 문자열 삽입 **제거**
- [ ] sympy 기반 expression DSL (`{expr, domain, features[]}`) 파서
- [ ] `graph_plot` render_fn을 DSL 기반으로 + Registry 등록
- [ ] 기존 `graph_plot` 호출부 마이그레이션

## Definition of Done

- [ ] lambda 없이 DSL만으로 함수 그래프 렌더 + 기존 호출부 동작
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- DSL 표현력 < lambda — 필요 feature(점근선·교점·정의역 등) 커버 확인
- `graph_plot`은 flagship "기각역" 예시의 핵심 — 이 task가 그래프를 화면에 띄움

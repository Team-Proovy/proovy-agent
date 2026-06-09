---
id: "2.08"
phase: 2
title: "워커 이미지 Dockerfile(비루트+폰트) + CI + runtime health check"
spec: "specs/phase-2/01-video-phase-b-async-infra.md"
issue: "90"
depends_on: ["2.05"]
blocks: ["2.09"]
estimate: "S"
status: "todo"
owner: ""
sprint: ""
---

# Task 2.08 — 워커 이미지 + health check

> Spec: [`specs/phase-2/01-video-phase-b-async-infra.md`](../../specs/phase-2/01-video-phase-b-async-infra.md)
>
> Issue: [#90](https://github.com/Team-Proovy/proovy-agent/issues/90)

## 의존성

- 2.05 (sandbox) — sandbox 포함 워커 런타임을 이미지로 패키징

## 사전 준비

- [ ] PoC §9.2 Dockerfile 참조 (TeX/ffmpeg/폰트) — **PoC = 외부 repo `manim-video-gen`** (이 repo 아님)

## 구현 체크리스트

- [ ] 워커 Dockerfile (비루트 + **Python deps[manim 포함]** + TeX Live + CJK 폰트 + ffmpeg) + CI 빌드/푸시
- [ ] Runtime health check (build-time + startup probe — manim/TeX/폰트 존재 확인)

## Definition of Done

- [ ] 이미지 빌드 + startup probe 통과 (폰트/TeX 검증)
- [ ] CI 빌드/푸시 통과

## 리스크 / 메모

- CJK 폰트 누락 시 tofu(글자 깨짐) — health check가 build/startup에서 잡음
- read-only rootfs 노브 없음 → 비루트 + 크기제한 볼륨 + 일회성으로 대체 (ADR 0003)
- 최종 보고에 Artifact Registry, image push, Cloud Run startup probe, font/TeX runtime 설치 등 사용자 조치 필요 항목이 있으면 2.09 Real GCP integration E2E에 누적한다.

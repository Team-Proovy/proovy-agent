---
id: "2.05"
phase: 2
title: "platform-features sandbox (manim render sub-process 격리)"
spec: "specs/phase-2/01-video-phase-b-async-infra.md"
issue: "87"
depends_on: ["2.04"]
blocks: ["2.07", "2.08", "2.09", "3.01", "3.02", "3.05"]
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 2.05 — platform-features sandbox

> Spec: [`specs/phase-2/01-video-phase-b-async-infra.md`](../../specs/phase-2/01-video-phase-b-async-infra.md)
>
> Issue: [#87](https://github.com/Team-Proovy/proovy-agent/issues/87)

## 의존성

- 2.04 (워커 서비스) — sandbox가 워커의 render 호출을 감쌈

## 사전 준비

- [ ] ADR 0003 platform-features(nsjail 제외) / §8.4 sub-process sandbox 재확인

## 구현 체크리스트

- [ ] `features/video/worker/sandbox/`: `manim render` CLI를 **비루트 + 크기제한 in-memory 볼륨 + rlimit/timeout** sub-process로 실행
- [ ] 시크릿 env 미전달
- [ ] platform-features 격리 Cloud Run 검증 (read-only rootfs 노브 없음 → 볼륨+일회성으로 대체)
- [ ] sandbox smoke 테스트: 워크스페이스 외 write · fork 폭탄 · 메모리/시간 초과 차단
- [ ] `features/video/worker/sandbox/tex_sanitizer.py`: MathTex/TeX 입력의 파일·shell 접근
      위험 명령 allowlist audit. 최소 차단 대상은 `\input`, `\include`, `\openin`,
      `\openout`, `\read`, `\write`, `\write18`, shell-escape variants,
      `\includegraphics` 파일 read, `\usepackage{shellesc}` 및 shell/file access를
      활성화하는 패키지
- [ ] TeX 위험 명령이 워크스페이스 밖 파일·시크릿을 읽지 못하는지 sandbox audit에
      포함하고, 실패 시 renderer가 `diagnostics["template"]["latex_validation_errors"]`를
      기록

## Definition of Done

- [ ] 허용 외 FS write / 자원 한도 초과가 모두 차단되어 잡 실패로 처리 (§0.5 sandbox 위반 100% 차단)
- [ ] TeX 위험 명령 audit이 통과하고 실패 원인이 `diagnostics["template"]["latex_validation_errors"]`에 남는다
- [ ] `latex_validation_errors`는 array이며 각 entry는 최소
      `{message: string, line?: number, column?: number, error_code?: string,
      severity?: "error"|"warning", original_snippet?: string}` 형태를 따른다.
      오류가 없을 때도 top-level `diagnostics["template"]` 객체는 존재한다
- [ ] 자동화된 테스트(sandbox audit) 통과

## 리스크 / 메모

- 워커는 LLM 생성 코드를 직접 import/eval하지 않는다 — 항상 sub-process `manim render` 경유
- network-off(egress 차단 별도 서비스)는 후속 — AST allowlist(3.01)가 1차 네트워크 차단
- 최종 보고에 Cloud Run sandbox 설정, runtime 권한, secret/env 전달 차단 등 사용자 조치 필요 항목이 있으면 2.09 Real GCP integration E2E에 누적한다.

---
id: "3.06"
phase: 3
title: "Diagnostic 2-tier (internal/user + redaction + 상태 API)"
spec: "specs/phase-3/01-video-phase-c-hardening.md"
issue: "96"
depends_on: ["2.04", "2.09"]
blocks: []
estimate: "M"
status: "todo"
owner: ""
sprint: ""
---

# Task 3.06 — Diagnostic 2-tier

> Spec: [`specs/phase-3/01-video-phase-c-hardening.md`](../../specs/phase-3/01-video-phase-c-hardening.md)
>
> Issue: [#96](https://github.com/Team-Proovy/proovy-agent/issues/96)

## 의존성

- 2.04 (워커 서비스) — 워커가 stage별 internal/user diagnostic을 생성, 2.01의 user_diagnostic 매핑 확장 **[cross-phase]**
- 2.09 (Real GCP integration E2E) — GCS/status API 결과 경로 검증 후 diagnostic 저장·조회 확장 **[cross-phase]**

## 사전 준비

- [ ] 설계 §6.6 Diagnostic 2-tier / UserErrorCode enum 재확인

## 구현 체크리스트

- [ ] `internal.json` (원본 문제·script·생성 코드·stderr — 운영자) vs `user` (실패 단계·safe error code·재시도 여부·최종 URL)
- [ ] GCS 기록 + user tier를 잡 상태 API로 즉시 조회
- [ ] redaction (API key / raw stderr / 생성 코드 미노출) + `UserErrorCode` enum 한국어 메시지

## Definition of Done

- [ ] user diagnostic redaction fuzz 테스트 (§0.5 secret 누출 0)
- [ ] UserErrorCode coverage 테스트 100%
- [ ] 자동화된 테스트 통과

## 리스크 / 메모

- redaction 누락이 최대 보안 risk — CI redaction fuzz test로 강제 (§0.5)

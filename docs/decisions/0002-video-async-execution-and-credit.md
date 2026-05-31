---
status: accepted
---

# 0002 — 영상 비동기 실행(Mode B) + 크레딧 hold 모델

> **개정 (ADR 0004)**: 이 ADR의 **Mode B(비동기 실행)는 유효**하다. 단 **크레딧 세부는 [ADR 0004](./0004-unified-credit-ledger.md)가 개정**한다 — hold는 video_node가 아니라 **Planner가 plan 전체로** 한 번 잡고(부족 시 요청 통째 거절), 영상 정산은 워커 capture/void가 아니라 **video_node가 Cloud Tasks createTask 전에 동기 capture + 실패/취소 terminal에서만 환불**한다. 아래 본문의 크레딧 메커니즘(video_node hold, 워커 capture/void)은 역사적 기록으로 남긴다.

## Context

영상은 5~15분(최대 20분)짜리 긴 비동기 잡이다. video-generation-design.md §2.5는 VideoNode가 완료까지 폴링하며 기다리는 **Mode A(블로킹)** 를, implementation_plan.md §9는 크레딧을 **예약 즉시 차감 후 차액 정산**하는 모델을 정해놨다.

검토 결과 Mode A는 (a) API 재배포 시 폴링 그래프(detached task)가 죽어 hold가 **상시 고아**가 되고, (b) 동시 렌더 수만큼 그래프 상태를 길게 보유한다. 또 §9의 즉시 차감은 15분 렌더 동안 **표시 잔액이 틀리게** 보인다.

## Decision

- **실행 = Mode B (논블로킹)**: VideoNode가 크레딧 hold + 큐 enqueue 후 **즉시 반환**, 그래프는 종료. 렌더는 워커가 독립 수행.
- **크레딧 = authorization hold**: enqueue 시 *가용* 크레딧만 hold(표시 잔액 불변, 동시 작업 게이트). 완료 시 **성공→capture(실차감) / 실패→void(해제)**. 영상은 정액 10cr. 작은 초과는 마이너스 허용(cap/최악값 예약 안 함).
- **크레딧 마무리 = 비동기 + idempotent**: 워커가 완료 시 좁은 `finalize_video_credit(job_id, outcome)` API 호출(워커가 원장 직접 write 안 함). job_id 기준 한 번만(Cloud Tasks 재배달 대비).
- **진행률 = MVP는 폴링**(job 상태 조회). live-push broker는 나중.
- **결과 = `video_jobs`(DB)** 가 출처, 프론트가 거기서 렌더 → "messages 단일 소스"의 문서화된 예외.
- **고아 hold = reconciliation sweep**(§3.4 progress-staleness 재사용)으로 void.

## Considered Options

- **Mode A(블로킹) + §9 즉시차감/정산**(문서 원안): 한 줄 선형 그래프라 만들기·테스트는 쉽지만, 배포마다 hold 고아 + 동시성만큼 상태 보유 + 렌더 중 표시 잔액 부정확. 긴 비동기 잡엔 부적합 — 기각.

## Consequences

- 크레딧 마무리·결과 전달이 그래프 밖으로 분산 → 실패 모드↑(capture↔result write 순서/원자성 주의), E2E 테스트가 그래프+워커로 쪼개짐.
- `credit_settler`는 영상 전에 끝나 "총 N cr"가 잠정값 → 영상 확정 시 갱신 이벤트 필요.
- live 진행률은 폴링이라 약간 chatty(broker 도입 시 해소).
- 신규 선결: 비동기 idempotent 크레딧 finalize + (폴링 기반) 진행률. 나머지(messages 예외, 고아 sweep)는 기존 설계 조각(video_jobs, progress-staleness)에 얹음.

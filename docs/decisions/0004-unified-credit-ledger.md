---
status: accepted
---

# 0004 — 통합 크레딧 원장: 단일 balance, 전 작업 공유 (Planner hold + 낙관적 차감)

> **개정 (2026-05-28)**: 본문 §Decision의 "차감(capture)은 CreditSettler(그래프 끝)에서 일괄"은 **영상에 한해** *video_node가 Cloud Tasks createTask 전에 동기 capture*로 이동한다. **이유**: Mode B 워커는 그래프 종료 후 비동기로 도므로, capture가 그래프 끝에 남으면 *워커 refund가 CreditSettler capture보다 먼저 도착*하는 race(공짜 +10cr)가 가능. video_node 안에서 `video_jobs` row 생성과 같은 트랜잭션으로 `balance −= 10, hold −= 10`을 끊고 그 뒤 createTask를 호출하면 "워커 도착 시 capture가 반드시 끝나 있음"을 보장 → refund 시그니처가 `balance += 10` 하나로 단순. `cloud_tasks_name`은 `job_id` 기반 deterministic task name으로 DB row 생성 시 함께 저장해 createTask 성공 후 DB UPDATE 실패 모드를 없앤다. 관측된 createTask 실패는 deterministic task name으로 getTask를 확인하고, 실제 task가 없고 아직 `queued + lease_holder=NULL`일 때만 즉시 `failed` terminal + 환불을 한 트랜잭션으로 보상한다. 이미 `running/succeeded`면 실제 task가 생성된 것이므로 환불하지 않고 enqueue 성공으로 간주한다. 취소도 terminal을 실제로 잡은 주체가 같은 트랜잭션에서 환불한다. lazy detection은 보상 전 프로세스 사망의 백스톱이다. **동기 작업(solve/pdf)은 변함없이 CreditSettler가 그래프 끝에 일괄 차감**(변동 비용 합산 가치 유지). 단일 원장·Planner 전체 hold·실패/취소 시 환불은 그대로. 자세한 흐름은 [video-generation-design.md §1.3](../architecture/video-generation-design.md#13-크레딧-정액-hold).

> **개정 (2026-05-28, 스키마)**: 본문 §Decision의 *단일 `credits(balance, hold)` 행 + hold TTL/에러 경로 void* 는 **별도 `credit_holds` 테이블 + TTL-on-read filter**로 변경한다. 각 hold가 개별 row(`id, user_id, amount, status, created_at, expires_at`)로 존재하고, 가용 잔액 계산 시 `WHERE status='pending' AND expires_at > NOW()` 필터로 *읽는 시점에* 만료를 자동 제외. **orphan hold sweep cron 불필요** — 그래프 크래시로 hold 후 capture 누락된 경우에도 `CREDIT_HOLD_TTL_SECONDS=1200`(20분, 그래프 worst case의 2.5배) 지나면 사용자 가용 잔액이 자동 회복. 만료된 pending row 자체의 housekeeping(`status='released'` transition)은 correctness 무관 — 운영자 재량(예: 6개월 후 cleanup). 단일 원장·Planner 전체 hold·all-or-nothing 거절은 그대로. 스키마와 흐름은 [video-generation-design.md §1.3.1~1.3.3](../architecture/video-generation-design.md#131-크레딧-스키마--credit_holds-테이블--ttl-on-read).

> **개정 (2026-05-30, 사용자 재시도)**: `action="video_retry"` 요청은 Planner가 credit hold를 만들기 전에 `retry_source_job_id` preflight를 먼저 수행한다. invalid retry(없는 job, 다른 사용자/스레드, `failed/canceled` 아님, 이미 사용자 재시도 1회 소비, retry로 만들어진 job, `input_snapshot` 없음)는 **hold 없이 거절**한다. VideoNode와 DB unique 제약은 새 job 생성/영상 10cr capture 전에 같은 조건을 방어적으로 재검증한다. preflight 후 동시 더블클릭 race 등으로 방어 재검증에서 막힌 경우에는 job/capture 전이므로 현재 plan hold를 즉시 `released` 처리한다. 이는 복구 로직이 아니라 잘못된 재시도 요청이 사용자의 가용 크레딧을 20분 동안 묶는 일을 막기 위한 early reject다.

## Context

크레딧 모델이 문서마다 갈려 있었다. implementation_plan.md §9는 "예약(즉시 차감) + 차액 정산"을, [ADR 0002](./0002-video-async-execution-and-credit.md)는 영상만을 위한 "video_node hold + 워커 capture/void"를 정해놨다. 그런데 코드를 보면 **영속 잔액(balance) 자체가 없다** — `credit_log`를 합산해 화면에 "총 N cr" 표시할 뿐이고, `state`의 `reservation_id`/`credit_reserved`는 읽지도 쓰지도 않는 죽은 필드, `features/credits/`·`common/db/`는 빈 스텁(마이그레이션 0개)이다. 이 상태로 영상에만 hold를 붙이면 **"영상만 잔액 검사를 받고 더 비싼 solve는 안 받는" 반쪽 원장**이 된다.

## Decision

크레딧은 **시스템 전반 단일 모델**로 통일한다.

- **단일 원장**: user별 `credits(balance, hold)` 한 곳. solve·pdf·video **모든 유료 작업이 같은 `balance`에서 차감**한다. (반쪽 원장 금지)
- **hold는 Planner에서 plan 전체 예상치로 한 번**: 원자적 `hold += 예상총액 WHERE balance - hold >= 예상총액`. 부족하면 **요청 통째 거절(all-or-nothing)** + "N cr 필요" 안내(아무 작업도 시작 안 함). 단 `action="video_retry"`는 hold 전에 `retry_source_job_id` preflight를 통과해야 한다. 개별 노드 hold·영상만 부분 skip(graceful-skip)은 두지 않는다 — 분기 단순화.
- **차감(capture)**: 동기 작업(solve/pdf)은 CreditSettler가 그래프 끝에 실제 비용으로 일괄 차감한다. 영상은 **Cloud Tasks createTask 전에 video_node가 낙관적으로 정액 차감**한다. `hold`는 예상치만큼 해제하고 `balance`는 실제만 줄여 초과예상은 자동 환불.
- **영상은 낙관적 차감 + 실패/취소 시에만 환불**: 워커가 성공하면 추가 동작 없음(이미 차감). **실패/사망/취소 terminal을 잡은 주체가 같은 transaction에서만 환불(+10)**, `job_id` 기준 idempotent. capture/void 두 갈래가 "terminal 실패/취소 시 환불" 한 갈래로 축소.
- **작은 초과는 마이너스 허용** (cap·최악값 예약 없음).

implementation_plan.md §9의 예약 모델은 이 ADR로 **폐기**. ADR 0002의 Mode B(비동기 실행)는 유효하되, **크레딧 세부**(hold 위치 = video_node→Planner, 영상 정산 = 워커 capture/void → video_node createTask 전 동기 capture + 실패/취소 terminal 환불)는 이 ADR이 **개정**한다.

## Considered Options

- **§9 예약(즉시 차감) + 차액정산**: 시작 시 차감이라 긴 작업 내내 표시 잔액이 틀림 — 폐기.
- **ADR 0002 hold를 워커까지 끌고 가 capture/void**: 렌더 중 표시 잔액은 정확하나 (a) 워커가 capture/void 두 경로를 가짐 (b) 그래프 종료 후에도 hold가 남아 고아 hold sweep이 상시 필요. 영상 성공률 ≥90%면 낙관적 차감이 더 단순 — 기각.
- **영상만 hold (반쪽 원장)**: solve는 잔액을 안 건드리는데 영상만 검사 — 비일관 — 기각.

## Consequences

- **트레이드오프**: 낙관적 차감이라 렌더 도는 동안(5~15분) 표시 잔액이 이미 −10. 실패한 <10%만 잠깐 −10 보였다 환불됨. 성공률 ≥90% 전제에서 수용 — ADR 0002가 hold로 피하려던 현상을 *의도적으로 일부 재수용*하고, 그 대가로 워커·고아처리 단순화를 얻는다.
- 워커 크레딧 책임이 **"실패/협조 취소 시 환불(idempotent)"로 축소.** 성공 경로엔 고아 hold 없음(CreditSettler가 그래프 끝에 남은 hold를 해제). 단 **그래프 에러**(예: solve 검증 실패로 raise)면 hold가 남으므로 **hold TTL(20분) + TTL-on-read**로 자동 회복(가용잔액 계산에서 만료 pending hold를 제외) — 별도 sweep/void cron 불필요(2026-05-28 스키마 개정, 위 헤더 참조). **영상 워커 사망**(차감됐는데 결과 없음)은 lease/lazy detection이 죽은 잡을 감지해 환불.
- invalid 사용자 재시도는 hold 전에 거절되므로 "retry 불가인데 20분간 가용 크레딧이 묶이는" UX가 없다. 그래도 동시 더블클릭은 VideoNode/DB 재검증으로 최종 차단하고, 이미 만들어진 plan hold는 즉시 `released` 처리한다.
- **선결**: `features/credits/`에 `credits` 원장(balance+hold) + 원자적 hold/capture/refund + alembic. **solve·pdf의 CreditSettler도 이 balance에서 차감하도록 배선**(영상 국소 아님 — 시스템 전반). `reservation_id`/`credit_reserved` 죽은 필드 제거.

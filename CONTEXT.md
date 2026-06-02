# Proovy Agent — 도메인 언어

LangGraph 기반 수학 문제 풀이 + 해설 영상/PDF 생성 에이전트. 이 문서는 노드·기능 간에 공유되는 용어의 단일 정의다 (구현 세부 제외 — 용어집).

## 언어

### 풀이 / 영상 경계

**verified_solution**:
CoreSolver가 solve마다 코드 검증을 마친 풀이를 단계·수식·최종답 프로즈로 요약한 것. **대화 내역(messages)에 깨끗한 산출물로 남아** 하류(video/pdf)가 소비하는 중립 산출물. 한 스레드에 문제별로 여러 개 공존한다.
_Avoid_: 단일 state 필드로 오해(멀티턴 다중 문제에 안 맞음 — ADR 0001 Update), SolutionPlan (video의 구조화 형태), explain (학생용 전체 설명)

**code execution evidence**:
CoreSolver의 `code_execute` 도구 호출에서 LangGraph 표준대로 messages에 자동 적재되는 `code`(`AIMessage.tool_calls.args.code`)와 `stdout`(`ToolMessage.content`). hint_extractor Stage 1b가 *trim 미들웨어 부착 없이* 풀텍스트로 LLM에 전달해 verified_solution(프로즈) 옆에 *코드와 실제 출력*을 함께 보임 → 환각이 일어나려면 두 곳에 동시에 같은 왜곡이 필요해 빈도가 낮음. anchor(하드 동치 게이트)가 아니라 *증거 제공*. ADR 0006 (supersedes ADR 0005 `verified_values`).
_Avoid_: verified_values (ADR 0005 폐기 — 답 형태 다양성에 안 맞음), consistency(narration↔화면 일치 — correctness 아님), anchor(강제 게이트는 폐기)

**SolutionPlan**:
verified_solution을 video가 단계 배열(steps[])로 구조화한 영상 입력 형태. video 기능이 소유.
_Avoid_: verified_solution (CoreSolver의 프로즈 원형)

**VideoHints**:
영상 전용 시각화 단서(어느 단계를 그래프로, 무엇을 강조). 풀이 자체가 아니라 풀이 위에 얹는 메타.

**하이브리드 입력**:
video 잡 입력을 새로 풀지 않고, 전체 대화 내역에서 대상 verified_solution을 짚어 재사용 + 영상 전용 hint_extractor **2-step**(Step 1: SolutionPlan + 대상 해소, Step 2: VideoHints)으로 구성하는 방식. ADR 0001 Update.

**hint_extractor 2-step**:
영상 입력 빌드를 외부적으로 두 단계로 분리(정확성 + 설계). **Step 1 — SolutionPlan + 대상 해소**(내부 1a + 1b 두 stage로 다시 분리): **Stage 1a**(`$VIDEO_HINT_TARGET_MODEL`, Flash) messages 메타뷰(ToolMessage trim)로 *라우팅*만 — target turn 식별. **Stage 1b**(`$VIDEO_HINT_PLAN_MODEL`, Sonnet) target turn 슬라이스 풀텍스트(verified_solution + code + stdout)로 *추출* + evidence(ADR 0006). **Step 2**(`$VIDEO_HINT_VIDEOHINTS_MODEL`, Flash): plan만 받아 `VideoHints` — *설계 추론*. 비용이 thread 길이와 무관(1a만 약하게 비례, 1b는 슬라이스 한 set).
_Avoid_: 단일 `with_structured_output` 1회 호출 (원안 — 다른 종류 추론을 같은 LLM이 토큰 예산 나눠 처리), Step 1을 messages 전체에 Sonnet 풀텍스트 통과 (Update 2의 원안 — thread 길이에 비례한 비용 폭증으로 ADR 0001 Update 3에서 분리)

**영상 박스 UX 패턴**:
video_node가 enqueue 직후 messages에 anchor 메시지(`display=tool, tool_name=video_generate, click_action=open_video_viewer, job_id`)를 박고, 워커는 messages 무관여. 프론트가 anchor의 `job_id`로 status API를 폴링/재호출해 박스 UI를 갱신·URL fetch하고, `succeeded/failed/canceled` terminal을 받으면 polling을 멈춘다. signed URL은 status API가 `artifact_object_key`로 즉석 발급하며 DB/messages에 저장하지 않는다. 도구 호출 박스(✅/❌ terminal)와 달리 완료 후 `>` 아이콘 + 클릭 시 비디오 뷰어 팝업. "messages 단일 소스" 원칙의 문서화된 예외 — messages는 박스 존재의 anchor + 핸들, DB는 휘발성 상태(URL/progress/만료)의 truth.
_Avoid_: 워커가 messages에 결과 append (그래프 밖에서 LangGraph state 만지면 race), signed URL을 messages에 박기(TTL 1시간이라 곧 stale)

**사용자 재시도 버튼**:
failed/canceled 영상 박스에서 사용자가 다시 만들기를 누르는 흐름. 프론트는 사용자가 버튼을 누른 사실을 보이는 사용자 말풍선 `HumanMessage(content="이전 영상 다시 만들기", additional_kwargs={"action":"video_retry","retry_source_job_id":...})`로 남겨 표준 그래프 요청을 시작한다. 기존 terminal job은 `queued/running`으로 되살리지 않고, 기존 job의 **job 입력 스냅샷**을 복사해 새 `job_id`를 만든다. 사용자 재시도는 원본 job당 1회만 허용하며, retry로 생성된 job은 다시 retry 원본이 될 수 없다. 이전 failed/canceled job은 이미 환불됐고 새 job이 다시 10cr capture하므로, 크레딧 관점의 최종 결과는 성공한 시도 1번만 과금이다. 이미 succeeded인 영상을 다시 만들면 retry가 아니라 별도 regenerate/new video request이며 새 과금.
_Avoid_: terminal job 재활성화(status 되감기), 같은 `job_id` 재사용(artifact/lease/credit 이력 혼합)

**재시도 원본 job id (`retry_source_job_id`)**:
사용자 재시도 버튼이 참조하는 기존 failed/canceled 영상 job의 id. 새로 만들 job id가 아니며, 존재하지 않거나 다른 사용자/스레드의 job이거나 status가 failed/canceled가 아니거나 이미 사용자 재시도 1회에 소비됐거나 원본 자체가 사용자 재시도로 만들어진 job이거나 job 입력 스냅샷이 유효하지 않으면 재시도 원본으로 쓸 수 없다.

**job 입력 스냅샷 (`input_snapshot`)**:
job 생성 순간의 `VideoJobInput`(problem_text, SolutionPlan, VideoHints, VideoOptions)을 JSON으로 고정 저장한 값. 사용자 재시도 버튼은 현재 대화를 다시 해석하지 않고 이 값을 검증·복사해 새 job을 만든다. 시스템 retry(Cloud Tasks 재배달)는 같은 job 안에서 이 스냅샷을 그대로 사용한다.
_Avoid_: 재시도 때 hint_extractor 재실행(대화가 바뀌면 다른 대상/힌트가 나올 수 있음), mutable input snapshot

**explanation_mode** (full / brief):
텍스트 풀이가 결과물인지(full — Phase 2 전체 설명) 영상의 재료일 뿐인지(brief — verified_solution만 노출, Phase 2 생략)를 가르는 의도 구분. Planner가 정함.

**멀티턴 참조 해소 (multi-turn reference resolution)**:
사용자가 "아까 1번 …"처럼 이전 턴을 가리킬 때 그 대상을 짚는 일. **video 전용 메커니즘이 아니라** 모든 LLM 노드(Planner·CoreSolver·hint_extractor)가 전체 대화 내역(messages)을 받아 LLM이 암묵적으로 처리하는 표준 동작. checkpointer로 히스토리가 유지돼야 함.
_Avoid_: video가 발명한 기능으로 오해, 별도 "resolver" 노드/필드(과형식화 — 암묵 해소로 충분)

**VideoNode**:
메인 그래프의 영상 진입 노드. 입력 빌드 + 크레딧 hold + 잡 enqueue 후 **즉시 반환**(Mode B). 실제 렌더·결과·크레딧 마무리는 워커가 비동기로.

**Mode B (논블로킹 실행)**:
VideoNode가 잡을 큐에 넣고 즉시 반환해 그래프를 끝내는 방식. 긴 비동기 영상 잡에 채택.
_Avoid_: Mode A (그래프가 렌더 끝까지 폴링하며 기다리는 방식 — 채택 안 함)

**크레딧 잔액 원장 (credits balance)**:
user별 `balance + hold`를 들고 있는 단일 영속 원장. solve·pdf·video 모든 유료 작업이 여기서 차감한다. ADR 0004.
_Avoid_: per-turn `credit_log`를 잔액으로 오해 (그건 이번 턴 비용 내역·표시용일 뿐), 영상 전용 원장(반쪽 원장)

**크레딧 hold**:
Planner가 plan 전체 예상 비용을 가용잔액(balance − active_holds_sum)에서 묶는 게이트. 부족하면 요청을 통째로 거절(all-or-nothing). **한 plan = `credit_holds`의 단일 row**(id, amount, status, expires_at). 차감(capture)은 *그 한 row를 부분으로 깨며* 진행 — 영상분은 video_node가 enqueue 직전에 동기로 `amount −= 10`(+ balance −10), 남은 동기작업(solve/pdf)분은 CreditSettler가 그래프 끝에 `status='captured'`로 finalize(+ balance −실제). **split row(work별 분리) 아님 — 단일 row의 amount 부분차감**(ADR 0004 `hold −= 10`). **만료된 pending hold는 가용잔액 계산에서 자동 제외**(TTL-on-read) — 별도 sweep 없이 orphan hold 자동 회복.
_Avoid_: 예약 즉시 차감(§9 폐기), video_node 개별 hold·graceful-skip(ADR 0004로 Planner 전체 hold로 통일), work별 hold row 분리(`video_hold_id`/`sync_hold_id` — 단일 row의 amount 부분차감으로 충분, 설계 §1.3.2 SQL이 한때 split을 가정했던 건 오기), 단일 `credits.hold` 컬럼(원안 ADR 0004 — credit_holds 테이블로 분리되어 TTL-on-read 가능)

**TTL-on-read (hold 만료)**:
hold record는 만료 후에도 DB에 row로 남지만, 가용 잔액 계산 시 `WHERE status='pending' AND expires_at > NOW()` 필터로 *읽는 시점에* 자동 제외. 별도 sweep cron 불필요 — SQL 필터 하나로 orphan hold 자동 회복. 그래프가 hold 후 크래시해도 TTL(20분) 지나면 사용자 가용 잔액이 자동 복구되고, 돈은 한 푼도 차감되지 않음(capture가 안 됐으므로).
_Avoid_: hold sweep cron (ADR 0004 원안의 hold TTL/에러 경로 void — TTL-on-read로 대체)

**lazy detection (stuck job)**:
외부 cron 없이 *사용자 활동 endpoint*에서 stuck 잡 정리. running은 `progress_updated_at` heartbeat stale로 failed/canceled terminal + refund를 같은 transaction으로 처리하고, queued는 deterministic `cloud_tasks_name`으로 Cloud Tasks getTask가 NOT_FOUND일 때만 failed terminal + refund를 같은 transaction으로 처리한다(정상 backlog 오탐 방지). thread 목록·messages 조회(저빈도, 페이지 네비게이션급)는 `_sweep_user_stuck_jobs(user_id)` 광역 sweep, status 폴링(기본 2초 hot)은 `_check_single_stuck_job`로 *폴링 중인 그 잡 1건만* 단일행 체크 — hot endpoint에 광역 UPDATE를 얹는 쓰기 증폭 회피(임계가 분 단위라 검출 지연 동일). active/intermittent 사용자는 자동 정리, abandoned 사용자(영영 안 옴)만 정리 미발생 → MVP 수용. Phase D에서 metric 보고 Cloud Scheduler 추가 여부 결정.
_Avoid_: 항상 외부 cron 필요로 보기 — lazy detection이 더 단순하고 인프라 0 추가

**낙관적 차감 (영상)**:
영상은 **video_node가 Cloud Tasks createTask 전에 동기로 정액 차감**(balance −= 10, hold −= 10)하고, 실패/취소 terminal에서만 환불(job_id idempotent)한다. terminal 전환(`failed/canceled`)과 환불은 같은 transaction에서 처리한다. 동기 작업(solve/pdf)은 CreditSettler가 그래프 끝에 일괄 차감 — 영상만 settler 분리. **이유**: Mode B 워커는 그래프 밖에서 비동기로 실행되므로, capture가 그래프 끝(CreditSettler)에 있으면 *워커가 capture보다 먼저 실패할 때* refund(+10)가 uncaptured balance에 적용돼 공짜 크레딧 발생. createTask 전에 동기 차감하면 "워커가 도착할 때 capture가 반드시 끝나 있음"을 보장 → refund 시그니처가 단순(`balance += 10`만). `cloud_tasks_name`은 `job_id` 기반 deterministic task name으로 DB row 생성 시 함께 저장해 createTask 성공 후 DB UPDATE 실패 모드를 없앤다. 관측된 createTask 실패는 task 존재 여부와 lease 상태를 확인한 뒤, 실제 task가 없고 아직 `queued + lease_holder=NULL`일 때만 즉시 `failed` terminal + 환불을 한 트랜잭션으로 보상한다. 이미 `running/succeeded`면 실제 task가 생성된 것이므로 환불하지 않고 enqueue 성공으로 간주한다. lazy detection은 보상 전 프로세스 사망의 백스톱이다.
_Avoid_: 워커 capture/void(ADR 0002 원안), 영상도 CreditSettler 일괄차감(ADR 0004 원안 — refund race로 개정)

**best-effort + lazy reconciliation (capture↔createTask race)**:
video_node에서 (DB INSERT + credits capture) + (Cloud Tasks createTask) 두 외부 시스템 작업을 atomic하게 묶을 수 없으므로(distributed transaction), DB 부분만 single transaction으로 묶고 Cloud Tasks는 별도 호출. `cloud_tasks_name`은 `queues/.../tasks/video-{job_id}`로 결정해 DB row에 먼저 저장하고, createTask는 같은 name으로 호출한다(`AlreadyExists`는 같은 job의 성공으로 간주). 관측된 createTask 실패는 deterministic task name으로 getTask를 확인하고, 실제 task가 없고 아직 워커가 lease를 못 잡은 `queued + lease_holder=NULL` 잡에 한해 `video_jobs.status='failed'` + `refund_if_not_succeeded`를 한 트랜잭션으로 보상한다. 네트워크 timeout처럼 실제 task 생성 여부가 애매하고 task가 존재하거나 워커가 먼저 `running`으로 바꿨다면 환불하지 않고 enqueue 성공으로 간주한다. lazy detection은 capture 후 createTask 호출/보상 전 프로세스가 죽어 queued로 남은 잡을 임계 후 getTask로 확인하고, task가 없을 때만 정리하는 백스톱이다. enqueue 실패 누적 metric이 임계 넘으면 Phase D에 Outbox 패턴(별도 publisher 워커가 Cloud Tasks 호출 담당) 도입.
_Avoid_: video_node 내에서 enqueue → capture 순서 (capture 실패 시 task 그대로 진행 → 무료 영상), 처음부터 Outbox 도입 (인프라 복잡도 ↑ — 실측 빈도로 결정)

**Permanent vs Transient 실패 분류**:
영상 워커의 실패를 두 종류로 명시 구분. **Permanent**(AST 위반·script_repair 3회 소진·malformed input 등) = retry해도 같은 결과 → status=failed + 환불을 같은 transaction으로 처리하고 return 200(ack — Cloud Tasks retry 안 함). **Transient**(LLM rate limit·OOM·네트워크 일시 장애 등) = retry 시 성공 가능 → **환불 안 함** + lease release + return 503(Cloud Tasks retry). 미분류 예외는 보수적으로 permanent 처리(돈 손해 < 무료영상 손해, 운영자가 분류 추가). 분류 없이 모든 실패에 환불하면 transient 후 retry 성공 시 capture는 유지되고 환불은 일어나 *무료 영상* race.
_Avoid_: "실패 = 환불" 단순화 (Q5 grilling으로 분리), Cloud Tasks `X-CloudTasks-TaskRetryCount` 헤더로 분기 (brittle — 헤더에 의존, 변경에 취약)

**영상 취소 (video cancellation)**:
사용자가 영상 잡을 중단하는 행위. **terminal 상태(`canceled`)를 실제로 잡은 주체만 환불**한다. queued + lease 없음이면 API가 `status='canceled'` + refund를 한 transaction으로 처리하고 Cloud Tasks delete는 best-effort. running이면 API는 `cancel_requested=true`만 세우고, 워커가 10초 cancel poll 또는 stage 경계에서 감지해 render sub-process를 멈춘 뒤 `status='canceled'` + refund를 한 transaction으로 처리한다. 외부 LLM/TTS 호출 중이면 해당 call timeout까지 취소 terminal이 늦을 수 있다. `succeeded/failed/canceled`는 no-op. running cancel 요청 후 워커가 죽으면 lazy detection이 `cancel_requested=true`를 보고 failed가 아니라 canceled + refund로 정리한다.
_Avoid_: cancel 요청 즉시 running job 환불(워커가 성공 처리하면 무료 영상), terminal 전환과 환불을 별도 transaction으로 분리

**artifact attempt / orphan artifact**:
영상 워커는 lease 획득 때 `active_attempt_id`를 만들고 모든 GCS 산출물을 `video-jobs/{job_id}/attempts/{attempt_id}/...` 아래에 쓴다. 성공 finalize가 `video_jobs.artifact_object_key`를 성공한 attempt의 `final.mp4`로 바꿀 때만 사용자에게 노출된다. GCS upload는 성공했지만 DB finalize가 실패하면 transient로 보고 503 retry; 이미 올라간 파일은 orphan artifact로 남긴다. orphan artifact는 DB 포인터가 가리키지 않는 attempt 산출물이며, 즉시 삭제하지 않고 GCS 30일 TTL로 정리한다.
_Avoid_: job_id 단일 경로 덮어쓰기(stale worker가 결과를 섞을 수 있음), DB finalize 실패 직후 보상 삭제(삭제 race·복잡도 대비 저장공간 비용이 작음)

**lease release (자발적 양보)**:
워커가 실패할 때 `lease_holder_instance_id = NULL` 명시 설정 — 다음 Cloud Tasks retry가 즉시 새 lease를 받게 함. self-fence(타의로 lease 탈취당함)와 반대로 자의로 양보. transient 실패에서 lease release를 안 하면 다음 retry가 8분 stale 기다려야 lease 탈취 가능 → max_attempts 소진 전에 lease 만료 못 해 stuck job 됨. permanent 실패에서도 release(이미 종료된 잡이라 의미는 작지만 정합성 유지).
_Avoid_: lease를 그대로 두고 503 반환 (다음 retry가 진입 못 함 → 처음부터 stuck)

**lease (잡 임대권)**:
"이 영상 잡은 내 Cloud Run 인스턴스가 처리한다"는 시간 제한 소유권. `video_jobs.lease_holder_instance_id` + `progress_updated_at`로 DB에 표현. lease holder만 heartbeat로 갱신할 수 있고, 8분간 갱신이 멈추면 만료 → 다른 인스턴스가 원자적 UPDATE로 탈취 + 처음부터 재실행. `succeeded/failed/canceled`는 terminal이라 lease 획득 대상이 아니다. **동시에 두 인스턴스가 같은 잡을 처리하지 않는다**는 보장의 핵심.
_Avoid_: progress write를 생존 신호로 *재사용*하는 원안(long-running scriptify stage에서 false-positive double dispatch — Q3 grilling으로 분리)

**heartbeat (lease 갱신)**:
워커가 60초마다 `progress_updated_at = NOW()`를 write해 lease 유지. asyncio task로 stage 실행과 *병렬*이라 long-running single-LLM stage(scriptify)에도 끊김 없는 생존 신호. UPDATE의 `WHERE lease_holder = my_instance_id` 조건이 self-fence 역할 — 누가 탈취하면 affected_rows=0 → 즉시 작업 중단.
_Avoid_: progress write(SSE용 진행 표시)와 혼동 — 둘은 *독립*. progress는 사용자에게 보일 진행률, heartbeat는 인프라용 생존 신호.

**platform-features 샌드박스**:
렌더 격리를 nsjail 한 도구가 아니라 gen2+concurrency=1(커널) / 비루트+크기제한 볼륨+일회성(FS) / rlimit·timeout(자원) / AST allowlist / 시크릿 미전달 조각으로 조립한 것.
_Avoid_: nsjail (채택 안 함 — 보안 사고 시 선택적 추가 계층)

## 관계

- **CoreSolver**가 solve마다 **verified_solution**(프로즈)을 대화 내역에 남김 + `code_execute` 호출의 code/stdout이 LangGraph 표준대로 ToolMessage에 자동 적재(**code execution evidence**) → **VideoNode**가 히스토리에서 대상을 골라 소비
- **VideoNode**가 **2-step**으로 처리: ① Step 1이 messages 전체에서 대상 문제·**verified_solution**을 짚고 **SolutionPlan** 생성 (evidence 풀텍스트 LLM 전달 — ADR 0006), ② Step 2가 plan만 받아 **VideoHints** 생성
- 충실성은 *hard 게이트가 아니라* evidence 제공으로 환각률 자체를 낮추는 방식. Phase D frame 회귀가 *영상 최종 산출물*에서 측정 (ADR 0006 supersedes ADR 0005)
- **explanation_mode**는 **Planner**가 정하고 **CoreSolver**가 소비
- **video**는 이번 plan에 pending **solve**가 있을 때만 대기 — 이전 턴 풀이를 참조하는 `[video]`-단독 plan은 즉시 진행(**PlanExecutor**)
- **멀티턴 참조 해소**는 **Planner**(의도/라우팅)·**CoreSolver**(재풀이)·**hint_extractor**(영상)가 공유 — 모두 전체 히스토리를 LLM에 넘김. solve는 다시 풀고, video는 이전 **verified_solution** 재사용(차이는 그것뿐)
- **Planner**가 plan 전체 예상치를 **크레딧 hold**(부족 시 요청 거절) → **CreditSettler**가 그래프 끝에 **크레딧 잔액 원장**에서 일괄 차감
- 영상은 **낙관적 차감**(createTask 전 차감) → 실패/취소 terminal을 잡은 주체가 같은 transaction으로 환불
- (Mode B라) 영상 결과·크레딧 마무리는 그래프 밖(워커)에서 → **video_jobs**(DB)가 결과의 출처

## Flagged ambiguities

- **"문제(problem)"의 출처**: 사용자 입력은 `messages`의 HumanMessage에 있다. 멀티턴에선 **최신 HumanMessage가 문제가 아니라 명령일 수 있다**("아까 1번 영상으로") — video는 '최신 메시지'가 아니라 **전체 히스토리에서 대상 문제를 해소**한다. `ocr_text`는 Preprocessor VLM이 뽑은 텍스트+그림 caption으로, **per-turn으로 messages에 동반**(단일 state 필드 아님 — 멀티턴, `verified_solution`과 같은 교훈)되어 텍스트 노드(solve·video·pdf)가 HumanMessage(의도)와 *함께* 읽는다. 이미지 자체는 비영속(VLM 결과 신뢰). 영상은 입력 modality 무관 — 타이핑이든 VLM 추출이든 동일하게 messages의 텍스트를 소비(이미지→영상은 video-side 분기 없이 상류 VLM 존재 여부일 뿐).
- **멀티턴 다중 문제("아까 1번")**: 한 스레드에 여러 문제·풀이가 쌓인다. 단일 `verified_solution` 필드로는 덮어써져 옛 문제를 못 가리킴 → **대화 내역 전체를 컨텍스트로 두고 hint_extractor가 대상을 LLM으로 해소**. ADR 0001 Update.
- **일치(consistency) vs 정확(correctness)**: consistency validator는 narration↔화면 *일치*만 본다(자기들끼리 맞나). 화면값이 *실제 계산값과 맞나*는 별개. ~~ADR 0005의 `verified_values` hard anchor~~는 답 형태 다양성에 안 맞아 폐기(ADR 0006). 대신 hint_extractor가 **code execution evidence**(code+stdout)를 풀텍스트로 보고 *환각률 자체를 낮추는* 방식 — 강제 게이트 없음, Phase D frame 회귀로 측정.
- **"풀이(solution)"의 두 형태**: CoreSolver의 프로즈(**verified_solution**) vs video의 구조(**SolutionPlan**) — 별개 개념으로 분리 확정. CoreSolver는 SolutionPlan을 만들지 않는다 (레이어 분리).
- **"solve"의 두 역할**: 결과물(텍스트 풀이) vs 전제(영상 재료) — **explanation_mode**로 구분.
- **영상 실행 모델**: Mode A(블로킹) vs Mode B(논블로킹) — Mode B로 확정(배포 안정성·확장성). ADR 0002.
- **크레딧 모델**: §9 예약(즉시 차감) vs ADR 0002 영상-전용 hold(워커 capture/void) vs 통합 — **단일 balance 원장 + Planner 전체 hold(all-or-nothing) + 동기작업은 CreditSettler 그래프끝 일괄차감, 영상은 video_node createTask 전 동기 capture + 실패/취소 시 환불** 으로 확정. §9 폐기, ADR 0002 크레딧 세부 개정. ADR 0004.
- **Cloud Run gen1 vs gen2**: gen1 = gVisor, gen2 = microVM(풀 Linux) — 초안 "gen2 = gVisor"는 오기. 렌더는 TeX/ffmpeg 호환·CPU 때문에 gen2. ADR 0003.

## Example dialogue

> **Dev:** "CoreSolver가 SolutionPlan을 바로 내보내면 video가 편하지 않나요?"
> **설계자:** "아니요. SolutionPlan은 video의 입력 모양이라 CoreSolver가 그걸 알면 레이어가 거꾸로 됩니다. CoreSolver는 verified_solution(중립 프로즈)만 내고, 구조화는 video가 합니다. pdf도 같은 verified_solution에서 자기 구조를 만들고요."
>
> **Dev:** "1번 풀고 3번 풀었는데 '아까 1번 영상으로'라고 하면 어떻게 1번을 찾나요?"
> **설계자:** "verified_solution을 단일 필드로 안 둡니다 — solve마다 대화 내역에 남아요. video의 hint_extractor Step 1이 전체 히스토리를 읽고 '1번'을 짚어 그 verified_solution으로 영상을 만듭니다. 멀티턴이라 최신 메시지(='아까 1번 영상으로')는 문제가 아니라 명령이거든요."
>
> **Dev:** "프로즈 옮기다가 LLM이 6.67을 6.7로 둥글면 영상에 잘못된 숫자가 박히지 않나요?"
> **설계자:** "그래서 hint_extractor가 verified_solution(프로즈)만 보는 게 아니라 *실제 실행한 코드와 stdout*도 같이 봅니다 (LangGraph 표준 ToolMessage로 자동 적재). 환각이 일어나려면 프로즈와 stdout 두 곳에 동시에 같은 왜곡이 있어야 해서 빈도가 매우 낮아요. anchor로 hard 검사하는 방식은 답이 'k>5' 같은 조건일 때 적용 불가라 폐기했고요(ADR 0006)."

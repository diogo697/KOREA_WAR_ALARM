# Integration API v1

Core는 UI·FastAPI를 import하지 않는다. Core는 SQLite WAL에 canonical state·stream·outbox를 기록한다.
별도 API 프로세스는 이를 조회한다. API 쓰기/경보 조작 endpoint는 없다.
OpenAPI 3.x는 실행 서버의 `/openapi.json`, UI는 `/docs`에서 제공한다.

| Endpoint | 응답 |
|---|---|
| `GET /api/v1/status` | 실행 상태, live/synthetic 구분, 최고 레벨, 활성 사건 수, 활성/정상 소스 수, Core heartbeat |
| `GET /api/v1/alert` | level, active, seq, incident_id, category, confidence, first_detected_at, updated_at |
| `GET /api/v1/alert/simple` | `{ "level": 0, "active": 0, "seq": 0 }` |
| `GET /api/v1/incidents` | `limit` 1–200, `min_level`, `category`, `active` 필터 |
| `GET /api/v1/incidents/{id}` | provenance 포함 사건 상세 |
| `GET /api/v1/sources` | 소스 ID, 활성/정상, 마지막 성공, 실패 유형, 관측 latency; 설정 URL/secret 제외 |
| `GET /api/v1/health` | `{ "status": "ok" }`, API 프로세스 생존 확인 |
| `GET /api/v1/latency` | 최근 관련 사건 최대 200건의 출처별 계측 구간 count/p50/p95, 미측정 구간 null |
| `GET /api/v1/stream` | SSE, 영속 이벤트 순서와 reconnect 지원 |

severity 숫자: INFO=0, WATCH=1, WARNING=2, HIGH=3, CRITICAL=4.
`active`는 사건 존재 여부이며 공격 확정을 뜻하지 않는다. 단순 응답은 timestamp가 없으므로 `/status` heartbeat도 확인해야 한다.
`alert.updated_at`은 경보 상태 변경 시각이다. heartbeat를 대신하지 않는다.
Core heartbeat가 10초 이상 없으면 `status=stale`; 정상 API health만으로 수집 정상 여부를 판단하지 않는다.

## SSE

`incident.created`, `incident.updated`, `alert.changed`, `source.health_changed`를 전송한다.
SSE `id`는 모든 스트림 이벤트의 cursor이고 payload의 `seq`는 경보 상태 번호다. 서로 다른 번호 체계다.
`Last-Event-ID` 또는 `?after=N`으로 이후 이벤트를 읽는다. 5초마다 comment heartbeat, reconnect 권장 2초.
보존 범위를 벗어난 cursor는 `stream.reset`과 현재 경보 snapshot을 보내고 가용 이벤트부터 재개한다.
유실 범위가 있으면 REST 상태도 다시 조회한다. DB를 새로 만들면 cursor가 초기화되므로 클라이언트는 reset을 처리해야 한다.

## 인증·오류

환경변수 `KWA_API_TOKEN`을 설정하면 `/api/*`에 `Authorization: Bearer ...`가 필요하다.
토큰을 query parameter로 전달하지 않는다. WebUI는 token 입력 후 fetch 기반 SSE를 사용한다.
CORS는 명시적 origin 목록만 허용한다. 서버는 루프백에만 바인딩한다. 외부 공개에는 HTTPS reverse proxy, 자체 token, 정확한 `allowed_hosts` 설정이 필요하다. 기본 Host는 `localhost`, `127.0.0.1`, `::1`뿐이다. 프록시는 HTTPS scheme과 Host를 올바르게 전달해야 한다.
오류 형태: `{ "error": { "code": 404, "message": "Incident not found" } }`.
rate limit은 프로세스별·IP별 분당 요청 수, 기본 0(비활성). 연결된 SSE의 이벤트마다 과금하지 않는다.

## Webhook

`POST` JSON: alert fields + `event`, `event_id`, `occurred_at`, `notify`.
`X-KWA-Signature`는 전송 원본 bytes의 `sha256=<hex HMAC>`다.
`Idempotency-Key`는 stream event와 destination index로 결정하며 재시도에서도 유지된다.
timeout 5초, 실패 시 2의 지수 backoff, 최대 8회 시도 후 failed로 보존한다. 자동 무한 재시도는 하지 않는다.
현재 webhook 대상은 전역 알림 threshold와 해당 webhook min_level을 모두 만족해야 한다.
URL·secret 값은 API에 공개하지 않는다. 실행 중 설정 변경은 지원하지 않으며 재시작이 필요하다.
알림 생성 시 대상 URL과 secret 환경변수 이름을 snapshot으로 보존하여 설정 순서 변경에도 기존 수신처를 유지한다.
이전 스키마의 대상 snapshot 없는 대기 건은 잘못된 수신처로 보내지 않고 실패로 보존한다.

## WebSocket·MQTT·준비 상태

`/api/v1/ws?after=N`은 SSE와 같은 cursor/event/data를 push한다. 서버 발신 전용이며 명령은 받지 않는다.
인증을 켠 서버에서는 Authorization 헤더가 필요하고 브라우저 Origin도 검사한다. query에 token을 넣지 않는다.
MQTT는 선택 adapter다. `status`, `alert`, `incidents` topic에 QoS1·retain으로 발행하며 heartbeat를 포함한다.
클라이언트는 오래된 retained 경보를 현재 상태로 해석하지 않는다. 로컬 broker만 있으면 외부 계정은 필요 없다.

`/api/v1/ready`는 Core와 활성 공개 소스가 정상일 때 200, 그 외 503이다.
`status.coverage=public_feeds`는 공개 피드 수집 정상이라는 뜻이며 사건의 독립성이나 전쟁 탐지 정확도 인증이 아니다.
`status.critical_capable`은 설정된 소스의 종류·신뢰도·발행자 수가 CRITICAL의 필요조건을 만족하는지 표시한다. 기본 설정은 false이며 사이렌이 울릴 수 없다. true도 독립 근거 확보나 탐지 성공을 보장하지 않는다. 이 제약은 `warnings`와 WebUI에도 표시한다.
`status.deliveries`에는 pending/delivered/failed 전송 수가 포함된다.
`critical_available`은 Core heartbeat와 현재 HEALTHY 소스만으로 필요조건을 재점검한다. true도 실제 독립 증거 확보를 보장하지 않는다.
`active_source_families`는 가용 소스의 확인된 원관측 계열만 세며 unresolved는 제외한다. `available_signal_types`는 이와 별개인 신호 종류다. `capability_blockers`는 설정 부족 또는 실시간 장애 사유를 제공한다.
`/sources`는 `health`(HEALTHY/DEGRADED/STALE/OFFLINE), `last_event`, `last_http_status`, `response_latency_seconds`, `parser_failures`, `rate_limit_until`, `reconnects`를 추가 제공한다. 기존 `latency_seconds`는 게시물 나이의 호환 필드로, 최초 탐지 속도가 아니다.
`/alert`에는 `alert_created_time`, `evidence_count`, `independent_family_count`, `latency_seconds`가 추가된다. `delivery`와 `end_to_end`는 클라이언트 계측이 없으므로 null. `/alert/simple`의 숫자형 level/active/seq 계약은 유지한다.
`kwa doctor`는 오프라인 설정 점검, `kwa backup`은 SQLite의 일관된 snapshot 백업이다.

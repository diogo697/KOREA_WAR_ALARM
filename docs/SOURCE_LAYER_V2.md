# Source Layer v2

2026-09-26 구현·검증 범위. Core·DB·기존 조회/알림 계약은 유지한다.

## 적용

- EMSC WSS adapter: 연결·메시지 크기 제한, ping/pong, malformed message 격리, 재연결 backoff, 종료 취소. auth=NEIC/USGS만 수용하고 `usgs` 계열로 묶는다. 나머지 기관은 미채택. 재접속 동안 놓친 이벤트의 복구는 보장하지 않으며 `reconnects`에 흔적을 남긴다.
- adsb.fi JSON adapter: 30초 조회, 최근 직접 ADS-B 민간 비상 코드 7500/7600/7700만 WATCH 대상으로 사용한다. 군 식별 표시·TIS-B·MLAT·오래된 위치·국외 좌표 제외. 항공기 소실/항로 우회를 공격으로 추론하지 않는다. 코드의 최초 발생 시각은 알 수 없다.
- USGS는 원관측망 `net=us`만 수용한다. 기관 식별 검사는 상위 제공자 수준이며 전 세계 각 원시 센서의 운영자까지 증명하는 절차는 아니다.
- source별 poll/minimum interval, 기존 conditional GET 유지. 429의 Retry-After 및 exponential backoff 적용. 반복된 데이터는 `last_content_change`를 갱신하지 않는다.
- QUIET과 장애를 구분한다. 새 사건이 없다는 이유로 OFFLINE으로 바꾸지 않는다. 지정된 정체 한계와 연결 성공 시각으로 상태를 평가한다.
- event_time이 검증된 source_reported인 경우에만 게시 시각 대신 사건 시각으로 correlation. 미확인 사건 시각을 기사 수신 시각으로 채우지 않는다. 180초 correlation/15분 freshness 문턱은 유지한다.
- 항공 비상 등 비군사 신호는 공격 category와 합치지 않는다. 서로 다른 endpoint나 신호 종류를 곧바로 독립 관측으로 세지 않는다.

## 시각과 측정

| 필드 | 의미 |
|---|---|
| event_time / event_time_basis | 원출처가 명시한 발생 시각. unknown/source_reported/simulated 구분 |
| source_publish_time | 확인 가능한 게시 시각. USGS 발생 시각으로 대신 채우지 않음 |
| source_observed_time | KWA가 해당 응답/프레임을 파싱한 시각. 원출처 내부 관측 시각이 아님 |
| kwa_ingested_time / kwa_correlated_time | 로컬 수신 처리·상관 판단 계측 |
| alert_created_time | 로컬 경보 생성 시각. synthetic replay에서는 null |
| client_received_time | 서버가 알 수 없으므로 저장하지 않음 |

`observation_age`는 첫 게시 지연이 아니라 수신 시점 사건 나이다. polling 간격·요청 RTT와도 다르다. source_publication/ingestion/correlation/decision을 구분하고, 음수 시각 차이는 0으로 위조하지 않고 null로 남긴다. 원출처와 로컬의 시계 오차는 보정되지 않는다.
최근 관련 사건 최대 200건만 `/latency`로 집계한다. 데이터가 없는 출처에는 측정치를 만들지 않는다. 전달·종단 지연은 수신측 계측 부재로 null이며 전쟁 발생 확률 또는 SLA를 뜻하지 않는다.

## 검증·남은 제한

- 기존 synthetic CRITICAL/역사 USGS replay 유지. `source_v2_nonwar.json`은 실제 parser를 거치는 합성 지진·항공 비상·훈련·해외 논평 회귀다. 시각을 실측 역사자료로 홍보하지 않는다.
- source health, 429/5xx/DNS/invalid JSON, WS malformed/reconnect/quiet pong, 동일 원관측 중복, 지연 게시 확인, 미측정 시간, 기존 simple API 호환 회귀 포함.
- 기본 구성은 고신뢰 뉴스 발행자 부족으로 CRITICAL 불가. 새로운 센서 수로 이를 우회하지 않는다.
- 검증된 독립 속보·해외 군사 경보 추가, 실제 사건의 최초 공개 기록, 장기간 오탐/미탐·지연 비교, 클라이언트 계측은 남은 과제. 현재 결과로 실제 탐지 속도 개선을 입증하지 않았다.
- 기존 사용자 config는 자동 수정하지 않는다. 기본 6개 source는 신규 설치에 적용한다.

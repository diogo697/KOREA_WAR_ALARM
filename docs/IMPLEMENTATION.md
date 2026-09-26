# 배포 구현 상태 — 2026-09-26

현재 배포는 가입·결제·외부 API 키 없는 공개 피드 모니터다.
기존 TDD의 계정 기반 후보는 사용자 추가 조건에 따라 제외했다.

## 구현

- 기본 공개 RSS 3개 + USGS, source별 timeout·conditional fetch·bounded download·backoff·장애 격리.
- typed Event/Incident, 정규화·중복/출처 계열·시간/공간 상관·결정론적 판정.
- SQLite WAL, read-only API 연결, migration/index, 보존·백업.
- Core/API 분리, supervisor 재시작, worker 재시작, 정상 종료, Windows Job으로 자식 프로세스 정리.
- REST/SSE/WebSocket, OpenAPI, readiness, 자체 LAN 인증 옵션, CORS·rate limit.
- webhook 영속 queue·HMAC·재시도·설정 변경에 안전한 destination snapshot.
- 로컬 알림 시점의 incident snapshot, desktop/siren, MQTT QoS1와 freshness 포함 retained payload.
- TypeScript WebUI, 공개 피드 상태·경보·사건·provenance·SSE 로그·연결 오류 표시.
- `kwa.exe` 첫 실행 자동 설정·로컬 수집·브라우저 실행. Python/Node 설치 없는 OS별 배포 ZIP 빌드.
- synthetic CRITICAL replay와 실제 USGS 사실 기반 회귀 fixture.
- Windows/Linux/macOS CI와 tag 기반 draft release workflow.

## 검증

Windows에서 Python unit/integration, 실제 REST/SSE 재연결, WebSocket CRITICAL, webhook 재시도·대상 snapshot, MQTT 로컬 broker 전송 테스트를 실행한다.
Playwright headless Chromium으로 실제 API 화면·모바일 overflow·연결 장애를 확인한다.
패키징 smoke는 빈 임시 폴더에서 설정 생성·Core/API 동시 실행·정적 자산·CLI·백업·정상 종료를 검사한다.
기본 4개 공개 소스는 실제 다운로드·parser 성공을 확인했다.
pip-audit에서 설치 의존성의 알려진 취약점은 발견되지 않았다. 자체 프로젝트는 PyPI에 없어 audit 데이터베이스 검사 대상이 아니다.
정확한 최종 결과는 [RELEASE_CHECKS.md](RELEASE_CHECKS.md)에 기록한다.

## 제품 범위·한계

- 기본 뉴스는 공개 게시형 feed이며 최속 breaking streaming을 보장하지 않는다.
- 원출처 불명은 WATCH, 단일 센서는 WATCH 이하. 임의로 CRITICAL이 나오도록 문턱을 낮추지 않는다.
- 실제 공개 소스 4개 연결 성공은 실제 사건에서 독립 근거 3계열을 확보했다는 뜻이 아니다.
- 실제 전쟁 탐지 정확도·미탐률·장기 오탐률은 미측정. 역사적 fixture는 센서 단독 오경보 방지 1건이며 종합 calibration corpus가 아니다.
- 가입이나 키가 필요한 ADS-B/AIS/위성 경로는 제외. 무료 공개 독립 source가 확보되지 않은 센서는 구현 완료라고 표시하지 않는다.
- ESP32 핀·실제 desktop popup·오디오 출력은 하드웨어/OS 수동 확인 대상이다.
- macOS/Linux 실행 파일은 각 OS CI에서 빌드한다. 이 Windows 세션에서 실행 검증했다고 주장하지 않는다.
- GitHub remote가 없어 원격 Actions·release 게시·코드서명은 실행하지 않았다.

사용자 원본 TDD는 보존한다. 소스 사용 정책은 최신 사용자 조건과 이 문서를 따른다.

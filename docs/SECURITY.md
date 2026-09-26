# 보안 및 운영

- API는 루프백 바인딩만 허용한다. 외부 접속은 HTTPS reverse proxy를 사용하고 자체 `KWA_API_TOKEN`과 정확한 `allowed_hosts` 호스트 목록을 설정해야 한다. 무료 로컬 실행에는 토큰이나 가입이 필요 없다.
- 프록시는 루프백 API로 전달하고 `Host`와 `X-Forwarded-Proto: https`를 설정한다. TLS 검증을 끄거나 외부 HTTP로 토큰을 전송하지 않는다. CLI·WebUI는 비루프백 HTTP 인증을 거부한다.
- HTTP와 WebSocket 모두 Host 허용 목록을 검사한다. WebSocket은 검증된 동일 출처 또는 명시된 `cors_origins`만 허용한다.
- 환경변수 `KWA_API_TOKEN`, `KWA_WEBHOOK_SECRET` 사용. `.env` 자동 로딩 없음.
- 설정·DB·runtime logs·알림 JSON·`.env`는 Git 제외. API에는 source ID/health만 노출한다.
- 사용자 입력으로 alert를 주입하거나 수집 URL을 바꾸는 API는 제공하지 않는다.
- source URL은 HTTPS, `.go.kr`·`.mil.kr`와 KR government 설정을 거부한다. 민간 도메인으로 운영되는 공공기관까지 자동 식별할 수 없으므로 소스 등록 시 운영자 확인이 필요하다.
- collector는 redirect를 따라가지 않는다. 등록 소스의 이용 조건·rate limit을 확인하고 활성화한다.
- WebUI는 외부 콘텐츠를 `textContent`로 표시하고 HTML로 삽입하지 않는다.
- webhook은 운영자가 관리하는 설정만 사용한다. HMAC 검증과 idempotency 처리는 수신 측 책임이다.
- SQLite 파일에 접근 가능한 로컬 사용자는 경보 데이터를 수정할 수 있다. DB 디렉터리를 신뢰하는 OS 사용자에게만 허용한다.
- 동일 DB의 Core 다중 실행은 OS 파일 잠금으로 차단한다. 단일 Core 프로세스 기준이다.
- 외부 피드/네트워크 장애와 UI 중단 시 INFO를 정상·안전 신호로 해석하지 않는다. `/status`와 `/sources` 확인 필요.

취약점 보고 채널과 GitHub 공개 저장소는 아직 지정되지 않았다. 공개 전 담당자가 지정해야 한다.

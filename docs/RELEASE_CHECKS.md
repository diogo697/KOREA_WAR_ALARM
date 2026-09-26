# 배포 검증

Windows 로컬 검증 결과. 아래 최신 수정본은 아직 원격 CI에서 실행하지 않았다.

- 공개 소스: 기본 6개 연결 HEALTHY 확인. HTTP 5개 응답·parser와 EMSC WSS 연결 확인. 한반도 실사건의 탐지 속도를 측정한 결과는 아님.
- Python 의존성 audit: 알려진 취약점 없음, 자체 미출판 패키지 제외.
- 브라우저: headless Chromium 2개 테스트 통과.
- Python: 77개 unit/integration 테스트 통과. Starlette TestClient deprecation 경고 1개. 원출처 중복, 항공 신호 WATCH 제한, 발생/발행 시각 구분, WSS 재접속·heartbeat, 소스 건강도, 기존 보안 회귀 포함.
- Windows 독립 실행 파일: PyInstaller 빌드·빈 폴더 smoke 통과. 설정 생성, supervisor, Core heartbeat, REST, 정적 WebUI, CLI, 백업, 정상 종료 확인.
- Windows 실행 파일의 기본 공개 소스 6개 실수집·readiness 200 확인. 소리·사용자 브라우저는 테스트에서 열지 않았음.
- MQTT: 로컬 broker에 simulated CRITICAL을 QoS1으로 전달하고 PUBACK 확인.
- replay: synthetic CRITICAL +35초, 역사적 USGS 센서 1건 WATCH·false-positive 0. Source v2 원문 형식 합성 비전쟁 fixture도 WATCH 제한 검증. 실제 탐지 속도/장기 오탐률 추정치는 아님.
- Ruff·TypeScript 빌드 통과. npm audit에서 알려진 취약점 없음.
- 배포물: `dist/korea-war-alarm-0.1.0-windows-amd64.zip` 및 `.zip.sha256`. 라이선스·의존성 목록·예제·문서 포함.
- 최신 수정본의 원격 CI·코드 서명은 미실행.
- 소개용 WebUI: headless Chromium으로 격리된 실수집 서버의 데스크톱·모바일 촬영. `uv run python scripts/smoke_release.py dist/kwa/kwa.exe --live --capture`로 재생성하며 결과는 Git 제외 `dist/promo`에 저장. 촬영 시각·실제 상태는 `capture.json`에 기록. 합성 위기 화면을 사용하지 않음.

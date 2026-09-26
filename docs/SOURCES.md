# Source Registry

기준: 2026-09-26. 가입·결제·키 발급이 필요한 서비스는 제외한다.
사용자 보유 API 계정이나 계약을 요구하지 않는다. 신규 기본 구성은 6개이며 HTTPS 5개와 WSS 1개 연결을 확인했다. 사건이 없던 센서에서 사건 탐지 속도를 측정했다고 주장하지 않는다.

| Name / Operator | URL / Protocol | 인증·가격 / 간격 | License·ToS | Observed latency / Reliability | 독립성 / 상태 |
|---|---|---|---|---|---|
| Democracy Now! / US 비영리 뉴스 | [RSS](https://www.democracynow.org/democracynow.rss) | 무인증·무료 / 120초 | [공식 피드 안내](https://www.democracynow.org/pages/help/podcasting), [콘텐츠 라이선스 표기](https://www.democracynow.org/2026/1/2/romper_la_barrera_del_silencio), CC BY-NC-ND 3.0 US, 별도 저작물 예외 | HTTP 200·42개 항목 parse. 사건 latency 미측정. 초기 신뢰도 0.8 | 원출처 미확인은 독립 근거 제외. 기본 활성 |
| Common Dreams / US 비영리 뉴스 | [RSS](https://www.commondreams.org/feeds/feed.rss) | 무인증·무료 / 120초 | [공식 재사용 정책](https://www.commondreams.org/republish-our-work): 비상업·출처 표기·재게시 콘텐츠 예외. 로컬 피드 열람 범위 | HTTP 200·30개 parse. 사건 latency 미측정. 0.75 | 인용 통신사/정부 계열로 묶음. 기본 활성 |
| Global Voices / NL 비영리 국제 시민 저널리즘 | [RSS](https://globalvoices.org/feed/) | 무인증·무료 / 300초 | [공식 RSS](https://globalvoices.org/feeds/), [재사용 정책](https://globalvoices.org/about/global-voices-attribution-policy/): CC BY 3.0, 작성자·원문·라이선스 표기, 제3자 미디어 예외 | HTTP 200·15개 parse. 사건 latency 미측정. 0.7 | OSINT·시민 보도. 원출처 미확인은 독립 근거 제외. 기본 활성 |
| USGS / US Department of Interior | [공개 GeoJSON](https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson) | 무인증·무료 / 60초 | [공식 형식](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php), [저작권 정책](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits): USGS 제작 데이터 public domain·출처 표시 | HTTP 200·parser 정상. 검증 시 한반도 범위 사건 0개. 0.95는 센서 신뢰도 | 단일 센서 계열. 전쟁 증거 단독 승격 금지. 기본 활성 |
| EMSC/CSEM / FR | [WSS 설명·endpoint](https://www.seismicportal.eu/realtime.html): `wss://www.seismicportal.eu/standing_order/websocket` | 무인증·무료·무가입 / push, 15초 생존 확인 | 해당 WebSocket 데이터 CC BY 4.0, EMSC와 원관측 출처 표시 | handshake·pong 확인, 짧은 관찰 중 사건 메시지 없음. 실제 사건 지연 미측정, 0.95 | `NEIC/USGS`만 허용. USGS와 같은 `usgs` 계열. 기본 활성 |
| adsb.fi / 커뮤니티 운영, 법적 운영국 미확인 | [공개 JSON endpoint](https://opendata.adsb.fi/api/v3/lat/37.5/lon/127/dist/250) | 무인증·무료·무가입 / 30초, 앱 최소 5초 | [공식 API·약관](https://github.com/adsbfi/opendata): 개인·비상업, 출처 링크 필요; 공개 endpoint 1회/초 제한 | HTTP 200·한반도 주변 항공 목록 parse, 검증 중 비상 사건 없음. 요청 약 0.61초는 전쟁 탐지 지연이 아님. 0.5 | `AVIATION`, `adsb-receiver-network`. 타 ADS-B 재집계와 독립성 미입증이므로 같은 계열 취급. WATCH 전용 |

수집 범위는 33–43N, 124–132E 또는 한국 관련 지명이다.
가중치는 초기 정책이며 실측 정확도나 전쟁 발생 확률이 아니다.
첫 다운로드의 `received_at - published_at`은 이미 오래된 게시물의 나이도 포함한다. 이 값을 피드의 실제 속보 전달 지연으로 해석하면 안 된다.
HTTP 200만으로 속보성·독립성을 주장하지 않는다. 여러 피드가 같은 발표를 인용하면 한 계열로만 계산한다.

## 운용 정보

모든 채택 소스는 인증/등록 None, 비용 Free, API key 없음. RSS 실제 갱신 주기와 사건→최초 노출 지연은 미측정이다. 운영자가 밝히지 않은 수치를 추정해 보장값으로 기록하지 않는다. 기본값보다 짧은 간격을 쓰려면 운영자의 제한을 별도로 확인해야 한다.

| 소스 | 목적·가독성 | 실패·독립성 제한 |
|---|---|---|
| Democracy Now!, Common Dreams | RSS 뉴스 확인, 120초 polling | 편집·게시 지연, 인용 계열 미확인 시 WATCH. 통신사 재게시를 별도 증거로 계산하지 않음 |
| Global Voices | RSS 시민 보도, 300초 polling | 속보 센서 아님, 원출처 미확인 제외, 초단위 탐지 기대하지 않음 |
| USGS | JSON 지진, SEISMIC | `net=us`만 채택. 발생 시각과 게시 시각 다름. 자연 지진/발파/관측망 공백 존재 |
| EMSC | JSON WebSocket, polling 대기 없는 전송 경로 | 원관측 생성 지연은 그대로 존재. 연결 유실 중 복구 보장 없음. USGS와 별도 독립 증거 아님 |
| adsb.fi | JSON 항공 비상 코드 관찰 | 위치 노후·수신망 공백·코드 오류·서비스 중단 가능. 비상 코드가 군사 공격 의미는 아님. API의 항공기 목록에서 직접 ADS-B·최신 위치만 선별 |

소스 사업자·약관·원관측망 단위 확인과 모든 원시 센서 운영자의 입증은 다르다. USGS/EMSC 수용 관측기관은 USGS로 제한하며, ADS-B는 군 식별 표시·지상국 재방송·MLAT을 제외한다. 더 엄격한 전체 원시 기여자 검증이 필요한 배포에서는 해당 집계 소스를 비활성화해야 한다.

## 추가 후보 판정 — 2026-09-26

차단·인증 요구를 우회하지 않는다. REJECTED는 명시한 경로에 대한 판정이며 제공자의 모든 상품에 대한 단정이 아니다.

| 후보·공식 근거 | 실제 접근/조건 | 판정·이유 |
|---|---|---|
| [ADSB.lol public API](https://www.adsb.lol/docs/open-data/api/) / `https://api.adsb.lol/v2/point/37.5/127/250` | 이번 환경 HTTP 403, 문서상 공개 API | REJECTED: 현재 접근 불가. key 방식으로 전환하지 않음 |
| [Airplanes.live](https://airplanes.live/api-docs/) / `https://api.airplanes.live/v2/point/37.5/127/250` | 이번 환경 HTTP 403 | REJECTED: 현재 익명 수집 검증 실패 |
| [AISStream](https://aisstream.io/) / `wss://stream.aisstream.io/v0/stream` | 공식 절차에 GitHub 로그인·API key 필요, 인증 연결은 시도 안 함 | REJECTED: registration/API key |
| [CTBTO vDEC](https://www.ctbto.org/resources/for-researchers-experts) | 초저주파 등 연구 접근 신청·계약 필요, 데이터 endpoint 미접속 | REJECTED: 승인·계정/계약 의존 |
| [NASA FIRMS API/WMS](https://firms.modaps.eosdis.nasa.gov/mapserver/wms-info/) | MAP_KEY 필요, 인증 endpoint 미접속 | REJECTED: API key. 별도 공개 정적 다운로드는 이번에 채택하지 않음 |
| [GPSJAM](https://gpsjam.org/about) | about HTTP 200. 항공 자료에서 파생한 지도 | PENDING: 저지연 기계용 endpoint·수집 약관 미검증, ADS-B와 독립 증거로 세지 않음 |
| [일본 총리관저 RSS](https://www.kantei.go.jp/rss.html) | RSS 소개는 공개지만 재배포 제한 명시 | PENDING: J-Alert 원본 익명 기계용 endpoint·지연·재배포 조건 미확보 |
| [JMA XML](https://www.data.jma.go.jp/developer/) / `https://www.data.jma.go.jp/developer/xml/feed/eqvol.xml` | HTTP 200, XML 확인 | PENDING: 지진·화산 자료이지 군사 공격 경보 아님. 일본어 본문 adapter·한반도 관련성·관측 출처 검증 필요 |
| [GDACS](https://www.gdacs.org/Documents/2025/GDACS_API_quickstart_v1.pdf) / `https://www.gdacs.org/xml/rss.xml` | HTTP 200, 재난 RSS 약 878KB | PENDING: 자연재난 확인 자료. 세부 원관측 종속성과 군사 조기경보 효용 미검증 |
| [GDELT DOC](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) / `https://api.gdeltproject.org/api/v2/doc/doc?query=korea&mode=artlist&maxrecords=5&format=json` | HTTP 200, 이번 요청 약 14.7초. 공개 뉴스 집계 | PENDING: 원보도와 독립 아님. 발생→게시 지연 미측정. 저지연 원관측 대체재로 채택하지 않음 |
| [GEOFON FDSN/SeedLink](https://geofon.gfz.de/waveform/webservices/fdsnws.php) | 공식 공개 서비스 문서 확인, 이번 raw-data endpoint 미측정 | PENDING: 원관측망 라이선스·한반도 범위·실시간 파형 처리 필요. 제한 자료 접근은 제외 |

소스 수가 늘었다는 이유로 성공 처리하지 않는다. 이번 변화는 전송 경로·신호 종류·계측 기반의 확장이며 실제 사건 전후 지연 개선은 아직 입증되지 않았다.

## 콘텐츠 처리

피드가 제공한 제목·요약만 처리하며 이미지·동영상·전체 기사 페이지는 수집하지 않는다.
본문 HTML을 제거하고 공백을 정규화하며 작성자, 원문 링크, 라이선스와 처리 사실을 metadata에 보존한다.
기본 배포 용도는 개인의 비상업 로컬 열람이다. 제3자 콘텐츠의 공개 재배포를 자동 허용하지 않는다.
소스별 게시 주기 때문에 국제 통신사 유료 streaming 수준의 지연은 보장할 수 없다.

## 제외한 경로

유료 뉴스 wire·계정 기반 ADS-B/AIS·키 기반 위성 API·인증 Telegram 등은 현재 후보에서 제외한다.
BBC/DW/Bellingcat은 이전 조사에서 HTTP 접근을 확인했으나 현 기본 소스 목록에서 제거했다.
Wikinews는 공개 라이선스를 확인했지만 실제 선택 endpoint 연결 실패로 기본 목록에 넣지 않았다.
가입을 사용자에게 넘기는 방식으로 기능을 충족했다고 표시하지 않는다.

## 역사적 재현

[USGS us2000aert](https://earthquake.usgs.gov/earthquakes/eventpage/us2000aert)의 공개 사실:
2017-09-03 03:30:01.760 UTC, 41.3324N/129.0297E, M6.3, USGS 분류 nuclear explosion.
공개 FDSN 응답으로 확인했다. fixture 수신 시각은 재현용 가정이며 실제 탐지 기록이 아니다.
이 한 센서 관측을 전쟁 CRITICAL로 오인하지 않는 회귀 테스트로 사용한다.

## 의존성·조사

버전은 `uv.lock`과 `web/package-lock.json`으로 고정한다. PyInstaller 6.22.3, Paho MQTT 2.1.0, websockets 17.1의 공식 문서와 설치를 확인했다.
출처: [PyInstaller](https://pyinstaller.org/en/stable/usage.html), [Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html), [FastAPI](https://fastapi.tiangolo.com/).
Brave 한도 초과 뒤 내장 웹과 공개 HTTP를 사용했다. 수집 앱은 해당 검색 서비스나 키에 의존하지 않는다.

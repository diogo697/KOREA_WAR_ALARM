# 외부 연동

[curl](../examples/curl/README.md), [CLI](../examples/cli/README.md),
[Python](../examples/python/poll.py), [JavaScript](../examples/javascript/poll.mjs),
[ESP32 HTTP](../examples/esp32-http/esp32-http.ino), [HMAC 검증](../examples/webhook/verify.py) 예제를 제공한다.
PC 예제는 실제 로컬 API를 호출한다. ESP32는 HTTPS gateway 주소와 인증 정보를 로컬에서 지정해야 한다.

## ESP32

Arduino ESP32 core와 ArduinoJson 7을 설치한다. 서버는 루프백으로 실행하고 외부 접속은 HTTPS gateway를 경유한다.
자체 `KWA_API_TOKEN` 환경변수와 `allowed_hosts`를 설정한다. 이는 외부 발급 키가 아니다.
ESP32의 `local_config.h`에 Wi-Fi·gateway URL·인증 토큰·신뢰 CA를 지정한다. 이 파일은 Git 제외이며 예제 header를 복사해 사용한다. 인증서 검증을 끄지 않는다.

1. Wi-Fi·server·buzzer pin을 장치에 맞춰 지정한다.
2. `/status`가 running일 때만 `/alert/simple`을 사용한다.
3. 새 seq의 active CRITICAL에서 1초간 buzzer를 켠다.
4. 같은 seq 반복 요청에 추가 알림이 없는지 확인한다.
5. API/Core 종료·네트워크 단절 시 과거 상태를 새로운 경보로 재생하지 않는지 확인한다.
6. 재부팅 시 현재 CRITICAL을 한 번 다시 울리는 예제 정책을 실제 장치 요구에 맞게 검토한다.

실제 ESP32 업로드·핀 동작·Arduino 빌드는 아직 검증하지 않았다.
[MQTT 연동 안내](../examples/esp32-mqtt/README.md)를 제공한다. QoS1 전송은 로컬 broker 통합 테스트로 확인했다.

## 로컬 알림 검증

자동 테스트는 데스크톱 popup·소리를 발생시키지 않는다.
실제 환경 검증 시 폐쇄된 테스트 DB를 사용하고 desktop 지원/Windows 오디오 출력을 확인한다.
Linux/macOS는 desktop backend 설치 상태와 terminal bell 설정에 따라 표시·재생되지 않을 수 있다.

## 장애 계약

API만 중단해도 별도 Core 프로세스의 heartbeat가 계속 갱신되는 통합 테스트를 제공한다.
SSE는 Last-Event-ID 재연결 시 가용 이벤트를 순서대로 전달한다.
Webhook 실패는 영속 outbox에서 재시도하고 로컬 알림·수집 worker와 분리된다.
전달은 at-least-once이며 수신측 event ID 중복 제거가 필요하다.

# ESP32 MQTT 연동

계정 발급 없는 사용자가 운영하는 로컬 MQTT broker에 연결한다. 앱 기본 실행에는 broker가 필요하지 않다.
설정 예:

```yaml
mqtt:
  enabled: true
  host: localhost
  port: 1883
  tls: false
```

외부 broker는 TLS가 필요하다. 로컬 MQTT를 LAN에 전달하려면 TLS broker 또는 장치 gateway를 사용한다.
ESP32 라이브러리의 MQTT 클라이언트로 `korea-war-alarm/alert`와 `/status`를 구독한다.
alert JSON은 `level`, `active`, `seq`, `updated_at`, `heartbeat`를 포함한다.
retained 메시지는 과거 메시지일 수 있으므로 heartbeat가 10초 이상 오래됐거나 `/status`가 offline이면 사이렌을 작동시키지 않는다.
새 seq의 active CRITICAL에만 반응한다. QoS1은 중복 전달될 수 있다.

실제 broker 프로토콜 전송은 Python 통합 테스트에서 확인하며 ESP32 하드웨어는 별도 검증 대상이다.

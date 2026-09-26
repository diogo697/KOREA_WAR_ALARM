#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "local_config.h"

// Wi-Fi 정보는 로컬에서 지정하고 저장소에 커밋하지 않는다.
const int BUZZER_PIN = 25;
unsigned long long lastSeq = 0;
unsigned long lastPoll = 0;
unsigned long buzzerUntil = 0;
bool initialized = false;

void setup() {
  pinMode(BUZZER_PIN, OUTPUT);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void loop() {
  if (buzzerUntil && (long)(millis() - buzzerUntil) >= 0) {
    digitalWrite(BUZZER_PIN, LOW);
    buzzerUntil = 0;
  }
  if (millis() - lastPoll < 2000 || WiFi.status() != WL_CONNECTED) return;
  lastPoll = millis();
  if (!String(SERVER).startsWith("https://") || !strlen(ROOT_CA) || !strlen(API_TOKEN)) return;
  WiFiClientSecure transport;
  transport.setCACert(ROOT_CA);
  HTTPClient http;
  http.setTimeout(3000);
  if (!http.begin(transport, String(SERVER) + "/api/v1/status")) return;
  http.addHeader("Authorization", String("Bearer ") + API_TOKEN);
  bool fresh = false;
  if (http.GET() == 200) {
    JsonDocument status;
    if (!deserializeJson(status, http.getString())) fresh = status["status"] == "running";
  }
  http.end();
  if (!fresh) return;
  if (!http.begin(transport, String(SERVER) + "/api/v1/alert/simple")) return;
  http.addHeader("Authorization", String("Bearer ") + API_TOKEN);
  if (http.GET() == 200) {
    JsonDocument alert;
    if (!deserializeJson(alert, http.getString()) && alert["seq"].is<unsigned long long>()) {
      unsigned long long seq = alert["seq"];
      if ((!initialized || seq != lastSeq) && alert["active"] == 1 && alert["level"] == 4) {
        digitalWrite(BUZZER_PIN, HIGH);
        buzzerUntil = millis() + 1000;
      }
      lastSeq = seq;
      initialized = true;
    }
  }
  http.end();
}

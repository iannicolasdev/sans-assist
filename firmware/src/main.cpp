#include <Arduino.h>
#include <ArduinoJson.h>
#include <WebServer.h>
#include <WiFi.h>

#if __has_include("secrets.h")
#include "secrets.h"
#else
#define SANS_WIFI_SSID ""
#define SANS_WIFI_PASSWORD ""
#endif

namespace {

constexpr uint16_t serverPort = 80;
constexpr size_t maxEventBodyBytes = 512;
constexpr unsigned long reconnectIntervalMs = 10000;
constexpr unsigned long ledStateDurationMs = 3000;
constexpr unsigned long eventReceivedDisplayMs = 700;
constexpr uint8_t yellowLedPin = 13;
constexpr uint8_t redLedPin = 14;
constexpr uint8_t greenLedPin = 26;

WebServer server(serverPort);
bool serverStarted = false;
unsigned long lastReconnectAttempt = 0;
unsigned long ledStateStartedAt = 0;

enum class LedState {
  Idle,
  EventReceived,
  NotificationAccepted,
  InvalidEvent
};

LedState currentLedState = LedState::Idle;

void setLedState(LedState state) {
  currentLedState = state;
  ledStateStartedAt = millis();
  digitalWrite(yellowLedPin, state == LedState::EventReceived ? HIGH : LOW);
  digitalWrite(greenLedPin, state == LedState::NotificationAccepted ? HIGH : LOW);
  digitalWrite(redLedPin, state == LedState::InvalidEvent ? HIGH : LOW);
}

void clearExpiredLedState() {
  if (currentLedState != LedState::Idle &&
      millis() - ledStateStartedAt >= ledStateDurationMs) {
    setLedState(LedState::Idle);
  }
}

void sendJsonResponse(
    int statusCode,
    bool success,
    const char* message,
    const char* eventId = nullptr) {
  JsonDocument response;
  response["success"] = success;
  response["message"] = message;
  if (eventId != nullptr) {
    response["event_id"] = eventId;
  }

  String responseBody;
  serializeJson(response, responseBody);
  server.send(statusCode, "application/json", responseBody);
}

bool hasNonEmptyString(JsonObjectConst event, const char* key) {
  JsonVariantConst value = event[key];
  return value.is<const char*>() && value.as<const char*>()[0] != '\0';
}

void rejectEvent(int statusCode, const char* message) {
  setLedState(LedState::InvalidEvent);
  sendJsonResponse(statusCode, false, message);
}

void handleEvent() {
  if (!server.hasArg("plain") || server.arg("plain").isEmpty()) {
    rejectEvent(400, "Request body is required");
    return;
  }

  String requestBody = server.arg("plain");
  if (requestBody.length() > maxEventBodyBytes) {
    rejectEvent(413, "Request body is too large");
    return;
  }

  JsonDocument event;
  DeserializationError error = deserializeJson(event, requestBody);
  if (error || !event.is<JsonObject>()) {
    rejectEvent(400, "Request body must be a JSON object");
    return;
  }

  JsonObject eventObject = event.as<JsonObject>();
  if (!hasNonEmptyString(eventObject, "device") ||
      !hasNonEmptyString(eventObject, "event") ||
      !hasNonEmptyString(eventObject, "description") ||
      !hasNonEmptyString(eventObject, "timestamp")) {
    rejectEvent(400, "Required string fields are missing or invalid");
    return;
  }

  if (eventObject.containsKey("event_id") &&
      !hasNonEmptyString(eventObject, "event_id")) {
    rejectEvent(400, "'event_id' must be a non-empty string");
    return;
  }

  JsonVariantConst confidence = eventObject["confidence"];
  if (!confidence.is<float>() || confidence.as<float>() < 0.0f ||
      confidence.as<float>() > 1.0f) {
    rejectEvent(400, "Confidence must be a number between 0 and 1");
    return;
  }

  char generatedEventId[32];
  if (!eventObject.containsKey("event_id")) {
    snprintf(
        generatedEventId,
        sizeof(generatedEventId),
        "sans-%08lx%08lx",
        static_cast<unsigned long>(millis()),
        static_cast<unsigned long>(esp_random()));
    eventObject["event_id"] = generatedEventId;
  }
  const char* eventId = eventObject["event_id"].as<const char*>();
  serializeJson(event, requestBody);
  if (requestBody.length() > maxEventBodyBytes) {
    rejectEvent(413, "Request body is too large after adding event_id");
    return;
  }

  Serial.printf(
      "Event received: id=%s device=%s event=%s confidence=%.2f\n",
      eventId,
      eventObject["device"].as<const char*>(),
      eventObject["event"].as<const char*>(),
      confidence.as<float>());

  setLedState(LedState::EventReceived);
  delay(eventReceivedDisplayMs);
  setLedState(LedState::NotificationAccepted);
  sendJsonResponse(200, true, "Notification accepted", eventId);
}

void startServer() {
  server.begin();
  serverStarted = true;
  Serial.printf("HTTP server listening at http://%s/event\n",
                WiFi.localIP().toString().c_str());
}

void attemptWiFiConnection() {
  if (SANS_WIFI_SSID[0] == '\0') {
    Serial.println("Wi-Fi not configured. Set credentials in firmware/include/secrets.h.");
    lastReconnectAttempt = millis();
    return;
  }

  Serial.println("Connecting to Wi-Fi...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(SANS_WIFI_SSID, SANS_WIFI_PASSWORD);
  lastReconnectAttempt = millis();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(yellowLedPin, OUTPUT);
  pinMode(redLedPin, OUTPUT);
  pinMode(greenLedPin, OUTPUT);
  setLedState(LedState::Idle);

  server.on("/event", HTTP_POST, handleEvent);
  server.onNotFound([]() {
    sendJsonResponse(404, false, "Endpoint not found");
  });

  if (SANS_WIFI_SSID[0] == '\0') {
    Serial.println("Configure Wi-Fi credentials in firmware/include/secrets.h.");
    return;
  }

  attemptWiFiConnection();
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!serverStarted) {
      startServer();
    }
    server.handleClient();
    clearExpiredLedState();
    return;
  }

  if (serverStarted) {
    server.stop();
    serverStarted = false;
    Serial.println("Wi-Fi disconnected; HTTP server paused.");
  }

  if (SANS_WIFI_SSID[0] != '\0' &&
      millis() - lastReconnectAttempt >= reconnectIntervalMs) {
    attemptWiFiConnection();
  }
  delay(10);
}

void reconnectMQTT() {
  Serial.print("Connecting MQTT...");
  if (client.connect("ESP32_Client")) {
    Serial.println("connected");
    client.subscribe(topic_cmd);
    client.subscribe(topic_confirm);
  } else {
    Serial.print("failed, rc=");
    Serial.println(client.state());
  }
}

// ===== ส่งสถานะ relay จริง (relayActive / สัญญาณเตือน) ออก MQTT เฉพาะตอนค่าเปลี่ยนไปจากที่ publish ล่าสุด =====
void publishRelayState() {
  if (!client.connected()) return;
  if (relayPublishInit && lastPublishedRelay == relayActive) return; // ไม่เปลี่ยน ไม่ต้อง publish ซ้ำ
  lastPublishedRelay = relayActive;
  relayPublishInit = true;
  client.publish(topic_relay, relayActive ? "ON" : "OFF");
}

// ===== ส่งสถานะกล้อง (ESP กำลังรอคอมตรวจสอบอยู่หรือไม่) ออก MQTT เฉพาะตอนค่าเปลี่ยน =====
void publishCameraState() {
  if (!client.connected()) return;
  if (cameraPublishInit && lastPublishedCamera == awaitingConfirm) return; // ไม่เปลี่ยน ไม่ต้อง publish ซ้ำ
  lastPublishedCamera = awaitingConfirm;
  cameraPublishInit = true;
  client.publish(topic_camera, awaitingConfirm ? "ON" : "OFF");
}

// ===== ส่งพิกัด GPS ปัจจุบัน (lat,lng) ออก MQTT ให้ dashboard ดึงไปแสดงตำแหน่งรถ =====
void publishGps() {
  if (!client.connected()) return;
  if (!gps.location.isValid()) return;

  char buf[32];
  snprintf(buf, sizeof(buf), "%.6f,%.6f", gps.location.lat(), gps.location.lng());
  client.publish(topic_gps, buf);
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String msg;
  for (unsigned int i = 0; i < length; i++) {
    msg += (char)payload[i];
  }
  msg.trim();
  Serial.print("MQTT [");
  Serial.print(topic);
  Serial.print("]: ");
  Serial.println(msg);

  String topicStr = String(topic);

  if (topicStr == topic_confirm) {
    if (msg.equalsIgnoreCase("CONFIRM")) {
      handleCamResult(true, false);
    } else if (msg.equalsIgnoreCase("NOPERSON")) {
      handleCamResult(false, false);
    } else if (msg.equalsIgnoreCase("CLEAR")) {
      handleClearSignal();
    }
    return;
  }

  if (msg.equalsIgnoreCase("off")) {
    systemEnabled = false;
    alarmActive = false;
    digitalWrite(RELAY_PIN, LOW);
    relayActive = false;
    Serial.println("SYSTEM OFF by MQTT");
  }
  else if (msg.equalsIgnoreCase("on")) {
    systemEnabled = true;
    Serial.println("SYSTEM ON by MQTT");
  }
}
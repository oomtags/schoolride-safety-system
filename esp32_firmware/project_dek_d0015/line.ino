void sendLineMessage(String message) {
  if (WiFi.status() != WL_CONNECTED) return;

  message = escapeForJson(message);

  HTTPClient http;
  http.begin("https://api.line.me/v2/bot/message/push");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", "Bearer " + lineToken);

  String payload = "{\"to\":\"" + userId + "\",\"messages\":[{\"type\":\"text\",\"text\":\"" + message + "\"}]}";
  http.POST(payload);
  http.end();
}

String escapeForJson(String text) {
  text.replace("\\", "\\\\");
  text.replace("\"", "\\\"");
  text.replace("\n", "\\n");
  text.replace("\r", "");
  return text;
}

// ===== รถหยุดนิ่งครบ 90 วิ -> สั่งกล้อง (dashboard_app.py บนคอม) เริ่มตรวจสอบผ่าน MQTT =====
void armCameraCheck() {
  triggeredThisCycle = true;
  awaitingConfirm     = true;
  camRequestTime      = millis();
  lastTriggerResend   = millis();

  if (client.connected()) {
    client.publish(topic_trigger, "TRIGGER");
  }
  Serial.println("รถหยุดนิ่งครบ 90 วิ -> สั่งกล้องตรวจสอบผ่าน MQTT รอผลยืนยัน...");
}

// ===== ส่ง TRIGGER ซ้ำ + เช็ค fail-safe timeout ระหว่างรอผลจากกล้อง (คอม) =====
void checkCamTimeout() {
  if (awaitingConfirm && (millis() - lastTriggerResend >= TRIGGER_RESEND_INTERVAL)) {
    lastTriggerResend = millis();
    if (client.connected()) {
      client.publish(topic_trigger, "TRIGGER");
    }
    Serial.println("ยังไม่ได้รับคำตอบจากกล้อง -> ส่ง TRIGGER ซ้ำ");
  }

  // Fail-safe: ถ้ารอเกินเวลาที่กำหนดแล้วคอมยังไม่ตอบกลับ (เช่น MQTT/เน็ตหลุด) ให้แจ้งเตือนเองไปก่อน
  if (awaitingConfirm && (millis() - camRequestTime >= CAM_CONFIRM_TIMEOUT)) {
    Serial.println("กล้อง/เครือข่ายไม่ตอบกลับภายในเวลาที่กำหนด -> แจ้งเตือนเองแบบ fail-safe");
    handleCamResult(true, true);
  }
}

// ===== รับผลยืนยันจากกล้อง (ผ่าน MQTT topic_confirm ใน mqttCallback) =====
// personConfirmed: กล้องเจอคนหรือไม่ / failSafe: true เฉพาะกรณี timeout ไม่มีคำตอบจากคอมจริงๆ
void handleCamResult(bool personConfirmed, bool failSafe) {
  awaitingConfirm = false;

  if (personConfirmed) {
    alarmActive = true;

    if (failSafe) {
      // เครือข่าย/คอมไม่ตอบกลับ -> ESP32 แจ้งเตือนเองแบบสำรอง (ข้อความล้วน ไม่มีรูป เพราะ ESP32 ไม่มีภาพ)
      String msg = "⚠️อันตราย พบการเคลื่อนไหวบนรถ! (fail-safe แจ้งเตือนสำรอง)\n";
      msg += "📞 ติดต่อ: 0923164791\n";
      msg += getGpsText();

      sendLineMessage(msg);
      Serial.println("Fail-safe: กล้อง/เครือข่ายไม่ตอบกลับ -> ส่งแจ้งเตือน LINE สำรองแล้ว");
    } else {
      // กรณีปกติ: คอม (dashboard_app.py) เป็นคนส่งรูป+ข้อความ+GPS เข้า LINE เองแล้ว
      // ฝั่ง ESP32 แค่เปิดสัญญาณเตือน (relay+buzzer) ไม่ต้องส่งซ้ำ
      Serial.println("กล้องยืนยันพบคนจริง -> เปิดสัญญาณเตือน (คอมส่งรูป+ข้อความเข้า LINE เองแล้ว)");
    }
  } else {
    Serial.println("กล้องไม่พบคน -> ไม่ต้องแจ้งเตือน");
  }
}

String getGpsText() {
  if (gps.location.isValid()) {
    String latStr = String(gps.location.lat(), 6);
    String lngStr = String(gps.location.lng(), 6);
    return "📍 พิกัดตำแหน่งรถตอนนี้:\nhttps://maps.google.com/?q=" + latStr + "," + lngStr;
  } else {
    return "📍 พิกัดตำแหน่งรถ: (กำลังค้นหาสัญญาณดาวเทียม...)";
  }
}

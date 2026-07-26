#define BUZZ_FREQ      4000  // ความถี่ 4 kHz
#define BUZZ_BEEP_MS   150   // ความยาวแต่ละ "ตี้ด"
#define BUZZ_GAP_MS    100   // ช่องว่างระหว่าง ตี้ด ตี้ด
#define BUZZ_PAUSE_MS  600   // หยุดยาวระหว่างรอบ

// state: 0=beep1, 1=gap, 2=beep2, 3=pause
int  buzzerStep     = 0;
unsigned long buzzerStepTime = 0;
bool buzzerActive   = false; // buzzer กำลังดังอยู่หรือเปล่า

void stopBuzzer() {
  buzzerActive = false;
  buzzerStep   = 0;
  noTone(BUZZER_PIN);
  digitalWrite(BUZZER_PIN, LOW);
}

// ===== เสียงไซเรนตามสถานะ alarmActive (เปิดเมื่อกล้องยืนยันพบคน หรือ fail-safe) =====
void updateBuzzer() {
  unsigned long now = millis();

  // --- alarmActive ปิดแล้ว (รถขยับ/ระบบถูกสั่งปิด) -> หยุดเสียงทันที ---
  if (buzzerActive && !alarmActive) {
    stopBuzzer();
    Serial.println("BUZZER OFF: alarm ปิดแล้ว");
    return;
  }

  // --- alarmActive เปิดใหม่ -> เริ่มเสียงทันที ไม่มีดีเลย์ (ยืนยันแล้วว่าเป็นเหตุการณ์จริง) ---
  if (alarmActive && !buzzerActive) {
    buzzerActive   = true;
    buzzerStep     = 0;
    buzzerStepTime = now;
    Serial.println("BUZZER ON");
  }

  if (!buzzerActive) return;

  // --- Buzzer pattern: ตี้ด ตี้ด ... ตี้ด ตี้ด ... ---
  switch (buzzerStep) {
    case 0:  // ตี้ด แรก
      tone(BUZZER_PIN, BUZZ_FREQ);
      if (now - buzzerStepTime >= BUZZ_BEEP_MS) {
        noTone(BUZZER_PIN);
        digitalWrite(BUZZER_PIN, LOW);
        buzzerStep = 1; buzzerStepTime = now;
      }
      break;

    case 1:  // ช่องว่างสั้น
      if (now - buzzerStepTime >= BUZZ_GAP_MS) {
        buzzerStep = 2; buzzerStepTime = now;
      }
      break;

    case 2:  // ตี้ด ที่สอง
      tone(BUZZER_PIN, BUZZ_FREQ);
      if (now - buzzerStepTime >= BUZZ_BEEP_MS) {
        noTone(BUZZER_PIN);
        digitalWrite(BUZZER_PIN, LOW);
        buzzerStep = 3; buzzerStepTime = now;
      }
      break;

    case 3:  // หยุดยาวก่อนวนรอบ
      if (now - buzzerStepTime >= BUZZ_PAUSE_MS) {
        buzzerStep = 0; buzzerStepTime = now;
      }
      break;
  }
}

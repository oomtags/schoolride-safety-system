// แต่ละบรรทัดสูง 11px, มีเนื้อหา 10 แถว รวม 110px → เลื่อนได้ 46px บน OLED 64px
#define LINE_H       11
#define TOTAL_ROWS   10

void showPeopleOnLCD() {
  float speed = gps.speed.isValid() ? gps.speed.kmph() : -1;

  // อ่าน Knob GPIO 35 แล้วแปลงเป็น pixel offset สำหรับ scroll
  int knobRaw   = analogRead(KNOB_PIN);
  int totalH    = TOTAL_ROWS * LINE_H;               // 99 px
  int maxScroll = totalH - SCREEN_HEIGHT;             // 35 px
  int scrollPx  = map(knobRaw, 0, 4095, 0, maxScroll);

  OLED.clearDisplay();
  OLED.setTextColor(SSD1306_WHITE);
  OLED.setTextSize(1);

  int y;

  // แถว 0 — สถานะรถหยุดนิ่ง / นับถอยหลัง
  y = 0 * LINE_H - scrollPx;
  if (y > -8 && y < SCREEN_HEIGHT) {
    OLED.setCursor(0, y);
    OLED.print("STOP   : ");
    if (checkEnabled) {
      OLED.print("ARMED   ");
    } else if (stateStartTime > 0 && speed <= SPEED_LIMIT) {
      unsigned long elapsed = millis() - stateStartTime;
      if (elapsed < LOCK_DELAY_TIME) {
        unsigned long rem = (LOCK_DELAY_TIME - elapsed) / 1000;
        OLED.print(rem);
        OLED.print("s left ");
      } else {
        OLED.print("STARTING");
      }
    } else {
      OLED.print("MOVING  ");
    }
  }

  // แถว 1 — สถานะกล้อง (รอ/ยืนยันแล้ว)
  y = 1 * LINE_H - scrollPx;
  if (y > -8 && y < SCREEN_HEIGHT) {
    OLED.setCursor(0, y);
    OLED.print("CAM    : ");
    if (awaitingConfirm) {
      OLED.print("CHECKING");
    } else if (alarmActive) {
      OLED.print("CONFIRM!");
    } else {
      OLED.print("IDLE    ");
    }
  }

  // แถว 2 — สัญญาณเตือน (relay+buzzer)
  y = 2 * LINE_H - scrollPx;
  if (y > -8 && y < SCREEN_HEIGHT) {
    OLED.setCursor(0, y);
    OLED.print("ALARM  : ");
    OLED.print(alarmActive ? "ON! " : "off ");
  }

  // แถว 3 — MQTT
  y = 3 * LINE_H - scrollPx;
  if (y > -8 && y < SCREEN_HEIGHT) {
    OLED.setCursor(0, y);
    OLED.print("MQTT   : ");
    OLED.print(client.connected() ? "CONNECTED" : "DISCONN. ");
  }

  // แถว 4 — WiFi
  y = 4 * LINE_H - scrollPx;
  if (y > -8 && y < SCREEN_HEIGHT) {
    OLED.setCursor(0, y);
    OLED.print("WiFi   : ");
    OLED.print(WiFi.status() == WL_CONNECTED ? "CONNECTED" : "DISCONN. ");
  }

  // แถว 5 — ความเร็ว GPS
  y = 5 * LINE_H - scrollPx;
  if (y > -8 && y < SCREEN_HEIGHT) {
    OLED.setCursor(0, y);
    OLED.print("Speed  : ");
    if (speed >= 0) {
      OLED.print(speed, 1);
      OLED.print(" km/h");
    } else {
      OLED.print("--.- km/h");
    }
  }

  // แถว 6 — พิกัด GPS
  y = 6 * LINE_H - scrollPx;
  if (y > -8 && y < SCREEN_HEIGHT) {
    OLED.setCursor(0, y);
    OLED.print("GPS    : ");
    if (gps.location.isValid()) {
      OLED.print(gps.location.lat(), 4);
      OLED.print(",");
      OLED.print(gps.location.lng(), 4);
    } else {
      OLED.print("No Fix");
    }
  }

  // แถว 7 — สถานะระบบ
  y = 7 * LINE_H - scrollPx;
  if (y > -8 && y < SCREEN_HEIGHT) {
    OLED.setCursor(0, y);
    OLED.print("SYS    : ");
    OLED.print(systemEnabled ? "ON      " : "OFF     ");
  }

  // แถว 8 — Relay
  y = 8 * LINE_H - scrollPx;
  if (y > -8 && y < SCREEN_HEIGHT) {
    OLED.setCursor(0, y);
    OLED.print("RELAY  : ");
    OLED.print(relayActive ? "ON " : "OFF");
  }

  // แถว 9 — แรงดันแบตเตอรี่
  y = 9 * LINE_H - scrollPx;
  if (y > -8 && y < SCREEN_HEIGHT) {
    OLED.setCursor(0, y);
    OLED.print("BAT    : ");
    OLED.print(batteryVoltage, 2);
    OLED.print("V");
  }

  // แถบ scroll indicator ขอบขวา
  if (maxScroll > 0) {
    int barH = max(5, (SCREEN_HEIGHT * SCREEN_HEIGHT) / totalH); // สัดส่วน
    int barY = (scrollPx * (SCREEN_HEIGHT - barH)) / maxScroll;
    OLED.drawFastVLine(127, barY, barH, SSD1306_WHITE);
  }

  OLED.display();

  // ส่ง MQTT ความเร็วและสถานะ
  if (client.connected()) {
    char buf[16];
    if (speed >= 0) {
      dtostrf(speed, 4, 1, buf);
      client.publish(topic_speed, buf);
    } else {
      client.publish(topic_speed, "0.0");
    }
    client.publish(topic_status, systemEnabled ? "ON" : "OFF");

    char vbuf[16];
    dtostrf(batteryVoltage, 4, 2, vbuf);
    client.publish(topic_voltage, vbuf);
  }
}

// ===== อ่านค่าแรงดันแบตเตอรี่จากโมดูล Voltage Sensor (VCC<25V) ที่ GPIO34 =====
void readBatteryVoltage() {
  int adcRaw = analogRead(VOLTAGE_PIN);          // 0-4095 (12-bit)
  float adcVoltage = (adcRaw / 4095.0) * 3.3;    // แปลงเป็นแรงดันจริงที่ขา ESP32 (0-3.3V)
  batteryVoltage = adcVoltage * VOLTAGE_DIVIDER_RATIO; // คูณกลับด้วยอัตราส่วนตัวหารของโมดูล
}

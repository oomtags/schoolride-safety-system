#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <TinyGPS++.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <PubSubClient.h>

// ประกาศฟังก์ชันข้ามไฟล์เพื่อให้คอมไพเลอร์รู้จัก
void reconnectMQTT();
void mqttCallback(char* topic, byte* payload, unsigned int length);
void showPeopleOnLCD();
void armCameraCheck();
void checkCamTimeout();
String getGpsText();
void updateBuzzer();
void handleCamResult(bool personConfirmed, bool failSafe);
void handleClearSignal();
void readBatteryVoltage();
void publishRelayState();
void publishCameraState();
void publishGps();
// หมายเหตุ: ไม่มีเซ็นเซอร์ PIR/IR/DIG และไม่มี Raspberry Pi ผ่าน UART อีกต่อไป
// "รถหยุดนิ่ง 90 วิ" (จาก GPS speed) คือตัวสั่งให้กล้อง (dashboard_app.py บนคอม) เริ่มตรวจสอบ
// ผ่าน MQTT (topic_trigger / topic_confirm) แทน — คอมเป็นคนส่งรูป+ข้อความเข้า LINE เองตอนยืนยันพบคน
// ESP32 จะส่ง LINE เองเฉพาะกรณี fail-safe (คอม/เครือข่ายไม่ตอบกลับภายในเวลาที่กำหนด) เท่านั้น

TinyGPSPlus gps;
HardwareSerial gpsSerial(2);

#define RXD2 16
#define TXD2 17
#define GPS_BAUD 9600

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 OLED(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

const char* ssid     = "RAIL_LOTUS_2.4GHz";
const char* password = "78965456321";

String lineToken = "JzESJSSG235li5X3IbkOgx9swZlt2jeUfRqzbKz94STnZMg56NVVFkbYbVXy+BJ6G77UHTH1gAHg5q/3rYuQlKLAS6Tea4X1HOc9G6ZUpDKDsDmybJDeFBlIrmU+AzegVd7xlDFhOigrJ1dXvjyc9gdB04t89/1O/w1cDnyilFU=";
String userId    = "C8fb4e80947892425468f0d142c0aa891";

const char* mqtt_server  = "rail.kls.ac.th";
const int   mqtt_port    = 1883;

const char* topic_cmd     = "eaip-kls-project-dek-d-cmd01";  //รับคำสั่งเปิด-ปิดระบบจากภายนอก (subscribe อย่างเดียว ESP ไม่ publish เข้าตัวนี้)
const char* topic_speed   = "eaip-kls-project-dek-d/speed01"; //ความเร็ว km/h
const char* topic_status  = "eaip-kls-project-dek-d/status01";
const char* topic_voltage = "eaip-kls-project-dek-d/voltage01"; // แรงดันแบตเตอรี่
const char* topic_relay   = "eaip-kls-project-dek-d/relay01"; // สถานะ relay จริง (ON เมื่อสัญญาณเตือนทำงานอยู่)
const char* topic_camera  = "eaip-kls-project-dek-d/camera01"; // ON ตอนกำลังรอกล้อง (คอม) ยืนยันผล (awaitingConfirm)
const char* topic_trigger = "eaip-kls-project-dek-d/trigger01"; // ESP32 -> คอม: สั่งเริ่มตรวจสอบด้วยกล้อง
const char* topic_confirm = "eaip-kls-project-dek-d/confirm01"; // คอม -> ESP32: ผลตรวจสอบ (CONFIRM / NOPERSON)
const char* topic_gps     = "eaip-kls-project-dek-d/gps01"; // พิกัด GPS "lat,lng" ส่งทุก 10 วิ ให้ dashboard แสดง

// ===== เซนเซอร์วัดแรงดันแบตเตอรี่ (Voltage Sensor VCC<25V) =====
#define VOLTAGE_PIN 34
#define VOLTAGE_DIVIDER_RATIO 5.0  // อัตราส่วนตัวหารของโมดูล (R1=30k, R2=7.5k) ปรับตามโมดูลจริงถ้าค่าอ่านไม่ตรง
float batteryVoltage = 0.0;//สถานะระบบ

WiFiClient   espClient;
PubSubClient client(espClient);

bool systemEnabled = true;

#define RELAY_PIN  19
#define KNOB_PIN   35
#define BUZZER_PIN 18

bool alarmActive       = false; // สัญญาณเตือนจริง (relay+buzzer) เปิดอยู่หรือไม่
bool triggeredThisCycle = false; // กันไม่ให้ส่ง TRIGGER ซ้ำหลายรอบระหว่างที่รถยังหยุดนิ่งต่อเนื่องรอบเดียวกัน

// ===== ตัวแปรรอผลยืนยันจากกล้อง (dashboard_app.py บนคอม ผ่าน MQTT) =====
bool awaitingConfirm  = false;
unsigned long camRequestTime = 0;
#define CAM_CONFIRM_TIMEOUT 55000UL // ถ้าคอมไม่ตอบกลับภายในเวลานี้ ให้แจ้งเตือนเองแบบ fail-safe

// ส่ง TRIGGER ซ้ำเป็นระยะระหว่างรอคอมตอบกลับ กันกรณี MQTT หลุด/ข้อความหาย
unsigned long lastTriggerResend = 0;
#define TRIGGER_RESEND_INTERVAL 3000UL

#define SPEED_LIMIT      10.0       //ความเร็วรถ ถ้ามากกว่า 10 ถึงจะรี
#define LCD_INTERVAL     1000
#define RELAY_ON_DURATION 60000UL  // เวลาสูงสุดที่ปล่อยให้สัญญาณเตือน (relay) ค้างได้ กันบอร์ดไหม้

// ตัวแปรคุมการนับถอยหลัง "รถหยุดนิ่ง" ก่อนเริ่มตรวจสอบด้วยกล้อง
#define LOCK_DELAY_TIME  90000UL   // 1.5 นาที = 90 * 1000 มิลลิวินาที
unsigned long lastCountdownLog = 0; // เอาไว้เก็บเวลาเพื่อไม่ให้ Serial พิมพ์สแปมถี่เกินไป

unsigned long lastLcdUpdate    = 0;
unsigned long stateStartTime   = 0;
unsigned long relayActivatedTime = 0;
bool relayActive = false;

unsigned long lastGpsPublish = 0;
#define GPS_PUBLISH_INTERVAL 10000UL // ส่งพิกัด GPS เข้า MQTT ทุก 10 วิ ให้ dashboard แสดงผล

bool checkEnabled   = false; // true เมื่อรถหยุดนิ่งครบ 90 วิแล้ว (armed พร้อมสั่งกล้องตรวจสอบ)

// ===== ส่งสถานะ relay จริงออก MQTT เฉพาะตอนที่ค่าเปลี่ยน (กันสแปม publish ทุก loop) =====
bool lastPublishedRelay = false;
bool relayPublishInit   = false;

// ===== ส่งสถานะกล้อง (awaitingConfirm) ออก MQTT เฉพาะตอนที่ค่าเปลี่ยน =====
bool lastPublishedCamera = false;
bool cameraPublishInit   = false;

unsigned long lastMqttAttempt = 0;
#define MQTT_RETRY_INTERVAL 5000

unsigned long lastWiFiCheck = 0;
#define WIFI_CHECK_INTERVAL 20000  // เดิม 10000 -- เพิ่มเวลาให้แต่ละครั้งพอสำหรับ handshake+DHCP ก่อนลองใหม่

// ===== กันสัญญาณ WiFi กระตุกสั้นๆ ไม่ให้ reconnect ถี่เกินไป =====
unsigned long wifiLostSince = 0;
bool wifiLostTracking = false;
#define WIFI_DISCONNECT_GRACE 10000UL // ต้องหลุดต่อเนื่องเกินนี้ก่อน ถึงจะเริ่ม reconnect จริง

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);

  gpsSerial.begin(GPS_BAUD, SERIAL_8N1, RXD2, TXD2);

  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  pinMode(VOLTAGE_PIN, INPUT);
  analogSetPinAttenuation(VOLTAGE_PIN, ADC_11db); // ให้อ่านได้เต็มช่วง 0-3.3V

  if (!OLED.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED not found");
  }
  OLED.clearDisplay();
  OLED.setTextColor(SSD1306_WHITE);
  OLED.setTextSize(1);
  OLED.setCursor(0, 20);
  OLED.println("Connecting WiFi...");
  OLED.display();

  WiFi.begin(ssid, password);
  Serial.print("Connecting WiFi");
  unsigned long wifiStart = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - wifiStart < 10000) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected!");
    OLED.clearDisplay();
    OLED.setCursor(0, 20);
    OLED.println("WiFi connected!");
    OLED.display();
  } else {
    Serial.println("\nWiFi FAILED! Start without WiFi");
    OLED.clearDisplay();
    OLED.setCursor(0, 20);
    OLED.println("WiFi FAILED!");
    OLED.display();
  }

  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(mqttCallback);
}

void loop() {
  unsigned long now = millis();

  // ===== WiFi Reconnect ระบบตรวจอินเทอร์เน็ต =====
  if (WiFi.status() != WL_CONNECTED) {
    if (!wifiLostTracking) {
      wifiLostTracking = true;
      wifiLostSince = now;
    }

    // ต้องหลุดต่อเนื่องเกิน WIFI_DISCONNECT_GRACE ก่อน ถึงจะเริ่ม reconnect จริง (กันสัญญาณกระตุกแวบเดียว)
    if (now - wifiLostSince >= WIFI_DISCONNECT_GRACE) {
      if (now - lastWiFiCheck >= WIFI_CHECK_INTERVAL) {
        lastWiFiCheck = now;
        Serial.println("WiFi Disconnected! Reconnecting...");
        // หมายเหตุ: ห้ามเรียก WiFi.disconnect() ก่อน begin() ตรงนี้ เพราะถ้า begin() รอบก่อนยังเชื่อมต่อค้างอยู่
        // (handshake/DHCP ยังไม่เสร็จ) จะโดน esp-idf ปฏิเสธด้วย "sta is connecting, cannot set config"
        // แล้ววนตัดการเชื่อมต่อที่ใกล้จะสำเร็จซ้ำไปเรื่อยๆ จนไม่มีทางต่อติดเลย
        WiFi.begin(ssid, password);
      }
    }
  } else {
    wifiLostTracking = false; // กลับมาเชื่อมต่อแล้ว รีเซ็ตตัวจับเวลา
  }

  // ===== Buzzer state machine (เรียกทุก loop ไม่มี interval) =====
  updateBuzzer();

  // ===== เช็ค resend/timeout ระหว่างรอกล้อง (คอม) ยืนยันผล ทุก loop (ไม่มี interval เพื่อไม่ให้พลาด) =====
  checkCamTimeout();

  // ===== อัปเดตข้อมูลบนหน้าจอ OLED ทุก 1 วินาที =====
  if (now - lastLcdUpdate >= LCD_INTERVAL) {
    lastLcdUpdate = now;
    readBatteryVoltage();
    showPeopleOnLCD();
  }

  // ===== ทำงานร่วมกับระบบ MQTT =====
  if (WiFi.status() == WL_CONNECTED) {
    if (!client.connected()) {
      if (now - lastMqttAttempt >= MQTT_RETRY_INTERVAL) {
        lastMqttAttempt = now;
        reconnectMQTT();
      }
    } else {
      client.loop();
    }
  }

  // ===== ถ้าระบบโดนสั่งปิดระยะไกลจาก Dashboard =====
  if (!systemEnabled) {
    alarmActive = false;
    digitalWrite(RELAY_PIN, LOW);
    relayActive = false;
    publishRelayState();
    publishCameraState();
    return;
  }

  // ===== ดึงข้อมูลสัญญาณดิบจากบอร์ด GPS เข้า TinyGPS++ แบบเรียลไทม์ =====
  while (gpsSerial.available() > 0) {
    gps.encode(gpsSerial.read());
  }

  bool gpsSpeedValid = gps.speed.isValid();
  float speed = gpsSpeedValid ? gps.speed.kmph() : -1;

  // ===== ปิดสัญญาณเตือน (relay+buzzer) เมื่อครบกำหนดเวลาป้องกันบอร์ดไหม้ =====
  // (fail-safe สำรอง เผื่อกล้อง/คอมไม่ส่ง CLEAR กลับมาด้วยเหตุผลใดก็ตาม ไม่ให้ปลุกดังค้างตลอดไป)
  if (relayActive && (now - relayActivatedTime >= RELAY_ON_DURATION)) {
    digitalWrite(RELAY_PIN, LOW);
    relayActive = false;
    alarmActive = false;
    Serial.println("Relay Timeout: OFF (fail-safe ปิด alarm ด้วย เผื่อไม่ได้รับ CLEAR จากกล้อง)");
  }

  // ===== การทำงานตามเงื่อนไขความเร็วและการรีเซ็ตระบบ =====
  if (gpsSpeedValid && speed > SPEED_LIMIT) {
    // มี GPS ยืนยันชัดเจนว่ารถกำลังวิ่งเร็วเกิน 10 กม./ชม. -> ปลอดภัยแล้ว รีเซ็ตทุกอย่างรวม alarm
    checkEnabled     = false;
    stateStartTime   = 0;
    triggeredThisCycle = false;
    awaitingConfirm  = false;
    alarmActive      = false;
    if (relayActive) {
      digitalWrite(RELAY_PIN, LOW);
      relayActive = false;
    }
  } else if (!gpsSpeedValid) {
    // ยังไม่มีสัญญาณ GPS (เช่น เพิ่งเปิดเครื่อง ยังล็อกดาวเทียมไม่ได้) -> ไม่รู้ว่ารถหยุดจริงหรือไม่
    // จึงยังไม่เริ่ม/นับเวลาหยุดนิ่งใหม่ แต่ "ไม่แตะ" alarmActive/relay ที่อาจกำลังทำงานอยู่จากรอบก่อนหน้า
    // (กันไม่ให้ GPS หลุดสัญญาณชั่วคราวไปเผลอตัดสัญญาณเตือนที่ยืนยันพบคนแล้วจริงๆ)
    checkEnabled       = false;
    stateStartTime     = 0;
    triggeredThisCycle = false;

    if (now - lastCountdownLog >= 5000) {
      lastCountdownLog = now;
      Serial.println("ยังไม่มีสัญญาณ GPS (รอล็อกดาวเทียม) -> ยังไม่เริ่มนับเวลารถหยุดนิ่ง");
    }
  } else {
    // มี GPS ยืนยันว่าความเร็วต่ำกว่าหรือเท่ากับ 10 กม./ชม. จริง -> นับเวลาหยุดนิ่ง
    if (stateStartTime == 0) {
      stateStartTime = now;
    }

    // เช็คว่าหยุดนิ่งต่อเนื่องครบ 90 วินาทีหรือยัง
    if (now - stateStartTime >= LOCK_DELAY_TIME) {
      checkEnabled = true; // ครบ 90 วิ -> พร้อมสั่งกล้องตรวจสอบ
    } else {
      checkEnabled = false;

      // พิมพ์ข้อความแจ้งเตือนสถานะบน Serial Monitor ทุกๆ 5 วินาที
      if (now - lastCountdownLog >= 5000) {
        lastCountdownLog = now;
        unsigned long remainingSec = (LOCK_DELAY_TIME - (now - stateStartTime)) / 1000;
        Serial.print("รถหยุดนิ่ง: กำลังนับถอยหลังตรวจสอบด้วยกล้องในอีก ");
        Serial.print(remainingSec);
        Serial.println(" วินาที...");
      }
    }
  }

  // ===== รถหยุดนิ่งครบ 90 วิแล้ว และยังไม่เคยสั่งกล้องตรวจสอบในรอบนี้ -> สั่งเดี๋ยวนี้ =====
  if (checkEnabled && !triggeredThisCycle) {
    armCameraCheck();
  }

  // ===== เปิด/ปิด relay ตามสถานะสัญญาณเตือน (alarmActive) =====
  if (alarmActive && !relayActive) {
    digitalWrite(RELAY_PIN, HIGH);
    relayActive = true;
    relayActivatedTime = now;
  } else if (!alarmActive && relayActive) {
    digitalWrite(RELAY_PIN, LOW);
    relayActive = false;
  }

  // ===== ส่งพิกัด GPS เข้า MQTT ทุก 10 วิ ให้ dashboard แสดงตำแหน่งรถ =====
  if (now - lastGpsPublish >= GPS_PUBLISH_INTERVAL) {
    lastGpsPublish = now;
    publishGps();
  }

  // ===== ส่งสถานะ relay / กล้อง ล่าสุดออก MQTT ถ้ามีการเปลี่ยนแปลงในรอบ loop นี้ =====
  publishRelayState();
  publishCameraState();
}

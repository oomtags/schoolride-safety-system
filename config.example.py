"""
คัดลอกไฟล์นี้เป็น config.py แล้วใส่ค่าจริงของคุณ (config.py ถูก .gitignore ไว้แล้ว
จะได้ไม่หลุดเข้า git โดยไม่ตั้งใจ เพราะมี LINE token อยู่ในนั้น)
"""

# ===== LINE Messaging API (channel access token + กลุ่ม/ผู้รับปลายทาง) =====
LINE_TOKEN = "ใส่ Channel Access Token ของคุณที่นี่"
LINE_USER_ID = "ใส่ userId/groupId ปลายทางที่นี่"

# ===== เบอร์ติดต่อที่จะแสดงในข้อความแจ้งเตือน LINE =====
CONTACT_PHONE = "0923164791"

# ===== MQTT broker เดียวกับที่ ESP32 ใช้ =====
MQTT_BROKER = "rail.kls.ac.th"
MQTT_PORT = 1883

MQTT_TOPIC_TRIGGER = "eaip-kls-project-dek-d/trigger01"
MQTT_TOPIC_CONFIRM = "eaip-kls-project-dek-d/confirm01"
MQTT_TOPIC_GPS = "eaip-kls-project-dek-d/gps01"

# ===== รหัสผ่านขั้นต่ำก่อนเปิดหน้าเว็บให้คนนอกดู (HTTP Basic Auth) =====
# เปลี่ยนก่อนเปิดให้คนนอกเข้าถึงจริงเสมอ! ไม่งั้นใครก็เดารหัสนี้ได้จากไฟล์ตัวอย่างที่ commit ไว้
DASHBOARD_USERNAME = "admin"
DASHBOARD_PASSWORD = "เปลี่ยนรหัสผ่านนี้ก่อนใช้งานจริง"

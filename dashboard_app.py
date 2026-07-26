"""
SchoolRide Intelligent Safety System — Web Dashboard
=====================================================
ระบบอัจฉริยะสำหรับเฝ้าระวังและแจ้งเตือนเด็กตกค้างบนรถรับส่งนักเรียน

ดึงภาพจากกล้องเดียวกับ multi_camera_ai_v2.py (จับหน้าต่าง BlueStacks + ตรวจจับคนด้วย YOLO)
แล้วสตรีมออกเป็นหน้าเว็บ Dashboard สวยๆ ดูผ่าน browser ได้ (เปิดจากเครื่องอื่นใน LAN เดียวกันก็ได้)

การเชื่อมต่อกับ ESP32 (บนรถ):
    ESP32 ตรวจจับว่ารถหยุดนิ่งครบ 1.5 นาที (จาก GPS speed) แล้ว publish MQTT "TRIGGER"
    มาที่นี่ (ผ่าน broker rail.kls.ac.th ตัวเดียวกับที่ ESP32 ใช้อยู่แล้ว) — โปรแกรมนี้จะเริ่ม
    สะสมเวลาที่เจอคนต่อกล้อง (หยุด/รอไว้ถ้ากระพริบ ไม่รีเซ็ตเป็นศูนย์) พอกล้องไหนสะสมครบ 3 วิ
    ถือว่ายืนยันพบคน -> publish "CONFIRM" กลับไปหา ESP32 (เพื่อเปิด relay/buzzer) พร้อมส่งรูป+
    ข้อความ+พิกัด GPS เข้ากลุ่ม LINE เอง (ผ่าน Cloudflare Tunnel เพื่อให้ LINE ดึงรูปจาก URL
    สาธารณะได้ แม้เครื่องนี้จะไม่มี public IP) — หลังจากนั้นจะเฝ้าดูต่อว่าคนออกจากกล้องหมดหรือยัง
    พอไม่เห็นคนเลยสักกล้องต่อเนื่องครบ CLEAR_ABSENCE_SECONDS จะ publish "CLEAR" ให้ ESP32
    ปิดสัญญาณเตือน (แทนที่จะรอให้รถขยับก่อนถึงจะปิดได้แบบเดิม)

วิธีติดตั้งเพิ่ม (นอกจากของ multi_camera_ai_v2.py):
    pip install flask paho-mqtt requests

วิธีใช้:
    1. คัดลอก config.example.py เป็น config.py แล้วใส่ค่า LINE token ของจริง
    2. python dashboard_app.py
    3. เปิดเบราว์เซอร์ไปที่ http://localhost:5000
"""

import hmac
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

import cv2
import paho.mqtt.client as mqtt
import requests
import win32gui
from flask import Flask, Response, jsonify, render_template, request, send_from_directory

import config
from multi_camera_ai_v2 import (
    capture_window,
    crop_top_bottom,
    ensure_config,
    find_window,
)

PERSON_CLASS_ID = 0
INFERENCE_SIZE = 480
CROP_TOP_RATIO = 0.17
CROP_BOTTOM_RATIO = 0.35
JPEG_QUALITY = 80

# ชื่อกล้องที่แสดงบนหน้าเว็บ (key ต้องตรงกับชื่อกล้องใน windows_config.json)
CAM_DISPLAY_NAMES = {
    "cam1": "กล้องแถวหน้า ของรถ",
    "cam2": "กล้องแถวกลาง ของรถ",
    "cam3": "กล้องแถวท้าย ของรถ",
}

# ถ้าตรวจพบคนต่อเนื่องเกินกี่วินาที ถึงจะขึ้น badge "แจ้งเตือน" บนหน้าเว็บ (แค่ตัวโชว์ผล ไม่เกี่ยวกับ ESP32)
ALERT_AFTER_SECONDS = 8

# ===== ค่าคุมการยืนยัน "พบคน" ตอนกล้องถูก ESP32 สั่งให้ตรวจสอบ (armed) =====
ARMED_CONFIRM_SECONDS = 3.0   # กล้องไหนสะสมเวลาที่เจอคนครบเท่านี้ ถือว่ายืนยัน
ARMED_WINDOW_SECONDS = 45.0   # ถ้าเกินเวลานี้แล้วไม่มีกล้องไหนยืนยันได้ ให้ตอบ NOPERSON กลับไป
                              # (สั้นกว่า timeout fail-safe ฝั่ง ESP32 ที่ ~55 วิ เพื่อให้ตอบทันก่อน)

SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
CLOUDFLARED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloudflared.exe")

TH_TZ = ZoneInfo("Asia/Bangkok")
TH_MONTHS = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]

app = Flask(__name__)


# ===== ป้องกันขั้นต่ำก่อนเปิดให้คนนอกดู (HTTP Basic Auth) =====
# หน้านี้โชว์วิดีโอสดในรถ + ตำแหน่ง GPS ของเด็กนักเรียน ห้ามเปิดโล่งให้ใครก็เข้าถึงได้
def _check_auth(username, password):
    return (
        hmac.compare_digest(username, config.DASHBOARD_USERNAME)
        and hmac.compare_digest(password, config.DASHBOARD_PASSWORD)
    )


def requires_auth(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        if not auth or not _check_auth(auth.username or "", auth.password or ""):
            return Response(
                "ต้องใส่ชื่อผู้ใช้/รหัสผ่านก่อนถึงจะดูข้อมูลนี้ได้",
                401,
                {"WWW-Authenticate": 'Basic realm="SchoolRide Dashboard"'},
            )
        return view_func(*args, **kwargs)
    return wrapped


state_lock = threading.Lock()
camera_state = {}  # cam_name -> dict(jpeg, person_count, updated_at, online, first_detected_at, alert)
latest_gps = {"lat": None, "lng": None, "updated_at": 0.0}

# ===== สถานะ "armed" (กำลังรอกล้องยืนยันตามคำสั่ง TRIGGER จาก ESP32) =====
armed_lock = threading.Lock()
armed = False
armed_deadline = 0.0
armed_accum = {}  # cam_name -> วินาทีสะสมที่เจอคน ระหว่างช่วง armed นี้

# ===== สถานะหลังยืนยันพบคนแล้ว: รอจนกว่าจะไม่เห็นคนเลยสักกล้อง ถึงจะสั่งปิด alarm ที่ ESP32 =====
CLEAR_ABSENCE_SECONDS = 2.0  # ต้องไม่พบคนต่อเนื่องกี่วิ ถึงจะถือว่า "ออกจากกล้องไปแล้ว" (กันกระพริบเดี๋ยวเจอเดี๋ยวไม่เจอ)
awaiting_clear = False
clear_absence_accum = 0.0

mqtt_client = None
public_base_url = None  # ตั้งค่าเมื่อ Cloudflare Tunnel รายงาน URL สาธารณะกลับมา


def thai_now():
    """เวลาจริงของประเทศไทย (Asia/Bangkok) ไม่ใช่นาฬิกาเครื่องผู้ใช้ที่อาจตั้งผิด/คนละโซนเวลา"""
    now = datetime.now(TH_TZ)
    return {
        "date": f"{now.day} {TH_MONTHS[now.month - 1]} {now.year + 543}",
        "time": now.strftime("%H:%M:%S"),
    }


# ============================================================
# MQTT: รับ TRIGGER/GPS จาก ESP32, ส่ง CONFIRM/NOPERSON กลับไป
# ============================================================

def _on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] เชื่อมต่อ {config.MQTT_BROKER} สำเร็จ")
        client.subscribe(config.MQTT_TOPIC_TRIGGER)
        client.subscribe(config.MQTT_TOPIC_GPS)
    else:
        print(f"[MQTT] เชื่อมต่อไม่สำเร็จ rc={rc}")


def _on_mqtt_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8", errors="ignore").strip()

    if msg.topic == config.MQTT_TOPIC_TRIGGER:
        arm_camera_check()
    elif msg.topic == config.MQTT_TOPIC_GPS:
        _update_gps(payload)


def _update_gps(payload):
    try:
        lat_str, lng_str = payload.split(",")
        with state_lock:
            latest_gps["lat"] = float(lat_str)
            latest_gps["lng"] = float(lng_str)
            latest_gps["updated_at"] = time.time()
    except ValueError:
        print(f"[MQTT] พิกัด GPS รูปแบบไม่ถูกต้อง: {payload!r}")


def arm_camera_check():
    """ESP32 สั่งมาว่ารถหยุดนิ่งครบ 90 วิแล้ว -> เริ่มสะสมเวลาที่เจอคนต่อกล้องใหม่"""
    global armed, armed_deadline
    with armed_lock:
        was_armed = armed
        armed = True
        armed_deadline = time.time() + ARMED_WINDOW_SECONDS
        for cam_name in camera_state:
            armed_accum[cam_name] = 0.0
    if not was_armed:
        print("[ARM] ได้รับ TRIGGER จาก ESP32 -> เริ่มตรวจสอบด้วยกล้อง (สะสมครบ 3 วิ ต่อกล้อง = ยืนยัน)")


def publish_confirm(result):
    if mqtt_client is not None:
        mqtt_client.publish(config.MQTT_TOPIC_CONFIRM, result)
    print(f"[MQTT] ส่งผลกลับ ESP32: {result}")


def start_mqtt():
    global mqtt_client
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="schoolride-dashboard")
    client.on_connect = _on_mqtt_connect
    client.on_message = _on_mqtt_message
    try:
        client.connect(config.MQTT_BROKER, config.MQTT_PORT, keepalive=30)
    except Exception as e:
        print(f"[MQTT] เชื่อมต่อ broker ไม่สำเร็จตอนเริ่มโปรแกรม: {e} (จะลองใหม่อัตโนมัติ)")
    client.loop_start()
    mqtt_client = client
    return client


# ============================================================
# Cloudflare Tunnel: เปิด URL สาธารณะชั่วคราวสำหรับให้ LINE ดึงรูปสแนปช็อต
# ============================================================

def start_cloudflare_tunnel():
    global public_base_url

    if not os.path.exists(CLOUDFLARED_PATH):
        print("[Tunnel] ไม่พบ cloudflared.exe ในโฟลเดอร์โปรเจกต์ -> จะส่งได้แค่ข้อความ LINE ไม่มีรูปแนบ")
        return None

    proc = subprocess.Popen(
        [CLOUDFLARED_PATH, "tunnel", "--url", "http://localhost:5000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    url_pattern = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")

    def _watch_output():
        global public_base_url
        for line in proc.stdout:
            match = url_pattern.search(line)
            if match and public_base_url is None:
                public_base_url = match.group(0)
                print(f"[Tunnel] URL สาธารณะพร้อมใช้งาน: {public_base_url}")

    threading.Thread(target=_watch_output, daemon=True).start()
    return proc


# ============================================================
# LINE: ส่งรูป + ข้อความ + พิกัด GPS เข้ากลุ่ม เมื่อกล้องยืนยันพบคน
# ============================================================

def save_snapshot(frame_bgr):
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    path = os.path.join(SNAPSHOT_DIR, "latest.jpg")
    cv2.imwrite(path, frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return path


def build_alert_text(cam_name, person_count):
    label = CAM_DISPLAY_NAMES.get(cam_name, cam_name)
    lines = [
        "⚠️ อันตราย พบเด็กตกค้างบนรถ!",
        f"📷 กล้อง: {label} (พบ {person_count} คน)",
        f"📞 ติดต่อ: {config.CONTACT_PHONE}",
    ]

    with state_lock:
        lat, lng = latest_gps["lat"], latest_gps["lng"]

    if lat is not None:
        lines.append(f"📍 พิกัดตำแหน่งรถตอนนี้:\nhttps://maps.google.com/?q={lat:.6f},{lng:.6f}")
    else:
        lines.append("📍 พิกัดตำแหน่งรถ: (ยังไม่ได้รับสัญญาณ GPS)")

    return "\n".join(lines)


def send_line_alert(cam_name, person_count):
    text = build_alert_text(cam_name, person_count)

    messages = []
    if public_base_url:
        image_url = f"{public_base_url}/snapshot/latest.jpg"
        messages.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url,
        })
    else:
        print("[LINE] ยังไม่มี URL สาธารณะ (cloudflared ยังไม่พร้อม/ไม่มีไฟล์) -> ส่งแค่ข้อความ")

    messages.append({"type": "text", "text": text})

    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.LINE_TOKEN}",
            },
            json={"to": config.LINE_USER_ID, "messages": messages},
            timeout=10,
        )
        print(f"[LINE] ส่งแจ้งเตือนแล้ว status={resp.status_code}")
        if resp.status_code >= 300:
            print(f"[LINE] response: {resp.text[:300]}")
    except Exception as e:
        print(f"[LINE] ส่งแจ้งเตือนไม่สำเร็จ: {e}")


# ============================================================
# กล้อง + YOLO: ตรวจจับต่อเนื่องสำหรับหน้าเว็บ + สะสมเวลา "armed" สำหรับยืนยันเหตุการณ์
# ============================================================

def worker():
    global armed, awaiting_clear, clear_absence_accum

    from ultralytics import YOLO

    cam_config = ensure_config()
    model = YOLO("yolov10s.pt")

    handles = {}
    for cam_name, title in cam_config.items():
        hwnd = find_window(title)
        if hwnd is None:
            print(f"⚠️  ไม่พบหน้าต่างชื่อ \"{title}\" สำหรับ {cam_name} — ข้ามกล้องนี้ไปก่อน")
            continue
        handles[cam_name] = hwnd
        with state_lock:
            camera_state[cam_name] = {
                "jpeg": None,
                "person_count": 0,
                "updated_at": 0.0,
                "online": False,
                "first_detected_at": None,
                "alert": False,
            }

    if not handles:
        print("ไม่พบหน้าต่างที่ตรงกับ config เลย ลองรัน --list-windows เพื่อเช็คชื่อหน้าต่างที่ถูกต้อง")
        return

    print(f"เริ่มตรวจจับวัตถุจาก {len(handles)} กล้อง สำหรับ dashboard...")

    last_tick = time.time()

    while True:
        now_tick = time.time()
        dt = now_tick - last_tick
        last_tick = now_tick

        confirmed_cam = None
        confirmed_count = 0
        confirmed_frame = None
        total_person_count = 0

        for cam_name, hwnd in handles.items():
            if not win32gui.IsWindow(hwnd):
                with state_lock:
                    camera_state[cam_name]["online"] = False
                continue

            try:
                frame = capture_window(hwnd)
            except Exception as e:
                print(f"จับภาพ {cam_name} ไม่สำเร็จ: {e}")
                with state_lock:
                    camera_state[cam_name]["online"] = False
                continue

            results = model(frame, verbose=False, classes=[PERSON_CLASS_ID], imgsz=INFERENCE_SIZE)
            person_count = len(results[0].boxes)
            total_person_count += person_count
            annotated = results[0].plot()
            cropped = crop_top_bottom(annotated, CROP_TOP_RATIO, CROP_BOTTOM_RATIO)

            ok, buf = cv2.imencode(".jpg", cropped, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                continue

            now = time.time()
            with state_lock:
                s = camera_state[cam_name]
                s["jpeg"] = buf.tobytes()
                s["person_count"] = person_count
                s["updated_at"] = now
                s["online"] = True

                if person_count > 0:
                    if s["first_detected_at"] is None:
                        s["first_detected_at"] = now
                    s["alert"] = (now - s["first_detected_at"]) >= ALERT_AFTER_SECONDS
                else:
                    s["first_detected_at"] = None
                    s["alert"] = False

            # ===== สะสมเวลาที่เจอคน ระหว่างช่วง armed (ESP32 สั่งตรวจสอบอยู่) =====
            # เจอคน -> บวกเวลาเพิ่ม / ไม่เจอ -> "หยุดรอ" ค้างค่าเดิมไว้ (ไม่รีเซ็ตเป็น 0)
            with armed_lock:
                if armed and cam_name in armed_accum:
                    if person_count > 0:
                        armed_accum[cam_name] += dt
                    if confirmed_cam is None and armed_accum[cam_name] >= ARMED_CONFIRM_SECONDS:
                        confirmed_cam = cam_name
                        confirmed_count = person_count
                        confirmed_frame = cropped

        # ===== ตัดสินผลของช่วง armed นี้ (ยืนยันพบคน / หมดเวลาไม่พบ) =====
        with armed_lock:
            is_armed = armed
            deadline = armed_deadline

        if is_armed and confirmed_cam is not None:
            with armed_lock:
                armed = False
            save_snapshot(confirmed_frame)
            publish_confirm("CONFIRM")
            send_line_alert(confirmed_cam, confirmed_count)
            awaiting_clear = True
            clear_absence_accum = 0.0
        elif is_armed and time.time() >= deadline:
            with armed_lock:
                armed = False
            publish_confirm("NOPERSON")
            print("[ARM] ครบเวลาที่กำหนดแล้วไม่มีกล้องไหนยืนยันพบคน -> NOPERSON")

        # ===== หลังยืนยันพบคนแล้ว: รอจนไม่เห็นคนเลยสักกล้องต่อเนื่อง CLEAR_ABSENCE_SECONDS -> สั่งปิด alarm =====
        if awaiting_clear:
            if total_person_count == 0:
                clear_absence_accum += dt
                if clear_absence_accum >= CLEAR_ABSENCE_SECONDS:
                    publish_confirm("CLEAR")
                    awaiting_clear = False
                    print("[CLEAR] ไม่พบคนในรถทุกกล้องต่อเนื่องแล้ว -> สั่งปิดสัญญาณเตือนที่ ESP32")
            else:
                clear_absence_accum = 0.0  # ยังเห็นคนอยู่ -> รีเซ็ตตัวจับเวลาความไม่มีคน


def mjpeg_generator(cam_name):
    boundary = b"--frame"
    while True:
        with state_lock:
            entry = camera_state.get(cam_name)
            jpeg = entry["jpeg"] if entry else None
        if jpeg is not None:
            yield (
                boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            )
        time.sleep(0.05)


@app.route("/video_feed/<cam_name>")
@requires_auth
def video_feed(cam_name):
    return Response(
        mjpeg_generator(cam_name),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/snapshot/<path:filename>")
def snapshot(filename):
    # หมายเหตุ: จุดนี้เปิดไว้ "ไม่มี" @requires_auth ตั้งใจ — เซิร์ฟเวอร์ของ LINE ต้องดึงรูปนี้เอง
    # ตอนส่ง originalContentUrl (ดู send_line_alert) โดยไม่มี credential ใดๆ ถ้าใส่ auth ตรงนี้
    # LINE จะโหลดรูปไม่ได้เลย เนื้อหาเสี่ยงต่ำเพราะเป็นแค่ snapshot ล่าสุด (ถูกเขียนทับทุกครั้งที่มีเหตุการณ์ใหม่)
    return send_from_directory(SNAPSHOT_DIR, filename)


@app.route("/api/status")
@requires_auth
def api_status():
    with state_lock:
        payload = {
            cam_name: {
                "online": s["online"],
                "person_count": s["person_count"],
                "alert": s["alert"],
                "updated_at": s["updated_at"],
            }
            for cam_name, s in camera_state.items()
        }
        payload["gps"] = dict(latest_gps)
    payload["_server_time"] = thai_now()
    return jsonify(payload)


@app.route("/")
@requires_auth
def index():
    with state_lock:
        cam_names = list(camera_state.keys())
    return render_template("dashboard.html", cam_names=cam_names, cam_display=CAM_DISPLAY_NAMES)


@app.route("/monitor")
@requires_auth
def monitor():
    # หน้า SchoolRide Monitor (ธีมเดิมของ project_dek_d000166/dashboard.html) — served
    # same-origin จากเซิร์ฟเวอร์นี้เอง เลยดึงวิดีโอ/จำนวนคนผ่าน path สัมพัทธ์ได้ตรงๆ
    # ไม่ต้องกรอกที่อยู่ dashboard เองแบบตอนเปิดเป็นไฟล์ file:// อีกต่อไป
    return render_template("monitor.html")


if __name__ == "__main__":
    start_mqtt()
    start_cloudflare_tunnel()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    # รอให้ worker หา config/หน้าต่างกล้องก่อน จะได้มี cam_names ตอนโหลดหน้าเว็บ
    time.sleep(2)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

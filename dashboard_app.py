"""
SchoolRide Intelligent Safety System — Web Dashboard
=====================================================
ระบบอัจฉริยะสำหรับเฝ้าระวังและแจ้งเตือนเด็กตกค้างบนรถรับส่งนักเรียน

ดึงภาพจากกล้องเดียวกับ multi_camera_ai_v2.py (จับหน้าต่าง BlueStacks + ตรวจจับคนด้วย YOLO)
แล้วสตรีมออกเป็นหน้าเว็บ Dashboard สวยๆ ดูผ่าน browser ได้ (เปิดจากเครื่องอื่นใน LAN เดียวกันก็ได้)

วิธีติดตั้งเพิ่ม (นอกจากของ multi_camera_ai_v2.py):
    pip install flask

วิธีใช้:
    python dashboard_app.py
    แล้วเปิดเบราว์เซอร์ไปที่ http://localhost:5000
"""

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import cv2
from flask import Flask, Response, jsonify, render_template

import win32gui

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

# ถ้าตรวจพบคนต่อเนื่องเกินกี่วินาที ถึงจะขึ้น "แจ้งเตือน" (กันการตรวจจับกระพริบเดี๋ยวเจอเดี๋ยวไม่เจอ)
ALERT_AFTER_SECONDS = 8

TH_TZ = ZoneInfo("Asia/Bangkok")
TH_MONTHS = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]

app = Flask(__name__)

state_lock = threading.Lock()
camera_state = {}  # cam_name -> dict(jpeg, person_count, updated_at, online, first_detected_at, alert)


def thai_now():
    """เวลาจริงของประเทศไทย (Asia/Bangkok) ไม่ใช่นาฬิกาเครื่องผู้ใช้ที่อาจตั้งผิด/คนละโซนเวลา"""
    now = datetime.now(TH_TZ)
    return {
        "date": f"{now.day} {TH_MONTHS[now.month - 1]} {now.year + 543}",
        "time": now.strftime("%H:%M:%S"),
    }


def worker():
    from ultralytics import YOLO

    config = ensure_config()
    model = YOLO("yolov10s.pt")

    handles = {}
    for cam_name, title in config.items():
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

    while True:
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
def video_feed(cam_name):
    return Response(
        mjpeg_generator(cam_name),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/status")
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
    payload["_server_time"] = thai_now()
    return jsonify(payload)


@app.route("/")
def index():
    with state_lock:
        cam_names = list(camera_state.keys())
    return render_template("dashboard.html", cam_names=cam_names, cam_display=CAM_DISPLAY_NAMES)


if __name__ == "__main__":
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    # รอให้ worker หา config/หน้าต่างกล้องก่อน จะได้มี cam_names ตอนโหลดหน้าเว็บ
    time.sleep(2)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

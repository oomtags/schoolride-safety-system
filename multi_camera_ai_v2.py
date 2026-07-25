"""
Multi-Camera AI Viewer (Window Capture Version)
=================================================
ดักจับภาพจาก "หน้าต่างโปรแกรม" โดยตรง (ผ่านชื่อหน้าต่าง/window title)
แทนที่จะจับพิกัดตายตัวบนหน้าจอ ข้อดีคือ:
  - ต่อให้มีหน้าต่างอื่นมาบัง หรือย้ายตำแหน่งหน้าต่าง ก็ยังจับภาพถูกตัวอยู่เสมอ
  - ไม่ติดปัญหา "ภาพซ้อนภาพ" แบบจับพิกัดหน้าจอตรงๆ

วิธีติดตั้ง:
    pip install ultralytics opencv-python numpy pywin32

วิธีใช้:
    1. เปิด BlueStacks ทั้ง 3 instance ให้แสดงกล้องแต่ละตัว
    2. รันคำสั่งนี้เพื่อดูรายชื่อหน้าต่างทั้งหมดที่เปิดอยู่ (หาไว้ว่า BlueStacks แต่ละอันชื่ออะไร):
           python multi_camera_ai_v2.py --list-windows
    3. เปิดไฟล์ windows_config.json แล้วใส่ชื่อหน้าต่าง (title) ของกล้องแต่ละตัวลงไป
       (มีตัวอย่างสร้างให้อัตโนมัติถ้ายังไม่มีไฟล์)
    4. รันโหมดใช้งานจริง:
           python multi_camera_ai_v2.py
"""

import argparse
import json
import os

import ctypes
from ctypes import wintypes

import cv2
import numpy as np
import win32gui

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# ค่าคงที่ที่ใช้กับ Windows API (ไม่ต้องพึ่ง win32con ก็ได้)
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0
PW_RENDERFULLCONTENT = 2


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

CONFIG_FILE = "windows_config.json"


def list_windows():
    """แสดงรายชื่อหน้าต่างทั้งหมดที่เปิดอยู่ตอนนี้ (ใช้หาว่า BlueStacks แต่ละ instance ชื่ออะไร)"""
    print("รายชื่อหน้าต่างที่เปิดอยู่ตอนนี้:\n")

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title.strip():
                print(f"  - \"{title}\"")

    win32gui.EnumWindows(callback, None)
    print(
        "\nจดชื่อหน้าต่างของ BlueStacks แต่ละ instance ไว้ (มักจะเป็น \"BlueStacks App Player\" "
        "หรือมีเลขต่อท้าย เช่น \"BlueStacks App Player 2\") แล้วนำไปใส่ในไฟล์ windows_config.json"
    )


def ensure_config():
    """สร้างไฟล์ config ตัวอย่างถ้ายังไม่มี ให้ผู้ใช้แก้ชื่อหน้าต่างเอง"""
    if not os.path.exists(CONFIG_FILE):
        example = {
            "cam1": "BlueStacks App Player",
            "cam2": "BlueStacks App Player 2",
            "cam3": "BlueStacks App Player 3",
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(example, f, indent=2, ensure_ascii=False)
        print(f"สร้างไฟล์ตัวอย่าง {CONFIG_FILE} ให้แล้ว กรุณาแก้ชื่อหน้าต่างให้ตรงกับเครื่องคุณก่อนรันใหม่")
        print("(ใช้คำสั่ง --list-windows เพื่อดูชื่อหน้าต่างที่ถูกต้องก่อน)")
        raise SystemExit(0)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def find_window(title_substring):
    """หา window handle จากชื่อหน้าต่าง (รองรับการค้นหาแบบ partial match)"""
    result = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title_substring.lower() in title.lower():
                result.append(hwnd)

    win32gui.EnumWindows(callback, None)
    return result[0] if result else None


def capture_window(hwnd):
    """
    จับภาพของหน้าต่างที่ระบุโดยตรง (ใช้ PrintWindow API ของ Windows ผ่าน ctypes ล้วนๆ
    ไม่พึ่ง win32ui เพื่อเลี่ยงปัญหา DLL บน Python เวอร์ชันใหม่ๆ)
    ใช้งานได้แม้หน้าต่างจะถูกบังด้วยหน้าต่างอื่น หรืออยู่นอกจอที่มองเห็น
    """
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width = right - left
    height = bottom - top

    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)

    # PW_RENDERFULLCONTENT ช่วยให้จับภาพถูกต้องแม้กับแอปที่ใช้ GPU rendering (เช่น BlueStacks)
    user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)

    bmp_info = BITMAPINFO()
    bmp_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmp_info.bmiHeader.biWidth = width
    bmp_info.bmiHeader.biHeight = -height  # ค่าติดลบ = ภาพไม่กลับหัว
    bmp_info.bmiHeader.biPlanes = 1
    bmp_info.bmiHeader.biBitCount = 32
    bmp_info.bmiHeader.biCompression = BI_RGB

    buffer_size = width * height * 4
    buffer = (ctypes.c_ubyte * buffer_size)()

    gdi32.GetDIBits(
        mem_dc, bitmap, 0, height, buffer, ctypes.byref(bmp_info), DIB_RGB_COLORS
    )

    img = np.frombuffer(buffer, dtype="uint8").reshape((height, width, 4))
    frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    # ล้าง resource
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    return frame


def crop_top_bottom(img, top_ratio, bottom_ratio):
    """
    Keep the native width completely untouched (no resize, no squeeze).
    Cut off the top top_ratio fraction and the bottom bottom_ratio fraction
    of the height independently (2 separate knobs, since the header at the
    top and the controls at the bottom aren't the same size).
    """
    h, w = img.shape[:2]
    top = int(h * top_ratio)
    bottom = int(h * bottom_ratio)

    end = h - bottom
    if end <= top:
        end = top + 1  # กันไม่ให้เหลือภาพ 0 แถวถ้าตั้งค่าเผลอชนกัน

    return img[top:end, :]


def run_detection():
    from ultralytics import YOLO

    config = ensure_config()
    # ใช้ yolov10s = ตรวจจับได้ดี + ความเร็วดี
    model = YOLO("yolov10s.pt")
    PERSON_CLASS_ID = 0  # ใน COCO dataset class 0 = "person"
    INFERENCE_SIZE = 480  # ลดขนาดภาพก่อนป้อนเข้าโมเดล ยิ่งเล็กยิ่งเร็ว (ปรับได้ 320-640)

    # ✅ ครอปความสูงให้สั้นลง โดยไม่ยุ่งกับความกว้างเลย (ไม่มีการบีบ/ซูมใดๆ)
    # ปรับ 2 ตัวแปรนี้แยกกันได้เลย เพราะส่วนบน (title bar) กับส่วนล่าง (ปุ่มควบคุม) ไม่เท่ากัน
    CROP_TOP_RATIO = 0.17     # ตัดจากด้านบนออกกี่ % (ข้าม title bar/แถบเวลา)
    CROP_BOTTOM_RATIO = 0.35  # ตัดจากด้านล่างออกกี่ % (ข้ามปุ่มควบคุม/ไอคอนล่าง)

    # หา handle ของแต่ละหน้าต่างล่วงหน้า
    handles = {}
    for cam_name, title in config.items():
        hwnd = find_window(title)
        if hwnd is None:
            print(f"⚠️  ไม่พบหน้าต่างชื่อ \"{title}\" สำหรับ {cam_name} — ข้ามกล้องนี้ไปก่อน")
            continue
        handles[cam_name] = hwnd

    if not handles:
        print("ไม่พบหน้าต่างที่ตรงกับ config เลย ลองรัน --list-windows เพื่อเช็คชื่อหน้าต่างที่ถูกต้อง")
        return

    print(f"เริ่มตรวจจับวัตถุจาก {len(handles)} กล้อง... กด 'q' ในหน้าต่างวิดีโอเพื่อออก")

    # ✅ ทำให้หน้าต่างปรับขนาดได้
    cv2.namedWindow("Multi-Camera AI Viewer", cv2.WINDOW_NORMAL)

    printed_sizes = set()
    last_window_size = None

    while True:
        frames = []
        for cam_name, hwnd in handles.items():
            if not win32gui.IsWindow(hwnd):
                continue
            try:
                frame = capture_window(hwnd)
            except Exception as e:
                print(f"จับภาพ {cam_name} ไม่สำเร็จ: {e}")
                continue

            if cam_name not in printed_sizes:
                h, w = frame.shape[:2]
                kept_h = h - int(h * CROP_TOP_RATIO) - int(h * CROP_BOTTOM_RATIO)
                print(f"[{cam_name}] ขนาดภาพต้นฉบับจริง: {w}x{h} px "
                      f"→ หลังครอปเหลือสูงประมาณ {kept_h}px")
                printed_sizes.add(cam_name)

            results = model(frame, verbose=False, classes=[PERSON_CLASS_ID], imgsz=INFERENCE_SIZE)
            annotated = results[0].plot()
            cv2.putText(
                annotated, cam_name, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
            )
            
            # ✅ ตัดความสูงให้สั้นลงเท่านั้น ความกว้างคงเดิม 100% ไม่มีการบีบ/ซูม
            cropped = crop_top_bottom(annotated, CROP_TOP_RATIO, CROP_BOTTOM_RATIO)
            frames.append(cropped)

        if not frames:
            print("จับภาพไม่ได้เลยสักกล้อง — ตรวจสอบว่าหน้าต่างยังเปิดอยู่ไหม")
            break

        # ✅ กล้องแต่ละตัวอาจได้ความสูงหลังครอปต่างกัน 1-2px จากการปัดเศษ
        # ตัดให้เท่ากับตัวที่เตี้ยที่สุดก่อน hstack (ซึ่งต้องการความสูงเท่ากันทุกภาพ)
        min_h = min(f.shape[0] for f in frames)
        frames = [f[:min_h, :] for f in frames]

        # ✅ วาง 3 frame แนวนอน (ตอนนี้มี 3 frame เท่านั้น)
        combined = np.hstack(frames)

        # ✅ บังคับให้หน้าต่างมีขนาดเท่ากับภาพจริงเสมอ กันไม่ให้หน้าต่างเล็กกว่าภาพ
        # แล้วทำให้ฝั่งขวาถูกตัด/บังไว้ (ให้ความกว้างเต็มมาก่อนเสมอ)
        combined_h, combined_w = combined.shape[:2]
        if (combined_w, combined_h) != last_window_size:
            cv2.resizeWindow("Multi-Camera AI Viewer", combined_w, combined_h)
            last_window_size = (combined_w, combined_h)

        cv2.imshow("Multi-Camera AI Viewer", combined)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Camera AI Viewer (Window Capture)")
    parser.add_argument(
        "--list-windows", action="store_true", help="แสดงรายชื่อหน้าต่างทั้งหมดที่เปิดอยู่"
    )
    args = parser.parse_args()

    if args.list_windows:
        list_windows()
    else:
        run_detection()
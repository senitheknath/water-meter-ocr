"""
High-Performance OCR & Upload Server
Prioritizes receiving the meter image, converting it into a clean string via OCR,
and uploading that string to 'currentReadings' and the new database (Firestore slwbdata).
"""
import json
import os
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import threading
import cv2
import numpy as np

from config import PORT, IMAGE_PATH, DEFAULT_USER_ID
from ocr import read_meter
from firebase import upload_ocr_reading
from esp32_camera import capture_esp32_image

PROCESSING_LOCK = threading.Lock()


def flip_image_horizontal(image_bytes):
    """Flip image horizontally for mirrored camera sensors (e.g. ESP32-CAM OV3660)."""
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes
    flipped = cv2.flip(img, 1)
    ok, encoded = cv2.imencode(".jpg", flipped, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return encoded.tobytes() if ok else image_bytes


def process_image_and_upload(image_bytes, user_id=None, save_disk=True):
    """
    Core pipeline:
    1. Runs OCR to extract meter digits as a string (with auto camera-mirror fallback).
    2. Writes the valid frame to latest.jpg.
    3. Uploads that string to the new database and to 'currentReadings'.
    """
    if not image_bytes or len(image_bytes) < 500:
        return {"success": False, "error": "Invalid or empty image bytes provided", "statusCode": 400}

    # Pass 1: Try reading as-is
    final_bytes = image_bytes
    reading_str = read_meter(final_bytes, debug=True)

    # Pass 2: If not detected, try horizontal flip (for mirrored ESP32 camera frames)
    if not reading_str:
        print("[*] Retrying with mirrored camera orientation correction...")
        mirrored = flip_image_horizontal(image_bytes)
        alt_str = read_meter(mirrored, debug=True)
        if alt_str:
            reading_str = alt_str
            final_bytes = mirrored

    if not reading_str:
        return {
            "success": False,
            "reading": None,
            "error": "OCR could not detect meter digits with sufficient confidence",
            "statusCode": 422,
        }

    # Save final oriented image to latest.jpg
    if save_disk:
        try:
            target_path = Path(IMAGE_PATH)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = target_path.with_suffix(".tmp")
            temp_path.write_bytes(final_bytes)
            os.replace(temp_path, target_path)
        except Exception as e:
            print(f"[!] Warning saving image to disk: {e}")

    print(f"\n[+] OCR Conversion Result: '{reading_str}'")

    # Upload string to the new database & currentReadings
    try:
        result = upload_ocr_reading(reading_str, user_id=user_id)
        result["imagePath"] = str(IMAGE_PATH)
        return result
    except Exception as e:
        print(f"[!] Upload to database failed: {e}")
        return {
            "success": False,
            "reading": reading_str,
            "error": f"Failed to upload to database: {e}",
            "statusCode": 503,
        }


class OCRServerHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Calculation-Id, X-User-Id",
        )

    def _send_json(self, data, status_code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        clean_path = self.path.split("?")[0].rstrip("/")
        if clean_path in ("", "/status"):
            self._send_json({
                "status": "online",
                "service": "Water Meter OCR Pipeline",
                "database": "slwbdata",
                "endpoints": [
                    "POST /upload (direct image bytes)",
                    "POST /ocr (direct image bytes)",
                    "POST /calculate_bill (capture from camera or uploaded bytes)",
                    "GET  /latest (view latest meter frame)",
                ],
            })
        elif clean_path == "/latest":
            if os.path.exists(IMAGE_PATH):
                data = Path(IMAGE_PATH).read_bytes()
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._send_json({"error": "No image captured yet"}, 404)
        else:
            self._send_json({"error": "Endpoint not found"}, 404)

    def do_POST(self):
        clean_path = self.path.split("?")[0].rstrip("/")
        user_id = self.headers.get("X-User-Id") or DEFAULT_USER_ID

        # 1. Direct Image Upload Endpoint (/upload or /ocr)
        if clean_path in ("/upload", "/ocr"):
            self._handle_direct_image_upload(user_id)

        # 2. Camera Trigger or Calculation Endpoint (/calculate_bill or /calculate)
        elif clean_path in ("/calculate_bill", "/calculate"):
            self._handle_calculate_bill(user_id)

        else:
            self._send_json({"error": "Endpoint not found"}, 404)

    def _handle_direct_image_upload(self, user_id):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json({"success": False, "error": "No image data sent"}, 400)
            return

        image_bytes = self.rfile.read(content_length)

        # If sent as multipart form-data, extract JPEG binary chunk
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" in content_type:
            start = image_bytes.find(b"\xff\xd8")
            end = image_bytes.rfind(b"\xff\xd9")
            if start != -1 and end != -1:
                image_bytes = image_bytes[start : end + 2]

        if not PROCESSING_LOCK.acquire(blocking=False):
            self._send_json({"success": False, "error": "OCR processing currently in progress"}, 409)
            return

        try:
            result = process_image_and_upload(image_bytes, user_id=user_id)
            status_code = result.get("statusCode", 200 if result.get("success") else 422)
            self._send_json(result, status_code)
        finally:
            PROCESSING_LOCK.release()

    def _handle_calculate_bill(self, user_id):
        content_length = int(self.headers.get("Content-Length", 0))
        image_bytes = None

        if content_length > 1000:
            raw = self.rfile.read(content_length)
            if raw.startswith(b"\xff\xd8"):
                image_bytes = raw

        if not PROCESSING_LOCK.acquire(blocking=False):
            self._send_json({"success": False, "error": "OCR processing already in progress"}, 409)
            return

        try:
            if not image_bytes:
                image_bytes = capture_esp32_image()

            if not image_bytes:
                self._send_json({
                    "success": False,
                    "error": "Could not obtain image from ESP32 camera. Ensure camera is powered on and accessible.",
                }, 502)
                return

            result = process_image_and_upload(image_bytes, user_id=user_id)
            status_code = result.get("statusCode", 200 if result.get("success") else 422)
            self._send_json(result, status_code)
        finally:
            PROCESSING_LOCK.release()


def run_server():
    server_address = ("", PORT)
    httpd = ThreadingHTTPServer(server_address, OCRServerHandler)
    print("==============================================================")
    print(f"  Water Meter OCR Server running on port {PORT}")
    print(f"  Active Database: {DEFAULT_USER_ID} on Firestore (slwbdata)")
    print(f"  Endpoints:")
    print(f"    POST http://localhost:{PORT}/upload")
    print(f"    POST http://localhost:{PORT}/ocr")
    print(f"    POST http://localhost:{PORT}/calculate_bill")
    print(f"    GET  http://localhost:{PORT}/status")
    print(f"    GET  http://localhost:{PORT}/latest")
    print("==============================================================")
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()

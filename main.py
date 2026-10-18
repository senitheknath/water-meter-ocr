"""
Command-Line Interface for Water Meter OCR & Firebase Upload
Receives or captures the meter image, extracts the numeric string,
and uploads the string to 'currentReadings' and the new database (Firestore slwbdata).
"""
import sys
import time
from pathlib import Path

from config import IMAGE_PATH, CAPTURE_INTERVAL, DEFAULT_USER_ID
from ocr import read_meter
from firebase import upload_ocr_reading
from esp32_camera import capture_esp32_image


def process_image(image_path=IMAGE_PATH, user_id=DEFAULT_USER_ID):
    """Run OCR on target image, convert to string, and upload to new database."""
    print()
    print("==============================================================")
    print("               WATER METER OCR & UPLOAD")
    print("==============================================================")
    print(f"Target Image : {image_path}")
    print(f"User ID      : {user_id}")
    print("--------------------------------------------------------------")

    if not Path(image_path).exists():
        print(f"[!] Error: Image file '{image_path}' not found.")
        return False

    # 1. OCR: Convert image into string
    reading_str = read_meter(str(image_path), debug=True)
    if not reading_str:
        print("[!] No meter reading detected.")
        return False

    print(f"[+] OCR Converted String: '{reading_str}'")

    # 2. Upload that string to the new database & currentReadings
    try:
        result = upload_ocr_reading(reading_str, user_id=user_id)
        print()
        print("==============================================================")
        print("  SUCCESS: Reading String Uploaded to Database!")
        print(f"  * Reading String   : '{result['reading']}'")
        print(f"  * Database Field   : users/{result['userId']}/currentReadings")
        print(f"  * Subcollection    : users/{result['userId']}/currentReadings/latest")
        print(f"  * Monthly Record   : users/{result['userId']}/monthlyReadings/2026_10_oct")
        print("==============================================================")
        return True
    except Exception as e:
        print(f"[!] Database upload failed: {e}")
        return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]

    is_loop = "--loop" in flags or "-l" in flags
    capture_camera = "--capture" in flags or "-c" in flags
    target_image = args[0] if args else IMAGE_PATH

    def run_cycle():
        if capture_camera:
            data = capture_esp32_image(save_path=target_image)
            if not data:
                print("[!] Camera capture failed, skipping cycle.")
                return False
        return process_image(target_image)

    if is_loop:
        print(f"[+] Starting OCR loop every {CAPTURE_INTERVAL} seconds...")
        while True:
            run_cycle()
            print(f"\nWaiting {CAPTURE_INTERVAL} seconds...")
            time.sleep(CAPTURE_INTERVAL)
    else:
        run_cycle()


if __name__ == "__main__":
    main()
import os
from pathlib import Path
import requests

from config import ESP32_URL, IMAGE_PATH


def capture_esp32_image(url=ESP32_URL, save_path=IMAGE_PATH, timeout=(5, 20)):
    """
    Fetches a fresh camera frame from the ESP32 camera endpoint.
    Saves it atomically to save_path and returns the image bytes.
    """
    try:
        print(f"[+] Requesting fresh camera frame from ESP32: {url}")
        resp = requests.get(
            url,
            headers={
                "Cache-Control": "no-cache, no-store",
                "Pragma": "no-cache",
                "User-Agent": "WaterMeterOCR/2.0",
            },
            timeout=timeout,
        )

        if resp.status_code != 200:
            print(f"[!] ESP32 returned HTTP {resp.status_code}")
            return None

        data = resp.content
        if len(data) < 1000 or not data.startswith(b"\xff\xd8"):
            print(f"[!] Invalid JPEG received ({len(data)} bytes)")
            return None

        # Atomically write to save_path
        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_file = target.with_suffix(target.suffix + ".tmp")
        temp_file.write_bytes(data)
        os.replace(temp_file, target)

        print(f"[+] Fresh camera image saved to: {target} ({len(data)} bytes)")
        return data

    except requests.exceptions.RequestException as e:
        print(f"[!] ESP32 connection failed: {e}")
        return None
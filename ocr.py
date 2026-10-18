import os
import re
import warnings
from pathlib import Path
import cv2
import numpy as np

# Suppress PyTorch internal quantization and loader warnings
warnings.filterwarnings("ignore", category=UserWarning)

import torch
import easyocr

from config import IMAGE_PATH, CROPPED_DIGITS_PATH

# Optimize thread count for responsive execution without CPU saturation
torch.set_num_threads(max(1, min(4, (os.cpu_count() or 2) // 2)))

print("[+] Initializing EasyOCR engine...")
_READER = easyocr.Reader(["en"], gpu=False)
print("[+] EasyOCR engine ready.")


def _crop_integer_digits(img_bgr, preview_path=CROPPED_DIGITS_PATH, debug=True):
    """Crop the grey/black integer wheels while excluding red decimal wheels."""
    height, width = img_bgr.shape[:2]
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    red_mask = (
        (((hsv[:, :, 0] <= 15) | (hsv[:, :, 0] >= 165))
         & (hsv[:, :, 1] >= 55)
         & (hsv[:, :, 2] >= 45))
        .astype(np.uint8)
    )
    ys, xs = np.where(red_mask > 0)

    if len(xs) >= 200:
        red_start = int(np.percentile(xs, 5))
        x2 = max(1, red_start)
        x1 = max(0, x2 - int(width * 0.56))
        y1 = max(0, int(np.percentile(ys, 2)) - int(height * 0.08))
        y2 = min(height, int(np.percentile(ys, 98)) + int(height * 0.08))
    else:
        x1, x2 = int(width * 0.02), int(width * 0.56)
        y1, y2 = int(height * 0.60), int(height * 0.99)

    cropped = img_bgr[y1:y2, x1:x2]
    if cropped.size == 0:
        return img_bgr

    if preview_path:
        try:
            cv2.imwrite(str(preview_path), cropped)
            if debug:
                print(f"[+] Crop saved to: {preview_path}")
        except Exception:
            pass

    return cropped


def _extract_meter_digits(raw_results, min_conf=0.25):
    """Filter and spatially sort detected digit bounding boxes from left to right."""
    if not raw_results:
        return None, 0.0, 0

    valid_boxes = []
    for item in raw_results:
        bbox, text, conf = item[0], item[1], float(item[2])
        digits = re.sub(r"[^0-9]", "", text)
        if digits and conf >= min_conf:
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            width = max(1, max_x - min_x)
            height = max(1, max_y - min_y)
            valid_boxes.append({
                "bbox": bbox,
                "center_x": (min_x + max_x) / 2.0,
                "height": height,
                "text": digits,
                "conf": conf,
            })

    if not valid_boxes:
        return None, 0.0, 0

    # Filter out tiny artifacts
    max_height = max(b["height"] for b in valid_boxes)
    filtered = [b for b in valid_boxes if b["height"] >= max_height * 0.30]
    filtered.sort(key=lambda b: b["center_x"])

    combined = "".join(b["text"] for b in filtered)
    if len(combined) < 4:
        return None, 0.0, 0

    avg_conf = float(np.mean([b["conf"] for b in filtered]))
    return combined[:4], avg_conf, len(filtered)


def _read_four_digit_slots(img_bgr, debug=True):
    """Read each of the four physical grey wheels individually."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    dark = cv2.threshold(gray, 125, 255, cv2.THRESH_BINARY_INV)[1]
    dark = cv2.morphologyEx(
        dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    )
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = gray.shape[:2]
    panels = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w >= width * 0.65 and h >= height * 0.40:
            panels.append((w * h, x, y, w, h))
    if not panels:
        return None

    _, x, y, w, h = max(panels)
    panel = gray[y:y + h, x:x + w]
    slot_width = panel.shape[1] / 4.0
    digits = []
    confidences = []

    for slot_index in range(4):
        left = max(0, int(slot_index * slot_width) - 12)
        right = min(panel.shape[1], int((slot_index + 1) * slot_width) + 12)
        slot = panel[:, left:right]
        results = _READER.readtext(
            slot,
            allowlist="0123456789",
            detail=1,
            paragraph=False,
            text_threshold=0.3,
            low_text=0.2,
            canvas_size=640,
            mag_ratio=1.5,
            batch_size=1,
            workers=0,
        )
        candidates = []
        for bbox, text, confidence in results:
            clean = re.sub(r"[^0-9]", "", text)
            if len(clean) == 1:
                candidates.append((float(confidence), clean))
        if not candidates:
            return None
        confidence, digit = max(candidates)
        digits.append(digit)
        confidences.append(confidence)

    reading = "".join(digits)
    if debug:
        print(f"[+] Slot reading detected: {reading} (conf: {float(np.mean(confidences)):.2%})")
    return reading


def read_meter(image_input=None, debug=True):
    """
    Optimized OCR pipeline: Accepts file path, image bytes, or numpy array.
    Extracts and returns the 4-digit meter reading as a string (e.g., '0549').
    """
    if image_input is None:
        image_input = IMAGE_PATH

    # 1. Flexible image loading (path, bytes, ndarray)
    if isinstance(image_input, (str, Path)):
        path_str = str(image_input)
        if not os.path.exists(path_str):
            print(f"[!] Image not found: {path_str}")
            return None
        img_bgr = cv2.imread(path_str)
    elif isinstance(image_input, (bytes, bytearray)):
        img_bgr = cv2.imdecode(np.frombuffer(image_input, np.uint8), cv2.IMREAD_COLOR)
    elif isinstance(image_input, np.ndarray):
        img_bgr = image_input
    elif hasattr(image_input, "convert"):
        img_bgr = cv2.cvtColor(np.array(image_input), cv2.COLOR_RGB2BGR)
    else:
        print(f"[!] Unsupported image input type: {type(image_input)}")
        return None

    if img_bgr is None or img_bgr.size == 0:
        print("[!] Could not decode image")
        return None

    # 2. Crop integer dial section
    img_bgr = _crop_integer_digits(img_bgr, debug=debug)

    # 3. Try reading individual physical wheel slots first
    slot_reading = _read_four_digit_slots(img_bgr, debug=debug)
    if slot_reading is not None and len(slot_reading) == 4:
        return slot_reading

    # 4. Standard multi-pass reading with CLAHE
    h, w = img_bgr.shape[:2]
    max_dimension = 960
    if max(h, w) > max_dimension:
        scale = max_dimension / max(h, w)
        img_bgr = cv2.resize(
            img_bgr,
            (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_AREA,
        )

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if len(img_bgr.shape) == 3 else img_bgr.copy()
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    clahe_gray = clahe.apply(gray)

    passes = [
        ("Grayscale CLAHE", clahe_gray),
        ("Standard Grayscale", gray),
    ]

    candidates = []
    for pass_name, proc_img in passes:
        try:
            raw_results = _READER.readtext(
                proc_img,
                mag_ratio=1.0,
                allowlist="0123456789",
                detail=1,
                text_threshold=0.45,
                low_text=0.25,
                canvas_size=960,
                batch_size=1,
                workers=0,
            )
            digits, conf, box_count = _extract_meter_digits(raw_results)
            if digits:
                if debug:
                    print(f"  * [{pass_name:20s}] -> Digits: {digits} | Conf: {conf:.2%}")
                candidates.append((conf, digits, pass_name))
                if conf >= 0.75:
                    break
        except Exception as e:
            if debug:
                print(f"[!] Error in pass '{pass_name}': {e}")

    if not candidates:
        if debug:
            print("[!] No meter digits recognized with sufficient confidence.")
        return None

    candidates.sort(key=lambda c: c[0], reverse=True)
    best_conf, best_digits, method = candidates[0]
    if debug:
        print(f"[+] Recognized Meter String: '{best_digits}' (Conf: {best_conf:.2%}, Method: {method})")

    return best_digits


if __name__ == "__main__":
    result = read_meter()
    print("Meter Reading String:", result)

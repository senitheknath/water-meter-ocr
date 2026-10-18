import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ESP32 Camera URL
ESP32_URL = os.environ.get("ESP32_URL", "http://10.186.151.47/capture")

# Local storage for captured meter images
IMAGE_PATH = str(BASE_DIR / "latest.jpg")
CROPPED_DIGITS_PATH = str(BASE_DIR / "latest_digits.jpg")

# The new Firestore database (slwbdata)
FIRESTORE_PROJECT_ID = os.environ.get("FIRESTORE_PROJECT_ID", "slwbdata")
FIRESTORE_BASE_URL = (
    f"https://firestore.googleapis.com/v1/projects/{FIRESTORE_PROJECT_ID}/databases/(default)/documents"
)

# Default customer account ID in slwbdata (USR001 - USR050)
DEFAULT_USER_ID = os.environ.get("DEFAULT_USER_ID", "USR001")

# Server settings
PORT = int(os.environ.get("PORT", os.environ.get("OCR_PORT", 5000)))
IMAGE_FLIP_MODE = os.environ.get("OCR_IMAGE_FLIP", "horizontal").strip().lower()
CAPTURE_INTERVAL = int(os.environ.get("CAPTURE_INTERVAL", 5))

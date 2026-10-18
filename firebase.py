"""
Firebase Firestore integration for the 'slwbdata' database.
Uploads the OCR-extracted meter string to the user's account and the 'currentReadings' collection.
"""
from datetime import datetime, timezone
import json
import re
import requests

from config import FIRESTORE_BASE_URL, DEFAULT_USER_ID
from water_bill_calculator import calculate_meter_usage, calculate_water_bill

REQUEST_TIMEOUT = 10


def normalize_user_id(user_id=None):
    """Normalize user IDs and map legacy identifiers to the active slwbdata users."""
    raw = (user_id or DEFAULT_USER_ID).strip().upper()
    if raw in ("USER_0001", "USER0001", "WB-0041", "WB0041", "DEFAULT"):
        return "USR001"
    return raw


def get_user(user_id=None):
    """Fetch user profile from Firestore slwbdata."""
    uid = normalize_user_id(user_id)
    url = f"{FIRESTORE_BASE_URL}/users/{uid}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.json().get("fields", {})
    except Exception as e:
        print(f"[!] Warning: Could not fetch user {uid}: {e}")
    return {}


def get_latest_previous_reading(user_id=None, fallback=520.0):
    """Fetch previous meter reading from Firestore slwbdata."""
    uid = normalize_user_id(user_id)
    url = f"{FIRESTORE_BASE_URL}/users/{uid}/monthlyReadings/2026_10_oct"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            fields = resp.json().get("fields", {})
            prev = fields.get("previousMeterReading", {})
            val = prev.get("doubleValue") or prev.get("integerValue")
            if val is not None:
                return float(val)
    except Exception as e:
        print(f"[!] Notice: Could not read previous meter reading for {uid}: {e}")
    return fallback


def upload_ocr_reading(reading_str, user_id=None):
    """
    Main upload pipeline:
    1. Sends the OCR string to users/{userId} as 'currentReadings' and 'currentReading'.
    2. Uploads the reading string into subcollection users/{userId}/currentReadings/latest.
    3. Updates users/{userId}/monthlyReadings/2026_10_oct with consumption & bill breakdown.
    """
    uid = normalize_user_id(user_id)
    clean_str = re.sub(r"[^0-9]", "", str(reading_str).strip())
    if not clean_str:
        raise ValueError("Invalid reading: no digits detected")

    reading_num = float(int(clean_str))
    prev_reading = get_latest_previous_reading(uid, fallback=520.0)

    try:
        usage = float(calculate_meter_usage(int(reading_num), int(prev_reading)))
    except Exception:
        usage = max(0.0, reading_num - prev_reading)

    bill = calculate_water_bill(usage, vat_rate=0.18)
    now_iso = datetime.now(timezone.utc).isoformat()

    print(f"\n[+] Uploading OCR Reading '{clean_str}' to new database (slwbdata)...")
    print(f"    * Target User         : {uid}")
    print(f"    * Current Reading     : {clean_str} ({reading_num} units)")
    print(f"    * Previous Reading    : {prev_reading} units")
    print(f"    * Water Consumption   : {usage} units")
    print(f"    * Calculated Bill     : LKR {bill['totalBill']:.2f}")

    # 1. Update user root document with currentReadings and currentReading strings
    user_url = (
        f"{FIRESTORE_BASE_URL}/users/{uid}?"
        "updateMask.fieldPaths=currentReadings&"
        "updateMask.fieldPaths=currentReading&"
        "updateMask.fieldPaths=ocrReading&"
        "updateMask.fieldPaths=currentFlowRate&"
        "updateMask.fieldPaths=currentDueBillInOctober_LKR&"
        "updateMask.fieldPaths=lastOcrUpdate"
    )
    user_payload = {
        "fields": {
            "currentReadings": {"stringValue": clean_str},
            "currentReading": {"stringValue": clean_str},
            "ocrReading": {"stringValue": clean_str},
            "currentFlowRate": {"doubleValue": float(bill["usageCharge"])},
            "currentDueBillInOctober_LKR": {"doubleValue": float(bill["totalBill"])},
            "lastOcrUpdate": {"stringValue": now_iso},
        }
    }
    r_user = requests.patch(
        user_url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(user_payload),
        timeout=REQUEST_TIMEOUT,
    )
    if r_user.status_code != 200:
        raise RuntimeError(f"Failed to update user document {uid}: HTTP {r_user.status_code} - {r_user.text}")
    print(f"    [OK] users/{uid} updated (currentReadings='{clean_str}')")

    # 2. Upload to currentReadings subcollection document
    readings_sub_url = (
        f"{FIRESTORE_BASE_URL}/users/{uid}/currentReadings/latest?"
        "updateMask.fieldPaths=reading&"
        "updateMask.fieldPaths=userId&"
        "updateMask.fieldPaths=timestamp"
    )
    readings_payload = {
        "fields": {
            "reading": {"stringValue": clean_str},
            "userId": {"stringValue": uid},
            "timestamp": {"stringValue": now_iso},
        }
    }
    r_sub = requests.patch(
        readings_sub_url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(readings_payload),
        timeout=REQUEST_TIMEOUT,
    )
    if r_sub.status_code == 200:
        print(f"    [OK] users/{uid}/currentReadings/latest updated with '{clean_str}'")

    # 3. Update October monthlyReading subcollection document
    oct_url = (
        f"{FIRESTORE_BASE_URL}/users/{uid}/monthlyReadings/2026_10_oct?"
        "updateMask.fieldPaths=previousMeterReading&"
        "updateMask.fieldPaths=currentMeterReading&"
        "updateMask.fieldPaths=waterUsage&"
        "updateMask.fieldPaths=billLKR&"
        "updateMask.fieldPaths=paymentStatus"
    )
    oct_payload = {
        "fields": {
            "previousMeterReading": {"doubleValue": float(prev_reading)},
            "currentMeterReading": {"doubleValue": float(reading_num)},
            "waterUsage": {"doubleValue": float(usage)},
            "billLKR": {"doubleValue": float(bill["totalBill"])},
            "paymentStatus": {"stringValue": "Unpaid"},
        }
    }
    requests.patch(
        oct_url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(oct_payload),
        timeout=REQUEST_TIMEOUT,
    )
    print(f"    [OK] users/{uid}/monthlyReadings/2026_10_oct synced")

    return {
        "success": True,
        "userId": uid,
        "reading": clean_str,
        "currentReadings": clean_str,
        "previousReading": prev_reading,
        "usage": usage,
        "bill": bill,
        "timestamp": now_iso,
    }

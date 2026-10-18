"""Sri Lanka NWSDB domestic water tariff calculator.

Rates are from Gazette Extraordinary No. 2398/19 effective 21 August 2024,
Tariff Table 02 (Domestic Other Than Samurdhi Recipients & Tenement Garden).
"""


def calculate_meter_usage(current, previous, modulus=10000):
    """Return forward usage for a four-digit register, including rollover."""
    current = int(current)
    previous = int(previous)
    if not (0 <= current < modulus and 0 <= previous < modulus):
        raise ValueError("Meter readings must be between 0000 and 9999")
    if current >= previous:
        return current - previous
    if previous >= 9000 and current <= 999:
        return (modulus - previous) + current
    raise ValueError("Current reading cannot be below the previous reading")

def calculate_water_bill(units, vat_rate=0.18):
    """
    Calculate water bill for given consumption units (m3) for a 30-day billing cycle
    with the official 18% VAT rate and full breakdown.
    Rates are from Gazette Extraordinary No. 2398/19 effective 21 August 2024,
    Tariff Table 02 (Domestic Other Than Samurdhi Recipients & Tenement Garden).
    """
    is_whole = isinstance(units, int) or (isinstance(units, float) and float(units).is_integer())
    num_units = max(0.0, float(units))
    units_display = int(num_units) if is_whole else round(num_units, 2)

    # 1. Tiered Usage Charge Calculation
    slabs = [
        (5.0, 50.0),
        (5.0, 70.0),
        (5.0, 90.0),
        (5.0, 100.0),
        (5.0, 120.0),
        (5.0, 150.0),
        (10.0, 170.0),
        (10.0, 195.0),
        (25.0, 225.0),
        (25.0, 250.0),
        (float('inf'), 280.0),
    ]

    remaining = num_units
    usage_charge = 0.0
    for capacity, rate in slabs:
        if remaining <= 0:
            break
        consumed_in_slab = min(remaining, capacity)
        usage_charge += consumed_in_slab * rate
        remaining -= consumed_in_slab

    # 2. Monthly Service Charge & Slab Text
    if num_units <= 5:
        service_charge = 300.0
        slab_text = "00 – 05 units"
    elif num_units <= 10:
        service_charge = 300.0
        slab_text = "06 – 10 units"
    elif num_units <= 15:
        service_charge = 300.0
        slab_text = "11 – 15 units"
    elif num_units <= 20:
        service_charge = 400.0
        slab_text = "16 – 20 units"
    elif num_units <= 25:
        service_charge = 500.0
        slab_text = "21 – 25 units"
    elif num_units <= 30:
        service_charge = 600.0
        slab_text = "26 – 30 units"
    elif num_units <= 40:
        service_charge = 1500.0
        slab_text = "31 – 40 units"
    elif num_units <= 50:
        service_charge = 3000.0
        slab_text = "41 – 50 units"
    elif num_units <= 75:
        service_charge = 3500.0
        slab_text = "51 – 75 units"
    elif num_units <= 100:
        service_charge = 4000.0
        slab_text = "76 – 100 units"
    else:
        service_charge = 4500.0
        slab_text = "Over 100 units"

    subtotal = usage_charge + service_charge
    vat = round(subtotal * vat_rate, 2)
    total_bill = round(subtotal + vat, 2)

    return {
        "units": units_display,
        "usageCharge": round(usage_charge, 2),
        "serviceCharge": round(service_charge, 2),
        "subtotal": round(subtotal, 2),
        "vatAmount": vat,
        "vat": vat,
        "totalBill": total_bill,
        "slabText": slab_text
    }


def calculate_detailed_bill(units, vat_rate=0.18):
    """
    Detailed Sri Lanka NWSDB domestic bill breakdown with block items,
    1.5% prompt payment discount (payable within 14 days), and 2.5% late payment surcharge.
    Gazette Extraordinary No. 2398/19 Items 2, 5, 6.
    """
    base = calculate_water_bill(units, vat_rate=vat_rate)
    num_units = max(0.0, float(units))
    
    slabs = [
        (5.0, 50.0, "00 – 05 units"),
        (5.0, 70.0, "06 – 10 units"),
        (5.0, 90.0, "11 – 15 units"),
        (5.0, 100.0, "16 – 20 units"),
        (5.0, 120.0, "21 – 25 units"),
        (5.0, 150.0, "26 – 30 units"),
        (10.0, 170.0, "31 – 40 units"),
        (10.0, 195.0, "41 – 50 units"),
        (25.0, 225.0, "51 – 75 units"),
        (25.0, 250.0, "76 – 100 units"),
        (float('inf'), 280.0, "Over 100 units"),
    ]
    
    blocks = []
    rem = num_units
    for cap, rate, label in slabs:
        if rem <= 0:
            break
        c = min(rem, cap)
        amt = round(c * rate, 2)
        blocks.append({
            "slab": label,
            "units": round(c, 2),
            "rate": rate,
            "amount": amt
        })
        rem -= c

    total = base["totalBill"]
    prompt_rebate = round(total * 0.015, 2)
    late_surcharge = round(total * 0.025, 2)

    res = dict(base)
    res.update({
        "blocks": blocks,
        "promptPaymentRebate": prompt_rebate,
        "payableWithin14Days": round(total - prompt_rebate, 2),
        "latePaymentSurcharge": late_surcharge,
        "gazetteNotice": "No. 2398/19 (21 August 2024)",
        "tariffCategory": "Tariff Table 02: Domestic Other Than Samurdhi",
    })
    return res


if __name__ == "__main__":
    ex = calculate_water_bill(24)
    assert ex == {
        "units": 24, "usageCharge": 2030.0, "serviceCharge": 500.0,
        "subtotal": 2530.0, "vatAmount": 455.4, "vat": 455.4,
        "totalBill": 2985.4, "slabText": "21 – 25 units",
    }
    print("[+] Official domestic tariff and 18% VAT calculation verified.")

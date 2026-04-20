from fastapi import FastAPI
import pandas as pd
import uuid
from datetime import datetime, timedelta
import math
import pytz

app = FastAPI()

DATABASE_FILE = "database.xlsx"

# ---------- SYSTEM CONFIG ----------
SLOTS = ["09:30", "12:30", "15:30", "18:00"]
SLOT_CAPACITY = 3
SLOT_DURATION_HOURS = 3

# ---------- TIMEZONE ----------
tz = pytz.timezone("Asia/Kolkata")


# ---------- DISPLAY FORMAT HELPERS ----------
def format_date_with_suffix(date_obj):
    """
    Example:
    2026-04-20 -> 20th April 2026
    """
    day = date_obj.day

    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {
            1: "st",
            2: "nd",
            3: "rd"
        }.get(day % 10, "th")

    return f"{day}{suffix} {date_obj.strftime('%B %Y')}"


def format_time_12hr(time_str):
    """
    Example:
    18:00 -> 6:00 PM
    09:30 -> 9:30 AM
    """
    if not time_str:
        return ""

    try:
        time_obj = datetime.strptime(str(time_str).strip(), "%H:%M")
        return time_obj.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return str(time_str)


def convert_12hr_to_24hr(time_str):
    """
    Example:
    6:00 PM -> 18:00
    9:30 AM -> 09:30
    """
    if not time_str:
        return ""

    value = str(time_str).strip()

    try:
        if "AM" in value.upper() or "PM" in value.upper():
            time_obj = datetime.strptime(value.upper(), "%I:%M %p")
            return time_obj.strftime("%H:%M")

        datetime.strptime(value, "%H:%M")
        return value

    except Exception:
        return value


# ---------------- LOAD DATABASE ----------------
def load_database():
    vehicle_df = pd.read_excel(DATABASE_FILE, sheet_name="Vehicle_Database")
    pricing_df = pd.read_excel(DATABASE_FILE, sheet_name="Pricing_Matrix")
    duration_df = pd.read_excel(DATABASE_FILE, sheet_name="Service_Duration")
    bookings_df = pd.read_excel(DATABASE_FILE, sheet_name="Bookings")

    vehicle_df.columns = vehicle_df.columns.str.strip()
    pricing_df.columns = pricing_df.columns.str.strip()
    duration_df.columns = duration_df.columns.str.strip()
    bookings_df.columns = bookings_df.columns.str.strip()

    return vehicle_df, pricing_df, duration_df, bookings_df


vehicle_df, pricing_df, duration_df, bookings_df = load_database()


@app.get("/")
def home():
    return {
        "status": "KarSpa backend running"
    }


@app.post("/api/vehicle-detect")
def vehicle_detect(data: dict):
    text = str(data.get("vehicle_model", "")).lower().strip()

    if text == "":
        return {"status": "not_found"}

    for _, row in vehicle_df.iterrows():
        keywords = str(row["Model Keywords"]).lower()

        for keyword in keywords.split(","):
            if keyword.strip() in text:
                return {
                    "status": "found",
                    "brand": row["Car Brands"],
                    "model": row["Car Models"],
                    "category": row["Car Category"]
                }

    return {"status": "not_found"}


@app.post("/api/price-check")
def price_check(data: dict):
    category = data.get("vehicle_category")
    service = data.get("service_selected")

    if not category or not service:
        return {"error": "vehicle_category and service_selected required"}

    row = pricing_df[pricing_df["Car Category"] == category]

    if row.empty:
        return {"error": "category not found"}

    if service not in pricing_df.columns:
        return {"error": "service not found in pricing"}

    try:
        price = int(row.iloc[0][service])
    except Exception:
        return {"error": "price conversion failed"}

    service_row = duration_df[duration_df["Service Name"] == service]

    if service_row.empty:
        return {"error": "service not found in duration"}

    duration = int(service_row.iloc[0]["Duration (Hours)"])
    description = service_row.iloc[0]["Description"]
    highlights = service_row.iloc[0]["Key Highlights"]

    return {
        "status": "success",
        "price": price,
        "duration_hours": duration,
        "description": description,
        "highlights": highlights
    }


@app.post("/api/slot-check")
def slot_check(data: dict):
    bookings_df = pd.read_excel(DATABASE_FILE, sheet_name="Bookings")
    bookings_df.columns = bookings_df.columns.str.strip()

    # RAW values for internal slot engine
    bookings_df["Date"] = pd.to_datetime(bookings_df["Date"]).dt.date
    bookings_df["Time"] = (
        bookings_df["Time"]
        .astype(str)
        .str.strip()
        .apply(convert_12hr_to_24hr)
    )

    now = datetime.now(tz)
    today = now.date()

    service_name = data.get("service_selected")

    if not service_name:
        return {"error": "service_selected required"}

    service_row = duration_df[
        duration_df["Service Name"] == service_name
    ]

    if service_row.empty:
        return {"error": "service not found"}

    duration_hours = int(service_row.iloc[0]["Duration (Hours)"])

    slots_needed = max(
        1,
        math.ceil(duration_hours / SLOT_DURATION_HOURS)
    )

    offset = int(data.get("day_offset", 0))
    start_date = today + timedelta(days=offset)

    last_slot_hour, last_slot_min = map(
        int,
        SLOTS[-1].split(":")
    )

    last_slot_today = tz.localize(
        datetime.combine(
            today,
            datetime.min.time()
        ).replace(
            hour=last_slot_hour,
            minute=last_slot_min
        )
    )

    if offset == 0 and now > last_slot_today:
        start_date = today + timedelta(days=1)

    for day in range(7):
        check_date = start_date + timedelta(days=day)

        day_bookings = bookings_df[
            bookings_df["Date"] == check_date
        ]

        available_slots = []

        for i, slot in enumerate(SLOTS):
            required_slots = SLOTS[i:i + slots_needed]

            if len(required_slots) < slots_needed:
                continue

            valid_sequence = True

            for rs in required_slots:
                hour, minute = map(int, rs.split(":"))

                slot_dt = tz.localize(
                    datetime.combine(
                        check_date,
                        datetime.min.time()
                    ).replace(
                        hour=hour,
                        minute=minute
                    )
                )

                if check_date == today and slot_dt <= now:
                    valid_sequence = False
                    break

                slot_count = len(
                    day_bookings[
                        day_bookings["Time"] == rs
                    ]
                )

                if slot_count >= SLOT_CAPACITY:
                    valid_sequence = False
                    break

            if valid_sequence:
                available_slots.append(slot)

        if available_slots:
            return {
                "status": "success",

                # RAW values (safe for backend logic)
                "date": str(check_date),
                "slots": available_slots,

                # DISPLAY values (for WhatsApp UI)
                "display_date": format_date_with_suffix(check_date),
                "next_available_date": format_date_with_suffix(check_date),
                "next_available_time": format_time_12hr(available_slots[0]),

                "slot_1": format_time_12hr(available_slots[0]) if len(available_slots) > 0 else "",
                "slot_2": format_time_12hr(available_slots[1]) if len(available_slots) > 1 else "",
                "slot_3": format_time_12hr(available_slots[2]) if len(available_slots) > 2 else "",
                "slot_4": format_time_12hr(available_slots[3]) if len(available_slots) > 3 else "",

                "slots_needed": slots_needed
            }

    return {
        "status": "no_slots",
        "message": "No slots available in next 7 days",
        "slot_1": "",
        "slot_2": "",
        "slot_3": "",
        "slot_4": ""
    }


@app.post("/api/create-booking")
def create_booking(data: dict):
    booking_id = "U3-" + str(uuid.uuid4())[:6]

    # Always store RAW time internally
    raw_time = convert_12hr_to_24hr(
        data.get("service_time")
    )

    booking = {
        "Booking_ID": booking_id,
        "Customer_Name": data.get("customer_name"),
        "Vehicle": str(data.get("vehicle_brand")) + " " + str(data.get("vehicle_model")),
        "Service": data.get("service_selected"),
        "Price": data.get("service_price"),
        "Date": data.get("service_date"),
        "Time": raw_time,
        "Timestamp": datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    }

    df = pd.read_excel(
        DATABASE_FILE,
        sheet_name="Bookings"
    )

    df = pd.concat(
        [df, pd.DataFrame([booking])],
        ignore_index=True
    )

    with pd.ExcelWriter(
        DATABASE_FILE,
        engine="openpyxl",
        mode="a",
        if_sheet_exists="replace"
    ) as writer:
        df.to_excel(
            writer,
            sheet_name="Bookings",
            index=False
        )

    return {
        "booking_id": booking_id,
        "status": "Booking created successfully"
    }

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


def format_date_with_suffix(date_obj):
    day = date_obj.day
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {date_obj.strftime('%B %Y')}"


def format_time_12hr(time_str):
    if not time_str:
        return ""
    try:
        time_obj = datetime.strptime(str(time_str).strip(), "%H:%M")
        return time_obj.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return str(time_str)


def convert_12hr_to_24hr(time_str):
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


def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


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
    return {"status": "KarSpa backend running"}


@app.get("/api/latest-booking")
def latest_booking():
    try:
        import os

        if not os.path.exists(DATABASE_FILE):
            return {
                "status": "error",
                "message": f"{DATABASE_FILE} file not found"
            }

        excel_file = pd.ExcelFile(DATABASE_FILE)

        if "Bookings" not in excel_file.sheet_names:
            return {
                "status": "error",
                "message": f"Bookings sheet not found. Available sheets: {excel_file.sheet_names}"
            }

        df = pd.read_excel(
            DATABASE_FILE,
            sheet_name="Bookings"
        )

        df.columns = df.columns.str.strip()

        if df.empty:
            return {
                "status": "error",
                "message": "No bookings found"
            }

        latest = df.tail(1).to_dict(orient="records")[0]

        return {
            "status": "success",
            "latest_booking": latest
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
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

    return {
        "status": "success",
        "price": int(row.iloc[0][service]),
        "duration_hours": safe_int(service_row.iloc[0]["Duration (Hours)"]),
        "description": service_row.iloc[0]["Description"],
        "highlights": service_row.iloc[0]["Key Highlights"]
    }


@app.post("/api/slot-check")
def slot_check(data: dict):
    bookings_df = pd.read_excel(DATABASE_FILE, sheet_name="Bookings")
    bookings_df.columns = bookings_df.columns.str.strip()

    bookings_df["Date"] = pd.to_datetime(bookings_df["Date"]).dt.date
    bookings_df["Time"] = (
        bookings_df["Time"].astype(str).str.strip().apply(convert_12hr_to_24hr)
    )

    now = datetime.now(tz)
    today = now.date()

    service_name = data.get("service_selected")
    if not service_name:
        return {"error": "service_selected required"}

    service_row = duration_df[duration_df["Service Name"] == service_name]
    if service_row.empty:
        return {"error": "service not found"}

    duration_hours = safe_int(service_row.iloc[0]["Duration (Hours)"])
    slots_needed = max(1, math.ceil(duration_hours / SLOT_DURATION_HOURS))

    offset = safe_int(data.get("day_offset", 0))
    start_date = today + timedelta(days=offset)

    for day in range(7):
        check_date = start_date + timedelta(days=day)
        day_bookings = bookings_df[bookings_df["Date"] == check_date]

        available_slots = []

        for i, slot in enumerate(SLOTS):
            required_slots = SLOTS[i:i + slots_needed]

            if len(required_slots) < slots_needed:
                continue

            valid = True

            for rs in required_slots:
                hour, minute = map(int, rs.split(":"))

                slot_dt = tz.localize(
                    datetime.combine(check_date, datetime.min.time()).replace(
                        hour=hour,
                        minute=minute
                    )
                )

                if check_date == today and slot_dt <= now:
                    valid = False
                    break

                slot_count = len(day_bookings[day_bookings["Time"] == rs])

                if slot_count >= SLOT_CAPACITY:
                    valid = False
                    break

            if valid:
                available_slots.append(slot)

        if available_slots:
            return {
                "status": "success",
                "date": str(check_date),
                "raw_time": available_slots[0],
                "slots": available_slots,
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
    try:
        required_fields = [
            "customer_name",
            "vehicle_brand",
            "vehicle_model",
            "service_selected",
            "service_price",
            "service_date",
            "service_time"
        ]

        missing = [field for field in required_fields if not data.get(field)]

        if missing:
            return {
                "status": "error",
                "message": f"Missing required fields: {', '.join(missing)}"
            }

        booking_id = "U3-" + str(uuid.uuid4())[:6]
        raw_time = convert_12hr_to_24hr(data.get("service_time"))

        booking = {
            "Booking_ID": booking_id,
            "Customer_Name": data.get("customer_name"),
            "Vehicle": f"{data.get('vehicle_brand')} {data.get('vehicle_model')}",
            "Service": data.get("service_selected"),
            "Price": data.get("service_price"),
            "Date": data.get("service_date"),
            "Time": raw_time,
            "Timestamp": datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        }

        df = pd.read_excel(DATABASE_FILE, sheet_name="Bookings")
        before_count = len(df)

        df = pd.concat([df, pd.DataFrame([booking])], ignore_index=True)

        with pd.ExcelWriter(
            DATABASE_FILE,
            engine="openpyxl",
            mode="a",
            if_sheet_exists="replace"
        ) as writer:
            df.to_excel(writer, sheet_name="Bookings", index=False)

        verify_df = pd.read_excel(DATABASE_FILE, sheet_name="Bookings")
        after_count = len(verify_df)

        if after_count <= before_count:
            return {
                "status": "error",
                "message": "Booking was not saved to database"
            }

        return {
            "status": "success",
            "booking_id": booking_id,
            "message": "Booking created successfully"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Booking creation failed: {str(e)}"
        }

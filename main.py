from fastapi import FastAPI
import pandas as pd
import uuid
from datetime import datetime, timedelta
import math
import pytz
import os
import gspread
from google.oauth2.service_account import Credentials

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



# ---------- GOOGLE SHEETS CRM ----------
def save_to_google_sheet(booking):
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]

        creds = Credentials.from_service_account_file(
            "service-account.json",
            scopes=scope
        )

        client = gspread.authorize(creds)
        sheet = client.open("U3 Bookings CRM").worksheet("Bookings")

        sheet.append_row([
            str(booking.get("Booking_ID", "")),
            str(booking.get("Customer_Name", "")),
            str(booking.get("Vehicle", "")),
            str(booking.get("Service", "")),
            str(booking.get("Price", "")),
            str(booking.get("Date", "")),
            str(booking.get("Time", "")),
            str(booking.get("Timestamp", ""))
        ])

        return True

    except Exception as e:
    return {
        "google_error": str(e)
    }


# ---------------- LOAD DATABASE ----------------
def load_database():
    """
    Safe loader:
    - If database.xlsx or any sheet is missing, the app still starts.
    - Missing sheets are returned as empty DataFrames.
    """
    empty_df = pd.DataFrame()

    try:
        if not os.path.exists(DATABASE_FILE):
            print(f"LOAD DATABASE ERROR: {DATABASE_FILE} not found")
            return empty_df, empty_df, empty_df, empty_df

        vehicle_df = pd.read_excel(DATABASE_FILE, sheet_name="Vehicle_Database")
        pricing_df = pd.read_excel(DATABASE_FILE, sheet_name="Pricing_Matrix")
        duration_df = pd.read_excel(DATABASE_FILE, sheet_name="Service_Duration")

        try:
            bookings_df = pd.read_excel(DATABASE_FILE, sheet_name="Bookings")
        except Exception:
            bookings_df = pd.DataFrame()

        vehicle_df.columns = vehicle_df.columns.str.strip()
        pricing_df.columns = pricing_df.columns.str.strip()
        duration_df.columns = duration_df.columns.str.strip()

        if not bookings_df.empty:
            bookings_df.columns = bookings_df.columns.str.strip()

        return vehicle_df, pricing_df, duration_df, bookings_df

    except Exception as e:
        print(f"LOAD DATABASE ERROR: {str(e)}")
        return empty_df, empty_df, empty_df, empty_df


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

        latest_row = df.tail(1).fillna("").iloc[0]

        latest_booking_data = {}

        for column in df.columns:
            value = latest_row[column]

            if pd.isna(value):
                latest_booking_data[column] = ""
            else:
                latest_booking_data[column] = str(value)

        return {
            "status": "success",
            "latest_booking": latest_booking_data
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Latest booking failed: {str(e)}"
        }


# =========================================================
# VEHICLE DETECTION API
# =========================================================


@app.get("/api/view-bookings")
def view_bookings():
    try:
        if not os.path.exists(DATABASE_FILE):
            return {
                "status": "error",
                "message": f"{DATABASE_FILE} file not found"
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

        df = df.fillna("")
        records = []

        for _, row in df.iterrows():
            item = {}

            for column in df.columns:
                value = row[column]

                if pd.isna(value):
                    item[column] = ""
                else:
                    item[column] = str(value)

            records.append(item)

        return {
            "status": "success",
            "total_bookings": len(records),
            "bookings": records
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"View bookings failed: {str(e)}"
        }


@app.post("/api/vehicle-detect")
def vehicle_detect(data: dict):
    try:
        text = str(data.get("vehicle_model", "")).lower().strip()

        if text == "":
            return {"status": "not_found"}

        if vehicle_df.empty:
            return {"status": "error", "message": "Vehicle database not loaded"}

        for _, row in vehicle_df.iterrows():
            keywords = str(row.get("Model Keywords", "")).lower()

            for keyword in keywords.split(","):
                if keyword.strip() and keyword.strip() in text:
                    return {
                        "status": "found",
                        "brand": row.get("Car Brands", ""),
                        "model": row.get("Car Models", ""),
                        "category": row.get("Car Category", "")
                    }

        return {"status": "not_found"}

    except Exception as e:
        return {"status": "error", "message": f"Vehicle detect failed: {str(e)}"}


# =========================================================
# PRICE LOOKUP API
# =========================================================
@app.post("/api/price-check")
def price_check(data: dict):
    try:
        category = data.get("vehicle_category")
        service = data.get("service_selected")

        if not category or not service:
            return {"error": "vehicle_category and service_selected required"}

        if pricing_df.empty:
            return {"error": "pricing database not loaded"}

        if duration_df.empty:
            return {"error": "duration database not loaded"}

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

        duration = safe_int(service_row.iloc[0]["Duration (Hours)"])
        description = service_row.iloc[0].get("Description", "")
        highlights = service_row.iloc[0].get("Key Highlights", "")

        return {
            "status": "success",
            "price": price,
            "duration_hours": duration,
            "description": description,
            "highlights": highlights
        }

    except Exception as e:
        return {"error": f"price-check failed: {str(e)}"}


# =========================================================
# SMART SLOT ENGINE (WABIS FRIENDLY)
# =========================================================
@app.post("/api/slot-check")
def slot_check(data: dict):
    try:
        # Reload bookings every request
        if os.path.exists(DATABASE_FILE):
            try:
                bookings_df = pd.read_excel(DATABASE_FILE, sheet_name="Bookings")
                bookings_df.columns = bookings_df.columns.str.strip()
            except Exception:
                bookings_df = pd.DataFrame()
        else:
            bookings_df = pd.DataFrame()

        if not bookings_df.empty:
            # clean date + time for internal logic
            if "Date" in bookings_df.columns:
                bookings_df["Date"] = pd.to_datetime(bookings_df["Date"], errors="coerce").dt.date
            else:
                bookings_df["Date"] = pd.Series(dtype="object")

            if "Time" in bookings_df.columns:
                bookings_df["Time"] = (
                    bookings_df["Time"]
                    .astype(str)
                    .str.strip()
                    .apply(convert_12hr_to_24hr)
                )
            else:
                bookings_df["Time"] = pd.Series(dtype="object")

        now = datetime.now(tz)
        today = now.date()

        service_name = data.get("service_selected")

        if not service_name:
            return {"error": "service_selected required"}

        if duration_df.empty:
            return {"error": "duration database not loaded"}

        service_row = duration_df[duration_df["Service Name"] == service_name]

        if service_row.empty:
            return {"error": "service not found"}

        duration_hours = safe_int(service_row.iloc[0]["Duration (Hours)"])
        slots_needed = max(1, math.ceil(duration_hours / SLOT_DURATION_HOURS))

        # day offset
        offset = safe_int(data.get("day_offset", 0))
        start_date = today + timedelta(days=offset)

        # if all today's slots are over → move to tomorrow
        last_slot_hour, last_slot_min = map(int, SLOTS[-1].split(":"))
        last_slot_today = tz.localize(
            datetime.combine(today, datetime.min.time()).replace(
                hour=last_slot_hour,
                minute=last_slot_min
            )
        )

        if offset == 0 and now > last_slot_today:
            start_date = today + timedelta(days=1)

        # check next 7 days
        for day in range(7):
            check_date = start_date + timedelta(days=day)

            if bookings_df.empty:
                day_bookings = pd.DataFrame()
            else:
                day_bookings = bookings_df[bookings_df["Date"] == check_date]

            available_slots = []

            for i, slot in enumerate(SLOTS):
                # continuous slot requirement
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

                    # remove past slots only for today
                    if check_date == today and slot_dt <= now:
                        valid_sequence = False
                        break

                    # slot capacity check
                    if not day_bookings.empty and "Time" in day_bookings.columns:
                        slot_count = len(day_bookings[day_bookings["Time"] == rs])
                    else:
                        slot_count = 0

                    if slot_count >= SLOT_CAPACITY:
                        valid_sequence = False
                        break

                if valid_sequence:
                    available_slots.append(slot)

            # if slots found
            if available_slots:
                return {
                    "status": "success",

                    # RAW values (safe for backend logic)
                    "date": str(check_date),
                    "raw_time": available_slots[0],
                    "slots": available_slots,

                    # DISPLAY values (for WhatsApp UI)
                    "display_date": format_date_with_suffix(check_date),
                    "next_available_date": format_date_with_suffix(check_date),
                    "next_available_time": format_time_12hr(available_slots[0]),

                    # WABIS-friendly fields
                    "slot_1": format_time_12hr(available_slots[0]) if len(available_slots) > 0 else "",
                    "slot_2": format_time_12hr(available_slots[1]) if len(available_slots) > 1 else "",
                    "slot_3": format_time_12hr(available_slots[2]) if len(available_slots) > 2 else "",
                    "slot_4": format_time_12hr(available_slots[3]) if len(available_slots) > 3 else "",

                    "slots_needed": slots_needed
                }

        # no slots found
        return {
            "status": "no_slots",
            "message": "No slots available in next 7 days",

            # keep mapping safe for WABIS
            "slot_1": "",
            "slot_2": "",
            "slot_3": "",
            "slot_4": ""
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"slot-check failed: {str(e)}"
        }


# =========================================================
# CREATE BOOKING API
# =========================================================
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

        if not os.path.exists(DATABASE_FILE):
            return {
                "status": "error",
                "message": f"{DATABASE_FILE} file not found"
            }

        booking_id = "U3-" + str(uuid.uuid4())[:6]

        # Always store RAW time internally
        raw_time = convert_12hr_to_24hr(data.get("service_time"))

        # if caller accidentally sends display date, it will still be stored as received
        raw_date = data.get("service_date")

        if not raw_date:
            raw_date = datetime.now(tz).strftime("%Y-%m-%d")

        booking = {
            "Booking_ID": booking_id,
            "Customer_Name": data.get("customer_name"),
            "Vehicle": f"{data.get('vehicle_brand')} {data.get('vehicle_model')}",
            "Service": data.get("service_selected"),
            "Price": data.get("service_price"),
            "Date": raw_date,
            "Time": raw_time,
            "Timestamp": datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        }

        # read existing bookings
        try:
            df = pd.read_excel(DATABASE_FILE, sheet_name="Bookings")
            df.columns = df.columns.str.strip()
        except Exception:
            # if sheet is missing, create a fresh table using booking columns
            df = pd.DataFrame(columns=list(booking.keys()))

        before_count = len(df)

        # append new booking
        df = pd.concat([df, pd.DataFrame([booking])], ignore_index=True)

        # write back to Excel
        with pd.ExcelWriter(
            DATABASE_FILE,
            engine="openpyxl",
            mode="a",
            if_sheet_exists="replace"
        ) as writer:
            df.to_excel(writer, sheet_name="Bookings", index=False)

        # verify save
        try:
            verify_df = pd.read_excel(DATABASE_FILE, sheet_name="Bookings")
            after_count = len(verify_df)
        except Exception:
            after_count = before_count

        if after_count <= before_count:
            return {
                "status": "error",
                "message": "Booking was not saved to database"
            }

        google_sheet_saved = save_to_google_sheet(booking)

        return {
            "status": "success",
            "booking_id": booking_id,
            "google_sheet_saved": google_sheet_saved,
            "message": "Booking created successfully"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Booking creation failed: {str(e)}"
        }

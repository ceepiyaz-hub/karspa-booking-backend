
from fastapi import FastAPI
import pandas as pd
import uuid
from datetime import datetime, timedelta
import math

app = FastAPI()

DATABASE_FILE = "database.xlsx"

# ---------- SYSTEM CONFIG ----------
SLOTS = ["09:30","12:30","15:30","18:00"]
SLOT_CAPACITY = 3   # number of detailing bays
SLOT_DURATION_HOURS = 3   # each slot roughly 3 hours

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
    return {"status": "KarSpa backend running"}


# ---------------- VEHICLE DETECTION ----------------
@app.post("/api/vehicle-detect")
def vehicle_detect(data: dict):

    text = str(data.get("vehicle_model","")).lower().strip()

    if text == "":
        return {"status":"not_found"}

    for _,row in vehicle_df.iterrows():

        keywords = str(row["Model Keywords"]).lower()

        for keyword in keywords.split(","):
            if keyword.strip() in text:

                return {
                    "status":"found",
                    "brand":row["Car Brands"],
                    "model":row["Car Models"],
                    "category":row["Car Category"]
                }

    return {"status":"not_found"}


# ---------------- PRICE LOOKUP ----------------
@app.post("/api/price-check")
def price_check(data: dict):

    category = data.get("vehicle_category")
    service = data.get("service_selected")

    row = pricing_df[pricing_df["Car Category"] == category]

    if row.empty:
        return {"error":"category not found"}

    price = int(row.iloc[0][service])

    service_row = duration_df[duration_df["Service Name"] == service]

    duration = int(service_row.iloc[0]["Duration (Hours)"])
    description = service_row.iloc[0]["Description"]
    highlights = service_row.iloc[0]["Key Highlights"]

    return {
        "status":"success",
        "price":price,
        "duration_hours":duration,
        "description":description,
        "highlights":highlights
    }


# ---------------- SMART SLOT ENGINE (DURATION AWARE) ----------------
@app.post("/api/slot-check")
def slot_check(data: dict):

    bookings_df = pd.read_excel(DATABASE_FILE, sheet_name="Bookings")
    bookings_df["Date"] = pd.to_datetime(bookings_df["Date"]).dt.date

    now = datetime.now()
    today = now.date()

    service_name = data.get("service_selected")

    service_row = duration_df[duration_df["Service Name"] == service_name]
    duration_hours = int(service_row.iloc[0]["Duration (Hours)"])

    slots_needed = max(1, math.ceil(duration_hours / SLOT_DURATION_HOURS))

    offset = int(data.get("day_offset",0))
    start_date = today + timedelta(days=offset)

    # skip today if working hours finished
    last_slot_hour, last_slot_min = map(int, SLOTS[-1].split(":"))
    last_slot_today = datetime.combine(today, datetime.min.time()).replace(
        hour=last_slot_hour, minute=last_slot_min
    )

    if now > last_slot_today:
        start_date = today + timedelta(days=1)

    for day in range(7):

        check_date = start_date + timedelta(days=day)
        day_bookings = bookings_df[bookings_df["Date"] == check_date]

        available_slots = []

        for i,slot in enumerate(SLOTS):

            required_slots = SLOTS[i:i+slots_needed]

            if len(required_slots) < slots_needed:
                continue

            valid_sequence = True

            for rs in required_slots:

                hour,minute = map(int, rs.split(":"))

                slot_dt = datetime.combine(check_date, datetime.min.time()).replace(
                    hour=hour, minute=minute
                )

                # Only skip past slots if checking today
                if check_date == today and slot_dt <= now:
                    valid_sequence = False
                    break

                slot_count = len(day_bookings[day_bookings["Time"] == rs])

                if slot_count >= SLOT_CAPACITY:
                    valid_sequence = False
                    break

            if valid_sequence:
                available_slots.append(slot)

        if available_slots:

            return {
                "status":"success",
                "date":str(check_date),
                "slots":available_slots,
                "slots_needed":slots_needed,
                "next_available_date":str(check_date),
                "next_available_time":available_slots[0]
            }

    return {
        "status":"no_slots",
        "message":"No slots available in next 7 days"
    }


# ---------------- CREATE BOOKING ----------------
@app.post("/api/create-booking")
def create_booking(data: dict):

    booking_id = "U3-" + str(uuid.uuid4())[:6]

    booking = {
        "Booking_ID":booking_id,
        "Customer_Name":data.get("customer_name"),
        "Vehicle":str(data.get("vehicle_brand")) + " " + str(data.get("vehicle_model")),
        "Service":data.get("service_selected"),
        "Price":data.get("service_price"),
        "Date":data.get("service_date"),
        "Time":data.get("service_time"),
        "Timestamp":datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    df = pd.read_excel(DATABASE_FILE, sheet_name="Bookings")
    df = pd.concat([df, pd.DataFrame([booking])], ignore_index=True)

    with pd.ExcelWriter(
        DATABASE_FILE,
        engine="openpyxl",
        mode="a",
        if_sheet_exists="replace"
    ) as writer:
        df.to_excel(writer, sheet_name="Bookings", index=False)

    return {
        "booking_id":booking_id,
        "status":"Booking created successfully"
    }

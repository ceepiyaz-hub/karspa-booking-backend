
from fastapi import FastAPI
import pandas as pd
import uuid
from datetime import datetime

app = FastAPI()

DATABASE_FILE = "database.xlsx"

# Load Excel database
try:
    vehicle_df = pd.read_excel(DATABASE_FILE, sheet_name="Vehicle_Database")
    pricing_df = pd.read_excel(DATABASE_FILE, sheet_name="Pricing_Matrix")
    duration_df = pd.read_excel(DATABASE_FILE, sheet_name="Service_Duration")
    print("Database loaded successfully")
except Exception as e:
    print("Database load error:", e)
    vehicle_df = None
    pricing_df = None
    duration_df = None


@app.get("/")
def home():
    return {"status": "KarSpa backend running"}


# ---------------- VEHICLE DETECTION ----------------
@app.post("/api/vehicle-detect")
def vehicle_detect(data: dict):

    if vehicle_df is None:
        return {"error": "vehicle database missing"}

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


# ---------------- PRICE LOOKUP ----------------
@app.post("/api/price-check")
def price_check(data: dict):

    if pricing_df is None:
        return {"error": "pricing database missing"}

    if duration_df is None:
        return {"error": "service duration database missing"}

    category = data.get("vehicle_category")
    service = data.get("service_selected")

    if category is None or service is None:
        return {"error": "vehicle_category and service_selected required"}

    # -------- FIND PRICE --------
    row = pricing_df[pricing_df["Car Category"] == category]

    if row.empty:
        return {"error": f"category '{category}' not found"}

    if service not in pricing_df.columns:
        return {"error": f"service '{service}' column not found"}

    try:
        price = row.iloc[0][service]
        price = int(price)
    except Exception as e:
        return {"error": str(e)}

    # -------- FIND SERVICE DETAILS --------
    service_row = duration_df[duration_df["Service Name"] == service]

    if service_row.empty:
        duration = None
        description = ""
        highlights = ""
    else:
        duration = service_row.iloc[0]["Duration (Hours)"]
        description = service_row.iloc[0]["Description"]
        highlights = service_row.iloc[0]["Key Highlights"]

    # convert duration safely
    try:
        duration = int(duration)
    except:
        duration = None

    # -------- RESPONSE --------
    return {
        "status": "success",
        "service": service,
        "vehicle_category": category,
        "price": price,
        "duration_hours": duration,
        "description": description,
        "highlights": highlights
    }

# ---------------- SLOT CHECK ----------------
from datetime import datetime, timedelta

@app.post("/api/slot-check")
def slot_check(data: dict):

    if bookings_df is None:
        return {"error": "booking database missing"}

    # available slots
    slots = ["09:30", "12:30", "15:30", "18:00"]

    # each slot capacity (3 bays)
    slot_capacity = 3

    # get selected day offset
    offset = data.get("day_offset", 0)

    booking_date = datetime.now().date() + timedelta(days=int(offset))
    booking_date_str = booking_date.strftime("%Y-%m-%d")

    # filter bookings for selected date
    day_bookings = bookings_df[bookings_df["Date"] == booking_date_str]

    available_slots = []

    for slot in slots:

        slot_count = len(day_bookings[day_bookings["Time"] == slot])

        if slot_count < slot_capacity:
            available_slots.append(slot)

    return {
        "status": "success",
        "date": booking_date_str,
        "slots": available_slots
    }

# ---------------- CREATE BOOKING ----------------
@app.post("/api/create-booking")
def create_booking(data: dict):

    booking_id = "U3-" + str(uuid.uuid4())[:6]

    booking = {
        "Booking_ID": booking_id,
        "Customer_Name": data.get("customer_name"),
        "Vehicle": str(data.get("vehicle_brand")) + " " + str(data.get("vehicle_model")),
        "Service": data.get("service_selected"),
        "Price": data.get("service_price"),
        "Date": data.get("service_date"),
        "Time": data.get("service_time"),
        "Pickup_Type": data.get("pickup_type"),
        "Location": data.get("pickup_location"),
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    try:

        bookings_df = pd.read_excel(DATABASE_FILE, sheet_name="Bookings")

        bookings_df = pd.concat(
            [bookings_df, pd.DataFrame([booking])],
            ignore_index=True
        )

        with pd.ExcelWriter(
            DATABASE_FILE,
            engine="openpyxl",
            mode="a",
            if_sheet_exists="replace"
        ) as writer:

            bookings_df.to_excel(writer, sheet_name="Bookings", index=False)

    except Exception as e:
        return {"error": str(e)}

    return {
        "booking_id": booking_id,
        "status": "Booking created successfully"
    }

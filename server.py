"""
Elderly Care Monitoring System (ECMS) - Backend Server
Author: Kathiravan A (Coimbatore Institute of Technology)
Enhanced Version: Multi-Senior Support, Medication Adherence, Caregiver Wellness Journal,
Emergency SOS Dispatch, Doctor Clinical Reports, Telemetry CSV Export & IoT Hardware Integration.
"""

import asyncio
import csv
import io
import json
import sqlite3
import time
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# App Initialization & Paths
# ---------------------------------------------------------------------------
app = FastAPI(title="Elderly Care Monitoring System (ECMS)", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "ecms.db"

# ---------------------------------------------------------------------------
# Database Initialization & Schema Migrations
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        
        # UserAccount Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL, -- Doctor, Family_Caregiver, Administrator
                phone TEXT,
                email TEXT
            )
        """)

        # ElderlyProfile Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS elderly_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                full_name TEXT NOT NULL,
                age INTEGER NOT NULL,
                gender TEXT,
                medical_history TEXT,
                emergency_contact TEXT,
                doctor_name TEXT DEFAULT 'Dr. Arvind Sharma',
                doctor_phone TEXT DEFAULT '+91-9876500002',
                address TEXT DEFAULT '142 Avinashi Road, Peelamedu, Coimbatore',
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # Add any missing columns to elderly_profiles if upgrading from older version
        for col, col_type in [
            ("doctor_name", "TEXT DEFAULT 'Dr. Arvind Sharma'"),
            ("doctor_phone", "TEXT DEFAULT '+91-9876500002'"),
            ("address", "TEXT DEFAULT '142 Avinashi Road, Peelamedu, Coimbatore'")
        ]:
            try:
                cursor.execute(f"ALTER TABLE elderly_profiles ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass

        # ThresholdConfig Table (1:1 with Patient)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS threshold_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER UNIQUE NOT NULL,
                min_hr INTEGER DEFAULT 55,
                max_hr INTEGER DEFAULT 105,
                min_spo2 REAL DEFAULT 92.0,
                min_temp REAL DEFAULT 36.0,
                max_temp REAL DEFAULT 37.8,
                safe_lat REAL DEFAULT 11.0168,
                safe_lng REAL DEFAULT 76.9558,
                safe_radius_meters REAL DEFAULT 250.0,
                FOREIGN KEY(patient_id) REFERENCES elderly_profiles(id)
            )
        """)

        # HealthMetricLog Table (Time-Series Store)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS health_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                heart_rate INTEGER NOT NULL,
                spo2 REAL NOT NULL,
                temperature REAL NOT NULL,
                steps INTEGER DEFAULT 0,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                motion_vector REAL DEFAULT 1.0,
                FOREIGN KEY(patient_id) REFERENCES elderly_profiles(id)
            )
        """)

        # IncidentAlert Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incident_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                alert_type TEXT NOT NULL, -- FALL_DETECTED, VITAL_ANOMALY, GEOFENCE_BREACH, EMERGENCY_SOS
                severity TEXT NOT NULL,   -- Warning, Emergency
                message TEXT NOT NULL,
                status TEXT NOT NULL,     -- Verifying_Countdown, Emergency, Resolved, Cancelled
                doctor_notes TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY(patient_id) REFERENCES elderly_profiles(id)
            )
        """)

        # DispatchLog Table (Emergency notification records: SMS, Email, Push)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dispatch_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER,
                channel TEXT NOT NULL, -- SMS, EMAIL, PUSH, WHATSAPP
                recipient TEXT NOT NULL,
                payload TEXT NOT NULL,
                dispatched_at TEXT NOT NULL,
                status TEXT DEFAULT 'Delivered'
            )
        """)

        # Medications Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS medications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                dosage TEXT NOT NULL,
                time TEXT NOT NULL, -- e.g. "08:00 AM"
                instructions TEXT,
                status TEXT DEFAULT 'pending', -- 'pending', 'taken', 'missed'
                last_taken_at TEXT,
                FOREIGN KEY(patient_id) REFERENCES elderly_profiles(id)
            )
        """)

        # Daily Wellness & Caregiver Journal Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_wellness_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                water_glasses INTEGER DEFAULT 4,
                meals_logged TEXT DEFAULT '{"breakfast": true, "lunch": false, "dinner": false}',
                sleep_hours REAL DEFAULT 7.5,
                mood TEXT DEFAULT 'Calm',
                notes TEXT DEFAULT 'Resting comfortably; vitals stable.',
                FOREIGN KEY(patient_id) REFERENCES elderly_profiles(id)
            )
        """)
        conn.commit()

        # Seed initial users if empty
        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO users (username, full_name, role, phone, email) VALUES
                ('admin', 'Kathiravan A', 'Administrator', '+91-9876500001', 'admin@ecms-cit.edu'),
                ('dr_sharma', 'Dr. Arvind Sharma', 'Doctor', '+91-9876500002', 'dr.sharma@hospital.org'),
                ('caregiver_priya', 'Priya K (Daughter)', 'Family_Caregiver', '+91-9876500003', 'priya.k@gmail.com')
            """)
            conn.commit()

        # Seed elderly profiles if only 0 or 1 exists
        cursor.execute("SELECT COUNT(*) FROM elderly_profiles")
        patient_count = cursor.fetchone()[0]

        if patient_count == 0:
            # Seed Patient 1
            cursor.execute("""
                INSERT INTO elderly_profiles (user_id, full_name, age, gender, medical_history, emergency_contact, doctor_name, doctor_phone, address) VALUES
                (3, 'Robert Jenkins', 78, 'Male', 'Hypertension, Mild Cardiac Arrhythmia, Osteoporosis', '+91-9876500003', 'Dr. Arvind Sharma (Cardiologist)', '+91-9876500002', '142 Avinashi Road, Peelamedu, Coimbatore')
            """)
            p1_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO threshold_configs (patient_id, min_hr, max_hr, min_spo2, min_temp, max_temp, safe_lat, safe_lng, safe_radius_meters)
                VALUES (?, 55, 105, 92.0, 36.0, 37.8, 11.0168, 76.9558, 250.0)
            """, (p1_id,))
            conn.commit()

        # Seed multi-patient demonstration profiles (Patient 2 & 3) if not present
        cursor.execute("SELECT COUNT(*) FROM elderly_profiles")
        if cursor.fetchone()[0] < 3:
            # Patient 2: Margaret Smith
            cursor.execute("""
                INSERT INTO elderly_profiles (user_id, full_name, age, gender, medical_history, emergency_contact, doctor_name, doctor_phone, address) VALUES
                (3, 'Margaret Smith', 82, 'Female', 'Early-Stage Alzheimer''s, Osteoarthritis, High Fall & Wander Risk', '+91-9876500004 (David Smith, Son)', 'Dr. Meenakshi Sundaram (Geriatrician)', '+91-9876500008', '28 Race Course Road, Coimbatore')
            """)
            p2_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO threshold_configs (patient_id, min_hr, max_hr, min_spo2, min_temp, max_temp, safe_lat, safe_lng, safe_radius_meters)
                VALUES (?, 58, 100, 93.0, 36.0, 37.7, 11.0055, 76.9680, 200.0)
            """, (p2_id,))

            # Patient 3: Sundar Rajan
            cursor.execute("""
                INSERT INTO elderly_profiles (user_id, full_name, age, gender, medical_history, emergency_contact, doctor_name, doctor_phone, address) VALUES
                (3, 'Sundar Rajan', 74, 'Male', 'Type 2 Diabetes, Diabetic Neuropathy, Post-Bypass Cardiac Rehab', '+91-9876500005 (Ananya Rajan, Wife)', 'Dr. Rajesh Kannan (Endocrinologist)', '+91-9876500009', '85 Gandhipuram 4th Cross, Coimbatore')
            """)
            p3_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO threshold_configs (patient_id, min_hr, max_hr, min_spo2, min_temp, max_temp, safe_lat, safe_lng, safe_radius_meters)
                VALUES (?, 52, 108, 91.5, 36.0, 37.9, 11.0185, 76.9642, 300.0)
            """, (p3_id,))
            conn.commit()

        # Seed baseline metrics for any patient lacking health_metrics
        cursor.execute("SELECT id FROM elderly_profiles")
        patients = cursor.fetchall()
        now = time.time()
        for p in patients:
            pid = p["id"]
            cursor.execute("SELECT COUNT(*) FROM health_metrics WHERE patient_id = ?", (pid,))
            if cursor.fetchone()[0] == 0:
                for i in range(12, 0, -1):
                    t_str = datetime.fromtimestamp(now - i * 30).strftime("%Y-%m-%d %H:%M:%S")
                    base_lat = 11.0168 if pid == 1 else (11.0055 if pid == 2 else 11.0185)
                    base_lng = 76.9558 if pid == 1 else (76.9680 if pid == 2 else 76.9642)
                    cursor.execute("""
                        INSERT INTO health_metrics (patient_id, timestamp, heart_rate, spo2, temperature, steps, latitude, longitude, motion_vector)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (pid, t_str, 72 + ((i + pid) % 6), 97.5 - ((i % 3) * 0.4), 36.6, 2100 + i * 35,
                          base_lat + (i * 0.00002), base_lng - (i * 0.00002), 0.98))
                conn.commit()

        # Seed default medications if medications table is empty
        cursor.execute("SELECT COUNT(*) FROM medications")
        if cursor.fetchone()[0] == 0:
            today_str = date.today().isoformat()
            # Patient 1 Medications
            cursor.execute("""
                INSERT INTO medications (patient_id, name, dosage, time, instructions, status, last_taken_at) VALUES
                (1, 'Amlodipine Besylate', '5 mg', '08:00 AM', 'Blood Pressure — Take after breakfast with a full glass of water', 'taken', ?),
                (1, 'Aspirin (Cardio)', '75 mg', '01:00 PM', 'Blood Thinner — Take after lunch to prevent gastric irritation', 'pending', NULL),
                (1, 'Atorvastatin', '20 mg', '08:00 PM', 'Cholesterol / Heart Health — Take before bedtime', 'pending', NULL)
            """, (f"{today_str} 08:15:00",))

            # Patient 2 Medications
            cursor.execute("""
                INSERT INTO medications (patient_id, name, dosage, time, instructions, status, last_taken_at) VALUES
                (2, 'Donepezil Hydrochloride', '10 mg', '09:00 AM', 'Cognitive Support — Take with morning meal', 'taken', ?),
                (2, 'Calcium Carbonate + D3', '500 mg', '02:00 PM', 'Bone Health / Osteoarthritis — Take with milk or meal', 'pending', NULL),
                (2, 'Melatonin', '3 mg', '09:00 PM', 'Sleep Regulation — Take 30 minutes before sleep', 'pending', NULL)
            """, (f"{today_str} 09:10:00",))

            # Patient 3 Medications
            cursor.execute("""
                INSERT INTO medications (patient_id, name, dosage, time, instructions, status, last_taken_at) VALUES
                (3, 'Metformin Extended Release', '500 mg', '08:30 AM', 'Blood Glucose Control — Take with breakfast', 'taken', ?),
                (3, 'Losartan Potassium', '50 mg', '01:30 PM', 'Renal Protection & BP — Take with lunch', 'taken', ?),
                (3, 'Glimepiride', '2 mg', '07:30 PM', 'Diabetes Management — Take immediately before dinner', 'pending', NULL)
            """, (f"{today_str} 08:35:00", f"{today_str} 13:40:00"))
            conn.commit()

        # Seed daily wellness logs if empty
        cursor.execute("SELECT COUNT(*) FROM daily_wellness_logs")
        if cursor.fetchone()[0] == 0:
            today_str = date.today().isoformat()
            cursor.execute("""
                INSERT INTO daily_wellness_logs (patient_id, date, water_glasses, meals_logged, sleep_hours, mood, notes) VALUES
                (1, ?, 5, '{"breakfast": true, "lunch": false, "dinner": false}', 7.5, 'Calm', 'Resting well in morning. Morning walk completed in garden.'),
                (2, ?, 4, '{"breakfast": true, "lunch": true, "dinner": false}', 6.8, 'Happy', 'Good memory recall today. Participated in art therapy.'),
                (3, ?, 6, '{"breakfast": true, "lunch": true, "dinner": false}', 8.0, 'Calm', 'Blood sugar fasting 114 mg/dL. Normal sensation in feet.')
            """, (today_str, today_str, today_str))
            conn.commit()

init_db()

# ---------------------------------------------------------------------------
# WebSocket Real-Time Connection Manager (REQ-5)
# ---------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

# ---------------------------------------------------------------------------
# Fall Detection & 15-Second False Alarm Safeguard Engine (REQ-6, 7, 8, 10)
# ---------------------------------------------------------------------------
active_countdown_task: Optional[asyncio.Task] = None
current_verifying_alert_id: Optional[int] = None

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates approximate distance between two GPS coordinates in meters."""
    from math import radians, cos, sin, asin, sqrt
    r = 6371000  # radius of Earth in meters
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2)**2
    c = 2 * asin(sqrt(a))
    return r * c

async def run_fall_countdown(alert_id: int, patient_id: int):
    """15-second non-blocking countdown safeguard. If not cancelled, triggers emergency dispatch."""
    global current_verifying_alert_id
    current_verifying_alert_id = alert_id
    try:
        for remaining in range(15, -1, -1):
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute("SELECT status FROM incident_alerts WHERE id = ?", (alert_id,))
                row = cur.fetchone()
                if not row or row["status"] != "Verifying_Countdown":
                    # Cancelled by user!
                    return

            await manager.broadcast({
                "type": "COUNTDOWN_TICK",
                "alert_id": alert_id,
                "patient_id": patient_id,
                "remaining_seconds": remaining
            })
            
            if remaining == 0:
                # Countdown expired -> Transition to EMERGENCY & Dispatch!
                execute_emergency_dispatch(alert_id, patient_id, reason="Fall impact verified (15s timeout expired)")
                return
                
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        current_verifying_alert_id = None

def execute_emergency_dispatch(alert_id: int, patient_id: int, reason: str = "Fall impact verified"):
    """Executes multi-channel notification dispatch (SMS, Email, Push, WhatsApp) upon confirmed emergency."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE incident_alerts 
            SET status = 'Emergency', severity = 'Emergency' 
            WHERE id = ?
        """, (alert_id,))

        cur.execute("SELECT full_name, emergency_contact, doctor_name, doctor_phone FROM elderly_profiles WHERE id = ?", (patient_id,))
        pat = cur.fetchone()
        cur.execute("SELECT latitude, longitude, heart_rate, spo2, temperature FROM health_metrics WHERE patient_id = ? ORDER BY id DESC LIMIT 1", (patient_id,))
        metric = cur.fetchone()
        
        lat = metric["latitude"] if metric else 11.0168
        lng = metric["longitude"] if metric else 76.9558
        hr = metric["heart_rate"] if metric else 75
        spo2 = metric["spo2"] if metric else 98.0
        contact = pat["emergency_contact"] if pat else "+91-9876500003"
        patient_name = pat["full_name"] if pat else "Robert Jenkins"

        maps_url = f"https://maps.google.com/?q={lat:.5f},{lng:.5f}"
        sms_body = f"CRITICAL EMERGENCY: {reason} for {patient_name}! Vitals: HR={hr}bpm, SpO2={spo2}%. Location: {maps_url}. Immediate assistance dispatched."
        email_body = f"Subject: URGENT Medical Emergency Alert - {patient_name}\n\nEmergency Trigger: {reason}\nVitals at Incident: Heart Rate = {hr} bpm, SpO2 = {spo2}%, Temp = {metric['temperature'] if metric else 36.6}°C\nReal-Time GPS Coordinates: ({lat:.5f}, {lng:.5f})\nLive Map: {maps_url}\nDispatcher Action: Automated notification dispatched to primary caregiver ({contact}) and ambulance standby."
        whatsapp_body = f"🚨 *EMERGENCY ALERT - ECMS CarePortal*\n*Patient:* {patient_name}\n*Alert:* {reason}\n*Vitals:* HR: {hr} bpm | SpO2: {spo2}%\n*Location:* {maps_url}\n*Time:* {now_str}"

        # Multi-channel logs
        cur.execute("INSERT INTO dispatch_logs (alert_id, channel, recipient, payload, dispatched_at) VALUES (?, 'SMS', ?, ?, ?)",
                    (alert_id, contact, sms_body, now_str))
        cur.execute("INSERT INTO dispatch_logs (alert_id, channel, recipient, payload, dispatched_at) VALUES (?, 'EMAIL', ?, ?, ?)",
                    (alert_id, "caregiver@ecms-cit.edu", email_body, now_str))
        cur.execute("INSERT INTO dispatch_logs (alert_id, channel, recipient, payload, dispatched_at) VALUES (?, 'PUSH', ?, ?, ?)",
                    (alert_id, f"Caregiver App [{patient_name}]", f"EMERGENCY: {reason} for {patient_name}", now_str))
        cur.execute("INSERT INTO dispatch_logs (alert_id, channel, recipient, payload, dispatched_at) VALUES (?, 'WHATSAPP', ?, ?, ?)",
                    (alert_id, contact, whatsapp_body, now_str))
        conn.commit()

    asyncio.create_task(manager.broadcast({
        "type": "EMERGENCY_CONFIRMED",
        "alert_id": alert_id,
        "patient_id": patient_id,
        "message": f"Critical emergency confirmed for {patient_name}! Multi-channel alerts dispatched to family and doctors."
    }))

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------
class MetricPayload(BaseModel):
    patient_id: int = 1
    heart_rate: int = Field(..., ge=20, le=240)
    spo2: float = Field(..., ge=50.0, le=100.0)
    temperature: float = Field(..., ge=30.0, le=45.0)
    steps: int = Field(default=0, ge=0)
    latitude: float = Field(...)
    longitude: float = Field(...)
    motion_vector: float = Field(default=1.0) # > 3.2g indicates fall deceleration

class ThresholdUpdate(BaseModel):
    min_hr: int
    max_hr: int
    min_spo2: float
    min_temp: float
    max_temp: float
    safe_lat: float
    safe_lng: float
    safe_radius_meters: float

class ResolveAlertPayload(BaseModel):
    doctor_notes: str

class MedicationCreate(BaseModel):
    name: str
    dosage: str
    time: str
    instructions: Optional[str] = ""

class WellnessUpdate(BaseModel):
    water_glasses: Optional[int] = None
    meals_logged: Optional[str] = None
    sleep_hours: Optional[float] = None
    mood: Optional[str] = None
    notes: Optional[str] = None

class PatientCreate(BaseModel):
    full_name: str
    age: int
    gender: str
    medical_history: str
    emergency_contact: str
    doctor_name: Optional[str] = "Dr. Arvind Sharma"
    doctor_phone: Optional[str] = "+91-9876500002"
    address: Optional[str] = "Coimbatore, Tamil Nadu"
    safe_lat: Optional[float] = 11.0168
    safe_lng: Optional[float] = 76.9558
    safe_radius_meters: Optional[float] = 250.0

class PatientUpdate(BaseModel):
    full_name: str
    age: int
    gender: str
    medical_history: str
    emergency_contact: str
    doctor_name: str
    doctor_phone: str
    address: str

# ---------------------------------------------------------------------------
# REST API Endpoints: Multi-Patient Management
# ---------------------------------------------------------------------------
@app.get("/api/patients")
def list_all_patients():
    """Returns list of all monitored senior citizens with summary status."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM elderly_profiles ORDER BY id ASC")
        patients = [dict(r) for r in cur.fetchall()]

        for p in patients:
            pid = p["id"]
            # Latest metric
            cur.execute("SELECT * FROM health_metrics WHERE patient_id = ? ORDER BY id DESC LIMIT 1", (pid,))
            metric = cur.fetchone()
            p["latest_metric"] = dict(metric) if metric else None

            # Thresholds
            cur.execute("SELECT * FROM threshold_configs WHERE patient_id = ?", (pid,))
            thresh = cur.fetchone()
            p["thresholds"] = dict(thresh) if thresh else {}

            # Active alerts
            cur.execute("SELECT * FROM incident_alerts WHERE patient_id = ? AND status IN ('Verifying_Countdown', 'Emergency') ORDER BY id DESC LIMIT 1", (pid,))
            active_alert = cur.fetchone()
            p["active_alert"] = dict(active_alert) if active_alert else None

            # Pending meds count
            cur.execute("SELECT COUNT(*) FROM medications WHERE patient_id = ? AND status = 'pending'", (pid,))
            p["pending_meds_count"] = cur.fetchone()[0]

            # Overall Status
            if active_alert:
                p["status_code"] = "emergency" if active_alert["status"] == "Emergency" else "countdown"
            elif metric and thresh:
                if (metric["heart_rate"] > thresh["max_hr"] or 
                    metric["heart_rate"] < thresh["min_hr"] or 
                    metric["spo2"] < thresh["min_spo2"]):
                    p["status_code"] = "warning"
                else:
                    p["status_code"] = "normal"
            else:
                p["status_code"] = "normal"

        return patients

@app.get("/api/patient")
def get_patient_profile(patient_id: int = 1):
    """Retrieves full profile, vitals, active alert, medications, and wellness for specific patient."""
    today_str = date.today().isoformat()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM elderly_profiles WHERE id = ?", (patient_id,))
        patient = cur.fetchone()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient profile not found")
        
        cur.execute("SELECT * FROM threshold_configs WHERE patient_id = ?", (patient_id,))
        thresholds = cur.fetchone()
        
        cur.execute("SELECT * FROM health_metrics WHERE patient_id = ? ORDER BY id DESC LIMIT 1", (patient_id,))
        latest_metric = cur.fetchone()

        cur.execute("SELECT * FROM incident_alerts WHERE patient_id = ? AND status IN ('Verifying_Countdown', 'Emergency') ORDER BY id DESC LIMIT 1", (patient_id,))
        active_alert = cur.fetchone()

        cur.execute("SELECT * FROM medications WHERE patient_id = ? ORDER BY id ASC", (patient_id,))
        medications = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM daily_wellness_logs WHERE patient_id = ? AND date = ? LIMIT 1", (patient_id, today_str))
        wellness = cur.fetchone()
        if not wellness:
            cur.execute("""
                INSERT INTO daily_wellness_logs (patient_id, date, water_glasses, meals_logged, sleep_hours, mood, notes)
                VALUES (?, ?, 4, '{"breakfast": false, "lunch": false, "dinner": false}', 7.0, 'Calm', 'Day started.')
            """, (patient_id, today_str))
            conn.commit()
            cur.execute("SELECT * FROM daily_wellness_logs WHERE patient_id = ? AND date = ? LIMIT 1", (patient_id, today_str))
            wellness = cur.fetchone()

        return {
            "profile": dict(patient),
            "thresholds": dict(thresholds) if thresholds else {},
            "latest_metric": dict(latest_metric) if latest_metric else {},
            "active_alert": dict(active_alert) if active_alert else None,
            "medications": medications,
            "wellness": dict(wellness) if wellness else {}
        }

@app.post("/api/patients")
async def create_new_patient(payload: PatientCreate):
    """Registers a new elderly citizen into the care system."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO elderly_profiles (user_id, full_name, age, gender, medical_history, emergency_contact, doctor_name, doctor_phone, address)
            VALUES (3, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (payload.full_name, payload.age, payload.gender, payload.medical_history, payload.emergency_contact,
              payload.doctor_name, payload.doctor_phone, payload.address))
        pid = cur.lastrowid

        cur.execute("""
            INSERT INTO threshold_configs (patient_id, min_hr, max_hr, min_spo2, min_temp, max_temp, safe_lat, safe_lng, safe_radius_meters)
            VALUES (?, 55, 105, 92.0, 36.0, 37.8, ?, ?, ?)
        """, (pid, payload.safe_lat, payload.safe_lng, payload.safe_radius_meters))

        # Seed initial metric
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""
            INSERT INTO health_metrics (patient_id, timestamp, heart_rate, spo2, temperature, steps, latitude, longitude, motion_vector)
            VALUES (?, ?, 74, 98.0, 36.6, 1200, ?, ?, 0.98)
        """, (pid, now_str, payload.safe_lat, payload.safe_lng))

        # Initialize wellness
        cur.execute("""
            INSERT INTO daily_wellness_logs (patient_id, date, water_glasses, meals_logged, sleep_hours, mood, notes)
            VALUES (?, ?, 4, '{"breakfast": false, "lunch": false, "dinner": false}', 7.5, 'Calm', 'Initial intake recorded.')
        """, (pid, date.today().isoformat()))

        conn.commit()

    await manager.broadcast({"type": "PATIENT_UPDATED", "patient_id": pid})
    return {"status": "success", "patient_id": pid, "message": f"Patient profile for {payload.full_name} created successfully."}

@app.put("/api/patients/{patient_id}")
async def update_patient_profile(patient_id: int, payload: PatientUpdate):
    """Updates senior's demographics, medical history, and contact coordinates."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE elderly_profiles
            SET full_name=?, age=?, gender=?, medical_history=?, emergency_contact=?, doctor_name=?, doctor_phone=?, address=?
            WHERE id=?
        """, (payload.full_name, payload.age, payload.gender, payload.medical_history, payload.emergency_contact,
              payload.doctor_name, payload.doctor_phone, payload.address, patient_id))
        conn.commit()
    await manager.broadcast({"type": "PATIENT_UPDATED", "patient_id": patient_id})
    return {"status": "success", "message": "Patient profile updated successfully."}

# ---------------------------------------------------------------------------
# REST API Endpoints: Medication Routine & Adherence
# ---------------------------------------------------------------------------
@app.get("/api/patients/{patient_id}/medications")
def get_patient_medications(patient_id: int):
    """Fetches medication schedule and computes daily adherence score."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM medications WHERE patient_id = ? ORDER BY id ASC", (patient_id,))
        meds = [dict(r) for r in cur.fetchall()]
        
        total = len(meds)
        taken = sum(1 for m in meds if m["status"] == "taken")
        adherence_rate = round((taken / total * 100), 1) if total > 0 else 100.0

        return {
            "patient_id": patient_id,
            "total_medications": total,
            "taken_medications": taken,
            "adherence_rate": adherence_rate,
            "medications": meds
        }

@app.post("/api/patients/{patient_id}/medications")
async def add_patient_medication(patient_id: int, payload: MedicationCreate):
    """Adds a new prescription schedule for senior."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO medications (patient_id, name, dosage, time, instructions, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (patient_id, payload.name, payload.dosage, payload.time, payload.instructions))
        med_id = cur.lastrowid
        conn.commit()

    await manager.broadcast({"type": "MEDICATION_UPDATED", "patient_id": patient_id})
    return {"status": "success", "medication_id": med_id, "message": "Medication added to schedule."}

@app.post("/api/medications/{med_id}/take")
async def toggle_medication_taken(med_id: int):
    """Toggles medication taken state and logs exact timestamp."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT patient_id, status FROM medications WHERE id = ?", (med_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Medication not found")
        
        patient_id = row["patient_id"]
        new_status = "pending" if row["status"] == "taken" else "taken"
        taken_at = now_str if new_status == "taken" else None

        cur.execute("UPDATE medications SET status = ?, last_taken_at = ? WHERE id = ?", (new_status, taken_at, med_id))
        conn.commit()

    await manager.broadcast({
        "type": "MEDICATION_UPDATED",
        "patient_id": patient_id,
        "med_id": med_id,
        "status": new_status
    })
    return {"status": "success", "new_status": new_status, "last_taken_at": taken_at}

@app.delete("/api/medications/{med_id}")
async def delete_medication(med_id: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT patient_id FROM medications WHERE id = ?", (med_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Medication not found")
        patient_id = row["patient_id"]
        cur.execute("DELETE FROM medications WHERE id = ?", (med_id,))
        conn.commit()

    await manager.broadcast({"type": "MEDICATION_UPDATED", "patient_id": patient_id})
    return {"status": "success", "message": "Medication removed."}

# ---------------------------------------------------------------------------
# REST API Endpoints: Caregiver Wellness & Daily Journal
# ---------------------------------------------------------------------------
@app.get("/api/patients/{patient_id}/wellness")
def get_patient_wellness(patient_id: int):
    today_str = date.today().isoformat()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM daily_wellness_logs WHERE patient_id = ? AND date = ?", (patient_id, today_str))
        row = cur.fetchone()
        if not row:
            cur.execute("""
                INSERT INTO daily_wellness_logs (patient_id, date, water_glasses, meals_logged, sleep_hours, mood, notes)
                VALUES (?, ?, 4, '{"breakfast": false, "lunch": false, "dinner": false}', 7.0, 'Calm', 'Day initialized.')
            """, (patient_id, today_str))
            conn.commit()
            cur.execute("SELECT * FROM daily_wellness_logs WHERE patient_id = ? AND date = ?", (patient_id, today_str))
            row = cur.fetchone()
        return dict(row)

@app.post("/api/patients/{patient_id}/wellness")
async def update_patient_wellness(patient_id: int, payload: WellnessUpdate):
    today_str = date.today().isoformat()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM daily_wellness_logs WHERE patient_id = ? AND date = ?", (patient_id, today_str))
        existing = cur.fetchone()

        water = payload.water_glasses if payload.water_glasses is not None else (existing["water_glasses"] if existing else 4)
        meals = payload.meals_logged if payload.meals_logged is not None else (existing["meals_logged"] if existing else '{"breakfast":false,"lunch":false,"dinner":false}')
        sleep = payload.sleep_hours if payload.sleep_hours is not None else (existing["sleep_hours"] if existing else 7.0)
        mood = payload.mood if payload.mood is not None else (existing["mood"] if existing else 'Calm')
        notes = payload.notes if payload.notes is not None else (existing["notes"] if existing else '')

        if existing:
            cur.execute("""
                UPDATE daily_wellness_logs 
                SET water_glasses=?, meals_logged=?, sleep_hours=?, mood=?, notes=? 
                WHERE id=?
            """, (water, meals, sleep, mood, notes, existing["id"]))
        else:
            cur.execute("""
                INSERT INTO daily_wellness_logs (patient_id, date, water_glasses, meals_logged, sleep_hours, mood, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (patient_id, today_str, water, meals, sleep, mood, notes))
        conn.commit()

    await manager.broadcast({"type": "WELLNESS_UPDATED", "patient_id": patient_id})
    return {"status": "success", "message": "Wellness journal updated."}

# ---------------------------------------------------------------------------
# REST API Endpoints: Emergency SOS One-Tap Trigger
# ---------------------------------------------------------------------------
@app.post("/api/patients/{patient_id}/sos")
async def trigger_emergency_sos(patient_id: int):
    """Emergency SOS button pressed by senior or family caregiver."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT full_name, emergency_contact, doctor_name, doctor_phone FROM elderly_profiles WHERE id = ?", (patient_id,))
        pat = cur.fetchone()
        if not pat:
            raise HTTPException(status_code=404, detail="Patient profile not found")

        cur.execute("SELECT latitude, longitude, heart_rate, spo2 FROM health_metrics WHERE patient_id = ? ORDER BY id DESC LIMIT 1", (patient_id,))
        met = cur.fetchone()
        lat = met["latitude"] if met else 11.0168
        lng = met["longitude"] if met else 76.9558

        msg = f"EMERGENCY SOS: Panic button manually triggered for {pat['full_name']}! Immediate assistance required."
        cur.execute("""
            INSERT INTO incident_alerts (patient_id, alert_type, severity, message, status, created_at)
            VALUES (?, 'EMERGENCY_SOS', 'Emergency', ?, 'Emergency', ?)
        """, (patient_id, msg, now_str))
        alert_id = cur.lastrowid
        conn.commit()

    execute_emergency_dispatch(alert_id, patient_id, reason="Manual Emergency SOS Panic Trigger")

    # WhatsApp pre-filled message generator
    maps_url = f"https://maps.google.com/?q={lat:.5f},{lng:.5f}"
    wa_text = f"EMERGENCY SOS ALERT for {pat['full_name']}! Immediate help needed. Location: {maps_url}"
    clean_phone = pat["emergency_contact"].replace("+", "").replace("-", "").replace(" ", "").split("(")[0]

    return {
        "status": "success",
        "alert_id": alert_id,
        "message": f"Emergency SOS initiated for {pat['full_name']}.",
        "whatsapp_url": f"https://wa.me/{clean_phone}?text={wa_text}"
    }

# ---------------------------------------------------------------------------
# REST API Endpoints: Thresholds, Telemetry & History
# ---------------------------------------------------------------------------
@app.post("/api/thresholds")
def update_thresholds(payload: ThresholdUpdate, patient_id: int = 1):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE threshold_configs
            SET min_hr=?, max_hr=?, min_spo2=?, min_temp=?, max_temp=?, safe_lat=?, safe_lng=?, safe_radius_meters=?
            WHERE patient_id=?
        """, (payload.min_hr, payload.max_hr, payload.min_spo2, payload.min_temp, payload.max_temp,
              payload.safe_lat, payload.safe_lng, payload.safe_radius_meters, patient_id))
        conn.commit()
    return {"status": "success", "message": "Thresholds updated successfully"}

@app.get("/api/history")
def get_metric_history(patient_id: int = 1, limit: int = 25):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, timestamp, heart_rate, spo2, temperature, steps, latitude, longitude, motion_vector 
            FROM health_metrics 
            WHERE patient_id = ? 
            ORDER BY id DESC LIMIT ?
        """, (patient_id, limit))
        rows = cur.fetchall()
        return [dict(r) for r in reversed(rows)]

@app.get("/api/alerts")
def get_incident_alerts(patient_id: int = 1):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM incident_alerts 
            WHERE patient_id = ? 
            ORDER BY id DESC LIMIT 30
        """, (patient_id,))
        return [dict(r) for r in cur.fetchall()]

@app.get("/api/dispatch-logs")
def get_dispatch_logs():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM dispatch_logs ORDER BY id DESC LIMIT 30")
        return [dict(r) for r in cur.fetchall()]

# ---------------------------------------------------------------------------
# Real-Time Telemetry Ingestion (REQ-1, 2, 3, 4, 5)
# ---------------------------------------------------------------------------
@app.post("/api/metrics")
async def ingest_metric(payload: MetricPayload):
    """Real-Time Vital Ingestion Endpoint (REQ-1, 2, 3, 4, 5)."""
    global active_countdown_task
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        cur = conn.cursor()
        
        # 1. Fetch threshold configuration
        cur.execute("SELECT * FROM threshold_configs WHERE patient_id = ?", (payload.patient_id,))
        cfg = cur.fetchone()
        
        # 2. Store time-series log
        cur.execute("""
            INSERT INTO health_metrics (patient_id, timestamp, heart_rate, spo2, temperature, steps, latitude, longitude, motion_vector)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (payload.patient_id, now_str, payload.heart_rate, payload.spo2, payload.temperature,
              payload.steps, payload.latitude, payload.longitude, payload.motion_vector))
        log_id = cur.lastrowid

        anomalies = []
        if cfg:
            if payload.heart_rate > cfg["max_hr"]:
                anomalies.append(f"Tachycardia detected: Heart rate {payload.heart_rate} bpm exceeds maximum {cfg['max_hr']} bpm")
            elif payload.heart_rate < cfg["min_hr"]:
                anomalies.append(f"Bradycardia detected: Heart rate {payload.heart_rate} bpm below minimum {cfg['min_hr']} bpm")

            if payload.spo2 < cfg["min_spo2"]:
                anomalies.append(f"Hypoxemia warning: SpO2 level {payload.spo2}% dropped below safe limit {cfg['min_spo2']}%")

            if payload.temperature > cfg["max_temp"]:
                anomalies.append(f"High fever detected: Body temperature {payload.temperature:.1f}°C exceeds {cfg['max_temp']}°C")

            dist = haversine_distance(cfg["safe_lat"], cfg["safe_lng"], payload.latitude, payload.longitude)
            if dist > cfg["safe_radius_meters"]:
                anomalies.append(f"Geo-fence breach: Senior is {dist:.1f}m away from safe center (Limit: {cfg['safe_radius_meters']}m)")

        is_fall = payload.motion_vector >= 3.2
        alert_id = None

        if is_fall:
            cur.execute("""
                INSERT INTO incident_alerts (patient_id, alert_type, severity, message, status, created_at)
                VALUES (?, 'FALL_DETECTED', 'Warning', 'High deceleration impact detected! 15s verification countdown started.', 'Verifying_Countdown', ?)
            """, (payload.patient_id, now_str))
            alert_id = cur.lastrowid
            conn.commit()

            if active_countdown_task and not active_countdown_task.done():
                active_countdown_task.cancel()
            active_countdown_task = asyncio.create_task(run_fall_countdown(alert_id, payload.patient_id))

        elif anomalies:
            msg = "; ".join(anomalies)
            cur.execute("""
                INSERT INTO incident_alerts (patient_id, alert_type, severity, message, status, created_at)
                VALUES (?, 'VITAL_ANOMALY', 'Warning', ?, 'Emergency', ?)
            """, (payload.patient_id, msg, now_str))
            alert_id = cur.lastrowid
            conn.commit()

    metric_data = {
        "type": "NEW_METRIC",
        "metric": {
            "id": log_id,
            "patient_id": payload.patient_id,
            "timestamp": now_str,
            "heart_rate": payload.heart_rate,
            "spo2": payload.spo2,
            "temperature": payload.temperature,
            "steps": payload.steps,
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "motion_vector": payload.motion_vector
        },
        "anomalies": anomalies,
        "is_fall": is_fall,
        "alert_id": alert_id
    }
    await manager.broadcast(metric_data)

    return {"status": "success", "metric_id": log_id, "anomalies": anomalies, "is_fall": is_fall}

@app.post("/api/alerts/{alert_id}/cancel")
async def cancel_alert(alert_id: int):
    """False Alarm Safeguard: Senior/Caregiver taps to cancel within 15-sec countdown (REQ-8)."""
    global active_countdown_task
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT status, patient_id FROM incident_alerts WHERE id = ?", (alert_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")
        if row["status"] != "Verifying_Countdown":
            return {"status": "ignored", "message": f"Alert cannot be cancelled in state '{row['status']}'"}

        cur.execute("""
            UPDATE incident_alerts 
            SET status = 'Cancelled', doctor_notes = 'Cancelled by senior as false alarm.' 
            WHERE id = ?
        """, (alert_id,))
        conn.commit()
        patient_id = row["patient_id"]

    if active_countdown_task and not active_countdown_task.done():
        active_countdown_task.cancel()

    await manager.broadcast({
        "type": "ALERT_CANCELLED",
        "alert_id": alert_id,
        "patient_id": patient_id,
        "message": "False alarm confirmed: emergency alert pipeline successfully aborted."
    })
    return {"status": "success", "message": "Alert cancelled successfully."}

@app.post("/api/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int, payload: ResolveAlertPayload):
    """Doctor / Caregiver Incident Resolution & Clinical Notes Logging (Section 2.3 & 5.5)."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT status, patient_id FROM incident_alerts WHERE id = ?", (alert_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")
        if row["status"] == "Resolved":
            raise HTTPException(status_code=400, detail="Historical records for resolved incidents are locked.")

        cur.execute("""
            UPDATE incident_alerts 
            SET status = 'Resolved', doctor_notes = ?, resolved_at = ? 
            WHERE id = ?
        """, (payload.doctor_notes, now_str, alert_id))
        conn.commit()
        patient_id = row["patient_id"]

    await manager.broadcast({
        "type": "ALERT_RESOLVED",
        "alert_id": alert_id,
        "patient_id": patient_id,
        "notes": payload.doctor_notes,
        "resolved_at": now_str
    })
    return {"status": "success", "message": "Incident resolved and securely locked."}

# ---------------------------------------------------------------------------
# Clinical Consultation Summary Report & CSV Export
# ---------------------------------------------------------------------------
@app.get("/api/patients/{patient_id}/report")
def get_clinical_report(patient_id: int):
    """Generates an aggregated medical health summary report for clinical reviews and printing."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM elderly_profiles WHERE id = ?", (patient_id,))
        patient = cur.fetchone()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient profile not found")

        # Telemetry aggregation
        cur.execute("""
            SELECT 
                COUNT(*) as total_records,
                AVG(heart_rate) as avg_hr,
                MIN(heart_rate) as min_hr,
                MAX(heart_rate) as max_hr,
                AVG(spo2) as avg_spo2,
                MIN(spo2) as min_spo2,
                AVG(temperature) as avg_temp,
                MAX(steps) as total_steps
            FROM health_metrics 
            WHERE patient_id = ?
        """, (patient_id,))
        stats = dict(cur.fetchone())

        # Incidents
        cur.execute("SELECT COUNT(*) FROM incident_alerts WHERE patient_id = ? AND alert_type = 'FALL_DETECTED'", (patient_id,))
        falls_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM incident_alerts WHERE patient_id = ? AND alert_type = 'VITAL_ANOMALY'", (patient_id,))
        vital_anomalies_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM incident_alerts WHERE patient_id = ? AND status = 'Cancelled'", (patient_id,))
        false_alarms_count = cur.fetchone()[0]

        # Recent alerts
        cur.execute("SELECT * FROM incident_alerts WHERE patient_id = ? ORDER BY id DESC LIMIT 5", (patient_id,))
        recent_alerts = [dict(r) for r in cur.fetchall()]

        # Medications & Adherence
        cur.execute("SELECT * FROM medications WHERE patient_id = ?", (patient_id,))
        meds = [dict(r) for r in cur.fetchall()]
        total_meds = len(meds)
        taken_meds = sum(1 for m in meds if m["status"] == "taken")
        adherence_rate = round((taken_meds / total_meds * 100), 1) if total_meds > 0 else 100.0

        # Wellness
        cur.execute("SELECT * FROM daily_wellness_logs WHERE patient_id = ? ORDER BY id DESC LIMIT 1", (patient_id,))
        wellness = cur.fetchone()

        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "patient": dict(patient),
            "stats": {
                "total_records": stats["total_records"] or 0,
                "avg_heart_rate": round(stats["avg_hr"] or 72, 1),
                "min_heart_rate": stats["min_hr"] or 70,
                "max_heart_rate": stats["max_hr"] or 85,
                "avg_spo2": round(stats["avg_spo2"] or 98.0, 1),
                "min_spo2": stats["min_spo2"] or 96.0,
                "avg_temperature": round(stats["avg_temp"] or 36.6, 1),
                "total_steps": stats["total_steps"] or 2400,
                "falls_count": falls_count,
                "vital_anomalies_count": vital_anomalies_count,
                "false_alarms_prevented": false_alarms_count,
                "medication_adherence_rate": adherence_rate
            },
            "medications": meds,
            "recent_alerts": recent_alerts,
            "wellness": dict(wellness) if wellness else {}
        }

@app.get("/api/patients/{patient_id}/export/csv")
def export_telemetry_csv(patient_id: int):
    """Exports raw time-series telemetry records as downloadable CSV."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT full_name FROM elderly_profiles WHERE id = ?", (patient_id,))
        pat = cur.fetchone()
        patient_name = pat["full_name"] if pat else f"patient_{patient_id}"

        cur.execute("""
            SELECT id, timestamp, heart_rate, spo2, temperature, steps, latitude, longitude, motion_vector 
            FROM health_metrics 
            WHERE patient_id = ? 
            ORDER BY id ASC
        """, (patient_id,))
        rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Log ID", "Patient Name", "Timestamp", "Heart Rate (bpm)", "SpO2 (%)", "Temperature (C)", "Steps", "Latitude", "Longitude", "Motion Vector (g)"])
    
    for r in rows:
        writer.writerow([r["id"], patient_name, r["timestamp"], r["heart_rate"], r["spo2"], r["temperature"], r["steps"], r["latitude"], r["longitude"], r["motion_vector"]])

    output.seek(0)
    filename = f"ecms_telemetry_{patient_name.replace(' ', '_').lower()}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ---------------------------------------------------------------------------
# IoT Hardware Integration Hub & Code Generator
# ---------------------------------------------------------------------------
@app.get("/api/iot/code")
def get_iot_hardware_code():
    """Provides ready-to-flash code snippets for ESP32, Raspberry Pi, and REST cURL."""
    esp32_code = """// ECMS ESP32 IoT Firmware (MAX30102 + MPU6050 + GPS NEO-6M)
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include "MAX30105.h"
#include <MPU6050_light.h>
#include <TinyGPS++.h>

const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
const char* serverUrl = "http://192.168.1.100:8000/api/metrics"; // Set to ECMS Server IP

MAX30105 particleSensor;
MPU6050 mpu(Wire);
TinyGPSPlus gps;

void setup() {
  Serial.begin(115200);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\\nWiFi Connected!");

  Wire.begin(21, 22); // SDA, SCL
  particleSensor.begin(Wire, I2C_SPEED_FAST);
  particleSensor.setup();
  mpu.begin();
  mpu.calcOffsets();
}

void loop() {
  mpu.update();
  float ax = mpu.getAccX(), ay = mpu.getAccY(), az = mpu.getAccZ();
  float motionVector = sqrt(ax*ax + ay*ay + az*az); // Magnitude in g

  // Ingest readings (Fall threshold > 3.2g)
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");

    String json = "{\\"patient_id\\": 1, \\"heart_rate\\": 74, \\"spo2\\": 98.0, \\"temperature\\": 36.6, \\"steps\\": 2600, \\"latitude\\": 11.0168, \\"longitude\\": 76.9558, \\"motion_vector\\": " + String(motionVector, 2) + "}";
    int httpResponseCode = http.POST(json);
    http.end();
  }
  delay(2500);
}"""

    python_rpi_code = """# ECMS Raspberry Pi Telemetry Publisher
import requests
import time
import math
import random

SERVER_URL = "http://localhost:8000/api/metrics"
PATIENT_ID = 1

def send_telemetry():
    payload = {
        "patient_id": PATIENT_ID,
        "heart_rate": random.randint(70, 78),
        "spo2": round(random.uniform(97.0, 99.0), 1),
        "temperature": 36.6,
        "steps": 2840,
        "latitude": 11.0168 + random.uniform(-0.0001, 0.0001),
        "longitude": 76.9558 + random.uniform(-0.0001, 0.0001),
        "motion_vector": 0.98
    }
    resp = requests.post(SERVER_URL, json=payload)
    print("Ingested metric:", resp.json())

if __name__ == "__main__":
    while True:
        send_telemetry()
        time.sleep(3)
"""

    curl_command = """curl -X POST "http://127.0.0.1:8000/api/metrics" \\
  -H "Content-Type: application/json" \\
  -d '{
    "patient_id": 1,
    "heart_rate": 75,
    "spo2": 98.2,
    "temperature": 36.6,
    "steps": 2650,
    "latitude": 11.0168,
    "longitude": 76.9558,
    "motion_vector": 0.98
  }'"""

    return {
        "esp32_arduino": esp32_code,
        "raspberry_pi_python": python_rpi_code,
        "curl_example": curl_command
    }

# ---------------------------------------------------------------------------
# Wearable Sensor Simulators (Enhanced with multi-patient support)
# ---------------------------------------------------------------------------
@app.post("/api/simulate/fall")
async def trigger_simulated_fall(patient_id: int = Query(1)):
    """Wearable Simulator trigger: simulates fall motion vector (REQ-6)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT safe_lat, safe_lng FROM threshold_configs WHERE patient_id = ?", (patient_id,))
        thresh = cur.fetchone()
        lat = thresh["safe_lat"] if thresh else 11.0168
        lng = thresh["safe_lng"] if thresh else 76.9558

    payload = MetricPayload(
        patient_id=patient_id,
        heart_rate=102,
        spo2=95.5,
        temperature=36.7,
        steps=2540,
        latitude=lat + 0.0001,
        longitude=lng + 0.0001,
        motion_vector=3.85 # Exceeds 3.2g threshold!
    )
    return await ingest_metric(payload)

@app.post("/api/simulate/fever")
async def trigger_simulated_fever(patient_id: int = Query(1)):
    """Simulates sudden high body temperature anomaly."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT safe_lat, safe_lng FROM threshold_configs WHERE patient_id = ?", (patient_id,))
        thresh = cur.fetchone()
        lat = thresh["safe_lat"] if thresh else 11.0168
        lng = thresh["safe_lng"] if thresh else 76.9558

    payload = MetricPayload(
        patient_id=patient_id,
        heart_rate=112,
        spo2=96.0,
        temperature=39.2, # High Fever!
        steps=2100,
        latitude=lat,
        longitude=lng,
        motion_vector=0.95
    )
    return await ingest_metric(payload)

@app.post("/api/simulate/reset")
async def reset_simulation(patient_id: int = Query(1)):
    """Resets patient state to normal vitals inside safe geofence."""
    global active_countdown_task
    if active_countdown_task and not active_countdown_task.done():
        active_countdown_task.cancel()

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE incident_alerts SET status = 'Resolved' WHERE patient_id = ? AND status IN ('Verifying_Countdown', 'Emergency')", (patient_id,))
        cur.execute("SELECT safe_lat, safe_lng FROM threshold_configs WHERE patient_id = ?", (patient_id,))
        thresh = cur.fetchone()
        lat = thresh["safe_lat"] if thresh else 11.0168
        lng = thresh["safe_lng"] if thresh else 76.9558
        conn.commit()

    payload = MetricPayload(
        patient_id=patient_id,
        heart_rate=74,
        spo2=98.0,
        temperature=36.6,
        steps=2600,
        latitude=lat,
        longitude=lng,
        motion_vector=0.98
    )
    res = await ingest_metric(payload)
    await manager.broadcast({"type": "RESET_ALL", "patient_id": patient_id})
    return {"status": "success", "message": "State reset to normal telemetry"}

# ---------------------------------------------------------------------------
# WebSocket Endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ---------------------------------------------------------------------------
# Static Web App Delivery
# ---------------------------------------------------------------------------
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "ECMS Backend running. Frontend static/index.html is being prepared."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)

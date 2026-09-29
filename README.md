# Elderly Care Monitoring System (ECMS)
**Software Requirement Specification (SRS) Implementation — Version 1.0**  
*Author: Kathiravan A (Coimbatore Institute of Technology)*

---

## 📌 Project Overview

The **Elderly Care Monitoring System (ECMS)** is an end-to-end, real-time IoT healthcare web application. It is designed to ingest, process, and visualize continuous health telemetry (Heart Rate, Blood Oxygen $\text{SpO}_2$, Temperature, Motion Vectors) and geographic location data from wearable trackers to safeguard senior citizens.

The application has been engineered to be **minimal in file count** (just 4 core files), cleanly written, and easy to explain during lab evaluations and project viva exams.

---

## 🗂️ Minimal File Structure

```text
ElderlyCareMonitoir/
├── server.py              # Asynchronous FastAPI backend, SQLite database, WebSockets, background timers (~350 lines)
├── requirements.txt       # Dependencies (fastapi, uvicorn, pydantic, websockets)
├── static/
│   ├── index.html         # Responsive, high-contrast, accessible medical dashboard & simulator
│   ├── style.css          # Modern dark healthcare theme with glassmorphism and emergency crimson styles
│   └── app.js             # WebSockets client, Leaflet GPS map, Chart.js trends, 15s countdown audio
└── README.md              # Project documentation & Lab Viva evaluation guide
```

---

## 🎯 SRS Functional Requirements (REQ-1 to REQ-10) Compliance Matrix

| Requirement ID | SRS Specification | Implementation in Codebase |
|---|---|---|
| **REQ-1** | Authenticate incoming metric streams | Pydantic payload models & patient ID validation in `server.py:ingest_metric` |
| **REQ-2** | Handle concurrent asynchronous incoming streams | Native Python `asyncio` & `FastAPI` non-blocking request handlers |
| **REQ-3** | Validate incoming metric structure ($\text{HR}$, $\text{SpO}_2$, Temp, Timestamp) | Strict field bounds validation via Pydantic (`MetricPayload`) |
| **REQ-4** | Store metrics in normalized time-series data table | SQLite `health_metrics` table mapped to `patient_id` |
| **REQ-5** | Instantly push updated data arrays to frontend dashboards | Persistent bi-directional WebSocket connection (`/ws`) via `ConnectionManager` |
| **REQ-6** | Trigger local verification state upon threshold-breaking motion vectors | Evaluates `motion_vector >= 3.2g`; flags `Verifying_Countdown` |
| **REQ-7** | Maintain non-blocking internal countdown mechanism | Asynchronous `asyncio.create_task(run_fall_countdown)` emitting 1-sec ticks |
| **REQ-8** | Abort alert pipeline immediately if cancellation received before expiry | False Alarm Safeguard via `POST /api/alerts/{id}/cancel` (stops dispatcher) |
| **REQ-9** | Extract latest GPS coordinates during active alarm dispatch | Queries latest `latitude` & `longitude` from `health_metrics` on dispatch |
| **REQ-10** | Route notifications to external API wrappers (SMS, Email, Push) | Automated Emergency Dispatcher logs multi-channel dispatches to `dispatch_logs` |

---

## 🗄️ Database Architecture (SRS Appendix B - ERD)

The system automatically initializes an embedded SQLite database (`ecms.db`) matching the SRS specification:

1. **`users`**: User identities, contact numbers, and roles (`Doctor`, `Family_Caregiver`, `Administrator`).
2. **`elderly_profiles`**: Monitored senior's details (Name, Age, Medical History, Primary Emergency Contact).
3. **`threshold_configs`** *(1:1 with Senior)*: Customizable boundaries for Min/Max Heart Rate, Min $\text{SpO}_2$, Temperature limits, and Safe Geo-fence coordinates and radius.
4. **`health_metrics`** *(1:N Time-Series Store)*: Continuous records with timestamp, $\text{HR}$, $\text{SpO}_2$, temperature, step count, latitude, longitude, and motion vector.
5. **`incident_alerts`**: Emergency logs tracking status (`Verifying_Countdown`, `Emergency`, `Resolved`, `Cancelled`) and doctor clinical notes.
6. **`dispatch_logs`**: Multi-channel notification audit trail (SMS, Email, Mobile Push token).

---

## 🚀 How to Run the Application

### 1. Prerequisites
- Python 3.10+ (Python 3.14 recommended)
- Modern web browser (Chrome, Edge, Firefox)

### 2. Setup Virtual Environment
```bash
# Navigate to project folder
cd c:\Users\kathi\ElderlyCareMonitoir

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Or Command Prompt:
.\venv\Scripts\activate.bat
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Start the Application Server
```bash
python server.py
```
*Or using uvicorn directly:*
```bash
uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

### 5. Access the Web Dashboard
Open your browser and navigate to:
```
http://127.0.0.1:8000
```

---

## 🧪 Interactive Lab Demonstration (Viva Guide)

The application includes a built-in **Wearable Sensor Simulator** bar at the bottom of the screen. You can demonstrate all SRS scenarios with a single click:

1. **Demonstrate Real-Time Telemetry & Charts (REQ-2, 3, 4, 5)**:
   - Click **"▶ Start Auto Stream"**.
   - Observe live Heart Rate and SpO2 curves updating dynamically on the Chart.js graph.
   - Observe the live Leaflet map updating the senior's GPS position in real-time.
2. **Demonstrate 15-Second Fall Safeguard (REQ-6, 7, 8)**:
   - Click **"🚨 Simulate Fall Impact (>3.2g)"**.
   - A high-visibility crimson warning modal appears with a 15-second countdown ring and audio warning beeps.
   - **Scenario A (False Alarm)**: Click **"🛡️ I AM OK — CANCEL ALERT"**. The alert is aborted, status returns to normal, and no emergency dispatch is sent.
   - **Scenario B (Actual Emergency)**: Click **"Simulate Fall Impact"** again and let the 15-second timer reach 0.
   - When the countdown finishes, the system enters **"CRITICAL EMERGENCY"**, sounds the alarm, extracts GPS coordinates, and dispatches multi-channel alerts (SMS, Email, Push) to the Emergency Dispatcher log!
3. **Demonstrate Vital Anomalies (Section 4.1)**:
   - Click **"📈 Tachycardia (135 bpm)"** &rarr; Shows Tachycardia warning.
   - Click **"📉 Hypoxemia (84% SpO2)"** &rarr; Shows low oxygen warning.
4. **Demonstrate Geo-Fencing (Section 1.2, 3.1)**:
   - Click **"🚶 Wander Out of Zone"**.
   - The senior's marker moves outside the safe perimeter. The safe zone turns red and triggers a **"BREACH: 550m away"** alert.
5. **Demonstrate Doctor Resolution & Record Locking (Section 2.3, 5.5)**:
   - Switch role to **"👨‍⚕️ Dr. Arvind Sharma (Doctor)"**.
   - In the Incident Action Tracker table, click **"Resolve & Sign Off"** next to an emergency.
   - Enter clinical notes (e.g., *"Patient checked via teleconsultation; vitals stabilized."*).
   - Once submitted, the incident status transitions to **Resolved** and is permanently locked (`🔒 Locked`) against retroactive editing.
6. **Reset State**:
   - Click **"🔄 Reset All to Normal"** to restore clean baseline telemetry anytime.

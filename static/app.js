/**
 * Elderly Care Monitoring System (ECMS) - Client Logic
 * Author: Kathiravan A (Coimbatore Institute of Technology)
 * Real-Time WebSockets, Chart.js trends, Leaflet GPS & 15s Fall Safeguard
 */

// Global State
let currentRole = "caregiver";
let ws = null;
let vitalsChart = null;
let map = null;
let patientMarker = null;
let geofenceCircle = null;
let audioEnabled = true;
let audioCtx = null;
let autoStreamTimer = null;
let activeCountdownAlertId = null;

let patientConfig = {
    min_hr: 55,
    max_hr: 105,
    min_spo2: 92.0,
    safe_lat: 11.0168,
    safe_lng: 76.9558,
    safe_radius_meters: 250.0
};

// ============================================================================
// Initialization on Page Load
// ============================================================================
document.addEventListener("DOMContentLoaded", async () => {
    initChart();
    initMap();
    await fetchPatientData();
    await loadMetricHistory();
    await loadIncidentAlerts();
    await loadDispatchLogs();
    connectWebSocket();
});

// ============================================================================
// Web Audio API Emergency Siren / Beep (No external MP3 needed)
// ============================================================================
function playBeep(freq = 880, duration = 0.15, type = "sine") {
    if (!audioEnabled) return;
    try {
        if (!audioCtx) {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (audioCtx.state === "suspended") {
            audioCtx.resume();
        }
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = type;
        osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
        gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + duration);
    } catch (e) {
        console.warn("Audio Context init error", e);
    }
}

function toggleAudio() {
    audioEnabled = !audioEnabled;
    const btn = document.getElementById("soundToggleBtn");
    btn.textContent = audioEnabled ? "🔊 Audio Alerts: ON" : "🔇 Audio Alerts: OFF";
}

// ============================================================================
// Role-Based Views
// ============================================================================
function switchRole(role) {
    currentRole = role;
    console.log(`Switched view to role: ${role}`);
    // Role-specific badge updates
    const titleRow = document.querySelector(".brand-subtitle");
    if (role === "doctor") {
        titleRow.textContent = "Medical Personnel & Clinical Diagnostics Portal";
    } else if (role === "admin") {
        titleRow.textContent = "System Administration & Infrastructure Operations";
    } else {
        titleRow.textContent = "Family Caregiver Live Monitoring & Safety Center";
    }
    loadIncidentAlerts();
}

// ============================================================================
// WebSocket Real-Time Ingestion & Alert Dispatch Listener
// ============================================================================
function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    const pill = document.getElementById("connectionPill");
    const statusText = document.getElementById("connStatusText");

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        pill.className = "status-pill status-connected";
        statusText.textContent = "Live WS Connected";
        console.log("WebSocket connected to ECMS backend");
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleIncomingSocketMessage(data);
        } catch (err) {
            console.error("Error parsing WS frame:", err);
        }
    };

    ws.onclose = () => {
        pill.className = "status-pill status-connecting";
        statusText.textContent = "Reconnecting...";
        setTimeout(connectWebSocket, 2000);
    };

    ws.onerror = () => {
        ws.close();
    };
}

function handleIncomingSocketMessage(data) {
    switch (data.type) {
        case "NEW_METRIC":
            updateMetricDisplay(data.metric, data.anomalies, data.is_fall);
            appendChartData(data.metric);
            updateMapPosition(data.metric.latitude, data.metric.longitude);
            if (data.anomalies && data.anomalies.length > 0) {
                playBeep(700, 0.25, "triangle");
                loadIncidentAlerts();
            }
            break;

        case "COUNTDOWN_TICK":
            handleCountdownTick(data.alert_id, data.remaining_seconds);
            break;

        case "ALERT_CANCELLED":
            handleAlertCancelled(data.alert_id);
            break;

        case "EMERGENCY_CONFIRMED":
            handleEmergencyConfirmed(data.alert_id, data.message);
            break;

        case "ALERT_RESOLVED":
            loadIncidentAlerts();
            break;

        case "RESET_ALL":
            resetUiDisplay();
            break;
    }
}

// ============================================================================
// Real-Time Metric Telemetry Updates
// ============================================================================
function updateMetricDisplay(metric, anomalies = [], is_fall = false) {
    document.getElementById("valHeartRate").textContent = metric.heart_rate;
    document.getElementById("valSpO2").textContent = metric.spo2.toFixed(1);
    document.getElementById("valTemp").textContent = metric.temperature.toFixed(1);
    document.getElementById("valMotion").textContent = metric.motion_vector.toFixed(2);
    document.getElementById("valSteps").textContent = metric.steps.toLocaleString();
    document.getElementById("lastSyncTime").textContent = metric.timestamp;

    // Heart Rate Bounds
    const hrStatus = document.getElementById("hrStatus");
    if (metric.heart_rate > patientConfig.max_hr) {
        hrStatus.textContent = "Tachycardia High";
        hrStatus.className = "badge badge-emergency";
    } else if (metric.heart_rate < patientConfig.min_hr) {
        hrStatus.textContent = "Bradycardia Low";
        hrStatus.className = "badge badge-warning";
    } else {
        hrStatus.textContent = "Normal";
        hrStatus.className = "badge badge-success";
    }

    // SpO2 Bounds
    const spo2Status = document.getElementById("spo2Status");
    if (metric.spo2 < patientConfig.min_spo2) {
        spo2Status.textContent = "Hypoxemia Low";
        spo2Status.className = "badge badge-emergency";
    } else {
        spo2Status.textContent = "Optimal";
        spo2Status.className = "badge badge-success";
    }

    // Motion status
    const motionStatus = document.getElementById("motionStatus");
    if (metric.motion_vector >= 3.2 || is_fall) {
        motionStatus.textContent = "HIGH IMPACT FALL";
        motionStatus.className = "badge badge-emergency";
    } else {
        motionStatus.textContent = "Steady";
        motionStatus.className = "badge badge-success";
    }

    // Overall Status
    const overallBadge = document.getElementById("patientStatusBadge");
    if (is_fall || (anomalies && anomalies.length > 0)) {
        overallBadge.textContent = "Status: Warning Anomaly";
        overallBadge.className = "badge badge-warning";
    } else {
        overallBadge.textContent = "Status: Normal";
        overallBadge.className = "badge badge-normal";
    }
}

// ============================================================================
// 15-Second Fall Safeguard Engine (REQ-6, 7, 8)
// ============================================================================
function handleCountdownTick(alertId, remaining) {
    activeCountdownAlertId = alertId;
    const modal = document.getElementById("fallCountdownModal");
    const numDisplay = document.getElementById("countdownNumber");
    const strokeCircle = document.getElementById("countdownStroke");

    modal.classList.remove("hidden");
    numDisplay.textContent = remaining;

    // SVG stroke dash animation (radius 45 -> circumference 283)
    const circumference = 283;
    const offset = circumference - (remaining / 15) * circumference;
    strokeCircle.style.strokeDashoffset = offset;

    // Pulse audible warning tone on each countdown second
    playBeep(920, 0.12, "square");

    // Change patient overall status banner
    const badge = document.getElementById("patientStatusBadge");
    badge.textContent = `Fall Verification: ${remaining}s`;
    badge.className = "badge badge-emergency";
}

async function cancelActiveAlert() {
    if (!activeCountdownAlertId) return;
    try {
        const res = await fetch(`/api/alerts/${activeCountdownAlertId}/cancel`, { method: "POST" });
        const data = await res.json();
        console.log("Alert cancel response:", data);
        handleAlertCancelled(activeCountdownAlertId);
    } catch (err) {
        console.error("Failed to cancel alert", err);
    }
}

function handleAlertCancelled(alertId) {
    activeCountdownAlertId = null;
    const modal = document.getElementById("fallCountdownModal");
    modal.classList.add("hidden");

    const badge = document.getElementById("patientStatusBadge");
    badge.textContent = "Status: Normal (False Alarm Cancelled)";
    badge.className = "badge badge-normal";

    playBeep(440, 0.3, "sine"); // reassuring low tone
    loadIncidentAlerts();
}

function handleEmergencyConfirmed(alertId, message) {
    activeCountdownAlertId = null;
    const modal = document.getElementById("fallCountdownModal");
    modal.classList.add("hidden");

    const badge = document.getElementById("patientStatusBadge");
    badge.textContent = "STATUS: CRITICAL EMERGENCY DISPATCHED";
    badge.className = "badge badge-emergency";

    // Continuous loud alarm sound for confirmed emergency
    playBeep(1200, 0.6, "sawtooth");
    
    loadIncidentAlerts();
    loadDispatchLogs();
}

// ============================================================================
// Chart.js Live Historical Trend Initializer
// ============================================================================
function initChart() {
    const ctx = document.getElementById("vitalsChart").getContext("2d");
    vitalsChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                {
                    label: "Heart Rate (bpm)",
                    data: [],
                    borderColor: "#f43f5e",
                    backgroundColor: "rgba(244, 63, 94, 0.08)",
                    borderWidth: 2.5,
                    tension: 0.35,
                    fill: true,
                    pointRadius: 3,
                    pointHoverRadius: 6,
                    yAxisID: "y"
                },
                {
                    label: "SpO2 (%)",
                    data: [],
                    borderColor: "#06b6d4",
                    backgroundColor: "transparent",
                    borderWidth: 2,
                    borderDash: [4, 4],
                    tension: 0.3,
                    pointRadius: 2,
                    yAxisID: "y1"
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: "index",
                intersect: false
            },
            plugins: {
                legend: {
                    labels: { color: "#94a3b8", font: { family: "Inter", size: 11 } }
                }
            },
            scales: {
                x: {
                    grid: { color: "rgba(255, 255, 255, 0.05)" },
                    ticks: { color: "#64748b", font: { size: 10 }, maxTicksLimit: 6 }
                },
                y: {
                    type: "linear",
                    position: "left",
                    min: 40,
                    max: 160,
                    grid: { color: "rgba(255, 255, 255, 0.05)" },
                    ticks: { color: "#f43f5e", font: { size: 10 } },
                    title: { display: true, text: "BPM", color: "#f43f5e" }
                },
                y1: {
                    type: "linear",
                    position: "right",
                    min: 75,
                    max: 100,
                    grid: { drawOnChartArea: false },
                    ticks: { color: "#06b6d4", font: { size: 10 } },
                    title: { display: true, text: "SpO2 %", color: "#06b6d4" }
                }
            }
        }
    });
}

function appendChartData(metric) {
    if (!vitalsChart) return;
    const timeLabel = metric.timestamp.split(" ")[1] || metric.timestamp;
    
    vitalsChart.data.labels.push(timeLabel);
    vitalsChart.data.datasets[0].data.push(metric.heart_rate);
    vitalsChart.data.datasets[1].data.push(metric.spo2);

    // Maintain recent 20 points
    if (vitalsChart.data.labels.length > 20) {
        vitalsChart.data.labels.shift();
        vitalsChart.data.datasets[0].data.shift();
        vitalsChart.data.datasets[1].data.shift();
    }
    vitalsChart.update("none");
}

async function loadMetricHistory() {
    try {
        const res = await fetch("/api/history?limit=15");
        const history = await res.json();
        if (Array.isArray(history)) {
            history.forEach(m => {
                const timeLabel = m.timestamp.split(" ")[1] || m.timestamp;
                vitalsChart.data.labels.push(timeLabel);
                vitalsChart.data.datasets[0].data.push(m.heart_rate);
                vitalsChart.data.datasets[1].data.push(m.spo2);
            });
            vitalsChart.update();
        }
    } catch (e) {
        console.error("Failed to load metric history:", e);
    }
}

// ============================================================================
// Leaflet Map & Geo-fencing
// ============================================================================
function initMap() {
    const lat = patientConfig.safe_lat;
    const lng = patientConfig.safe_lng;

    map = L.map("mapContainer", { zoomControl: false }).setView([lat, lng], 16);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    L.control.zoom({ position: "bottomright" }).addTo(map);

    // Create Geo-fence Circle
    geofenceCircle = L.circle([lat, lng], {
        color: "#10b981",
        fillColor: "#10b981",
        fillOpacity: 0.18,
        radius: patientConfig.safe_radius_meters
    }).addTo(map);

    // Create Patient Marker
    const patientIcon = L.divIcon({
        className: "custom-patient-pin",
        html: '<div style="background:#2563eb; width:22px; height:22px; border-radius:50%; border:3px solid #ffffff; box-shadow:0 0 12px #2563eb;"></div>',
        iconSize: [22, 22],
        iconAnchor: [11, 11]
    });

    patientMarker = L.marker([lat, lng], { icon: patientIcon }).addTo(map);
    patientMarker.bindPopup("<b>Robert Jenkins</b><br>Safe Zone Tracker").openPopup();
}

function updateMapPosition(lat, lng) {
    if (!map || !patientMarker) return;
    patientMarker.setLatLng([lat, lng]);

    document.getElementById("mapLat").textContent = `${lat.toFixed(4)}° N`;
    document.getElementById("mapLng").textContent = `${lng.toFixed(4)}° E`;

    // Distance to safe center
    const safeLatLng = L.latLng(patientConfig.safe_lat, patientConfig.safe_lng);
    const currentLatLng = L.latLng(lat, lng);
    const dist = safeLatLng.distanceTo(currentLatLng);

    const pill = document.getElementById("geofenceStatusPill");
    const txt = document.getElementById("geofenceText");

    if (dist > patientConfig.safe_radius_meters) {
        pill.className = "status-pill status-danger";
        txt.textContent = `BREACH: ${Math.round(dist)}m away`;
        if (geofenceCircle) {
            geofenceCircle.setStyle({ color: "#ef4444", fillColor: "#ef4444" });
        }
    } else {
        pill.className = "status-pill status-safe";
        txt.textContent = "Safe in Zone";
        if (geofenceCircle) {
            geofenceCircle.setStyle({ color: "#10b981", fillColor: "#10b981" });
        }
    }
}

// ============================================================================
// Incident Action Tracker & Resolution
// ============================================================================
async function loadIncidentAlerts() {
    try {
        const res = await fetch("/api/alerts");
        const alerts = await res.json();
        const tbody = document.getElementById("incidentTableBody");
        tbody.innerHTML = "";

        if (!alerts || alerts.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No safety incidents recorded.</td></tr>`;
            return;
        }

        alerts.forEach(a => {
            const tr = document.createElement("tr");

            let statusBadge = "badge-normal";
            if (a.status === "Emergency") statusBadge = "badge-emergency";
            else if (a.status === "Verifying_Countdown") statusBadge = "badge-warning";
            else if (a.status === "Cancelled") statusBadge = "badge-age";

            let actionBtn = "";
            if (a.status === "Emergency") {
                actionBtn = `<button class="btn btn-sm btn-primary" onclick="openResolveModal(${a.id})">Resolve & Sign Off</button>`;
            } else if (a.status === "Resolved") {
                actionBtn = `<span class="text-muted" title="Historical records locked">🔒 Locked</span>`;
            } else {
                actionBtn = `<span class="text-muted">—</span>`;
            }

            tr.innerHTML = `
                <td>#${a.id}</td>
                <td><strong>${a.alert_type}</strong></td>
                <td><span class="badge ${a.severity === 'Emergency' ? 'badge-emergency' : 'badge-warning'}">${a.severity}</span></td>
                <td>${a.message}</td>
                <td><span class="badge ${statusBadge}">${a.status}</span></td>
                <td>${a.doctor_notes || '<em class="text-muted">Pending review</em>'}</td>
                <td>${actionBtn}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Failed to load incidents:", e);
    }
}

function openResolveModal(alertId) {
    document.getElementById("resolveAlertId").value = alertId;
    document.getElementById("doctorNotesInput").value = "";
    document.getElementById("resolveModal").classList.remove("hidden");
}

function closeResolveModal() {
    document.getElementById("resolveModal").classList.add("hidden");
}

async function submitIncidentResolution(event) {
    event.preventDefault();
    const alertId = document.getElementById("resolveAlertId").value;
    const notes = document.getElementById("doctorNotesInput").value;

    try {
        const res = await fetch(`/api/alerts/${alertId}/resolve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ doctor_notes: notes })
        });
        if (res.ok) {
            closeResolveModal();
            loadIncidentAlerts();
        }
    } catch (e) {
        console.error("Failed to resolve alert:", e);
    }
}

// ============================================================================
// Multi-Channel Emergency Dispatch Log (REQ-10)
// ============================================================================
async function loadDispatchLogs() {
    try {
        const res = await fetch("/api/dispatch-logs");
        const logs = await res.json();
        const container = document.getElementById("dispatchLogList");

        if (!logs || logs.length === 0) {
            container.innerHTML = `<div class="empty-state">No emergency dispatches issued yet. System running in safe baseline.</div>`;
            return;
        }

        container.innerHTML = "";
        logs.forEach(log => {
            const item = document.createElement("div");
            item.className = "dispatch-item";
            item.innerHTML = `
                <div class="dispatch-meta">
                    <span class="dispatch-channel">[${log.channel}] &rarr; ${log.recipient}</span>
                    <span>${log.dispatched_at}</span>
                </div>
                <div class="dispatch-payload">${log.payload}</div>
            `;
            container.appendChild(item);
        });
    } catch (e) {
        console.error("Failed to load dispatch logs:", e);
    }
}

// ============================================================================
// Thresholds & Patient Profile Config
// ============================================================================
async function fetchPatientData() {
    try {
        const res = await fetch("/api/patient");
        const data = await res.json();
        if (data.profile) {
            document.getElementById("patientName").textContent = data.profile.full_name;
            document.getElementById("patientAge").textContent = `Age: ${data.profile.age}`;
            document.getElementById("patientHistory").textContent = `Conditions: ${data.profile.medical_history}`;
            document.getElementById("patientEmergencyContact").textContent = `${data.profile.emergency_contact} (Primary Caregiver)`;
        }
        if (data.thresholds) {
            patientConfig = data.thresholds;
            document.getElementById("hrThresholdText").textContent = `Safe Range: ${patientConfig.min_hr} - ${patientConfig.max_hr} bpm`;
            document.getElementById("spo2ThresholdText").textContent = `Safe: ≥ ${patientConfig.min_spo2}%`;
            document.getElementById("mapRadius").textContent = `${patientConfig.safe_radius_meters} meters`;
        }
        if (data.latest_metric) {
            updateMetricDisplay(data.latest_metric);
            updateMapPosition(data.latest_metric.latitude, data.latest_metric.longitude);
        }
    } catch (e) {
        console.error("Failed to fetch patient data:", e);
    }
}

function openThresholdModal() {
    document.getElementById("inputMinHr").value = patientConfig.min_hr;
    document.getElementById("inputMaxHr").value = patientConfig.max_hr;
    document.getElementById("inputMinSpO2").value = patientConfig.min_spo2;
    document.getElementById("inputRadius").value = patientConfig.safe_radius_meters;
    document.getElementById("inputSafeLat").value = patientConfig.safe_lat;
    document.getElementById("inputSafeLng").value = patientConfig.safe_lng;
    document.getElementById("thresholdModal").classList.remove("hidden");
}

function closeThresholdModal() {
    document.getElementById("thresholdModal").classList.add("hidden");
}

async function saveThresholds(event) {
    event.preventDefault();
    const updated = {
        min_hr: parseInt(document.getElementById("inputMinHr").value),
        max_hr: parseInt(document.getElementById("inputMaxHr").value),
        min_spo2: parseFloat(document.getElementById("inputMinSpO2").value),
        min_temp: 36.0,
        max_temp: 37.8,
        safe_lat: parseFloat(document.getElementById("inputSafeLat").value),
        safe_lng: parseFloat(document.getElementById("inputSafeLng").value),
        safe_radius_meters: parseFloat(document.getElementById("inputRadius").value)
    };

    try {
        const res = await fetch("/api/thresholds", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(updated)
        });
        if (res.ok) {
            patientConfig = updated;
            document.getElementById("hrThresholdText").textContent = `Safe Range: ${patientConfig.min_hr} - ${patientConfig.max_hr} bpm`;
            document.getElementById("spo2ThresholdText").textContent = `Safe: ≥ ${patientConfig.min_spo2}%`;
            document.getElementById("mapRadius").textContent = `${patientConfig.safe_radius_meters} meters`;
            if (geofenceCircle) {
                geofenceCircle.setRadius(patientConfig.safe_radius_meters);
                geofenceCircle.setLatLng([patientConfig.safe_lat, patientConfig.safe_lng]);
            }
            closeThresholdModal();
        }
    } catch (e) {
        console.error("Failed to save thresholds:", e);
    }
}

// ============================================================================
// Interactive Wearable Sensor Simulator Controls (For Demos & Viva!)
// ============================================================================
function toggleAutoStream() {
    const btn = document.getElementById("autoStreamBtn");
    if (autoStreamTimer) {
        clearInterval(autoStreamTimer);
        autoStreamTimer = null;
        btn.textContent = "▶ Start Auto Stream";
        btn.classList.remove("btn-stream-active");
    } else {
        btn.textContent = "⏸ Stop Auto Stream";
        btn.classList.add("btn-stream-active");
        autoStreamTimer = setInterval(sendRandomHealthyMetric, 2500);
        sendRandomHealthyMetric();
    }
}

async function sendMetricPayload(payload) {
    try {
        const res = await fetch("/api/metrics", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        return await res.json();
    } catch (e) {
        console.error("Failed to push metric payload:", e);
    }
}

function sendRandomHealthyMetric() {
    const hr = Math.floor(70 + Math.random() * 10);
    const spo2 = +(97 + Math.random() * 2).toFixed(1);
    const temp = +(36.4 + Math.random() * 0.4).toFixed(1);
    const steps = parseInt(document.getElementById("valSteps").textContent.replace(",", "")) + Math.floor(Math.random() * 4);
    
    // Slight jitter around safe center
    const lat = patientConfig.safe_lat + (Math.random() - 0.5) * 0.0003;
    const lng = patientConfig.safe_lng + (Math.random() - 0.5) * 0.0003;

    sendMetricPayload({
        patient_id: 1,
        heart_rate: hr,
        spo2: spo2,
        temperature: temp,
        steps: steps,
        latitude: lat,
        longitude: lng,
        motion_vector: 0.98 + (Math.random() * 0.1)
    });
}

function triggerFallSimulation() {
    fetch("/api/simulate/fall", { method: "POST" });
}

function simulateTachycardia() {
    sendMetricPayload({
        patient_id: 1,
        heart_rate: 135,
        spo2: 96.5,
        temperature: 36.8,
        steps: 2750,
        latitude: patientConfig.safe_lat,
        longitude: patientConfig.safe_lng,
        motion_vector: 1.15
    });
}

function simulateLowSpO2() {
    sendMetricPayload({
        patient_id: 1,
        heart_rate: 88,
        spo2: 84.0, // Hypoxemia!
        temperature: 36.5,
        steps: 2750,
        latitude: patientConfig.safe_lat,
        longitude: patientConfig.safe_lng,
        motion_vector: 0.92
    });
}

function simulateGeofenceBreach() {
    // Shift coordinate ~550 meters away
    const breachLat = patientConfig.safe_lat + 0.0050;
    const breachLng = patientConfig.safe_lng + 0.0050;

    sendMetricPayload({
        patient_id: 1,
        heart_rate: 82,
        spo2: 97.0,
        temperature: 36.6,
        steps: 3100,
        latitude: breachLat,
        longitude: breachLng,
        motion_vector: 1.05
    });
}

async function resetToNormal() {
    if (autoStreamTimer) {
        clearInterval(autoStreamTimer);
        autoStreamTimer = null;
        document.getElementById("autoStreamBtn").textContent = "▶ Start Auto Stream";
    }
    await fetch("/api/simulate/reset", { method: "POST" });
    await fetchPatientData();
    await loadIncidentAlerts();
    await loadDispatchLogs();
}

function resetUiDisplay() {
    document.getElementById("patientStatusBadge").textContent = "Status: Normal";
    document.getElementById("patientStatusBadge").className = "badge badge-normal";
    document.getElementById("fallCountdownModal").classList.add("hidden");
    if (geofenceCircle) {
        geofenceCircle.setStyle({ color: "#10b981", fillColor: "#10b981" });
    }
}

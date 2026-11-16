import json
import math
import os
import threading
import time
from functools import wraps
from flask import Flask, Response, jsonify, render_template, request, session, stream_with_context
from flask_cors import CORS
from werkzeug.security import check_password_hash
from database import get_db, init_db

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "pace-smart-bus-secret-2026")
CORS(app)

EARTH_RADIUS_KM = 6371.0
MIN_CRUISING_SPEED_KMH = 15.0
STALE_THRESHOLD_SEC = 30.0

LATEST_CACHE = {}
UPDATE_CONDITION = threading.Condition()


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def compute_eta_minutes(distance_km: float, speed_mps: float) -> tuple[float, float]:
    speed_kmh = max(0.0, speed_mps * 3.6)
    effective_v = max(speed_kmh, MIN_CRUISING_SPEED_KMH)
    eta_min = (distance_km / effective_v) * 60.0
    return round(eta_min, 1), round(speed_kmh, 1)


def warm_cache():
    conn = get_db()
    buses = conn.execute("SELECT bus_id FROM BUS").fetchall()
    for b in buses:
        row = conn.execute(
            "SELECT latitude, longitude, speed, timestamp FROM LOCATION WHERE bus_id = ? ORDER BY timestamp DESC LIMIT 1",
            (b["bus_id"],),
        ).fetchone()
        if row:
            LATEST_CACHE[b["bus_id"]] = {
                "lat": row["latitude"],
                "lon": row["longitude"],
                "speed": row["speed"],
                "ts": row["timestamp"],
            }
    conn.close()


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_user"):
            return jsonify(error="Unauthorized admin access"), 401
        return f(*args, **kwargs)
    return decorated


def build_bus_payload(bus_id: str, rec: dict) -> dict:
    age_sec = round(max(0.0, time.time() - rec["ts"]), 1)
    return {
        "bus_id": bus_id,
        "lat": rec["lat"],
        "lon": rec["lon"],
        "speed_mps": rec["speed"],
        "speed_kmh": round(rec["speed"] * 3.6, 1),
        "timestamp": rec["ts"],
        "age_sec": age_sec,
        "stale": age_sec > STALE_THRESHOLD_SEC,
    }


# -------------------- HTML VIEWS --------------------

@app.route("/")
def passenger_view():
    return render_template("passenger.html")


@app.route("/driver")
def driver_view():
    return render_template("driver.html")


@app.route("/admin")
def admin_view():
    return render_template("admin.html")


# -------------------- REST API + REAL-TIME SSE STREAM --------------------

@app.route("/api/location", methods=["POST"])
def update_location():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify(error="invalid payload"), 400

    try:
        bus_id = str(d["bus_id"]).strip()
        lat = float(d["lat"])
        lon = float(d["lon"])
        speed = float(d.get("speed", 0.0) or 0.0)
    except (KeyError, ValueError, TypeError):
        return jsonify(error="invalid payload"), 400

    if not bus_id or math.isnan(lat) or math.isnan(lon) or math.isnan(speed):
        return jsonify(error="invalid payload"), 400

    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0) or speed < 0:
        return jsonify(error="out of range"), 400

    conn = get_db()
    bus = conn.execute("SELECT bus_id, api_token FROM BUS WHERE bus_id = ?", (bus_id,)).fetchone()
    if not bus:
        conn.close()
        return jsonify(error="unknown bus_id"), 404

    token = request.headers.get("X-Bus-Token")
    if token and token != bus["api_token"]:
        conn.close()
        return jsonify(error="invalid bus token"), 403

    now = time.time()
    conn.execute(
        "INSERT INTO LOCATION (bus_id, latitude, longitude, speed, timestamp) VALUES (?, ?, ?, ?, ?)",
        (bus_id, lat, lon, speed, now),
    )
    conn.commit()
    conn.close()

    with UPDATE_CONDITION:
        LATEST_CACHE[bus_id] = {"lat": lat, "lon": lon, "speed": speed, "ts": now}
        UPDATE_CONDITION.notify_all()

    return jsonify(status="ok", bus_id=bus_id, timestamp=now)


@app.route("/api/stream/<bus_id>", methods=["GET"])
def stream_bus(bus_id: str):
    if bus_id not in LATEST_CACHE:
        conn = get_db()
        bus = conn.execute("SELECT bus_id FROM BUS WHERE bus_id = ?", (bus_id,)).fetchone()
        conn.close()
        if not bus:
            return jsonify(error="bus not found"), 404

    @stream_with_context
    def event_stream():
        last_ts = -1.0
        while True:
            rec = LATEST_CACHE.get(bus_id)
            if rec and rec["ts"] != last_ts:
                last_ts = rec["ts"]
                payload = json.dumps(build_bus_payload(bus_id, rec))
                yield "data: " + payload + "\n\n"
            else:
                if rec:
                    payload = json.dumps(build_bus_payload(bus_id, rec))
                    yield "data: " + payload + "\n\n"
            with UPDATE_CONDITION:
                UPDATE_CONDITION.wait(timeout=2.0)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(event_stream(), mimetype="text/event-stream", headers=headers)


@app.route("/api/bus/<bus_id>", methods=["GET"])
def get_bus_location(bus_id: str):
    rec = LATEST_CACHE.get(bus_id)
    if not rec:
        conn = get_db()
        bus = conn.execute("SELECT bus_id FROM BUS WHERE bus_id = ?", (bus_id,)).fetchone()
        if not bus:
            conn.close()
            return jsonify(error="bus not found"), 404
        row = conn.execute(
            "SELECT latitude, longitude, speed, timestamp FROM LOCATION WHERE bus_id = ? ORDER BY timestamp DESC LIMIT 1",
            (bus_id,),
        ).fetchone()
        conn.close()
        if not row:
            return jsonify(error="no location recorded yet"), 404
        rec = {
            "lat": row["latitude"],
            "lon": row["longitude"],
            "speed": row["speed"],
            "ts": row["timestamp"],
        }
        LATEST_CACHE[bus_id] = rec

    return jsonify(build_bus_payload(bus_id, rec))


@app.route("/api/eta/<bus_id>/<int:stop_index>", methods=["GET"])
def get_eta(bus_id: str, stop_index: int):
    conn = get_db()
    bus = conn.execute("SELECT bus_id, route_id FROM BUS WHERE bus_id = ?", (bus_id,)).fetchone()
    if not bus:
        conn.close()
        return jsonify(error="bus not found"), 404

    stops = conn.execute(
        "SELECT stop_id, name, latitude, longitude, sequence FROM STOP WHERE route_id = ? ORDER BY sequence ASC",
        (bus["route_id"],),
    ).fetchall()
    conn.close()

    if stop_index < 0 or stop_index >= len(stops):
        return jsonify(error="invalid stop index"), 404

    rec = LATEST_CACHE.get(bus_id)
    if not rec:
        return jsonify(error="no location data for bus"), 404

    target = stops[stop_index]
    dist_km = haversine(rec["lat"], rec["lon"], target["latitude"], target["longitude"])
    eta_min, speed_kmh = compute_eta_minutes(dist_km, rec["speed"])
    age_sec = round(max(0.0, time.time() - rec["ts"]), 1)

    return jsonify(
        bus_id=bus_id,
        stop_index=stop_index,
        stop_name=target["name"],
        distance_km=round(dist_km, 2),
        eta_min=eta_min,
        speed_kmh=speed_kmh,
        stale=age_sec > STALE_THRESHOLD_SEC,
        age_sec=age_sec,
    )


@app.route("/api/routes", methods=["GET"])
def get_routes():
    conn = get_db()
    routes = conn.execute("SELECT * FROM ROUTE ORDER BY route_id ASC").fetchall()
    result = []
    for r in routes:
        stops = conn.execute(
            "SELECT stop_id, name, latitude, longitude, sequence FROM STOP WHERE route_id = ? ORDER BY sequence ASC",
            (r["route_id"],),
        ).fetchall()
        buses = conn.execute(
            "SELECT bus_id, bus_number, driver_id, route_id FROM BUS WHERE route_id = ? ORDER BY bus_id ASC",
            (r["route_id"],),
        ).fetchall()
        result.append({
            "route_id": r["route_id"],
            "route_name": r["route_name"],
            "start": r["start"],
            "destination": r["destination"],
            "color": r["color"],
            "stops": [dict(s) for s in stops],
            "buses": [dict(b) for b in buses],
        })
    conn.close()
    return jsonify(routes=result)


@app.route("/api/history/<bus_id>", methods=["GET"])
def get_location_history(bus_id: str):
    limit = min(int(request.args.get("limit", 30)), 200)
    conn = get_db()
    rows = conn.execute(
        "SELECT latitude, longitude, speed, timestamp FROM LOCATION WHERE bus_id = ? ORDER BY timestamp DESC LIMIT ?",
        (bus_id, limit),
    ).fetchall()
    conn.close()
    return jsonify(bus_id=bus_id, history=[dict(r) for r in reversed(rows)])


# -------------------- ADMIN ENDPOINTS --------------------

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    d = request.get_json(silent=True) or {}
    username = str(d.get("username", "")).strip()
    password = str(d.get("password", ""))
    conn = get_db()
    user = conn.execute("SELECT username, password_hash FROM ADMIN WHERE username = ?", (username,)).fetchone()
    conn.close()
    if user and check_password_hash(user["password_hash"], password):
        session["admin_user"] = username
        return jsonify(status="ok", username=username)
    return jsonify(error="Invalid credentials"), 401


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin_user", None)
    return jsonify(status="ok")


@app.route("/api/admin/status", methods=["GET"])
def admin_status():
    return jsonify(authenticated=bool(session.get("admin_user")), username=session.get("admin_user"))


@app.route("/api/admin/route", methods=["POST"])
@admin_required
def admin_add_route():
    d = request.get_json(silent=True) or {}
    route_id = str(d.get("route_id", "")).strip().upper()
    route_name = str(d.get("route_name", "")).strip()
    start = str(d.get("start", "")).strip()
    destination = str(d.get("destination", "")).strip()
    color = str(d.get("color", "#2563eb")).strip() or "#2563eb"

    if not all([route_id, route_name, start, destination]):
        return jsonify(error="All route fields are required"), 400

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO ROUTE (route_id, route_name, start, destination, color) VALUES (?, ?, ?, ?, ?)",
            (route_id, route_name, start, destination, color),
        )
        conn.commit()
    except Exception as exc:
        conn.close()
        return jsonify(error=f"Could not create route: {exc}"), 400
    conn.close()
    return jsonify(status="ok", route_id=route_id)


@app.route("/api/admin/bus", methods=["POST"])
@admin_required
def admin_add_bus():
    d = request.get_json(silent=True) or {}
    bus_id = str(d.get("bus_id", "")).strip().upper()
    bus_number = str(d.get("bus_number", "")).strip().upper()
    driver_id = str(d.get("driver_id", "")).strip()
    route_id = str(d.get("route_id", "")).strip().upper()
    api_token = str(d.get("api_token", f"tok_{bus_id.lower()}_pace")).strip()

    if not all([bus_id, bus_number, driver_id, route_id]):
        return jsonify(error="All bus fields are required"), 400

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO BUS (bus_id, bus_number, driver_id, route_id, api_token) VALUES (?, ?, ?, ?, ?)",
            (bus_id, bus_number, driver_id, route_id, api_token),
        )
        first_stop = conn.execute(
            "SELECT latitude, longitude FROM STOP WHERE route_id = ? ORDER BY sequence ASC LIMIT 1",
            (route_id,),
        ).fetchone()
        if first_stop:
            now = time.time()
            conn.execute(
                "INSERT INTO LOCATION (bus_id, latitude, longitude, speed, timestamp) VALUES (?, ?, ?, ?, ?)",
                (bus_id, first_stop["latitude"], first_stop["longitude"], 0.0, now),
            )
            with UPDATE_CONDITION:
                LATEST_CACHE[bus_id] = {
                    "lat": first_stop["latitude"],
                    "lon": first_stop["longitude"],
                    "speed": 0.0,
                    "ts": now,
                }
                UPDATE_CONDITION.notify_all()
        conn.commit()
    except Exception as exc:
        conn.close()
        return jsonify(error=f"Could not add bus: {exc}"), 400
    conn.close()
    return jsonify(status="ok", bus_id=bus_id, api_token=api_token)


init_db()
warm_cache()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)

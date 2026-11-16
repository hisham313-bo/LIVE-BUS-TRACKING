import os
import tempfile
import time
import pytest

db_fd, temp_db = tempfile.mkstemp(suffix=".db")
os.environ["BUS_DB_PATH"] = temp_db

from app import app, LATEST_CACHE, haversine  # noqa: E402


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_haversine_worked_example():
    d = haversine(12.8950, 74.9850, 12.9000, 74.9900)
    assert round(d, 2) == 0.78


def test_t1_t2_driver_location_update_and_fetch(client):
    res = client.post(
        "/api/location",
        json={"bus_id": "B101", "lat": 12.8632, "lon": 74.8725, "speed": 10.0},
    )
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"

    get_res = client.get("/api/bus/B101")
    assert get_res.status_code == 200
    body = get_res.get_json()
    assert body["lat"] == 12.8632
    assert body["lon"] == 74.8725
    assert body["stale"] is False


def test_t3_invalid_payload_and_out_of_range(client):
    r1 = client.post("/api/location", json={"bus_id": "B101"})
    assert r1.status_code == 400

    r2 = client.post("/api/location", json={"bus_id": "B101", "lat": 125.0, "lon": 74.8})
    assert r2.status_code == 400

    r3 = client.post("/api/location", json={"bus_id": "B101", "lat": 12.8, "lon": 210.0})
    assert r3.status_code == 400


def test_t4_t5_stale_data_flag_and_recovery(client):
    LATEST_CACHE["B101"]["ts"] = time.time() - 35.0
    stale_res = client.get("/api/bus/B101").get_json()
    assert stale_res["stale"] is True

    client.post("/api/location", json={"bus_id": "B101", "lat": 12.8520, "lon": 74.9180, "speed": 8.0})
    fresh_res = client.get("/api/bus/B101").get_json()
    assert fresh_res["stale"] is False


def test_t6_unknown_bus_returns_404(client):
    res = client.get("/api/bus/B999")
    assert res.status_code == 404


def test_t7_t8_routes_and_eta_minimum_speed_guard(client):
    routes = client.get("/api/routes").get_json()["routes"]
    assert len(routes) >= 3

    client.post("/api/location", json={"bus_id": "B101", "lat": 12.8520, "lon": 74.9180, "speed": 0.0})
    eta_res = client.get("/api/eta/B101/4")
    assert eta_res.status_code == 200
    eta_body = eta_res.get_json()
    assert eta_body["distance_km"] > 0
    assert eta_body["eta_min"] > 0

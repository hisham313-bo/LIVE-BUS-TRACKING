import sqlite3
import os
import time
from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get("BUS_DB_PATH", "smart_bus.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS ROUTE (
        route_id TEXT PRIMARY KEY,
        route_name TEXT NOT NULL,
        start TEXT NOT NULL,
        destination TEXT NOT NULL,
        color TEXT DEFAULT '#2563eb'
    );

    CREATE TABLE IF NOT EXISTS BUS (
        bus_id TEXT PRIMARY KEY,
        bus_number TEXT NOT NULL,
        driver_id TEXT NOT NULL,
        route_id TEXT NOT NULL,
        api_token TEXT NOT NULL,
        FOREIGN KEY (route_id) REFERENCES ROUTE(route_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS STOP (
        stop_id INTEGER PRIMARY KEY AUTOINCREMENT,
        route_id TEXT NOT NULL,
        name TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        sequence INTEGER NOT NULL,
        FOREIGN KEY (route_id) REFERENCES ROUTE(route_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS LOCATION (
        location_id INTEGER PRIMARY KEY AUTOINCREMENT,
        bus_id TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        speed REAL DEFAULT 0.0,
        timestamp REAL NOT NULL,
        FOREIGN KEY (bus_id) REFERENCES BUS(bus_id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_location_bus_ts ON LOCATION(bus_id, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_stop_route_seq ON STOP(route_id, sequence ASC);

    CREATE TABLE IF NOT EXISTS ADMIN (
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL
    );
    """)

    cur.execute("SELECT COUNT(*) FROM ADMIN")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO ADMIN (username, password_hash) VALUES (?, ?)",
            ("admin", generate_password_hash("pace2026")),
        )

    cur.execute("SELECT COUNT(*) FROM ROUTE")
    if cur.fetchone()[0] == 0:
        routes = [
            ("R1", "Campus Express - Hampankatta", "Hampankatta", "PACE Campus", "#2563eb"),
            ("R2", "Coastal Link - Thokkottu", "Thokkottu", "PACE Campus", "#059669"),
            ("R3", "Highway Line - BC Road", "BC Road", "PACE Campus", "#d97706"),
        ]
        cur.executemany(
            "INSERT INTO ROUTE (route_id, route_name, start, destination, color) VALUES (?, ?, ?, ?, ?)",
            routes,
        )

        buses = [
            ("B101", "KA-19-AB-1101", "DRV-01 (Ramesh)", "R1", "tok_b101_pace"),
            ("B102", "KA-19-AB-1102", "DRV-02 (Suresh)", "R2", "tok_b102_pace"),
            ("B103", "KA-19-AB-1103", "DRV-03 (Mahesh)", "R3", "tok_b103_pace"),
        ]
        cur.executemany(
            "INSERT INTO BUS (bus_id, bus_number, driver_id, route_id, api_token) VALUES (?, ?, ?, ?, ?)",
            buses,
        )

        stops = [
            ("R1", "Hampankatta Junction", 12.8698, 74.8430, 1),
            ("R1", "Kankanady Circle", 12.8685, 74.8588, 2),
            ("R1", "Pumpwell Flyover", 12.8632, 74.8725, 3),
            ("R1", "Adyar Katte", 12.8520, 74.9180, 4),
            ("R1", "P A College of Engineering (PACE)", 12.8055, 74.9333, 5),

            ("R2", "Thokkottu Junction", 12.8152, 74.8565, 1),
            ("R2", "Deralakatte Junction", 12.8110, 74.8850, 2),
            ("R2", "Natekal", 12.8045, 74.9085, 3),
            ("R2", "P A College of Engineering (PACE)", 12.8055, 74.9333, 4),

            ("R3", "BC Road Bus Stand", 12.8810, 74.9980, 1),
            ("R3", "Farangipete", 12.8690, 74.9560, 2),
            ("R3", "Arkula", 12.8615, 74.9350, 3),
            ("R3", "P A College of Engineering (PACE)", 12.8055, 74.9333, 4),
        ]
        cur.executemany(
            "INSERT INTO STOP (route_id, name, latitude, longitude, sequence) VALUES (?, ?, ?, ?, ?)",
            stops,
        )

        now = time.time()
        init_locs = [
            ("B101", 12.8685, 74.8588, 8.0, now),
            ("B102", 12.8110, 74.8850, 7.5, now),
            ("B103", 12.8690, 74.9560, 9.5, now),
        ]
        cur.executemany(
            "INSERT INTO LOCATION (bus_id, latitude, longitude, speed, timestamp) VALUES (?, ?, ?, ?, ?)",
            init_locs,
        )

    conn.commit()
    conn.close()

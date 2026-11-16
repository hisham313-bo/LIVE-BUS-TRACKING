# Smart Bus Live Tracking System (True Real-Time Edition)

Complete full-stack real-time implementation of:
**"Smart Bus Live Tracking System: Real-Time Bus Location and Route Monitoring Using GPS and Web Technologies"**
*Department of Computer Science and Engineering, P A College of Engineering (PACE), Academic Year 2026-27.*

## Real-Time Architecture Upgrades
- **Instant Server-Sent Events (SSE) Push (`/api/stream/<bus_id>`):** Passenger maps receive live GPS packets the exact millisecond the driver device posts them (`threading.Condition` + `EventSource`), eliminating 3-second polling lag.
- **Real Smartphone GPS + Screen Wake Lock (`/driver`):** Defaults to `navigator.geolocation.watchPosition({ enableHighAccuracy: true })` and acquires `navigator.wakeLock.request("screen")` so the driver's phone continues streaming smoothly over mobile data.
- **Cloud-Ready Deployment (`Procfile` + `gunicorn`):** Preconfigured with `gthread` workers for concurrent SSE passenger connections on Render, Railway, or ngrok HTTPS tunnels.

## Quick Start (Local)
```bash
cd smart_bus_tracker
pip install -r requirements.txt
python app.py
```

## Go Live on Real Phones (HTTPS)
1. **Quick Tunnel (Local Laptop -> Real Phones):**
   Run `ngrok http 5000` and open the generated `https://...` link on the driver's smartphone (`/driver`) and passengers' phones (`/`).
2. **Permanent Cloud Hosting (Render / Railway):**
   Push `smart_bus_tracker/` to GitHub, connect it as a Python Web Service (uses `Procfile` automatically), and open your live `https://` URL.

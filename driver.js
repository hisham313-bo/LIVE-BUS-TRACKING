let routesMap = {};
let busToRoute = {};
let trackingTimer = null;
let geoWatchId = null;
let wakeLock = null;
let lastSentMs = 0;
let simStep = 0;

if (window.location.protocol !== "https:" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
  document.getElementById("httpsWarning").style.display = "block";
}

function logMsg(text) {
  const box = document.getElementById("txLog");
  const ts = new Date().toLocaleTimeString();
  box.innerHTML += `<div>[${ts}] ${text}</div>`;
  box.scrollTop = box.scrollHeight;
}

async function requestWakeLock() {
  try {
    if ("wakeLock" in navigator) {
      wakeLock = await navigator.wakeLock.request("screen");
      logMsg("Screen Wake Lock active (prevents GPS sleep during trip).");
    }
  } catch (err) {
    logMsg(`Wake Lock unavailable: ${err.message}`);
  }
}

function releaseWakeLock() {
  if (wakeLock) {
    wakeLock.release().catch(() => {});
    wakeLock = null;
  }
}

async function initDriver() {
  const res = await fetch("/api/routes");
  const data = await res.json();
  const sel = document.getElementById("driverBusSelect");
  sel.innerHTML = "";

  (data.routes || []).forEach(r => {
    routesMap[r.route_id] = r;
    r.buses.forEach(b => {
      busToRoute[b.bus_id] = r;
      const opt = document.createElement("option");
      opt.value = b.bus_id;
      opt.textContent = `${b.bus_id} (${b.bus_number}) - ${r.route_name}`;
      sel.appendChild(opt);
    });
  });
}

function getSimulatedCoord(busId) {
  const route = busToRoute[busId];
  const stops = route ? route.stops : [];
  if (stops.length < 2) {
    return { lat: 12.8055, lon: 74.9333 };
  }
  const totalSegments = stops.length - 1;
  const stepsPerSeg = 12;
  const totalSteps = totalSegments * stepsPerSeg;
  const pos = simStep % totalSteps;
  const segIdx = Math.floor(pos / stepsPerSeg);
  const t = (pos % stepsPerSeg) / stepsPerSeg;

  const s1 = stops[segIdx];
  const s2 = stops[segIdx + 1];
  simStep += 1;

  return {
    lat: Number((s1.latitude + (s2.latitude - s1.latitude) * t).toFixed(6)),
    lon: Number((s1.longitude + (s2.longitude - s1.longitude) * t).toFixed(6))
  };
}

async function postLocation(busId, lat, lon, speedMps) {
  try {
    const res = await fetch("/api/location", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bus_id: busId, lat, lon, speed: speedMps })
    });
    const data = await res.json();
    if (res.ok) {
      logMsg(`PUSH -> 200 OK | bus=${busId} (${lat.toFixed(5)}, ${lon.toFixed(5)}) speed=${(speedMps * 3.6).toFixed(1)} km/h`);
    } else {
      logMsg(`ERROR ${res.status}: ${data.error}`);
    }
  } catch (err) {
    logMsg("NetworkError: skipped stale cycle, retrying next fix");
  }
}

async function startTracking() {
  const busId = document.getElementById("driverBusSelect").value;
  const mode = document.getElementById("modeSelect").value;
  const intervalMs = Number(document.getElementById("intervalSelect").value);

  document.getElementById("startBtn").disabled = true;
  document.getElementById("stopBtn").disabled = false;
  lastSentMs = 0;
  await requestWakeLock();
  logMsg(`Started LIVE tracking ${busId} in [${mode.toUpperCase()}] mode (T=${intervalMs / 1000}s)`);

  if (mode === "gps") {
    if (!navigator.geolocation) {
      logMsg("Geolocation API not supported in this browser.");
      stopTracking();
      return;
    }
    geoWatchId = navigator.geolocation.watchPosition(
      p => {
        const now = Date.now();
        if (now - lastSentMs >= intervalMs) {
          lastSentMs = now;
          postLocation(busId, p.coords.latitude, p.coords.longitude, p.coords.speed || 0);
        }
      },
      err => {
        logMsg(`GPS Warning (${err.code}): ${err.message}`);
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 10000 }
    );
  } else {
    const tick = () => {
      const speedKmh = Math.max(0, Number(document.getElementById("simSpeedInput").value) || 0);
      const speedMps = speedKmh / 3.6;
      const coord = getSimulatedCoord(busId);
      postLocation(busId, coord.lat, coord.lon, speedMps);
    };
    tick();
    trackingTimer = setInterval(tick, intervalMs);
  }
}

function stopTracking() {
  if (trackingTimer) {
    clearInterval(trackingTimer);
    trackingTimer = null;
  }
  if (geoWatchId !== null) {
    navigator.geolocation.clearWatch(geoWatchId);
    geoWatchId = null;
  }
  releaseWakeLock();
  document.getElementById("startBtn").disabled = false;
  document.getElementById("stopBtn").disabled = true;
  logMsg("Tracking stopped.");
}

document.getElementById("startBtn").addEventListener("click", startTracking);
document.getElementById("stopBtn").addEventListener("click", stopTracking);
document.getElementById("sendOnceBtn").addEventListener("click", () => {
  const busId = document.getElementById("driverBusSelect").value;
  const mode = document.getElementById("modeSelect").value;
  if (mode === "gps" && navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(p => {
      postLocation(busId, p.coords.latitude, p.coords.longitude, p.coords.speed || 0);
    }, err => logMsg(`GPS Error: ${err.message}`), { enableHighAccuracy: true });
  } else {
    const speedKmh = Math.max(0, Number(document.getElementById("simSpeedInput").value) || 0);
    const coord = getSimulatedCoord(busId);
    postLocation(busId, coord.lat, coord.lon, speedKmh / 3.6);
  }
});

initDriver();

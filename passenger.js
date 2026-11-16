let routesData = [];
let busRouteMap = {};
let selectedBusId = null;
let selectedStopIdx = 0;
let activeEventSource = null;

const map = L.map("map").setView([12.835, 74.900], 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);

let routeLayer = L.layerGroup().addTo(map);
let busMarker = null;

function createBusIcon(busId, isStale) {
  return L.divIcon({
    className: `bus-marker-icon ${isStale ? "stale" : ""}`,
    html: busId,
    iconSize: [32, 32],
    iconAnchor: [16, 16]
  });
}

async function loadRoutesAndBuses() {
  const res = await fetch("/api/routes");
  const data = await res.json();
  routesData = data.routes || [];

  const busSelect = document.getElementById("busSelect");
  busSelect.innerHTML = "";
  busRouteMap = {};

  routesData.forEach(route => {
    route.buses.forEach(bus => {
      busRouteMap[bus.bus_id] = { bus, route };
      const opt = document.createElement("option");
      opt.value = bus.bus_id;
      opt.textContent = `${bus.bus_id} (${bus.bus_number}) - ${route.route_name}`;
      busSelect.appendChild(opt);
    });
  });

  if (busSelect.options.length > 0) {
    selectedBusId = busSelect.options[0].value;
    onBusChanged(true);
  }
}

function onBusChanged(fitMap = false) {
  const entry = busRouteMap[selectedBusId];
  if (!entry) return;

  const { route } = entry;
  const stopSelect = document.getElementById("stopSelect");
  const stopsList = document.getElementById("stopsList");
  stopSelect.innerHTML = "";
  stopsList.innerHTML = "";

  routeLayer.clearLayers();
  const latlngs = [];

  route.stops.forEach((stop, idx) => {
    const opt = document.createElement("option");
    opt.value = idx;
    opt.textContent = `${stop.sequence}. ${stop.name}`;
    stopSelect.appendChild(opt);

    const li = document.createElement("li");
    li.textContent = `${stop.sequence}. ${stop.name}`;
    li.dataset.idx = idx;
    li.addEventListener("click", () => {
      selectedStopIdx = idx;
      stopSelect.value = idx;
      highlightSelectedStop();
      refreshEtaOnly();
    });
    stopsList.appendChild(li);

    const ll = [stop.latitude, stop.longitude];
    latlngs.push(ll);
    L.circleMarker(ll, {
      radius: 6,
      color: route.color || "#2563eb",
      fillColor: "#ffffff",
      fillOpacity: 1,
      weight: 2.5
    })
      .bindPopup(`<strong>Stop ${stop.sequence}:</strong> ${stop.name}`)
      .addTo(routeLayer);
  });

  if (latlngs.length > 1) {
    const poly = L.polyline(latlngs, {
      color: route.color || "#2563eb",
      weight: 4,
      opacity: 0.75
    }).addTo(routeLayer);
    if (fitMap) {
      map.fitBounds(poly.getBounds(), { padding: [35, 35] });
    }
  }

  selectedStopIdx = Math.max(0, route.stops.length - 1);
  stopSelect.value = selectedStopIdx;
  highlightSelectedStop();
  subscribeRealTimeStream(selectedBusId);
}

function highlightSelectedStop() {
  document.querySelectorAll("#stopsList li").forEach(li => {
    li.classList.toggle("selected-stop", Number(li.dataset.idx) === Number(selectedStopIdx));
  });
}

function renderBusState(busData) {
  const entry = busRouteMap[selectedBusId];
  if (!entry) return;

  const pos = [busData.lat, busData.lon];
  if (!busMarker) {
    busMarker = L.marker(pos, { icon: createBusIcon(selectedBusId, busData.stale) }).addTo(map);
  } else {
    busMarker.setLatLng(pos);
    busMarker.setIcon(createBusIcon(selectedBusId, busData.stale));
  }

  busMarker.bindPopup(
    `<strong>${selectedBusId}</strong> (${entry.bus.bus_number})<br/>` +
    `Speed: ${busData.speed_kmh} km/h<br/>` +
    `Last seen: ${busData.age_sec}s ago`
  );

  document.getElementById("panelBusTitle").textContent = `${selectedBusId} (${entry.bus.bus_number})`;
  document.getElementById("panelRoute").textContent = entry.route.route_name;
  document.getElementById("panelSpeed").textContent = `${busData.speed_kmh} km/h`;
  document.getElementById("panelSeen").textContent = busData.age_sec < 1 ? "Just now" : `${busData.age_sec} s ago`;

  const pill = document.getElementById("statusPill");
  if (busData.stale) {
    pill.textContent = "STALE (>30s)";
    pill.className = "pill pill-stale";
  } else {
    pill.textContent = "LIVE";
    pill.className = "pill pill-live";
  }

  refreshEtaOnly();
}

async function refreshEtaOnly() {
  if (!selectedBusId) return;
  try {
    const etaRes = await fetch(`/api/eta/${encodeURIComponent(selectedBusId)}/${selectedStopIdx}`);
    if (etaRes.ok) {
      const etaData = await etaRes.json();
      document.getElementById("panelStop").textContent = etaData.stop_name;
      document.getElementById("panelEta").textContent = `~ ${etaData.eta_min} min`;
      document.getElementById("panelDist").textContent = `${etaData.distance_km} km`;
    }
  } catch (e) {
    console.warn("ETA fetch warning:", e);
  }
}

function subscribeRealTimeStream(busId) {
  if (activeEventSource) {
    activeEventSource.close();
    activeEventSource = null;
  }

  // Immediate initial fetch
  fetch(`/api/bus/${encodeURIComponent(busId)}`)
    .then(r => (r.ok ? r.json() : null))
    .then(data => { if (data) renderBusState(data); });

  // Open real-time Server-Sent Events (SSE) push channel
  const streamEl = document.getElementById("panelStream");
  streamEl.textContent = "Connecting...";

  activeEventSource = new EventSource(`/api/stream/${encodeURIComponent(busId)}`);
  activeEventSource.onopen = () => {
    streamEl.textContent = "Real-Time Push (SSE)";
  };
  activeEventSource.onmessage = event => {
    const busData = JSON.parse(event.data);
    renderBusState(busData);
  };
  activeEventSource.onerror = () => {
    streamEl.textContent = "Reconnecting...";
  };
}

document.getElementById("busSelect").addEventListener("change", e => {
  selectedBusId = e.target.value;
  if (busMarker) {
    map.removeLayer(busMarker);
    busMarker = null;
  }
  onBusChanged(true);
});

document.getElementById("stopSelect").addEventListener("change", e => {
  selectedStopIdx = Number(e.target.value);
  highlightSelectedStop();
  refreshEtaOnly();
});

document.getElementById("refreshBtn").addEventListener("click", () => {
  if (selectedBusId) subscribeRealTimeStream(selectedBusId);
});

loadRoutesAndBuses();

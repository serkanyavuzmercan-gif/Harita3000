const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const LEAFLET_HEAT_JS = "https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js";
const ROUTE_COLOR = "#1f6f5b";
const TRACK_COLOR = "#2563eb";
const ENTITY_COLORS = {
  customer: "#2563eb",
  supplier: "#ea580c",
  competitor: "#dc2626",
  other: "#6b7280",
};
const ENTITY_LABELS = {
  customer: "Müşteri",
  supplier: "Tedarikçi",
  competitor: "Rakip",
  other: "Diğer",
};
const COMPANY_COLOR = "#7c3aed";
const SEARCH_COLOR = "#122033";
const VEHICLE_COLORS = { moving: "#16a34a", parked: "#a16207", stale: "#9ca3af" };
const loadedAssets = new Map();

const HaritaMap = {
  impl: null,
  provider: "",
  ready: false,
  fitted: false,
  handlers: { moved: null },

  async mount(element, config) {
    if (!element) return false;
    this.destroy();
    const useGoogle = config.provider === "google" && Boolean(config.google_maps_api_key);
    const impl = useGoogle ? GoogleLayer : OsmLayer;
    await impl.mount(element, config);
    this.impl = impl;
    this.provider = useGoogle ? "google" : "osm";
    this.ready = true;
    return true;
  },

  destroy() {
    if (this.impl) this.impl.destroy();
    this.impl = null;
    this.provider = "";
    this.ready = false;
    this.fitted = false;
  },

  setData(data, role, layers) {
    if (!this.ready) return;
    const show = { customer: true, supplier: true, competitor: true, other: true, company: true, vehicles: true, ...(layers || {}) };
    const canMove = role === "admin";
    const moved = (kind, id, name) => (lat, lng) => {
      if (this.handlers.moved) this.handlers.moved(kind, id, lat, lng, name);
    };
    const pins = [];
    (data.entities || []).forEach((entity) => {
      if (!show[entity.type]) return;
      pins.push({
        key: `e-${entity.id}`,
        lat: entity.latitude,
        lng: entity.longitude,
        color: ENTITY_COLORS[entity.type] || ENTITY_COLORS.other,
        shape: "pin",
        html: entityHtml(entity, role),
        draggable: canMove,
        onMoved: moved("entity", entity.id, entity.name),
      });
    });
    if (show.company) {
      (data.company_locations || []).forEach((location) => {
        pins.push({
          key: `c-${location.id}`,
          lat: location.latitude,
          lng: location.longitude,
          color: COMPANY_COLOR,
          shape: "star",
          html: locationHtml(location),
          draggable: canMove,
          onMoved: moved("location", location.id, location.name),
        });
      });
    }
    if (show.vehicles) {
      (data.vehicles || []).forEach((vehicle) => {
        const state = vehicleState(vehicle);
        pins.push({
          key: `v-${vehicle.id}`,
          lat: vehicle.latitude,
          lng: vehicle.longitude,
          color: VEHICLE_COLORS[state],
          shape: "pin",
          moving: state === "moving",
          html: vehicleHtml(vehicle, state),
        });
      });
    }
    this.impl.setPins(pins, !this.fitted);
    if (pins.length) this.fitted = true;
  },

  focus(entityId) {
    this.focusKey(`e-${entityId}`);
  },

  focusKey(key) {
    if (this.ready) this.impl.focus(key);
  },

  setHeatmap(enabled, points) {
    if (!this.ready) return Promise.resolve();
    return this.impl.setHeatmap(enabled, points || []);
  },

  drawRoute(origin, stops) {
    if (!this.ready) return Promise.reject(new Error("Harita hazır değil"));
    if (!stops.length) return Promise.reject(new Error("Durak seçin"));
    return this.impl.route([asPoint(origin), ...stops.map(asPoint)]);
  },

  clearRoute() {
    if (this.ready) this.impl.clearRoute();
  },

  enablePick(callback) {
    if (!this.ready) return false;
    this.impl.enablePick((lat, lng) => {
      this.impl.disablePick();
      callback(Math.round(lat * 1e6) / 1e6, Math.round(lng * 1e6) / 1e6);
    });
    return true;
  },

  disablePick() {
    if (this.ready) this.impl.disablePick();
  },

  showTrack(points, stops) {
    if (!this.ready) return;
    this.impl.showTrack(
      points.map((point) => [point.lat, point.lng]),
      (stops || []).map((stop) => ({
        lat: stop.latitude,
        lng: stop.longitude,
        label: String(stop.index),
        title: stopTitle(stop),
      })),
    );
  },

  clearTrack() {
    if (this.ready) this.impl.clearTrack();
  },

  center() {
    return this.ready ? this.impl.center() : null;
  },

  showSearchResult(lat, lng, label) {
    if (this.ready) this.impl.showSearchResult(lat, lng, label);
  },

  clearSearchResult() {
    if (this.ready) this.impl.clearSearchResult();
  },

  // Resolves to null when the active provider has no type-ahead (OpenStreetMap forbids it).
  suggest(input, near) {
    if (!this.ready || !this.impl.suggest) return Promise.resolve(null);
    return this.impl.suggest(input, near);
  },
};

const OsmLayer = {
  map: null,
  layer: null,
  markers: new Map(),
  heat: null,
  routeLine: null,
  track: null,
  pickHandler: null,
  searchMarker: null,

  async mount(element, config) {
    await loadLeaflet();
    this.map = L.map(element, { zoomControl: true }).setView([config.center_lat, config.center_lng], config.zoom);
    L.tileLayer(config.tile_url, { maxZoom: 19, attribution: config.tile_attribution }).addTo(this.map);
    this.layer = L.layerGroup().addTo(this.map);
    setTimeout(() => this.map && this.map.invalidateSize(), 0);
  },

  destroy() {
    this.disablePick();
    if (this.map) this.map.remove();
    this.map = null;
    this.layer = null;
    this.heat = null;
    this.routeLine = null;
    this.track = null;
    this.searchMarker = null;
    this.markers = new Map();
  },

  setPins(pins, fit) {
    this.layer.clearLayers();
    this.markers = new Map();
    pins.forEach((pin) => {
      const marker = L.marker([pin.lat, pin.lng], {
        draggable: Boolean(pin.draggable),
        zIndexOffset: pin.shape === "star" ? 500 : 0,
        icon: L.divIcon({
          className: "",
          html: `<div class="${pin.moving ? "pin-moving" : ""}">${iconSvg(pin)}</div>`,
          iconSize: [32, 42],
          iconAnchor: [16, 42],
          popupAnchor: [0, -38],
        }),
      });
      marker.bindPopup(pin.html, { maxWidth: 300 });
      if (pin.draggable && pin.onMoved) {
        marker.on("dragend", () => {
          const position = marker.getLatLng();
          pin.onMoved(position.lat, position.lng);
        });
      }
      marker.addTo(this.layer);
      this.markers.set(pin.key, marker);
    });
    if (fit && pins.length) {
      this.map.fitBounds(L.latLngBounds(pins.map((pin) => [pin.lat, pin.lng])), { padding: [48, 48], maxZoom: 14 });
    }
  },

  focus(key) {
    const marker = this.markers.get(key);
    if (!marker) return;
    this.map.setView(marker.getLatLng(), Math.max(this.map.getZoom(), 14));
    marker.openPopup();
  },

  async setHeatmap(enabled, points) {
    if (!enabled) {
      if (this.heat) this.map.removeLayer(this.heat);
      return;
    }
    await loadScriptOnce(LEAFLET_HEAT_JS);
    if (!this.map) return;
    const data = points.map((point) => [point.latitude, point.longitude, 1]);
    if (!this.heat) this.heat = L.heatLayer(data, { radius: 32, blur: 24, maxZoom: 14 });
    else this.heat.setLatLngs(data);
    this.heat.addTo(this.map);
  },

  async route(points) {
    const result = await API.request("/api/logistics/route", {
      method: "POST",
      body: JSON.stringify({ points: points.map((point) => ({ latitude: point.lat, longitude: point.lng })) }),
    });
    this.clearRoute();
    this.routeLine = L.polyline(result.coordinates, { color: ROUTE_COLOR, weight: 5, opacity: 0.9 }).addTo(this.map);
    this.map.fitBounds(this.routeLine.getBounds(), { padding: [48, 48] });
    return { distanceKm: result.distance_km, durationMin: result.duration_min };
  },

  clearRoute() {
    if (this.routeLine) this.map.removeLayer(this.routeLine);
    this.routeLine = null;
  },

  enablePick(callback) {
    this.disablePick();
    this.pickHandler = (event) => callback(event.latlng.lat, event.latlng.lng);
    this.map.on("click", this.pickHandler);
    this.map.getContainer().style.cursor = "crosshair";
  },

  disablePick() {
    if (!this.map) return;
    if (this.pickHandler) this.map.off("click", this.pickHandler);
    this.pickHandler = null;
    this.map.getContainer().style.cursor = "";
  },

  showTrack(coords, stops) {
    this.clearTrack();
    if (!coords.length) return;
    const group = L.layerGroup();
    L.polyline(coords, { color: TRACK_COLOR, weight: 4, opacity: 0.85 }).addTo(group);
    L.circleMarker(coords[0], { radius: 7, color: "#fff", weight: 2, fillColor: "#16a34a", fillOpacity: 1 })
      .bindTooltip("Başlangıç").addTo(group);
    L.circleMarker(coords[coords.length - 1], { radius: 7, color: "#fff", weight: 2, fillColor: "#dc2626", fillOpacity: 1 })
      .bindTooltip("Son konum").addTo(group);
    stops.forEach((stop) => {
      L.marker([stop.lat, stop.lng], {
        icon: L.divIcon({ className: "", html: stopBadge(stop.label), iconSize: [24, 24], iconAnchor: [12, 12] }),
      }).bindTooltip(stop.title).addTo(group);
    });
    this.track = group.addTo(this.map);
    this.map.fitBounds(L.latLngBounds(coords), { padding: [48, 48] });
  },

  clearTrack() {
    if (this.track && this.map) this.map.removeLayer(this.track);
    this.track = null;
  },

  center() {
    const point = this.map.getCenter();
    return { lat: point.lat, lng: point.lng };
  },

  showSearchResult(lat, lng, label) {
    this.clearSearchResult();
    this.searchMarker = L.marker([lat, lng], {
      zIndexOffset: 1000,
      icon: L.divIcon({ className: "", html: pinSvg(SEARCH_COLOR), iconSize: [32, 42], iconAnchor: [16, 42] }),
    })
      .bindTooltip(esc(label), { direction: "top", offset: [0, -40] })
      .addTo(this.map);
    this.map.setView([lat, lng], Math.max(this.map.getZoom(), 16));
    this.searchMarker.openTooltip();
  },

  clearSearchResult() {
    if (this.searchMarker && this.map) this.map.removeLayer(this.searchMarker);
    this.searchMarker = null;
  },
};

const GoogleLayer = {
  map: null,
  info: null,
  markers: new Map(),
  heat: null,
  directionsService: null,
  directionsRenderer: null,
  pickListener: null,
  trackItems: [],
  searchMarker: null,
  placesLib: undefined,
  sessionToken: null,

  async mount(element, config) {
    await loadGoogle(config.google_maps_api_key);
    this.map = new google.maps.Map(element, {
      center: { lat: config.center_lat, lng: config.center_lng },
      zoom: config.zoom,
      mapTypeControl: false,
      streetViewControl: false,
      fullscreenControl: true,
      styles: [
        { featureType: "poi", stylers: [{ visibility: "off" }] },
        { featureType: "transit", stylers: [{ visibility: "off" }] },
      ],
    });
    this.info = new google.maps.InfoWindow({ maxWidth: 300 });
    this.directionsService = new google.maps.DirectionsService();
    this.directionsRenderer = new google.maps.DirectionsRenderer({
      map: this.map,
      suppressMarkers: true,
      polylineOptions: { strokeColor: ROUTE_COLOR, strokeWeight: 5, strokeOpacity: 0.9 },
    });
  },

  destroy() {
    this.disablePick();
    this.clearTrack();
    this.clearSearchResult();
    this.markers.forEach((marker) => marker.setMap(null));
    if (this.heat) this.heat.setMap(null);
    if (this.directionsRenderer) this.directionsRenderer.setMap(null);
    this.markers = new Map();
    this.map = null;
    this.heat = null;
  },

  setPins(pins, fit) {
    this.markers.forEach((marker) => marker.setMap(null));
    this.markers = new Map();
    const bounds = new google.maps.LatLngBounds();
    pins.forEach((pin) => {
      const marker = new google.maps.Marker({
        map: this.map,
        position: { lat: pin.lat, lng: pin.lng },
        draggable: Boolean(pin.draggable),
        zIndex: pin.shape === "star" ? 500 : undefined,
        icon: {
          url: `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(iconSvg(pin))}`,
          scaledSize: new google.maps.Size(32, 42),
          anchor: new google.maps.Point(16, 42),
        },
      });
      if (pin.moving) marker.setAnimation(google.maps.Animation.BOUNCE);
      marker.addListener("click", () => {
        this.info.setContent(pin.html);
        this.info.open({ map: this.map, anchor: marker });
      });
      if (pin.draggable && pin.onMoved) {
        marker.addListener("dragend", (event) => pin.onMoved(event.latLng.lat(), event.latLng.lng()));
      }
      this.markers.set(pin.key, marker);
      bounds.extend({ lat: pin.lat, lng: pin.lng });
    });
    if (fit && pins.length) this.map.fitBounds(bounds, 64);
  },

  focus(key) {
    const marker = this.markers.get(key);
    if (!marker) return;
    this.map.panTo(marker.getPosition());
    this.map.setZoom(Math.max(this.map.getZoom() || 10, 14));
    google.maps.event.trigger(marker, "click");
  },

  async setHeatmap(enabled, points) {
    if (!google.maps.visualization) return;
    if (!this.heat) this.heat = new google.maps.visualization.HeatmapLayer({ radius: 38, opacity: 0.65 });
    this.heat.setData(points.map((point) => new google.maps.LatLng(point.latitude, point.longitude)));
    this.heat.setMap(enabled ? this.map : null);
  },

  route(points) {
    if (points.length > 27) return Promise.reject(new Error("Google en fazla 25 ara durak kabul eder"));
    const waypoints = points.slice(1, -1).map((point) => ({ location: point, stopover: true }));
    return new Promise((resolve, reject) => {
      this.directionsService.route(
        {
          origin: points[0],
          destination: points[points.length - 1],
          waypoints,
          optimizeWaypoints: waypoints.length > 1,
          travelMode: google.maps.TravelMode.DRIVING,
        },
        (result, status) => {
          if (status !== "OK") {
            reject(new Error(googleRouteError(status)));
            return;
          }
          this.directionsRenderer.setMap(this.map);
          this.directionsRenderer.setDirections(result);
          const legs = result.routes[0].legs || [];
          const meters = legs.reduce((sum, leg) => sum + (leg.distance ? leg.distance.value : 0), 0);
          const seconds = legs.reduce((sum, leg) => sum + (leg.duration ? leg.duration.value : 0), 0);
          resolve({ distanceKm: Math.round(meters / 10) / 100, durationMin: Math.round(seconds / 6) / 10 });
        },
      );
    });
  },

  clearRoute() {
    if (this.directionsRenderer) this.directionsRenderer.set("directions", null);
  },

  enablePick(callback) {
    this.disablePick();
    this.pickListener = this.map.addListener("click", (event) => callback(event.latLng.lat(), event.latLng.lng()));
    this.map.setOptions({ draggableCursor: "crosshair" });
  },

  disablePick() {
    if (this.pickListener) this.pickListener.remove();
    this.pickListener = null;
    if (this.map) this.map.setOptions({ draggableCursor: null });
  },

  showTrack(coords, stops) {
    this.clearTrack();
    if (!coords.length) return;
    const path = coords.map(([lat, lng]) => ({ lat, lng }));
    const bounds = new google.maps.LatLngBounds();
    path.forEach((point) => bounds.extend(point));
    this.trackItems.push(
      new google.maps.Polyline({ map: this.map, path, strokeColor: TRACK_COLOR, strokeWeight: 4, strokeOpacity: 0.85 }),
      endpointMarker(this.map, path[0], "#16a34a", "Başlangıç"),
      endpointMarker(this.map, path[path.length - 1], "#dc2626", "Son konum"),
    );
    stops.forEach((stop) => {
      this.trackItems.push(
        new google.maps.Marker({
          map: this.map,
          position: { lat: stop.lat, lng: stop.lng },
          title: stop.title,
          label: { text: stop.label, color: "#ffffff", fontSize: "11px", fontWeight: "700" },
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            scale: 11,
            fillColor: "#122033",
            fillOpacity: 1,
            strokeColor: "#ffffff",
            strokeWeight: 2,
          },
        }),
      );
    });
    this.map.fitBounds(bounds, 64);
  },

  clearTrack() {
    this.trackItems.forEach((item) => item.setMap(null));
    this.trackItems = [];
  },

  center() {
    const point = this.map.getCenter();
    return { lat: point.lat(), lng: point.lng() };
  },

  showSearchResult(lat, lng, label) {
    this.clearSearchResult();
    this.searchMarker = new google.maps.Marker({
      map: this.map,
      position: { lat, lng },
      title: label,
      zIndex: 1000,
      icon: {
        url: `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(pinSvg(SEARCH_COLOR))}`,
        scaledSize: new google.maps.Size(32, 42),
        anchor: new google.maps.Point(16, 42),
      },
    });
    this.map.panTo({ lat, lng });
    this.map.setZoom(Math.max(this.map.getZoom() || 10, 16));
  },

  clearSearchResult() {
    if (this.searchMarker) this.searchMarker.setMap(null);
    this.searchMarker = null;
  },

  async suggest(input, near) {
    if (this.placesLib === undefined) {
      try {
        this.placesLib = google.maps.importLibrary ? await google.maps.importLibrary("places") : null;
      } catch (error) {
        this.placesLib = null;
      }
    }
    const places = this.placesLib;
    if (!places || !places.AutocompleteSuggestion) return null;
    if (!this.sessionToken) this.sessionToken = new places.AutocompleteSessionToken();
    const request = {
      input,
      sessionToken: this.sessionToken,
      language: "tr",
      region: "tr",
      includedRegionCodes: ["tr"],
    };
    if (near) request.locationBias = { center: near, radius: 50000 };
    const { suggestions } = await places.AutocompleteSuggestion.fetchAutocompleteSuggestions(request);
    return (suggestions || [])
      .filter((item) => item.placePrediction)
      .map((item) => {
        const prediction = item.placePrediction;
        return {
          text: prediction.mainText ? prediction.mainText.toString() : prediction.text.toString(),
          secondary: prediction.secondaryText ? prediction.secondaryText.toString() : "",
          resolve: async () => {
            const place = prediction.toPlace();
            await place.fetchFields({ fields: ["displayName", "formattedAddress", "location"] });
            this.sessionToken = null;
            return {
              name: place.displayName || prediction.text.toString(),
              address: place.formattedAddress || prediction.text.toString(),
              latitude: place.location.lat(),
              longitude: place.location.lng(),
            };
          },
        };
      });
  },
};

function endpointMarker(map, position, color, title) {
  return new google.maps.Marker({
    map,
    position,
    title,
    icon: { path: google.maps.SymbolPath.CIRCLE, scale: 7, fillColor: color, fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 2 },
  });
}

function loadScriptOnce(src) {
  if (!loadedAssets.has(src)) {
    loadedAssets.set(
      src,
      new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = src;
        script.async = true;
        script.onload = () => resolve();
        script.onerror = () => {
          loadedAssets.delete(src);
          reject(new Error("Harita kütüphanesi yüklenemedi"));
        };
        document.head.appendChild(script);
      }),
    );
  }
  return loadedAssets.get(src);
}

function loadCssOnce(href) {
  if (loadedAssets.has(href)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.appendChild(link);
  loadedAssets.set(href, Promise.resolve());
}

async function loadLeaflet() {
  loadCssOnce(LEAFLET_CSS);
  if (window.L && window.L.map) return;
  await loadScriptOnce(LEAFLET_JS);
}

function loadGoogle(apiKey) {
  if (window.google && window.google.maps) return Promise.resolve();
  const key = `google:${apiKey}`;
  if (!loadedAssets.has(key)) {
    loadedAssets.set(
      key,
      new Promise((resolve, reject) => {
        const callback = `__haritaMapsReady_${Date.now()}`;
        window[callback] = () => {
          delete window[callback];
          resolve();
        };
        const script = document.createElement("script");
        script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&libraries=visualization,places&language=tr&region=TR&callback=${callback}`;
        script.async = true;
        script.onerror = () => {
          delete window[callback];
          loadedAssets.delete(key);
          reject(new Error("Google Maps yüklenemedi"));
        };
        document.head.appendChild(script);
      }),
    );
  }
  return loadedAssets.get(key);
}

function iconSvg(pin) {
  return pin.shape === "star" ? starSvg(pin.color) : pinSvg(pin.color);
}

function pinSvg(color) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="42" viewBox="0 0 32 42"><path fill="${color}" d="M16 0C7.2 0 0 7.2 0 16c0 12 16 26 16 26s16-14 16-26C32 7.2 24.8 0 16 0z"/><circle cx="16" cy="16" r="6" fill="white"/></svg>`;
}

function starSvg(color) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="42" viewBox="0 0 32 42"><path fill="${color}" d="M16 0C7.2 0 0 7.2 0 16c0 12 16 26 16 26s16-14 16-26C32 7.2 24.8 0 16 0z"/><path fill="white" d="M16 7.5l2.5 5.2 5.7.8-4.1 4 1 5.6-5.1-2.7-5.1 2.7 1-5.6-4.1-4 5.7-.8z"/></svg>`;
}

function stopBadge(label) {
  return `<div style="display:grid;place-items:center;width:24px;height:24px;border-radius:999px;background:#122033;color:#fff;border:2px solid #fff;font:700 11px Outfit,sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.35)">${esc(label)}</div>`;
}

function stopTitle(stop) {
  const start = new Date(stop.start).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
  const place = stop.place_name || "Tanımsız nokta";
  return `${stop.index}. ${place} · ${start} · ${Math.round(stop.duration_min)} dk${stop.planned ? " · planlı" : ""}`;
}

function vehicleState(vehicle) {
  if (vehicle.tracked) {
    if (vehicle.stale) return "stale";
    return vehicle.moving ? "moving" : "parked";
  }
  return vehicle.current_status === "Yolda" ? "moving" : "parked";
}

function entityHtml(entity, role) {
  const balance = new Intl.NumberFormat("tr-TR", {
    style: "currency",
    currency: "TRY",
    maximumFractionDigits: 0,
  }).format(entity.current_balance || 0);
  const kind = ENTITY_LABELS[entity.type] || entity.type;
  const last = entity.last_shipment
    ? `${esc(entity.last_shipment.status)}${entity.last_shipment.delivery_date ? ` · ${esc(entity.last_shipment.delivery_date)}` : ""}`
    : "Kayıt yok";
  const buttons = [];
  if (role === "admin" || role === "marketer") {
    buttons.push(`<button type="button" style="${btn("#1f6f5b")}" onclick="window.__harita.visit(${entity.id})">Ziyaret Ekle</button>`);
  }
  if (role === "admin" || role === "logistics") {
    buttons.push(`<button type="button" style="${btn("#c56a2d")}" onclick="window.__harita.shipment(${entity.id})">Sevkiyat Oluştur</button>`);
  }
  const hint = role === "admin" ? `<div style="margin-top:8px;font-size:11px;color:#6b7280">Konumu değiştirmek için pini sürükleyin.</div>` : "";
  return `
    <div style="font-family:Outfit,sans-serif;min-width:220px;color:#122033">
      <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#6b7280">${esc(kind)} · ${esc(entity.category)}</div>
      <div style="font-size:16px;font-weight:650;margin:4px 0 8px">${esc(entity.name)}</div>
      <div style="font-size:13px;line-height:1.45">Bakiye: <strong>${esc(balance)}</strong><br>Son sevkiyat: ${last}<br>${esc(entity.phone || "Telefon yok")}</div>
      <div style="margin-top:10px">${buttons.join("")}</div>
      ${hint}
    </div>`;
}

function locationHtml(location) {
  const badge = location.is_default_depot
    ? `<div style="margin-top:6px;display:inline-block;border-radius:999px;background:#ede9fe;color:#5b21b6;padding:2px 8px;font-size:11px;font-weight:600">Rota başlangıcı</div>`
    : "";
  return `
    <div style="font-family:Outfit,sans-serif;min-width:200px;color:#122033">
      <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#6b7280">Firmam · ${esc(location.kind)}</div>
      <div style="font-size:16px;font-weight:650;margin:4px 0">${esc(location.name)}</div>
      <div style="font-size:13px">${esc(location.address || "Adres girilmedi")}</div>
      ${badge}
    </div>`;
}

function vehicleHtml(vehicle, state) {
  const label = vehicle.current_status === "Musait" ? "Müsait" : vehicle.current_status;
  let telemetry = "";
  if (vehicle.tracked) {
    const seen = vehicle.last_seen_at
      ? new Date(vehicle.last_seen_at).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" })
      : "—";
    const status = state === "stale" ? "Veri gecikmiş" : state === "moving" ? "Hareket halinde" : "Duruyor";
    const speed = vehicle.speed_kmh != null ? ` · ${Math.round(vehicle.speed_kmh)} km/sa` : "";
    telemetry = `<div style="font-size:13px;margin-top:6px">${esc(status)}${esc(speed)}<br><span style="color:#6b7280">Son veri: ${esc(seen)}</span></div>`;
  }
  return `
    <div style="font-family:Outfit,sans-serif;min-width:180px;color:#122033">
      <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#6b7280">Araç${vehicle.tracked ? " · filo takip" : ""}</div>
      <div style="font-size:16px;font-weight:650;margin:4px 0">${esc(vehicle.plate_number)}</div>
      <div style="font-size:13px">${esc(vehicle.vehicle_type)} · ${esc(label)}</div>
      ${telemetry}
    </div>`;
}

function asPoint(value) {
  return { lat: value.lat ?? value.latitude, lng: value.lng ?? value.longitude };
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function btn(color) {
  return `margin:0 6px 0 0;border:0;background:${color};color:white;border-radius:8px;padding:7px 10px;cursor:pointer;font-size:12px;font-weight:600`;
}

function googleRouteError(status) {
  const messages = {
    REQUEST_DENIED: "Directions isteği reddedildi. Anahtar kısıtlarını kontrol edin.",
    ZERO_RESULTS: "Bu duraklar için sürüş rotası bulunamadı.",
    OVER_QUERY_LIMIT: "Google kota sınırına takıldı.",
    MAX_WAYPOINTS_EXCEEDED: "Durak sayısı Google sınırını aşıyor.",
  };
  return messages[status] || `Rota hesaplanamadı (${status})`;
}

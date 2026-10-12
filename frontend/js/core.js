const ROLE_LABEL = {
  admin: "Yönetici",
  logistics: "Lojistik Sorumlusu",
  marketer: "Saha Pazarlamacı",
  driver: "Sürücü",
};
const ENTITY_TYPES = [
  { value: "customer", label: "Müşteri" },
  { value: "supplier", label: "Tedarikçi" },
  { value: "competitor", label: "Rakip" },
  { value: "other", label: "Diğer" },
];
const CATEGORIES = ["VIP", "Aktif", "Potansiyel", "Hammadde Tedarikçisi", "Pasif"];
const SHIPMENT_STATUSES = ["Bekliyor", "Yolda", "Teslim Edildi", "İptal"];
const VISIT_TYPES = ["Pazarlama", "Tahsilat", "Servis"];
const VEHICLE_TYPES = ["Kamyonet", "Tır", "Minibüs"];
const LOCATION_KINDS = ["Merkez", "Şube", "Depo", "Fabrika"];
const MAP_LAYERS = [
  { key: "customer", label: "Müşteri", dot: "bg-blue-600" },
  { key: "supplier", label: "Tedarikçi", dot: "bg-orange-600" },
  { key: "competitor", label: "Rakip", dot: "bg-red-600" },
  { key: "other", label: "Diğer", dot: "bg-gray-500" },
  { key: "company", label: "Firmam", dot: "bg-violet-600" },
  { key: "vehicles", label: "Araçlar", dot: "bg-green-600" },
];

// Object.assign would evaluate getters once and freeze their values, so features are merged by descriptor.
function mergeFeatures(...features) {
  const target = {};
  features.forEach((feature) => Object.defineProperties(target, Object.getOwnPropertyDescriptors(feature)));
  return target;
}

function haritaApp() {
  return mergeFeatures(
    coreFeature(),
    entitiesFeature(),
    logisticsFeature(),
    visitsFeature(),
    companyFeature(),
    fleetFeature(),
    reportsFeature(),
    searchFeature(),
    dataFeature(),
  );
}

function coreFeature() {
  return {
    booting: true,
    authRequired: true,
    user: null,
    username: "",
    password: "",
    authError: "",
    toast: "",
    busy: false,
    loading: false,
    tab: "entities",
    mapReady: false,
    mapTried: false,
    mapError: "",
    mapProvider: "",
    mapConfig: null,
    heatOn: false,
    layers: { customer: true, supplier: true, competitor: true, other: true, company: true, vehicles: true },
    mapLayers: MAP_LAYERS,
    regions: [],
    mapData: { entities: [], vehicles: [], company_locations: [], unlocated_count: 0 },
    summary: {
      completed_visits_today: 0,
      shipments_on_route: 0,
      urgent_deliveries: 0,
      pending_shipments: 0,
    },
    picking: null,
    picked: null,
    _pollTimer: null,

    async init() {
      window.__harita = {
        visit: (id) => this.prepareVisit(Number(id)),
        shipment: (id) => this.prepareShipment(Number(id)),
      };
      HaritaMap.handlers.moved = (kind, id, lat, lng, name) => this.onPinMoved(kind, id, lat, lng, name);
      window.addEventListener("harita-unauthorized", () => {
        this.stopPolling();
        this.user = null;
        this.booting = false;
      });
      window.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && this.picking) this.cancelPick();
      });
      await this.start();
    },

    async start() {
      this.booting = true;
      this.authError = "";
      try {
        const health = await API.request("/api/health");
        this.authRequired = health.auth_required !== false;
      } catch (error) {
        this.authRequired = false;
        this.authError = error.message;
        this.booting = false;
        return;
      }
      if (!this.authRequired) API.setToken("");
      if (!this.authRequired || API.token) {
        try {
          await this.bootstrap();
        } catch (error) {
          API.setToken("");
          this.user = null;
          this.authError = error.message;
        }
      }
      this.booting = false;
    },

    async login() {
      this.busy = true;
      this.authError = "";
      try {
        const session = await API.login(this.username.trim(), this.password);
        API.setToken(session.access_token);
        this.mapTried = false;
        await this.bootstrap();
      } catch (error) {
        this.authError = error.message;
      } finally {
        this.busy = false;
      }
    },

    logout() {
      this.stopPolling();
      API.setToken("");
      this.user = null;
      this.tab = "entities";
      this.mapReady = false;
      this.mapTried = false;
      this.mapProvider = "";
      this.picking = null;
      this.picked = null;
      HaritaMap.destroy();
    },

    async bootstrap() {
      this.user = await API.me();
      await this.refresh();
      this.$nextTick(() => requestAnimationFrame(() => this.setupMap()));
    },

    async setupMap() {
      if (this.mapTried) return;
      this.mapTried = true;
      this.mapError = "";
      try {
        const config = await API.request("/api/map/config");
        this.mapConfig = config;
        const ok = await HaritaMap.mount(document.getElementById("map"), config);
        this.mapReady = ok;
        this.mapProvider = HaritaMap.provider;
        if (ok) this.syncMap();
        this.startPolling();
      } catch (error) {
        this.mapReady = false;
        this.mapError = error.message || "Harita yüklenemedi";
        this.notify(this.mapError);
      }
    },

    syncMap() {
      if (!this.mapReady) return;
      HaritaMap.setData(this.mapData, this.user.role, this.layers);
      HaritaMap.setHeatmap(
        this.heatOn,
        (this.mapData.entities || []).filter((item) => item.type === "customer"),
      ).catch((error) => this.notify(error.message));
    },

    toggleLayer(key) {
      this.layers[key] = !this.layers[key];
      this.syncMap();
    },

    toggleHeat() {
      this.heatOn = !this.heatOn;
      this.syncMap();
    },

    mapQuery() {
      return queryString({
        entity_type: this.filters.entity_type,
        category: this.filters.category,
        status: this.filters.status,
        region_id: this.filters.region_id,
      });
    },

    async refresh() {
      if (!this.user) return;
      this.loading = true;
      try {
        const requests = [
          API.request("/api/entities?limit=1000"),
          API.request(`/api/entities${queryString(this.filters)}`),
          API.request("/api/logistics/shipments"),
          API.request("/api/visits"),
          API.request(`/api/map/data${this.mapQuery()}`),
          API.request("/api/dashboard/summary"),
          API.request("/api/regions"),
          this.can("fleet") ? API.request("/api/logistics/vehicles") : Promise.resolve([]),
          this.can("fleet") ? API.request("/api/logistics/drivers") : Promise.resolve([]),
        ];
        const [allEntities, entities, shipments, visits, mapData, summary, regions, vehicles, drivers] =
          await Promise.all(requests);
        this.allEntities = allEntities;
        this.entities = entities;
        this.shipments = shipments;
        this.visits = visits.map((visit) => ({
          ...visit,
          draftNotes: visit.notes || "",
          draftRakip: (visit.form_data_json && visit.form_data_json.rakip_analizi) || "",
          draftTalep: (visit.form_data_json && visit.form_data_json.musteri_talebi) || "",
        }));
        this.mapData = mapData;
        this.summary = summary;
        this.regions = regions;
        this.vehicles = vehicles;
        this.drivers = drivers;
        this.syncMap();
        await Promise.all([this.loadCompany(), this.loadFleet(), this.loadArchive()]);
      } catch (error) {
        this.notify(error.message);
      } finally {
        this.loading = false;
      }
    },

    startPolling() {
      this.stopPolling();
      const seconds = Math.max(Number(this.mapConfig && this.mapConfig.vehicle_refresh_seconds) || 60, 15);
      this._pollTimer = setInterval(() => this.pollVehicles(), seconds * 1000);
    },

    stopPolling() {
      if (this._pollTimer) clearInterval(this._pollTimer);
      this._pollTimer = null;
    },

    async pollVehicles() {
      if (!this.user || document.hidden || this.busy || this.picking || this.picked) return;
      try {
        const [mapData] = await Promise.all([
          API.request(`/api/map/data${this.mapQuery()}`),
          this.can("fleetView") ? this.loadLive() : Promise.resolve(),
        ]);
        this.mapData = mapData;
        this.syncMap();
      } catch (error) {
        // A transient polling failure should not interrupt the user; the next tick retries.
      }
    },

    startPick(purpose) {
      if (!this.mapReady) {
        this.notify("Harita yüklenmedi, işaretleme yapılamıyor");
        return;
      }
      this.picked = null;
      this.picking = purpose || "any";
      HaritaMap.enablePick((lat, lng) => this.onPicked(lat, lng));
      this.notify("Haritada konuma tıklayın (iptal için Esc)");
    },

    cancelPick() {
      HaritaMap.disablePick();
      HaritaMap.clearSearchResult();
      this.picking = null;
      this.picked = null;
    },

    async onPicked(lat, lng) {
      const purpose = this.picking;
      this.picking = null;
      this.picked = { lat, lng, address: "", loading: true, purpose };
      let address = "";
      try {
        const result = await API.request(`/api/geocode/reverse${queryString({ lat, lng })}`);
        address = result.address || "";
        if (!address && result.warning) this.notify(result.warning);
      } catch (error) {
        this.notify(error.message);
      }
      if (!this.picked) return;
      this.picked = { ...this.picked, address, loading: false };
      if (purpose === "entity") this.usePickedAsEntity();
      else if (purpose === "location") this.usePickedAsLocation();
    },

    usePickedAsEntity() {
      const point = this.picked;
      if (!point) return;
      this.applyPointToEntityForm(point);
      this.picked = null;
      HaritaMap.clearSearchResult();
      this.tab = "entities";
    },

    usePickedAsLocation() {
      const point = this.picked;
      if (!point) return;
      this.applyPointToLocationForm(point);
      this.picked = null;
      HaritaMap.clearSearchResult();
      this.tab = "company";
    },

    async onPinMoved(kind, id, lat, lng, name) {
      const rounded = { latitude: Math.round(lat * 1e6) / 1e6, longitude: Math.round(lng * 1e6) / 1e6 };
      if (!confirm(`${name} yeni konuma taşınsın mı?`)) {
        this.syncMap();
        return;
      }
      const path = kind === "location" ? `/api/company/locations/${id}` : `/api/entities/${id}`;
      try {
        await API.request(path, { method: "PUT", body: JSON.stringify(rounded) });
        this.notify(`${name} konumu güncellendi`);
        await this.refresh();
      } catch (error) {
        this.notify(error.message);
        this.syncMap();
      }
    },

    can(action) {
      const role = this.user && this.user.role;
      if (!role) return false;
      if (role === "admin") return true;
      const allowed = {
        entityWrite: [],
        companyWrite: [],
        fleetAdmin: [],
        shipmentWrite: ["logistics"],
        route: ["logistics"],
        visitWrite: ["marketer"],
        fleet: ["logistics"],
        fleetView: ["logistics"],
        reports: ["logistics"],
        proof: ["logistics", "driver"],
        status: ["logistics", "driver"],
      };
      return (allowed[action] || []).includes(role);
    },

    roleLabel(role) {
      return ROLE_LABEL[role] || role;
    },

    money(value) {
      return new Intl.NumberFormat("tr-TR", {
        style: "currency",
        currency: "TRY",
        maximumFractionDigits: 0,
      }).format(value || 0);
    },

    formatWhen(value) {
      if (!value) return "—";
      if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
        const [year, month, day] = value.split("-");
        return `${day}.${month}.${year}`;
      }
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" });
    },

    formatAgo(value) {
      if (!value) return "veri yok";
      const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
      if (minutes < 1) return "az önce";
      if (minutes < 60) return `${minutes} dk önce`;
      if (minutes < 1440) return `${Math.floor(minutes / 60)} sa önce`;
      return this.formatWhen(value);
    },

    localDate(offsetDays) {
      const date = new Date();
      date.setDate(date.getDate() + (offsetDays || 0));
      const pad = (value) => String(value).padStart(2, "0");
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
    },

    notify(message) {
      this.toast = message;
      clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => {
        this.toast = "";
      }, 4200);
    },

    async run(work) {
      this.busy = true;
      try {
        await work();
      } catch (error) {
        this.notify(error.message || "İşlem başarısız");
      } finally {
        this.busy = false;
      }
    },
  };
}

window.haritaApp = haritaApp;

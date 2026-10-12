function logisticsFeature() {
  return {
    shipments: [],
    vehicles: [],
    drivers: [],
    showShipmentForm: false,
    shipmentForm: blankShipment(),
    showFleetForm: false,
    vehicleForm: blankVehicle(),
    shipmentQuery: "",
    routeIds: [],
    routePlan: null,
    shipmentStatuses: SHIPMENT_STATUSES,
    vehicleTypes: VEHICLE_TYPES,

    get visibleShipments() {
      const query = this.shipmentQuery.toLocaleLowerCase("tr");
      if (!query) return this.shipments;
      return this.shipments.filter((shipment) =>
        `${shipment.entity_name || ""} ${shipment.vehicle_plate || ""} ${shipment.status || ""}`
          .toLocaleLowerCase("tr")
          .includes(query),
      );
    },

    get urgentShipments() {
      const today = this.localDate(0);
      return this.shipments.filter(
        (shipment) =>
          (shipment.status === "Bekliyor" || shipment.status === "Yolda") &&
          shipment.delivery_date &&
          shipment.delivery_date <= today,
      );
    },

    get depotLabel() {
      return this.depot().label;
    },

    depot() {
      const preferred = (this.locations || []).find((location) => location.is_default_depot);
      if (preferred) return { lat: preferred.latitude, lng: preferred.longitude, label: preferred.name };
      if (this.mapConfig) {
        return { lat: this.mapConfig.depot_lat, lng: this.mapConfig.depot_lng, label: this.mapConfig.depot_label };
      }
      return { lat: null, lng: null, label: "Depo tanımlı değil" };
    },

    ownsShipment(shipment) {
      return !this.user || this.user.role !== "driver" || shipment.driver_id === this.user.id;
    },

    itemSummary(items) {
      if (!items || !items.length) return "Kalemsiz";
      return items.map((item) => `${item.name} × ${item.quantity} ${item.unit || ""}`.trim()).join(", ");
    },

    prepareShipment(id) {
      this.tab = "shipments";
      this.showShipmentForm = true;
      this.shipmentForm = { ...blankShipment(), entity_id: String(id) };
      const entity = this.allEntities.find((item) => item.id === id) || this.mapData.entities.find((item) => item.id === id);
      this.notify(entity ? `${entity.name} için sevkiyat formu açıldı` : "Sevkiyat formu açıldı");
    },

    addShipmentItem() {
      const name = this.shipmentForm.draftName.trim();
      if (!name) return;
      this.shipmentForm.items.push({
        name,
        quantity: Number(this.shipmentForm.draftQty) || 1,
        unit: this.shipmentForm.draftUnit || "adet",
      });
      this.shipmentForm.draftName = "";
      this.shipmentForm.draftQty = 1;
    },

    async saveShipment() {
      await this.run(async () => {
        const payload = {
          entity_id: Number(this.shipmentForm.entity_id),
          vehicle_id: this.shipmentForm.vehicle_id ? Number(this.shipmentForm.vehicle_id) : null,
          driver_id: this.shipmentForm.driver_id ? Number(this.shipmentForm.driver_id) : null,
          status: "Bekliyor",
          items_json: this.shipmentForm.items,
          delivery_date: this.shipmentForm.delivery_date || null,
          notes: this.shipmentForm.notes,
        };
        if (!payload.entity_id) throw new Error("Cari seçin");
        await API.request("/api/logistics/shipments", { method: "POST", body: JSON.stringify(payload) });
        this.shipmentForm = blankShipment();
        this.showShipmentForm = false;
        await this.refresh();
        this.notify("Sevkiyat kuyruğa alındı");
      });
    },

    async changeStatus(shipment, status) {
      await this.run(async () => {
        await API.request(`/api/logistics/shipments/${shipment.id}`, {
          method: "PATCH",
          body: JSON.stringify({ status }),
        });
        await this.refresh();
      });
    },

    async assignShipment(shipment, field, value) {
      await this.run(async () => {
        const body = {};
        body[field] = value ? Number(value) : null;
        await API.request(`/api/logistics/shipments/${shipment.id}/assign`, {
          method: "POST",
          body: JSON.stringify(body),
        });
        await this.refresh();
      });
    },

    async uploadProof(shipment, event) {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (!file) return;
      await this.run(async () => {
        const body = new FormData();
        body.append("file", file);
        await API.request(`/api/logistics/shipments/${shipment.id}/proof`, { method: "POST", body });
        await this.refresh();
        this.notify("Teslim kanıtı yüklendi");
      });
    },

    toggleRoute(id) {
      this.routeIds = this.routeIds.includes(id)
        ? this.routeIds.filter((item) => item !== id)
        : this.routeIds.concat(id);
    },

    selectedStops() {
      const ordered = this.routeIds
        .map((id) => this.shipments.find((shipment) => shipment.id === id))
        .filter(Boolean);
      const missing = ordered.filter((shipment) => shipment.entity_latitude == null || shipment.entity_longitude == null);
      if (missing.length) this.notify("Koordinatı olmayan duraklar rotaya alınmadı");
      return ordered
        .filter((shipment) => shipment.entity_latitude != null && shipment.entity_longitude != null)
        .map((shipment) => ({
          id: shipment.id,
          latitude: shipment.entity_latitude,
          longitude: shipment.entity_longitude,
          label: shipment.entity_name || `Sevkiyat ${shipment.id}`,
        }));
    },

    requireDepot() {
      const depot = this.depot();
      if (depot.lat == null || depot.lng == null) throw new Error("Firma sekmesinden rota başlangıcı (depo) seçin");
      return depot;
    },

    async optimizeQueue() {
      await this.run(async () => {
        const stops = this.selectedStops();
        if (!stops.length) throw new Error("Koordinatı olan sevkiyat seçin");
        const depot = this.requireDepot();
        const result = await API.request("/api/logistics/optimize", {
          method: "POST",
          body: JSON.stringify({ origin_lat: depot.lat, origin_lng: depot.lng, stops }),
        });
        this.routePlan = result;
        this.routeIds = result.stops.map((stop) => stop.id);
        this.notify(`Sıra hazır, yaklaşık ${result.total_km} km`);
      });
    },

    async drawSelected() {
      if (!this.mapReady) {
        this.notify("Harita yüklenmedi, rota çizilemiyor");
        return;
      }
      await this.run(async () => {
        const stops = this.routePlan ? this.routePlan.stops : this.selectedStops();
        if (!stops.length) throw new Error("Durak seçin");
        const result = await HaritaMap.drawRoute(this.requireDepot(), stops);
        this.notify(`Rota: ${result.distanceKm} km, yaklaşık ${Math.round(result.durationMin)} dk`);
      });
    },

    clearRoute() {
      HaritaMap.clearRoute();
      this.routePlan = null;
      this.notify("Rota temizlendi");
    },

    async saveVehicle() {
      await this.run(async () => {
        await API.request("/api/logistics/vehicles", {
          method: "POST",
          body: JSON.stringify({
            plate_number: this.vehicleForm.plate_number,
            vehicle_type: this.vehicleForm.vehicle_type,
            max_weight_kg: Number(this.vehicleForm.max_weight_kg) || 0,
            max_volume_m3: Number(this.vehicleForm.max_volume_m3) || 0,
            current_status: this.vehicleForm.current_status,
            region_id: this.vehicleForm.region_id ? Number(this.vehicleForm.region_id) : null,
          }),
        });
        this.vehicleForm = blankVehicle();
        this.showFleetForm = false;
        await this.refresh();
        this.notify("Araç filoya eklendi");
      });
    },
  };
}

function blankShipment() {
  return {
    entity_id: "",
    vehicle_id: "",
    driver_id: "",
    delivery_date: "",
    notes: "",
    items: [],
    draftName: "",
    draftQty: 1,
    draftUnit: "adet",
  };
}

function blankVehicle() {
  return {
    plate_number: "",
    vehicle_type: "Kamyonet",
    max_weight_kg: 1000,
    max_volume_m3: 5,
    current_status: "Musait",
    region_id: "",
  };
}

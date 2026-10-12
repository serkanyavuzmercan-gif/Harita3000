function fleetFeature() {
  return {
    providers: [],
    integrations: [],
    live: [],
    showIntegrationForm: false,
    editingIntegrationId: null,
    integrationForm: blankIntegration(),
    externalFor: null,
    externalVehicles: [],
    trackDate: "",
    track: null,

    async loadFleet() {
      if (!this.can("fleetView")) return;
      if (!this.trackDate) this.trackDate = this.localDate(0);
      const [integrations, providers] = await Promise.all([
        API.request("/api/fleet/integrations"),
        this.can("fleetAdmin") && !this.providers.length ? API.request("/api/fleet/providers") : Promise.resolve(this.providers),
        this.loadLive(),
      ]);
      this.integrations = integrations;
      this.providers = providers;
    },

    async loadLive() {
      this.live = await API.request("/api/fleet/live");
    },

    get trackedCount() {
      return this.live.filter((vehicle) => vehicle.tracked).length;
    },

    providerInfo(provider) {
      return this.providers.find((item) => item.provider === provider) || { label: provider, fields: [] };
    },

    providerLabel(provider) {
      return this.providerInfo(provider).label;
    },

    liveBadge(vehicle) {
      if (!vehicle.tracked) return { text: "Takip yok", cls: "bg-white/10 text-sand/60" };
      if (vehicle.stale) return { text: "Veri gecikmiş", cls: "bg-gray-500/30 text-gray-200" };
      if (vehicle.moving) return { text: "Hareketli", cls: "bg-green-600/30 text-green-200" };
      return { text: "Duruyor", cls: "bg-amber-600/30 text-amber-100" };
    },

    openIntegrationForm() {
      this.editingIntegrationId = null;
      this.integrationForm = blankIntegration();
      this.showIntegrationForm = true;
    },

    editIntegration(integration) {
      this.editingIntegrationId = integration.id;
      this.integrationForm = {
        provider: integration.provider,
        name: integration.name,
        poll_interval_min: integration.poll_interval_min,
        is_active: integration.is_active,
        credentials: {},
        configured: integration.configured_fields || [],
      };
      this.showIntegrationForm = true;
    },

    resetIntegrationForm() {
      this.editingIntegrationId = null;
      this.integrationForm = blankIntegration();
      this.showIntegrationForm = false;
    },

    credentialPlaceholder(field) {
      if (this.editingIntegrationId && (this.integrationForm.configured || []).includes(field.key)) {
        return field.secret ? "Kayıtlı (değiştirmek için yazın)" : "Kayıtlı değer korunur";
      }
      return field.placeholder || (field.required ? "Zorunlu" : "İsteğe bağlı");
    },

    async saveIntegration() {
      await this.run(async () => {
        const credentials = {};
        Object.entries(this.integrationForm.credentials || {}).forEach(([key, value]) => {
          if (String(value || "").trim()) credentials[key] = String(value).trim();
        });
        const base = {
          name: this.integrationForm.name,
          poll_interval_min: Number(this.integrationForm.poll_interval_min) || 5,
          is_active: Boolean(this.integrationForm.is_active),
        };
        if (this.editingIntegrationId) {
          const payload = Object.keys(credentials).length ? { ...base, credentials } : base;
          await API.request(`/api/fleet/integrations/${this.editingIntegrationId}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          });
        } else {
          await API.request("/api/fleet/integrations", {
            method: "POST",
            body: JSON.stringify({ ...base, provider: this.integrationForm.provider, credentials }),
          });
        }
        this.resetIntegrationForm();
        await this.loadFleet();
        this.notify("Entegrasyon kaydedildi");
      });
    },

    async removeIntegration(integration) {
      if (!confirm(`${integration.name} silinsin mi? Bağlı araçların eşleşmesi kaldırılır, geçmiş konumlar korunur.`)) return;
      await this.run(async () => {
        await API.request(`/api/fleet/integrations/${integration.id}`, { method: "DELETE" });
        if (this.externalFor === integration.id) this.externalFor = null;
        await this.loadFleet();
        this.notify("Entegrasyon silindi");
      });
    },

    async testIntegration(integration) {
      await this.run(async () => {
        const result = await API.request(`/api/fleet/integrations/${integration.id}/test`, { method: "POST" });
        this.notify(result.message);
      });
    },

    async syncIntegration(integration) {
      await this.run(async () => {
        const result = await API.request(`/api/fleet/integrations/${integration.id}/sync`, { method: "POST" });
        const unmatched = result.unmatched_ids.length ? `, eşleşmeyen: ${result.unmatched_ids.join(", ")}` : "";
        this.notify(`${result.inserted} yeni konum, ${result.matched_vehicles} araç${unmatched}`);
        await Promise.all([this.loadFleet(), this.pollVehicles()]);
      });
    },

    async showExternal(integration) {
      if (this.externalFor === integration.id) {
        this.externalFor = null;
        return;
      }
      await this.run(async () => {
        this.externalVehicles = await API.request(`/api/fleet/integrations/${integration.id}/external-vehicles`);
        this.externalFor = integration.id;
      });
    },

    async linkExternal(external, vehicleId) {
      await this.run(async () => {
        if (vehicleId) {
          await API.request(`/api/fleet/vehicles/${vehicleId}/link`, {
            method: "PUT",
            body: JSON.stringify({ integration_id: this.externalFor, external_id: external.external_id }),
          });
        }
        if (external.linked_vehicle_id && String(external.linked_vehicle_id) !== String(vehicleId)) {
          await API.request(`/api/fleet/vehicles/${external.linked_vehicle_id}/link`, {
            method: "PUT",
            body: JSON.stringify({ integration_id: null, external_id: null }),
          });
        }
        this.externalVehicles = await API.request(`/api/fleet/integrations/${this.externalFor}/external-vehicles`);
        await this.loadFleet();
        this.notify(vehicleId ? "Araç eşleştirildi" : "Eşleşme kaldırıldı");
      });
    },

    focusVehicle(vehicle) {
      if (!this.mapReady || vehicle.latitude == null) return;
      HaritaMap.focusKey(`v-${vehicle.id}`);
    },

    async showVehicleTrack(vehicle) {
      if (!this.mapReady) {
        this.notify("Harita yüklenmedi, iz gösterilemiyor");
        return;
      }
      await this.run(async () => {
        const day = this.trackDate || this.localDate(0);
        const result = await API.request(`/api/fleet/vehicles/${vehicle.id}/track${queryString({ date: day })}`);
        if (!result.points.length) {
          this.track = null;
          HaritaMap.clearTrack();
          throw new Error(`${vehicle.plate_number} için ${this.formatWhen(day)} tarihinde konum yok`);
        }
        this.track = result;
        HaritaMap.showTrack(result.points, result.stops);
      });
    },

    clearTrack() {
      this.track = null;
      HaritaMap.clearTrack();
    },

    durationText(minutes) {
      const total = Math.round(minutes || 0);
      const hours = Math.floor(total / 60);
      return hours ? `${hours} sa ${total % 60} dk` : `${total} dk`;
    },

    timeOf(value) {
      return value ? new Date(value).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }) : "—";
    },
  };
}

function blankIntegration() {
  return { provider: "simulator", name: "", poll_interval_min: 5, is_active: true, credentials: {}, configured: [] };
}

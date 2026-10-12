function companyFeature() {
  return {
    company: null,
    companyForm: blankCompany(),
    locations: [],
    showLocationForm: false,
    editingLocationId: null,
    locationForm: blankLocation(),
    locationKinds: LOCATION_KINDS,

    async loadCompany() {
      const [company, locations] = await Promise.all([
        API.request("/api/company"),
        API.request("/api/company/locations"),
      ]);
      this.company = company;
      this.companyForm = {
        name: company.name || "",
        tax_number: company.tax_number || "",
        phone: company.phone || "",
        email: company.email || "",
        address: company.address || "",
      };
      this.locations = locations;
    },

    async saveCompany() {
      await this.run(async () => {
        this.company = await API.request("/api/company", { method: "PUT", body: JSON.stringify(this.companyForm) });
        this.notify("Firma bilgileri kaydedildi");
      });
    },

    async uploadLogo(event) {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (!file) return;
      await this.run(async () => {
        const body = new FormData();
        body.append("file", file);
        this.company = await API.request("/api/company/logo", { method: "POST", body });
        this.notify("Logo yüklendi, raporlarda kullanılacak");
      });
    },

    openLocationForm() {
      this.editingLocationId = null;
      this.locationForm = blankLocation();
      this.showLocationForm = true;
    },

    resetLocationForm() {
      this.editingLocationId = null;
      this.locationForm = blankLocation();
      this.showLocationForm = false;
    },

    editLocation(location) {
      this.editingLocationId = location.id;
      this.showLocationForm = true;
      this.locationForm = {
        name: location.name,
        kind: location.kind,
        address: location.address || "",
        latitude: location.latitude,
        longitude: location.longitude,
        is_default_depot: location.is_default_depot,
        region_id: location.region_id || "",
      };
    },

    applyPointToLocationForm(point) {
      if (!this.showLocationForm) {
        this.editingLocationId = null;
        this.locationForm = blankLocation();
        this.showLocationForm = true;
      }
      this.locationForm.latitude = point.lat;
      this.locationForm.longitude = point.lng;
      if (point.address) this.locationForm.address = point.address;
      if (point.name && !this.locationForm.name) this.locationForm.name = point.name;
      this.notify("Konum forma işlendi, adını verip kaydedin");
    },

    focusLocation(location) {
      if (this.mapReady) HaritaMap.focusKey(`c-${location.id}`);
    },

    async saveLocation() {
      await this.run(async () => {
        const latitude = optionalNumber(this.locationForm.latitude);
        const longitude = optionalNumber(this.locationForm.longitude);
        if (latitude === null || longitude === null) throw new Error("Konumu haritadan seçin veya koordinat girin");
        const payload = {
          ...this.locationForm,
          latitude,
          longitude,
          region_id: this.locationForm.region_id ? Number(this.locationForm.region_id) : null,
        };
        const path = this.editingLocationId ? `/api/company/locations/${this.editingLocationId}` : "/api/company/locations";
        await API.request(path, { method: this.editingLocationId ? "PUT" : "POST", body: JSON.stringify(payload) });
        this.resetLocationForm();
        await this.refresh();
        this.notify("Lokasyon kaydedildi");
      });
    },

    async makeDefaultDepot(location) {
      await this.run(async () => {
        await API.request(`/api/company/locations/${location.id}`, {
          method: "PUT",
          body: JSON.stringify({ is_default_depot: true }),
        });
        await this.refresh();
        this.notify(`${location.name} artık rota başlangıcı`);
      });
    },

    async removeLocation(location) {
      if (!confirm(`${location.name} silinsin mi?`)) return;
      await this.run(async () => {
        await API.request(`/api/company/locations/${location.id}`, { method: "DELETE" });
        await this.refresh();
        this.notify("Lokasyon silindi");
      });
    },
  };
}

function blankCompany() {
  return { name: "", tax_number: "", phone: "", email: "", address: "" };
}

function blankLocation() {
  return {
    name: "",
    kind: "Şube",
    address: "",
    latitude: "",
    longitude: "",
    is_default_depot: false,
    region_id: "",
  };
}

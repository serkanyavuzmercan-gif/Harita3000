function entitiesFeature() {
  return {
    filters: { search: "", entity_type: "", category: "", status: "", region_id: "" },
    entities: [],
    allEntities: [],
    activeId: null,
    showEntityForm: false,
    editingId: null,
    entityForm: blankEntity(),
    categories: CATEGORIES,
    entityTypes: ENTITY_TYPES,

    typeLabel(type) {
      const match = ENTITY_TYPES.find((item) => item.value === type);
      return match ? match.label : type;
    },

    typeDot(type) {
      return { customer: "bg-blue-500", supplier: "bg-orange-500", competitor: "bg-red-500", other: "bg-gray-400" }[type] || "bg-gray-400";
    },

    focusEntity(entity) {
      this.activeId = entity.id;
      if (this.mapReady && entity.latitude != null) HaritaMap.focus(entity.id);
    },

    openEntityForm() {
      this.editingId = null;
      this.entityForm = blankEntity();
      this.showEntityForm = true;
    },

    resetEntityForm() {
      this.editingId = null;
      this.entityForm = blankEntity();
      this.showEntityForm = false;
    },

    editEntity(entity) {
      this.editingId = entity.id;
      this.showEntityForm = true;
      this.entityForm = {
        name: entity.name,
        type: entity.type,
        category: entity.category,
        address: entity.address || "",
        latitude: entity.latitude ?? "",
        longitude: entity.longitude ?? "",
        phone: entity.phone || "",
        email: entity.email || "",
        tax_number: entity.tax_number || "",
        current_balance: entity.current_balance || 0,
        status: entity.status,
        region_id: entity.region_id || "",
      };
    },

    applyPointToEntityForm(point) {
      if (!this.showEntityForm) {
        this.editingId = null;
        this.entityForm = blankEntity();
        this.showEntityForm = true;
      }
      this.entityForm.latitude = point.lat;
      this.entityForm.longitude = point.lng;
      if (point.address) this.entityForm.address = point.address;
      if (point.name && !this.entityForm.name) this.entityForm.name = point.name;
      this.notify("Konum forma işlendi, bilgileri tamamlayıp kaydedin");
    },

    async saveEntity() {
      await this.run(async () => {
        const latitude = optionalNumber(this.entityForm.latitude);
        const longitude = optionalNumber(this.entityForm.longitude);
        if ((latitude === null) !== (longitude === null)) throw new Error("Enlem ve boylamı birlikte girin");
        const payload = {
          ...this.entityForm,
          latitude,
          longitude,
          current_balance: Number(this.entityForm.current_balance || 0),
          region_id: this.entityForm.region_id ? Number(this.entityForm.region_id) : null,
        };
        const path = this.editingId ? `/api/entities/${this.editingId}` : "/api/entities";
        await API.request(path, { method: this.editingId ? "PUT" : "POST", body: JSON.stringify(payload) });
        this.resetEntityForm();
        await this.refresh();
        this.notify("Cari kaydedildi");
      });
    },

    async removeEntity(entity) {
      if (!confirm(`${entity.name} silinsin mi?`)) return;
      await this.run(async () => {
        await API.request(`/api/entities/${entity.id}`, { method: "DELETE" });
        await this.refresh();
        this.notify("Cari silindi");
      });
    },

    async geocodeEntity(entity) {
      await this.run(async () => {
        const result = await API.request(`/api/entities/${entity.id}/geocode`, { method: "POST" });
        await this.refresh();
        this.notify(result.warning || "Koordinat güncellendi");
      });
    },

    async importFile(event) {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (!file) return;
      await this.run(async () => {
        const body = new FormData();
        body.append("file", file);
        const result = await API.request("/api/entities/import", { method: "POST", body });
        await this.refresh();
        const extra = result.warnings && result.warnings.length ? ` ${result.warnings[0]}` : "";
        this.notify(`${result.created} kayıt alındı.${extra}`);
      });
    },
  };
}

function blankEntity() {
  return {
    name: "",
    type: "customer",
    category: "Aktif",
    address: "",
    latitude: "",
    longitude: "",
    phone: "",
    email: "",
    tax_number: "",
    current_balance: 0,
    status: "aktif",
    region_id: "",
  };
}

function optionalNumber(value) {
  if (value === "" || value === null || value === undefined) return null;
  const number = Number(value);
  if (Number.isNaN(number)) throw new Error("Koordinat sayı olmalı");
  return number;
}

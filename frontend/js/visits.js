function visitsFeature() {
  return {
    visits: [],
    showVisitForm: false,
    visitForm: blankVisit(),
    visitQuery: "",
    visitTypes: VISIT_TYPES,

    get visibleVisits() {
      const query = this.visitQuery.toLocaleLowerCase("tr");
      if (!query) return this.visits;
      return this.visits.filter((visit) =>
        `${visit.entity_name || ""} ${visit.visit_type || ""} ${visit.user_name || ""}`
          .toLocaleLowerCase("tr")
          .includes(query),
      );
    },

    canEditVisit(visit) {
      if (!this.can("visitWrite")) return false;
      return this.user.role !== "marketer" || visit.user_id === this.user.id;
    },

    prepareVisit(id) {
      this.tab = "visits";
      this.showVisitForm = true;
      this.visitForm = { ...blankVisit(), entity_id: String(id) };
      const entity = this.allEntities.find((item) => item.id === id) || this.mapData.entities.find((item) => item.id === id);
      this.notify(entity ? `${entity.name} için ziyaret formu açıldı` : "Ziyaret formu açıldı");
    },

    async saveVisit() {
      await this.run(async () => {
        if (!this.visitForm.entity_id) throw new Error("Cari seçin");
        await API.request("/api/visits", {
          method: "POST",
          body: JSON.stringify({
            entity_id: Number(this.visitForm.entity_id),
            visit_type: this.visitForm.visit_type,
            notes: this.visitForm.notes,
            form_data_json: {
              rakip_analizi: this.visitForm.rakip_analizi,
              musteri_talebi: this.visitForm.musteri_talebi,
            },
          }),
        });
        this.visitForm = blankVisit();
        this.showVisitForm = false;
        await this.refresh();
        this.notify("Ziyaret planlandı");
      });
    },

    async checkIn(visit) {
      await this.run(async () => {
        await API.request(`/api/visits/${visit.id}/check-in`, { method: "POST" });
        await this.refresh();
      });
    },

    async checkOut(visit) {
      await this.run(async () => {
        await API.request(`/api/visits/${visit.id}/check-out`, { method: "POST" });
        await this.refresh();
      });
    },

    async saveForm(visit) {
      await this.run(async () => {
        await API.request(`/api/visits/${visit.id}/form`, {
          method: "PUT",
          body: JSON.stringify({
            notes: visit.draftNotes,
            form_data_json: {
              rakip_analizi: visit.draftRakip,
              musteri_talebi: visit.draftTalep,
            },
          }),
        });
        await this.refresh();
        this.notify("Form kaydedildi");
      });
    },
  };
}

function blankVisit() {
  return {
    entity_id: "",
    visit_type: "Pazarlama",
    notes: "",
    rakip_analizi: "",
    musteri_talebi: "",
  };
}

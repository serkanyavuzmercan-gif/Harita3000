function reportsFeature() {
  return {
    reportDate: "",
    reportVehicleId: "",
    archive: [],

    async loadArchive() {
      if (!this.can("reports")) return;
      if (!this.reportDate) this.reportDate = this.localDate(-1);
      this.archive = await API.request("/api/reports/archive");
    },

    get reportVehicles() {
      const tracked = this.live.filter((vehicle) => vehicle.tracked);
      return tracked.length ? tracked : this.live;
    },

    async downloadRouteDay(format) {
      await this.run(async () => {
        if (!this.reportVehicleId) throw new Error("Araç seçin");
        if (!this.reportDate) throw new Error("Tarih seçin");
        const query = queryString({ vehicle_id: this.reportVehicleId, date: this.reportDate, format });
        const name = await API.download(`/api/reports/route-day${query}`, `rota.${format}`);
        this.notify(`${name} indirildi`);
      });
    },

    async downloadFleetDay() {
      await this.run(async () => {
        if (!this.reportDate) throw new Error("Tarih seçin");
        const name = await API.download(`/api/reports/fleet-day${queryString({ date: this.reportDate })}`, "filo.pdf");
        this.notify(`${name} indirildi`);
      });
    },

    async archiveNow() {
      await this.run(async () => {
        if (!this.reportDate) throw new Error("Tarih seçin");
        const result = await API.request(`/api/reports/archive${queryString({ date: this.reportDate })}`, { method: "POST" });
        await this.loadArchive();
        this.notify(result.written ? `${result.written} araç için rapor arşivlendi` : "Bu günde konum verisi olan araç yok");
      });
    },

    async downloadArchive(item, kind) {
      await this.run(async () => {
        await API.download(`/api/reports/archive/${item.id}/${kind}`, `${item.plate_number}_${item.report_date}.${kind}`);
      });
    },
  };
}

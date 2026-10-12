function dataFeature() {
  return {
    backupWithPositions: true,
    lastRestore: null,

    async downloadBackup() {
      await this.run(async () => {
        const name = await API.download(
          `/api/backup/export${queryString({ positions: this.backupWithPositions })}`,
          "harita3000_yedek.zip",
        );
        this.notify(`Yedek indirildi: ${name}`);
      });
    },

    async restoreBackup(event) {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (!file) return;
      const ok = confirm(
        `${file.name} geri yüklensin mi?\n\nMevcut TÜM veriler (cariler, sevkiyatlar, ziyaretler, firma, filo, raporlar) ` +
          "bu yedektekilerle değiştirilecek. Emin değilseniz önce şimdiki verinin yedeğini alın.",
      );
      if (!ok) return;
      await this.run(async () => {
        const body = new FormData();
        body.append("file", file);
        const result = await API.request("/api/backup/import", { method: "POST", body });
        this.lastRestore = result;
        HaritaMap.clearTrack();
        HaritaMap.clearRoute();
        this.track = null;
        this.routePlan = null;
        this.routeIds = [];
        this.providers = [];
        this.user = await API.me();
        await this.refresh();
        const entities = result.counts.entities || 0;
        this.notify(`Yedek geri yüklendi: ${entities} cari, ${result.counts.shipments || 0} sevkiyat`);
      });
    },

    async exportEntities(format) {
      await this.run(async () => {
        const name = await API.download(`/api/entities/export${queryString({ format })}`, `cariler.${format}`);
        this.notify(`${name} indirildi`);
      });
    },
  };
}

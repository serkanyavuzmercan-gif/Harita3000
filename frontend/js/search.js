const SEARCH_LOCAL_LIMIT = 5;
const SUGGEST_DELAY_MS = 300;

function searchFeature() {
  return {
    searchQuery: "",
    searchOpen: false,
    searchBusy: false,
    searchSuggestions: [],
    searchResults: [],
    searchWarning: "",
    searchProvider: "",
    suggestDisabled: false,
    _suggestTimer: null,
    _suggestSeq: 0,

    get searchLocal() {
      const query = this.searchQuery.trim().toLocaleLowerCase("tr");
      if (query.length < 2) return [];
      const matches = (text) => String(text || "").toLocaleLowerCase("tr").includes(query);
      const own = (this.locations || [])
        .filter((location) => matches(location.name) || matches(location.address))
        .map((location) => ({
          key: `c-${location.id}`,
          name: location.name,
          detail: `Firmam · ${location.kind}`,
          latitude: location.latitude,
          longitude: location.longitude,
        }));
      const entities = (this.allEntities || [])
        .filter((entity) => entity.latitude != null && (matches(entity.name) || matches(entity.address) || matches(entity.phone)))
        .map((entity) => ({
          key: `e-${entity.id}`,
          name: entity.name,
          detail: `${this.typeLabel(entity.type)} · ${entity.address || ""}`,
          latitude: entity.latitude,
          longitude: entity.longitude,
        }));
      return own.concat(entities).slice(0, SEARCH_LOCAL_LIMIT);
    },

    get searchHint() {
      if (this.mapProvider === "google" && !this.suggestDisabled) return "Yazdıkça Google önerileri gelir";
      return "Adres veya yer adı için Enter'a basın";
    },

    onSearchInput() {
      this.searchOpen = true;
      this.searchResults = [];
      this.searchWarning = "";
      clearTimeout(this._suggestTimer);
      const query = this.searchQuery.trim();
      if (query.length < 3 || this.mapProvider !== "google" || this.suggestDisabled) {
        this.searchSuggestions = [];
        return;
      }
      this._suggestTimer = setTimeout(() => this.loadSuggestions(query), SUGGEST_DELAY_MS);
    },

    async loadSuggestions(query) {
      const seq = ++this._suggestSeq;
      try {
        const suggestions = await HaritaMap.suggest(query, HaritaMap.center());
        if (seq !== this._suggestSeq) return;
        if (suggestions === null) {
          this.suggestDisabled = true;
          this.searchSuggestions = [];
          return;
        }
        this.searchSuggestions = suggestions;
      } catch (error) {
        if (seq !== this._suggestSeq) return;
        this.suggestDisabled = true;
        this.searchSuggestions = [];
        this.searchWarning = "Google önerileri alınamadı (Places API kapalı olabilir); Enter ile arama çalışır";
      }
    },

    async runSearch() {
      const query = this.searchQuery.trim();
      if (query.length < 3) {
        this.searchWarning = "En az 3 karakter yazın";
        this.searchOpen = true;
        return;
      }
      clearTimeout(this._suggestTimer);
      this._suggestSeq += 1;
      this.searchOpen = true;
      this.searchBusy = true;
      this.searchWarning = "";
      this.searchSuggestions = [];
      try {
        const center = HaritaMap.center() || {};
        const result = await API.request(`/api/geocode/search${queryString({ q: query, lat: center.lat, lng: center.lng })}`);
        this.searchProvider = result.provider;
        this.searchResults = result.results;
        if (!result.results.length) this.searchWarning = result.warning || "Sonuç bulunamadı";
      } catch (error) {
        this.searchWarning = error.message;
      } finally {
        this.searchBusy = false;
      }
    },

    chooseLocal(item) {
      this.closeSearch();
      HaritaMap.clearSearchResult();
      if (this.layers) {
        const layer = item.key.startsWith("c-") ? "company" : null;
        const entity = item.key.startsWith("e-") ? this.allEntities.find((row) => `e-${row.id}` === item.key) : null;
        const key = layer || (entity && entity.type);
        if (key && !this.layers[key]) this.toggleLayer(key);
      }
      HaritaMap.focusKey(item.key);
    },

    async chooseSuggestion(suggestion) {
      this.searchBusy = true;
      try {
        this.choosePlace(await suggestion.resolve());
      } catch (error) {
        this.searchWarning = "Seçilen yerin konumu alınamadı";
      } finally {
        this.searchBusy = false;
      }
    },

    choosePlace(place) {
      this.closeSearch();
      HaritaMap.showSearchResult(place.latitude, place.longitude, place.name);
      this.picking = null;
      HaritaMap.disablePick();
      this.picked = {
        lat: Math.round(place.latitude * 1e6) / 1e6,
        lng: Math.round(place.longitude * 1e6) / 1e6,
        name: place.name,
        address: place.address,
        loading: false,
        purpose: "any",
      };
    },

    closeSearch() {
      this.searchOpen = false;
      this.searchSuggestions = [];
      this.searchResults = [];
      this.searchWarning = "";
    },

    clearSearch() {
      this.searchQuery = "";
      this.closeSearch();
      HaritaMap.clearSearchResult();
    },
  };
}

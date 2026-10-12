const API = {
  token: localStorage.getItem("harita_token") || "",

  setToken(token) {
    this.token = token || "";
    if (token) localStorage.setItem("harita_token", token);
    else localStorage.removeItem("harita_token");
  },

  async request(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
    if (!isForm && options.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    if (this.token) headers.Authorization = `Bearer ${this.token}`;

    let response;
    try {
      response = await fetch(path, { ...options, headers });
    } catch (error) {
      throw new Error("Sunucuya ulaşılamadı");
    }

    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && !path.endsWith("/login")) {
      this.setToken("");
      window.dispatchEvent(new CustomEvent("harita-unauthorized"));
    }
    if (!response.ok) {
      throw new Error(messageFrom(data));
    }
    return data;
  },

  async download(path, fallbackName) {
    const headers = this.token ? { Authorization: `Bearer ${this.token}` } : {};
    let response;
    try {
      response = await fetch(path, { headers });
    } catch (error) {
      throw new Error("Sunucuya ulaşılamadı");
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(messageFrom(data));
    }
    const blob = await response.blob();
    const name = filenameFrom(response.headers.get("Content-Disposition")) || fallbackName || "rapor";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return name;
  },

  login(username, password) {
    return this.request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
  },

  me() {
    return this.request("/api/auth/me");
  },
};

function messageFrom(data) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || "Geçersiz alan").join(" ");
  }
  return "İstek başarısız";
}

function filenameFrom(disposition) {
  if (!disposition) return "";
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch (error) {
      return encoded[1];
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1] : "";
}

function queryString(params) {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) search.set(key, value);
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

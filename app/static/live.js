(() => {
  const state = { lastGeneratedAt: null };
  let liveMap;
  const fmtDelay = value => value == null ? "—" : `${value >= 0 ? "+" : "−"}${Math.abs(Math.round(value))} s`;
  const message = text => {
    const element = document.querySelector("#map-message");
    if (!element) return;
    element.hidden = !text;
    element.textContent = text || "";
  };
  const metric = (id, value) => {
    const node = document.querySelector(id);
    if (node) {
      node.textContent = value;
      node.classList.toggle("metric__value--empty", value === "—");
    }
  };
  function renderStats(data) {
    metric("#current-delay", fmtDelay(data.current_delay_median));
    metric("#average-delay", fmtDelay(data.current_delay_average));
    metric("#maximum-delay", fmtDelay(data.maximum_delay));
    metric("#on-time", data.on_time_percentage == null ? "—" : `${Math.round(data.on_time_percentage)} %`);
    const details = document.querySelector("#maximum-delay-details");
    if (details) {
      const detailParts = [data.maximum_delay_headsign && `→ ${data.maximum_delay_headsign}`, data.maximum_delay_last_stop_name].filter(Boolean);
      details.hidden = detailParts.length === 0;
      details.textContent = detailParts.join(" · ");
    }
    const trend = document.querySelector("#live-trend");
    if (trend) {
      const labels = { stable: "→ Zpoždění je posledních 30 min stabilní", slightly_worsening: "↗ Zpoždění se mírně zhoršuje", worsening: "↗ Zpoždění se zhoršuje", slightly_improving: "↘ Zpoždění se mírně zlepšuje", improving: "↘ Zpoždění se zlepšuje", unknown: "→ Trend zatím nelze určit" };
      const status = data.trend_status || "unknown";
      trend.hidden = false;
      trend.className = `live-trend live-trend--${status}`;
      trend.textContent = labels[status] || labels.unknown;
      if (data.trend_delta != null && status !== "stable") trend.textContent += ` · ${fmtDelay(data.trend_delta)} / 30 min`;
    }
    state.lastGeneratedAt = data.generated_at;
    updateAge();
  }
  async function refresh() {
    const results = await Promise.allSettled([
      fetch("/api/live/summary").then(response => response.ok ? response.json() : Promise.reject()),
      fetch("/api/live/vehicles").then(response => response.ok ? response.json() : Promise.reject()),
      fetch("/api/live/route").then(response => response.ok ? response.json() : Promise.reject())
    ]);
    const [summary, vehicles, route] = results;
    if (summary.status === "fulfilled") renderStats(summary.value);
    if (route.status === "fulfilled") liveMap.renderRoute(route.value);
    if (vehicles.status === "fulfilled") {
      liveMap.renderVehicles(vehicles.value.vehicles || []);
      message(vehicles.value.vehicles?.length ? "" : "Aktuálně nejsou k dispozici polohy aktivních autobusů.");
    } else message("Aktualizace poloh autobusů se nezdařila; zobrazuji poslední známá data.");
  }
  function updateAge() {
    const element = document.querySelector("#update-state");
    if (!element || !state.lastGeneratedAt) return;
    const generatedAt = new Date(state.lastGeneratedAt).getTime();
    if (!Number.isFinite(generatedAt)) { element.textContent = "Aktualizace dat —"; return; }
    const seconds = Math.max(0, Math.floor((Date.now() - generatedAt) / 1000));
    element.textContent = seconds < 60 ? `Data aktualizována před ${seconds} s` : `Poslední data před ${Math.floor(seconds / 60)} min`;
  }
  function setupOnTimeInfo() {
    const button = document.querySelector(".metric__info");
    const popover = document.querySelector("#on-time-description");
    if (!button || !popover) return;
    const setOpen = open => { popover.hidden = !open; button.setAttribute("aria-expanded", String(open)); };
    let openedFromPointer = false;
    button.addEventListener("pointerdown", () => { openedFromPointer = true; });
    button.addEventListener("focus", () => setOpen(true));
    button.addEventListener("click", () => {
      if (openedFromPointer) { openedFromPointer = false; setOpen(true); return; }
      setOpen(button.getAttribute("aria-expanded") !== "true");
    });
    button.addEventListener("keydown", event => { if (event.key === "Escape") { setOpen(false); button.focus(); } });
    button.addEventListener("blur", () => { window.setTimeout(() => { if (!popover.contains(document.activeElement)) setOpen(false); }, 0); });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && button.getAttribute("aria-expanded") === "true") { setOpen(false); button.focus(); }
    });
  }
  function start() {
    liveMap = window.TunelbusLiveMap.create({ onLoadError: () => message("Mapa se nepodařila načíst.") });
    liveMap.init();
    setupOnTimeInfo();
    refresh();
    window.setInterval(refresh, 20000);
    window.setInterval(updateAge, 1000);
  }
  const mapScript = document.createElement("script");
  mapScript.src = "/static/live-map.js";
  mapScript.onload = start;
  mapScript.onerror = () => message("Mapa se nepodařila načíst.");
  document.head.append(mapScript);
})();

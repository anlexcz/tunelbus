(() => {
  "use strict";
  const page = document.querySelector("[data-history-page]");
  if (!page) return;

  const $ = (selector) => page.querySelector(selector);
  const ns = "http://www.w3.org/2000/svg";
  let dailyData = [];
  let latestTo = null;
  let selectedMetric = "median_delay";

  const formatDelay = (value) => value == null ? "—" : `${value > 0 ? "+" : ""}${Math.round(value)} s`;
  const formatPercent = (value) => value == null ? "—" : `${Number(value).toLocaleString("cs-CZ", { maximumFractionDigits: 1 })} %`;
  const formatDate = (value) => value ? new Intl.DateTimeFormat("cs-CZ", { day: "numeric", month: "numeric", year: "numeric" }).format(new Date(`${value}T12:00:00`)) : "—";
  const setText = (selector, value) => { const element = $(selector); if (element) element.textContent = value; };
  const requestUrl = (path, range) => {
    const params = new URLSearchParams();
    if (range.from) params.set("from", range.from);
    if (range.to) params.set("to", range.to);
    return `${path}${params.size ? `?${params}` : ""}`;
  };
  const fetchJson = async (path, range) => {
    const response = await fetch(requestUrl(path, range), { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  };
  const setState = (name, message) => setText(`[data-history-${name}-state]`, message);
  const svg = (name, attributes = {}) => {
    const element = document.createElementNS(ns, name);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  };
  const metricValue = (item, metric) => metric === "on_time" ? (item.usable_trips ? item.distribution.on_time * 100 / item.usable_trips : null) : item[metric];
  const metricLabel = (metric) => ({ median_delay: "Medián", average_delay: "Průměr", p90_delay: "P90", on_time: "Včasnost" })[metric];
  const valueLabel = (value, metric) => metric === "on_time" ? formatPercent(value) : formatDelay(value);

  function chart(container, items, valueFor, labelFor, statusFor, onSelect) {
    container.replaceChildren();
    const valid = items.filter((item) => valueFor(item) != null);
    if (!valid.length) return false;
    const width = 720, height = 250, left = 42, right = 12, top = 18, bottom = 36;
    const values = valid.map(valueFor);
    let low = Math.min(...values), high = Math.max(...values);
    if (low === high) { low -= 1; high += 1; }
    const x = (index) => left + (width - left - right) * (items.length === 1 ? 0.5 : index / (items.length - 1));
    const y = (value) => top + (height - top - bottom) * (1 - (value - low) / (high - low));
    const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, focusable: "false", "aria-hidden": "true" });
    [0, 0.5, 1].forEach((fraction) => {
      const value = high - (high - low) * fraction, yy = y(value);
      root.append(svg("line", { x1: left, y1: yy, x2: width - right, y2: yy, class: "history-chart__grid" }));
      const text = svg("text", { x: left - 7, y: yy + 3, "text-anchor": "end", class: "history-chart__axis" }); text.textContent = Math.round(value); root.append(text);
    });
    const points = items.map((item, index) => valueFor(item) == null ? null : [x(index), y(valueFor(item))]);
    const path = points.reduce((text, point) => point ? `${text}${text ? " L" : "M"}${point[0]} ${point[1]}` : text, "");
    if (path) root.append(svg("path", { d: path, class: "history-chart__line" }));
    items.forEach((item, index) => {
      const point = points[index]; if (!point) return;
      const label = labelFor(item);
      if (index === 0 || index === items.length - 1 || items.length <= 8 || index % Math.ceil(items.length / 6) === 0) {
        const text = svg("text", { x: point[0], y: height - 13, "text-anchor": "middle", class: "history-chart__axis" }); text.textContent = label; root.append(text);
      }
      const circle = svg("circle", { cx: point[0], cy: point[1], r: 5, class: `history-chart__point${statusFor(item) === "partial" ? " history-chart__point--partial" : statusFor(item) === "insufficient" ? " history-chart__point--insufficient" : ""}`, tabindex: 0, role: "button", "aria-label": `${label}: ${valueLabel(valueFor(item), selectedMetric)}. Coverage ${formatPercent(item.coverage)}.` });
      const select = () => onSelect(item);
      circle.addEventListener("click", select); circle.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } });
      root.append(circle);
    });
    container.append(root);
    return true;
  }

  function renderSummary(data) {
    $("[data-history-summary-region]").setAttribute("aria-busy", "false");
    ["median_delay", "average_delay", "p90_delay"].forEach((key) => setText(`[data-history-summary="${key}"]`, formatDelay(data[key])));
    const onTime = data.usable_trips ? data.distribution.on_time * 100 / data.usable_trips : null;
    setText('[data-history-summary="on_time"]', formatPercent(onTime));
    setText('[data-history-summary="coverage"]', formatPercent(data.coverage));
    setText('[data-history-summary="coverage_detail"]', `${data.usable_trips} / ${data.planned_trips} spojů`);
    const note = $("[data-history-coverage-note]");
    note.hidden = data.coverage_status === "good";
    note.textContent = data.coverage_status === "partial" ? "Data za toto období nejsou úplná." : data.coverage_status === "insufficient" ? "Pro spolehlivé vyhodnocení není k dispozici dostatek dat." : "";
    Object.entries(data.distribution).forEach(([key, count]) => {
      const bucket = $(`[data-history-bucket="${key}"]`); if (!bucket) return;
      bucket.querySelector("output").textContent = `${count} spojů`;
      bucket.querySelector(".delay-distribution__fill").style.width = `${data.usable_trips ? count * 100 / data.usable_trips : 0}%`;
    });
    setState("summary", "");
  }
  function renderDays(data) {
    dailyData = data.days;
    const container = $("[data-history-days-chart]");
    const drawn = chart(container, dailyData, (item) => metricValue(item, selectedMetric), (item) => formatDate(item.date), (item) => item.coverage_status, (item) => { window.location.assign(`/history/${encodeURIComponent(item.date)}`); });
    container.setAttribute("aria-label", drawn ? `${metricLabel(selectedMetric)} po provozních dnech. Bod lze vybrat klávesnicí nebo tapnutím.` : "Pro toto období nejsou dostupná data po dnech.");
    setState("days", drawn ? "" : "Pro toto období nejsou dostupná data po dnech.");
  }
  function renderHours(data) {
    const container = $("[data-history-hours-chart]");
    const drawn = chart(container, data.hours, (item) => item.median_delay, (item) => `${item.hour} h`, () => "good", (item) => setText("[data-history-hours-detail]", `${item.hour}:00: medián ${formatDelay(item.median_delay)}; coverage ${formatPercent(item.coverage)}.`));
    container.setAttribute("aria-label", drawn ? "Medián zpoždění podle hodiny provozního dne." : "Pro toto období nejsou dostupná hodinová data.");
    setState("hours", drawn ? "" : "Pro toto období nejsou dostupná hodinová data.");
  }
  function fail(name) { setState(name, "Data se nepodařilo načíst. Zkuste to prosím později."); }
  async function load(range = {}) {
    setText("[data-history-period-state]", "Načítám data období…");
    $("[data-history-summary-region]").setAttribute("aria-busy", "true");
    setState("summary", "Načítám souhrn…"); setState("days", "Načítám vývoj po dnech…"); setState("hours", "Načítám hodinový profil…");
    const [summary, days, hours] = await Promise.allSettled([fetchJson("/api/history/summary", range), fetchJson("/api/history/days", range), fetchJson("/api/history/hours", range)]);
    if (summary.status === "fulfilled") { renderSummary(summary.value); latestTo = summary.value.to; setText("[data-history-period-state]", `Použité období: ${formatDate(summary.value.from)} – ${formatDate(summary.value.to)}.`); } else { fail("summary"); }
    if (days.status === "fulfilled") renderDays(days.value); else fail("days");
    if (hours.status === "fulfilled") renderHours(hours.value); else fail("hours");
  }
  function activate(period) {
    page.querySelectorAll("[data-history-period]").forEach((button) => { const active = button.dataset.historyPeriod === period; button.classList.toggle("period-preset--active", active); button.setAttribute("aria-pressed", active); });
    const form = $("[data-history-custom-range]"); form.hidden = period !== "custom";
    if (period === "last_7") load({});
    if (period === "last_30") { const end = latestTo ? new Date(`${latestTo}T12:00:00`) : new Date(); const start = new Date(end); start.setDate(start.getDate() - 29); load({ from: start.toISOString().slice(0, 10), to: end.toISOString().slice(0, 10) }); }
  }
  page.querySelectorAll("[data-history-period]").forEach((button) => button.addEventListener("click", () => activate(button.dataset.historyPeriod)));
  $("[data-history-custom-range]").addEventListener("submit", (event) => { event.preventDefault(); const from = $("[data-history-from]").value, to = $("[data-history-to]").value; if (from && to && from <= to) load({ from, to }); else setText("[data-history-period-state]", "Zadejte platné období: datum Od nesmí být později než Do."); });
  page.querySelectorAll("[data-history-chart-metric]").forEach((button) => button.addEventListener("click", () => { selectedMetric = button.dataset.historyChartMetric; page.querySelectorAll("[data-history-chart-metric]").forEach((item) => item.setAttribute("aria-pressed", item === button)); renderDays({ days: dailyData }); }));
  load({});
})();

(() => {
  const controls = document.querySelector(".day-controls");
  if (!controls) return;

  const periods = {
    all: { fromOffset: null, toOffset: null },
    morning: { fromOffset: 1, toOffset: 5 },
    late_morning: { fromOffset: 6, toOffset: 8 },
    afternoon: { fromOffset: 9, toOffset: 14 },
    evening: { fromOffset: 15, toOffset: 18 },
    night: { fromOffset: 19, toOffset: 23 }
  };
  const days = JSON.parse(controls.dataset.days || "[]");
  const state = {
    selectedDay: controls.dataset.selectedDay,
    selectedPeriod: "all",
    fromOffset: null,
    toOffset: null,
    hours: []
  };
  const previous = document.querySelector("[data-day-previous]");
  const next = document.querySelector("[data-day-next]");
  const pickerTrigger = document.querySelector("[data-day-picker]");
  const picker = document.querySelector("[data-day-input]");
  const status = document.querySelector("[data-day-state]");
  const analyticsStatus = document.querySelector("[data-analytics-state]");
  const analyticsDashboard = document.querySelector(".analytics-dashboard");
  const presetButtons = [...document.querySelectorAll("[data-period]")];
  const analyticsValues = [...document.querySelectorAll("[data-analytics-value]")];
  const distributionValues = [...document.querySelectorAll("[data-distribution-value]")];
  const distributionFills = [...document.querySelectorAll("[data-distribution-fill]")];
  const worstTrip = document.querySelector("[data-worst-trip]");
  const worstTripPrimary = document.querySelector("[data-worst-trip-primary]");
  const worstTripDelay = document.querySelector("[data-worst-trip-delay]");
  const worstTripMaximumStop = document.querySelector("[data-worst-trip-maximum-stop]");
  const worstSegmentFrom = document.querySelector("[data-worst-segment-from]");
  const worstSegmentTo = document.querySelector("[data-worst-segment-to]");
  const worstSegmentDelay = document.querySelector("[data-worst-segment-delay]");
  const worstSegmentTime = document.querySelector("[data-worst-segment-time]");
  const largestEarlyPrimary = document.querySelector("[data-largest-early-primary]");
  const largestEarly = document.querySelector("[data-largest-early]");
  const largestEarlyStop = document.querySelector("[data-largest-early-stop]");
  const capturedPlanned = document.querySelector("[data-captured-planned]");
  const vehicles = document.querySelector("[data-vehicles]");
  const firstObserved = document.querySelector("[data-first-observed]");
  const firstObservedWrap = document.querySelector("[data-first-observed-wrap]");
  const realtimeObservations = document.querySelector("[data-realtime-observations]");
  const lastObserved = document.querySelector("[data-last-observed]");
  const collectorInterval = document.querySelector("[data-collector-interval]");
  const methodologyTrigger = document.querySelector("[data-methodology-trigger]");
  const methodologyDialog = document.querySelector("[data-methodology-dialog]");
  const methodologyClose = document.querySelector("[data-methodology-close]");
  let analyticsRequest = 0;
  let analyticsAbortController;

  const setStatus = message => {
    status.hidden = !message;
    status.textContent = message || "";
  };
  const setAnalyticsStatus = message => {
    analyticsStatus.hidden = !message;
    analyticsStatus.textContent = message || "";
  };
  const resetAnalytics = () => {
    analyticsValues.forEach(node => { node.textContent = "—"; });
    distributionValues.forEach(node => { node.textContent = "—"; });
    distributionFills.forEach(node => { node.style.width = "0%"; });
    worstTrip.removeAttribute("data-trip-id");
    worstTripPrimary.textContent = "—";
    worstTripDelay.hidden = true;
    worstTripDelay.textContent = "";
    worstTripMaximumStop.hidden = true;
    worstTripMaximumStop.textContent = "";
    worstSegmentFrom.textContent = "—";
    worstSegmentTo.hidden = true;
    worstSegmentTo.textContent = "";
    worstSegmentDelay.hidden = true;
    worstSegmentDelay.textContent = "";
    worstSegmentTime.hidden = true;
    worstSegmentTime.textContent = "";
    largestEarlyPrimary.textContent = "—";
    largestEarly.textContent = "—";
    largestEarly.hidden = true;
    largestEarlyStop.hidden = true;
    largestEarlyStop.textContent = "";
    capturedPlanned.textContent = "—";
    vehicles.textContent = "—";
    firstObserved.textContent = "—";
    firstObservedWrap.hidden = true;
    realtimeObservations.textContent = "—";
    lastObserved.textContent = "—";
    collectorInterval.textContent = "—";
  };
  const formatDelay = value => {
    if (!Number.isFinite(value)) return "—";
    const sign = value > 0 ? "+" : value < 0 ? "−" : "";
    return `${sign}${Math.abs(Math.round(value))} s`;
  };
  const formatNumber = value => Number.isFinite(value) ? new Intl.NumberFormat("cs-CZ").format(value) : "—";
  const formatTime = value => {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  };
  const setOptionalText = (node, value) => {
    node.hidden = !value;
    node.textContent = value || "";
  };
  const tripSummary = value => [value?.scheduled_start, value?.headsign && `→ ${value.headsign}`].filter(Boolean).join(" ");
  const stopSummary = (name, time) => [name, time].filter(Boolean).join(" · ");
  const renderAnalytics = payload => {
    analyticsValues.forEach(node => { node.textContent = formatDelay(payload[node.dataset.analyticsValue]); });
    const distribution = new Map((Array.isArray(payload.delay_distribution) ? payload.delay_distribution : []).map(bucket => [bucket.key, bucket]));
    distributionValues.forEach(node => {
      const percentage = distribution.get(node.dataset.distributionValue)?.percentage;
      node.textContent = Number.isFinite(percentage) ? `${percentage} %` : "—";
    });
    distributionFills.forEach(node => {
      const percentage = distribution.get(node.dataset.distributionFill)?.percentage;
      node.style.width = `${Number.isFinite(percentage) ? Math.max(0, Math.min(100, percentage)) : 0}%`;
    });
    const trip = payload.worst_trip;
    if (trip) {
      if (trip.trip_id) worstTrip.dataset.tripId = trip.trip_id;
      const summary = tripSummary(trip);
      worstTripPrimary.textContent = summary || formatDelay(trip.maximum_delay);
      setOptionalText(worstTripDelay, summary && Number.isFinite(trip.maximum_delay) ? `max. ${formatDelay(trip.maximum_delay)}` : null);
      setOptionalText(worstTripMaximumStop, stopSummary(trip.maximum_delay_stop_name, trip.maximum_delay_scheduled_time));
    }
    const segment = payload.worst_delay_segment;
    if (segment) {
      worstSegmentFrom.textContent = segment.from_stop_name || segment.to_stop_name || "—";
      setOptionalText(worstSegmentTo, segment.from_stop_name && segment.to_stop_name ? `→ ${segment.to_stop_name}` : null);
      setOptionalText(worstSegmentDelay, Number.isFinite(segment.delay_increase) ? formatDelay(segment.delay_increase) : null);
      setOptionalText(worstSegmentTime, segment.to_scheduled_time || null);
    }
    const early = payload.largest_early;
    if (early && typeof early === "object") {
      const summary = tripSummary(early);
      largestEarlyPrimary.textContent = summary || formatDelay(early.delay);
      setOptionalText(largestEarly, summary && Number.isFinite(early.delay) ? formatDelay(early.delay) : null);
      setOptionalText(largestEarlyStop, stopSummary(early.stop_name, early.scheduled_time));
    }
    capturedPlanned.textContent = Number.isFinite(payload.captured_trips) && Number.isFinite(payload.planned_trips) ? `${formatNumber(payload.captured_trips)} / ${formatNumber(payload.planned_trips)}` : "—";
    vehicles.textContent = formatNumber(payload.vehicles);
    const firstTime = formatTime(payload.first_observed_at);
    firstObserved.textContent = firstTime || "—";
    firstObservedWrap.hidden = !firstTime;
    realtimeObservations.textContent = formatNumber(payload.realtime_observations);
    lastObserved.textContent = formatTime(payload.last_observed_at) || "—";
    collectorInterval.textContent = Number.isFinite(payload.collector_interval) ? `${formatNumber(payload.collector_interval)} s` : "—";
  };
  const loadAnalytics = async () => {
    analyticsRequest += 1;
    const request = analyticsRequest;
    if (analyticsAbortController) analyticsAbortController.abort();
    analyticsAbortController = new AbortController();
    analyticsDashboard.setAttribute("aria-busy", "true");
    resetAnalytics();
    setAnalyticsStatus("");
    const params = new URLSearchParams();
    if (state.fromOffset !== null) {
      params.set("from_offset", state.fromOffset);
      params.set("to_offset", state.toOffset);
    }
    const suffix = params.size ? `?${params}` : "";
    try {
      const response = await fetch(`/api/day/${encodeURIComponent(state.selectedDay)}/analytics${suffix}`, { signal: analyticsAbortController.signal });
      if (!response.ok) throw new Error("analytics unavailable");
      const payload = await response.json();
      if (request !== analyticsRequest) return;
      renderAnalytics(payload);
      analyticsDashboard.setAttribute("aria-busy", "false");
    } catch (error) {
      if (error.name === "AbortError" || request !== analyticsRequest) return;
      resetAnalytics();
      setAnalyticsStatus("Analytika vybraného období není nyní k dispozici.");
      analyticsDashboard.setAttribute("aria-busy", "false");
    }
  };
  const setPeriod = (key, { load = true } = {}) => {
    const period = periods[key];
    state.selectedPeriod = key;
    state.fromOffset = period.fromOffset;
    state.toOffset = period.toOffset;
    presetButtons.forEach(button => {
      const active = button.dataset.period === key;
      button.classList.toggle("period-preset--active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    window.TunelbusDay = { ...state };
    if (load) loadAnalytics();
  };
  const updateAvailability = () => {
    const availableOffsets = new Set(state.hours.filter(hour => !hour.future).map(hour => hour.offset));
    presetButtons.forEach(button => {
      const period = periods[button.dataset.period];
      const enabled = button.dataset.period === "all" || [...availableOffsets].some(offset => offset >= period.fromOffset && offset <= period.toOffset);
      button.disabled = !enabled;
      if (button.disabled && button.dataset.period === state.selectedPeriod) setPeriod("all", { load: false });
    });
  };
  const loadHours = async () => {
    presetButtons.forEach(button => { if (button.dataset.period !== "all") button.disabled = true; });
    try {
      const response = await fetch(`/api/day/${encodeURIComponent(state.selectedDay)}/hours`);
      if (!response.ok) throw new Error("hours unavailable");
      const payload = await response.json();
      state.hours = Array.isArray(payload.hours) ? payload.hours : [];
      updateAvailability();
      setStatus("");
    } catch {
      state.hours = [];
      updateAvailability();
      setStatus("Časové části dne nejsou nyní k dispozici.");
    }
    window.TunelbusDay = { ...state };
  };
  const navigateTo = day => {
    if (!day || !days.includes(day)) return;
    const url = new URL(window.location.href);
    url.searchParams.set("date", day);
    window.location.assign(url);
  };

  previous.addEventListener("click", () => navigateTo(controls.dataset.previousDay));
  next.addEventListener("click", () => navigateTo(controls.dataset.nextDay));
  pickerTrigger.addEventListener("click", () => {
    if (typeof picker.showPicker === "function") picker.showPicker();
    else { picker.focus(); picker.click(); }
  });
  picker.addEventListener("change", () => {
    if (days.includes(picker.value)) navigateTo(picker.value);
    else setStatus("Pro vybraný den nejsou dostupná data.");
  });
  presetButtons.forEach(button => button.addEventListener("click", () => {
    if (!button.disabled) setPeriod(button.dataset.period);
  }));
  if (methodologyTrigger && methodologyDialog && methodologyClose) {
    const closeMethodology = () => methodologyDialog.close();
    methodologyTrigger.addEventListener("click", () => {
      methodologyDialog.showModal();
      methodologyTrigger.setAttribute("aria-expanded", "true");
      methodologyClose.focus();
    });
    methodologyClose.addEventListener("click", closeMethodology);
    methodologyDialog.addEventListener("cancel", event => { event.preventDefault(); closeMethodology(); });
    methodologyDialog.addEventListener("click", event => { if (event.target === methodologyDialog) closeMethodology(); });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && methodologyDialog.open) { event.preventDefault(); closeMethodology(); }
    });
    methodologyDialog.addEventListener("close", () => {
      methodologyTrigger.setAttribute("aria-expanded", "false");
      methodologyTrigger.focus();
    });
  }

  setPeriod("all", { load: false });
  loadHours();
  loadAnalytics();
})();

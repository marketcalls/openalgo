const runsListEl = document.getElementById("runsList");
const statusEl = document.getElementById("statusMessage");
const runTitleEl = document.getElementById("runTitle");
const runMetaEl = document.getElementById("runMeta");
const tradesBodyEl = document.getElementById("tradesBody");
const ordersBodyEl = document.getElementById("ordersBody");
const equityChartContainerEl = document.getElementById("equityChart");
const drawdownChartContainerEl = document.getElementById("drawdownChart");

let activeRunId = "";
let equityChart = null;
let drawdownChart = null;
let equitySeries = null;
let drawdownSeries = null;
let chartResizeObserver = null;
let allRuns = [];
let filteredRuns = [];

function queryRunId() {
  const params = new URLSearchParams(globalThis.location.search);
  return params.get("run") || "";
}

function fmtNumber(value, suffix = "") {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return `${value.toFixed(2)}${suffix}`;
}

function fmtDateTime(value) {
  if (!value) {
    return "-";
  }
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) {
    return value;
  }
  return dt.toLocaleString();
}

function formatShortDate(value) {
  if (!value || value === "?") return "?";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function toEpochSeconds(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    if (value > 10_000_000_000) {
      return Math.floor(value / 1000);
    }
    return Math.floor(value);
  }

  if (typeof value !== "string" || !value.trim()) {
    return null;
  }

  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return null;
  }

  return Math.floor(parsed / 1000);
}

function toIsoDateFromEpoch(epochSeconds) {
  if (!Number.isFinite(epochSeconds)) {
    return "?";
  }
  return new Date(epochSeconds * 1000).toISOString().slice(0, 10);
}

function deriveTradeWindow(trades) {
  if (!Array.isArray(trades) || !trades.length) {
    return { start: null, end: null };
  }

  let start = null;
  let end = null;

  trades.forEach((trade) => {
    if (!trade || typeof trade !== "object") {
      return;
    }

    const tradeStart = toEpochSeconds(trade.startDateTime);
    const tradeEnd = toEpochSeconds(trade.endDateTime);

    if (Number.isFinite(tradeStart)) {
      start = start === null ? tradeStart : Math.min(start, tradeStart);
    }

    if (Number.isFinite(tradeEnd)) {
      end = end === null ? tradeEnd : Math.max(end, tradeEnd);
    }
  });

  return { start, end };
}

function deriveOrderWindow(orders) {
  if (!Array.isArray(orders) || !orders.length) {
    return { start: null, end: null };
  }

  let start = null;
  let end = null;

  orders.forEach((order) => {
    if (!order || typeof order !== "object") {
      return;
    }

    const orderTime = toEpochSeconds(order.time);
    if (!Number.isFinite(orderTime)) {
      return;
    }

    start = start === null ? orderTime : Math.min(start, orderTime);
    end = end === null ? orderTime : Math.max(end, orderTime);
  });

  return { start, end };
}

function derivePointWindow(points) {
  if (!Array.isArray(points) || !points.length) {
    return { start: null, end: null };
  }

  let start = null;
  let end = null;

  points.forEach((point) => {
    if (!point || typeof point !== "object") {
      return;
    }
    const t = toEpochSeconds(point.t);
    if (!Number.isFinite(t)) {
      return;
    }
    start = start === null ? t : Math.min(start, t);
    end = end === null ? t : Math.max(end, t);
  });

  return { start, end };
}

function deriveEffectiveRange(dateRange, trades, orders, points) {
  const tradeWindow = deriveTradeWindow(trades);
  const orderWindow = deriveOrderWindow(orders);

  const activityStarts = [tradeWindow.start, orderWindow.start].filter((v) => Number.isFinite(v));
  const activityEnds = [tradeWindow.end, orderWindow.end].filter((v) => Number.isFinite(v));
  if (activityStarts.length && activityEnds.length) {
    return {
      start: Math.min(...activityStarts),
      end: Math.max(...activityEnds),
    };
  }

  const configuredStart = toEpochSeconds(dateRange?.start);
  const configuredEnd = toEpochSeconds(dateRange?.end);
  if (Number.isFinite(configuredStart) && Number.isFinite(configuredEnd)) {
    return { start: configuredStart, end: configuredEnd };
  }

  return derivePointWindow(points);
}

function filterPointsByRange(points, range) {
  if (!Array.isArray(points)) {
    return [];
  }

  const hasRange = range && Number.isFinite(range.start) && Number.isFinite(range.end);
  if (hasRange) {
    return points.filter((point) => {
      if (!point || typeof point !== "object") {
        return false;
      }
      const t = toEpochSeconds(point.t);
      return Number.isFinite(t) && t >= range.start && t <= range.end;
    });
  }

  return points;
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Request failed (${response.status}): ${text}`);
  }
  return response.json();
}

function renderRuns(runs, selectedRunId) {
  runsListEl.innerHTML = "";
  const emptyStateEl = document.getElementById("emptyState");
  const runsCountEl = document.getElementById("runsCount");

  if (!runs.length) {
    if (emptyStateEl) emptyStateEl.style.display = "block";
    if (runsCountEl) runsCountEl.textContent = "";
    return;
  }

  if (emptyStateEl) emptyStateEl.style.display = "none";
  if (runsCountEl) runsCountEl.textContent = `${runs.length} of ${allRuns.length} run${allRuns.length !== 1 ? "s" : ""}`;

  runs.forEach((run) => {
    const runId = run.runId || "";
    const item = document.createElement("button");
    item.type = "button";
    item.className = `run-item ${runId === selectedRunId ? "active" : ""}`;
    item.dataset.runId = runId;

    const start = run.dateRange?.start || "?";
    const end = run.dateRange?.end || "?";
    const netProfit = run.metrics?.netProfitPct;
    const pnlClass = typeof netProfit === "number" ? (netProfit >= 0 ? "pnl-positive" : "pnl-negative") : "";
    const pnlText = typeof netProfit === "number" ? `${netProfit >= 0 ? "+" : ""}${netProfit.toFixed(2)}%` : "-";
    const status = (run.status || "Unknown").toLowerCase();
    const statusClass = status === "completed" ? "completed" : "failed";

    item.innerHTML = `
      <h4>
        <span>${run.algorithmType || "Unknown Strategy"}</span>
        <span class="status-badge ${statusClass}">${run.status || "Unknown"}</span>
      </h4>
      <p>${fmtDateTime(run.timestamp)}</p>
      <p>${formatShortDate(start)} → ${formatShortDate(end)}</p>
      <p class="${pnlClass}">Net ${pnlText}</p>
    `;

    item.addEventListener("click", () => {
      void loadRun(runId, allRuns);
    });

    runsListEl.appendChild(item);
  });
}

function applyFilters() {
  const searchText = (document.getElementById("searchInput")?.value || "").toLowerCase().trim();
  const dateFrom = document.getElementById("dateFrom")?.value || "";
  const dateTo = document.getElementById("dateTo")?.value || "";
  const sortBy = document.getElementById("sortSelect")?.value || "newest";

  filteredRuns = allRuns.filter((run) => {
    // Text search: match algorithm name or runId
    if (searchText) {
      const name = (run.algorithmType || "").toLowerCase();
      const id = (run.runId || "").toLowerCase();
      if (!name.includes(searchText) && !id.includes(searchText)) {
        return false;
      }
    }

    // Date range filter: check overlap with backtest date range
    if (dateFrom || dateTo) {
      const runStart = run.dateRange?.start ? new Date(run.dateRange.start).getTime() : null;
      const runEnd = run.dateRange?.end ? new Date(run.dateRange.end).getTime() : null;

      if (dateFrom) {
        const fromMs = new Date(dateFrom).getTime();
        if (runEnd && runEnd < fromMs) return false;
      }

      if (dateTo) {
        const toMs = new Date(dateTo + "T23:59:59Z").getTime();
        if (runStart && runStart > toMs) return false;
      }
    }

    return true;
  });

  // Sort
  filteredRuns.sort((a, b) => {
    switch (sortBy) {
      case "newest":
        return new Date(b.timestamp || 0).getTime() - new Date(a.timestamp || 0).getTime();
      case "oldest":
        return new Date(a.timestamp || 0).getTime() - new Date(b.timestamp || 0).getTime();
      case "profit":
        return (b.metrics?.netProfitPct ?? -Infinity) - (a.metrics?.netProfitPct ?? -Infinity);
      case "drawdown":
        return (a.metrics?.drawdownPct ?? Infinity) - (b.metrics?.drawdownPct ?? Infinity);
      default:
        return 0;
    }
  });

  // Re-render with current active run
  renderRuns(filteredRuns, activeRunId);
}

function clearFilters() {
  const searchInput = document.getElementById("searchInput");
  const dateFrom = document.getElementById("dateFrom");
  const dateTo = document.getElementById("dateTo");
  const sortSelect = document.getElementById("sortSelect");

  if (searchInput) searchInput.value = "";
  if (dateFrom) dateFrom.value = "";
  if (dateTo) dateTo.value = "";
  if (sortSelect) sortSelect.value = "newest";

  applyFilters();
}

function setKpi(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = value;
  }
}

function chartLibReady() {
  return globalThis.LightweightCharts !== undefined;
}

function chartThemeOptions() {
  return {
    layout: {
      background: { type: "solid", color: "#fcfcfd" },
      textColor: "#5f6a7a",
      fontFamily: '"Avenir Next", "Segoe UI", sans-serif',
    },
    grid: {
      vertLines: { color: "#edf0f4" },
      horzLines: { color: "#edf0f4" },
    },
    rightPriceScale: {
      borderColor: "#e6e8ec",
    },
    timeScale: {
      borderColor: "#e6e8ec",
      timeVisible: true,
      secondsVisible: false,
    },
    crosshair: {
      vertLine: { color: "#c7d0db" },
      horzLine: { color: "#c7d0db" },
    },
    handleScroll: true,
    handleScale: true,
  };
}

function ensureCharts() {
  if (!chartLibReady() || equityChart || drawdownChart) {
    return;
  }

  const width1 = Math.max(320, Math.floor(equityChartContainerEl.clientWidth || 800));
  const width2 = Math.max(320, Math.floor(drawdownChartContainerEl.clientWidth || 800));
  const baseOptions = chartThemeOptions();

  equityChart = globalThis.LightweightCharts.createChart(equityChartContainerEl, {
    ...baseOptions,
    width: width1,
    height: 260,
  });

  drawdownChart = globalThis.LightweightCharts.createChart(drawdownChartContainerEl, {
    ...baseOptions,
    width: width2,
    height: 260,
  });

  const lineSeriesOpts = {
    color: "#006a6a",
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: true,
  };

  const drawdownSeriesOpts = {
    color: "#9d2a2a",
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: true,
  };

  // Lightweight Charts v5+ uses addSeries(LineSeries, options) instead of addLineSeries(options)
  const LineSeries = globalThis.LightweightCharts.LineSeries;
  if (LineSeries && typeof equityChart.addSeries === "function") {
    equitySeries = equityChart.addSeries(LineSeries, lineSeriesOpts);
    drawdownSeries = drawdownChart.addSeries(LineSeries, drawdownSeriesOpts);
  } else if (typeof equityChart.addLineSeries === "function") {
    equitySeries = equityChart.addLineSeries(lineSeriesOpts);
    drawdownSeries = drawdownChart.addLineSeries(drawdownSeriesOpts);
  }

  if (typeof ResizeObserver !== "undefined" && !chartResizeObserver) {
    chartResizeObserver = new ResizeObserver(() => {
      if (equityChart) {
        equityChart.applyOptions({ width: Math.max(320, Math.floor(equityChartContainerEl.clientWidth || 800)) });
      }
      if (drawdownChart) {
        drawdownChart.applyOptions({ width: Math.max(320, Math.floor(drawdownChartContainerEl.clientWidth || 800)) });
      }
    });

    chartResizeObserver.observe(equityChartContainerEl);
    chartResizeObserver.observe(drawdownChartContainerEl);
  }
}

function toLineData(points) {
  if (!Array.isArray(points)) {
    return [];
  }

  const mapByTime = new Map();
  points.forEach((point) => {
    if (!point || typeof point !== "object") {
      return;
    }
    const time = toEpochSeconds(point.t);
    const value = Number(point.v);
    if (!time || !Number.isFinite(value)) {
      return;
    }
    mapByTime.set(time, value);
  });

  return Array.from(mapByTime.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([time, value]) => ({ time, value }));
}

function applySeriesMarkers(series, markers) {
  if (!series) {
    return;
  }

  // Lightweight Charts v5+ uses createSeriesMarkers(series, markers)
  const createSeriesMarkers = globalThis.LightweightCharts?.createSeriesMarkers;
  if (createSeriesMarkers !== undefined) {
    createSeriesMarkers(series, markers);
    return;
  }

  // Fallback for older versions
  if (typeof series.setMarkers === "function") {
    series.setMarkers(markers);
  }
}

function buildTradeAndOrderMarkers(trades, orders) {
  const markers = [];

  if (Array.isArray(trades)) {
    trades.forEach((trade) => {
      const directionText = String(trade.direction || "").toLowerCase();
      const isBuy = directionText.includes("buy") || directionText.includes("long");
      const symbol = String(trade.symbol || "");
      const pnl = Number(trade.profitLoss);

      const entryTime = toEpochSeconds(trade.startDateTime);
      if (entryTime) {
        markers.push({
          time: entryTime,
          position: isBuy ? "belowBar" : "aboveBar",
          color: isBuy ? "#0f8a5f" : "#b53a2d",
          shape: isBuy ? "arrowUp" : "arrowDown",
          text: `${symbol} entry`,
        });
      }

      const exitTime = toEpochSeconds(trade.endDateTime);
      if (exitTime) {
        const profitable = Number.isFinite(pnl) ? pnl >= 0 : true;
        markers.push({
          time: exitTime,
          position: "inBar",
          color: profitable ? "#246bce" : "#9d2a2a",
          shape: "circle",
          text: `${symbol} exit ${Number.isFinite(pnl) ? pnl.toFixed(2) : ""}`.trim(),
        });
      }
    });
  }

  if (Array.isArray(orders)) {
    orders.forEach((order) => {
      const orderTime = toEpochSeconds(order.time);
      if (!orderTime) {
        return;
      }

      const directionText = String(order.direction || "").toLowerCase();
      const isBuy = directionText.includes("buy") || directionText.includes("long") || directionText === "0";
      const symbol = String(order.symbol || "");

      markers.push({
        time: orderTime,
        position: isBuy ? "belowBar" : "aboveBar",
        color: isBuy ? "#3f9f4d" : "#c24a38",
        shape: isBuy ? "arrowUp" : "arrowDown",
        text: `${symbol} ${isBuy ? "buy" : "sell"}`.trim(),
      });
    });
  }

  markers.sort((a, b) => a.time - b.time);
  return markers;
}

function renderEquityChart(points, trades, orders, effectiveRange) {
  if (!chartLibReady()) {
    equityChartContainerEl.textContent = "Chart library did not load.";
    return;
  }

  ensureCharts();
  if (!equitySeries || !equityChart) {
    return;
  }

  const filteredPoints = filterPointsByRange(points, effectiveRange);
  const lineData = toLineData(filteredPoints);
  equitySeries.setData(lineData);

  const markers = buildTradeAndOrderMarkers(trades, orders).filter((marker) => {
    if (!effectiveRange || !Number.isFinite(effectiveRange.start) || !Number.isFinite(effectiveRange.end)) {
      return true;
    }
    return marker.time >= effectiveRange.start && marker.time <= effectiveRange.end;
  });
  applySeriesMarkers(equitySeries, markers);

  if (lineData.length) {
    equityChart.timeScale().fitContent();
  }
}

function renderDrawdownChart(points, effectiveRange) {
  if (!chartLibReady()) {
    drawdownChartContainerEl.textContent = "Chart library did not load.";
    return;
  }

  ensureCharts();
  if (!drawdownSeries || !drawdownChart) {
    return;
  }

  const filteredPoints = filterPointsByRange(points, effectiveRange);
  const lineData = toLineData(filteredPoints);
  drawdownSeries.setData(lineData);
  applySeriesMarkers(drawdownSeries, []);

  if (lineData.length) {
    drawdownChart.timeScale().fitContent();
  }
}

function renderTrades(trades) {
  tradesBodyEl.innerHTML = "";
  if (!Array.isArray(trades) || !trades.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="8">No closed trades for this run.</td>';
    tradesBodyEl.appendChild(row);
    return;
  }

  trades.forEach((trade) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${trade.symbol || ""}</td>
      <td>${trade.direction || ""}</td>
      <td>${fmtNumber(trade.quantity)}</td>
      <td>${fmtNumber(trade.entryPrice)}</td>
      <td>${fmtNumber(trade.exitPrice)}</td>
      <td>${fmtNumber(trade.profitLoss)}</td>
      <td>${fmtDateTime(trade.startDateTime)}</td>
      <td>${fmtDateTime(trade.endDateTime)}</td>
    `;
    tradesBodyEl.appendChild(row);
  });
}

function renderOrders(orders) {
  ordersBodyEl.innerHTML = "";

  if (!Array.isArray(orders) || !orders.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="6">No executions captured for this run.</td>';
    ordersBodyEl.appendChild(row);
    return;
  }

  orders.forEach((order) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${fmtDateTime(order.time)}</td>
      <td>${order.symbol || ""}</td>
      <td>${order.direction || ""}</td>
      <td>${fmtNumber(order.quantity)}</td>
      <td>${fmtNumber(order.price)}</td>
      <td>${order.status || ""}</td>
    `;
    ordersBodyEl.appendChild(row);
  });
}

async function loadRun(runId, runsCache = null) {
  if (!runId) {
    return;
  }

  statusEl.textContent = "Loading run details...";

  try {
    const runPayload = await fetchJson(`/api/runs/${runId}`);
    const summary = runPayload.summary || {};
    const dateRange = runPayload.dateRange || {};
    const effectiveRange = deriveEffectiveRange(
      dateRange,
      runPayload.trades || [],
      runPayload.orders || [],
      runPayload.equity || []
    );

    activeRunId = runId;

    runTitleEl.textContent = `${runPayload.algorithmType || "Strategy"} (${runId})`;
    runMetaEl.textContent = `Range: ${toIsoDateFromEpoch(effectiveRange.start)} to ${toIsoDateFromEpoch(effectiveRange.end)} | Status: ${runPayload.status || "Unknown"}`;

    setKpi("kpiNetProfit", `${fmtNumber(summary.netProfitPct, "%")}`);
    setKpi("kpiDrawdown", `${fmtNumber(summary.drawdownPct, "%")}`);
    setKpi("kpiSharpe", fmtNumber(summary.sharpeRatio));
    setKpi("kpiOrders", String(summary.totalOrders ?? 0));

    renderEquityChart(runPayload.equity || [], runPayload.trades || [], runPayload.orders || [], effectiveRange);
    renderDrawdownChart(runPayload.drawdown || [], effectiveRange);
    renderTrades(runPayload.trades || []);
    renderOrders(runPayload.orders || []);

    if (runsCache) {
      allRuns = runsCache;
    }
    applyFilters();

    statusEl.textContent = "";
  } catch (error) {
    statusEl.textContent = error instanceof Error ? error.message : String(error);
  }
}

async function bootstrap() {
  try {
    const runsResp = await fetchJson("/api/runs");
    const runs = Array.isArray(runsResp.runs) ? runsResp.runs : [];

    if (!runs.length) {
      allRuns = [];
      renderRuns([], "");
      statusEl.textContent = "No archived backtests yet. Run a strategy first.";
      return;
    }

    allRuns = runs;
    filteredRuns = runs;

    // Wire up filter event listeners
    document.getElementById("searchInput")?.addEventListener("input", () => applyFilters());
    document.getElementById("dateFrom")?.addEventListener("change", () => applyFilters());
    document.getElementById("dateTo")?.addEventListener("change", () => applyFilters());
    document.getElementById("sortSelect")?.addEventListener("change", () => applyFilters());
    document.getElementById("clearFilters")?.addEventListener("click", () => clearFilters());

    const requestedRunId = queryRunId();
    const selected = runs.find((run) => run.runId === requestedRunId)?.runId || runs[0].runId;

    await loadRun(selected, runs);
  } catch (error) {
    statusEl.textContent = error instanceof Error ? error.message : String(error);
  }
}

await bootstrap();

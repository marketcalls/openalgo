/**
 * OpenAlgo /trading — line-based chart trading on openalgo-charts.
 *
 * Bootstraps from the logged-in session (API key + WS URL), then drives
 * everything through the public /api/v1/* endpoints and the WebSocket proxy:
 * history → live candles → on-chart order lines (right-click to place, drag to
 * modify, ✕ to cancel) with real-time order updates, in analyzer or live mode.
 * FnO quantities are entered in lots (converted via the symbol's lot size) and
 * every price is snapped to the instrument's tick size.
 */
import {
  createChart, OpenAlgoDataFeed, OpenAlgoWsFeed, OpenAlgoTradeFeed,
  CandleBuilder, darkTheme, lightTheme, LogoWatermark, BuySellButtons,
} from './openalgo-charts.mjs';
import {
  runTransform, HeikinAshiTransform, RenkoTransform, RangeBarsTransform,
  LineBreakTransform,
} from './openalgo-charts.transform.mjs';

const el = (id) => document.getElementById(id);
const nowSec = () => Math.floor(Date.now() / 1000);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* ── state ──────────────────────────────────────────────────────────────── */
let apiKey = null;
let wsUrl = null;
let chart = null, price = null, volume = null, ltpLine = null, posLine = null, tradeBtns = null;
let ws = null, rest = null, trade = null, builder = null, offLtp = null;
let rawBars = [];            // raw OHLC (history + live-built bars)
let liveBucket = null;       // time of the forming live bar
let lastLtp = null, prevClose = null, tickN = 0;
let sym = null;              // { symbol, exchange, name, lotsize, tick, freezeQty, instrumenttype, quoteOnly }
let bookTimer = null, reconcileTimer = null;
let ctxPrice = 0;
let position = null;         // { net, avg, product }
const orderLines = new Map();// orderid -> { line, order }
let analyzerMode = null;     // null until the API tells us; analyzer locks the theme

const DERIVATIVE_EXCHANGES = new Set(['NFO', 'BFO', 'CDS', 'BCD', 'MCX', 'NCO', 'NCDEX']);
const QUOTE_ONLY = new Set(['NSE_INDEX', 'BSE_INDEX', 'MCX_INDEX', 'GLOBAL_INDEX']);
const STRATEGY = 'chart-trading';

/* history lookback (days) per interval token */
function lookbackDays(interval) {
  const m = /^(\d+)([smh])$/.exec(interval);
  if (m) {
    const n = Number(m[1]);
    if (m[2] === 's') return 2;
    if (m[2] === 'm') return n <= 1 ? 7 : n <= 5 ? 30 : n <= 15 ? 60 : 120;
    return 180; // hours
  }
  if (interval === 'D') return 3 * 365;
  if (interval === 'W') return 5 * 365;
  if (interval === 'M') return 10 * 365;
  return 30;
}

/* interval token → seconds (null = no intraday aggregation, e.g. D/W/M) */
function intervalSeconds(interval) {
  const m = /^(\d+)([smh])$/.exec(interval);
  if (!m) return null;
  const n = Number(m[1]);
  return m[2] === 's' ? n : m[2] === 'm' ? n * 60 : n * 3600;
}

/* ── tick-size helpers ──────────────────────────────────────────────────── */
const tickDecimals = () => {
  const t = String(sym?.tick ?? 0.05);
  return t.includes('.') ? Math.min(6, t.split('.')[1].length) : 0;
};
function snapTick(p) {
  const tick = sym?.tick || 0.05;
  return Number((Math.round(p / tick) * tick).toFixed(tickDecimals()));
}
const fmt = (n) => Number(n).toLocaleString('en-IN', {
  minimumFractionDigits: Math.min(2, tickDecimals() || 2), maximumFractionDigits: Math.max(2, tickDecimals()),
});

/* ── toast + status ─────────────────────────────────────────────────────── */
let toastTimer = null;
function toast(msg, kind = '') {
  const t = el('toast');
  t.textContent = msg;
  t.className = kind;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3800);
}
const status = (msg) => { el('status').textContent = msg; };

/* Trader-facing error text: strip the technical "openalgo-charts: /api/v1/x
 * failed (nnn):" chain and keep the broker/OpenAlgo message. The full error
 * always lands in the console for debugging. */
function cleanError(e) {
  console.error('[trading]', e);
  let m = String((e && e.message) || e || 'request failed');
  m = m.replace(/^openalgo-charts:\s*/i, '').replace(/^\/api\/v1\/[\w/]+\s+failed\s+\(\d+\)(:\s*)?/i, '');
  return m.trim() || 'request failed';
}

/* connection LED: green = live stream, amber = degraded/connecting, red = down */
function setWs(state) {
  const led = el('wsled');
  const cls = state === 'live' || state === 'open' ? 'ok'
    : state === 'closed' || state === 'error' || state === 'auth failed' ? 'off' : 'warn';
  led.className = `led ${cls}`;
  led.title = state === 'live' ? 'live — WebSocket streaming'
    : state === 'fallback' ? 'WebSocket down — REST fallback active'
    : `WebSocket ${state}`;
}

function setMode(m) {
  const e = el('mode');
  if (m === 'analyze' || m === 'analyzer') { e.textContent = 'Analyze Mode'; e.className = 'analyze'; analyzerMode = true; }
  else if (m === 'live') { e.textContent = 'Live Mode'; e.className = 'live'; analyzerMode = false; }
  applyTheme();
}
const isLiveMode = () => el('mode').classList.contains('live');

/* ── theme sync with the app (openalgo-theme in shared localStorage) ─────── */
function appThemeMode() {
  try { return JSON.parse(localStorage.getItem('openalgo-theme') || '{}').state?.mode || 'dark'; }
  catch (_) { return 'dark'; }
}
function themeKey() {
  if (analyzerMode !== false) return 'analyzer'; // sandbox: violet theme, locked (like the app)
  return appThemeMode() === 'light' ? 'live-light' : 'live-dark';
}
const isLightTheme = () => document.documentElement.dataset.theme === 'live-light';
function applyTheme() {
  const k = themeKey();
  el('themebtn').hidden = analyzerMode !== false; // theme is not changeable in sandbox
  if (document.documentElement.dataset.theme === k) return;
  document.documentElement.dataset.theme = k;
  if (chart && rawBars.length) buildChart(); // repaint canvas chrome with the new tokens
}
window.addEventListener('storage', (e) => { if (e.key === 'openalgo-theme') applyTheme(); });

/* ⚡ toggles analyze ↔ live (like the app header) */
el('modetoggle').addEventListener('click', async () => {
  if (analyzerMode === null || el('modetoggle').disabled) return;
  const toAnalyzer = !analyzerMode;
  el('modetoggle').disabled = true;
  try {
    const j = await api('analyzer/toggle', { mode: toAnalyzer });
    setMode(j.data?.mode || (toAnalyzer ? 'analyze' : 'live'));
    toast(toAnalyzer ? 'Analyze mode — orders go to the sandbox' : 'LIVE mode — orders hit your broker', toAnalyzer ? 'ok' : 'err');
    pollBook(); // books differ between modes
  } catch (e) { toast(`mode toggle failed: ${cleanError(e)}`, 'err'); }
  el('modetoggle').disabled = false;
});

/* profile flyout */
el('avatar').addEventListener('click', (e) => {
  e.stopPropagation();
  el('pmenu').hidden = !el('pmenu').hidden;
});
document.addEventListener('click', (e) => { if (!e.target.closest('.pwrap')) el('pmenu').hidden = true; });

/* ── API helpers (same-origin /api/v1) ──────────────────────────────────── */
async function api(path, body = {}) {
  const res = await fetch(`/api/v1/${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ apikey: apiKey, ...body }),
  });
  const j = await res.json().catch(() => ({}));
  if (j && j.mode) setMode(j.mode);
  if (!res.ok || j.status === 'error') throw new Error(j.message || `${path} failed (${res.status})`);
  return j;
}

/* ── chart types (transforms bucket volume onto their own element times) ── */
const boxOf = () => {
  const c = rawBars.length ? rawBars[rawBars.length - 1].close : 100;
  const tick = sym?.tick || 0.05;
  return Math.max(tick, Number((Math.round((c * 0.0015) / tick) * tick).toFixed(tickDecimals())));
};
const CHART_TYPES = {
  candlestick: { series: 'candlestick' }, 'hollow-candle': { series: 'hollow-candle' }, bar: { series: 'bar' },
  'high-low': { series: 'high-low' }, 'volume-candle': { series: 'volume-candle' }, line: { series: 'line' },
  'line-markers': { series: 'line-markers' }, step: { series: 'step' }, area: { series: 'area' },
  'hlc-area': { series: 'hlc-area' },
  baseline: { series: 'baseline', style: () => ({ baseValue: rawBars.reduce((s, b) => s + b.close, 0) / (rawBars.length || 1) }) },
  'heikin-ashi': { series: 'candlestick', tf: () => new HeikinAshiTransform() },
  renko: { series: 'candlestick', tf: () => new RenkoTransform({ boxSize: boxOf() }) },
  range: { series: 'candlestick', tf: () => new RangeBarsTransform({ range: boxOf() }) },
  'line-break': { series: 'candlestick', tf: () => new LineBreakTransform({ lines: 3 }) },
};
const chartType = () => CHART_TYPES[el('ctype').value] || CHART_TYPES.candlestick;

function bucketVolume(tbars) {
  const out = []; let ri = 0;
  for (const tb of tbars) {
    let v = 0;
    while (ri < rawBars.length && rawBars[ri].time <= tb.time) { v += rawBars[ri].volume || 0; ri++; }
    out.push({ time: tb.time, open: 0, high: v, low: 0, close: v });
  }
  let rest_ = 0;
  while (ri < rawBars.length) { rest_ += rawBars[ri].volume || 0; ri++; }
  if (out.length && rest_) { const last = out[out.length - 1]; last.high += rest_; last.close += rest_; }
  return out;
}

let shownCount = 0; // elements in the rendered price series (≠ rawBars for transforms)
function setPriceData() {
  if (!price || !rawBars.length) return;
  const cfg = chartType();
  if (cfg.tf) {
    const t = runTransform(cfg.tf(), rawBars);
    price.setData(t);
    volume.setData(bucketVolume(t));
    shownCount = t.length;
  } else {
    price.setData(rawBars);
    volume.setData(rawBars.map((b) => ({ time: b.time, open: 0, high: b.volume || 0, low: 0, close: b.volume || 0 })));
    shownCount = rawBars.length;
  }
}

/* ── legend ─────────────────────────────────────────────────────────────── */
function setLegend(bar) {
  if (!sym) { el('legend').innerHTML = ''; return; }
  const lots = sym.lots ? ` · lot ${sym.lotsize}` : '';
  const col = bar && bar.close >= bar.open ? 'up' : 'dn';
  const chg = lastLtp != null && prevClose ? ((lastLtp - prevClose) / prevClose) * 100 : null;
  el('legend').innerHTML =
    `<b>${esc(sym.symbol)}</b> <span style="opacity:.55">· ${esc(el('interval').value)} · ${esc(sym.exchange)}${lots}</span>` +
    (bar ? ` <span class="${col}">O ${fmt(bar.open)} H ${fmt(bar.high)} L ${fmt(bar.low)} C ${fmt(bar.close)}</span>` : '') +
    (lastLtp != null ? ` <span class="ltpc">LTP ${fmt(lastLtp)}</span>` : '') +
    (chg != null ? ` <span class="${chg >= 0 ? 'up' : 'dn'}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span>` : '');
}

/* ── trading: order lines / position (proven flow from the charts live demo) */
function makeOrderLine(o) {
  return chart.addPriceLine({
    price: o.triggerPrice ?? o.price, color: o.side === 'BUY' ? '#26a69a' : '#ef5350',
    lineWidth: 1, dashed: true, id: `order:${o.id}`, cursor: 'ns-resize', extentFromRight: 0.30,
    closeButton: true, badge: o.side, qty: o.qty, leftLabel: o.type,
  }, 0);
}

function posLabel() {
  if (!position) return '';
  const mark = lastLtp != null ? lastLtp : position.avg;
  const pnl = (mark - position.avg) * position.net;
  return `@ ${fmt(position.avg)}  ${pnl >= 0 ? '+' : '-'}₹${Math.round(Math.abs(pnl)).toLocaleString('en-IN')}`;
}

function renderPosition(pos) {
  if (posLine && chart) { chart.removePrimitive(posLine); posLine = null; }
  position = pos ? { net: Number(pos.quantity), avg: Number(pos.average_price), product: pos.product } : null;
  if (!position || !chart || position.net === 0) { position = position && position.net !== 0 ? position : null; return; }
  posLine = chart.addPriceLine({
    price: position.avg, color: position.net > 0 ? '#2e7d6b' : '#a14a52', lineWidth: 2, dashed: false,
    id: 'position', extentFromRight: 0.30, closeButton: true,
    badge: position.net > 0 ? 'LONG' : 'SHORT', qty: Math.abs(position.net), leftLabel: posLabel(),
  }, 0);
}

async function pollBook() {
  if (!trade || !sym) return;
  try {
    const orders = await trade.getOrders(); // caches modify context
    const seen = new Set();
    for (const o of orders) {
      if (o.status !== 'working' || o.symbol !== sym.symbol) continue;
      seen.add(o.id);
      const px = o.triggerPrice ?? o.price;
      const rec = orderLines.get(o.id);
      if (rec) { rec.order = o; rec.line.setPrice(px); }
      else orderLines.set(o.id, { line: makeOrderLine(o), order: o });
    }
    for (const [id, rec] of orderLines) if (!seen.has(id)) { chart.removePrimitive(rec.line); orderLines.delete(id); }
  } catch (_) { /* transient */ }
  try {
    const j = await api('positionbook');
    renderPosition((j.data || []).find((p) => p.symbol === sym.symbol && p.exchange === sym.exchange && Number(p.quantity) !== 0));
  } catch (_) { /* transient */ }
}

/* real order quantity from the qty input (lots × lotsize for derivatives) */
function orderQty() {
  const n = Math.max(1, Math.floor(Number(el('qty').value) || 1));
  return sym.lots ? n * sym.lotsize : n;
}

/* label for the inline panel's quantity chip (lots for FnO, else qty) */
function qtyChip() {
  if (!sym) return '';
  const n = Math.max(1, Math.floor(Number(el('qty').value) || 1));
  return sym.lots ? `${n}L` : String(n);
}

/* inline Buy/Sell panel → market order */
const placeMarket = (side) => placeFromMenu(side, 'MARKET');

function marketPrice() {
  return lastLtp != null ? lastLtp : (rawBars.length ? rawBars[rawBars.length - 1].close : null);
}

async function placeFromMenu(side, type) {
  if (!sym || !trade) { toast('search a symbol first'); return; }
  if (sym.quoteOnly) { toast(`${sym.exchange} is quote-only — trading is not supported`, 'err'); return; }
  const qty = orderQty();
  if (sym.freezeQty > 1 && qty > sym.freezeQty) {
    toast(`qty ${qty} exceeds the freeze limit ${sym.freezeQty} — reduce lots`, 'err');
    return;
  }
  const px = type === 'MARKET' ? 0 : snapTick(ctxPrice);
  const m = marketPrice();
  if (m != null && (type === 'SL' || type === 'SL-M') && (side === 'BUY' ? px <= m : px >= m)) {
    toast(`${side} stop must be ${side === 'BUY' ? 'above' : 'below'} LTP ${fmt(m)}`, 'err');
    return;
  }
  const product = el('product').value;
  const summary = `${side} ${type} ${sym.lots ? `${qty / sym.lotsize}L (${qty})` : qty} ${sym.symbol}` +
    (type === 'MARKET' ? '' : ` @ ${fmt(px)}`) + ` · ${product}`;
  status(`placing ${summary} …`);
  try {
    const r = await trade.place({
      symbol: sym.symbol, exchange: sym.exchange, side, type, qty, product,
      price: type === 'MARKET' ? undefined : px,
      triggerPrice: type === 'SL' || type === 'SL-M' ? px : undefined,
      mode: isLiveMode() ? 'live' : 'analyzer',
    });
    toast(`placed ${summary} (id ${r.orderId})`, 'ok');
    status(`placed ${summary}`);
    pollBook();
  } catch (e) { toast(cleanError(e), 'err'); status('order rejected'); }
}

async function exitPosition() {
  if (!trade || !position || !sym) return;
  const qty = Math.abs(position.net), side = position.net > 0 ? 'SELL' : 'BUY';
  const summary = `close ${position.net > 0 ? 'LONG' : 'SHORT'} ${qty} ${sym.symbol} @ market`;
  status(summary + ' …');
  try {
    await api('placesmartorder', {
      strategy: STRATEGY, exchange: sym.exchange, symbol: sym.symbol,
      action: side, product: position.product || el('product').value, pricetype: 'MARKET',
      quantity: String(qty), position_size: '0', price: '0', trigger_price: '0', disclosed_quantity: '0',
    });
    toast('position closed', 'ok');
    pollBook();
  } catch (e) { toast(cleanError(e), 'err'); status(''); }
}

/* ── chart build + interaction wiring ───────────────────────────────────── */
/* Resolve a CSS custom property (oklch token) to a plain rgb() string. The
 * computed style can stay in oklch (which the canvas engine's color parser
 * doesn't read — pill text contrast breaks), so rasterize via a 1×1 canvas. */
const cssColor = (() => {
  const probe = document.createElement('span');
  probe.style.display = 'none';
  document.body.appendChild(probe);
  const cnv = document.createElement('canvas');
  cnv.width = cnv.height = 1;
  const g = cnv.getContext('2d', { willReadFrequently: true });
  return (varName) => {
    probe.style.color = `var(${varName})`;
    g.clearRect(0, 0, 1, 1);
    g.fillStyle = '#000';
    g.fillStyle = getComputedStyle(probe).color; // invalid values keep #000
    g.fillRect(0, 0, 1, 1);
    const d = g.getImageData(0, 0, 1, 1).data;
    return `rgb(${d[0]},${d[1]},${d[2]})`;
  };
})();

function themeObj() {
  const base = isLightTheme() ? lightTheme : darkTheme;
  return {
    ...base,
    background: cssColor('--bg'),
    grid: cssColor('--card'),
    axisText: cssColor('--mut'),
    axisLine: cssColor('--bd'),
    crosshair: cssColor('--faint'),
  };
}

function buildChart() {
  if (chart) chart.destroy();
  el('chart').innerHTML = '';
  chart = createChart(el('chart'), { priceAxisWidth: 78, theme: themeObj() });
  const cfg = chartType();
  price = chart.addSeries(cfg.series, {
    style: cfg.style ? cfg.style() : {},
    priceFormat: sym && sym.tick ? { type: 'price', minMove: sym.tick } : undefined,
  });
  volume = chart.addSeries('histogram', { paneIndex: 1, style: { color: isLightTheme() ? '#d4d4d8' : '#33415e' } });
  setPriceData();
  // Comfortable default zoom: ~last 120 candles right-aligned, instead of
  // squeezing the full history into the viewport. Short series still fit whole.
  if (shownCount > 140) {
    chart.timeScale.setBarSpacing(9);
    chart.timeScale.setRightOffset(5);
  } else if (chart.timeScale.barSpacing > 14) {
    chart.timeScale.setBarSpacing(14); // don't over-stretch a short series
  }
  const lp = lastLtp != null ? lastLtp : (rawBars.length ? rawBars[rawBars.length - 1].close : null);
  ltpLine = lp != null ? chart.addPriceLine({ price: lp, color: '#e0b020', lineWidth: 1, dashed: true, id: 'ltp' }, 0) : null;

  // TradingView-style mini brand mark, bottom-left just above the time axis
  // (bottom pane), same convention as the openalgo-charts website examples:
  // the mark-only svg (transparent background), tinted light on dark themes.
  chart.addPrimitive(new LogoWatermark({
    src: '/trading/static/openalgo-mark.svg',
    position: 'bottom-left', height: 34, margin: 10, opacity: 0.85,
    tint: isLightTheme() ? undefined : '#e4e8f4', // black mark on light, light mark on dark
  }), 1);

  // inline TradingView-style SELL · qty · BUY panel, docked top-left below the
  // OHLC legend (which is an HTML overlay at the top-left corner)
  if (!sym.quoteOnly) {
    tradeBtns = new BuySellButtons({ id: 'trade', position: 'top-left', margin: { x: 14, y: 52 }, qty: qtyChip() });
    if (lp != null) tradeBtns.setMark(lp);
    chart.addPrimitive(tradeBtns, 0);
  } else tradeBtns = null;

  chart.subscribeCrosshairMove((e) => setLegend(e.bar || (rawBars.length ? rawBars[rawBars.length - 1] : null)));

  // drag-to-modify with a drag ghost; commit on release (tick-snapped)
  chart.subscribeDrag(
    (id, p) => {
      if (!id.startsWith('order:') || id.endsWith('::close')) return;
      const rec = orderLines.get(id.slice(6)); if (!rec) return;
      if (rec.dragFrom == null) { rec.dragFrom = rec.line.price; rec.line.setDragGhost(rec.dragFrom); }
      rec.line.setPrice(snapTick(p));
    },
    (id, p) => {
      if (!id.startsWith('order:') || id.endsWith('::close')) return;
      const oid = id.slice(6), rec = orderLines.get(oid); if (!rec) return;
      rec.line.setDragGhost(null); rec.dragFrom = null;
      const px = snapTick(p), stop = rec.order.type === 'SL' || rec.order.type === 'SL-M';
      status(`modifying ${rec.order.side} ${rec.order.type} to ${fmt(px)} …`);
      trade.modify(oid, stop ? { triggerPrice: px } : { price: px })
        .then(() => { status(`modified ${rec.order.side} ${rec.order.type} to ${fmt(px)}`); pollBook(); })
        .catch((e) => { toast(cleanError(e), 'err'); status(''); pollBook(); });
    },
  );
  chart.subscribeClick((id) => {
    if (id === 'trade:buy') { placeMarket('BUY'); return; }
    if (id === 'trade:sell') { placeMarket('SELL'); return; }
    if (id === 'trade:qty') { el('qty').focus(); el('qty').select(); return; }
    if (id === 'position::close') { exitPosition(); return; }
    if (id.startsWith('order:') && id.endsWith('::close')) {
      const oid = id.slice(6, -7);
      trade.cancel(oid).then(() => { toast(`order ${oid} cancelled`, 'ok'); pollBook(); })
        .catch((e) => toast(cleanError(e), 'err'));
    }
  });

  orderLines.clear(); posLine = null; position = null; // primitives died with the old chart
  if (trade && sym) pollBook();
  setLegend(rawBars.length ? rawBars[rawBars.length - 1] : null);
  window.__chart = chart;
}

/* ── WS-down fallback: poll quotes so LTP + the forming candle stay live ── */
let ltpPollTimer = null;
function startLtpFallback() {
  if (ltpPollTimer) return;
  ltpPollTimer = setInterval(async () => {
    if (!sym) return;
    try {
      const j = await api('quotes', { symbol: sym.symbol, exchange: sym.exchange });
      const q = j.data || {};
      if (typeof q.ltp === 'number' && q.ltp > 0) onTick({ symbol: sym.symbol, ltp: q.ltp, timeSec: nowSec() });
      setWs('fallback');
    } catch (_) { /* next cycle */ }
  }, 4000);
}
function stopLtpFallback() {
  if (ltpPollTimer) { clearInterval(ltpPollTimer); ltpPollTimer = null; }
}

/* single tick path shared by WS pushes and the REST fallback */
function onTick(e) {
  if (!sym || (e.symbol && e.symbol !== sym.symbol)) return;
  tickN += 1;
  el('ltp').textContent = `LTP ${fmt(e.ltp)}`;
  lastLtp = e.ltp;
  if (ltpLine) ltpLine.setPrice(e.ltp);
  if (position && posLine) posLine.setLeftLabel(posLabel());
  if (tradeBtns) tradeBtns.setMark(e.ltp);
  if (builder) {
    const u = builder.onTick({ time: e.timeSec || nowSec(), price: e.ltp, ltq: e.ltq });
    if (u) {
      liveBucket = u.bar.time;
      if (u.isNew) rawBars.push(u.bar); else rawBars[rawBars.length - 1] = u.bar;
      setPriceData();
    }
  }
  setLegend(rawBars.length ? rawBars[rawBars.length - 1] : null);
}

/* ── live data: WS ticks → candles; order stream → lines ────────────────── */
function connectLive() {
  const interval = el('interval').value;
  const sec = intervalSeconds(interval);
  builder = sec ? new CandleBuilder({ intervalSec: sec, volumeMode: 'ltq-sum' }) : null;
  tickN = 0;
  if (offLtp) { offLtp(); offLtp = null; }
  offLtp = ws.onLtp((e) => {
    setWs('live');
    stopLtpFallback(); // push stream is alive — REST polling not needed
    onTick(e);
  });
  ws.subscribe('LTP', sym.symbol, sym.exchange);
}

/* periodic history reconcile: snap completed bars to broker OHLC/volume */
function scheduleReconcile() {
  clearTimeout(reconcileTimer);
  reconcileTimer = setTimeout(async () => {
    try {
      if (sym && rest) {
        const interval = el('interval').value;
        const to = nowSec();
        const fresh = await rest.getBars({
          symbol: sym.symbol, exchange: sym.exchange, interval,
          from: to - Math.min(3, lookbackDays(interval)) * 86400, to,
        });
        const byTime = new Map(fresh.map((b) => [b.time, b]));
        let changed = false;
        for (let i = 0; i < rawBars.length; i++) {
          const f = byTime.get(rawBars[i].time);
          if (f && (liveBucket == null || f.time < liveBucket)) { rawBars[i] = f; changed = true; }
        }
        if (changed) setPriceData();
      }
    } catch (_) { /* next cycle retries */ }
    scheduleReconcile();
  }, 25000 + Math.random() * 10000);
}

/* ── symbol selection ───────────────────────────────────────────────────── */
function setProductOptions() {
  const p = el('product');
  p.innerHTML = '';
  const opts = sym.lots ? ['MIS', 'NRML'] : ['MIS', 'CNC'];
  for (const o of opts) p.append(new Option(o, o));
  p.disabled = !!sym.quoteOnly;
}

function setQtyUi() {
  el('qty').value = '1';
  el('qtylbl').firstChild.textContent = sym.lots ? 'Lots ' : 'Qty ';
  updateLotInfo();
}

function updateLotInfo() {
  if (!sym) { el('lotinfo').textContent = ''; return; }
  if (sym.lots) {
    const lots = Math.max(1, Math.floor(Number(el('qty').value) || 1));
    let txt = `${lots} × ${sym.lotsize} = ${lots * sym.lotsize} qty`;
    if (sym.freezeQty > 1 && lots * sym.lotsize > sym.freezeQty) txt += ` ⚠ freeze ${sym.freezeQty}`;
    el('lotinfo').textContent = txt;
  } else el('lotinfo').textContent = sym.quoteOnly ? 'quote-only (no trading)' : '';
}

async function loadSymbol(pick, opts = {}) {
  // swap the live stream: drop the previous symbol's subscription
  if (ws && sym && (sym.symbol !== pick.symbol || sym.exchange !== pick.exchange)) {
    try { ws.unsubscribe('LTP', sym.symbol, sym.exchange); } catch (_) { /* not subscribed */ }
  }
  // authoritative metadata (lotsize / tick_size / freeze_qty)
  status(`loading ${pick.symbol} …`);
  let info = pick;
  try { info = { ...pick, ...(await api('symbol', { symbol: pick.symbol, exchange: pick.exchange })).data }; }
  catch (_) { /* search row already carries the essentials */ }
  sym = {
    symbol: info.symbol, exchange: info.exchange, name: info.name || '',
    lotsize: Number(info.lotsize) || 1,
    tick: Number(info.tick_size) || 0.05,
    freezeQty: Number(info.freeze_qty) || 1,
    instrumenttype: info.instrumenttype || '',
    quoteOnly: QUOTE_ONLY.has(info.exchange),
  };
  sym.lots = DERIVATIVE_EXCHANGES.has(sym.exchange) && sym.lotsize > 1;
  localStorage.setItem('oa-trading-symbol', JSON.stringify({ symbol: sym.symbol, exchange: sym.exchange }));
  el('symsearch').value = sym.symbol;
  setProductOptions();
  setQtyUi();

  // history
  const interval = el('interval').value;
  const to = nowSec();
  lastLtp = null; prevClose = null; liveBucket = null;
  try {
    rawBars = await rest.getBars({ symbol: sym.symbol, exchange: sym.exchange, interval, from: to - lookbackDays(interval) * 86400, to });
  } catch (e) {
    rawBars = [];
    if (!opts.silent) { toast(`history error: ${cleanError(e)}`, 'err'); status(''); }
    return false; // caller may fall back (e.g. to the default symbol)
  }
  if (!rawBars.length) {
    if (!opts.silent) toast(`no history for ${sym.symbol} ${sym.exchange} ${interval}`, 'err');
    return false;
  }
  prevClose = rawBars.length > 1 ? rawBars[rawBars.length - 2].close : rawBars[rawBars.length - 1].open;
  lastLtp = rawBars[rawBars.length - 1].close;
  buildChart();
  status('');
  el('ltp').textContent = `LTP ${fmt(lastLtp)}`;

  // live subscription (swap the previous symbol's stream)
  connectLive();
  scheduleReconcile();
  pollBook();
  return true;
}

/* ── symbol search dropdown ─────────────────────────────────────────────── */
let searchTimer = null, searchRows = [], searchSel = -1;
function renderSearch(rows) {
  searchRows = rows; searchSel = -1;
  const pop = el('searchpop');
  if (!rows.length) { pop.hidden = true; pop.innerHTML = ''; return; }
  pop.innerHTML = rows.map((r, i) =>
    `<div class="s-row" data-i="${i}">
       <span class="s-sym">${esc(r.symbol)}</span>
       <span class="s-name">${esc(r.name || '')}</span>
       <span class="s-lot">${Number(r.lotsize) > 1 ? 'lot ' + esc(r.lotsize) : ''}</span>
       <span class="s-badge">${esc(r.exchange)}</span>
     </div>`).join('');
  pop.hidden = false;
}
function highlightSearch(delta) {
  if (!searchRows.length) return;
  searchSel = (searchSel + delta + searchRows.length) % searchRows.length;
  [...el('searchpop').children].forEach((n, i) => n.classList.toggle('sel', i === searchSel));
  el('searchpop').children[searchSel]?.scrollIntoView({ block: 'nearest' });
}
async function doSearch(q) {
  const exchange = el('exchange').value || undefined;
  try {
    const j = await api('search', { query: q, ...(exchange ? { exchange } : {}) });
    renderSearch((j.data || []).slice(0, 30));
  } catch (_) { renderSearch([]); }
}

el('symsearch').addEventListener('input', () => {
  const q = el('symsearch').value.trim();
  clearTimeout(searchTimer);
  if (q.length < 2) { renderSearch([]); return; }
  searchTimer = setTimeout(() => doSearch(q), 220);
});
el('symsearch').addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown') { highlightSearch(1); e.preventDefault(); }
  else if (e.key === 'ArrowUp') { highlightSearch(-1); e.preventDefault(); }
  else if (e.key === 'Enter') {
    const pick = searchRows[searchSel >= 0 ? searchSel : 0];
    if (pick) { renderSearch([]); loadSymbol(pick); }
  } else if (e.key === 'Escape') renderSearch([]);
});
el('searchpop').addEventListener('mousedown', (e) => {
  const row = e.target.closest('.s-row'); if (!row) return;
  const pick = searchRows[Number(row.dataset.i)];
  renderSearch([]);
  if (pick) loadSymbol(pick);
});
document.addEventListener('click', (e) => { if (!e.target.closest('.search')) renderSearch([]); });

/* ── right-click order menu ─────────────────────────────────────────────── */
const ctxMenu = el('ctxmenu');
el('chart').addEventListener('contextmenu', (e) => {
  if (!chart || !sym) return;
  if (sym.quoteOnly) return; // let the native menu (and its Save image) through
  e.preventDefault();
  const p = chart.coordinateToPrice(e.clientY - el('chart').getBoundingClientRect().top, 0);
  if (p == null) return;
  ctxPrice = snapTick(p);
  const m = marketPrice();
  const lotTxt = sym.lots ? `${Math.max(1, Math.floor(Number(el('qty').value) || 1))}L` : orderQty();
  ctxMenu.querySelectorAll('button[data-type]').forEach((b) => {
    const side = b.getAttribute('data-side'), v = side === 'BUY' ? 'Buy' : 'Sell', t = b.getAttribute('data-type');
    const label = t === 'MARKET' ? `${v} ${lotTxt} Market` : t === 'LIMIT' ? `${v} ${lotTxt} Limit @ ${fmt(ctxPrice)}` : `${v} ${lotTxt} Stop @ ${fmt(ctxPrice)}`;
    b.querySelector('span').textContent = label;
    let ok = true;
    if (m != null) {
      if (t === 'SL') ok = side === 'BUY' ? ctxPrice > m : ctxPrice < m;
      else if (t === 'LIMIT') ok = side === 'BUY' ? ctxPrice < m : ctxPrice > m;
    }
    b.disabled = !ok;
  });
  ctxMenu.style.left = Math.min(e.clientX, window.innerWidth - 250) + 'px';
  ctxMenu.style.top = Math.min(e.clientY, window.innerHeight - 320) + 'px';
  ctxMenu.hidden = false;
});
window.addEventListener('click', () => { ctxMenu.hidden = true; });
ctxMenu.addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b || b.disabled) return;
  e.stopPropagation(); ctxMenu.hidden = true;
  placeFromMenu(b.getAttribute('data-side'), b.getAttribute('data-type'));
});

/* ── toolbar wiring ─────────────────────────────────────────────────────── */
el('fit').addEventListener('click', () => chart && chart.resetScale());
el('snap').addEventListener('click', () => {
  if (!chart || !sym) return;
  const stamp = new Date().toISOString().slice(0, 16).replace(/[T:]/g, '-');
  chart.downloadScreenshot(`${sym.symbol}-${el('interval').value}-${stamp}.png`);
});
el('themebtn').addEventListener('click', () => {
  if (analyzerMode !== false) return; // locked in sandbox, like the app
  // flip the app-wide theme (openalgo-theme) so /dashboard and /trading stay in sync
  let stored;
  try { stored = JSON.parse(localStorage.getItem('openalgo-theme') || '{}'); } catch (_) { stored = {}; }
  stored.state = { ...(stored.state || {}), mode: appThemeMode() === 'light' ? 'dark' : 'light' };
  stored.version = stored.version ?? 0;
  localStorage.setItem('openalgo-theme', JSON.stringify(stored));
  applyTheme();
});
el('ctype').addEventListener('change', () => {
  localStorage.setItem('oa-trading-ctype', el('ctype').value);
  if (rawBars.length) buildChart();
});
el('interval').addEventListener('change', () => {
  localStorage.setItem('oa-trading-interval', el('interval').value);
  if (sym) loadSymbol(sym);
});
el('exchange').addEventListener('change', () => {
  const q = el('symsearch').value.trim();
  if (q.length >= 2) doSearch(q);
});
el('qty').addEventListener('input', () => { updateLotInfo(); if (tradeBtns) tradeBtns.setQty(qtyChip()); });

/* ── bootstrap ──────────────────────────────────────────────────────────── */
function populateIntervals(data) {
  const sel = el('interval');
  sel.innerHTML = '';
  const groups = [['seconds', data.seconds], ['minutes', data.minutes], ['hours', data.hours],
    ['days', data.days], ['weeks', data.weeks], ['months', data.months]];
  for (const [label, arr] of groups) {
    if (!arr || !arr.length) continue;
    const og = document.createElement('optgroup');
    og.label = label;
    for (const iv of arr) og.append(new Option(iv, iv));
    sel.append(og);
  }
  // restore the saved interval if the broker still supports it, else default to
  // 5m (then first minute interval, then whatever exists)
  const all = [...sel.options].map((o) => o.value);
  const saved = localStorage.getItem('oa-trading-interval');
  sel.value = (saved && all.includes(saved)) ? saved
    : all.includes('5m') ? '5m'
    : (data.minutes && data.minutes[0]) || all[0] || 'D';
}

async function bootstrap() {
  applyTheme(); // analyzer look until the API reports the actual mode
  // restore the saved chart type (defaults to candles for a fresh browser)
  const savedType = localStorage.getItem('oa-trading-ctype');
  if (savedType && [...el('ctype').options].some((o) => o.value === savedType)) el('ctype').value = savedType;
  try {
    const [keyRes, cfgRes] = await Promise.all([
      fetch('/api/websocket/apikey').then((r) => r.json()),
      fetch('/api/websocket/config').then((r) => r.json()),
    ]);
    if (keyRes.status !== 'success') {
      status('no API key found — generate one at /apikey, then reload');
      toast('No API key — generate one at /apikey first', 'err');
      return;
    }
    apiKey = keyRes.api_key;
    wsUrl = cfgRes.websocket_url || 'ws://127.0.0.1:8765';
  } catch (e) { status('bootstrap failed — are you logged in?'); return; }

  rest = new OpenAlgoDataFeed({ baseUrl: '', apiKey });
  trade = new OpenAlgoTradeFeed({ baseUrl: '', apiKey, strategy: STRATEGY });

  // header avatar: logged-in user's initial (same as the app header)
  fetch('/trading/api/me').then((r) => r.json())
    .then((j) => { if (j.user) el('avatar').textContent = String(j.user).slice(0, 1); })
    .catch(() => {});

  // broker-supported intervals + current analyzer/live mode
  try { populateIntervals((await api('intervals')).data || {}); }
  catch (_) { populateIntervals({ minutes: ['1m', '5m', '15m'], hours: ['1h'], days: ['D'] }); }
  try { const a = await api('analyzer'); setMode(a.data?.mode || (a.data?.analyze_mode ? 'analyze' : 'live')); }
  catch (_) { /* mode chip updates from later responses */ }

  // one WebSocket for ticks + the account-level order stream. If the socket
  // drops, it auto-reconnects with backoff and replays every subscription;
  // meanwhile a REST quotes poll keeps LTP + the forming candle alive, and the
  // 8s book poll below keeps order/position lines truthful either way.
  ws = new OpenAlgoWsFeed({ url: wsUrl, apiKey });
  ws.onState((s) => {
    setWs(s);
    if (s === 'closed' || s === 'error' || s === 'reconnecting') startLtpFallback();
  });
  ws.onControl((mmsg) => {
    if (mmsg.type === 'auth' && mmsg.status !== 'success') setWs('auth failed');
  });
  ws.onOrderUpdate((e) => {
    if (e.mode) setMode(e.mode === 'analyze' ? 'analyze' : e.mode);
    if (!sym || e.symbol !== sym.symbol || !chart) return;
    const working = e.status === 'open' || e.status === 'trigger pending' || e.status === 'pending';
    const rec = orderLines.get(e.orderId);
    const o = { id: e.orderId, side: e.action, type: e.pricetype, qty: e.quantity, filledQty: e.filledQuantity,
      price: e.price, triggerPrice: e.triggerPrice, status: working ? 'working' : e.status };
    if (working) {
      if (rec) { rec.order = o; rec.line.setPrice(e.triggerPrice ?? e.price); }
      else orderLines.set(e.orderId, { line: makeOrderLine(o), order: o });
    } else if (rec) { chart.removePrimitive(rec.line); orderLines.delete(e.orderId); }
    status(`order ${e.orderId} ${e.status}` +
      (e.status === 'complete' ? ` @ ${fmt(e.averagePrice || e.price)}` : '') +
      (e.rejectionReason ? ' — ' + e.rejectionReason : ''));
    if (e.status === 'rejected') toast(`rejected: ${e.rejectionReason || 'see order book'}`, 'err');
    if (e.status === 'complete') toast(`filled: ${e.action} ${e.quantity} @ ${fmt(e.averagePrice || e.price)}`, 'ok');
    if (!working) pollBook(); // fills/cancels move the position book too
  });
  ws.connect();
  ws.subscribeOrders();

  clearInterval(bookTimer);
  bookTimer = setInterval(pollBook, 8000); // slow reconciliation; order events stream via WS

  // restore the last symbol; if it's gone (delisted) or has no data (expired
  // contract), fall back to the default (BHEL / NSE).
  let loaded = false;
  try {
    const saved = JSON.parse(localStorage.getItem('oa-trading-symbol') || 'null');
    if (saved && saved.symbol) {
      const j = await api('search', { query: saved.symbol, exchange: saved.exchange });
      const row = (j.data || []).find((r) => r.symbol === saved.symbol && r.exchange === saved.exchange);
      if (row) loaded = await loadSymbol(row, { silent: true }); // silent: we may fall back
    }
  } catch (_) { /* fall through to the default */ }
  if (!loaded) {
    try {
      const j = await api('search', { query: 'BHEL', exchange: 'NSE' });
      const bhel = (j.data || []).find((r) => r.symbol === 'BHEL' && r.exchange === 'NSE');
      if (bhel) await loadSymbol(bhel);
    } catch (_) { status('search a symbol to begin'); }
  }
}

bootstrap();

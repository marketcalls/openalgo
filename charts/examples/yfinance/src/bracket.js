import * as engine from '/dist/openalgo-charts.mjs';
import { el, fmt, pnlText } from './ui.js';
import { snapPrice } from './ticks.js';
import { saveState, tradeColors, TRADE_EXTENT, removeAllOrders, clearPosition, executionAllowed } from './orders.js';

let app;

// ── Bracket (entry / target / stop) ──────────────────────────
const chartTop = () => el('chart').getBoundingClientRect().top;

export function makeBracket(side) {
  if (!executionAllowed()) return;
  if (!app.currentBars.length) return;
  const entry = snapPrice(app.ticks, app.currentBars[app.currentBars.length - 1].close);
  const qty = Math.max(1, Number(el('qty').value) || 1);
  app.bracket = {
    side, entry, qty,
    target: snapPrice(app.ticks, side === 'BUY' ? entry * 1.012 : entry * 0.988),
    stop: snapPrice(app.ticks, side === 'BUY' ? entry * 0.99 : entry * 1.01),
  };
  attachBracketLines();
  el('bracket').hidden = false;
  el('bk-entry').querySelector('[data-act="place"]').className = side === 'BUY' ? 'bk-buy' : 'bk-sell';
  updateBracket();
  saveState();
}

// (Re)create the three dashed price lines on the current chart. They auto-sync
// with pan/zoom and are draggable through the chart's subscribeDrag.
export function attachBracketLines() {
  if (!app.bracket) return;
  const tc = tradeColors();
  const pl = (price, color, id) => app.chart.addPriceLine(
    { price, color, lineWidth: 1, dashed: true, id, cursor: 'ns-resize', extentFromRight: TRADE_EXTENT });
  // The entry leg is a resting order like any other, so it takes the order
  // colour; the two exits take the take-profit and stop-loss colours.
  app.bLines = {
    entry: pl(app.bracket.entry, tc.order, 'bk-entry'),
    tp: pl(app.bracket.target, tc.tp, 'bk-tp'),
    sl: pl(app.bracket.stop, tc.sl, 'bk-sl'),
  };
}

// Move one leg (or the whole bracket via the entry) and keep TP/SL on the
// correct side of entry, then refresh lines, labels and pill positions.
export function setBracketPrice(which, raw) {
  if (!executionAllowed()) return;
  if (!app.bracket) return;
  const ticks = app.ticks;
  const p = snapPrice(ticks, raw);
  const buy = app.bracket.side === 'BUY';
  // One tick either side of the entry. On a scheduled instrument that is the
  // tick of the band each side falls in, so the bound changes at a boundary.
  const above = () => (ticks ? ticks.step(app.bracket.entry, 1) : app.bracket.entry + 0.01);
  const below = () => (ticks ? ticks.step(app.bracket.entry, -1) : app.bracket.entry - 0.01);
  if (which === 'entry') {
    const d = p - app.bracket.entry;
    app.bracket.entry = p; app.bracket.target = snapPrice(ticks, app.bracket.target + d); app.bracket.stop = snapPrice(ticks, app.bracket.stop + d);
    // Each leg snaps in its own band, which can close a gap the shift kept.
    if (ticks) {
      app.bracket.target = buy ? Math.max(app.bracket.target, above()) : Math.min(app.bracket.target, below());
      app.bracket.stop = buy ? Math.min(app.bracket.stop, below()) : Math.max(app.bracket.stop, above());
    }
  } else if (which === 'tp') {
    app.bracket.target = buy ? Math.max(p, above()) : Math.min(p, below());
  } else {
    app.bracket.stop = buy ? Math.min(p, below()) : Math.max(p, above());
  }
  updateBracket();
  saveState();
}

export function updateBracket() {
  if (!app.bracket || !app.bLines) return;
  app.bLines.entry.setPrice(app.bracket.entry); app.bLines.tp.setPrice(app.bracket.target); app.bLines.sl.setPrice(app.bracket.stop);
  const sign = app.bracket.side === 'BUY' ? 1 : -1;
  const tpPts = Math.abs(app.bracket.target - app.bracket.entry);
  const slPts = Math.abs(app.bracket.entry - app.bracket.stop);
  const tpPnl = sign * (app.bracket.target - app.bracket.entry) * app.bracket.qty;
  const slPnl = sign * (app.bracket.stop - app.bracket.entry) * app.bracket.qty;
  const rr = slPts > 0 ? tpPts / slPts : 0;
  const set = (id, pts, pnl) => {
    const n = el(id);
    n.querySelector('.pts').textContent = fmt(pts);
    n.querySelector('.pct').textContent = (pts / app.bracket.entry * 100).toFixed(2) + '%';
    n.querySelector('.pnl').textContent = pnlText(pnl);
  };
  set('bk-tp', tpPts, tpPnl);
  set('bk-sl', slPts, slPnl);
  const e = el('bk-entry');
  e.querySelector('.q').textContent = app.bracket.qty;
  e.querySelector('.rr').textContent = rr.toFixed(2);
  e.querySelector('[data-act="place"]').textContent = '1-Click ' + (app.bracket.side === 'BUY' ? 'Buy' : 'Sell');
  positionPills();
}

// Glue each pill to its price and to the LEFT end of the 30% line (viewport
// coords), clamped to stay on the chart and off the price axis.
export function positionPills() {
  if (!app.bracket || el('bracket').hidden) return;
  const rect = el('chart').getBoundingClientRect();
  const plotW = Math.max(0, rect.width - 72); // priceAxisWidth
  const lineLeftX = rect.left + plotW * (1 - TRADE_EXTENT);
  const at = { 'bk-tp': app.bracket.target, 'bk-entry': app.bracket.entry, 'bk-sl': app.bracket.stop };
  for (const id in at) {
    const y = app.chart ? app.chart.priceToCoordinate(at[id]) : null;
    const node = el(id);
    if (y == null) { node.style.display = 'none'; continue; }
    node.style.display = '';
    node.style.top = (rect.top + y) + 'px';
    node.style.left = Math.max(rect.left + 8, Math.min(lineLeftX, rect.right - node.offsetWidth - 84)) + 'px';
  }
}
export function removeBracket() {
  if (app.bLines && app.chart) for (const k in app.bLines) app.chart.removePrimitive(app.bLines[k]);
  app.bracket = null; app.bLines = null; el('bracket').hidden = true;
}

// Drag a pill vertically to modify its leg (entry pill moves the whole bracket).
function dragify(id, which) {
  const node = el(id);
  node.addEventListener('pointerdown', (e) => {
    if (e.target.closest('button')) return; // let buttons handle their own clicks
    node.setPointerCapture(e.pointerId); node._drag = true; e.preventDefault();
  });
  node.addEventListener('pointermove', (e) => {
    if (!node._drag) return;
    const p = app.chart && app.chart.coordinateToPrice(e.clientY - chartTop());
    if (p != null) setBracketPrice(which, p);
  });
  const end = (e) => { node._drag = false; try { node.releasePointerCapture(e.pointerId); } catch (_) {} };
  node.addEventListener('pointerup', end);
  node.addEventListener('pointercancel', end);
}

export function initBracket(a) {
  app = a;
  // Keep pills locked to price across pan / zoom / rescale / kinetic, and give
  // the chart one repaint a second while we are here. Three readings on this
  // chart are times of day rather than prices - the corner clock, the countdown
  // row in the last-price tag, and the session state on the status line - and a
  // yfinance chart has no incoming tick to repaint them for. A host on a live
  // feed gets this for free and needs none of it.
  const LIGHT = engine.InvalidationLevel ? engine.InvalidationLevel.Light : undefined;
  let lastClockTick = 0;
  (function frame(t) {
    positionPills();
    if (app.chart && LIGHT !== undefined && typeof app.chart.invalidate === 'function' && t - lastClockTick >= 1000) {
      lastClockTick = t;
      app.chart.invalidate((m) => m.invalidateGlobal(LIGHT));
    }
    requestAnimationFrame(frame);
  })(0);

  dragify('bk-tp', 'tp'); dragify('bk-entry', 'entry'); dragify('bk-sl', 'sl');

  el('bracket').addEventListener('click', (e) => {
    const act = e.target.getAttribute && e.target.getAttribute('data-act');
    if (!act || !app.bracket) return;
    if (act === 'cancel') { removeBracket(); saveState(); el('status').textContent = 'bracket cancelled'; }
    else if (act === 'place') {
      if (!executionAllowed()) return;
      el('status').textContent = `placed ${app.bracket.side} OCO bracket - ${app.bracket.qty} entry ${fmt(app.bracket.entry)} · TP ${fmt(app.bracket.target)} · SL ${fmt(app.bracket.stop)} (target/stop are OCO)`;
    } else if (act === 'modify') {
      // It edits nothing: it writes the bracket out, so it is named that way.
      const rr = (Math.abs(app.bracket.target - app.bracket.entry) / Math.max(1e-9, Math.abs(app.bracket.entry - app.bracket.stop))).toFixed(2);
      el('status').textContent = `bracket - entry ${fmt(app.bracket.entry)} · TP ${fmt(app.bracket.target)} · SL ${fmt(app.bracket.stop)} · R:R ${rr}`;
    }
  });

  el('buy').addEventListener('click', () => makeBracket('BUY'));
  el('sell').addEventListener('click', () => makeBracket('SELL'));
  el('cancel').addEventListener('click', () => { removeBracket(); removeAllOrders(); clearPosition(); saveState(); el('status').textContent = 'cancelled / flat'; });
  el('qty').addEventListener('change', () => { if (app.bracket) { app.bracket.qty = Math.max(1, Number(el('qty').value) || 1); updateBracket(); saveState(); } });
}

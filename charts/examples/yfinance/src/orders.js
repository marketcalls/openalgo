import { el, fmt, round2, pnlText } from './ui.js';
import { snapPrice, tickNote } from './ticks.js';

let app;
export function initOrders(a) { app = a; }

export function executionAllowed() {
  if (!app.workspaceLoading && !app.replay && !app.replayPicking && !app.replayLoading && !app.loading && !app.loadFailed) return true;
  el('status').textContent = 'Order entry is unavailable during replay or while chart data is unavailable.';
  return false;
}

export const TRADE_EXTENT = 0.30; // order/bracket lines span only the rightmost 30% (broker-style)

/**
 * The trade palette the Trading tab of chart settings writes. The demo draws
 * its orders, bracket and position as its own price lines rather than
 * through `chart.trading`, so nothing would read those seven colours unless
 * this asked for them: they were declared, persisted, and consumed by
 * nobody, which is the same defect as an option no renderer reads.
 *
 * `tradingSettings()` answers whether or not the trade controller exists, so
 * reading it here does not create one.
 */
export const TRADE_FALLBACK = {
  long: '#2f6df6', short: '#ef5350', order: '#3b82f6',
  tp: '#26a69a', sl: '#ef5350', buy: '#26a69a', sell: '#ef5350',
};
export function tradeColors() {
  return app.chart && typeof app.chart.tradingSettings === 'function' ? app.chart.tradingSettings() : TRADE_FALLBACK;
}

// Persist trade state per symbol so orders/bracket/position survive a refresh.
export const STORE_KEY = (sym) => 'oa-charts-trade:' + sym;
export function saveState() {
  if (!app.req.symbol) return;
  try {
    localStorage.setItem(STORE_KEY(app.req.symbol), JSON.stringify({
      orders: app.orders.map((o) => ({ id: o.id, side: o.side, type: o.type, price: o.price, qty: o.qty, product: o.product })),
      nextOrderId: app.nextOrderId, bracket: app.bracket, position: app.position, fills: app.fills,
    }));
  } catch (_) {}
}
export function restoreState(sym) {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(STORE_KEY(sym)) || 'null'); } catch (_) {}
  app.orders = s && s.orders ? s.orders.map((o) => ({ ...o, line: null })) : [];
  app.nextOrderId = s && s.nextOrderId ? s.nextOrderId : 1;
  app.bracket = s ? s.bracket || null : null;
  app.position = s ? s.position || null : null;
  app.fills = s && s.fills ? s.fills : [];
}

// ── Resting orders (right-click) - each a draggable broker-style line ──
export function orderLine(o) {
  return app.chart.addPriceLine({
    price: o.price, color: tradeColors().order, lineWidth: 1, dashed: true,
    id: `order:${o.id}`, cursor: 'ns-resize', extentFromRight: TRADE_EXTENT,
    leftLabel: `${o.side} ${o.qty} ${o.type}`, closeButton: true, // click the box to cancel
  });
}
export function cancelOrder(id) { // id = "order:<n>"
  const o = app.orders.find((x) => `order:${x.id}` === id);
  if (!o) return;
  if (o.line && app.chart) app.chart.removePrimitive(o.line);
  app.orders = app.orders.filter((x) => x !== o);
  el('status').textContent = `cancelled ${o.side} ${o.type} @ ${fmt(o.price)}`;
  saveState();
}
export function placeOrder(side, type, price) {
  if (!executionAllowed()) return;
  const qty = Math.max(1, Number(el('qty').value) || 1);
  if (type === 'MARKET') { fillMarket(side, qty); return; } // executes into a position
  const o = { id: app.nextOrderId++, side, type, price: snapPrice(app.ticks, price), qty, product: el('product').value };
  o.line = app.chart ? orderLine(o) : null;
  app.orders.push(o);
  el('status').textContent = `${side} ${type} ${qty} ${app.req.symbol} @ ${fmt(o.price)} (${o.product})${tickNote(app.ticks, o.price)} - drag the line to modify`;
  saveState();
}
// A dragged order line (id = "order:<n>") takes the price the pointer is on,
// rounded the way the instrument quotes it, so crossing a band boundary
// changes the step the line moves in.
export function repriceOrder(id, price) {
  const o = app.orders.find((x) => `order:${x.id}` === id);
  if (!o || !o.line) return;
  o.price = snapPrice(app.ticks, price);
  o.line.setPrice(o.price);
  el('status').textContent = `${o.side} ${o.type} order -> ${fmt(o.price)}${tickNote(app.ticks, o.price)}`;
  saveState();
}
export function attachOrderLines() { for (const o of app.orders) o.line = orderLine(o); } // on chart rebuild
export function removeAllOrders() {
  if (app.chart) for (const o of app.orders) if (o.line) app.chart.removePrimitive(o.line);
  app.orders = [];
}

// Execute a market order at the last price -> update the net position, drop an
// arrow marker on the bar, and (re)draw the position line.
export function fillMarket(side, qty) {
  if (!executionAllowed()) return;
  if (!app.currentBars.length) return;
  const last = app.currentBars[app.currentBars.length - 1];
  const price = snapPrice(app.ticks, last.close);
  const signed = side === 'BUY' ? qty : -qty;
  if (!app.position || app.position.netQty === 0) {
    app.position = { netQty: signed, avgPrice: price };
  } else if (Math.sign(app.position.netQty) === Math.sign(signed)) {
    const net = app.position.netQty + signed; // adding -> volume-weighted average
    app.position.avgPrice = (app.position.avgPrice * app.position.netQty + price * signed) / net;
    app.position.netQty = net;
  } else {
    const net = app.position.netQty + signed; // reducing / flipping
    app.position = net === 0 ? null
      : Math.sign(net) === Math.sign(app.position.netQty) ? { netQty: net, avgPrice: app.position.avgPrice }
      : { netQty: net, avgPrice: price };
  }
  const tc = tradeColors();
  app.fills.push({
    time: last.time, position: side === 'BUY' ? 'belowBar' : 'aboveBar',
    shape: side === 'BUY' ? 'arrowUp' : 'arrowDown', size: 'small',
    color: side === 'BUY' ? tc.buy : tc.sell, text: `${side[0]} ${qty}`,
  });
  if (app.markersApi) app.markersApi.setMarkers(app.fills);
  updatePositionLine();
  const p = app.position;
  el('status').textContent = p
    ? `${side} MARKET ${qty} filled @ ${fmt(price)} -> ${p.netQty > 0 ? 'LONG' : 'SHORT'} ${Math.abs(p.netQty)} @ ${fmt(p.avgPrice)}`
    : `${side} MARKET ${qty} filled @ ${fmt(price)} -> flat`;
  saveState();
}
// P&L of the open position marked at `mp` (defaults to the latest close).
export function markPrice() { return app.currentBars.length ? app.currentBars[app.currentBars.length - 1].close : 0; }
export function positionLabel(mp) {
  const long = app.position.netQty > 0;
  const pnl = (mp - app.position.avgPrice) * app.position.netQty;
  return `${long ? 'LONG' : 'SHORT'} ${Math.abs(app.position.netQty)} @ ${fmt(app.position.avgPrice)}  ${pnlText(pnl)}`;
}
export function updatePositionLine() {
  if (app.posLine && app.chart) { app.chart.removePrimitive(app.posLine); app.posLine = null; }
  if (!app.position || app.position.netQty === 0 || !app.chart) return;
  const long = app.position.netQty > 0;
  const tc = tradeColors();
  app.posLine = app.chart.addPriceLine({
    price: round2(app.position.avgPrice), color: long ? tc.long : tc.short, lineWidth: 2, dashed: false,
    id: 'position', extentFromRight: TRADE_EXTENT, leftLabel: positionLabel(markPrice()), closeButton: true,
  });
}

/**
 * Repaint the demo's own trade chrome in the current palette. The lines and
 * markers already on the chart were built with the colours as they were, so
 * a Trading-tab edit has to reach them: `setOptions` restyles a price line in
 * place, and the markers carry their colour per fill.
 */
export function restyleTradeChrome() {
  const tc = tradeColors();
  for (const o of app.orders) if (o.line) o.line.setOptions({ color: tc.order });
  if (app.bLines) {
    app.bLines.entry.setOptions({ color: tc.order });
    app.bLines.tp.setOptions({ color: tc.tp });
    app.bLines.sl.setOptions({ color: tc.sl });
  }
  if (app.posLine && app.position) app.posLine.setOptions({ color: app.position.netQty > 0 ? tc.long : tc.short });
  if (app.fills.length) {
    for (const f of app.fills) f.color = f.shape === 'arrowUp' ? tc.buy : tc.sell;
    if (app.markersApi) app.markersApi.setMarkers(app.fills);
  }
}
export function clearPosition() {
  if (app.posLine && app.chart) app.chart.removePrimitive(app.posLine);
  app.posLine = null; app.position = null; app.fills = [];
  if (app.markersApi) app.markersApi.setMarkers([]);
}

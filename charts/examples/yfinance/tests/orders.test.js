import { describe, it, expect, beforeEach } from 'vitest';
import {
  initOrders, tradeColors, TRADE_FALLBACK, STORE_KEY, saveState, restoreState,
  placeOrder, cancelOrder, fillMarket, removeAllOrders, clearPosition, restyleTradeChrome,
} from '../src/orders.js';
import { fakeDom, fakeStorage, flatBar } from './helpers.js';

function freshApp() {
  return {
    chart: null, req: { symbol: 'AAPL' }, currentBars: [flatBar(1, 10)],
    orders: [], nextOrderId: 1, position: null, posLine: null, fills: [], markersApi: null,
    bLines: null,
  };
}

describe('orders and the net position', () => {
  let app;
  let dom;
  beforeEach(() => {
    dom = fakeDom({ qty: '100', product: 'MIS' });
    fakeStorage();
    app = freshApp();
    initOrders(app);
  });

  it('falls back to the demo palette until a chart answers', () => {
    expect(tradeColors()).toBe(TRADE_FALLBACK);
    app.chart = { tradingSettings: () => ({ order: '#123456' }) };
    expect(tradeColors().order).toBe('#123456');
  });

  it.each(['workspaceLoading', 'replay', 'replayPicking', 'replayLoading', 'loading', 'loadFailed'])('refuses execution during %s', flag => {
    app[flag] = true;
    placeOrder('BUY', 'LIMIT', 10);
    fillMarket('SELL', 1);
    expect(app.orders).toEqual([]);
    expect(app.position).toBeNull();
    expect(app.fills).toEqual([]);
    expect(app.nextOrderId).toBe(1);
  });

  it('rests a limit order with the quantity and product from the controls', () => {
    placeOrder('BUY', 'LIMIT', 101.239);
    expect(app.orders).toEqual([{ id: 1, side: 'BUY', type: 'LIMIT', price: 101.24, qty: 100, product: 'MIS', line: null }]);
    expect(app.nextOrderId).toBe(2);
    expect(dom.get('status').textContent).toContain('BUY LIMIT 100 AAPL @ 101.24 (MIS)');
    cancelOrder('order:1');
    expect(app.orders).toEqual([]);
    expect(dom.get('status').textContent).toBe('cancelled BUY LIMIT @ 101.24');
  });

  it('builds a volume-weighted position out of market fills', () => {
    fillMarket('BUY', 100);
    expect(app.position).toEqual({ netQty: 100, avgPrice: 10 });
    app.currentBars = [flatBar(2, 12)];
    fillMarket('BUY', 100);
    expect(app.position).toEqual({ netQty: 200, avgPrice: 11 });
    expect(app.fills.map((f) => f.shape)).toEqual(['arrowUp', 'arrowUp']);
    expect(dom.get('status').textContent).toBe('BUY MARKET 100 filled @ 12.00 -> LONG 200 @ 11.00');
  });

  it('reduces on the average price and flips at the fill price', () => {
    fillMarket('BUY', 100);
    app.currentBars = [flatBar(2, 15)];
    fillMarket('SELL', 40);
    expect(app.position).toEqual({ netQty: 60, avgPrice: 10 });
    fillMarket('SELL', 100);
    expect(app.position).toEqual({ netQty: -40, avgPrice: 15 });
    fillMarket('BUY', 40);
    expect(app.position).toBeNull();
    expect(dom.get('status').textContent).toBe('BUY MARKET 40 filled @ 15.00 -> flat');
  });

  it('persists and restores the trade state per symbol without the line handles', () => {
    placeOrder('SELL', 'SL', 9.5);
    app.orders[0].line = { fake: true };
    app.bracket = { side: 'BUY', entry: 10, target: 11, stop: 9, qty: 5 };
    fillMarket('BUY', 10);
    saveState();
    const raw = JSON.parse(localStorage.getItem(STORE_KEY('AAPL')));
    expect(raw.orders).toEqual([{ id: 1, side: 'SELL', type: 'SL', price: 9.5, qty: 100, product: 'MIS' }]);
    expect(raw.nextOrderId).toBe(2);
    expect(raw.bracket.entry).toBe(10);
    expect(raw.position).toEqual({ netQty: 10, avgPrice: 10 });
    expect(raw.fills).toHaveLength(1);

    removeAllOrders(); clearPosition(); app.bracket = null;
    restoreState('AAPL');
    expect(app.orders).toEqual([{ id: 1, side: 'SELL', type: 'SL', price: 9.5, qty: 100, product: 'MIS', line: null }]);
    expect(app.nextOrderId).toBe(2);
    expect(app.bracket.stop).toBe(9);
    expect(app.position).toEqual({ netQty: 10, avgPrice: 10 });
    expect(app.fills).toHaveLength(1);

    restoreState('NOPE');
    expect(app.orders).toEqual([]);
    expect(app.bracket).toBeNull();
    expect(app.position).toBeNull();
  });

  it('repaints resting lines and fills in the palette the chart reports', () => {
    app.chart = { tradingSettings: () => ({ ...TRADE_FALLBACK, order: '#111111', buy: '#222222' }) };
    const styled = [];
    app.orders = [{ id: 1, line: { setOptions: (o) => styled.push(o) } }];
    app.fills = [{ shape: 'arrowUp', color: '#000000' }];
    const marked = [];
    app.markersApi = { setMarkers: (m) => marked.push(m.map((f) => f.color)) };
    restyleTradeChrome();
    expect(styled).toEqual([{ color: '#111111' }]);
    expect(marked).toEqual([['#222222']]);
  });
});

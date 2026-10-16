import { describe, it, expect, beforeEach } from 'vitest';
import { initBracket, makeBracket, setBracketPrice, removeBracket } from '../src/bracket.js';
import { initOrders } from '../src/orders.js';
import { fakeDom, fakeStorage, flatBar } from './helpers.js';

// initBracket starts the pill loop through requestAnimationFrame; a stub that
// never calls back keeps the tests synchronous.
globalThis.requestAnimationFrame = () => 0;

/** A chart that hands out price lines and remembers what was removed. */
function fakeChart() {
  const lines = [];
  const removed = [];
  return {
    lines, removed,
    addPriceLine: (opts) => {
      const line = { ...opts, setPrice: (p) => { line.price = p; }, setOptions: () => {} };
      lines.push(line);
      return line;
    },
    removePrimitive: (p) => removed.push(p),
    priceToCoordinate: () => null,
  };
}

describe('the bracket', () => {
  let app;
  let dom;
  beforeEach(() => {
    dom = fakeDom({ qty: '100' });
    fakeStorage();
    app = {
      chart: fakeChart(), req: { symbol: 'AAPL' }, currentBars: [flatBar(1, 100)],
      bracket: null, bLines: null, orders: [], nextOrderId: 1, position: null, posLine: null,
      fills: [], markersApi: null,
    };
    initOrders(app);
    initBracket(app);
  });

  it('opens around the last close with a wider target than stop', () => {
    makeBracket('BUY');
    expect(app.bracket).toEqual({ side: 'BUY', entry: 100, qty: 100, target: 101.2, stop: 99 });
    expect(app.chart.lines.map((l) => l.id)).toEqual(['bk-entry', 'bk-tp', 'bk-sl']);
    expect(dom.get('bracket').hidden).toBe(false);
    expect(dom.get('bk-tp').querySelector('.pts').textContent).toBe('1.20');
    // No currency sign: the demo charts instruments in several currencies.
    expect(dom.get('bk-tp').querySelector('.pnl').textContent).toBe('+120');
    expect(dom.get('bk-sl').querySelector('.pnl').textContent).toBe('-100');
    expect(dom.get('bk-entry').querySelector('.rr').textContent).toBe('1.20');
    expect(dom.get('bk-entry').querySelector('[data-act="place"]').textContent).toBe('1-Click Buy');
  });

  it('does not create or reprice a bracket while replay history is loading', () => {
    app.replayLoading = true;
    makeBracket('BUY');
    expect(app.bracket).toBeNull();
    app.replayLoading = false;
    makeBracket('BUY');
    const saved = { ...app.bracket };
    app.replayLoading = true;
    setBracketPrice('entry', 150);
    expect(app.bracket).toEqual(saved);
  });

  it('keeps the exits on the right side of the entry and moves the whole bracket with it', () => {
    makeBracket('BUY');
    setBracketPrice('tp', 100.5);
    expect(app.bracket.target).toBe(100.5);
    setBracketPrice('tp', 98);
    expect(app.bracket.target).toBe(100.01);
    setBracketPrice('sl', 102);
    expect(app.bracket.stop).toBe(99.99);
    setBracketPrice('entry', 110);
    expect(app.bracket).toEqual({ side: 'BUY', entry: 110, qty: 100, target: 110.01, stop: 109.99 });
    expect(app.bLines.entry.price).toBe(110);
    expect(app.bLines.tp.price).toBe(110.01);
    expect(app.bLines.sl.price).toBe(109.99);
  });

  it('mirrors the sides for a short', () => {
    makeBracket('SELL');
    expect(app.bracket.target).toBe(98.8);
    expect(app.bracket.stop).toBe(101);
    setBracketPrice('tp', 105);
    expect(app.bracket.target).toBe(99.99);
    expect(dom.get('bk-entry').querySelector('[data-act="place"]').textContent).toBe('1-Click Sell');
  });

  it('takes its three lines off the chart when cancelled', () => {
    makeBracket('BUY');
    const lines = app.bLines;
    removeBracket();
    expect(app.bracket).toBeNull();
    expect(app.bLines).toBeNull();
    expect(app.chart.removed).toEqual([lines.entry, lines.tp, lines.sl]);
    expect(dom.get('bracket').hidden).toBe(true);
  });
});

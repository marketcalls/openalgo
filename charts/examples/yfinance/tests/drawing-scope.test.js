import { describe, it, expect, afterEach, vi } from 'vitest';

vi.mock('../src/ui.js', async original => ({ ...await original(), toast: vi.fn() }));

import { DrawingController } from '/dist/openalgo-charts.draw.mjs';
import { DRAWINGS_PREFIX, scopeDrawings } from '../src/drawing-scope.js';
import { toast } from '../src/ui.js';
import { fakeStorage } from './helpers.js';

// The reference host keeps each chart's drawings per symbol, in the page's
// storage: one entry per chart and symbol, swapped as the chart's data context
// names another symbol, and a storage that refuses is said once.

const made = [];
afterEach(() => { for (const draw of made.splice(0)) draw.destroy(); vi.clearAllMocks(); });

/** A chart host with a data context, enough for the drawing controller. */
function chart(symbol) {
  const listeners = new Map();
  let context = { symbol, interval: '1d' };
  const host = {
    on: (event, cb) => { const set = listeners.get(event) ?? new Set(); set.add(cb); listeners.set(event, set); return () => set.delete(cb); },
    emit: (event, payload) => { for (const cb of [...(listeners.get(event) ?? [])]) cb(payload); },
    addPrimitive() {}, removePrimitive() {}, dataLayer: {}, getVisibleLogicalRange: () => ({ from: 0, to: 10 }),
    drawingState: () => null, setDrawingState() {}, panes: () => [{}],
    getDataContext: () => context,
    setDataContext: next => { context = next; host.emit('data:context', next); },
  };
  const draw = new DrawingController(host);
  made.push(draw);
  return { host, draw };
}
const line = price => ({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1000, price }] });

describe('drawings per symbol in the reference host', () => {
  it('keeps one entry per chart and symbol, and swaps them with the symbol', () => {
    const storage = fakeStorage();
    const { host, draw } = chart('AAPL');
    const scoped = scopeDrawings(host, draw, 1, 'stored');
    const drawn = draw.add(line(101));
    expect([...storage.keys()]).toEqual([`${DRAWINGS_PREFIX}1:AAPL`]);
    host.setDataContext({ symbol: 'MSFT', interval: '1d' });
    expect(draw.drawings()).toEqual([]);
    host.setDataContext({ symbol: 'AAPL', interval: '1d' });
    expect(draw.drawings().map(d => d.id)).toEqual([drawn.id]);
    scoped.destroy();

    // The second chart of the split keeps its own, on the same symbol too.
    const second = chart('AAPL');
    scopeDrawings(second.host, second.draw, 2, 'stored');
    expect(second.draw.drawings()).toEqual([]);
  });

  it('says once that storage refused the drawings, and keeps them for the session', () => {
    const storage = fakeStorage();
    globalThis.localStorage.setItem = () => { throw new Error('quota'); };
    const { host, draw } = chart('AAPL');
    scopeDrawings(host, draw, 1, 'stored');
    draw.add(line(101));
    draw.add(line(102));
    expect(toast).toHaveBeenCalledTimes(1);
    expect(toast.mock.calls[0][1]).toContain('AAPL');
    host.setDataContext({ symbol: 'MSFT', interval: '1d' });
    host.setDataContext({ symbol: 'AAPL', interval: '1d' });
    expect(draw.drawings()).toHaveLength(2);
    expect(storage.size).toBe(0);
  });
});

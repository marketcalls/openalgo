import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDom } from './fake-dom.js';
vi.mock('../src/persist.js', () => ({ autosave: vi.fn() }));
vi.mock('../src/ui.js', async original => ({ ...await original(), toast: vi.fn() }));
import { toast } from '../src/ui.js';
import { initIndicators, watchStudyStatus } from '../src/indicators.js';

// A study that stops drawing says why in the reference host: the status line
// and a toast, once per reason.
afterEach(() => { vi.clearAllMocks(); });

function setup() {
  const { document } = installDom();
  for (const id of ['set-body', 'set-title', 'setmodal', 'indadd', 'indpick', 'set-ok', 'set-x', 'set-reset', 'status', 'indlist']) {
    const node = document.createElement(id.startsWith('set-') && !['set-body', 'set-title'].includes(id) ? 'button' : 'div');
    node.id = id; document.body.appendChild(node);
  }
  let status = { state: 'ready' };
  const study = { id: 'ema-1', indicatorId: 'ema', name: 'EMA', settings: () => ({ color: '#26a69a' }), values: () => ({ ema: [] }),
    series: () => null, dataStatus: () => status };
  const listeners = new Map();
  const chart = { indicators: () => [study], getDataContext: () => undefined,
    on: (event, callback) => {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(callback); return () => listeners.get(event).delete(callback);
    } };
  initIndicators({ chart, req: {}, focusPane: 1 });
  const publish = next => { status = next; for (const callback of listeners.get('indicator:data-status') ?? []) callback({ id: study.id, indicatorId: 'ema', status }); };
  return { document, chart, publish };
}

describe('a study that stops drawing', () => {
  it('says why once per reason, and again once it fails anew after drawing', () => {
    const { document, chart, publish } = setup();
    watchStudyStatus(chart);
    const refusal = new Error('EMA: this chart draws transformed bars, which a timeframe cannot fold; compute the study on the underlying bars');
    publish({ state: 'error', error: refusal });
    expect(document.getElementById('status').textContent).toBe(refusal.message);
    expect(toast).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledWith('error', refusal.message);
    // The next tick fails the same way with a new error object: no second toast.
    publish({ state: 'error', error: new Error(refusal.message) });
    expect(toast).toHaveBeenCalledTimes(1);
    // A failure without the study's name gets it, once.
    publish({ state: 'error', error: new Error('division by zero') });
    expect(toast).toHaveBeenLastCalledWith('error', 'EMA: division by zero');
    publish({ state: 'ready' });
    publish({ state: 'error', error: new Error('division by zero') });
    expect(toast).toHaveBeenCalledTimes(3);
  });
});

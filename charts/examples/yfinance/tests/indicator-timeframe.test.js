import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock('/dist/openalgo-charts.mjs', () => import('../../../src/index.ts'));
vi.mock('/dist/openalgo-charts.widget.mjs', () => import('../../../src/widget/index.ts'));
vi.mock('openalgo-charts', () => import('../../../src/index.ts'));
vi.mock('../src/persist.js', () => ({ autosave: vi.fn() }));
import { installDom } from '../../../tests/widget-form.test.ts';
import { renderInputRows, collectInputRows, destroyInputRows } from '../src/indicators.js';
import { INTERVALS, intervalLabel } from '../src/intervals.js';

// A study's timeframe input in the reference host's settings form: a select,
// the chart's own timeframe first, then the intervals this host serves.
const input = { key: 'timeframe', type: 'interval', label: 'Timeframe', default: '' };
const cleanups = [];
afterEach(() => { cleanups.splice(0).reverse().forEach(dispose => dispose()); vi.unstubAllGlobals(); });

function form(value) {
  const dom = installDom(); vi.stubGlobal('document', dom.doc); vi.stubGlobal('window', dom.win);
  const host = dom.doc.createElement('div'); host.id = 'set-body'; dom.root.appendChild(host);
  renderInputRows(host, [input], { timeframe: value });
  cleanups.push(() => destroyInputRows(host));
  return { host, field: host.querySelector('#set-body_timeframe') };
}

describe('the timeframe input', () => {
  it('is a select over the chart and the intervals the host serves', () => {
    const { host, field } = form('');
    expect(field.tagName).toBe('SELECT');
    const options = field.querySelectorAll('option');
    expect(options.map(o => o.value)).toEqual(['', ...INTERVALS]);
    expect(options[0].textContent).toBe('Chart');
    expect(options.slice(1).map(o => o.textContent)).toEqual(INTERVALS.map(intervalLabel));
    field.value = '1h';
    field.fire('change');
    expect(collectInputRows(host)).toEqual({ timeframe: '1h' });
  });

  it('keeps a saved code the host does not list, rather than dropping it to the chart', () => {
    const { host, field } = form('2h');
    expect(field.value).toBe('2h');
    expect(field.querySelectorAll('option').map(o => o.value)).toEqual(['', ...INTERVALS, '2h']);
    expect(collectInputRows(host)).toEqual({ timeframe: '2h' });
  });
});

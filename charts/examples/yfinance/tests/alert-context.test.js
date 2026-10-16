import { describe, expect, it, vi } from 'vitest';
import '/dist/openalgo-charts.indicators.mjs';
import { alertContextEntries } from '../src/alerts.js';

function host() {
  const context = { symbol: 'ONE', exchange: 'SIM', interval: '5m' };
  const chart = { getDataContext: () => context, primaryBars: () => [{ close: 100 }],
    indicators: () => [{ id: 'study-two', indicatorId: 'macd', paneIndex: 1,
      values: () => ({ macd: [10, 20], signal: [0, null], hist: [5, 6] }) }] };
  const draw = { get: id => id === 'clicked' ? { id } : null,
    alertInfo: () => ({ available: true }) };
  const ui = { openList: vi.fn(() => true), openEditor: vi.fn(() => true) };
  const app = { chart, draw, alertUi: ui, chart2: chart, draw2: draw,
    alertUi2: { openList: vi.fn(() => true), openEditor: vi.fn(() => true) }, focusPane: 1 };
  return { app, chart, draw, ui, context };
}
const event = (patch = {}) => ({ paneIndex: 0, price: 105, index: 0, target: { kind: 'empty' }, ...patch });

describe('reference alert context actions', () => {
  it('binds secondary creation and list actions to the clicked chart despite a focus change', () => {
    const { app, ui } = host();
    const rows = alertContextEntries(app, event(), 2);
    app.focusPane = 1;
    rows[0].onSelect(); rows[1].onSelect();
    expect(app.alertUi2.openEditor).toHaveBeenCalledWith({ source: { kind: 'price', price: 105 } });
    expect(app.alertUi2.openList).toHaveBeenCalledOnce();
    expect(ui.openEditor).not.toHaveBeenCalled();
    expect(ui.openList).not.toHaveBeenCalled();
  });
  it('preserves the clicked plot and a zero reading without replacing a missing reading', () => {
    const { app, ui } = host();
    const target = { kind: 'indicator', instanceId: 'study-two', plotKey: 'signal' };
    alertContextEntries(app, event({ paneIndex: 1, target }))[0].onSelect();
    expect(ui.openEditor).toHaveBeenLastCalledWith({ source: {
      kind: 'indicator', instanceId: 'study-two', plotKey: 'signal', value: 0,
    } });
    alertContextEntries(app, event({ paneIndex: 1, index: 1, target }))[0].onSelect();
    expect(ui.openEditor.mock.lastCall[0].source.value).toBeNaN();
  });
  it('keeps unavailable drawings disabled and never substitutes a price for a deleted anchor', () => {
    const { app, draw, ui } = host();
    draw.alertInfo = () => ({ available: false, reason: 'No alert level' });
    const target = { kind: 'drawing', id: 'draw:clicked#0' };
    const row = alertContextEntries(app, event({ target }))[0];
    expect(row).toMatchObject({ disabled: true, reason: 'No alert level' });
    row.onSelect();
    expect(ui.openEditor).not.toHaveBeenCalled();
    expect(alertContextEntries(app, event({ target: { kind: 'drawing', id: 'draw:gone' } }))).toHaveLength(1);
  });
  it('rejects stale chart generations and scope changes without opening an editor', () => {
    const { app, ui, chart, context } = host();
    const rows = alertContextEntries(app, event());
    app.chart = { ...chart };
    rows[0].onSelect();
    app.chart = chart;
    context.symbol = 'OTHER';
    rows[0].onSelect(); rows[1].onSelect();
    expect(ui.openEditor).not.toHaveBeenCalled();
    expect(ui.openList).not.toHaveBeenCalled();
  });
  it('treats a session change after the menu opened as a change of scope', () => {
    const { app, ui, context } = host();
    const rows = alertContextEntries(app, event());
    context.variant = { session: 'extended' };
    rows[0].onSelect(); rows[1].onSelect();
    expect(ui.openEditor).not.toHaveBeenCalled();
    expect(ui.openList).not.toHaveBeenCalled();
  });
  it('offers only the list for empty oscillator space, time scales and unavailable chart UI', () => {
    const { app } = host();
    expect(alertContextEntries(app, event({ paneIndex: 1 })).map(row => row.label)).toEqual(['Alerts...']);
    expect(alertContextEntries(app, event({ price: null, target: { kind: 'time-scale' } }))).toHaveLength(1);
    app.alertUi = null;
    expect(alertContextEntries(app, event())).toEqual([]);
  });
});

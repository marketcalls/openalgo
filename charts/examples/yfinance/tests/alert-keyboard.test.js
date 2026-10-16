import { afterEach, describe, expect, it } from 'vitest';
import { AlertController } from '../../../src/alerts/controller.ts';
import { initRail, buildRail } from '../src/rail.js';
import { railPage, pressKey } from './rail-dom.js';
import { fakeStorage } from './helpers.js';
import { makeApp, line, T0 } from './draw-host.js';

const cleanup = [];
afterEach(() => { for (const dispose of cleanup.splice(0)) dispose(); });

function controller() {
  const { app, chart, draw } = makeApp();
  let saved;
  Object.assign(chart, {
    primaryBars: () => [{ time: T0, open: 100, high: 101, low: 99, close: 100 }],
    getDataContext: () => ({ symbol: 'TEST', interval: '1m' }),
    setAlertState: value => { saved = value; },
    alertState: () => saved,
  });
  const alerts = new AlertController(chart, { drawings: draw, visuals: false });
  cleanup.push(() => { alerts.destroy(); draw.destroy(); });
  app.alerts = alerts;
  const alert = alerts.add({ source: { kind: 'price', price: 101 } });
  chart.emit('hover', { id: `alert:${alert.id}:0` });
  expect(alerts.hovered()).toBe(alert.id);
  return { app, chart, draw, alerts, alert };
}

function setup() {
  const page = railPage();
  fakeStorage();
  const host = controller();
  initRail(host.app);
  buildRail();
  return { ...host, page };
}

describe('reference host alert keyboard ownership', () => {
  it.each(['Delete', 'Backspace'])('removes and saves only the hovered alert for %s', key => {
    const { chart, alerts } = setup();
    const kept = alerts.add({ source: { kind: 'price', price: 99 } });
    const event = pressKey(key);
    expect(alerts.list().map(item => item.id)).toEqual([kept.id]);
    expect(chart.alertState().alerts.map(item => item.id)).toEqual([kept.id]);
    expect(event.defaultPrevented).toBe(true);
    expect(event.propagationStopped).toBe(true);
  });

  it.each(['Delete', 'Backspace'])('gives selected drawings priority over a hovered alert for %s', key => {
    const { chart, draw, alerts, alert } = setup();
    const first = line(draw);
    const second = line(draw);
    draw.select([first.id, second.id]);
    chart.emit('hover', { id: `alert:${alert.id}:0` });
    expect(alerts.hovered()).toBe(alert.id);
    expect(pressKey(key).defaultPrevented).toBe(true);
    expect(draw.drawings()).toEqual([]);
    expect(alerts.list().map(item => item.id)).toEqual([alert.id]);
  });

  it.each(['Delete', 'Backspace'])('gives a hovered drawing priority for %s', key => {
    const { chart, draw, alerts, alert } = setup();
    const drawing = line(draw);
    chart.emit('hover', { id: `draw:${drawing.id}` });
    expect(pressKey(key).defaultPrevented).toBe(true);
    expect(draw.get(drawing.id)).toBeUndefined();
    expect(alerts.list().map(item => item.id)).toEqual([alert.id]);
  });

  it('preserves the alert during placement and drops the last anchor on Backspace', () => {
    const { chart, draw, alerts, alert } = setup();
    draw.setTool('polyline');
    for (const [time, price] of [[T0, 99], [T0 + 60, 100], [T0 + 120, 101]]) chart.emit('click', { time, price, paneIndex: 0 });
    expect(pressKey('Delete').defaultPrevented).toBe(false);
    expect(pressKey('Backspace').defaultPrevented).toBe(true);
    pressKey('Enter');
    expect(draw.drawings()).toHaveLength(1);
    expect(draw.drawings()[0].points).toEqual([{ time: T0, price: 99 }, { time: T0 + 60, price: 100 }]);
    expect(alerts.list().map(item => item.id)).toEqual([alert.id]);
  });

  it.each(['Delete', 'Backspace'])('uses the focused split chart for %s', key => {
    const { app, alerts, alert } = setup();
    const second = controller();
    app.chart2 = second.chart;
    app.draw2 = second.draw;
    app.alerts2 = second.alerts;
    app.focusPane = 2;
    expect(pressKey(key).defaultPrevented).toBe(true);
    expect(second.alerts.list()).toEqual([]);
    expect(alerts.list().map(item => item.id)).toEqual([alert.id]);
  });

  it.each(['input', 'textarea', 'select', 'editable'])('leaves %s editing alone', kind => {
    const { page, alerts, alert } = setup();
    const input = page.doc.createElement(kind === 'editable' ? 'div' : kind);
    if (kind === 'editable') input.isContentEditable = true;
    page.doc.body.appendChild(input);
    for (const key of ['Delete', 'Backspace']) expect(pressKey(key, {}, input).defaultPrevented).toBe(false);
    expect(alerts.list().map(item => item.id)).toEqual([alert.id]);
  });

  it('leaves modified keys, dialogs and rail focus alone', () => {
    const { app, page, alerts, alert } = setup();
    const check = () => {
      for (const key of ['Delete', 'Backspace']) expect(pressKey(key).defaultPrevented).toBe(false);
      expect(alerts.list().map(item => item.id)).toEqual([alert.id]);
    };
    for (const modifier of ['ctrlKey', 'metaKey', 'altKey', 'shiftKey']) {
      for (const key of ['Delete', 'Backspace']) expect(pressKey(key, { [modifier]: true }).defaultPrevented).toBe(false);
    }
    page.doc.getElementById('textmodal').hidden = false;
    check();
    page.doc.getElementById('textmodal').hidden = true;
    app.alertUi = { isOpen: () => true };
    check();
    app.alertUi = null;
    app.alertUi2 = { isOpen: () => true };
    check();
    app.alertUi2 = null;
    page.rail.querySelector('button').focus();
    check();
  });
});

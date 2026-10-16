// The reference host's Go to panel across the chart rebuild a longer period
// causes. load() throws the pane's chart away together with the overlays the
// panel lives in, so the panel that started a request is gone before the
// request has an answer. These tests hold the page to reporting that answer
// in a panel anyway, and to dropping the request when the user closes it.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('/dist/openalgo-charts.mjs', () => import('../../../src/index.ts'));
vi.mock('/dist/openalgo-charts.widget.mjs', () => import('../../../src/widget/index.ts'));
vi.mock('openalgo-charts', () => import('../../../src/index.ts'));
vi.mock('openalgo-charts/draw', () => import('../../../src/draw/index.ts'));
import { Chart, utcSecondsToZonedParts } from '../../../src/index.ts';
import { createOverlayStack } from '../../../src/widget/context.ts';
import { installDom } from '../../../tests/widget-form.test.ts';
import { PERIOD_DAYS } from '../src/intervals.js';
import { initGoTo, openGoTo } from '../src/goto.js';

const DAY = 86400;
const NOW = Math.floor(Date.now() / 1000);
// A date on a daily chart past the five years it opens with.
const BACK = NOW - 6 * 366 * DAY;
const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };
const ymd = time => {
  const p = utcSecondsToZonedParts(time, 'Asia/Kolkata');
  return `${p.year}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')}`;
};

let dom, app, pane, gate;

/** One bar a day at the same instant, reaching `days` back from now: what a period load returns. */
function periodBars(days) {
  const out = [];
  for (let t = NOW - days * DAY; t < NOW; t += DAY) out.push({ time: t, open: 10, high: 11, low: 9, close: 10.5 });
  return out;
}
// The longest period has no length of its own: it returns what the source
// holds, twenty years here as on the fixture server.
const MAX_DAYS = 20 * 366;

/** What render() leaves behind: a new chart and a new overlay layer for its panels. */
function mountPane() {
  const chart = new Chart(dom.chartEl, { document: dom.doc, pixelRatio: () => 1, shortcuts: false,
    branding: false, timeNavigator: false, raf: { schedule: fn => { fn(); return 1; }, cancel() {} } });
  chart.applySize(900, 600);
  chart.addSeries('candlestick').setData(periodBars(Math.min(PERIOD_DAYS[app.req.period], MAX_DAYS)));
  chart.setDataContext({ symbol: app.req.symbol, exchange: '', interval: app.req.interval });
  const overlays = createOverlayStack(dom.root, dom.doc);
  const context = { chart, root: dom.root, document: dom.doc, overlays,
    openOverlay: (node, options) => overlays.open(node, options), interval: () => app.req.interval };
  app.chart = chart;
  app.inspection1 = { context };
  return { chart, overlays };
}

function setup(interval, period) {
  dom = installDom();
  vi.stubGlobal('document', dom.doc);
  vi.stubGlobal('window', dom.win);
  for (const [tag, id] of [['div', 'status'], ['input', 'period'], ['button', 'goto']]) {
    const node = dom.doc.createElement(tag);
    node.id = id;
    dom.root.appendChild(node);
  }
  dom.doc.getElementById('period').value = period;
  // The fake document lays nothing out, and a reopened panel hangs only from a
  // control that is on screen: the toolbar's Go to is, here.
  dom.doc.getElementById('goto').getClientRects = () => [{}];
  gate = null;
  app = { req: { symbol: 'AAA', interval, period }, focusPane: 1 };
  app.load = vi.fn(async () => {
    // The real load awaits its fetch before render() rebuilds, so the rebuild
    // lands while the panel's request is under way, never inside navigate().
    await (gate ? gate.promise : Promise.resolve());
    await Promise.resolve();
    app.req.period = dom.doc.getElementById('period').value;
    // render(): the pane's overlays are released first, then its chart.
    pane.overlays.destroy();
    pane.chart.destroy();
    pane = mountPane();
  });
  pane = mountPane();
  initGoTo(app);
}

function ask(date) {
  expect(openGoTo(dom.doc.getElementById('goto'))).toBe(true);
  const panel = dom.doc.querySelector('.oac-goto');
  const [day, time] = panel.querySelectorAll('input');
  day.value = date;
  time.value = '';
  panel.querySelector('.oac-dialog__actions button').click();
  return panel;
}

const centre = chart => {
  const view = chart.getVisibleLogicalRange();
  return chart.dataLayer.indexToTime(Math.round((view.from + view.to) / 2));
};

afterEach(() => { pane?.overlays.destroy(); pane?.chart.destroy(); vi.unstubAllGlobals(); });

describe('reference go-to panel across a chart rebuild', () => {
  // Five years on screen, the shortest daily range, so six years back needs the longest.
  beforeEach(() => setup('1d', '5y'));

  it('places the date on the rebuilt chart and closes the panel it reopened', async () => {
    const first = ask(ymd(BACK));
    await flush();
    expect(app.load).toHaveBeenCalledTimes(1);
    expect(app.req.period).toBe('max');
    expect(first.isConnected).toBe(false);
    expect(dom.doc.querySelector('.oac-goto')).toBeNull();
    expect(dom.doc.getElementById('status').textContent).toMatch(/^Showing /);
    const expected = app.chart.primaryBars().find(bar => ymd(bar.time) === ymd(BACK)).time;
    expect(centre(app.chart)).toBe(expected);
  });

  it('drops the request when the user closes the panel during the load', async () => {
    let release;
    gate = { promise: new Promise(resolve => { release = resolve; }) };
    const panel = ask(ymd(BACK));
    await flush();
    expect(panel.querySelector('.oac-goto__message').textContent).toBe('Loading history');
    panel.querySelector('.oac-dialog__head button').click();
    await flush();
    release();
    await flush();
    // The longer period still loads; the view does not jump to the date.
    expect(app.req.period).toBe('max');
    expect(dom.doc.querySelector('.oac-goto')).toBeNull();
    expect(dom.doc.getElementById('status').textContent).not.toMatch(/^Showing /);
    const target = app.chart.primaryBars().find(bar => ymd(bar.time) === ymd(BACK)).time;
    expect(centre(app.chart)).not.toBe(target);
  });
});

describe('reference go-to request and the view it would move', () => {
  // Five years on screen, the shortest daily range, so six years back needs the longest.
  beforeEach(() => setup('1d', '5y'));

  it('drops the request when the user pans or zooms while the longer period loads', async () => {
    let release;
    gate = { promise: new Promise(resolve => { release = resolve; }) };
    const panel = ask(ymd(BACK));
    await flush();
    const message = panel.querySelector('.oac-goto__message');
    expect(message.textContent).toBe('Loading history');
    const view = app.chart.getVisibleLogicalRange();
    app.chart.setVisibleLogicalRange({ from: view.from - 3, to: view.to - 3 });
    await flush();
    // Still open over the chart it was on, no longer claiming to load.
    expect(panel.isConnected).toBe(true);
    expect(message.textContent).toBe('');
    release();
    await flush();
    expect(app.req.period).toBe('max');
    expect(dom.doc.querySelector('.oac-goto')).toBeNull();
    expect(dom.doc.getElementById('status').textContent).not.toMatch(/^Showing /);
    const target = app.chart.primaryBars().find(bar => ymd(bar.time) === ymd(BACK)).time;
    expect(centre(app.chart)).not.toBe(target);
  });
});

describe('reference go-to panel reporting short history', () => {
  beforeEach(() => setup('1h', '1mo'));

  it('reports in a reopened panel where history starts when no period reaches the date', async () => {
    ask(ymd(NOW - 3 * 366 * DAY));
    await flush();
    // One reload to the longest period an hourly frame can serve, then nothing older.
    expect(app.load).toHaveBeenCalledTimes(1);
    expect(app.req.period).toBe('1y');
    const reopened = dom.doc.querySelector('.oac-goto');
    expect(reopened).not.toBeNull();
    expect(reopened.querySelectorAll('input')[0].value).toBe(ymd(NOW - 3 * 366 * DAY));
    expect(reopened.querySelector('.oac-goto__message').textContent).toMatch(/^History starts at /);
    expect(dom.doc.getElementById('status').textContent).toMatch(/^History starts at /);
    expect(centre(app.chart)).toBe(app.chart.primaryBars()[0].time);
  });
});

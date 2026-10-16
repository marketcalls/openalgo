/**
 * The wash behind pre-open, post-close and extended-hours bars.
 *
 * What it must get right: it shades exactly the bars the calendar puts outside
 * the regular session, with edges on bar midpoints; it shades nothing unless a
 * host attaches it or the view has nothing to show; and it asks the calendar
 * about the sessions in view, not about every bar on every frame.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { SessionShade, attachSessionShading } from '../src/primitives/session-shade';
import { SessionCalendar } from '../src/feed/instrument';
import type { SessionPhaseSource } from '../src/feed/market-status';
import { DataLayer } from '../src/model/data-layer';
import { TimeScale } from '../src/scale/time-scale';
import { darkTheme, lightTheme, type ChartTheme } from '../src/theme';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { RecordingContext } from './helpers/fake-ctx';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import type { Bar } from '../src/model/bar';
import '../src/indicators/index';

const time = (iso: string): number => Date.parse(iso) / 1000;
const PLOT_W = 900, PLOT_H = 400;

/** US hours with pre-open from 04:00 and post-close to 20:00, New York time. */
const us = new SessionCalendar({
  timezone: 'America/New_York', sessions: ['0930-1600:23456'], preMarketMinutes: 330, postMarketMinutes: 240,
});

/** A seeded random walk, one bar every `step` seconds while `keep(time)` holds. */
function walk(from: number, to: number, step: number, keep: (t: number) => boolean = () => true): Bar[] {
  let seed = 11, close = 187.3;
  const random = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const bars: Bar[] = [];
  for (let t = from; t < to; t += step) {
    if (!keep(t)) continue;
    const open = close;
    close = +(open * (1 + (random() - 0.5) * 0.004)).toFixed(2);
    bars.push({ time: t, open, high: Math.max(open, close) + 0.05, low: Math.min(open, close) - 0.05, close, volume: 500 });
  }
  return bars;
}

/** Two New York trading days of 15-minute bars, 04:00 to 20:00 EDT, as an extended-hours feed serves them. */
const extendedBars = (): Bar[] => walk(time('2026-06-17T08:00:00Z'), time('2026-06-19T00:00:00Z'), 900,
  t => us.phaseAt(t) !== 'closed');

function setup(bars: Bar[], spacing = PLOT_W / bars.length, theme: ChartTheme = darkTheme, dpr = 1) {
  const data = new DataLayer();
  data.setSeriesData(data.createSeries(), bars);
  const timeScale = new TimeScale({ barSpacing: spacing });
  timeScale.setWidth(PLOT_W);
  timeScale.setBaseIndex(bars.length - 1);
  timeScale.setRightOffset(0);
  const rc = { timeScale, dataLayer: data, plotWidth: PLOT_W, plotHeight: PLOT_H, dpr, theme } as PrimitiveRenderContext;
  const paint = (shade: SessionShade): RecordingContext => {
    const rec = new RecordingContext();
    shade.draw(rec as unknown as CanvasRenderingContext2D, rc);
    return rec;
  };
  return { data, timeScale, rc, paint };
}

const fills = (rec: RecordingContext) => rec.ops.filter(op => op.type === 'fillRect');

describe('SessionShade', () => {
  it('shades each pre-open and post-close run as one rect, edge to edge on bar midpoints', () => {
    const bars = extendedBars();
    const { rc, paint } = setup(bars);
    const rects = fills(paint(new SessionShade({ calendar: us, preColor: 'pre', postColor: 'post' })));
    // Per day: 22 pre-open bars (04:00 to 09:30), 26 regular, 16 post-close.
    expect(bars).toHaveLength(128);
    expect(rects.map(r => r.fillStyle)).toEqual(['pre', 'post', 'pre', 'post']);
    const edge = (i: number): number => Math.round(rc.timeScale.indexToX(i));
    const runs = [[0, 21], [48, 63], [64, 85], [112, 127]];
    rects.forEach((rect, k) => {
      const [a, b] = runs[k];
      expect(rect.args).toEqual([Math.max(0, edge(a - 0.5)), 0, Math.min(PLOT_W, edge(b + 0.5)) - Math.max(0, edge(a - 0.5)), PLOT_H]);
    });
    // The first day's post-close and the next day's pre-open are neighbours on
    // the gapless axis, and meet on one pixel column without overlapping.
    expect(rects[1].args[0] + rects[1].args[2]).toBe(rects[2].args[0]);
  });

  it('keeps whole device pixels and shared edges at a fractional pixel ratio', () => {
    const bars = extendedBars();
    const rects = fills(setup(bars, undefined, darkTheme, 1.25).paint(new SessionShade({ calendar: us })));
    expect(rects).toHaveLength(4);
    for (const rect of rects) expect(rect.args.every(Number.isInteger)).toBe(true);
    // Neighbours on the gapless axis meet on one device column, no gap and no overlap.
    expect(rects[1].args[0] + rects[1].args[2]).toBe(rects[2].args[0]);
    expect(rects[0].args[3]).toBe(PLOT_H * 1.25);
  });

  it('reads the calendar the chart holds, each frame, when given none of its own', () => {
    const { data, paint } = setup(extendedBars());
    const shade = new SessionShade();
    expect(fills(paint(shade))).toHaveLength(0);
    data.setSessionCalendar(us);
    expect(fills(paint(shade))).toHaveLength(4);
    // Hours with `sessionFrom` alone lay out no phases.
    data.setSessionCalendar({ sessionFrom: () => null });
    expect(fills(paint(shade))).toHaveLength(0);
    data.setSessionCalendar(null);
    expect(fills(paint(shade))).toHaveLength(0);
  });

  it('shades nothing on a regular-hours feed, on daily bars, or when hidden', () => {
    const regular = walk(time('2026-06-15T13:30:00Z'), time('2026-06-20T00:00:00Z'), 900, t => us.phaseAt(t) === 'regular');
    expect(fills(setup(regular).paint(new SessionShade({ calendar: us })))).toHaveLength(0);
    // Daily bars stamped at midnight sit inside an overnight extended window,
    // but a day bar has no part of the day to show.
    const overnight = new SessionCalendar({ timezone: 'UTC', sessions: ['0930-1600:23456'], extendedHours: ['2000-0400'] });
    const daily = walk(time('2026-01-05T00:00:00Z'), time('2026-04-05T00:00:00Z'), 86400);
    expect(fills(setup(daily).paint(new SessionShade({ calendar: overnight })))).toHaveLength(0);
    // The same calendar on 30-minute bars does shade them.
    const intraday = walk(time('2026-01-05T00:00:00Z'), time('2026-01-07T00:00:00Z'), 1800);
    expect(fills(setup(intraday).paint(new SessionShade({ calendar: overnight })))).not.toHaveLength(0);
    const { paint } = setup(extendedBars());
    expect(fills(paint(new SessionShade({ calendar: us, visible: false })))).toHaveLength(0);
  });

  it('shades nothing across a view wider than 90 days, where each column is a sliver', () => {
    // Four months of hourly extended-hours bars.
    const bars = walk(time('2026-03-02T08:00:00Z'), time('2026-07-01T00:00:00Z'), 3600, t => us.phaseAt(t) !== 'closed');
    const wide = setup(bars, PLOT_W / bars.length);
    const range = wide.timeScale.visibleRange();
    const shown = bars[Math.min(bars.length - 1, Math.ceil(range.to))].time - bars[Math.max(0, Math.floor(range.from))].time;
    expect(shown).toBeGreaterThan(90 * 86400);
    expect(fills(wide.paint(new SessionShade({ calendar: us })))).toHaveLength(0);
    // The same bars with the last few weeks in view do shade.
    expect(fills(setup(bars, 6).paint(new SessionShade({ calendar: us })))).not.toHaveLength(0);
  });

  it('shades extended hours of their own, and leaves a phase out when its colour is null', () => {
    const overnight = new SessionCalendar({ timezone: 'America/New_York', sessions: ['0930-1600:23456'],
      preMarketMinutes: 330, extendedHours: ['2000-0400:12345'] });
    const bars = walk(time('2026-06-17T00:00:00Z'), time('2026-06-18T20:00:00Z'), 1800);
    const { paint } = setup(bars);
    const all = fills(paint(new SessionShade({ calendar: overnight, preColor: 'p', extendedColor: 'x' })));
    expect(new Set(all.map(r => r.fillStyle))).toEqual(new Set(['p', 'x']));
    const noPre = fills(paint(new SessionShade({ calendar: overnight, preColor: null, extendedColor: 'x' })));
    expect(noPre.every(r => r.fillStyle === 'x')).toBe(true);
    expect(noPre.length).toBe(all.filter(r => r.fillStyle === 'x').length);
  });

  it('picks faint theme tints by default, a touch fainter on a light background', () => {
    const dark = fills(setup(extendedBars()).paint(new SessionShade({ calendar: us })));
    const light = fills(setup(extendedBars(), undefined, lightTheme).paint(new SessionShade({ calendar: us })));
    expect(dark[0].fillStyle).toBe('rgba(79,140,255,0.1)');
    expect(dark[1].fillStyle).toBe('rgba(245,158,11,0.1)');
    expect(light[0].fillStyle).toBe('rgba(41,98,255,0.07)');
    expect(light[1].fillStyle).toBe('rgba(245,158,11,0.07)');
  });

  it('keeps the default wash faint for a theme colour it cannot tint', () => {
    // A named or hsl() theme colour cannot take an alpha here, and painted as
    // it is it would cover the whole column opaque.
    const overnight = new SessionCalendar({ timezone: 'America/New_York', sessions: ['0930-1600:23456'],
      preMarketMinutes: 330, extendedHours: ['2000-0400:12345'] });
    const bars = walk(time('2026-06-17T00:00:00Z'), time('2026-06-18T20:00:00Z'), 1800);
    const theme = { ...darkTheme, lineColor: 'orange', axisText: 'hsl(220 10% 60%)' };
    const styles = new Set(fills(setup(bars, undefined, theme).paint(new SessionShade({ calendar: overnight }))).map(r => r.fillStyle));
    expect(styles).toEqual(new Set(['rgba(79,140,255,0.1)', 'rgba(139,145,167,0.13)']));
    const light = { ...lightTheme, lineColor: 'rebeccapurple' };
    const lightStyles = new Set(fills(setup(bars, undefined, light).paint(new SessionShade({ calendar: overnight }))).map(r => r.fillStyle));
    expect(lightStyles).toEqual(new Set(['rgba(41,98,255,0.07)', 'rgba(91,100,114,0.1)']));
  });

  it('asks the calendar once while a pan stays inside the time it laid out', () => {
    const bars = walk(time('2026-06-01T08:00:00Z'), time('2026-06-27T00:00:00Z'), 900, t => us.phaseAt(t) !== 'closed');
    let calls = 0;
    const counting: SessionPhaseSource = { phaseSpans: (from, to) => { calls++; return us.phaseSpans(from, to); } };
    const { timeScale, paint } = setup(bars, 6);
    const shade = new SessionShade({ calendar: counting });
    for (let k = 0; k < 20; k++) {
      timeScale.setBaseIndex(bars.length - 1 - k * 4);
      paint(shade);
    }
    expect(calls).toBe(1);
    // A jump far to the left is outside it, and lays the spans out again.
    timeScale.setBaseIndex(200);
    expect(fills(paint(shade)).length).toBeGreaterThan(0);
    expect(calls).toBe(2);
    // New options drop what was laid out: the host may mean new hours.
    shade.setOptions({ preColor: 'rgba(0,0,0,0.2)' });
    paint(shade);
    expect(calls).toBe(3);
  });

  it('draws nothing, and does not throw, for a calendar that cannot answer', () => {
    const { paint } = setup(extendedBars());
    const broken: SessionPhaseSource = { phaseSpans: () => { throw new Error('boundary is absent'); } };
    expect(fills(paint(new SessionShade({ calendar: broken })))).toHaveLength(0);
  });

  it('is a background: behind the series, never hit, never in the autoscale', () => {
    const shade = new SessionShade();
    expect(shade.zOrder()).toBe('bottom');
    expect(shade.hitTest()).toBeNull();
    expect(shade.hitBounds()).toBeNull();
    expect(shade.autoscaleInfo()).toBeNull();
  });
});

describe('attachSessionShading', () => {
  const charts: Chart[] = [];
  afterEach(() => { for (const chart of charts.splice(0)) if (!chart.isDestroyed) chart.destroy(); });
  function chart(): Chart {
    const doc = fakeDocument();
    const c = new Chart(doc.createElement('div'), { document: doc, shortcuts: false, raf: { schedule: () => 0 }, movablePrimaryPane: true });
    charts.push(c); c.applySize(900, 600); c.addSeries('candlestick').setData(extendedBars());
    return c;
  }
  const shadesOn = (c: Chart) => c.panes().map(p => p.primitives().filter(x => x instanceof SessionShade).length);

  it('adds nothing until a host attaches it, then one shade in the price pane', () => {
    const c = chart();
    c.addIndicator('rsi');
    expect(shadesOn(c)).toEqual([0, 0]);
    const shading = attachSessionShading(c, { calendar: us });
    expect(shadesOn(c)).toEqual([1, 0]);
    // A second attach is the same shading with the new options, not a second wash.
    const again = attachSessionShading(c, { preColor: null });
    expect(again).toBe(shading);
    expect(shadesOn(c)).toEqual([1, 0]);
    expect(shading.options()).toMatchObject({ calendar: us, preColor: null });
    shading.destroy();
    expect(shadesOn(c)).toEqual([0, 0]);
    shading.destroy();
    // After a destroy, attaching starts afresh.
    const fresh = attachSessionShading(c);
    expect(fresh).not.toBe(shading);
    expect(shadesOn(c)).toEqual([1, 0]);
  });

  it('follows the price pane when it moves and fills the pane maximized over it', () => {
    const c = chart();
    c.addIndicator('rsi');
    attachSessionShading(c, { calendar: us });
    expect(c.movePane(0, 1)).toBe(true);
    expect(shadesOn(c)).toEqual([0, 1]);
    expect(c.maximizePane(0)).toBe(true);
    expect(shadesOn(c)).toEqual([1, 0]);
    c.maximizePane(0);
    expect(shadesOn(c)).toEqual([0, 1]);
  });

  it('puts the shade back when a host removed it and attaches again', () => {
    const c = chart();
    const shading = attachSessionShading(c, { calendar: us });
    c.removePrimitive(c.panes()[0].primitives().find(p => p instanceof SessionShade)!);
    expect(shadesOn(c)).toEqual([0]);
    expect(attachSessionShading(c, { postColor: null })).toBe(shading);
    expect(shadesOn(c)).toEqual([1]);
    expect(shading.options()).toMatchObject({ calendar: us, postColor: null });
  });

  it('lets a destroyed chart go without throwing', () => {
    const c = chart();
    const shading = attachSessionShading(c, { calendar: us });
    c.destroy();
    expect(() => shading.destroy()).not.toThrow();
  });
});

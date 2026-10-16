/**
 * Price levels: the previous session's close, the session high and low, the last
 * price, extended hours and the quote, each one a line plus an axis label that
 * toggle independently.
 *
 * The fixture is a US session on purpose. It runs 14:30 to 20:30 UTC, so IST
 * midnight (18:30 UTC) falls in the middle of it: any rule that cut the day at a
 * calendar midnight would report a different previous close and a different
 * session high, which is exactly the defect fixed in 1.2.0.
 */
import { describe, it, expect } from 'vitest';
import {
  PriceLevels, computePriceLevels, lastPriceLevelFromSeriesStyle, seriesStyleForLastPriceLevel,
  PRICE_LEVEL_KINDS,
  type PriceLevelKind, type PriceLevelStyle, type PriceLevelsOptions, type MarketPhase,
} from '../src/primitives/price-levels';
import { Chart } from '../src/core/chart';
import { darkTheme } from '../src/theme';
import { makeCtx } from './helpers/fake-ctx';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

const DAY = 86400;
const HOUR = 3600;
const HALF_HOUR = 1800;
/** 2024-01-15, a Monday, at midnight UTC. Every time below is UTC seconds. */
const MON = Date.UTC(2024, 0, 15, 0, 0, 0) / 1000;

/**
 * One regular US session: 14:30 to 20:30 UTC in 30-minute bars. Prices fall
 * through the session, which puts the session high in its first half (before
 * IST midnight), so a midnight split is visible in the high as well as in the
 * previous close.
 */
function usSession(dayOffset: number, base: number): Bar[] {
  const open = MON + dayOffset * DAY + 14.5 * HOUR;
  return Array.from({ length: 13 }, (_, i) => {
    const close = base + (12 - i) * 0.5;
    return { time: open + i * HALF_HOUR, open: close + 0.25, high: close + 0.5, low: close - 0.5, close, volume: 100 };
  });
}

// Mon Tue Wed Thu Fri, a weekend, Mon, a holiday on the Tuesday, Wed.
const DAYS = [0, 1, 2, 3, 4, 7, 9];
const sessions = DAYS.map((d, s) => usSession(d, 100 + s * 10));
const usBars: Bar[] = sessions.flat();

/** Time of bar `i` in session `s`, for anchoring a viewport. */
const at = (s: number, i: number): number => sessions[s][i].time;
/** Session `s` closed here, opened 6.0 above it, and ranged over [-0.5, +6.5]. */
const base = (s: number): number => 100 + s * 10;

describe('previous session close', () => {
  it('reaches back over a weekend gap', () => {
    // Viewport inside Monday the 22nd: the previous session is Friday the 19th.
    const v = computePriceLevels({ bars: usBars, anchorTime: at(5, 6) });
    expect(v.previousClose).toBe(base(4));
  });

  it('reaches back over a holiday gap', () => {
    // Viewport inside Wednesday the 24th; the Tuesday never traded.
    const v = computePriceLevels({ bars: usBars, anchorTime: at(6, 6) });
    expect(v.previousClose).toBe(base(5));
  });

  it('reads the session break from the bars, not from a calendar midnight', () => {
    const ist = computePriceLevels({ bars: usBars, anchorTime: at(5, 12) });
    const ny = computePriceLevels({ bars: usBars, anchorTime: at(5, 12), timezone: 'America/New_York' });
    // The gaps decide, so the zone cannot change a single level.
    expect(ist).toEqual(ny);
    // 18:30 UTC is midnight in IST and lands on bar 8 of this session. Cutting
    // there would make "the previous session" the first half of this one, whose
    // last close is 152.5, and would shrink the session high to 154.5.
    expect(ist.previousClose).toBe(base(4));
    expect(ist.previousClose).not.toBe(152.5);
    expect(ist.sessionHigh).toBe(base(5) + 6.5);
    expect(ist.sessionHigh).not.toBe(base(5) + 4.5);
  });

  it('has no previous close in the first session, and says so with null', () => {
    const v = computePriceLevels({ bars: usBars, anchorTime: at(0, 3) });
    expect(v.previousClose).toBeNull();
    // The rest of the family is unaffected: only the level without data is out.
    expect(v.sessionHigh).toBe(base(0) + 6.5);
  });

  it('walks back over an untraded tail rather than blanking the level', () => {
    const bars = usBars.map((b) => ({ ...b }));
    const lastOfFriday = usBars.indexOf(sessions[4][12]);
    bars[lastOfFriday] = { ...bars[lastOfFriday], open: NaN, high: NaN, low: NaN, close: NaN };
    bars[lastOfFriday - 1] = { ...bars[lastOfFriday - 1], open: NaN, high: NaN, low: NaN, close: NaN };
    const v = computePriceLevels({ bars, anchorTime: at(5, 6) });
    expect(v.previousClose).toBe(base(4) + 1); // bar 10, the last one that traded
  });

  it('treats each bar of a daily series as its own session', () => {
    // No readable intraday break, so the calendar fallback decides: the only
    // answer available for daily bars, and the right one.
    const daily = Array.from({ length: 5 }, (_, i) => (
      { time: MON + i * DAY, open: 10 + i, high: 12 + i, low: 9 + i, close: 11 + i }
    ));
    const v = computePriceLevels({ bars: daily, anchorTime: daily[3].time });
    expect(v.previousClose).toBe(13);
    expect(v.sessionHigh).toBe(15);
    expect(v.sessionLow).toBe(12);
  });
});

describe('session high and low', () => {
  it('tracks the session in view and not the whole dataset', () => {
    const v = computePriceLevels({ bars: usBars, anchorTime: at(5, 6) });
    expect(v.sessionHigh).toBe(base(5) + 6.5);
    expect(v.sessionLow).toBe(base(5) - 0.5);
    // The dataset's own extremes are elsewhere entirely.
    const datasetHigh = Math.max(...usBars.map((b) => b.high));
    const datasetLow = Math.min(...usBars.map((b) => b.low));
    expect(datasetHigh).toBe(base(6) + 6.5);
    expect(datasetLow).toBe(base(0) - 0.5);
    expect(v.sessionHigh).not.toBe(datasetHigh);
    expect(v.sessionLow).not.toBe(datasetLow);
  });

  it('follows the viewport back through history', () => {
    for (const s of [0, 1, 2, 3, 4, 5, 6]) {
      const v = computePriceLevels({ bars: usBars, anchorTime: at(s, 4) });
      expect(v.sessionHigh).toBe(base(s) + 6.5);
      expect(v.sessionLow).toBe(base(s) - 0.5);
    }
  });

  it('anchors on the newest session when the viewport runs past the last bar', () => {
    // The usual case: a right offset puts the viewport edge in empty space.
    const beyond = usBars[usBars.length - 1].time + 5 * DAY;
    const v = computePriceLevels({ bars: usBars, anchorTime: beyond });
    expect(v.sessionHigh).toBe(base(6) + 6.5);
    expect(v.previousClose).toBe(base(5));
  });

  it('has no session at all when the viewport sits before the data', () => {
    const v = computePriceLevels({ bars: usBars, anchorTime: usBars[0].time - DAY });
    expect(v.sessionHigh).toBeNull();
    expect(v.sessionLow).toBeNull();
    expect(v.previousClose).toBeNull();
    // The last trade is not a property of the viewport.
    expect(v.lastPrice).toBe(base(6));
  });

  it('keeps the last price fixed while the viewport moves', () => {
    expect(computePriceLevels({ bars: usBars, anchorTime: at(2, 0) }).lastPrice).toBe(base(6));
    expect(computePriceLevels({ bars: usBars, anchorTime: at(6, 12) }).lastPrice).toBe(base(6));
  });

  it('returns nothing but the quote when there are no bars', () => {
    const v = computePriceLevels({ bars: [], quote: { bid: 99, ask: 101 } });
    expect(v.lastPrice).toBeNull();
    expect(v.sessionHigh).toBeNull();
    expect(v.bid).toBe(99);
    expect(v.ask).toBe(101);
  });
});

describe('extended hours', () => {
  /** 13:00-14:30 pre, 14:30-21:00 regular, 21:00 onward post (UTC). */
  const phase = (bar: Bar): MarketPhase => {
    const secondsIntoDay = ((bar.time % DAY) + DAY) % DAY;
    if (secondsIntoDay < 14.5 * HOUR) return 'pre';
    if (secondsIntoDay >= 21 * HOUR) return 'post';
    return 'regular';
  };

  /** A session with three pre-market bars before it and two post after. */
  function extendedDay(dayOffset: number, b: number): Bar[] {
    const midnight = MON + dayOffset * DAY;
    const flat = (time: number, open: number, close: number): Bar => (
      { time, open, high: Math.max(open, close) + 0.5, low: Math.min(open, close) - 0.5, close }
    );
    return [
      flat(midnight + 13 * HOUR, b - 5, b - 4),
      flat(midnight + 13.5 * HOUR, b - 4, b - 3),
      flat(midnight + 14 * HOUR, b - 3, b - 2),
      ...usSession(dayOffset, b),
      flat(midnight + 21 * HOUR, b + 8, b + 9),
      flat(midnight + 21.5 * HOUR, b + 9, b + 10),
    ];
  }
  const extBars = [...extendedDay(0, 100), ...extendedDay(1, 200)];

  it('reads the four levels off the session in view when a host classifies the bars', () => {
    const v = computePriceLevels({ bars: extBars, anchorTime: MON + DAY + 16 * HOUR, marketPhase: phase });
    expect(v.preMarketOpen).toBe(195);
    expect(v.preMarketClose).toBe(198);
    expect(v.postMarketOpen).toBe(208);
    expect(v.postMarketClose).toBe(210);
    // Yesterday's extended hours belong to yesterday's session.
    const prev = computePriceLevels({ bars: extBars, anchorTime: MON + 16 * HOUR, marketPhase: phase });
    expect(prev.preMarketOpen).toBe(95);
    expect(prev.postMarketClose).toBe(110);
  });

  it('stays inert with no classifier rather than inventing a phase', () => {
    const v = computePriceLevels({ bars: extBars, anchorTime: MON + DAY + 16 * HOUR });
    expect(v.preMarketOpen).toBeNull();
    expect(v.preMarketClose).toBeNull();
    expect(v.postMarketOpen).toBeNull();
    expect(v.postMarketClose).toBeNull();
    // The levels that the bars *can* answer are unaffected.
    expect(v.sessionHigh).not.toBeNull();
  });

  it('leaves them inert for an instrument whose bars are all regular hours', () => {
    const v = computePriceLevels({ bars: usBars, anchorTime: at(6, 6), marketPhase: () => 'regular' });
    expect(v.preMarketOpen).toBeNull();
    expect(v.postMarketClose).toBeNull();
  });
});

describe('bid and ask', () => {
  it('come from the quote and are null without one', () => {
    const none = computePriceLevels({ bars: usBars, anchorTime: at(6, 6) });
    expect(none.bid).toBeNull();
    expect(none.ask).toBeNull();
    const quoted = computePriceLevels({ bars: usBars, anchorTime: at(6, 6), quote: { bid: 159.9, ask: 160.1 } });
    expect(quoted.bid).toBe(159.9);
    expect(quoted.ask).toBe(160.1);
  });

  it('take one side at a time', () => {
    const v = computePriceLevels({ bars: usBars, anchorTime: at(6, 6), quote: { bid: 159.9 } });
    expect(v.bid).toBe(159.9);
    expect(v.ask).toBeNull();
  });
});

/**
 * A render context whose price scale puts price 0 at y = 250 media px, well
 * inside a 300 px plot. A level that fell back to zero instead of drawing
 * nothing would therefore leave a line across the middle, which is what the
 * "no data" tests below check for.
 */
function makeRc(bars: readonly Bar[], anchorTime: number): PrimitiveRenderContext {
  return {
    dpr: 2,
    plotWidth: 600,
    plotHeight: 300,
    priceAxisWidth: 60,
    timeScale: { visibleRange: () => ({ from: 0, to: 100 }) },
    dataLayer: { indexToTimeFloat: () => anchorTime },
    priceScale: { priceToY: (p: number) => 250 - p, format: (p: number) => p.toFixed(2) },
    theme: darkTheme,
    bars: () => bars,
  } as unknown as PrimitiveRenderContext;
}

/** Bitmap y the primitive draws a level at, for the scale in `makeRc`. */
const yOf = (price: number): number => Math.round((250 - price) * 2) + 0.5;

/** Options with every level off except `kind`, so one level is under test. */
function only(kind: PriceLevelKind, style: Partial<PriceLevelStyle>): PriceLevelsOptions {
  const levels: Partial<Record<PriceLevelKind, Partial<PriceLevelStyle>>> = {};
  for (const k of PRICE_LEVEL_KINDS) levels[k] = { line: false, label: false };
  levels[kind] = { ...levels[kind], ...style };
  return { levels };
}

describe('PriceLevels primitive', () => {
  it('draws nothing for a level with no data, and nothing at zero', () => {
    const levels = new PriceLevels(only('bid', { line: true, label: true }));
    const first = makeCtx();
    levels.draw(first.ctx, makeRc(usBars, at(6, 6)));
    expect(levels.available('bid')).toBe(false);
    expect(first.rec.count('stroke')).toBe(0);
    expect(first.rec.count('fillRect')).toBe(0);
    expect(first.rec.count('fillText')).toBe(0);
    expect(first.rec.ops.some((o) => o.type === 'moveTo' && o.args[1] === yOf(0))).toBe(false);

    // The same level draws the moment the quote arrives: inert, not dead.
    levels.setQuote({ bid: 155 });
    const second = makeCtx();
    levels.draw(second.ctx, makeRc(usBars, at(6, 6)));
    expect(levels.available('bid')).toBe(true);
    expect(second.rec.count('stroke')).toBe(1);
    expect(second.rec.ops.some((o) => o.type === 'moveTo' && o.args[1] === yOf(155))).toBe(true);
  });

  it('accepts the quote as a callback read each frame', () => {
    let bid = 155;
    const levels = new PriceLevels({ ...only('bid', { line: true, label: false }), quote: () => ({ bid }) });
    const first = makeCtx();
    levels.draw(first.ctx, makeRc(usBars, at(6, 6)));
    expect(first.rec.ops.some((o) => o.type === 'moveTo' && o.args[1] === yOf(155))).toBe(true);
    bid = 151;
    const second = makeCtx();
    levels.draw(second.ctx, makeRc(usBars, at(6, 6)));
    expect(second.rec.ops.some((o) => o.type === 'moveTo' && o.args[1] === yOf(151))).toBe(true);
  });

  it('skips only the level without data, not the frame', () => {
    // Anchored in the first session: there is no previous close, but the
    // session high in the same group is drawn.
    const levels = new PriceLevels({
      levels: {
        ...only('previousClose', { line: true, label: false }).levels,
        sessionHigh: { line: true, label: false },
      },
    });
    const { ctx, rec } = makeCtx();
    levels.draw(ctx, makeRc(usBars, at(0, 3)));
    expect(levels.available('previousClose')).toBe(false);
    expect(levels.available('sessionHigh')).toBe(true);
    expect(rec.count('stroke')).toBe(1);
    expect(rec.ops.some((o) => o.type === 'moveTo' && o.args[1] === yOf(base(0) + 6.5))).toBe(true);
  });

  it('toggles line and label independently', () => {
    const cases = [
      { line: true, label: false, strokes: 1, tags: 0 },
      { line: false, label: true, strokes: 0, tags: 1 },
      { line: true, label: true, strokes: 1, tags: 1 },
      { line: false, label: false, strokes: 0, tags: 0 },
    ];
    for (const c of cases) {
      const levels = new PriceLevels(only('previousClose', { line: c.line, label: c.label }));
      const { ctx, rec } = makeCtx();
      levels.draw(ctx, makeRc(usBars, at(6, 6)));
      expect(levels.values().previousClose).toBe(base(5));
      expect(rec.count('stroke')).toBe(c.strokes);
      expect(rec.count('fillRect')).toBe(c.tags);
      expect(rec.count('fillText')).toBe(c.tags);
    }
  });

  it('toggles one half of a level without disturbing the other', () => {
    const levels = new PriceLevels(only('previousClose', { line: true, label: true }));
    levels.setLevel('previousClose', { label: false });
    expect(levels.level('previousClose').line).toBe(true);
    expect(levels.level('previousClose').label).toBe(false);
    levels.setLevel('previousClose', { line: false, label: true });
    expect(levels.level('previousClose').line).toBe(false);
    expect(levels.level('previousClose').label).toBe(true);
  });

  it('labels the axis with the formatted price unless given text', () => {
    const plain = new PriceLevels(only('previousClose', { line: false, label: true }));
    const first = makeCtx();
    plain.draw(first.ctx, makeRc(usBars, at(6, 6)));
    expect(first.rec.ops.find((o) => o.type === 'fillText')?.text).toBe('150.00');

    const named = new PriceLevels(only('previousClose', { line: false, label: true, text: 'PDC' }));
    const second = makeCtx();
    named.draw(second.ctx, makeRc(usBars, at(6, 6)));
    expect(second.rec.ops.find((o) => o.type === 'fillText')?.text).toBe('PDC');
  });

  it('skips a level that scrolls off the plot', () => {
    const levels = new PriceLevels(only('bid', { line: true, label: true }));
    levels.setQuote({ bid: 400 }); // above the top of this scale
    const { ctx, rec } = makeCtx();
    levels.draw(ctx, makeRc(usBars, at(6, 6)));
    expect(levels.available('bid')).toBe(true); // it has a value, it is just not on screen
    expect(rec.count('stroke')).toBe(0);
    expect(rec.count('fillRect')).toBe(0);
  });

  it('defaults previous close on and every other level off', () => {
    const levels = new PriceLevels();
    // Previous close is the level an intraday chart is routinely read against,
    // and it sits away from the current price rather than on top of it.
    expect(levels.level('previousClose').line).toBe(true);
    expect(levels.level('previousClose').label).toBe(true);

    // Session high and low were on too, and the three together drew a cluster of
    // dashed lines within a few points of the last price. A level nobody asked
    // for is clutter, so they are opt-in. The core already draws the last price
    // from the series style, and the rest need data a host has to supply.
    for (const kind of [
      'sessionHigh', 'sessionLow', 'lastPrice', 'preMarketOpen', 'postMarketClose', 'bid', 'ask',
    ] as const) {
      expect(levels.level(kind).line).toBe(false);
      expect(levels.level(kind).label).toBe(false);
    }
  });

  it('reports every level as unavailable before the first frame', () => {
    const levels = new PriceLevels();
    for (const kind of PRICE_LEVEL_KINDS) expect(levels.available(kind)).toBe(false);
  });
});

describe('last price, shared with the series style', () => {
  it('reads the two series flags as one level group', () => {
    expect(lastPriceLevelFromSeriesStyle({})).toEqual({ line: true, label: true });
    expect(lastPriceLevelFromSeriesStyle({ priceLineVisible: false })).toEqual({ line: false, label: true });
    expect(lastPriceLevelFromSeriesStyle({ lastValueVisible: false })).toEqual({ line: true, label: false });
  });

  it('writes a level group back to the series flags', () => {
    expect(seriesStyleForLastPriceLevel({ line: false, label: true }))
      .toEqual({ priceLineVisible: false, lastValueVisible: true });
    // Round trip: what the series says is what the group says.
    const style = { priceLineVisible: false, lastValueVisible: true };
    expect(seriesStyleForLastPriceLevel(lastPriceLevelFromSeriesStyle(style))).toEqual(style);
  });

  it('draws the last price only when the host takes the level over', () => {
    const off = new PriceLevels();
    const first = makeCtx();
    off.draw(first.ctx, makeRc(usBars, at(6, 6)));
    // Available (the value is known) but not drawn, because the pane draws it.
    expect(off.available('lastPrice')).toBe(true);
    expect(first.rec.ops.some((o) => o.type === 'moveTo' && o.args[1] === yOf(base(6)))).toBe(false);

    const on = new PriceLevels(only('lastPrice', lastPriceLevelFromSeriesStyle({})));
    const second = makeCtx();
    on.draw(second.ctx, makeRc(usBars, at(6, 6)));
    expect(second.rec.ops.some((o) => o.type === 'moveTo' && o.args[1] === yOf(base(6)))).toBe(true);
  });
});

/**
 * A chart that paints synchronously and has been sized, so the price scale is
 * measured rather than sitting on its 0..1 placeholder.
 */
function makeChart(): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(),
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  return chart;
}

describe('on a real chart', () => {
  it('computes its levels from the pane it is attached to', () => {
    const chart = makeChart();
    const levels = new PriceLevels();
    chart.addPrimitive(levels, 0);
    const series = chart.addSeries('candlestick');
    series.setData(usBars);

    // The viewport sits at the right edge, so the session in view is the last.
    expect(levels.values().sessionHigh).toBe(base(6) + 6.5);
    expect(levels.values().sessionLow).toBe(base(6) - 0.5);
    expect(levels.values().previousClose).toBe(base(5));
    expect(levels.values().lastPrice).toBe(base(6));
    expect(levels.available('bid')).toBe(false);
    expect(levels.available('preMarketOpen')).toBe(false);
  });

  it('follows the viewport when the chart is scrolled back', () => {
    const chart = makeChart();
    const levels = new PriceLevels();
    chart.addPrimitive(levels, 0);
    const series = chart.addSeries('candlestick');
    series.setData(usBars);
    // Put the right edge on the last bar of the second session.
    const to = usBars.findIndex((b) => b.time === at(1, 12));
    chart.timeScale.setVisibleLogicalRange({ from: to - 12, to });

    expect(levels.values().sessionHigh).toBe(base(1) + 6.5);
    expect(levels.values().previousClose).toBe(base(0));
  });
});

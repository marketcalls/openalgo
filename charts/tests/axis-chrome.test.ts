/**
 * Axis chrome: the bar-close countdown, the crosshair's date pill, the corner
 * session clock, and price-axis overlap suppression.
 *
 * Two things have to hold at once, and both are pinned below:
 *
 *  1. A chart that configures none of it draws exactly the axes it drew before
 *     the chrome existed, op for op. That is the regression that matters most,
 *     so the default op streams are written out literally rather than compared
 *     against another run of the same code.
 *  2. Every live piece runs off an injected clock. `Date.now()` is spied on and
 *     asserted never to be called: a renderer that reached for the global clock
 *     could not be tested, replayed, or corrected against an exchange feed.
 */
import { describe, it, expect, vi } from 'vitest';
import { PriceScale } from '../src/scale/price-scale';
import {
  AXIS_LABEL_PRIORITY, AXIS_TAG_HEIGHT, AXIS_TAG_HEIGHT_COUNTDOWN,
  barCountdownSeconds, drawLastPriceLine, drawLastPriceTag, drawPriceAxis,
  drawSessionClock, drawTimeAxisPill, formatCountdown, formatUtcOffset,
  lastPriceTagHeight, medianBarInterval, priceTickCount, resolveAxisLabels,
  type AxisLabelBand, type BarTimeSource, type LastPriceTagOptions, type PlotLayout,
} from '../src/render/axis';
import { makeCtx, type Op, type RecordingContext } from './helpers/fake-ctx';
import { Chart, type AxisChromeOptions } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';

const LAYOUT: PlotLayout = {
  plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, timeAxisHeight: 22, plotLeft: 0,
};

/** A measured linear scale: 400px of pane over 90..110, so 100 sits at y=200. */
function scale(): PriceScale {
  const ps = new PriceScale();
  ps.setHeight(400);
  ps.setPriceRange({ min: 90, max: 110 });
  return ps;
}

const texts = (rec: RecordingContext): (string | undefined)[] =>
  rec.ops.filter((o) => o.type === 'fillText').map((o) => o.text);

/**
 * The rungs the axis labels: a label within half a tag of the pane's top or
 * bottom edge would be cut by it, and is left out. On this scale the top and
 * bottom rungs sit on the edges themselves.
 */
const labelled = (ps: PriceScale, height = LAYOUT.plotHeight): number[] =>
  ps.ticks(priceTickCount(height)).filter((p) => {
    const y = Math.round(ps.priceToY(p));
    return y >= AXIS_TAG_HEIGHT / 2 && y <= height - AXIS_TAG_HEIGHT / 2;
  });

const ofType = (rec: RecordingContext, type: string): Op[] => rec.ops.filter((o) => o.type === type);

/** UTC seconds for a UTC wall clock. */
const utc = (y: number, mo: number, d: number, h = 0, mi = 0, s = 0): number =>
  Math.floor(Date.UTC(y, mo - 1, d, h, mi, s) / 1000);

/** A `DataLayer`-shaped reader over a plain list of bar times. */
function timeSource(times: readonly number[]): BarTimeSource {
  return { indexToTime: (i: number) => times[i], baseIndex: times.length - 1 };
}

/**
 * Run `body` with `Date.now` poisoned. Every clock in this file is injected, so
 * a renderer touching the global one is a defect, not a style preference.
 */
function withNoGlobalClock(body: () => void): void {
  const now = vi.spyOn(Date, 'now');
  try {
    body();
    expect(now).not.toHaveBeenCalled();
  } finally {
    now.mockRestore();
  }
}

// ---------------------------------------------------------------------------

describe('bar countdown maths', () => {
  const OPEN = utc(2026, 5, 21, 3, 45); // 09:15 IST, a five-minute bar
  const FIVE_MIN = 300;

  it('counts down through the bar it is inside', () => {
    expect(barCountdownSeconds(OPEN, FIVE_MIN, OPEN)).toBe(300);
    expect(barCountdownSeconds(OPEN, FIVE_MIN, OPEN + 1)).toBe(299);
    expect(barCountdownSeconds(OPEN, FIVE_MIN, OPEN + 240)).toBe(60);
    expect(barCountdownSeconds(OPEN, FIVE_MIN, OPEN + 299)).toBe(1);
  });

  it('rolls into the next bar at the exact instant of a close', () => {
    // Not zero and not negative: the bar that closed is gone and a new one has
    // just opened, so a full interval is the honest reading even before the
    // feed delivers its first tick.
    expect(barCountdownSeconds(OPEN, FIVE_MIN, OPEN + 300)).toBe(300);
    expect(formatCountdown(barCountdownSeconds(OPEN, FIVE_MIN, OPEN + 300))).toBe('00:05:00');
  });

  it('keeps running while the feed is late with the new bar', () => {
    expect(barCountdownSeconds(OPEN, FIVE_MIN, OPEN + 301)).toBe(299);
    expect(barCountdownSeconds(OPEN, FIVE_MIN, OPEN + 599)).toBe(1);
    expect(barCountdownSeconds(OPEN, FIVE_MIN, OPEN + 600)).toBe(300);
    expect(barCountdownSeconds(OPEN, FIVE_MIN, OPEN + 3000)).toBe(300);
  });

  it('gives a clock running behind the bar the longer answer, not a wrapped one', () => {
    // A machine five seconds slow is still 305s from this bar's close. Folding
    // it through the modulo would answer 5, i.e. an imminent close that is not.
    expect(barCountdownSeconds(OPEN, FIVE_MIN, OPEN - 5)).toBe(305);
  });

  it('has nothing to count without a readable interval', () => {
    expect(barCountdownSeconds(OPEN, 0, OPEN + 10)).toBeNull();
    expect(barCountdownSeconds(OPEN, -60, OPEN + 10)).toBeNull();
    expect(barCountdownSeconds(OPEN, Number.POSITIVE_INFINITY, OPEN + 10)).toBeNull();
    expect(barCountdownSeconds(Number.NaN, FIVE_MIN, OPEN + 10)).toBeNull();
    expect(barCountdownSeconds(OPEN, FIVE_MIN, Number.NaN)).toBeNull();
  });

  it('formats HH:MM:SS, and says so when there is nothing to count', () => {
    expect(formatCountdown(0)).toBe('00:00:00');
    expect(formatCountdown(9)).toBe('00:00:09');
    expect(formatCountdown(59)).toBe('00:00:59');
    expect(formatCountdown(60)).toBe('00:01:00');
    expect(formatCountdown(3599)).toBe('00:59:59');
    expect(formatCountdown(null)).toBe('--:--:--');
  });

  it('does not cap the hours of a daily or weekly bar', () => {
    expect(formatCountdown(86400)).toBe('24:00:00');
    expect(formatCountdown(7 * 86400)).toBe('168:00:00');
  });

  it('rounds a fractional second up, so the last second on screen is 00:00:01', () => {
    expect(formatCountdown(0.4)).toBe('00:00:01');
    expect(formatCountdown(58.2)).toBe('00:00:59');
  });
});

describe('medianBarInterval', () => {
  it('reads a one-minute cadence through an overnight gap', () => {
    const open = utc(2026, 5, 21, 3, 45);
    const day1 = Array.from({ length: 20 }, (_, i) => open + i * 60);
    const day2 = Array.from({ length: 20 }, (_, i) => open + 86400 + i * 60);
    expect(medianBarInterval(timeSource([...day1, ...day2]))).toBe(60);
  });

  it('is not halved by a single tighter gap the way a minimum would be', () => {
    const open = utc(2026, 5, 21, 3, 45);
    const times = Array.from({ length: 20 }, (_, i) => open + i * 60);
    times.splice(10, 0, times[9] + 5); // a backfilled duplicate, five seconds on
    expect(medianBarInterval(timeSource(times))).toBe(60);
  });

  it('follows a timeframe switch within the sample window', () => {
    const open = utc(2026, 5, 21, 3, 45);
    const old = Array.from({ length: 100 }, (_, i) => open + i * 60);
    const now = Array.from({ length: 40 }, (_, i) => old[99] + (i + 1) * 300);
    expect(medianBarInterval(timeSource([...old, ...now]))).toBe(300);
  });

  it('says nothing when there is nothing to read', () => {
    expect(medianBarInterval(timeSource([]))).toBe(0);
    expect(medianBarInterval(timeSource([1000]))).toBe(0);
    expect(medianBarInterval(timeSource([1000, 1000, 1000]))).toBe(0);
  });
});

describe('countdown row in the last-price tag', () => {
  const OPEN = utc(2026, 5, 21, 3, 45);

  /** Draw the tag only (no price line) so the op stream is just the tag. */
  function tag(countdown?: LastPriceTagOptions['countdown']): RecordingContext {
    const { ctx, rec } = makeCtx();
    drawLastPriceTag(ctx, scale(), 100, true, LAYOUT, 1, undefined, { countdown });
    return rec;
  }

  it('leaves the tag exactly one line when the option is unset or off', () => {
    const off = tag();
    const explicitlyOff = tag({ visible: false, now: () => OPEN, lastBarTime: OPEN, intervalSec: 300 });
    expect(texts(off)).toEqual(['100.0']);
    expect(ofType(off, 'fillRect')[0].args[3]).toBe(AXIS_TAG_HEIGHT);
    expect(explicitlyOff.ops).toEqual(off.ops);
  });

  it('adds the countdown under the price when the option is on', () => {
    const rec = tag({ visible: true, now: () => OPEN + 41, lastBarTime: OPEN, intervalSec: 300 });
    expect(texts(rec)).toEqual(['100.0', '00:04:19']);
  });

  it('grows the tag to two rows and keeps the price on the price line', () => {
    const rec = tag({ visible: true, now: () => OPEN, lastBarTime: OPEN, intervalSec: 300 });
    const box = ofType(rec, 'fillRect')[0];
    // y=200 is where the scale puts 100.00; the box straddles it, one row either side.
    expect(box.args[1]).toBe(200 - AXIS_TAG_HEIGHT_COUNTDOWN / 2);
    expect(box.args[3]).toBe(AXIS_TAG_HEIGHT_COUNTDOWN);
    const rows = ofType(rec, 'fillText');
    expect(rows.map((o) => o.args[1])).toEqual([193, 207]);
    expect(rows.map((o) => o.args[0])).toEqual([607, 607]);
  });

  it('widens the tag to the wider of the two rows', () => {
    // measureText is 6px per character here: '100.0' is 30, '00:04:19' is 48.
    const rec = tag({ visible: true, now: () => OPEN + 41, lastBarTime: OPEN, intervalSec: 300 });
    expect(ofType(rec, 'fillRect')[0].args[2]).toBe(48 + 12);
    expect(ofType(tag(), 'fillRect')[0].args[2]).toBe(30 + 12);
  });

  it('shows the row as unreadable rather than dropping it when the interval is unknown', () => {
    // The caller asked for a countdown; a row that silently vanished would read
    // as the option not having taken effect.
    const rec = tag({ visible: true, now: () => OPEN, lastBarTime: OPEN, intervalSec: 0 });
    expect(texts(rec)).toEqual(['100.0', '--:--:--']);
    expect(ofType(rec, 'fillRect')[0].args[3]).toBe(AXIS_TAG_HEIGHT_COUNTDOWN);
  });

  it('follows the injected clock and never the global one', () => {
    withNoGlobalClock(() => {
      let t = OPEN;
      const opts = { visible: true, now: () => t, lastBarTime: OPEN, intervalSec: 300 };
      const first = tag(opts);
      t = OPEN + 120;
      const later = tag(opts);
      expect(texts(first)).toEqual(['100.0', '00:05:00']);
      expect(texts(later)).toEqual(['100.0', '00:03:00']);
    });
  });

  it('reports the tag height it will use, for a caller reserving the band', () => {
    expect(lastPriceTagHeight(1)).toBe(AXIS_TAG_HEIGHT);
    expect(lastPriceTagHeight(2)).toBe(AXIS_TAG_HEIGHT * 2);
    expect(lastPriceTagHeight(2, true)).toBe(AXIS_TAG_HEIGHT_COUNTDOWN * 2);
  });
});

describe('crosshair date pill on the time axis', () => {
  const LABEL = "Wed 21 May '26 09:15"; // 20 chars, so 120px of text here
  const STYLE = { background: '#3d4a63', textColor: '#e8ecf4' };

  it('fills a rounded background before it draws the text', () => {
    const { ctx, rec } = makeCtx();
    drawTimeAxisPill(ctx, LABEL, 300, 400, 1, STYLE);
    const kinds = rec.ops.map((o) => o.type);
    expect(kinds.indexOf('roundRect')).toBeGreaterThanOrEqual(0);
    expect(kinds.indexOf('fill')).toBeGreaterThan(kinds.indexOf('roundRect'));
    expect(kinds.indexOf('fillText')).toBeGreaterThan(kinds.indexOf('fill'));
  });

  it('sizes the background around the text and centres the label in it', () => {
    const { ctx, rec } = makeCtx();
    drawTimeAxisPill(ctx, LABEL, 300, 400, 1, STYLE);
    const [x, y, w, h, r] = ofType(rec, 'roundRect')[0].args;
    expect(w).toBe(120 + 14); // text + 7px padding either side
    expect(x).toBe(300 - w / 2);
    expect(y).toBe(401); // one px clear of the axis separator
    expect(h).toBe(18);
    expect(r).toBe(4);
    const text = ofType(rec, 'fillText')[0];
    expect(text.args).toEqual([x + w / 2, y + h / 2]);
    // The background genuinely covers the label rather than sitting beside it.
    expect(text.args[0] - 60).toBeGreaterThanOrEqual(x);
    expect(text.args[0] + 60).toBeLessThanOrEqual(x + w);
  });

  it('takes its fill and its text colour from the theme', () => {
    const { ctx, rec } = makeCtx();
    drawTimeAxisPill(ctx, LABEL, 300, 400, 1, { background: '#c9d3e4', textColor: '#10131a' });
    expect(ofType(rec, 'fill')[0].fillStyle).toBe('#c9d3e4');
    expect(ofType(rec, 'fillText')[0].fillStyle).toBe('#10131a');
  });

  it('lays an opaque backplate under a translucent fill when asked', () => {
    const { ctx, rec } = makeCtx();
    drawTimeAxisPill(ctx, LABEL, 300, 400, 1, { ...STYLE, background: 'rgba(61,74,99,0.7)', backplate: '#0d0e12' });
    expect(ofType(rec, 'fill').map((o) => o.fillStyle)).toEqual(['#0d0e12', 'rgba(61,74,99,0.7)']);
  });

  it('outlines the pill only when a border colour is given', () => {
    const plain = makeCtx();
    drawTimeAxisPill(plain.ctx, LABEL, 300, 400, 1, STYLE);
    expect(plain.rec.count('stroke')).toBe(0);
    const bordered = makeCtx();
    drawTimeAxisPill(bordered.ctx, LABEL, 300, 400, 1, { ...STYLE, border: '#5a6480' });
    expect(ofType(bordered.rec, 'stroke')[0].strokeStyle).toBe('#5a6480');
  });

  it('clamps at the left edge instead of running the date off the canvas', () => {
    const { ctx, rec } = makeCtx();
    drawTimeAxisPill(ctx, LABEL, 10, 400, 1, STYLE);
    expect(ofType(rec, 'roundRect')[0].args[0]).toBe(0);
  });

  it('scales its box with the device pixel ratio', () => {
    const { ctx, rec } = makeCtx();
    drawTimeAxisPill(ctx, LABEL, 600, 800, 2, STYLE);
    const [, y, , h] = ofType(rec, 'roundRect')[0].args;
    expect(h).toBe(36);
    expect(y).toBe(802);
  });
});

describe('session clock', () => {
  const T = utc(2026, 5, 21, 3, 45, 7); // 09:15:07 IST

  it('draws nothing at all unless it is switched on', () => {
    const unset = makeCtx();
    drawSessionClock(unset.ctx, LAYOUT, 1, { now: () => T });
    expect(unset.rec.ops).toEqual([]);
    const off = makeCtx();
    drawSessionClock(off.ctx, LAYOUT, 1, { visible: false, now: () => T });
    expect(off.rec.ops).toEqual([]);
  });

  it('reads the shipped default zone, with its offset under it', () => {
    withNoGlobalClock(() => {
      const { ctx, rec } = makeCtx();
      drawSessionClock(ctx, LAYOUT, 1, { visible: true, now: () => T });
      expect(texts(rec)).toEqual(['09:15:07', 'UTC+5:30']);
    });
  });

  it('sits in the corner where the price axis meets the time axis', () => {
    const { ctx, rec } = makeCtx();
    drawSessionClock(ctx, LAYOUT, 1, { visible: true, now: () => T });
    const rows = ofType(rec, 'fillText');
    // Centred in the 56px price-axis strip that starts at the 600px plot edge.
    expect(rows.map((o) => o.args[0])).toEqual([628, 628]);
    // Both rows inside the 22px time-axis strip below the plot.
    for (const row of rows) {
      expect(row.args[1]).toBeGreaterThan(400);
      expect(row.args[1]).toBeLessThan(422);
    }
    expect(rows[0].args[1]).toBeLessThan(rows[1].args[1]);
  });

  it('reads a named zone, and follows it through a DST changeover', () => {
    const summer = makeCtx();
    drawSessionClock(summer.ctx, LAYOUT, 1, {
      visible: true, now: () => utc(2026, 7, 15, 13, 30), timezone: 'America/New_York',
    });
    expect(texts(summer.rec)).toEqual(['09:30:00', 'UTC-4']);

    const winter = makeCtx();
    drawSessionClock(winter.ctx, LAYOUT, 1, {
      visible: true, now: () => utc(2026, 1, 15, 14, 30), timezone: 'America/New_York',
    });
    expect(texts(winter.rec)).toEqual(['09:30:00', 'UTC-5']);
  });

  it('falls back to the default zone rather than throwing on a name it cannot resolve', () => {
    const { ctx, rec } = makeCtx();
    expect(() => drawSessionClock(ctx, LAYOUT, 1, {
      visible: true, now: () => T, timezone: 'Mars/Olympus_Mons',
    })).not.toThrow();
    expect(texts(rec)).toEqual(['09:15:07', 'UTC+5:30']);
  });

  it('drops to the clock alone when the offset is unwanted or will not fit', () => {
    const noOffset = makeCtx();
    drawSessionClock(noOffset.ctx, LAYOUT, 1, { visible: true, now: () => T, showOffset: false });
    expect(texts(noOffset.rec)).toEqual(['09:15:07']);

    const shortStrip = makeCtx();
    drawSessionClock(shortStrip.ctx, { ...LAYOUT, timeAxisHeight: 14 }, 1, { visible: true, now: () => T });
    expect(texts(shortStrip.rec)).toEqual(['09:15:07']);
  });

  it('has no corner to draw in when the axes are hidden', () => {
    const noTimeAxis = makeCtx();
    drawSessionClock(noTimeAxis.ctx, { ...LAYOUT, timeAxisHeight: 0 }, 1, { visible: true, now: () => T });
    expect(noTimeAxis.rec.ops).toEqual([]);
    const noPriceAxis = makeCtx();
    drawSessionClock(noPriceAxis.ctx, { ...LAYOUT, priceAxisWidth: 0 }, 1, { visible: true, now: () => T });
    expect(noPriceAxis.rec.ops).toEqual([]);
  });

  it('ticks with the injected clock and never the global one', () => {
    withNoGlobalClock(() => {
      let t = T;
      const opts = { visible: true, now: () => t };
      const first = makeCtx();
      drawSessionClock(first.ctx, LAYOUT, 1, opts);
      t = T + 3600;
      const later = makeCtx();
      drawSessionClock(later.ctx, LAYOUT, 1, opts);
      expect(texts(first.rec)).toEqual(['09:15:07', 'UTC+5:30']);
      expect(texts(later.rec)).toEqual(['10:15:07', 'UTC+5:30']);
    });
  });

  it('survives a clock that answers with nothing usable', () => {
    const { ctx, rec } = makeCtx();
    drawSessionClock(ctx, LAYOUT, 1, { visible: true, now: () => Number.NaN });
    expect(rec.ops).toEqual([]);
  });

  it('writes an offset the way a desk writes it', () => {
    expect(formatUtcOffset(0)).toBe('UTC');
    expect(formatUtcOffset(5.5 * 3600)).toBe('UTC+5:30');
    expect(formatUtcOffset(-4 * 3600)).toBe('UTC-4');
    expect(formatUtcOffset(-3.5 * 3600)).toBe('UTC-3:30');
    expect(formatUtcOffset(13 * 3600)).toBe('UTC+13');
    expect(formatUtcOffset(5.75 * 3600)).toBe('UTC+5:45');
  });
});

describe('price-axis label overlap suppression', () => {
  const band = (y: number, priority: number, height = 16): AxisLabelBand => ({ y, height, priority });

  it('keeps the higher-priority label and drops the one it lands on', () => {
    const bands = [band(200, AXIS_LABEL_PRIORITY.tick), band(204, AXIS_LABEL_PRIORITY.lastPrice)];
    expect(resolveAxisLabels(bands)).toEqual([false, true]);
    // Order of declaration must not decide it.
    expect(resolveAxisLabels([bands[1], bands[0]])).toEqual([true, false]);
  });

  it('leaves labels alone once they clear each other', () => {
    expect(resolveAxisLabels([band(200, 10), band(220, 90)])).toEqual([true, true]);
    // A couple of px of demanded daylight is enough to turn that around.
    expect(resolveAxisLabels([band(200, 10), band(214, 90)], 2)).toEqual([false, true]);
  });

  it('resolves a pile-up down the documented order', () => {
    const bands = [
      band(200, AXIS_LABEL_PRIORITY.tick),
      band(202, AXIS_LABEL_PRIORITY.previousClose),
      band(204, AXIS_LABEL_PRIORITY.sessionLevel),
      band(206, AXIS_LABEL_PRIORITY.priceLine),
      band(208, AXIS_LABEL_PRIORITY.lastPrice),
      band(210, AXIS_LABEL_PRIORITY.crosshair),
    ];
    expect(resolveAxisLabels(bands)).toEqual([false, false, false, false, false, true]);
    expect(AXIS_LABEL_PRIORITY.crosshair).toBeGreaterThan(AXIS_LABEL_PRIORITY.lastPrice);
    expect(AXIS_LABEL_PRIORITY.lastPrice).toBeGreaterThan(AXIS_LABEL_PRIORITY.priceLine);
    expect(AXIS_LABEL_PRIORITY.priceLine).toBeGreaterThan(AXIS_LABEL_PRIORITY.sessionLevel);
    expect(AXIS_LABEL_PRIORITY.sessionLevel).toBeGreaterThan(AXIS_LABEL_PRIORITY.previousClose);
    expect(AXIS_LABEL_PRIORITY.previousClose).toBeGreaterThan(AXIS_LABEL_PRIORITY.tick);
  });

  it('breaks a tie on declaration order, so the same frame resolves the same way', () => {
    const bands = [band(200, 70), band(203, 70), band(206, 70)];
    expect(resolveAxisLabels(bands)).toEqual([true, false, false]);
    expect(resolveAxisLabels(bands)).toEqual(resolveAxisLabels(bands));
  });

  it('a suppressed label frees nothing: the winner still owns the whole band', () => {
    // 200 wins, 210 loses to it, and 218 clears 200 so it draws even though the
    // label between them was dropped.
    expect(resolveAxisLabels([band(200, 90), band(210, 10), band(218, 10)])).toEqual([true, false, true]);
  });

  it('ignores a band with no position to occupy', () => {
    expect(resolveAxisLabels([band(Number.NaN, 90), band(200, 10)])).toEqual([false, true]);
  });

  it('drops the tick a reserved last-price tag lands on, and only that one', () => {
    const ps = scale();
    const ticks = labelled(ps);
    const all = ticks.map((p) => ps.format(p));
    const collide = ticks[2];

    const { ctx, rec } = makeCtx();
    drawPriceAxis(ctx, ps, LAYOUT, 1, undefined, [{
      y: Math.round(ps.priceToY(collide)),
      height: lastPriceTagHeight(1),
      priority: AXIS_LABEL_PRIORITY.lastPrice,
    }]);
    expect(texts(rec)).toEqual(all.filter((_, i) => i !== 2));
  });

  it('costs more of the ladder once the countdown makes the tag taller', () => {
    const ps = scale();
    const ticks = ps.ticks(priceTickCount(LAYOUT.plotHeight));
    // 22px off a tick: a one-row tag clears it and a two-row tag does not, so
    // the taller tag is the one that has to take a label down with it.
    const y = Math.round(ps.priceToY(ticks[2])) + 22;
    const drawn = (height: number): (string | undefined)[] => {
      const { ctx, rec } = makeCtx();
      drawPriceAxis(ctx, ps, LAYOUT, 1, undefined, [{ y, height, priority: AXIS_LABEL_PRIORITY.lastPrice }]);
      return texts(rec);
    };
    expect(drawn(lastPriceTagHeight(1)).length).toBeGreaterThan(drawn(lastPriceTagHeight(1, true)).length);
  });

  it('leaves the ladder whole when the reservation lands in clear air', () => {
    const ps = scale();
    const { ctx, rec } = makeCtx();
    // Midway between two rungs, derived rather than hardcoded: the ladder's
    // spacing follows the pane height, so a fixed y stops being clear air the
    // moment that density changes.
    const rungs = ps.ticks(priceTickCount(LAYOUT.plotHeight));
    const midway = (ps.priceToY(rungs[1]) + ps.priceToY(rungs[2])) / 2;
    drawPriceAxis(ctx, ps, LAYOUT, 1, undefined, [
      { y: Math.round(midway), height: 16, priority: AXIS_LABEL_PRIORITY.lastPrice },
    ]);
    expect(texts(rec)).toEqual(labelled(ps).map((p) => ps.format(p)));
  });

  it('consults the priority rather than letting any reservation win', () => {
    const ps = scale();
    const ticks = labelled(ps);
    const { ctx, rec } = makeCtx();
    drawPriceAxis(ctx, ps, LAYOUT, 1, undefined, [{
      y: Math.round(ps.priceToY(ticks[2])),
      height: 16,
      priority: AXIS_LABEL_PRIORITY.tick - 1,
    }]);
    expect(texts(rec)).toEqual(ticks.map((p) => ps.format(p)));
  });

  it('applies the same rule to a left axis', () => {
    const ps = scale();
    const ticks = labelled(ps);
    const { ctx, rec } = makeCtx();
    drawPriceAxis(ctx, ps, { ...LAYOUT, plotLeft: 60 }, 1, undefined, [{
      y: Math.round(ps.priceToY(ticks[1])),
      height: lastPriceTagHeight(1),
      priority: AXIS_LABEL_PRIORITY.lastPrice,
    }]);
    expect(texts(rec)).toEqual(ticks.map((p) => ps.format(p)).filter((_, i) => i !== 1));
  });
});

describe('a tick label at a pane edge', () => {
  /**
   * 400 px over a range nudged so the 110 rung sits `gap` px under the top
   * edge and the 90 rung `gap` px over the bottom one.
   */
  const nudged = (gap: number): PriceScale => {
    const ps = new PriceScale();
    ps.setHeight(400);
    const per = 20 / (400 - 2 * gap);
    ps.setPriceRange({ min: 90 - gap * per, max: 110 + gap * per });
    return ps;
  };
  const drawn = (ps: PriceScale, left = false, dpr = 1): (string | undefined)[] => {
    const { ctx, rec } = makeCtx();
    const layout = { ...LAYOUT, plotHeight: 400 };
    if (left) drawPriceAxis(ctx, ps, { ...layout, plotLeft: 60 }, dpr, undefined, undefined, 'left');
    else drawPriceAxis(ctx, ps, layout, dpr);
    return texts(rec);
  };

  it('is left out when the edge would cut it, top and bottom', () => {
    const ps = scale();
    // 110 sits on the top edge and 90 on the bottom one: half of each would be cut off.
    expect(Math.round(ps.priceToY(110))).toBe(0);
    expect(Math.round(ps.priceToY(90))).toBe(400);
    const labels = drawn(ps);
    expect(labels).not.toContain('110.0');
    expect(labels).not.toContain('90.0');
    expect(labels).toContain('100.0');
  });

  it('is kept once half a tag clears the edge, and left out a pixel nearer', () => {
    const clear = nudged(AXIS_TAG_HEIGHT / 2), near = nudged(AXIS_TAG_HEIGHT / 2 - 1);
    expect(Math.round(clear.priceToY(110))).toBe(8);
    expect(Math.round(clear.priceToY(90))).toBe(392);
    expect(Math.round(near.priceToY(110))).toBe(7);
    expect(Math.round(near.priceToY(90))).toBe(393);
    const kept = drawn(clear), cut = drawn(near);
    expect(kept).toContain('110.0');
    expect(kept).toContain('90.0');
    expect(cut).not.toContain('110.0');
    expect(cut).not.toContain('90.0');
    // Only the edge rungs: every other one is well clear either way.
    expect(cut.length).toBe(kept.length - 2);
  });

  it('is judged the same way on a left axis', () => {
    expect(drawn(scale(), true)).not.toContain('110.0');
    expect(drawn(scale(), true)).not.toContain('90.0');
    expect(drawn(nudged(AXIS_TAG_HEIGHT / 2), true)).toContain('110.0');
    expect(drawn(nudged(AXIS_TAG_HEIGHT / 2 - 1), true)).not.toContain('110.0');
  });

  it('keeps its margin in device pixels at a fractional pixel ratio', () => {
    // At 1.5 the rung 7 media px under the top edge is 10.5 device px down,
    // under the 12 px that half a tag takes there.
    const ps = nudged(7);
    const { ctx, rec } = makeCtx();
    drawPriceAxis(ctx, ps, { ...LAYOUT, plotHeight: 400 }, 1.5);
    expect(texts(rec)).not.toContain('110.0');
    const at8 = makeCtx();
    drawPriceAxis(at8.ctx, nudged(8), { ...LAYOUT, plotHeight: 400 }, 1.5);
    expect(texts(at8.rec)).toContain('110.0');
  });
});

// ---------------------------------------------------------------------------
// The regression that matters most: nothing configured, nothing changed.
// ---------------------------------------------------------------------------

/**
 * The font the axis sets when nothing overrides it. Pinned in the goldens
 * alongside the coordinates: text size is a chrome option now, so "unchanged"
 * has to mean the same size as well as the same string in the same place.
 */
const AXIS_FONT = '11px system-ui, sans-serif';

describe('a chart that configures no chrome draws exactly what it drew before', () => {
  it('draws the right price axis op for op', () => {
    const ps = scale();
    const { ctx, rec } = makeCtx();
    drawPriceAxis(ctx, ps, LAYOUT, 1);
    expect(rec.ops).toEqual([
      { type: 'save', args: [] },
      { type: 'beginPath', args: [] },
      { type: 'moveTo', args: [600.5, 0] },
      { type: 'lineTo', args: [600.5, 400] },
      { type: 'stroke', args: [], strokeStyle: '#2a3046', lineWidth: 1 },
      ...labelled(ps).map((p) => ({
        type: 'fillText',
        args: [606, Math.round(ps.priceToY(p))],
        fillStyle: '#8b91a7',
        text: ps.format(p),
        font: AXIS_FONT,
      })),
      { type: 'restore', args: [] },
    ]);
  });

  it('draws the left price axis op for op', () => {
    const ps = scale();
    const { ctx, rec } = makeCtx();
    drawPriceAxis(ctx, ps, { ...LAYOUT, plotLeft: 60 }, 1, undefined, undefined, 'left');
    expect(rec.ops).toEqual([
      { type: 'save', args: [] },
      { type: 'beginPath', args: [] },
      { type: 'moveTo', args: [59.5, 0] },
      { type: 'lineTo', args: [59.5, 400] },
      { type: 'stroke', args: [], strokeStyle: '#2a3046', lineWidth: 1 },
      ...labelled(ps).map((p) => ({
        type: 'fillText',
        args: [54, Math.round(ps.priceToY(p))],
        fillStyle: '#8b91a7',
        text: ps.format(p),
        font: AXIS_FONT,
      })),
      { type: 'restore', args: [] },
    ]);
  });

  it('draws the last-price line and tag op for op', () => {
    const { ctx, rec } = makeCtx();
    drawLastPriceLine(ctx, scale(), 100, true, LAYOUT, 1);
    drawLastPriceTag(ctx, scale(), 100, true, LAYOUT, 1);
    expect(rec.ops).toEqual([
      { type: 'save', args: [] },
      { type: 'setLineDash', args: [3, 3] },
      { type: 'beginPath', args: [] },
      { type: 'moveTo', args: [0, 200.5] },
      { type: 'lineTo', args: [600, 200.5] },
      { type: 'stroke', args: [], strokeStyle: '#26a69a', lineWidth: 1 },
      { type: 'setLineDash', args: [] },
      { type: 'restore', args: [] },
      { type: 'save', args: [] },
      { type: 'fillRect', args: [601, 192, 42, 16], fillStyle: '#26a69a' },
      { type: 'fillText', args: [607, 200], fillStyle: '#0d0e12', text: '100.0', font: AXIS_FONT },
      { type: 'restore', args: [] },
    ]);
  });

  it('draws a down tag in the down colour, unchanged', () => {
    const { ctx, rec } = makeCtx();
    drawLastPriceTag(ctx, scale(), 100, false, LAYOUT, 1);
    expect(ofType(rec, 'fillRect')[0].fillStyle).toBe('#ef5350');
  });

  it('leaves the axis corner empty, as it has always been', () => {
    const { ctx, rec } = makeCtx();
    drawSessionClock(ctx, LAYOUT, 1, { now: () => 0 });
    expect(rec.ops).toEqual([]);
  });

  it('reaches no global clock while drawing an unconfigured axis', () => {
    withNoGlobalClock(() => {
      const ps = scale();
      const { ctx } = makeCtx();
      drawPriceAxis(ctx, ps, LAYOUT, 1);
      drawPriceAxis(ctx, ps, { ...LAYOUT, plotLeft: 60 }, 1, undefined, undefined, 'left');
      drawLastPriceLine(ctx, ps, 100, true, LAYOUT, 1);
      drawLastPriceTag(ctx, ps, 100, true, LAYOUT, 1);
      drawSessionClock(ctx, LAYOUT, 1, { now: () => 0 });
    });
  });
});

// ---------------------------------------------------------------------------
// The pane is what has to reserve. The suppression above is only worth having
// if the engine's own tag actually claims its band: without that wiring every
// helper here is unreachable code and the tag paints over a tick label.
// ---------------------------------------------------------------------------

describe('the pane reserves the band its last-price tag will cover', () => {
  /** A chart that paints synchronously, so a frame has run on return. */
  function mount(closes: readonly number[]): Chart {
    const doc = fakeDocument();
    const el = doc.createElement('div') as unknown as HTMLElement;
    Object.assign(el, { clientWidth: 800, clientHeight: 600 });
    const chart = new Chart(el, {
      document: doc,
      pixelRatio: () => 1,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
      shortcuts: false,
      timeNavigator: false,
    });
    chart.applySize(800, 600);
    chart.addSeries('line').setData(closes.map((close, i) => ({ time: 1700000000 + i * 60, value: close })));
    return chart;
  }

  const paneRec = (chart: Chart): RecordingContext =>
    chart.panes()[0].base.ctx as unknown as RecordingContext;

  /** The tag's box: the only fillRect drawn past the plot edge. */
  function tagBox(chart: Chart): { centre: number; h: number } {
    const box = ofType(paneRec(chart), 'fillRect').find((o) => o.args[0] >= 800 - 56);
    if (box === undefined) throw new Error('no last-price tag was drawn');
    return { centre: box.args[1] + box.args[3] / 2, h: box.args[3] };
  }

  /**
   * Tick labels actually drawn, by text. Selected on the axis text colour, so
   * the tag's own label (drawn in the tag's text colour, inside the same strip)
   * is not mistaken for a tick.
   */
  const drawnTicks = (chart: Chart): string[] =>
    paneRec(chart).ops
      .filter((o) => o.type === 'fillText' && o.args[0] >= 800 - 56 && o.fillStyle === chart.theme().axisText)
      .map((o) => o.text as string);

  /** Every label the ladder asked for, before any suppression. */
  const ladder = (chart: Chart): string[] => {
    const ps = chart.panes()[0].priceScale;
    return ps.ticks(priceTickCount(LAYOUT.plotHeight)).map((p) => ps.format(p));
  };

  /** Where the ladder would have drawn a given label. */
  const yOf = (chart: Chart, label: string): number => {
    const ps = chart.panes()[0].priceScale;
    const price = ps.ticks(priceTickCount(LAYOUT.plotHeight)).find((p) => ps.format(p) === label) as number;
    return Math.round(ps.priceToY(price));
  };

  it('drops the tick labels the tag would be painted over, and only those', () => {
    // 90 to 110 autoscales to a ladder on round fives, and the last bar closes
    // exactly on one of them: the tag is then centred on a tick label, which is
    // the collision the whole mechanism exists to resolve.
    const chart = mount([...Array.from({ length: 39 }, (_, i) => 90 + i * (20 / 38)), 100]);
    const tag = tagBox(chart);
    const drawn = drawnTicks(chart);
    const all = ladder(chart);
    const suppressed = all.filter((t) => !drawn.includes(t));

    // Something was suppressed, or this chart is not exercising the feature.
    expect(suppressed.length).toBeGreaterThan(0);
    // Everything suppressed sits under the tag.
    for (const label of suppressed) {
      expect(Math.abs(yOf(chart, label) - tag.centre)).toBeLessThan(tag.h);
    }
    // Nothing that survived does.
    for (const label of drawn) {
      expect(Math.abs(yOf(chart, label) - tag.centre)).toBeGreaterThanOrEqual(tag.h / 2);
    }
    // The ladder is still labelled: suppression must not empty the axis.
    expect(drawn.length).toBeGreaterThan(1);
  });

  it('suppresses only the ticks the tag actually covers, never its neighbours', () => {
    // This used to assert "clear air leaves the whole ladder", with a fixture
    // whose last price happened to land between two rungs. At the shipped label
    // density that state is unreachable: rungs sit about a tag-height apart, so
    // midway between two of them is exactly a tag-height from each and the tag
    // always takes at least one label down. A reference terminal behaves the
    // same way, suppressing the prices either side of its own last-price tag.
    //
    // The invariant worth pinning is therefore the other half of the rule, and
    // it holds at any density: a tick that does NOT collide with the tag is
    // drawn. Over-suppression is what would make the axis unreadable.
    const chart = mount([...Array.from({ length: 39 }, (_, i) => 90 + i * 0.5), 102.5]);
    const tag = tagBox(chart);
    const drawn = new Set(drawnTicks(chart));
    let collided = 0;
    for (const label of ladder(chart)) {
      if (Math.abs(yOf(chart, label) - tag.centre) > tag.h) expect(drawn.has(label)).toBe(true);
      else collided++;
    }
    // And the fixture is worth having only while it still exercises a collision.
    expect(collided).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// The corner clock and the countdown row: both are chrome a host switches on,
// and until it does the chart draws neither. Both were built with a `visible`
// flag and an injected clock and reached by nothing, which is the state this
// covers against.
// ---------------------------------------------------------------------------

describe('axis chrome a host can actually switch on', () => {
  const BARS = Array.from({ length: 30 }, (_, i) => ({
    time: 1700000000 + i * 300, // five-minute bars
    open: 100, high: 101, low: 99, close: 100.5,
  }));

  /** A chart whose wall clock is frozen, so the countdown is a fixed string. */
  function mount(axisChrome?: AxisChromeOptions): Chart {
    const doc = fakeDocument();
    const el = doc.createElement('div') as unknown as HTMLElement;
    Object.assign(el, { clientWidth: 800, clientHeight: 600 });
    const chart = new Chart(el, {
      document: doc,
      pixelRatio: () => 1,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
      shortcuts: false,
      timeNavigator: false,
      axisChrome,
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(BARS);
    return chart;
  }

  const rec = (chart: Chart): RecordingContext =>
    chart.panes()[0].base.ctx as unknown as RecordingContext;

  it('draws no corner clock and no countdown until asked', () => {
    const drawn = texts(rec(mount()));
    expect(drawn.some((t) => t !== undefined && /^\d\d:\d\d:\d\d$/.test(t))).toBe(false);
    expect(drawn.some((t) => t !== undefined && t.startsWith('UTC'))).toBe(false);
  });

  it('draws the corner clock in the chart timezone once switched on', () => {
    // 2023-11-14T22:13:20Z is 03:43:20 the next morning in the shipped zone.
    const chart = mount({ sessionClock: true, clock: () => 1700000000 });
    const drawn = texts(rec(chart));
    expect(drawn).toContain('03:43:20');
    expect(drawn).toContain('UTC+5:30');
  });

  it('follows the chart timezone rather than the machine', () => {
    const chart = mount({ sessionClock: true, clock: () => 1700000000 });
    chart.setTimezone('America/New_York');
    const drawn = texts(rec(chart));
    expect(drawn).toContain('17:13:20');
    expect(drawn).toContain('UTC-5');
  });

  it('counts the current bar down from the interval read off the bars', () => {
    // The last bar opened at 1700008700; 100 seconds later, 200 of its 300 left.
    const chart = mount({ barCountdown: true, clock: () => 1700008700 + 100 });
    expect(texts(rec(chart))).toContain('00:03:20');
  });

  it('reserves the taller band the countdown tag occupies', () => {
    const plain = mount({ barCountdown: false });
    const counting = mount({ barCountdown: true, clock: () => 1700008700 + 100 });
    const boxOf = (c: Chart): Op => {
      const box = ofType(rec(c), 'fillRect').find((o) => o.args[0] >= 800 - 56);
      if (box === undefined) throw new Error('no last-price tag');
      return box;
    };
    // The tag really is taller, which is the reason the reservation has to ask.
    expect(boxOf(counting).args[3]).toBeGreaterThan(boxOf(plain).args[3]);
  });

  it('can be asked for the clock without the offset row', () => {
    const chart = mount({ sessionClock: { showOffset: false }, clock: () => 1700000000 });
    const drawn = texts(rec(chart));
    expect(drawn).toContain('03:43:20');
    expect(drawn.some((t) => t !== undefined && t.startsWith('UTC'))).toBe(false);
  });

  it('reaches no global clock: the chart passes the clock it was given', () => {
    withNoGlobalClock(() => {
      const chart = mount({ sessionClock: true, barCountdown: true, clock: () => 1700000000 });
      expect(texts(rec(chart))).toContain('03:43:20');
    });
  });
});

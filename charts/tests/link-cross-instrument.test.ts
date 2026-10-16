/**
 * Release-gate verification of the one claim the whole linking feature rests
 * on: two charts holding **different symbols on different intervals** in one
 * group stay aligned by instant, never by bar index.
 *
 * Written independently of `tests/chart-link.test.ts` and
 * `tests/link-wiring.test.ts` on purpose. The failure mode being ruled out is
 * the implementation that copies a logical index or a logical range straight
 * across: it is indistinguishable from a correct one whenever the two charts
 * hold the same bars, so every assertion here is arranged so that the
 * index-copying answer and the time-mapping answer are different numbers, and
 * the index-copying answer is named in the assertion.
 *
 * Leader:   INFY, intraday bars (5-minute or hourly).
 * Follower: RELIANCE, daily bars with two of its own holidays punched out, so
 *           the follower's index for a given instant is nowhere near the
 *           leader's and is not even a fixed offset from it.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument, pointer } from './helpers/fake-dom';
import { createLinkGroup } from '../src/index';
import type { Bar } from '../src/model/bar';

const MIN = 60;
const HOUR = 3600;
const DAY = 86400;
/** A Monday 00:00 UTC, so "day N" is a distinct calendar day. */
const T0 = 1700438400;

const bar = (time: number, value: number): Bar => ({
  time, open: value, high: value + 1, low: value - 1, close: value,
});

/**
 * A chart that paints synchronously and is measured. Without `applySize` every
 * price scale sits on its 0..1 placeholder and the time scale has no width, so
 * `timeToCoordinate` would be answering from nothing.
 */
function makeChart(bars: readonly Bar[]): { chart: Chart; el: HTMLElement } {
  const el = fakeDocument().createElement('div');
  const chart = new Chart(el, {
    document: fakeDocument(),
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(bars);
  chart.fitContent();
  return { chart, el };
}

/** Drive the real pointer path so the crosshair event carries a real instant. */
function hoverAt(el: HTMLElement, x: number): void {
  (el as unknown as { dispatch(t: string, e: unknown): void })
    .dispatch('pointermove', pointer('move', x, 200, { buttons: 0 }));
}

/** INFY: 75 five-minute bars on day 5, one session. */
const SESSION_START = T0 + 5 * DAY + 9 * HOUR + 15 * MIN;
const infy5m: Bar[] = Array.from({ length: 75 }, (_, i) => bar(SESSION_START + i * 5 * MIN, 1500 + i));

/** RELIANCE: 200 calendar days of daily bars, days 4 and 100 its own holidays. */
const RELIANCE_HOLIDAYS = new Set([4, 100]);
const relianceDaily: Bar[] = Array.from({ length: 200 }, (_, i) => i)
  .filter((d) => !RELIANCE_HOLIDAYS.has(d))
  .map((d) => bar(T0 + d * DAY, 2400 + d));

/** INFY: hourly bars over the same 200 days, 24 a day and no holidays at all. */
const infyHourly: Bar[] = Array.from({ length: 200 * 24 }, (_, i) => bar(T0 + i * HOUR, 1500 + (i % 400)));

/**
 * The first ten days of the same hourly series. Short enough that `fitContent`
 * leaves every bar on screen, so a hover assertion below cannot pass or fail on
 * whether the probe happened to be scrolled out of the plot.
 */
const infyHourlyShort: Bar[] = infyHourly.slice(0, 10 * 24);

/** The follower's own index of the daily bar covering day N. */
function dailyIndexOfDay(chart: Chart, day: number): number {
  const idx = chart.dataLayer.timeToIndex(T0 + day * DAY);
  expect(idx, `follower has a bar for day ${day}`).not.toBeUndefined();
  return idx as number;
}

beforeEach(() => {
  // Chart._attachInput bails out when there is no window, and without it no
  // pointer handler runs and every hover assertion below would be vacuous.
  vi.stubGlobal('window', {});
});
afterEach(() => { vi.unstubAllGlobals(); });

describe('link: different symbol AND different interval stay aligned by instant', () => {
  it('the two charts really are misaligned by index, or nothing below proves anything', () => {
    const leader = makeChart(infy5m);
    const follower = makeChart(relianceDaily);
    // The leader's bar 40 is inside day 5; the follower's own index for day 5
    // is 4, because day 4 is one of its holidays.
    expect(leader.chart.dataLayer.length).toBe(75);
    expect(follower.chart.dataLayer.length).toBe(198);
    expect(dailyIndexOfDay(follower.chart, 5)).toBe(4);
    leader.chart.destroy();
    follower.chart.destroy();
  });

  it('mirrors the hovered instant onto the follower bar that contains it, not onto the same index', () => {
    const leader = makeChart(infy5m);
    const follower = makeChart(relianceDaily);
    const group = createLinkGroup({ crosshair: true, viewport: false, symbol: false });
    group.add(leader.chart, { symbol: 'INFY' });
    group.add(follower.chart, { symbol: 'RELIANCE' });

    // 09:40 on day 5. Morning on purpose: see the last test in this file for
    // what the 'nearest' policy does to an afternoon instant.
    const leaderIndex = 5;
    const hoveredTime = infy5m[leaderIndex].time;
    expect(hoveredTime).toBe(T0 + 5 * DAY + 9 * HOUR + 40 * MIN);
    hoverAt(leader.el, leader.chart.timeToCoordinate(hoveredTime));

    const mapped = group.crosshairIndex(follower.chart);
    expect(mapped).not.toBeNull();
    expect(mapped).toBe(dailyIndexOfDay(follower.chart, 5));
    // The index-copying implementation would have answered the leader's own
    // index, which the follower does have a bar at. Named explicitly so this
    // test cannot pass against it.
    expect(mapped).toBe(4);
    expect(mapped).not.toBe(leaderIndex);
    // And the instant the follower is marking really contains the one hovered.
    const markedTime = follower.chart.dataLayer.indexToTime(mapped as number) as number;
    expect(markedTime).toBe(T0 + 5 * DAY);
    expect(hoveredTime).toBeGreaterThanOrEqual(markedTime);
    expect(hoveredTime).toBeLessThan(markedTime + DAY);

    // The leader itself never draws a linked line over its own real crosshair.
    expect(group.crosshairIndex(leader.chart)).toBeNull();

    group.destroy();
    leader.chart.destroy();
    follower.chart.destroy();
  });

  it('refuses an instant the follower does not cover rather than pinning it to an edge bar', () => {
    // Follower's history stops at day 2, so every instant on the leader's day-5
    // session is past its coverage. Clamping would answer its last index.
    const leader = makeChart(infy5m);
    const shortHistory = relianceDaily.filter((b) => b.time <= T0 + 2 * DAY);
    const follower = makeChart(shortHistory);
    const group = createLinkGroup({ crosshair: true, viewport: false });
    group.add(leader.chart);
    group.add(follower.chart);

    hoverAt(leader.el, leader.chart.timeToCoordinate(infy5m[10].time));
    expect(follower.chart.dataLayer.length).toBe(3);
    expect(group.crosshairIndex(follower.chart)).toBeNull();

    group.destroy();
    leader.chart.destroy();
    follower.chart.destroy();
  });

  it("hide and nearest differ over the follower's holiday, and both answer per instant", () => {
    // The leader trades hourly straight through day 4, which the follower is
    // shut for. Two probes inside that one gap. Both resolve to day 3: it is the
    // last bar the follower had OPENED at either instant, and day 5's bar is
    // still in the future from both. Choosing day 5 for the second probe, on the
    // grounds that its stamp is arithmetically closer, would mark a candle that
    // had not happened yet.
    const nearest = createLinkGroup({ crosshair: true, viewport: false, whenMissing: 'nearest' });
    const nLeader = makeChart(infyHourlyShort);
    const nFollower = makeChart(relianceDaily);
    nearest.add(nLeader.chart);
    nearest.add(nFollower.chart);

    const lateDay3 = T0 + 3 * DAY + 20 * HOUR;
    hoverAt(nLeader.el, nLeader.chart.timeToCoordinate(lateDay3));
    const backwards = nearest.crosshairIndex(nFollower.chart);
    expect(backwards).toBe(dailyIndexOfDay(nFollower.chart, 3));
    expect(nFollower.chart.dataLayer.indexToTime(backwards as number)).toBe(T0 + 3 * DAY);

    const earlyDay4 = T0 + 4 * DAY + 2 * HOUR;
    hoverAt(nLeader.el, nLeader.chart.timeToCoordinate(earlyDay4));
    const forwards = nearest.crosshairIndex(nFollower.chart);
    expect(forwards).toBe(dailyIndexOfDay(nFollower.chart, 3));
    expect(nFollower.chart.dataLayer.indexToTime(forwards as number)).toBe(T0 + 3 * DAY);
    // Same gap, same bar, whichever end of it you probe: the follower never
    // moves forward onto a bar that had not opened.
    expect(forwards).toBe(backwards);

    const hide = createLinkGroup({ crosshair: true, viewport: false, whenMissing: 'hide' });
    const hLeader = makeChart(infyHourlyShort);
    const hFollower = makeChart(relianceDaily);
    hide.add(hLeader.chart);
    hide.add(hFollower.chart);
    hoverAt(hLeader.el, hLeader.chart.timeToCoordinate(earlyDay4));
    expect(hide.crosshairIndex(hFollower.chart)).toBeNull();
    // ...but an instant the follower does have a bar for still shows, so 'hide'
    // is not simply switching the channel off.
    hoverAt(hLeader.el, hLeader.chart.timeToCoordinate(T0 + 5 * DAY));
    expect(hide.crosshairIndex(hFollower.chart)).toBe(dailyIndexOfDay(hFollower.chart, 5));

    nearest.destroy();
    hide.destroy();
    for (const c of [nLeader, nFollower, hLeader, hFollower]) c.chart.destroy();
  });

  // Windows below are 20 calendar days: 480 hourly leader bars and 20 daily
  // follower bars across the same ~744 px plot, which is inside the scale's
  // 1..80 px bar-spacing clamp on both charts. Outside it the scale would
  // rewrite the range and these assertions would be measuring the clamp.
  it('maps a programmatic viewport change to the same wall-clock window, not the same logical range', () => {
    const leader = makeChart(infyHourly);
    const follower = makeChart(relianceDaily);
    const group = createLinkGroup({ crosshair: false, viewport: true });
    group.add(leader.chart, { symbol: 'INFY' });
    group.add(follower.chart, { symbol: 'RELIANCE' });

    const from = 50 * 24;
    const to = 70 * 24;
    leader.chart.setVisibleLogicalRange({ from, to });
    // The leader kept the window it was given, so the follower's is a mapping
    // of these numbers and not of something the clamp invented.
    const kept = leader.chart.getVisibleLogicalRange();
    expect(kept.from).toBeCloseTo(from, 6);
    expect(kept.to).toBeCloseTo(to, 6);

    const got = follower.chart.getVisibleLogicalRange();
    // Copying the range across would have put the follower at 1200..1680, past
    // the end of its 198 bars. Rule that out first.
    expect(got.from).toBeLessThan(from);
    expect(got.to).toBeLessThan(to);

    // The window is the same wall clock on both, to under a second.
    const leaderFromT = leader.chart.dataLayer.indexToTimeFloat(from);
    const leaderToT = leader.chart.dataLayer.indexToTimeFloat(to);
    expect(leaderFromT).toBe(T0 + 50 * DAY);
    expect(leaderToT).toBe(T0 + 70 * DAY);
    expect(follower.chart.dataLayer.indexToTimeFloat(got.from)).toBeCloseTo(leaderFromT, 0);
    expect(follower.chart.dataLayer.indexToTimeFloat(got.to)).toBeCloseTo(leaderToT, 0);

    // Day 50 is the follower's index 49 (day 4 gone) and day 70 its index 69.
    expect(got.from).toBeCloseTo(49, 6);
    expect(got.to).toBeCloseTo(69, 6);
    expect(to - from).toBe(480);
    expect(got.to - got.from).toBeCloseTo(20, 6);

    group.destroy();
    leader.chart.destroy();
    follower.chart.destroy();
  });

  it('crossing the follower holiday shifts the mapping again, so it is per-instant not per-offset', () => {
    const leader = makeChart(infyHourly);
    const follower = makeChart(relianceDaily);
    const group = createLinkGroup({ crosshair: false, viewport: true });
    group.add(leader.chart);
    group.add(follower.chart);

    // Before day 100: one holiday behind us, so day N maps to index N-1.
    leader.chart.setVisibleLogicalRange({ from: 50 * 24, to: 70 * 24 });
    expect(follower.chart.getVisibleLogicalRange().from).toBeCloseTo(49, 6);

    // After day 100: two holidays behind us, so day N maps to index N-2. A
    // fixed-offset implementation cannot produce both answers.
    leader.chart.setVisibleLogicalRange({ from: 120 * 24, to: 140 * 24 });
    const after = follower.chart.getVisibleLogicalRange();
    expect(after.from).toBeCloseTo(118, 6);
    expect(after.to).toBeCloseTo(138, 6);
    expect(follower.chart.dataLayer.indexToTimeFloat(after.from)).toBeCloseTo(T0 + 120 * DAY, 0);
    expect(follower.chart.dataLayer.indexToTimeFloat(after.to)).toBeCloseTo(T0 + 140 * DAY, 0);

    group.destroy();
    leader.chart.destroy();
    follower.chart.destroy();
  });

  it('does not echo: mirroring the follower leaves the leader exactly where it was put', () => {
    const leader = makeChart(infyHourly);
    const follower = makeChart(relianceDaily);
    const group = createLinkGroup({ crosshair: false, viewport: true });
    group.add(leader.chart);
    group.add(follower.chart);

    leader.chart.setVisibleLogicalRange({ from: 50 * 24, to: 70 * 24 });
    const back = leader.chart.getVisibleLogicalRange();
    expect(back.from).toBeCloseTo(50 * 24, 6);
    expect(back.to).toBeCloseTo(70 * 24, 6);

    group.destroy();
    leader.chart.destroy();
    follower.chart.destroy();
  });
  /**
   * Was an audit finding, now the fixed behaviour.
   *
   * `nearest` used to pick the follower bar whose TIMESTAMP was closest, and a
   * bar is stamped at the instant it opened. On a daily follower that meant any
   * instant past midday was closer to tomorrow's open than to today's, so an
   * afternoon cursor on an intraday leader marked the NEXT day's candle. A host
   * reading the linked bar's OHLC back out was reading tomorrow's bar for half
   * of every day, which is not a rounding preference.
   *
   * It now resolves to the last bar that had opened at that instant.
   */
  it('marks the daily bar that contains an afternoon instant, not the next one', () => {
    const leader = makeChart(infy5m);
    const follower = makeChart(relianceDaily);
    const group = createLinkGroup({ crosshair: true, viewport: false });
    group.add(leader.chart);
    group.add(follower.chart);

    const afternoon = infy5m[40].time;           // 12:35 on day 5
    expect(afternoon).toBe(T0 + 5 * DAY + 12 * HOUR + 35 * MIN);
    hoverAt(leader.el, leader.chart.timeToCoordinate(afternoon));

    const marked = group.crosshairIndex(follower.chart) as number;
    // Day 5, the bar the instant falls inside. Day 6 has not opened yet, even
    // though its stamp is 11h25m away against day 5's 12h35m.
    expect(follower.chart.dataLayer.indexToTime(marked)).toBe(T0 + 5 * DAY);
    expect(marked).toBe(dailyIndexOfDay(follower.chart, 5));

    group.destroy();
    leader.chart.destroy();
    follower.chart.destroy();
  });
});

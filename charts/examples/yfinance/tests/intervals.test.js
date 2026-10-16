import { describe, it, expect } from 'vitest';
import * as engine from '/dist/openalgo-charts.mjs';
import {
  CUSTOM_INTERVALS, customInterval, foldedInterval, intervalSeconds, foldToBuckets,
  INTERVALS, intervalLabel, intervalName, periodsFor, clampPeriod, PERIODS, PERIOD_DAYS, fillIntervalSelect,
  resolvePickerInterval, UnknownIntervalError, rangeLoad,
} from '../src/intervals.js';
import { DEFAULT_RANGES, rangeInterval } from '/dist/openalgo-charts.widget.mjs';
import { fakeDom, flatBar } from './helpers.js';

const { bucketStartOf } = engine;

describe('interval registry', () => {
  it('registers the calendar codes so the picker and the registry agree', () => {
    expect(INTERVALS).toEqual(['5m', '15m', '30m', '1h', '1d', '1wk', '1mo', '1q']);
    expect(CUSTOM_INTERVALS.map((i) => i.code)).toEqual(['1wk', '1mo', '1q']);
    expect(customInterval('1mo').name).toBe('Calendar month');
    expect(customInterval('1d')).toBeNull();
  });

  it('knows which codes are folded locally rather than fetched', () => {
    expect(foldedInterval('1mo').foldFrom).toBe('1d');
    expect(foldedInterval('1q').foldFrom).toBe('1d');
    expect(foldedInterval('1wk')).toBeNull();
    expect(foldedInterval('1d')).toBeNull();
  });

  it('answers bar length off the registry, and 0 for a calendar bucket', () => {
    expect(intervalSeconds('1d')).toBe(86400);
    expect(intervalSeconds('1wk')).toBe(604800);
    expect(intervalSeconds('1mo')).toBe(0);
  });

  it('labels and names the codes for the pills', () => {
    expect(intervalLabel('5m')).toBe('5M');
    expect(intervalLabel('1mo')).toBe('1MO');
    // In words: "5M bars" read as five months beside the bottom bar's 1M.
    expect(intervalName('1d')).toBe('Daily bars');
    expect(intervalName('5m')).toBe('5 minute bars');
    expect(intervalName('1wk')).toBe('Weekly bars');
    expect(intervalName('1q')).toBe('Calendar quarter (folded from 1D bars)');
  });
});

describe('folding into calendar buckets', () => {
  const month = customInterval('1mo').bucketing;
  // 12:00 UTC on 31 January 2024 is still January everywhere; 18:30 UTC is
  // 00:00 on 1 February in Kolkata and 13:30 on 31 January in New York.
  const bars = [
    flatBar(Date.UTC(2024, 0, 31, 12) / 1000, 100, 10),
    { time: Date.UTC(2024, 0, 31, 18, 30) / 1000, open: 101, high: 105, low: 99, close: 104, volume: 20 },
  ];

  it('moves the month boundary with the zone', () => {
    const kolkata = foldToBuckets(bars, month, 'Asia/Kolkata');
    expect(kolkata).toHaveLength(2);
    expect(kolkata[1].time).toBe(bucketStartOf(month, bars[1].time, 'Asia/Kolkata'));

    const newYork = foldToBuckets(bars, month, 'America/New_York');
    expect(newYork).toHaveLength(1);
    expect(newYork[0]).toEqual({
      time: bucketStartOf(month, bars[0].time, 'America/New_York'),
      open: 100, high: 105, low: 99, close: 104, volume: 30,
    });
  });

  it('returns nothing for no bars', () => {
    expect(foldToBuckets([], month, 'Asia/Kolkata')).toEqual([]);
  });
});

describe('ranges an interval can serve', () => {
  it('caps intraday frames at what the source goes back to', () => {
    expect(periodsFor('5m')).toEqual(['1mo']);
    expect(periodsFor('1h')).toEqual(['1mo', '6mo', '1y']);
    // Daily and up have no cap: weekly, which has no floor either, offers
    // every range, and daily still reaches back as far as the source goes.
    expect(periodsFor('1wk')).toEqual(PERIODS);
    expect(periodsFor('1d')).toContain('max');
  });

  it('floors calendar frames at a range that draws more than one candle', () => {
    expect(periodsFor('1mo')).toEqual(['5y', 'max']);
    expect(periodsFor('1q')).toEqual(['5y', 'max']);
  });

  it('floors daily at five years, so a daily chart holds 500 candles or more', () => {
    expect(periodsFor('1d')).toEqual(['5y', 'max']);
    // Two years is about 495 sessions, short of 500, and the source has no
    // three-year period: no range under five years may be offered at all.
    expect(periodsFor('1d').filter((p) => PERIOD_DAYS[p] < 5 * 365)).toEqual([]);
  });

  it('clamps to the nearest range the frame can fill', () => {
    expect(clampPeriod('1h', '6mo')).toBe('6mo');
    expect(clampPeriod('1wk', '1mo')).toBe('1mo');
    expect(clampPeriod('5m', '1y')).toBe('1mo');
    expect(clampPeriod('1mo', '1y')).toBe('5y');
    expect(clampPeriod('1q', 'max')).toBe('max');
    for (const short of ['1mo', '6mo', '1y']) expect(clampPeriod('1d', short)).toBe('5y');
    expect(clampPeriod('1d', '5y')).toBe('5y');
    expect(clampPeriod('1d', 'max')).toBe('max');
  });

  it('loads a preset range at an interval whose history reaches all of it', () => {
    const range = id => DEFAULT_RANGES.find(r => r.id === id);
    const load = (id, days) => rangeLoad(range(id), days * 86400, rangeInterval);
    expect(load('1D', 3)).toEqual({ interval: '5m', period: '1mo' });
    expect(load('5D', 7)).toEqual({ interval: '5m', period: '1mo' });
    // A month back to midnight inside the 31 days of the page's month keeps
    // the month's 30-minute bars; a longer one would stop a few hours short.
    expect(load('1M', 30.5)).toEqual({ interval: '30m', period: '1mo' });
    expect(load('1M', 31.2)).toEqual({ interval: '1h', period: '6mo' });
    expect(load('3M', 92)).toEqual({ interval: '1h', period: '6mo' });
    expect(load('1Y', 366)).toEqual({ interval: '1d', period: '5y' });
    expect(load('5Y', 1827)).toEqual({ interval: '1wk', period: '5y' });
    expect(load('ALL', 30 * 366)).toEqual({ interval: '1wk', period: 'max' });
  });
});

describe('fillIntervalSelect', () => {
  it('rebuilds the hidden select from the same list as the pills and keeps the choice', () => {
    const { get } = fakeDom({ interval: '1h' });
    fillIntervalSelect();
    const sel = get('interval');
    expect(sel.children.map((o) => o.value)).toEqual(INTERVALS);
    expect(sel.children.map((o) => o.textContent)).toEqual(INTERVALS.map(intervalLabel));
    expect(sel.value).toBe('1h');
  });

  it('falls back to daily when the select held a code the list does not have', () => {
    const { get } = fakeDom({ interval: '2m' });
    fillIntervalSelect();
    expect(get('interval').value).toBe('1d');
  });
});

describe('resolvePickerInterval', () => {
  it('answers off the registry for built-in and registered codes', () => {
    expect(resolvePickerInterval('1d').bucketing).toEqual({ mode: 'interval', seconds: 86400 });
    expect(resolvePickerInterval('1wk').bucketing.seconds).toBe(604800);
    expect(resolvePickerInterval('1mo').bucketing.mode).toBe('calendar');
    // The registry folds case and trims, the way the built-in tokens always have.
    expect(resolvePickerInterval(' 1H ').bucketing.seconds).toBe(3600);
  });

  it('throws UnknownIntervalError, carrying the code, for anything else', () => {
    expect(() => resolvePickerInterval('3x')).toThrow(UnknownIntervalError);
    let caught = null;
    try { resolvePickerInterval('3x'); } catch (e) { caught = e; }
    expect(caught.name).toBe('UnknownIntervalError');
    expect(caught.code).toBe('3x');
    expect(caught.message).toContain('3x');
    expect(() => resolvePickerInterval('')).toThrow(UnknownIntervalError);
    expect(() => resolvePickerInterval(undefined)).toThrow(UnknownIntervalError);
    expect(() => resolvePickerInterval(null)).toThrow(UnknownIntervalError);
    // A bare M is a month on every terminal and sixty seconds to a careless
    // parser; the registry refuses it rather than guess, and so does this.
    expect(() => resolvePickerInterval('1M')).toThrow(UnknownIntervalError);
  });

  it("is the engine's own error class when the build has one", () => {
    expect(UnknownIntervalError).toBe(engine.UnknownIntervalError);
    expect(new UnknownIntervalError('zz')).toBeInstanceOf(engine.UnknownIntervalError);
  });
});

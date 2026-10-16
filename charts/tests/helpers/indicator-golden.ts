/**
 * Complete, ordinary market data and a bit-exact digest of what the studies
 * touched by the gap corrections compute on it.
 *
 * Those corrections change only bars that are missing an input. The digests in
 * `tests/indicator-gap-recovery.test.ts` were recorded from the 2.5.4 code before
 * the corrections landed, so a matching digest proves that finite output on
 * complete data is unchanged to the last bit, not merely close.
 */
import type { Bar } from '../../src/model/bar';
import type { IndicatorDescriptor } from '../../src/model/indicator-registry';
import { indicatorDefaults } from '../../src/model/indicator-registry';
import { atr } from '../../src/indicators/atr';
import { supertrend } from '../../src/indicators/supertrend';
import { ATR } from '../../src/indicators/momentum';
import { KELTNER_CHANNEL } from '../../src/indicators/adaptive';
import { CHANDE_KROLL_STOP, CHANDELIER_EXIT } from '../../src/indicators/overlay';
import { MEDIAN, TWAP } from '../../src/indicators/averages';
import { HALFTREND, PARABOLIC_SAR, SUPERTREND, VWAP } from '../../src/indicators/trend';
import { VOLATILITY_STOP } from '../../src/indicators/signals';
import { ADL, OBV } from '../../src/indicators/volume';

type Columns = Readonly<Record<string, readonly (number | null)[]>>;

/**
 * Five sessions of one-minute bars, 09:15 to 15:30 on the default zone's clock,
 * from a seeded random walk. Unrounded prices keep every rounding step in play.
 */
export function completeSessions(): Bar[] {
  let state = 0x2545f491;
  const next = (): number => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 2 ** 32;
  };
  const bars: Bar[] = [];
  let close = 1500 + next() * 10;
  for (let day = 0; day < 5; day++) {
    const start = Date.UTC(2024, 0, 1 + day, 3, 45) / 1000;
    for (let minute = 0; minute < 375; minute++) {
      const open = close;
      close = open + (next() - 0.5) * 3;
      const high = Math.max(open, close) + next() * 1.5;
      const low = Math.min(open, close) - next() * 1.5;
      bars.push({ time: start + minute * 60, open, high, low, close, volume: 100 + Math.floor(next() * 5000) });
    }
  }
  return bars;
}

/**
 * Every column, every bit: -0 stays apart from 0, and an absent slot from both.
 * `String` of a double round-trips exactly, so equal text is equal bits.
 */
export async function digest(columns: Columns): Promise<string> {
  const text = Object.keys(columns).sort().map((key) => `${key}:${columns[key].map((value) =>
    value === null ? 'n' : Object.is(value, -0) ? '-0' : String(value)).join(',')}`).join('|');
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)));
  return Array.from(hash.subarray(0, 8), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

const study = (descriptor: IndicatorDescriptor, overrides: Record<string, unknown> = {}) =>
  (bars: Bar[]): Columns => descriptor.calc(bars, { ...indicatorDefaults(descriptor), ...overrides }, {}) as Columns;

/** Named calculations whose complete-data output must not move by one bit. */
export const GOLDEN_CASES: readonly (readonly [string, (bars: Bar[]) => Columns])[] = [
  ['atr()', (bars) => {
    const high = bars.map((b) => b.high);
    const low = bars.map((b) => b.low);
    const close = bars.map((b) => b.close);
    const out: Record<string, number[]> = {};
    for (const period of [1, 2, 14, 100, 500]) out[`p${period}`] = atr(high, low, close, period);
    return out;
  }],
  ['supertrend()', (bars) => {
    const points = supertrend(bars, 10, 3);
    return { value: points.map((p) => p.value), direction: points.map((p) => p.direction) };
  }],
  ['ATR', study(ATR)],
  ['ATR period 1', study(ATR, { period: 1 })],
  ['ATR period 5', study(ATR, { period: 5 })],
  ['Keltner', study(KELTNER_CHANNEL)],
  ['Keltner ATR 3', study(KELTNER_CHANNEL, { atrlength: 3, exp: false })],
  ['Chande Kroll Stop', study(CHANDE_KROLL_STOP)],
  ['Chandelier Exit', study(CHANDELIER_EXIT)],
  ['Median', study(MEDIAN)],
  ['HalfTrend', study(HALFTREND)],
  ['HalfTrend ATR 10', study(HALFTREND, { atrPeriod: 10 })],
  ['Volatility Stop', study(VOLATILITY_STOP)],
  ['Supertrend', study(SUPERTREND)],
  ['VWAP session', study(VWAP, { showBand2: true, showBand3: true })],
  ['VWAP week', study(VWAP, { anchor: 'week', showBand2: true })],
  ['VWAP continuous percent', study(VWAP, { anchor: 'continuous', calcMode: 'percent', showBand3: true })],
  ['VWAP New York', study(VWAP, { timezone: 'America/New_York', offset: 3 })],
  ['Parabolic SAR', study(PARABOLIC_SAR)],
  ['Parabolic SAR fast', study(PARABOLIC_SAR, { start: 0.01, increment: 0.03, maximum: 0.3 })],
  ['OBV', study(OBV)],
  ['OBV Bollinger', study(OBV, { maType: 'SMA + Bollinger Bands' })],
  ['OBV VWMA', study(OBV, { maType: 'VWMA' })],
  ['OBV EMA', study(OBV, { maType: 'EMA' })],
  ['ADL', study(ADL)],
  ['TWAP session', study(TWAP)],
  ['TWAP continuous', study(TWAP, { anchor: 'continuous', source: 'hlc3', offset: -2 })],
];

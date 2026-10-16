/**
 * How the built-ins read their settings blob. A blob carries whatever a
 * settings UI, a saved chart or a host wrote, so each reader falls back to the
 * given default on a value of the wrong type and never throws: a `calc` that
 * throws takes the whole repaint down with it.
 *
 * One module, so that one blob means the same thing to every built-in
 * whichever family it lives in. Tier-internal: the tier index does not
 * re-export it.
 */
import { DEFAULT_TIMEZONE, isValidTimezone } from 'openalgo-charts';
import type { IndicatorSource } from 'openalgo-charts';

export type Settings = Readonly<Record<string, unknown>>;

/** A finite number, or the default. */
export const num = (s: Settings, k: string, d: number): number => {
  const v = s[k];
  return typeof v === 'number' && Number.isFinite(v) ? v : d;
};

/**
 * A count of bars, such as a window length: a whole number of at least `min`
 * (1 unless given), rounded to the nearest. The reference `input.int` is whole
 * by construction, but a settings blob carries whatever a UI wrote, and every
 * built-in reads 14.5 as 15 so that one blob means one window across the
 * catalogue. The kernels refuse a fractional length outright, which a study
 * would show as an empty pane.
 */
export const int = (s: Settings, k: string, d: number, min = 1): number =>
  Math.max(min, Math.round(num(s, k, d)));

/** A plot offset: whole bars, and the one whole-number setting that may be negative. */
export const offsetOf = (s: Settings, k: string, d: number): number => Math.round(num(s, k, d));

/** A non-empty string, such as a colour or a choice, or the default. */
export const str = (s: Settings, k: string, d: string): string => {
  const v = s[k];
  return typeof v === 'string' && v !== '' ? v : d;
};

/** A boolean, or the default. */
export const flag = (s: Settings, k: string, d: boolean): boolean => {
  const v = s[k];
  return typeof v === 'boolean' ? v : d;
};

/** A price source; a study reference passes through for the kernel to resolve. */
export const src = (s: Settings, k = 'source', d: IndicatorSource = 'close'): IndicatorSource =>
  (s[k] as IndicatorSource | undefined) ?? d;

/**
 * The chart's configured zone, as it reaches an indicator.
 *
 * A descriptor's hooks are handed bars and settings and never the chart, so the
 * zone travels on the settings blob under the reserved `timezone` key. A blob
 * without one, which is every caller that predates the option, resolves to the
 * shipped default and computes exactly what 1.2.0 computed.
 *
 * An unrecognised name falls back rather than throwing: `chart.setTimezone`
 * already rejects a bad zone at the call site.
 */
export const zoneOf = (s: Settings): string => {
  const v = s.timezone;
  if (typeof v !== 'string' || v === '' || v === DEFAULT_TIMEZONE) return DEFAULT_TIMEZONE;
  return isValidTimezone(v) ? v : DEFAULT_TIMEZONE;
};

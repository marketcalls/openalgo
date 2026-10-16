/** Per-bar position levels from the instrument itself, with no external alignment. */
import type { IndicatorDescriptor } from 'openalgo-charts';
import { str } from './settings';

const reading = (value: number | undefined): number | null =>
  value !== undefined && Number.isFinite(value) ? value : null;

/** A missing observation breaks the line; it is not an empty position. */
export const OPEN_INTEREST: IndicatorDescriptor = {
  id: 'open-interest', name: 'Open Interest', category: 'Volume', placement: 'pane',
  inputs: [{ key: 'color', type: 'color', label: 'Open interest', default: '#26c6da' }],
  plots: [{
    key: 'oi', type: 'line', title: 'Open interest', colorKey: 'color',
    priceFormat: { type: 'volume' }, style: { lineWidth: 1.5 },
  }],
  calc: bars => ({ oi: bars.map(bar => reading(bar.oi)) }),
};

/** Adjacent observations only: a gap cannot support a bar-on-bar change. */
export const OPEN_INTEREST_CHANGE: IndicatorDescriptor = {
  id: 'open-interest-change', name: 'Open Interest Change', category: 'Volume', placement: 'pane',
  inputs: [
    { key: 'upColor', type: 'color', label: 'Increase', default: '#26a69a' },
    { key: 'downColor', type: 'color', label: 'Decrease', default: '#ef5350' },
  ],
  plots: [{
    key: 'change', type: 'histogram', title: 'OI change', colorKey: 'upColor', style: { base: 0 },
    priceFormat: { type: 'volume' },
    // The plot's Opacity setting fades this colour in the plot writer.
    colorBy: ({ value, settings }) => (value < 0 ? str(settings, 'downColor', '#ef5350') : str(settings, 'upColor', '#26a69a')),
  }],
  calc: bars => ({
    change: bars.map((bar, i) => {
      const current = reading(bar.oi);
      const previous = reading(bars[i - 1]?.oi);
      return current === null || previous === null ? null : current - previous;
    }),
  }),
};

const BUILDUP_COLORS = [
  ['longBuildupColor', '#26a69a'],
  ['shortBuildupColor', '#ef5350'],
  ['shortCoveringColor', '#42a5f5'],
  ['longUnwindingColor', '#ffb74d'],
] as const;

/**
 * Price and position changes describe a regime, not a second price series.
 * Publish candle colors only, so the study cannot distort the instrument axis.
 */
export const OPEN_INTEREST_BUILDUP: IndicatorDescriptor = {
  id: 'open-interest-buildup', name: 'Open Interest Buildup', category: 'Volume', placement: 'onchart',
  inputs: [
    { key: 'longBuildupColor', type: 'color', label: 'Long buildup', default: '#26a69a' },
    { key: 'shortBuildupColor', type: 'color', label: 'Short buildup', default: '#ef5350' },
    { key: 'shortCoveringColor', type: 'color', label: 'Short covering', default: '#42a5f5' },
    { key: 'longUnwindingColor', type: 'color', label: 'Long unwinding', default: '#ffb74d' },
    {
      key: 'unchanged', type: 'select', label: 'Unchanged reading', default: 'neutral',
      options: [{ value: 'neutral', label: 'Neutral' }, { value: 'up', label: 'Treat as up' }],
    },
  ],
  plots: [],
  calc: (bars, settings) => ({
    state: bars.map((bar, i) => {
      const previous = bars[i - 1];
      const oi = reading(bar.oi);
      const previousOi = reading(previous?.oi);
      if (previous === undefined || oi === null || previousOi === null) return null;
      const priceChange = bar.close - previous.close;
      const oiChange = oi - previousOi;
      if (!Number.isFinite(priceChange)) return null;
      if (settings.unchanged !== 'up' && (priceChange === 0 || oiChange === 0)) return null;
      // 1 long buildup, 2 short buildup, 3 short covering, 4 long unwinding.
      return oiChange >= 0 ? priceChange >= 0 ? 1 : 2 : priceChange >= 0 ? 3 : 4;
    }),
  }),
  // `calc` above always writes `state`, and each reading in it is 1 to 4.
  barColors: ({ values, settings }) => values.state!.map(state => {
    if (state === null) return null;
    const [key, fallback] = BUILDUP_COLORS[state - 1]!;
    return str(settings, key, fallback);
  }),
};

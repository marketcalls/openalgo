import { registerIndicator } from '/dist/openalgo-charts.mjs';

/**
 * A study that lives in its own pane but has things to say about the candles.
 * Its Buy and Sell plates and its range box name the price pane, so they sit
 * on the bars that fired rather than on the histogram; the crossing dots and
 * the latest reading stay with the histogram. The Signals on price input sends
 * the plates back to the study's own layer, which is the only difference a
 * descriptor needs to route an output.
 *
 * The momentum regime shades the candles the same way: the shading column
 * names the price pane, because which way momentum points is a statement about
 * the price bars. Momentum shading moves it behind the histogram instead, as a
 * column naming no target, or turns it off.
 */
const SHADE_UP = 'rgba(38, 166, 154, 0.12)';
const SHADE_DOWN = 'rgba(239, 83, 80, 0.12)';

export function routedSignalDescriptor() {
  return {
    id: 'routed-signal-sample', name: 'Routed signal sample', category: 'Examples',
    placement: 'pane',
    inputs: [
      { key: 'length', type: 'number', label: 'Length', default: 10, min: 2, max: 100, step: 1 },
      { key: 'onPrice', type: 'boolean', label: 'Signals on price', default: true },
      {
        key: 'shade', type: 'select', label: 'Momentum shading', default: 'price',
        options: [{ label: 'On price', value: 'price' }, { label: 'In study pane', value: 'study' }, { label: 'Off', value: 'off' }],
      },
    ],
    plots: [{ key: 'momentum', type: 'histogram', title: 'Momentum', style: { color: '#64748b' } }],
    calc(bars, settings) {
      const n = Math.max(2, Math.floor(Number(settings.length) || 10));
      return { momentum: bars.map((bar, i) => (i < n ? null : bar.close - bars[i - n].close)) };
    },
    markers({ bars, values, settings }) {
      const out = [];
      for (let i = 1; i < bars.length; i++) {
        const before = values.momentum[i - 1], now = values.momentum[i];
        if (before == null || now == null || Math.sign(before) === Math.sign(now)) continue;
        const up = now > 0, color = up ? '#26a69a' : '#ef5350';
        out.push({
          time: bars[i].time, position: up ? 'belowBar' : 'aboveBar', shape: up ? 'labelUp' : 'labelDown',
          size: 'small', color, text: up ? 'Buy' : 'Sell', id: `signal:${bars[i].time}`,
          ...(settings.onPrice === false ? {} : { overlay: true }),
        });
        out.push({ time: bars[i].time, position: 'atPrice', price: now, shape: 'circle', size: 'tiny', color });
      }
      return out;
    },
    background({ values, settings }) {
      if (settings.shade === 'off') return [];
      const colors = values.momentum.map(v => (v == null || v === 0 ? null : v > 0 ? SHADE_UP : SHADE_DOWN));
      return [settings.shade === 'study' ? { colors } : { colors, overlay: true }];
    },
    draws({ bars, values }) {
      const last = bars.length - 1;
      if (last < 30) return [];
      const recent = bars.slice(last - 30);
      return [
        {
          kind: 'box', overlay: true, color: '#4f8cff', fillColor: '#4f8cff', opacity: 0.08,
          from: { time: recent[0].time, price: Math.max(...recent.map(bar => bar.high)) },
          to: { time: bars[last].time, price: Math.min(...recent.map(bar => bar.low)) },
          text: '30-bar range', verticalAlign: 'top', id: 'routed-range',
          tooltip: 'The range the latest signals fired in',
        },
        {
          kind: 'label', plot: 'momentum', align: 'left', color: '#64748b', text: 'Now',
          at: { time: bars[last].time, price: values.momentum[last] ?? 0 },
        },
      ];
    },
  };
}

export function initRoutedStudy() {
  registerIndicator(routedSignalDescriptor());
}

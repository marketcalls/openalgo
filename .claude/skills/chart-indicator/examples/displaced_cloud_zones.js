/**
 * ADVANCED example (2.4.0): drawing ahead of the last bar, and zones that
 * explain themselves.
 *
 * Two things a ported study reaches for constantly, and the difference between
 * them is worth knowing because it is not obvious:
 *
 *   - **A plot cannot leave the bars.** A column is one value per bar, so
 *     `plot(x, offset = 26)` is not a column that runs past the end; it is the
 *     same column PAINTED 26 bars to the right. `plot.offset` does that. The
 *     shifted tail lands in the right margin and the axis gains no bars.
 *   - **A drawing was never on the bars.** `draws()` anchors to a time, and the
 *     time scale extrapolates, so a box or a label at a future time has always
 *     rendered. 2.4.0 only adds the ability for one to answer the pointer.
 *
 * Also here: a candle plot whose wick is painted apart from its body, which is
 * what a translucent Heikin Ashi over the real candles wants, and a table that
 * sizes its own type.
 */

export default function ({
  registerIndicator,
  sourceValues,
  sma,
  atr,
  nulls,
  withAlpha,
  zonedStringToUtcSeconds,
  DEFAULT_TIMEZONE,
}) {
  registerIndicator({
    id: 'ex-displaced-zones',
    name: 'Displaced Cloud and Zones',
    category: 'Custom',
    placement: 'onchart',

    inputs: [
      { key: 'length', type: 'number', label: 'Length', default: 20, min: 2, max: 400, step: 1 },
      { key: 'shift', type: 'number', label: 'Displacement', default: 26, min: 0, max: 200, step: 1,
        tooltip: 'Bars to paint the cloud ahead of the data. The last few land in the right margin, past the newest candle.' },
      // 2.4.0: a wall-clock instant in the chart's zone, carried as a string so
      // a layout saved in one zone restores to the same clock in another.
      { key: 'anchor', type: 'time', label: 'Zone anchor', default: '',
        tooltip: 'Optional. YYYY-MM-DD HH:MM in the chart timezone. Blank measures from the first loaded bar.' },
      { key: 'up', type: 'color', label: 'Cloud', default: '#26a69a' },
      { key: 'down', type: 'color', label: 'Cloud down', default: '#ef5350' },
    ],

    plots: [
      // 2.4.0: same data, painted `shift` bars to the right. Both edges carry
      // the same offset, so the fill between them follows.
      { key: 'fast', type: 'line', title: 'Fast', style: { color: '#26a69a', lineWidth: 1 }, offset: 26 },
      { key: 'slow', type: 'line', title: 'Slow', style: { color: '#ef5350', lineWidth: 1 }, offset: 26 },
      // 2.4.0: a candle plot coloured body, wick and border apart. `colorBy`
      // would set all three together, which is the one thing it cannot express.
      {
        key: 'ha',
        type: 'candlestick',
        title: 'Smoothed',
        ohlc: { open: 'haOpen', high: 'haHigh', low: 'haLow', close: 'haClose' },
        colorParts: ({ index, values, settings }) => {
          const rising = values.haClose[index] != null && values.haOpen[index] != null
            && values.haClose[index] >= values.haOpen[index];
          const base = String(rising ? settings.up : settings.down);
          // A solid wick over a translucent body: the candle reads as an
          // overlay rather than hiding the real one underneath it.
          return { body: withAlpha(base, 0.35), wick: base, border: base };
        },
      },
    ],

    fills: [{ between: ['fast', 'slow'], colorUpKey: 'up', colorDownKey: 'down', opacity: 0.12 }],

    calc(bars, settings) {
      const n = bars.length;
      const length = Math.max(2, Math.floor(Number(settings.length) || 20));
      const close = sourceValues(bars, 'close');
      const fast = sma(close, Math.max(2, Math.floor(length / 2)));
      const slow = sma(close, length);

      // Heikin Ashi, carried as four columns for the candle plot above.
      const haOpen = new Array(n).fill(NaN);
      const haHigh = new Array(n).fill(NaN);
      const haLow = new Array(n).fill(NaN);
      const haClose = new Array(n).fill(NaN);
      for (let i = 0; i < n; i++) {
        const b = bars[i];
        haClose[i] = (b.open + b.high + b.low + b.close) / 4;
        haOpen[i] = i === 0 ? (b.open + b.close) / 2 : (haOpen[i - 1] + haClose[i - 1]) / 2;
        haHigh[i] = Math.max(b.high, haOpen[i], haClose[i]);
        haLow[i] = Math.min(b.low, haOpen[i], haClose[i]);
      }

      return {
        fast: nulls(fast),
        slow: nulls(slow),
        haOpen: nulls(haOpen),
        haHigh: nulls(haHigh),
        haLow: nulls(haLow),
        haClose: nulls(haClose),
      };
    },

    /**
     * A supply zone from the recent range, projected past the last bar.
     *
     * The projection is in TIME, not in bars: the last bar's spacing times the
     * shift. That is what the scale extrapolates, so the box lands exactly
     * where the displaced cloud above it does.
     */
    draws({ bars, values, settings }) {
      const n = bars.length;
      if (n < 3) return [];
      const zone = String(settings.timezone ?? '') || DEFAULT_TIMEZONE;
      const shift = Math.max(0, Math.floor(Number(settings.shift) || 0));
      const step = bars[n - 1].time - bars[n - 2].time;
      const from = (() => {
        const typed = String(settings.anchor ?? '').trim();
        if (typed === '') return bars[Math.max(0, n - 60)].time;
        const t = zonedStringToUtcSeconds(typed, zone);
        return Number.isFinite(t) ? t : bars[Math.max(0, n - 60)].time;
      })();

      const highs = bars.map((b) => b.high);
      const lows = bars.map((b) => b.low);
      const range = atr(highs, lows, bars.map((b) => b.close), 14);
      const width = Number.isFinite(range[n - 1]) ? range[n - 1] : (bars[n - 1].high - bars[n - 1].low);
      const top = Math.max(...highs.slice(Math.max(0, n - 60)));
      const up = String(settings.up ?? '#26a69a');

      return [
        {
          kind: 'box',
          from: { time: from, price: top },
          to: { time: bars[n - 1].time + step * shift, price: top - width },
          color: up,
          fillColor: up,
          opacity: 0.1,
          text: 'Supply',
          // 2.4.0: the caption names the zone, the tooltip explains it. Detail
          // that would hide the candles if it were printed on the box.
          tooltip: `Supply zone\ntop ${top.toFixed(2)}\nwidth ${width.toFixed(2)} (1 ATR)\nprojected ${shift} bars`,
          id: 'supply-zone',
        },
        {
          kind: 'label',
          at: { time: bars[n - 1].time + step * shift, price: top },
          text: 'Projection',
          color: up,
          align: 'left',
          tooltip: `Drawn ${shift} bars past the newest candle.\nA drawing anchors to a time, so it may leave the bars; a plot column may not.`,
          id: 'projection-label',
        },
      ];
    },

    /** 2.4.0: `fontSize: 'auto'` fits each cell to its row and its column. */
    table({ bars, values }) {
      const n = bars.length;
      if (n === 0) return null;
      const last = (col) => {
        for (let i = n - 1; i >= 0; i--) if (col[i] != null) return col[i].toFixed(2);
        return 'n/a';
      };
      return {
        rows: [
          [{ text: 'Displaced cloud', bold: true }, { text: '' }],
          [{ text: 'Fast' }, { text: last(values.fast), align: 'right' }],
          [{ text: 'Slow' }, { text: last(values.slow), align: 'right' }],
        ],
        options: { position: 'top-right', cellWidth: [96, 64], cellHeight: 16, fontSize: 'auto' },
      };
    },
  });
}

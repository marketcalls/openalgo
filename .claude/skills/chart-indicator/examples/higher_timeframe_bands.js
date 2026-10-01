/**
 * ADVANCED example (2.4.0): a higher timeframe read off the chart's own bars.
 *
 * This is the shape most ported studies need and the one that used to be
 * hand-rolled differently every time: "where is price inside the day's range".
 * `securitySeries` folds the chart's bars into buckets and hands back one value
 * per bar, so nothing is fetched and nothing is a second data source.
 *
 * The three readings are the whole point, and this file uses two of them:
 *
 *   - the default reads the bucket AS IT STOOD at that bar: the day's high so
 *     far, the day's low so far. It never uses a later bar, so the oscillator
 *     is the same on history as it was live.
 *   - `offset: 1` reads the LAST COMPLETED bucket, held constant across the
 *     current one. That is yesterday's range, and it is what the bands draw.
 *
 * The third, `lookahead: true`, reads the bucket's final values on every one of
 * its bars. It repaints. It is here only to reproduce a source that did it.
 *
 * Shape worth copying: the study lives in its own pane (the 0..100 position),
 * while three of its plots carry `overlay: true` so the bands and the fill sit
 * on the candles where they belong. One indicator, one set of inputs, two panes.
 */

export default function ({
  registerIndicator,
  securitySeries,
  IndicatorInputError,
  sourceValues,
  nulls,
  withAlpha,
  DEFAULT_TIMEZONE,
  isIntradayInterval,
}) {
  registerIndicator({
    id: 'ex-htf-bands',
    name: 'Higher Timeframe Range',
    category: 'Custom',
    placement: 'pane',

    inputs: [
      // 2.4.0: a timeframe the engine can bucket by. The settings dialog shows
      // the registered codes, so the study can never be handed '5min'.
      { key: 'tf', type: 'interval', label: 'Higher timeframe', default: '1d',
        tooltip: 'The bucket the range is measured over. Leave on the chart interval to disable the fold.' },
      { key: 'session', type: 'text', label: 'Session', default: '0915-1530',
        tooltip: 'Anchors sub-day buckets to the session open. A 30m bucket on a 09:15 open then runs 09:15 to 09:45.' },
      { key: 'showPrev', type: 'boolean', label: 'Show previous range', default: true },
      { key: 'prevUp', type: 'color', label: 'Previous range', default: '#4f8cff' },
    ],

    plots: [
      // The study's own pane: where price sits inside the current bucket.
      { key: 'pos', type: 'line', title: 'Range %', style: { color: '#f5a623', lineWidth: 2 } },
      // The bands belong on the candles, so they are sent there individually.
      { key: 'prevHigh', type: 'step', title: 'Prev high', style: { color: '#4f8cff', lineWidth: 1 }, overlay: true },
      { key: 'prevLow', type: 'step', title: 'Prev low', style: { color: '#4f8cff', lineWidth: 1 }, overlay: true },
    ],

    // 2.4.0: the band follows its plots onto the price pane. Without `overlay`
    // it would be shaded in the study pane, where neither edge is drawn.
    fills: [{ between: ['prevHigh', 'prevLow'], colorUpKey: 'prevUp', colorDownKey: 'prevUp', opacity: 0.07, overlay: true }],

    levels: () => [
      { price: 100, title: 'High', color: '#ef5350', lineStyle: 'dotted' },
      { price: 50, title: 'Mid', color: '#8892a6', lineStyle: 'dotted' },
      { price: 0, title: 'Low', color: '#26a69a', lineStyle: 'dotted' },
    ],
    range: () => ({ min: -5, max: 105 }),

    calc(bars, settings, store, ctx) {
      const tf = String(settings.tf ?? '').trim();
      const zone = String(settings.timezone ?? '') || DEFAULT_TIMEZONE;
      const n = bars.length;
      const close = sourceValues(bars, 'close');

      // A cleared select arrives as '', which means "the chart's own interval":
      // there is no coarser bucket to fold into, so every bar is its own.
      //
      // Every column the hooks read is returned here too, not just the plots.
      // `markers` and `alerts` below read `brokeUp`, and a hook that reads a
      // column this branch forgot throws inside the runtime rather than drawing
      // nothing, which is why the gate checks the hooks on cleared inputs.
      if (tf === '') {
        const flat = new Array(n).fill(50);
        const none = new Array(n).fill(NaN);
        return {
          pos: nulls(flat),
          prevHigh: nulls(none),
          prevLow: nulls(none),
          brokeUp: nulls(none),
          prevHighRaw: nulls(none),
        };
      }

      // 2.4.0: refuse an input the user can fix, in words they can act on. The
      // runtime publishes this on the study's data status and keeps the chart
      // drawing; before 2.4.0 a throw here took the whole frame down.
      if (ctx?.interval !== undefined && tf === ctx.interval) {
        throw new IndicatorInputError(
          `Higher timeframe ${tf} is the chart's own interval. Pick a coarser one, or clear it.`,
        );
      }

      // The session only anchors intraday buckets. Passing one to a daily fold
      // is harmless but says something untrue, so it is only sent when it means
      // something.
      const spec = String(settings.session ?? '').trim();
      const opts = spec !== '' && isIntradayInterval(tf)
        ? { timezone: zone, session: spec }
        : { timezone: zone };

      let current;
      let previous;
      try {
        current = securitySeries(bars, tf, opts);
        // The last completed bucket, held constant across the current one.
        previous = securitySeries(bars, tf, { ...opts, offset: 1 });
      } catch (e) {
        // securitySeries itself throws IndicatorInputError for a tick or volume
        // interval and for an unreadable session. Let it through: it is already
        // the right kind of error with the right message.
        throw e;
      }

      const showPrev = settings.showPrev !== false;
      const pos = new Array(n).fill(NaN);
      const prevHigh = new Array(n).fill(NaN);
      const prevLow = new Array(n).fill(NaN);

      for (let i = 0; i < n; i++) {
        const hi = current.high[i];
        const lo = current.low[i];
        // Guard the divide: a bucket whose first bar is flat has zero span.
        if (hi != null && lo != null && hi > lo && Number.isFinite(close[i])) {
          pos[i] = ((close[i] - lo) / (hi - lo)) * 100;
        }
        if (!showPrev) continue;
        const ph = previous.high[i];
        const pl = previous.low[i];
        if (ph != null) prevHigh[i] = ph;
        if (pl != null) prevLow[i] = pl;
      }

      // Carried for the hooks below. A column only a hook reads is still a
      // column, but it is not a plot, so it is not declared in `plots`.
      const brokeUp = new Array(n).fill(NaN);
      for (let i = 0; i < n; i++) {
        const ph = previous.high[i];
        if (ph == null || !Number.isFinite(close[i])) continue;
        const was = i > 0 ? close[i - 1] : NaN;
        const prevBand = i > 0 ? previous.high[i - 1] : NaN;
        if (Number.isFinite(was) && prevBand != null && Number.isFinite(prevBand)) {
          brokeUp[i] = close[i] > ph && was <= prevBand ? 1 : 0;
        }
      }

      return {
        pos: nulls(pos),
        prevHigh: nulls(prevHigh),
        prevLow: nulls(prevLow),
        brokeUp: nulls(brokeUp),
        prevHighRaw: nulls(previous.high.map((v) => (v == null ? NaN : v))),
      };
    },

    // 2.4.0: pinned to the pane edge rather than to a price, so the row stays
    // put whatever the scale does and needs no bar under it.
    markers({ bars, values }) {
      const out = [];
      for (let i = 0; i < bars.length; i++) {
        if (values.brokeUp[i] !== 1) continue;
        out.push({
          time: bars[i].time,
          position: 'paneBottom',
          shape: 'cross',
          size: 'small',
          color: '#26a69a',
        });
      }
      return out;
    },

    background({ values, settings }) {
      const up = String(settings.prevUp ?? '#4f8cff');
      return values.pos.map((v) => (v == null ? null : v > 100 || v < 0 ? withAlpha(up, 0.1) : null));
    },

    // 2.4.0: the message is built from the bar that fired, so the notification
    // carries the level instead of a fixed sentence.
    alerts: [
      {
        id: 'break-prev-high',
        title: 'Broke the previous range high',
        message: ({ bars, values, index }) =>
          `Closed ${bars[index].close} above the previous high ${values.prevHighRaw[index]}`,
        when: ({ values, index }) => values.brokeUp[index] === 1,
      },
    ],
  });
}

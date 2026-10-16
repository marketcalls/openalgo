let app;
export function initTimezone(a) { app = a; }

// ── chart timezone ─────────────────────────────────────────────────────
// The zone is the engine's: it is a schema control on the Axes tab and
// `chart.setTimezone()` behind it, so nothing here builds a picker. What the
// demo does keep is a copy of the chosen zone, because render() throws the
// chart away and builds a new one on every chart-type switch, exactly like
// activeIndicators: the engine persists the zone in getState(), but a
// rebuilt chart starts on the default again unless we hand it back.
export const DEFAULT_TZ = 'Asia/Kolkata';

/** Mirror the chart's zone back into the demo's own copy. */
export function syncTimezoneFromChart() {
  if (app.chart && typeof app.chart.timezone === 'function') app.chartTimezone = app.chart.timezone();
}

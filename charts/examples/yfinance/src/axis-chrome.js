let app;
export function initAxisChrome(a) { app = a; }

// ── axis chrome ────────────────────────────────────────────────────────
// The corner clock and the countdown row inside the last-price tag are
// engine options: a chart that upgrades should keep drawing the axes it
// always drew, so neither turns itself on. The reference host is exactly
// where they should be visible, so the demo asks for both, and then carries
// whatever the settings dialog leaves behind across a chart rebuild the same
// way it carries the timezone.
//
// The corner clock gives way to the bottom bar's, which tells the same time a
// few pixels below it and opens the zone menu besides. So it is drawn where
// the bar is not (the phone shell hides the bar) and follows the bar in and
// out of view, over whatever a restored layout says, until the Corner clock
// switch in the settings is used: that choice is the user's, and it stands
// wherever the page is shown and after a reload.
const axisChrome = { sessionClock: true, barCountdown: true };
const CLOCK_KEY = 'oa-charts:corner-clock';   // under the page's storage prefix (persist.js)
let clockChoice;
export function applyAxisChrome() {
  if (!app.chart || typeof app.chart.setAxisChromeOptions !== 'function') return;
  app.chart.setAxisChromeOptions(axisChrome);
  followBottombar();
  app.chart.on('state:restore:end', followBottombar);
}
/** Show the corner clock where the bottom bar is not, or where the user chose. */
export function followBottombar() {
  if (clockChoice === undefined) {
    let saved = null;
    try { saved = localStorage.getItem(CLOCK_KEY); } catch (_) { /* private mode: no earlier choice */ }
    clockChoice = saved === 'true' ? true : saved === 'false' ? false : null;
  }
  if (!app.bottombar || !app.chart || typeof app.chart.setAxisChromeOptions !== 'function') return;
  const on = clockChoice ?? barHidden();
  axisChrome.sessionClock = on;
  if (Boolean(app.chart.axisChromeOptions().sessionClock) !== on) app.chart.setAxisChromeOptions({ sessionClock: on });
}
const barHidden = () => app.bottombar.el.getClientRects().length === 0;
export function syncAxisChromeFromChart() {
  if (!app.chart || typeof app.chart.axisChromeOptions !== 'function') return;
  const now = app.chart.axisChromeOptions();
  const on = Boolean(now.sessionClock);
  if (app.bottombar && on !== Boolean(axisChrome.sessionClock)) {
    // Switched to what the bar would show anyway (an edit taken back, a
    // Cancel), the clock goes back to following the bar.
    clockChoice = on === barHidden() ? null : on;
    try {
      if (clockChoice === null) localStorage.removeItem(CLOCK_KEY);
      else localStorage.setItem(CLOCK_KEY, String(clockChoice));
    } catch (_) { /* private mode: the choice lasts the visit */ }
  }
  Object.assign(axisChrome, now);
}

// The status-line switches and the trade palette are the chart's, and a
// chart-type switch throws the chart away: without these two copies, every
// Readout and Trading choice silently reverted the moment someone picked
// Heikin Ashi. Same contract as the timezone above - read back from the
// chart after a settings write, hand it back on the next build.
const statusLineChoice = {};
export function applyStatusLineChoice() {
  if (app.chart && Object.keys(statusLineChoice).length) app.chart.setStatusLineOptions(statusLineChoice);
}
export function syncStatusLineFromChart() {
  if (app.chart && typeof app.chart.statusLineOptions === 'function') Object.assign(statusLineChoice, app.chart.statusLineOptions());
}

// `tradingSettings()` answers in resolved names (`long`) and
// `setTradingSettings` takes patch names (`longColor`), so carrying the
// choice across a rebuild means translating between the two.
const TRADE_PATCH_KEY = {
  long: 'longColor', short: 'shortColor', order: 'orderColor',
  tp: 'tpColor', sl: 'slColor', buy: 'buyColor', sell: 'sellColor',
};
const tradeChoice = {};
export function applyTradeChoice() {
  if (app.chart && Object.keys(tradeChoice).length) app.chart.setTradingSettings(tradeChoice);
}
export function syncTradeChoiceFromChart() {
  if (!app.chart || typeof app.chart.tradingSettings !== 'function') return;
  const resolved = app.chart.tradingSettings();
  for (const key in TRADE_PATCH_KEY) tradeChoice[TRADE_PATCH_KEY[key]] = resolved[key];
}

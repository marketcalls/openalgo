import * as engine from '/dist/openalgo-charts.mjs';
import { el, onEscape } from './ui.js';
import { fetchBars, abortFetch } from './feed.js';
import { renderToolbar, ticon } from './toolbar.js';
import { attachTip } from './hover.js';
import { setLegend } from './volume.js';
import { capturePaneTarget } from './pane-target.js';
import { replayBarEndTime } from './replay-timing.js';
import { requestVariant, sessionOf } from './session.js';
import { INTERVAL_MAX_DAYS, PERIOD_DAYS } from './intervals.js';
export { replayBarEndTime } from './replay-timing.js';

// Read off the namespace rather than named above on purpose: a missing named
// import fails the whole module at link time, and a demo served against a
// dist/ built before replay shipped should still draw a chart and simply
// report the feature as unavailable.
const { ReplayController, ReplayGroup, TextWatermark, ReplayShade } = engine;

let app;

// ── market replay ──────────────────────────────────────────────────────
// ReplayController owns the playhead and feeds the series a prefix of the
// session; indicators reconstruct themselves because the chart recomputes
// them from the shortened history. Everything below is the transport bar.
export const REPLAY_SPEEDS = [0.5, 1, 2, 5, 10];
let replaySpeed = 1;
/** Base-interval bars under the displayed ones, for intra-bar replay. */
let replaySubBars = new Map();
let replayLoadRevision = 0;
// The session is part of the key: extended finer bars are another series.
const requestKey = req => JSON.stringify([req.symbol, req.interval, req.period, sessionOf(req)]);
const readouts = new WeakMap();
let controlHomes = [];
export function syncReplayAlertPause() {
  const active = Boolean(app.workspaceLoading || app.replay || app.replayPicking || app.replayLoading);
  app.alerts?.setPaused(active || Boolean(app.loading || app.loadFailed));
  app.alerts2?.setPaused(active || Boolean(app.loading2 || app.loadFailed2));
}

function captureReplayTarget(pane) {
  const target = capturePaneTarget(app, pane);
  if (!target) return null;
  const timezone = target.chart.timezone?.() || app.chartTimezone;
  return { ...target, timezone, chartType: target.pane === 2 ? app.p2.chartType : el('ctype')?.value,
    series: target.chart.primarySeries?.() || (target.pane === 1 ? app.price : null),
    node: el(target.pane === 2 ? 'chart2' : 'chart'), shades: [], mark: null,
    current: () => target.current() && (target.chart.timezone?.() || app.chartTimezone) === timezone };
}
const ready = target => target?.current() && !target.chart.isDestroyed && target.series
  && !app[target.pane === 2 ? 'loading2' : 'loading'] && !app[target.pane === 2 ? 'loadFailed2' : 'loadFailed'];
const owner = () => app.replayTarget || captureReplayTarget();
const targets = () => app.replayTargets || [];
const activeTargets = () => app.replayScope === 'all' ? targets() : targets().filter(target => target === app.replayTarget);
const memberState = chart => app.replay?.state().members.find(member => targets().some(target => target.chart === chart && String(target.pane) === member.id));

function captureSession(target) {
  app.replayTarget = target;
  app.replayTargets = [target, captureReplayTarget(target.pane === 1 ? 2 : 1)].filter(Boolean);
  app.replayScope = 'focused';
}

function validateAllTargets() {
  const visible = [app.chart, app.chart2].filter(chart => chart && !chart.isDestroyed);
  const ids = app.replay && new Set(app.replay.state().members.map(member => member.id));
  for (const chart of visible) {
    const target = targets().find(item => item.chart === chart);
    if (target?.unavailable) throw new Error(target.unavailable);
    if (!ready(target) || (ids && !ids.has(String(target.pane)))) {
      throw new Error('Wait for chart history, then start a new replay to include all charts');
    }
  }
}

function syncScopeControls() {
  const all = app.replayScope === 'all';
  // The pick prompt has no owner label, so its toggle names the chart. The
  // transport bar already names it in #rp-owner, and a toggle saying the same
  // thing beside it read as "Chart 1 Chart 1": there it names the scope.
  const labels = {
    'rp-pick-scope': all ? 'All charts' : `Chart ${app.replayTarget?.pane || 1}`,
    'rp-scope': all ? 'All charts' : 'This chart',
  };
  for (const [id, label] of Object.entries(labels)) {
    const button = el(id);
    if (!button) continue;
    button.textContent = label;
    // Named for the scope in force, so no pressed state says it a second time.
    button.setAttribute('aria-label', 'Replay scope: ' + label);
    button.disabled = Boolean(app.replayLoading);
  }
}

export function setReplayScope(scope) {
  if (app.replayLoading || !app.replayTarget) return;
  if (scope !== 'focused' && scope !== 'all') return;
  try {
    if (scope === 'all') validateAllTargets();
    app.replay?.setScope(scope, String(app.replayTarget.pane));
    app.replayScope = scope;
    mountControls(app.replayTarget);
    if (app.replayPicking) setShadeIndex(app.replayPickIndex);
    showReplayMark(Boolean(app.replay));
    syncScopeControls(); syncReplayBar();
  } catch (error) { el('status').textContent = error.message; }
}
const toggleScope = () => setReplayScope(app.replayScope === 'all' ? 'focused' : 'all');

function mountControls(target) {
  // Either chart can occupy fullscreen while replay retains its captured owner.
  const parent = el('split') || target.node.parentElement || target.node.parentNode;
  if (parent) for (const [node] of controlHomes) parent.appendChild(node);
}

function releaseTarget(destroyedPane) {
  for (const target of targets()) {
    target.node.classList.remove('is-picking');
    if (!target.chart.isDestroyed && target.pane !== destroyedPane) {
      for (const primitive of [...target.shades, target.mark].filter(Boolean)) target.chart.removePrimitive?.(primitive);
    }
  }
  app.replayTarget = null;
  app.replayTargets = [];
  app.replayPickIndex = null;
  for (const [node, home] of controlHomes) if (home) home.appendChild(node);
}

/** Each chart owns its input listeners; linked hover cannot choose a replay bar. */
export function attachReplay(chart, pane, readout) {
  readouts.set(chart, readout);
  const off = [];
  for (const event of ['replay:start', 'replay:frame', 'replay:play', 'replay:pause', 'replay:end', 'replay:stop']) {
    off.push(chart.on(event, state => {
      if (!targets().some(target => target.chart === chart)) return;
      syncReplayBar();
      readout?.(event === 'replay:stop' ? chart.primarySeries()?.getData().at(-1) : state?.bar ?? null);
    }));
  }
  off.push(chart.on('crosshair:move', event => {
    if (event.source !== 'linked') movePick(event.index, chart);
  }));
  off.push(chart.on('click', () => {
    if (app.replayTarget?.chart === chart && app.replayPicking && app.replayPickIndex !== null) startReplayAt(app.replayPickIndex);
  }));
  off.push(chart.on('data:context', () => {
    const target = targets().find(item => item.chart === chart);
    if (target && !target.current()) exitReplay(pane);
  }));
  off.push(chart.on('destroy', () => {
    exitReplay(pane, true);
    for (const dispose of off.splice(0)) dispose();
    readouts.delete(chart);
  }));
}

/**
 * The interval a displayed bar is built from, so replay can form one in
 * front of the user instead of landing it whole.
 *
 * One rung down, not the finest available: 1-minute bars under a daily chart
 * would be 375 steps per candle, which is not a replay, it is a stall. The
 * pairs stop where the feed does, and an interval with no rung below it
 * simply replays bar by bar as before.
 */
export const REPLAY_SUB_INTERVAL = {
  '5m': '1m', '15m': '5m', '30m': '15m', '60m': '15m', '1h': '15m',
  '1d': '60m', '1wk': '1d', '1mo': '1d', '1q': '1d',
};

/**
 * How many steps a candle takes when that finer rung has no bars for it: the
 * finer bars it would have held, so a simulated candle forms at the pace a real
 * one does (five for 5 minutes over 1 minute, seven hours in an NSE session).
 * yfinance keeps about a week of 1-minute bars, so every older 5-minute candle
 * takes this path; the transport marks each of its steps as simulated.
 */
export const REPLAY_SIMULATED_STEPS = {
  '5m': 5, '15m': 3, '30m': 2, '60m': 4, '1h': 4,
  '1d': 7, '1wk': 5, '1mo': 21, '1q': 63,
};

/** Where the newest bar sits while replay is running (or the real one). */
export const lastBar = () => {
  const member = memberState(app.chart);
  return member?.active ? member.state.bar : app.currentBars[app.currentBars.length - 1];
};

/**
 * Open at the left edge of what the user is looking at, so replay starts
 * where their attention already is. Floored so an indicator has some history
 * to compute from rather than opening on a single bar.
 */
export function replayStartIndex(total) {
  let from = 0;
  try {
    const target = owner();
    from = Math.round(target.chart.timeScale.getVisibleLogicalRange().from);
    // A transformed chart's view counts elements: start from the bar the leftmost one formed on.
    if (transformed(target)) {
      const element = target.chart.primaryBars()[Math.max(0, from)];
      from = element ? lastWhere(target.series.getData(), t => t <= element.time) : 0;
    }
  } catch (_) { from = 0; }
  const floor = Math.min(20, total - 1);
  return Math.max(floor, Math.min(total - 1, from));
}

/**
 * Step one: choose where to start.
 *
 * Replay used to open at the left edge of the viewport, which quietly
 * decided the exercise for the user. The bar you start from is the whole
 * premise -- "from here, what happens next?" -- so it is picked, and while
 * it is being picked everything to the right is greyed. Choosing a start
 * while able to read the next twenty bars is choosing on hindsight, which is
 * the one thing replay exists to remove.
 */
export function enterReplay() {
  if (app.workspaceLoading || app.replay || app.replayPicking || app.replayLoading) return;
  const target = captureReplayTarget();
  if (!ready(target)) return;
  if (!ReplayGroup) { el('status').textContent = 'shared replay is not in this build of dist/'; return; }
  const bars = target.series.getData();
  if (bars.length < 2) { el('status').textContent = 'replay needs bars'; return; }
  captureSession(target);
  mountControls(target);
  app.replayPicking = true;
  syncReplayAlertPause();
  app.replayPickIndex = replayStartIndex(bars.length);
  setShadeIndex(app.replayPickIndex);
  target.node.classList.add('is-picking');
  el('replaypick').hidden = false;
  syncPickHint();
  syncScopeControls();
  renderToolbar();
  el('status').textContent = `Chart ${target.pane}: choose a bar; replay starts at its close (Esc to cancel)`;
}

/**
 * Whether the chart transforms the bars replay walks. Its own index then
 * counts the elements it draws (bricks, columns), not those bars, so a pick
 * and a cut cross between the two by time.
 */
function transformed(target) {
  const primary = target.chart.primarySeries?.();
  return Boolean(primary && target.chart.seriesTransform?.(primary));
}

/** The last index in a time-ordered list whose time passes `test`, or -1. */
function lastWhere(list, test) {
  let from = 0, to = list.length;
  while (from < to) {
    const mid = (from + to) >>> 1;
    if (test(list[mid].time)) from = mid + 1;
    else to = mid;
  }
  return from - 1;
}

/**
 * Move (or raise, or clear) the veil on every pane.
 *
 * Built lazily and per pane because a pane can appear while the picker is
 * open -- an oscillator added mid-selection -- and a pane left bright to the
 * right of the cut shows exactly what the shade is hiding on the one above.
 */
export function setShadeIndex(index) {
  const owner = app.replayTarget;
  if (!ReplayShade || !owner) return;
  const picked = owner.series.getData()[index];
  const time = picked && replayBarEndTime(owner.request.interval, owner.timezone)(picked);
  for (const target of targets()) {
    const active = index !== null && activeTargets().includes(target);
    target.node.classList.toggle('is-picking', active);
    if (target.chart.isDestroyed) continue;
    const panes = target.chart.panes ? target.chart.panes() : [];
    // The cut line belongs on the price pane, wherever it sits; the other panes only dim.
    const price = typeof target.chart.primaryPaneIndex === 'function' ? target.chart.primaryPaneIndex() : 0;
    for (let i = target.shades.length; i < panes.length; i++) {
      const shade = new ReplayShade({ index: null, lineVisible: i === price });
      target.chart.addPrimitive(shade, i);
      target.shades.push(shade);
    }
    let cut = null;
    if (active) {
      const bars = target.series.getData(), end = replayBarEndTime(target.request.interval, target.timezone);
      // The last bar closed when the picked one did: on its own chart, the picked bar.
      let closed = index;
      if (target !== owner) {
        let from = 0, to = bars.length;
        while (from < to) {
          const mid = (from + to) >>> 1;
          if (end(bars[mid]) <= time) from = mid + 1;
          else to = mid;
        }
        closed = from - 1;
      }
      // A transformed chart is cut after the last element those bars formed.
      // Elements are dated at the bar they form on (a second apart when one bar
      // forms several), so the next bar's time bounds them. Comparing an
      // element's own time with the picked close instead would leave in view what
      // a longer bar, still open at that close, had formed.
      const next = bars[closed + 1];
      if (!transformed(target)) cut = closed;
      else cut = next ? lastWhere(target.chart.primaryBars(), t => t < next.time) : target.chart.primaryBars().length - 1;
    }
    for (const shade of target.shades) shade.setOptions({ index: cut });
  }
}

/** The hovered bar, while the picker is open. */
export function movePick(index, chart = app.replayTarget?.chart) {
  if (!app.replayPicking || index === null || index === undefined) return;
  const target = app.replayTarget;
  if (!target || target.chart !== chart) return;
  const bars = target.series.getData();
  const total = bars.length;
  if (total === 0) return;
  // Over a transformed chart the crosshair is on an element: replay starts from the bar it formed on.
  const shown = transformed(target) ? target.chart.primaryBars() : null;
  const element = shown?.[Math.max(0, Math.min(shown.length - 1, Math.round(index)))];
  const at = shown ? (element ? lastWhere(bars, t => t <= element.time) : -1) : Math.round(index);
  const clamped = Math.max(0, Math.min(total - 1, at));
  if (clamped === app.replayPickIndex) return;
  app.replayPickIndex = clamped;
  setShadeIndex(clamped);
  syncPickHint();
}

export function syncPickHint() {
  const bars = app.replayTarget?.series.getData() || [];
  const b = bars[app.replayPickIndex];
  const hint = el('rp-picked');
  if (hint) hint.textContent = b ? barStamp(replayBarEndTime(owner().request.interval, owner().timezone)(b), true) : '';
}

export function cancelPick(destroyedPane) {
  if (!app.replayPicking && !app.replayLoading) return;
  replayLoadRevision++;
  for (const target of targets()) abortFetch('replay:' + target.pane);
  app.replayLoading = false;
  app.replayPicking = false;
  releaseTarget(destroyedPane);
  syncReplayAlertPause();
  el('replaypick').hidden = true;
  renderToolbar();
  el('status').textContent = 'replay cancelled';
}

/**
 * Step two: walk forward from the chosen bar.
 *
 * The shade comes off here rather than staying on the un-walked future,
 * because replay truncates the series: past the playhead there is nothing
 * left to cover.
 */
export async function startReplayAt(index) {
  if (app.workspaceLoading || app.replay || app.replayLoading) return;
  const target = owner();
  if (!ready(target)) return;
  const bars = target.series.getData();
  if (bars.length < 2) return;
  if (!app.replayTarget) captureSession(target);
  mountControls(target);
  const revision = ++replayLoadRevision;
  app.replayLoading = true;
  app.replayPicking = false;
  syncReplayAlertPause();
  el('replaypick').hidden = true;
  setShadeIndex(null);
  syncScopeControls();
  renderToolbar();
  try {
    if (!ReplayGroup) throw new Error('shared replay is not in this build');
    if (app.replayScope === 'all') validateAllTargets();
    const captured = targets().filter(ready);
    const loaded = await Promise.all(captured.map(async item => ({ target: item, sub: await loadReplaySubBars(item) })));
    if (revision !== replayLoadRevision) return;
    if (!target.current() || (app.replayScope === 'all' && captured.some(item => !ready(item)))) { cancelPick(); return; }
    const fallback = [];
    const members = loaded.filter(item => ready(item.target)).map(({ target: item, sub }) => {
      const timing = { barEndTime: replayBarEndTime(item.request.interval, item.timezone),
        subBarEndTime: replayBarEndTime(REPLAY_SUB_INTERVAL[item.request.interval], item.timezone) };
      const steps = REPLAY_SIMULATED_STEPS[item.request.interval];
      const options = { series: [item.series], timing, ...(steps ? { simulate: { steps } } : {}) };
      try { new ReplayController(item.chart, { ...options, autoStart: false }); }
      catch {
        item.unavailable = `Chart ${item.pane} has overlapping or unordered candle times. Use time-based chart data.`;
        if (app.replayScope === 'all' || item === target) throw new Error(item.unavailable);
        return null;
      }
      // Finer history may fall back. The group still validates every primary
      // snapshot before entry, so a bad primary is never hidden by fallback.
      if (sub?.length) {
        try {
          new ReplayController(item.chart, { ...options, subBars: sub, autoStart: false });
          options.subBars = sub;
        } catch { sub = null; }
      }
      if (REPLAY_SUB_INTERVAL[item.request.interval] && !sub?.length) fallback.push(`Chart ${item.pane}`);
      return { id: String(item.pane), chart: item.chart, options };
    }).filter(Boolean);
    const picked = bars[Math.max(0, Math.min(bars.length - 1, Math.floor(index)))];
    app.replay = new ReplayGroup(members, {
      scope: app.replayScope, focusedId: String(target.pane),
      startTime: replayBarEndTime(target.request.interval, target.timezone)(picked),
      barMs: 1000, speed: replaySpeed,
      onChange: state => {
        if (state.destroyed && app.replay) { exitReplay(); return; }
        syncReplayBar();
      },
    });
    app.replayLoading = false;
    showReplayMark(true); buildReplayBar();
    el('replaybar').hidden = false;
    syncScopeControls(); syncReplayBar(); renderToolbar();
    el('status').textContent = fallback.length
      ? `${fallback.join(', ')}: finer history unavailable; candles form along a simulated path, marked Simulated`
      : 'Replay advances by available observations; candles without finer history form along a simulated path, marked Simulated';
  } catch (error) {
    if (revision !== replayLoadRevision) return;
    if (app.replay) exitReplay();
    else cancelPick();
    const reason = error.message.includes('replay time')
      ? 'Candle times overlap or are unordered. Check the intervals or use time-based chart data.' : error.message;
    el('status').textContent = 'Replay could not start: ' + reason;
  }
}

/** Periods the history endpoint serves, with their length in days, shortest first. */
const FINER_PERIODS = [['5d', 5], ['1mo', 31], ['3mo', 92], ['6mo', 186], ['1y', 366]];

/**
 * The period to ask the finer interval for: the chart's own, unless that is
 * longer than the source keeps for the finer interval, then the longest it does
 * keep. A 5-minute chart over a month asks for five days of 1-minute bars, not
 * a month the source refuses outright, so the last week forms from real bars
 * and only the older candles are simulated.
 */
export function finerPeriod(finer, period) {
  const cap = INTERVAL_MAX_DAYS[finer];
  const days = PERIOD_DAYS[period];
  if (cap === undefined || days === undefined || days <= cap) return period;
  let best = FINER_PERIODS[0][0];
  for (const [name, length] of FINER_PERIODS) if (length <= cap) best = name;
  return best;
}

/**
 * The base-interval session under the displayed one.
 *
 * Each participant owns its request slot. Failures return no finer data so
 * the caller can identify the completed-candle fallback in the status line.
 */
export async function loadReplaySubBars(target = owner()) {
  if (!target) return null;
  const req = target.request;
  const key = requestKey(req) + ':' + target.timezone;
  const finer = REPLAY_SUB_INTERVAL[req.interval];
  if (!finer) return null;
  // A transformed chart takes the finer bars too: the chart applies its
  // transform to every frame, so its bricks form as the finer bars land.
  if (replaySubBars.has(key)) return replaySubBars.get(key);
  const revision = replayLoadRevision;
  try {
    const bars = await fetchBars(req.symbol, finer, finerPeriod(finer, req.period), { slot: 'replay:' + target.pane, timezone: target.timezone,
      variant: requestVariant(req) });
    if (!bars || bars.length === 0) return null;
    if (revision !== replayLoadRevision || !target.current()) return null;
    replaySubBars.set(key, bars);
    if (replaySubBars.size > 2) replaySubBars.delete(replaySubBars.keys().next().value);
    return bars;
  } catch (_) {
    return null;
  }
}

/**
 * The mode marker. A chart replaying August looks exactly like a chart
 * showing today, and reading a live decision off history is the mistake this
 * exists to prevent, so it goes on while replay is on and comes off with it.
 */
export function showReplayMark(on) {
  if (!TextWatermark) return;
  for (const target of targets()) {
    if (target.chart.isDestroyed) continue;
    const active = on && memberState(target.chart)?.active;
    if (active && !target.mark) {
      target.mark = new TextWatermark({ text: 'Replay' }); target.chart.addPrimitive(target.mark);
    } else target.mark?.setOptions({ text: active ? 'Replay' : '' });
  }
}

/**
 * Leave without asking. Used by the confirm dialog, and by anything that is
 * tearing the chart down anyway (a symbol or chart-type change), where a
 * prompt would be asking permission for something already decided.
 */
export function exitReplay(pane, destroyed = false) {
  if (!app) return;
  if (pane !== undefined && !activeTargets().some(target => target.pane === pane)) return;
  cancelPick(destroyed ? pane : undefined);
  if (!app.replay) return;
  const controller = app.replay, captured = targets();
  // Keep the workspace guarded while restoration writes real histories.
  app.replayLoading = true;
  app.replay = null;
  let failure;
  try { controller.destroy(); } catch (error) { failure = error; }
  releaseTarget(destroyed ? pane : undefined);
  app.replayLoading = false;
  syncReplayAlertPause();
  el('replaybar').hidden = true;
  el('replaybar').innerHTML = '';
  el('replayleave').hidden = true;
  for (const target of captured) if (!target.chart.isDestroyed && !(destroyed && target.pane === pane)) {
    const tail = target.series.getData().at(-1);
    const readout = readouts.get(target.chart) || (target.pane === 1 ? setLegend : null);
    readout?.(tail);
  }
  renderToolbar();
  if (failure) el('status').textContent = 'Replay ended with a restoration error: ' + failure.message;
}

/**
 * The user-facing exit. Walking a session is work, and the playhead is the
 * only record of how far it got, so closing the mode confirms rather than
 * discarding it on a mis-click.
 */
export function askExitReplay() {
  if (app.replayPicking || app.replayLoading) { cancelPick(); return; }
  if (!app.replay) return;
  el('replayleave').hidden = false;
}

export function toggleReplayPlay() {
  if (!app.replay) return;
  if (app.replay.state().playing) app.replay.pause();
  else app.replay.play({ speed: replaySpeed });
}

export function cycleReplaySpeed() {
  const at = REPLAY_SPEEDS.indexOf(replaySpeed);
  replaySpeed = REPLAY_SPEEDS[(at + 1) % REPLAY_SPEEDS.length];
  // Re-speeding a running timer goes through play(); paused, the new speed
  // is simply what the next play() will use.
  if (app.replay && app.replay.state().playing) app.replay.play({ speed: replaySpeed });
  syncReplayBar();
}

/** Replay's clock: the bar time, with the clock only where the interval has one. */
export function barStamp(t, withTime = false) {
  const d = new Date(t * 1000);
  const target = owner();
  const timeZone = target?.timezone;
  const date = d.toLocaleDateString('en-GB', { year: 'numeric', month: 'short', day: '2-digit', timeZone });
  if (!withTime && !/[mh]$/.test(target?.request.interval || '')) return date;
  return date + ' ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone });
}

// Built once per replay session; syncReplayBar() then only writes the parts
// that move, so a drag on the scrub bar is not fighting a rebuild every frame.
export function buildReplayBar() {
  const bar = el('replaybar');
  bar.innerHTML = '';
  const btn = (icon, title, onClick, id, parent = bar) => {
    const b = document.createElement('button');
    b.innerHTML = ticon(icon);
    if (id) b.id = id;
    // The label is stored on the node, not captured here: syncReplayBar
    // rewrites play/pause and the step units as the transport moves.
    b.dataset.tip = title;
    b.setAttribute('aria-label', title);
    attachTip(b, () => ({ title: b.dataset.tip, side: 'top' }));
    b.addEventListener('click', onClick);
    parent.appendChild(b);
    return b;
  };

  const label = document.createElement('span');
  label.id = 'rp-owner';
  label.className = 'rcount';
  label.textContent = `Chart ${app.replayTarget?.pane || 1}`;
  bar.appendChild(label);
  const scope = document.createElement('button');
  scope.id = 'rp-scope'; scope.addEventListener('click', toggleScope); bar.appendChild(scope);
  btn('exit', 'Exit replay (puts the chart back)', askExitReplay);
  const actions = document.createElement('div');
  actions.className = 'rp-actions';
  bar.appendChild(actions);
  btn('stepback', 'Step back', () => app.replay && app.replay.stepBack(), 'rp-back', actions);
  btn('play', 'Play', toggleReplayPlay, 'rp-play', actions);
  btn('stepfwd', 'Step forward', () => app.replay && app.replay.step(), 'rp-fwd', actions);

  const scrub = document.createElement('input');
  scrub.type = 'range';
  scrub.id = 'rp-scrub';
  scrub.min = '0';
  scrub.step = '1';
  scrub.title = 'Scrub the session';
  scrub.addEventListener('input', () => app.replay && app.replay.seek(Number(scrub.value)));
  bar.appendChild(scrub);

  const count = document.createElement('span');
  count.className = 'rcount';
  count.id = 'rp-count';
  bar.appendChild(count);
  const sub = document.createElement('span');
  sub.className = 'rsub';
  sub.id = 'rp-sub';
  bar.appendChild(sub);
  // Said on screen, not only in the status line: a simulated step's prices were
  // never traded, and a trader testing a stop against them has to know.
  const simulated = document.createElement('span');
  simulated.className = 'rsim';
  simulated.id = 'rp-sim';
  simulated.textContent = 'Simulated';
  simulated.hidden = true;
  simulated.title = 'No finer bars for this candle: it forms along a path through its own open, high, low and close, and closes on the real candle';
  bar.appendChild(simulated);
  const clock = document.createElement('span');
  clock.className = 'rclock';
  clock.id = 'rp-clock';
  bar.appendChild(clock);

  const speed = document.createElement('button');
  speed.id = 'rp-speed';
  speed.title = 'Playback speed (click to cycle)';
  speed.addEventListener('click', cycleReplaySpeed);
  bar.appendChild(speed);
}

/** Everything the transport shows comes from one state() read. */
export function syncReplayBar() {
  if (!app.replay) return;
  const s = app.replay.state();
  const focused = s.members.find(member => member.id === s.focusedId)?.state;
  const scrub = el('rp-scrub');
  if (scrub) {
    scrub.max = String(Math.max(0, s.total - 1));
    if (Number(scrub.value) !== s.index) scrub.value = String(s.index);
  }
  const count = el('rp-count');
  if (count) count.textContent = `${s.index + 1} / ${s.total}`;
  // Only shown when a bar actually takes more than one step, so a plain
  // whole-bar replay does not carry a permanent "1/1".
  const sub = el('rp-sub');
  if (sub) sub.textContent = focused?.subSteps > 1 ? `${focused.subIndex + 1}/${focused.subSteps}` : '';
  const simulated = el('rp-sim');
  if (simulated) simulated.hidden = !focused?.simulated;
  const back = el('rp-back');
  const fwd = el('rp-fwd');
  const unit = 'one observation';
  if (back) { back.dataset.tip = 'Step back ' + unit; back.setAttribute('aria-label', back.dataset.tip); }
  if (fwd) { fwd.dataset.tip = 'Step forward ' + unit; fwd.setAttribute('aria-label', fwd.dataset.tip); }
  const clock = el('rp-clock');
  if (clock) clock.textContent = s.time === null ? '' : barStamp(s.time, true);
  const play = el('rp-play');
  if (play) {
    play.innerHTML = ticon(s.playing ? 'pause' : 'play');
    play.dataset.tip = s.playing ? 'Pause' : 'Play';
    play.setAttribute('aria-label', play.dataset.tip);
    play.classList.toggle('is-on', s.playing);
  }
  const speed = el('rp-speed');
  if (speed) speed.textContent = replaySpeed + 'x';
}

export function initReplay(a) {
  app = a;
  replayLoadRevision++;
  replaySubBars = new Map();
  replaySpeed = 1;
  app.replayTargets = [];
  app.replayScope = 'focused';
  controlHomes = ['replaybar', 'replaypick', 'replayleave'].map(id => { const node = el(id); return [node, node.parentNode]; });
  el('rp-pick-cancel').addEventListener('click', () => cancelPick());
  el('rp-pick-scope')?.addEventListener('click', toggleScope);
  el('rp-leave-stay').addEventListener('click', () => { el('replayleave').hidden = true; });
  el('rp-leave-go').addEventListener('click', () => exitReplay());
  onEscape(() => {
    if (!el('replayleave').hidden) { el('replayleave').hidden = true; return; }
    if (app.replayPicking || app.replayLoading) cancelPick();
  }, document);
}

/**
 * The bottom bar: a thin strip under the chart. On the left, preset ranges
 * and Go to, which move the chart through time; on the right, the market
 * status, the clock and the price scale toggles, which say where the chart
 * stands.
 *
 * It acts on a target read at every use rather than on a chart it was given,
 * so one bar serves a grid by pointing at the focused chart, and a host that
 * rebuilds its chart keeps its bar. Everything it shows is re-read from that
 * target: the range from `range()`, the scale from `priceAxisState`, the zone
 * from `timezone()`, the status from the chart's session calendar. It keeps
 * no copy that could drift from the chart, and no control here does anything
 * the chart's public API does not.
 *
 * Three rules it follows:
 *
 * - **One clock.** The time, the market status and the scale toggles are
 *   re-read on one timer, once a second, stopped while the page is hidden.
 *   The status is worked out again only when it can have changed.
 * - **A control it cannot back is shown greyed, not dropped.** A target with
 *   no ranges greys the range buttons, an interval without time buckets greys
 *   Go to, a chart with no price scale to act on greys the scale toggles.
 * - **Its menus open in the host's overlay stack**, so Escape, focus return
 *   and outside presses behave as they do for every other popup, and a bar at
 *   the bottom of the page opens its menu upward.
 */
import {
  chartSettingsSchema,
  type Chart, type PriceAxisState, type PriceScaleId,
} from 'openalgo-charts';
import { chromeIconSvg } from 'openalgo-charts/draw';
import { glyph, h, type OverlayOptions, type TipController } from './context';
import { timeBuckets, type DateNavigationResult } from './date-navigator';
import { describeNavigation } from './date-navigation-dialog';
import { errorText, widgetText, type WidgetTranslationOptions } from './localization';
import {
  MarketStatusHold, PHASE_GLYPHS, clockText, marketStatusReading, sessionStateShown, utcOffsetLabel,
  type MarketStatusReading,
} from './bottombar-status';
import { DEFAULT_RANGES, type WidgetRange } from './ranges';
import { openMenu, type MenuRow } from './menu';
import { token as v } from './tokens';

/** The bar's height in CSS px. */
export const BOTTOMBAR_HEIGHT = 28;

/**
 * What the bar needs from its host: a document, an overlay stack and tips for
 * its menus and labels, a status line for what a range did, and translations.
 * A `WidgetContext` is one; a custom host builds one from `createOverlayStack`
 * and `createTipController` over an `.oac-widget` root.
 */
export interface BottombarContext extends WidgetTranslationOptions {
  readonly document: Document;
  /** BCP 47 tag for weekday names. Default: the runtime's. */
  readonly locale?: string | undefined;
  readonly tips: TipController;
  openOverlay(el: HTMLElement, opts?: OverlayOptions): () => void;
  /** Report what a control did, and why a range fell short. */
  status(text: string, kind?: 'info' | 'error'): void;
  /** The chart the bar acts on when `BottombarOptions.target` is not given. */
  readonly chart?: Chart;
}

/**
 * The chart the bar acts on, and the widget's range methods when it has them.
 * A `Widget` is one.
 */
export interface BottombarTarget {
  readonly chart: Chart;
  /** The interval in force, for Go to. Default: the chart's data context. */
  interval?(): string;
  /** The range in force, pressed in the bar; null when none is. */
  range?(): string | null;
  /** Apply a range. The bar reports what it returns. Without it the range buttons are greyed. */
  setRange?(id: string): Promise<DateNavigationResult> | DateNavigationResult | void;
}

export interface BottombarOptions {
  /**
   * What the bar acts on, read at every use: a grid passes its focused
   * chart. Default: the context's chart, with no ranges.
   */
  target?: () => BottombarTarget | null;
  /** The range buttons. `[]` leaves them out. Default `DEFAULT_RANGES`. */
  ranges?: readonly WidgetRange[] | undefined;
  /** Open the go-to panel from the bar's button. Omit to leave the button out. */
  onGoTo?(anchor: HTMLElement): void | boolean;
  /** Clock for the time and the market status, in milliseconds. Default `Date.now`. */
  now?: (() => number) | undefined;
  /** Zones the timezone menu lists first. Default: those the settings dialog offers. */
  timezones?: readonly string[];
  /** Called after the bar moves the chart to another zone, for a host that keeps its own copy. */
  onTimezone?(zone: string): void;
}

/** The three price scale toggles. */
export type BottombarScaleToggle = 'auto' | 'log' | 'percent';

/** Which toggles are on for the price scale the bar acts on. */
export interface BottombarScaleState {
  auto: boolean;
  log: boolean;
  percent: boolean;
}

/**
 * The bar's controls without its markup: what the phone layout's sheets show
 * in its place, since the bar itself is hidden there.
 */
export interface BottombarControls {
  /** The range buttons, or none when the target cannot take a range. */
  ranges(): readonly WidgetRange[];
  range(): string | null;
  setRange(id: string): void;
  /** The market status, or null without a calendar or with "Session state" off. */
  marketStatus(): MarketStatusReading | null;
  /** The time and the zone's offset, `14:32 UTC+5:30`. */
  clock(): string;
  timezone(): string;
  /** The zones the timezone choice lists, the current one included. */
  timezones(): readonly string[];
  setTimezone(zone: string): void;
  /** Null when the chart has no price scale to act on yet. */
  scale(): BottombarScaleState | null;
  toggleScale(which: BottombarScaleToggle): void;
  /** Called when a range, the zone, the scale or the status changes; returns the unsubscribe. */
  subscribe(listener: () => void): () => void;
}

export interface BottombarHandle {
  readonly el: HTMLElement;
  readonly controls: BottombarControls;
  /** Read the target again and repaint: after the host points it elsewhere. */
  refresh(): void;
  destroy(): void;
}

/** The glyph and the words for each scale toggle; the phone layout's sheet shows the same words. */
export const SCALE_TOGGLES: ReadonlyArray<{ id: BottombarScaleToggle; icon: string; key: `schema.${string}`; label: string }> = [
  { id: 'auto', icon: 'scale-auto', key: 'schema.ui.bottombar.auto', label: 'Auto-fit to the data' },
  { id: 'log', icon: 'scale-log', key: 'schema.ui.bottombar.log', label: 'Logarithmic scale' },
  { id: 'percent', icon: 'scale-percent', key: 'schema.ui.bottombar.percent', label: 'Percent scale' },
];

/** The scale the primary series reads from, on the price pane: the one a scale toggle acts on. */
function primaryScale(chart: Chart): { pane: number; id: PriceScaleId } | null {
  if (chart.isDestroyed) return null;
  const pane = chart.primaryPaneIndex();
  const record = chart.panes()[pane];
  if (record === undefined) return null;
  const series = chart.primarySeries();
  for (const id of ['right', 'left'] as const) {
    if (series !== null && series.priceScale() === record.scaleFor(id)) return { pane, id };
  }
  return { pane, id: 'right' };
}

/** The price scale state a toggle reads, or null when nothing is measured on it yet. */
function scaleState(chart: Chart): { state: PriceAxisState; pane: number; id: PriceScaleId } | null {
  const at = primaryScale(chart);
  const state = at === null ? null : chart.priceAxisState(at.pane, at.id);
  return at === null || state === null || !state.active ? null : { state, ...at };
}

/** The zones the settings dialog offers, with the chart's own folded in. */
function settingsZones(chart: Chart): string[] {
  try {
    for (const tab of chartSettingsSchema(chart)) {
      const input = tab.inputs.find(i => i.key === 'time.timezone');
      const options = (input as { options?: ReadonlyArray<{ value: unknown }> } | undefined)?.options;
      if (options) return options.map(o => String(o.value));
    }
  } catch { /* A chart the schema cannot read still has its own zone. */ }
  return [chart.timezone()];
}

/** Every zone the runtime knows, where it can list them. */
function runtimeZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  try { return intl.supportedValuesOf?.('timeZone') ?? []; } catch { return []; }
}

/** A range's span in words, for its tooltip. */
function spanText(ctx: WidgetTranslationOptions, range: WidgetRange): string {
  const n = Math.max(1, Math.floor(range.count ?? 1));
  switch (range.unit) {
    case 'session': return n === 1 ? widgetText(ctx, 'schema.ui.rangeSpan.session', {}, 'One trading session')
      : widgetText(ctx, 'schema.ui.rangeSpan.sessions', { count: n }, '{count} trading sessions');
    case 'month': return n === 1 ? widgetText(ctx, 'schema.ui.rangeSpan.month', {}, 'One month')
      : widgetText(ctx, 'schema.ui.rangeSpan.months', { count: n }, '{count} months');
    case 'year': return n === 1 ? widgetText(ctx, 'schema.ui.rangeSpan.year', {}, 'One year')
      : widgetText(ctx, 'schema.ui.rangeSpan.years', { count: n }, '{count} years');
    case 'ytd': return widgetText(ctx, 'schema.ui.rangeSpan.ytd', {}, 'Year to date');
    default: return widgetText(ctx, 'schema.ui.rangeSpan.all', {}, 'All history');
  }
}

/** What a range did, for the status line, in the dialog's words where they fit. */
function describeRange(ctx: BottombarContext, chart: Chart, label: string, result: DateNavigationResult): string {
  const zone = chart.timezone();
  const intraday = chart.primaryBars().length > 1 && chart.primaryBars()[1]!.time - chart.primaryBars()[0]!.time < 86400; // length checked first
  let format: Intl.DateTimeFormat;
  try { format = new Intl.DateTimeFormat(ctx.locale, { timeZone: zone, dateStyle: 'medium', ...(intraday ? { timeStyle: 'short' } : {}) }); }
  catch { format = new Intl.DateTimeFormat(undefined, { timeZone: zone, dateStyle: 'medium' }); }
  const at = (t: number | undefined): string => (t === undefined ? '' : format.format(new Date(t * 1000)));
  const span = { range: label, from: at(result.from), to: at(result.to) };
  switch (result.status) {
    case 'placed': return widgetText(ctx, 'schema.ui.rangeResult.placed', span, '{range}: {from} to {to}');
    case 'no-data': return widgetText(ctx, 'schema.ui.rangeResult.empty', { range: label }, 'No bars for {range}');
    // A range is never typed, so an invalid one has no words of its own here.
    default: return describeNavigation(ctx, result, span) ?? '';
  }
}

/** Mount the bottom bar into `host`. */
export function mountBottombar(ctx: BottombarContext, host: HTMLElement, opts: BottombarOptions = {}): BottombarHandle {
  const doc = ctx.document;
  const now = (): number => (opts.now ?? Date.now)() / 1000;
  const ranges = opts.ranges ?? DEFAULT_RANGES;
  const target = (): BottombarTarget | null => {
    if (opts.target) return opts.target();
    return ctx.chart ? { chart: ctx.chart } : null;
  };
  const chartOf = (): Chart | null => {
    // A destroyed bar acts on nothing, whatever a host still holding its controls calls.
    if (destroyed) return null;
    const chart = target()?.chart ?? null;
    return chart !== null && !chart.isDestroyed ? chart : null;
  };
  const listeners = new Set<() => void>();
  const notify = (): void => { for (const listener of Array.from(listeners)) { try { listener(); } catch { /* one host listener must not stop the bar */ } } };
  /** A control changed the target: the bar shows it at once, and so does whatever subscribed. */
  const changed = (): void => { paint(); notify(); };
  const hold = new MarketStatusHold();
  let destroyed = false;
  let request = 0;

  // ── controls ─────────────────────────────────────────────────────────
  const controls: BottombarControls = {
    ranges: () => (target()?.setRange ? ranges : []),
    range: () => target()?.range?.() ?? null,
    setRange: (id) => {
      const t = destroyed ? null : target();
      const range = ranges.find(r => r.id === id);
      if (t?.setRange === undefined || range === undefined || t.chart.isDestroyed) return;
      const mine = ++request;
      let work: ReturnType<NonNullable<BottombarTarget['setRange']>>;
      try { work = t.setRange(id); } catch (error) {
        ctx.status(widgetText(ctx, 'Could not load history: {error}', { error: errorText(ctx, error) }), 'error');
        return;
      }
      changed();
      void Promise.resolve(work).then((result) => {
        if (destroyed || mine !== request || !result || result.status === 'cancelled') return;
        const text = describeRange(ctx, t.chart, range.label, result);
        if (text !== '') ctx.status(text, result.status === 'error' || result.status === 'unsupported' ? 'error' : 'info');
        changed();
      }, (error: unknown) => {
        if (!destroyed && mine === request) ctx.status(widgetText(ctx, 'Could not load history: {error}', { error: errorText(ctx, error) }), 'error');
      });
    },
    marketStatus: () => {
      const chart = chartOf();
      if (chart === null || !sessionStateShown(chart)) return null;
      const t = now();
      const status = hold.read(chart.dataLayer.sessionCalendar, t);
      return status === null ? null : marketStatusReading(ctx, status, t, chart.timezone());
    },
    clock: () => {
      const chart = chartOf();
      if (chart === null) return '';
      const t = now();
      return `${clockText(t, chart.timezone(), false)} ${utcOffsetLabel(t, chart.timezone())}`;
    },
    timezone: () => chartOf()?.timezone() ?? '',
    timezones: () => {
      const chart = chartOf();
      if (chart === null) return [];
      const zones = opts.timezones ? [...opts.timezones] : settingsZones(chart);
      if (!zones.includes(chart.timezone())) zones.push(chart.timezone());
      return zones;
    },
    setTimezone: (zone) => {
      const chart = chartOf();
      if (chart === null || zone === chart.timezone()) return;
      try { chart.setTimezone(zone); } catch {
        ctx.status(widgetText(ctx, 'schema.ui.bottombar.badZone', { zone }, 'Unknown timezone: {zone}'), 'error');
        return;
      }
      opts.onTimezone?.(zone);
      changed();
    },
    scale: () => {
      const chart = chartOf();
      const s = chart === null ? null : scaleState(chart);
      return s === null ? null : { auto: s.state.autoFit, log: s.state.mode === 'logarithmic', percent: s.state.mode === 'percentage' };
    },
    toggleScale: (which) => {
      const chart = chartOf();
      const s = chart === null ? null : scaleState(chart);
      if (chart === null || s === null) return;
      if (which === 'auto') chart.setPriceAxisAutoFit(s.pane, s.id, !s.state.autoFit);
      else {
        const mode = which === 'log' ? 'logarithmic' : 'percentage';
        chart.setPriceAxisOptions(s.pane, s.id, { mode: s.state.mode === mode ? 'linear' : mode });
      }
      changed();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };

  // ── markup ───────────────────────────────────────────────────────────
  host.classList.add('oac-bottombar');
  host.setAttribute('role', 'toolbar');
  host.setAttribute('aria-label', widgetText(ctx, 'schema.ui.bottombar.label', {}, 'Range, time and scale'));
  // Pressing a control must not start a pan on a chart the host placed it over.
  const stopPointer = (event: Event): void => { event.stopPropagation(); };
  host.addEventListener('pointerdown', stopPointer);
  const button = (cls: string, label: string): HTMLButtonElement => {
    const b = h(doc, 'button', cls, { type: 'button', 'aria-label': label });
    return b;
  };
  const off = (b: HTMLElement, disabled: boolean): void => {
    if (b.getAttribute('aria-disabled') !== String(disabled)) b.setAttribute('aria-disabled', String(disabled));
  };
  const write = (el: HTMLElement, text: string): void => { if (el.textContent !== text) el.textContent = text; };

  const rangeButtons = new Map<string, HTMLButtonElement>();
  if (ranges.length > 0) {
    const group = h(doc, 'div', 'oac-bottombar__group oac-bottombar__ranges', { role: 'group', 'aria-label': widgetText(ctx, 'schema.ui.bottombar.ranges', {}, 'Range') });
    for (const range of ranges) {
      const label = widgetText(ctx, `schema.ui.range.${range.id}`, {}, range.label);
      // Named like the interval pills ("Interval 1d"): a host's own "1D"
      // interval button and this "1D" range do different things, and must
      // not be announced alike. The name keeps the text on the button, and
      // is also the tip's title, which a shown tip writes back as the name.
      const name = widgetText(ctx, 'schema.ui.rangeName', { range: label }, 'Range {range}');
      const b = button('oac-bottombar__range', name);
      b.textContent = label;
      b.dataset.range = range.id;
      b.setAttribute('aria-pressed', 'false');
      ctx.tips.attach(b, () => ({
        title: name,
        sub: target()?.setRange ? spanText(ctx, range) : widgetText(ctx, 'schema.ui.bottombar.noRanges', {}, 'This chart takes no preset ranges'),
        side: 'top',
      }));
      b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') controls.setRange(range.id); });
      group.appendChild(b);
      rangeButtons.set(range.id, b);
    }
    // Focus scrolls a button in only when none of it shows, so a range the
    // narrow strip cuts in part would stay cut under the keyboard: the strip
    // brings the whole of it in.
    group.addEventListener('focusin', (e) => { (e.target as HTMLElement).scrollIntoView?.({ block: 'nearest', inline: 'nearest' }); });
    host.appendChild(group);
  }

  let goTo: HTMLButtonElement | null = null;
  if (opts.onGoTo) {
    if (ranges.length > 0) host.appendChild(h(doc, 'span', 'oac-sep', { role: 'separator' }));
    const b = button('oac-bottombar__goto', widgetText(ctx, 'Go to'));
    b.appendChild(glyph(doc, chromeIconSvg('calendar'), 'chrome'));
    const text = h(doc, 'span');
    text.textContent = widgetText(ctx, 'Go to');
    b.appendChild(text);
    b.setAttribute('aria-haspopup', 'dialog');
    ctx.tips.attach(b, () => ({
      title: widgetText(ctx, 'Go to'),
      sub: timeBuckets(intervalOf()) === null ? widgetText(ctx, 'Go to needs a time-based interval') : undefined,
      side: 'top',
    }));
    b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') opts.onGoTo?.(b); });
    host.appendChild(b);
    goTo = b;
  }

  host.appendChild(h(doc, 'span', 'oac-bottombar__spacer'));

  // A status region: it can carry the full reading as its name while a narrow
  // bar hides the detail, and a change of phase is announced, not only recoloured.
  const status = h(doc, 'span', 'oac-bottombar__status', { role: 'status' });
  const statusGlyph = h(doc, 'span', 'oac-bottombar__phase');
  const statusLabel = h(doc, 'b');
  const statusDetail = h(doc, 'span', 'oac-bottombar__detail');
  status.append(statusGlyph, statusLabel, statusDetail);
  status.hidden = true;
  host.appendChild(status);
  const statusSep = h(doc, 'span', 'oac-sep', { role: 'separator' });
  statusSep.hidden = true;
  host.appendChild(statusSep);

  const clock = button('oac-bottombar__clock', widgetText(ctx, 'schema.ui.bottombar.timezone', { zone: '' }, 'Timezone: {zone}'));
  const clockTime = h(doc, 'span', 'oac-bottombar__time');
  const clockZone = h(doc, 'small');
  clock.append(clockTime, clockZone);
  clock.setAttribute('aria-haspopup', 'menu');
  ctx.tips.attach(clock, () => ({
    title: widgetText(ctx, 'schema.ui.bottombar.timezone', { zone: controls.timezone() }, 'Timezone: {zone}'),
    sub: widgetText(ctx, 'schema.ui.bottombar.timezoneHint', {}, 'The zone the time axis and the sessions are read in'),
    side: 'top',
  }));
  clock.addEventListener('click', () => openZones(clock));
  host.appendChild(clock);
  host.appendChild(h(doc, 'span', 'oac-sep', { role: 'separator' }));

  const scaleGroup = h(doc, 'div', 'oac-bottombar__group oac-bottombar__scale', { role: 'group', 'aria-label': widgetText(ctx, 'schema.ui.bottombar.scale', {}, 'Price scale') });
  const scaleButtons = new Map<BottombarScaleToggle, HTMLButtonElement>();
  for (const toggle of SCALE_TOGGLES) {
    const label = widgetText(ctx, toggle.key, {}, toggle.label);
    const b = button('oac-bottombar__icon', label);
    b.dataset.scale = toggle.id;
    b.setAttribute('aria-pressed', 'false');
    b.appendChild(glyph(doc, chromeIconSvg(toggle.icon), 'chrome'));
    ctx.tips.attach(b, () => ({
      title: label,
      sub: controls.scale() === null ? widgetText(ctx, 'schema.ui.bottombar.noScale', {}, 'Nothing is plotted on the price scale yet') : undefined,
      side: 'top',
    }));
    b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') controls.toggleScale(toggle.id); });
    scaleGroup.appendChild(b);
    scaleButtons.set(toggle.id, b);
  }
  host.appendChild(scaleGroup);

  function intervalOf(): string | undefined {
    const t = target();
    return t?.interval?.() ?? t?.chart.getDataContext()?.interval;
  }

  let closeZones: (() => void) | null = null;
  function openZones(anchor: HTMLElement): void {
    const chart = chartOf();
    if (chart === null) return;
    const current = chart.timezone();
    const t = now();
    const first = controls.timezones();
    const row = (zone: string): MenuRow => {
      let sub = '';
      try { sub = utcOffsetLabel(t, zone); } catch { /* a zone the runtime cannot format is still listed by name */ }
      return { label: zone, sub, on: zone === current, onSelect: () => controls.setTimezone(zone) };
    };
    const rest = runtimeZones().filter(zone => !first.includes(zone));
    const rows: Array<MenuRow | string> = [...first.map(row)];
    if (rest.length > 0) rows.push(widgetText(ctx, 'schema.ui.bottombar.allZones', {}, 'All zones'), ...rest.map(row));
    closeZones = openMenu(ctx, anchor, rows, {
      find: widgetText(ctx, 'schema.ui.bottombar.findZone', {}, 'Find a zone'),
      ariaLabel: widgetText(ctx, 'schema.ui.bottombar.timezones', {}, 'Timezone'),
    });
  }

  // ── painting ─────────────────────────────────────────────────────────
  let zoneShown = '';
  const paintClock = (): void => {
    const chart = chartOf();
    const t = now();
    const zone = chart?.timezone() ?? '';
    write(clockTime, chart === null ? '' : clockText(t, zone));
    write(clockZone, chart === null ? '' : utcOffsetLabel(t, zone));
    if (zone !== zoneShown) {
      zoneShown = zone;
      ctx.tips.refreshLabel(clock);
      clock.setAttribute('aria-label', widgetText(ctx, 'schema.ui.bottombar.timezone', { zone }, 'Timezone: {zone}'));
    }
    off(clock, chart === null);
  };
  let phaseShown: string | null = null;
  const paintStatus = (): void => {
    const reading = controls.marketStatus();
    status.hidden = reading === null;
    statusSep.hidden = reading === null;
    if (reading === null) { phaseShown = null; return; }
    if (reading.phase !== phaseShown) {
      // The market moved on: the phone layout's sheet reads it again.
      if (phaseShown !== null) queueMicrotask(notify);
      phaseShown = reading.phase;
      status.dataset.phase = reading.phase;
      statusGlyph.textContent = '';
      statusGlyph.appendChild(glyph(doc, chromeIconSvg(PHASE_GLYPHS[reading.phase]), 'chrome'));
    }
    write(statusLabel, reading.label);
    write(statusDetail, reading.detail);
    const name = reading.detail === '' ? reading.label : `${reading.label}, ${reading.detail}`;
    if (status.getAttribute('aria-label') !== name) status.setAttribute('aria-label', name);
  };
  const paintScale = (): void => {
    const state = controls.scale();
    for (const [id, b] of scaleButtons) {
      const on = state !== null && state[id];
      if (b.getAttribute('aria-pressed') !== String(on)) b.setAttribute('aria-pressed', String(on));
      off(b, state === null);
    }
  };
  const paintRanges = (): void => {
    const t = target();
    const current = t?.range?.() ?? null;
    for (const [id, b] of rangeButtons) {
      const on = id === current;
      if (b.getAttribute('aria-pressed') !== String(on)) b.setAttribute('aria-pressed', String(on));
      off(b, t?.setRange === undefined);
    }
    // Its tip reads the reason when it opens; the name never changes.
    if (goTo !== null) off(goTo, t === null || timeBuckets(intervalOf()) === null);
  };
  const paint = (): void => {
    if (destroyed) return;
    bind();
    paintRanges();
    paintStatus();
    paintClock();
    paintScale();
  };

  // ── following the target ─────────────────────────────────────────────
  let bound: Chart | null = null;
  let chartOffs: Array<() => void> = [];
  function bind(): void {
    const chart = chartOf();
    if (chart === bound) return;
    for (const offChart of chartOffs.splice(0)) offChart();
    bound = chart;
    if (chart === null) return;
    const repaintScale = (): void => { if (!destroyed) paintScale(); };
    const repaintAll = (): void => { if (!destroyed) { paint(); notify(); } };
    // A symbol or an interval change reaches the range and Go to; a new zone
    // the clock and the status; a layout change (a scale, the "Session state"
    // switch, an undo) the scale and the status.
    chartOffs = [
      chart.on('data:context', repaintAll),
      chart.on('timezone:changed', repaintAll),
      chart.on('state:restore:end', repaintAll),
      chart.on('layout:change', () => { if (!destroyed) { paintScale(); paintStatus(); } }),
      chart.on('zoom', repaintScale),
      chart.on('pan', repaintScale),
      chart.on('dblclick', repaintScale),
      chart.on('destroy', () => { if (!destroyed) queueMicrotask(paint); }),
    ];
  }
  // Dragging the price axis switches auto-fit off without an event of its own,
  // so the toggles look again when any press ends.
  const onPointerUp = (): void => { if (!destroyed) paintScale(); };
  doc.addEventListener('pointerup', onPointerUp, true);

  let timer: ReturnType<typeof setTimeout> | 0 = 0;
  const schedule = (): void => {
    if (timer !== 0) clearTimeout(timer);
    timer = 0;
    if (destroyed || doc.hidden === true) return;
    const ms = (opts.now ?? Date.now)();
    timer = setTimeout(tick, 1000 - (((ms % 1000) + 1000) % 1000) + 5);
  };
  function tick(): void {
    timer = 0;
    if (destroyed) return;
    // A layout this bar cannot hear about (a host swapping the target's
    // chart, a calendar set on the chart) is caught here within a second.
    paint();
    schedule();
  }
  const onVisibility = (): void => { if (doc.hidden !== true) paint(); schedule(); };
  doc.addEventListener('visibilitychange', onVisibility);
  paint();
  schedule();

  return {
    el: host,
    controls,
    refresh: paint,
    destroy: () => {
      if (destroyed) return;
      destroyed = true;
      request++;
      // Its menu and tip live in the host's overlay layer, which outlives the bar.
      closeZones?.();
      if (ctx.tips.target() !== null && host.contains(ctx.tips.target())) ctx.tips.hide();
      if (timer !== 0) clearTimeout(timer);
      timer = 0;
      for (const offChart of chartOffs.splice(0)) offChart();
      doc.removeEventListener('pointerup', onPointerUp, true);
      doc.removeEventListener('visibilitychange', onVisibility);
      host.removeEventListener('pointerdown', stopPointer);
      listeners.clear();
      host.textContent = '';
    },
  };
}

/**
 * The bar's rules, scoped under `.oac-widget` like the rest of the chrome.
 * A widget root carrying the bar takes a fourth row for it, between the chart
 * and the status line; the phone layout hides it, its controls having moved
 * into the sheets. A bar marked `is-kept` has no sheet to move into (a widget
 * without a top bar has no More sheet), so it stays under the chart there and
 * the phone footer takes the last row.
 *
 * On a narrow bar the ranges give way and scroll; the status, the clock and
 * the scale toggles are never cut. The narrowest bar shows the status by its
 * glyph, its reading kept as the status region's name.
 */
export const BOTTOMBAR_CSS = `
.oac-widget.has-bottombar { grid-template-rows: auto minmax(0, 1fr) auto auto; }
.oac-widget.has-bottombar > .oac-bottombar { grid-row: 3; }
.oac-widget.has-bottombar > .oac-statusline { grid-row: 4; }
.oac-widget.has-bottombar:not(.is-mobile) > .oac-toasts { bottom: calc(${v('status-h')} + ${BOTTOMBAR_HEIGHT + 10}px); }
.oac-widget.is-mobile > .oac-bottombar:not(.is-kept) { display: none; }
.oac-widget.is-mobile:has(> .oac-bottombar.is-kept) .oac-mobile__footer { grid-row: 4; }
.oac-widget.is-mobile:has(> .oac-bottombar.is-kept) > .oac-toasts { bottom: calc(${54 + BOTTOMBAR_HEIGHT}px + env(safe-area-inset-bottom)); }
.oac-widget .oac-bottombar { container: oac-bottombar / inline-size; display: flex; align-items: center; gap: 2px;
  height: ${BOTTOMBAR_HEIGHT}px; min-width: 0; padding: 0 6px; background: ${v('panel')}; border-top: 1px solid ${v('bd-soft')};
  color: ${v('mut')}; font-size: 11.5px; font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; }
.oac-widget .oac-bottombar .oac-sep { height: 16px; }
.oac-widget .oac-bottombar__group { display: inline-flex; align-items: center; gap: 1px; min-width: 0; }
.oac-widget .oac-bottombar__ranges { flex: 0 1 auto; min-width: 56px; overflow-x: auto; scrollbar-width: none; }
.oac-widget .oac-bottombar__scale { flex: none; }
.oac-widget .oac-bottombar__ranges::-webkit-scrollbar { width: 0; height: 0; }
.oac-widget .oac-bottombar button { display: inline-flex; align-items: center; gap: 5px; flex: none; height: 22px;
  padding: 0 7px; background: transparent; border: 1px solid transparent; border-radius: 5px; color: ${v('mut')};
  font-size: 11.5px; font-weight: 600; letter-spacing: .2px; transition: background .1s, color .1s, border-color .1s; }
.oac-widget .oac-bottombar button:hover { background: ${v('elev')}; color: ${v('tx')}; }
.oac-widget .oac-bottombar button[aria-pressed="true"] { background: ${v('on-bg')}; border-color: ${v('on-bd')}; color: ${v('acc-2')}; }
.oac-widget .oac-bottombar button[aria-disabled="true"] { background: transparent; border-color: transparent; color: ${v('faint')}; cursor: default; }
.oac-widget .oac-bottombar button:focus-visible { outline-offset: -1px; }
.oac-widget .oac-bottombar .oac-glyph > svg { width: 14px; height: 14px; }
.oac-widget .oac-bottombar__icon { width: 24px; padding: 0; justify-content: center; }
.oac-widget .oac-bottombar__spacer { flex: 1 1 auto; min-width: 6px; }
.oac-widget .oac-bottombar__status { display: inline-flex; flex: none; align-items: center; gap: 5px; padding: 0 5px; }
.oac-widget .oac-bottombar__status > b { flex: none; color: ${v('tx')}; font-weight: 600; }
.oac-widget .oac-bottombar__phase { display: inline-grid; flex: none; color: ${v('faint')}; }
.oac-widget .oac-bottombar__status[data-phase="regular"] .oac-bottombar__phase { color: ${v('up')}; }
.oac-widget .oac-bottombar__status:is([data-phase="pre"], [data-phase="post"], [data-phase="extended"]) .oac-bottombar__phase { color: ${v('amber')}; }
.oac-widget .oac-bottombar__detail { color: ${v('faint')}; }
.oac-widget .oac-bottombar__clock { color: ${v('tx')}; }
.oac-widget .oac-bottombar__time { font-weight: 500; }
.oac-widget .oac-bottombar__clock > small { color: ${v('faint')}; font-size: 10.5px; font-weight: 600; }
.oac-widget .oac-mobile-sheet__note { grid-column: 1 / -1; margin: 0; padding: 8px 10px 10px; color: ${v('mut')};
  border-bottom: 1px solid ${v('bd-soft')}; margin-bottom: 6px; font-variant-numeric: tabular-nums; }
.oac-widget .oac-mobile-sheet__note > b { color: ${v('tx')}; font-weight: 600; }
.oac-widget .oac-mobile-sheet__body > [data-mobile-action="timezone"] { grid-column: 1 / -1; }
.oac-widget .oac-mobile-sheet__ranges, .oac-widget .oac-mobile-sheet__scales { grid-column: 1 / -1; display: grid; }
.oac-widget .oac-mobile-sheet__ranges { grid-template-columns: repeat(5, minmax(0, 1fr)); }
.oac-widget .oac-mobile-sheet__scales { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.oac-widget .oac-statusline__market[data-phase="regular"] { color: ${v('up')}; }
@container oac-bottombar (max-width: 760px) {
  .oac-widget .oac-bottombar__detail, .oac-widget .oac-bottombar__goto > span:not(.oac-glyph) { display: none; }
}
@container oac-bottombar (max-width: 600px) {
  .oac-widget .oac-bottombar__clock > small { display: none; }
}
@container oac-bottombar (max-width: 360px) {
  .oac-widget .oac-bottombar__status > b { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .oac-widget .oac-bottombar button { transition: none; }
}
`;

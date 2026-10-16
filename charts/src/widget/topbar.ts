/**
 * The top bar: symbol, interval, chart type, indicators, settings, capture
 * and theme, left to right.
 *
 * Buttons and popup menus rather than native selects: a select cannot group,
 * cannot carry a chord and looks like a form control on a chart. The
 * interval pills come from the list the shell resolves (its own defaults
 * plus every code registered with the engine); the chart type menu is read
 * from the chart-type and series-transform registries at open time, so the
 * types the transform tier registers appear without a second list to keep in
 * step. The indicators
 * and settings buttons open the dialog tier's panels; without one registered
 * they render disabled, with their state visible, rather than dead.
 */
import { errorText, widgetText, type WidgetTranslationOptions } from './localization';
import { registeredChartTypes, getChartType, exportChartDataCsv, getSeriesTransform, registeredSeriesTransforms } from 'openalgo-charts';
import { chartTypeIcon, chromeIconSvg } from 'openalgo-charts/draw';
import { h, glyph, type WidgetContext } from './context';
import type { WidgetThemeName } from './tokens';
import { mountSymbolPicker, type SymbolPickerHandle } from './symbol-picker';
import { timeBuckets } from './date-navigator';
import { boxChartType } from './chart-type-choice';
export { SEARCH_DEBOUNCE_MS } from './symbol-picker';
export type { SymbolMatch, SymbolSearch } from './symbol-picker';
import type { SymbolSearch } from './symbol-picker';
import type { PanelHandle } from './form';
import type { LayoutsController } from './layouts';
import { layoutNeedsAttention, layoutStatusText } from './layouts-widget';
import { lazyPart, partFailed, usePart, type PartSlot } from './lazy';
import { canCopyImage, copyCanvasImage, downloadCanvas } from './capture';
import { captureName, downloadText, openMenu, type MenuRow } from './menu';
export { captureName, downloadText, openMenu } from './menu';
export type { MenuOptions, MenuRow } from './menu';

/** The chart data dialog, fetched when it first opens. Internal. */
export const dataExportPart = lazyPart(() => import('./chart-data-export-dialog'));
/** The point and figure and Renko settings, fetched when they first open. Internal. */
const chartTypeSettingsPart = lazyPart(() => import('./chart-type-settings'));

/** Labels for the built-in chart types; a transform's is its own name, and anything else is read from its id. */
export const CHART_TYPE_LABELS: Readonly<Record<string, string>> = {
  candlestick: 'Candles',
  'hollow-candle': 'Hollow candles',
  bar: 'Bars',
  'high-low': 'High-low',
  'volume-candle': 'Volume candles',
  line: 'Line',
  'line-markers': 'Line with markers',
  step: 'Step line',
  area: 'Area',
  'hlc-area': 'HLC area',
  baseline: 'Baseline',
  'point-figure': 'Point and figure',
  kagi: 'Kagi',
};

export function chartTypeLabel(id: string): string {
  const known = CHART_TYPE_LABELS[id] ?? (registeredSeriesTransforms().includes(id) ? getSeriesTransform(id).name : undefined);
  if (known !== undefined) return known;
  return id.replace(/[-_]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
}

/**
 * The chart types a primary series can be: every registered renderer that
 * declares itself a price series, then every transform the chart can apply
 * (Heikin Ashi to Kagi, once the transform tier is imported), which the chart
 * derives from the bars rather than drawing them as they come. Point and
 * figure and Kagi are both a renderer and a transform, and are listed once,
 * with the transforms. A volume histogram is registered too and would draw,
 * but it is not a chart type anyone picks for the instrument.
 */
export function chartTypeChoices(): string[] {
  const transforms = registeredSeriesTransforms();
  return [...registeredChartTypes().filter((t) => {
    try { return !transforms.includes(t) && getChartType(t).isPriceSeries; } catch { return false; }
  }), ...transforms];
}

/**
 * A pill label for an interval code: minutes and hours keep their lower-case
 * unit (`5m`, `1h`), days and weeks read as a capital (`D`, `W`, `2W`), and
 * anything else (a registered calendar code) is upper-cased as written.
 */
export function intervalLabel(code: string): string {
  const m = /^(\d*)\s*([smhdwSMHDW])$/.exec(code.trim());
  if (m === null) return code.toUpperCase();
  const n = m[1] === '' || m[1] === '1' ? '' : m[1];
  const unit = m[2]!; // the unit group is not optional, so a match fills it
  if (unit === 'm') return `${m[1] === '' ? '1' : m[1]}m`;
  if (unit === 's') return `${m[1] === '' ? '1' : m[1]}s`;
  if (unit === 'h' || unit === 'H') return `${m[1] === '' ? '1' : m[1]}h`;
  return n + unit.toUpperCase();
}

export interface TopbarState {
  symbol: string;
  exchange: string;
  interval: string;
  chartType: string;
  theme: WidgetThemeName;
}

export interface TopbarOptions {
  intervals: readonly string[];
  /** Show the indicators button. Default true. */
  indicators?: boolean | undefined;
  search?: SymbolSearch | undefined;
  /** The current facts, read on every refresh. */
  state: () => TopbarState;
  onSymbol(symbol: string, exchange?: string): void;
  onInterval(code: string): void;
  onChartType(id: string): void;
  onTheme(next: WidgetThemeName): void;
  /** Open the settings dialog from `anchor`. Return false when no dialog is registered. */
  onSettings(anchor: HTMLElement): boolean;
  onIndicators(anchor: HTMLElement): boolean;
  /** A text control for the host's object inventory, omitted without a handler. */
  onObjects?(anchor: HTMLElement): boolean;
  /** Open the docked data window, omitted without a handler. */
  onDataWindow?(anchor: HTMLElement): void | boolean;
  onAlerts?(anchor: HTMLElement): boolean;
  /** Open the docked watchlist, omitted without a handler (the host supplied no lists). */
  onWatchlist?(anchor: HTMLElement): void | boolean;
  /** Open the docked news reader, omitted without a handler (the host supplied no news source). */
  onNews?(anchor: HTMLElement): void | boolean;
  /** Open the date and range navigation panel, omitted without a handler. */
  onGoTo?(anchor: HTMLElement): void | boolean;
  /**
   * The saved layouts the Layouts button names: it shows the held layout and
   * marks one with unsaved changes. Omitted, with `onLayouts`, without a store.
   */
  layouts?: LayoutsController | undefined;
  /** Open the Layouts menu from `anchor`. */
  onLayouts?(anchor: HTMLElement): void | boolean;
  settingsAvailable(): boolean;
  indicatorsAvailable(): boolean;
  /** Refuse CSV export while the host is replacing or recovering its data. */
  dataAvailable?(): boolean;
  /** More capture menu rows, read on every open (the chart grid adds its whole-grid capture); a string starts a group. */
  captureRows?: (() => ReadonlyArray<MenuRow | string>) | undefined;
}

export interface TopbarHandle {
  readonly el: HTMLElement;
  /** Open the shared capture menu from desktop or mobile chrome. */
  openCapture(anchor: HTMLElement): void;
  /** Repaint every control from `state()`. */
  refresh(): void;
  /** Put the caret in the symbol box, text selected. */
  focusSymbol(): void;
  destroy(): void;
}

/** Read safe link metadata from the chart's active branding. */
export function brandingLink(chart: WidgetContext['chart'], translation: WidgetTranslationOptions = {}): { href: string; label: string } | null {
  const options = chart.brandingOptions();
  if (!options || typeof options.href !== 'string' || !/^https?:\/\//i.test(options.href)) return null;
  const label = typeof options.label === 'string' && options.label.trim() !== ''
    ? options.label.trim()
    : widgetText(translation, 'Chart branding');
  return { href: options.href, label };
}

/**
 * The settings control beside the chart type, shown only while the chart
 * builds point and figure or Renko itself: drawn from a host's own elements,
 * point and figure has no box size to set. Its dialog loads on first use.
 */
function typeSettingsButton(ctx: WidgetContext, host: HTMLElement): { el: HTMLButtonElement; refresh(): void; close(): void } {
  const doc = ctx.document;
  const b = h(doc, 'button', 'oac-btn oac-btn--icon oac-topbar__type-settings', { type: 'button', 'aria-haspopup': 'dialog' });
  b.appendChild(glyph(doc, chromeIconSvg('settings'), 'chrome'));
  const name = (): string => {
    const id = boxChartType(ctx.chart) ?? '';
    return widgetText(ctx, 'schema.ui.chartTypeSettings.title', { name: widgetText(ctx, `schema.chartType.${id}`, {}, chartTypeLabel(id)) }, '{name} settings');
  };
  ctx.tips.attach(b, () => ({ title: name(), side: 'bottom' }));
  let dialog: PanelHandle | null = null;
  const slot: PartSlot = { waiting: null };
  b.addEventListener('click', () => {
    usePart(chartTypeSettingsPart, module => {
      dialog?.close();
      if (boxChartType(ctx.chart) !== null) dialog = module.openChartTypeSettings(ctx, b);
    }, error => ctx.status(partFailed(ctx, name(), error), 'error'), () => host.isConnected, { slot, doc, from: b });
  });
  return {
    el: b,
    refresh: () => {
      const type = boxChartType(ctx.chart) ?? '';
      if (b.dataset.type === type) return;
      b.dataset.type = type;
      b.hidden = type === '';
      // A tip still up names the type the chart was a moment ago.
      if (ctx.tips.target() === b) ctx.tips.hide();
      ctx.tips.refreshLabel(b);
    },
    close: () => dialog?.close(),
  };
}

export function mountTopbar(ctx: WidgetContext, host: HTMLElement, opts: TopbarOptions): TopbarHandle {
  const doc = ctx.document;
  host.classList.add('oac-topbar');
  host.setAttribute('role', 'toolbar');
  host.setAttribute('aria-label', widgetText(ctx, 'Chart toolbar'));

  const btn = (label: string, cls = ''): HTMLButtonElement => h(doc, 'button', 'oac-btn' + (cls ? ' ' + cls : ''), { type: 'button', 'aria-label': label });
  const chev = (): HTMLElement => Object.assign(h(doc, 'span', 'oac-chev', { 'aria-hidden': 'true' }), { innerHTML: chromeIconSvg('chevron-down') });
  const sep = (): HTMLElement => h(doc, 'span', 'oac-sep', { role: 'separator' });
  const setOff = (b: HTMLButtonElement, off: boolean): void => {
    b.classList.toggle('is-off', off);
    b.setAttribute('aria-disabled', String(off));
  };

  // ── symbol ───────────────────────────────────────────────────────────
  const symWrap = h(doc, 'div', 'oac-sym');
  symWrap.appendChild(glyph(doc, chromeIconSvg('search'), 'chrome'));
  const symInput = h(doc, 'input', 'oac-sym__input', {
    type: 'text', 'aria-label': widgetText(ctx, 'Symbol'), placeholder: widgetText(ctx, 'Symbol'), autocomplete: 'off', spellcheck: 'false',
  });
  symWrap.appendChild(symInput);
  const symEx = h(doc, 'span', 'oac-sym__ex');
  symWrap.appendChild(symEx);
  host.appendChild(symWrap);
  host.appendChild(sep());

  let picker: SymbolPickerHandle | null = null;
  const commit = (symbol: string, exchange?: string): void => {
    picker?.close();
    const s = symbol.trim().toUpperCase();
    if (s === '') { refresh(); return; }
    opts.onSymbol(s, exchange);
    symInput.blur();
  };
  if (opts.search) picker = mountSymbolPicker(ctx, symInput, {
    search: opts.search, onSelect: commit,
    context: () => `${opts.state().exchange}:${opts.state().symbol}:${opts.state().interval}`,
  });
  symInput.addEventListener('keydown', (e) => {
    const ke = e as KeyboardEvent;
    if (ke.key === 'Enter') {
      ke.preventDefault();
      // A search still running would have shown what the user meant: wait for it.
      if (picker === null || picker.canCommitRaw()) commit(symInput.value);
    } else if (ke.key === 'Escape') { refresh(); symInput.blur(); }
  });
  symInput.addEventListener('focus', () => { symInput.select(); });
  symInput.addEventListener('blur', () => { refresh(); });

  // ── intervals ────────────────────────────────────────────────────────
  const pills = h(doc, 'div', 'oac-pills', { role: 'radiogroup', 'aria-label': widgetText(ctx, 'Interval') });
  const pillByCode = new Map<string, HTMLButtonElement>();
  for (const code of opts.intervals) {
    const b = h(doc, 'button', undefined, { type: 'button', role: 'radio', 'aria-pressed': 'false', 'aria-label': widgetText(ctx, 'Interval {code}', { code: intervalLabel(code) }) });
    b.textContent = intervalLabel(code);
    b.dataset.interval = code;
    b.addEventListener('click', () => opts.onInterval(code));
    pills.appendChild(b);
    pillByCode.set(code, b);
  }
  host.appendChild(pills);
  host.appendChild(sep());

  // ── chart type ───────────────────────────────────────────────────────
  const typeBtn = btn(widgetText(ctx, 'Chart type'), 'oac-topbar__type');
  // The type in force as its glyph and its name; a type with no glyph shows the name alone.
  const typeGlyph = glyph(doc, '', 'chrome');
  const typeLabel = h(doc, 'span');
  typeBtn.append(typeGlyph, typeLabel);
  typeBtn.appendChild(chev());
  typeBtn.setAttribute('aria-haspopup', 'menu');
  typeBtn.addEventListener('click', () => {
    const cur = opts.state().chartType;
    // The types the chart forms from price rather than the clock follow under a heading of their own.
    const first = registeredSeriesTransforms()[0];
    openMenu(ctx, typeBtn, chartTypeChoices().flatMap((id) => [
      ...(id === first ? [widgetText(ctx, 'schema.chartType.group.transforms', {}, 'Transforms')] : []),
      { label: widgetText(ctx, `schema.chartType.${id}`, {}, chartTypeLabel(id)), icon: `chart-${id}`, on: id === cur, onSelect: () => opts.onChartType(id) },
    ]), { ariaLabel: widgetText(ctx, 'Chart type') });
  });
  const typeSettings = typeSettingsButton(ctx, host);
  host.append(typeBtn, typeSettings.el);

  // ── indicators ───────────────────────────────────────────────────────
  let indBtn: HTMLButtonElement | null = null;
  if (opts.indicators !== false) {
    indBtn = btn(widgetText(ctx, 'Indicators'));
    indBtn.appendChild(glyph(doc, chromeIconSvg('plus'), 'chrome'));
    const t = h(doc, 'span');
    t.textContent = widgetText(ctx, 'Indicators');
    indBtn.appendChild(t);
    indBtn.addEventListener('click', () => {
      if (indBtn !== null && indBtn.classList.contains('is-off')) return;
      if (indBtn !== null) opts.onIndicators(indBtn);
    });
    host.appendChild(indBtn);
  }

  host.appendChild(h(doc, 'span', 'oac-topbar__spacer'));

  // The canvas mark can be activated by pointer. This host link gives the
  // same destination to keyboard and assistive-technology users without
  // placing transparent chrome over the chart.
  const brandingSlot = h(doc, 'span', 'oac-topbar__branding-slot');
  let brandingAnchor: HTMLAnchorElement | null = null;
  host.appendChild(brandingSlot);

  // ── layouts ──────────────────────────────────────────────────────────
  // The held layout's name on the button: which document the chart is, at a
  // glance, with a dot while it has changes that are not saved.
  let offLayouts: (() => void) | null = null;
  const controller = opts.layouts;
  if (controller !== undefined && opts.onLayouts) {
    const title = widgetText(ctx, 'schema.ui.layouts.title', {}, 'Layouts');
    const held = (): string | null => {
      const state = controller.state();
      return state.layoutId === null ? null : state.catalog?.workspaces.find(doc => doc.id === state.layoutId)?.name ?? null;
    };
    const layouts = btn(title, 'oac-topbar__layouts');
    layouts.setAttribute('aria-haspopup', 'dialog');
    layouts.appendChild(glyph(doc, chromeIconSvg('layout'), 'chrome'));
    const label = h(doc, 'span', 'oac-topbar__layouts-name');
    layouts.appendChild(label);
    ctx.tips.attach(layouts, () => {
      const name = held();
      const state = controller.state();
      const said = name === null ? title : `${title}: ${name}`;
      const status = layoutStatusText(ctx, state);
      // The mark is a dot: a screen reader hears what it means with the name.
      return { title: said, label: layoutNeedsAttention(state) ? `${said}, ${status}` : undefined, sub: status, side: 'bottom' };
    });
    const paintLayouts = (): void => {
      label.textContent = held() ?? title;
      layouts.dataset.attention = String(layoutNeedsAttention(controller.state()));
      ctx.tips.refreshLabel(layouts);
    };
    offLayouts = controller.subscribe(paintLayouts);
    paintLayouts();
    layouts.addEventListener('click', () => { opts.onLayouts?.(layouts); });
    host.appendChild(layouts);
    // The bar measures itself, so the name can give way before it wraps (LAYOUTS_BUTTON_CSS).
    host.classList.add('has-layouts');
  }

  // Tick and volume bars have no date to go to: greyed with the reason, not dead.
  const goTo = opts.onGoTo ? btn(widgetText(ctx, 'Go to'), 'oac-topbar__goto') : null;
  if (goTo !== null) {
    goTo.textContent = widgetText(ctx, 'Go to');
    goTo.setAttribute('aria-haspopup', 'dialog');
    ctx.tips.attach(goTo, () => ({
      title: widgetText(ctx, 'Go to'),
      sub: timeBuckets(opts.state().interval) === null ? widgetText(ctx, 'Go to needs a time-based interval') : undefined,
      side: 'bottom',
    }));
    goTo.addEventListener('click', () => { if (!goTo.classList.contains('is-off')) opts.onGoTo?.(goTo); });
    host.appendChild(goTo);
  }
  if (opts.onObjects) {
    const objects = btn(widgetText(ctx, 'Objects'), 'oac-topbar__objects');
    objects.textContent = widgetText(ctx, 'Objects');
    objects.setAttribute('aria-haspopup', 'dialog');
    objects.addEventListener('click', () => { opts.onObjects?.(objects); });
    host.appendChild(objects);
  }
  if (opts.onDataWindow) {
    const data = btn(widgetText(ctx, 'schema.ui.dataWindow', {}, 'Data'), 'oac-topbar__data');
    data.textContent = widgetText(ctx, 'schema.ui.dataWindow', {}, 'Data');
    data.addEventListener('click', () => { opts.onDataWindow?.(data); });
    host.appendChild(data);
  }
  for (const [key, label, handler] of [['watchlist', 'Watchlist', opts.onWatchlist], ['news', 'News', opts.onNews]] as const) {
    if (!handler) continue;
    const control = btn(widgetText(ctx, `schema.ui.dock.${key}`, {}, label), `oac-topbar__${key}`);
    control.textContent = widgetText(ctx, `schema.ui.dock.${key}`, {}, label);
    control.addEventListener('click', () => { handler(control); });
    host.appendChild(control);
  }
  if (opts.onAlerts) {
    const alerts = btn(widgetText(ctx, 'Alerts'), 'oac-topbar__alerts');
    alerts.textContent = widgetText(ctx, 'Alerts');
    alerts.setAttribute('aria-haspopup', 'dialog');
    alerts.addEventListener('click', () => { opts.onAlerts?.(alerts); });
    host.appendChild(alerts);
  }

  // ── capture ──────────────────────────────────────────────────────────
  const snapBtn = btn(widgetText(ctx, 'Capture chart'), 'oac-btn--icon');
  snapBtn.appendChild(glyph(doc, chromeIconSvg('camera'), 'chrome'));
  snapBtn.setAttribute('aria-haspopup', 'menu');
  ctx.tips.attach(snapBtn, { title: widgetText(ctx, 'Capture'), sub: widgetText(ctx, 'PNG, SVG, CSV or the clipboard'), side: 'bottom' });
  let dataDialog: PanelHandle | null = null;
  const dataSlot: PartSlot = { waiting: null };
  const openCapture = (anchor: HTMLElement): void => {
    const s = { ...opts.state() };
    const capturedChart = ctx.chart;
    const capturedPrimary = capturedChart.primarySeries();
    const source = capturedChart.getDataContext();
    const dataAvailable = (): boolean => !capturedChart.isDestroyed && opts.dataAvailable?.() !== false && capturedChart.primaryBars().length > 0;
    const checkSource = (): void => {
      const current = opts.state(), context = ctx.chart.getDataContext();
      if (ctx.chart !== capturedChart || capturedChart.primarySeries() !== capturedPrimary
        || current.symbol !== s.symbol || current.exchange !== s.exchange || current.interval !== s.interval || current.chartType !== s.chartType
        || context !== source) {
        throw new Error(widgetText(ctx, 'The chart changed; reopen Capture for its current source'));
      }
      if (!dataAvailable()) throw new Error(widgetText(ctx, 'Wait for this chart to finish loading its data'));
    };
    const canCopy = canCopyImage();
    openMenu(ctx, anchor, [
      { label: widgetText(ctx, 'Download PNG'), onSelect: () => {
        const ok = downloadCanvas(doc, () => ctx.chart.takeScreenshot(), captureName(s.symbol, s.interval) + '.png');
        ctx.status(ok ? widgetText(ctx, 'Saved a PNG of the chart') : widgetText(ctx, 'This runtime cannot save files'), ok ? 'info' : 'error');
      } },
      { label: widgetText(ctx, 'Download SVG'), sub: widgetText(ctx, 'text stays text'), onSelect: () => {
        const ok = downloadText(doc, captureName(s.symbol, s.interval) + '.svg', ctx.chart.exportSVG(), 'image/svg+xml');
        ctx.status(ok ? widgetText(ctx, 'Saved an SVG of the chart') : widgetText(ctx, 'This runtime cannot save files'), ok ? 'info' : 'error');
      } },
      { label: widgetText(ctx, 'Copy image'), sub: canCopy ? widgetText(ctx, 'paste it anywhere') : widgetText(ctx, 'needs https or localhost'), disabled: !canCopy, onSelect: () => {
        copyCanvasImage(ctx, ctx.chart.takeScreenshot(), widgetText(ctx, 'Chart copied'), (message, kind) => ctx.status(message, kind));
      } },
      { label: widgetText(ctx, 'Download chart data (CSV)'), disabled: !dataAvailable(), onSelect: () => {
        const failed = (error: unknown): void => ctx.status(widgetText(ctx, 'Data export failed: {error}', { error: errorText(ctx, error) }), 'error');
        // The dialog loads on first use (lazy.ts), and the chart it captures is checked again when it arrives.
        usePart(dataExportPart, module => {
          try {
            checkSource();
            dataDialog?.close();
            dataDialog = module.openChartDataExportDialog(ctx, anchor, options => {
              checkSource();
              const csv = exportChartDataCsv(capturedChart, options);
              checkSource();
              if (!downloadText(doc, captureName(s.symbol, s.interval) + '.csv', csv, 'text/csv;charset=utf-8')) {
                throw new Error(widgetText(ctx, 'This runtime cannot save files'));
              }
              ctx.status(widgetText(ctx, 'Chart data download started'));
            });
          } catch (error) { failed(error); }
        }, error => ctx.status(partFailed(ctx, widgetText(ctx, 'Download chart data (CSV)'), error), 'error'), () => host.isConnected, { slot: dataSlot, doc, from: anchor });
      } },
      ...(opts.captureRows?.() ?? []),
    ], { ariaLabel: widgetText(ctx, 'Capture') });
  };
  snapBtn.addEventListener('click', () => openCapture(snapBtn));
  host.appendChild(snapBtn);

  // ── settings ─────────────────────────────────────────────────────────
  const setBtn = btn(widgetText(ctx, 'Chart settings'), 'oac-btn--icon');
  setBtn.appendChild(glyph(doc, chromeIconSvg('settings'), 'chrome'));
  ctx.tips.attach(setBtn, () => ({
    title: widgetText(ctx, 'Chart settings'),
    sub: opts.settingsAvailable() ? undefined : widgetText(ctx, 'The settings dialog is not in this build'),
    side: 'bottom',
  }));
  setBtn.addEventListener('click', () => { if (!setBtn.classList.contains('is-off')) opts.onSettings(setBtn); });
  host.appendChild(setBtn);

  // ── theme ────────────────────────────────────────────────────────────
  // The theme the click switches to, as a sun or a moon; the tip and the
  // accessible name say it in words.
  const themeBtn = btn(widgetText(ctx, 'Theme'), 'oac-btn--icon oac-topbar__theme');
  const themeGlyph = glyph(doc, '', 'chrome');
  themeBtn.appendChild(themeGlyph);
  ctx.tips.attach(themeBtn, () => ({ title: opts.state().theme === 'dark' ? widgetText(ctx, 'Switch to the light theme') : widgetText(ctx, 'Switch to the dark theme'), side: 'bottom' }));
  themeBtn.addEventListener('click', () => opts.onTheme(opts.state().theme === 'dark' ? 'light' : 'dark'));
  host.appendChild(themeBtn);

  if (indBtn !== null) {
    ctx.tips.attach(indBtn, () => ({
      title: widgetText(ctx, 'Indicators'),
      sub: opts.indicatorsAvailable() ? widgetText(ctx, 'Add a study to the chart') : widgetText(ctx, 'The indicator picker is not in this build'),
      side: 'bottom',
    }));
  }

  const refresh = (): void => {
    const s = opts.state();
    if (doc.activeElement !== symInput) symInput.value = s.symbol;
    symEx.textContent = s.exchange;
    symEx.hidden = s.exchange === '';
    for (const [code, b] of pillByCode) {
      const on = code === s.interval;
      b.setAttribute('aria-pressed', String(on));
      b.setAttribute('aria-checked', String(on));
    }
    if (typeGlyph.dataset.type !== s.chartType) {
      typeGlyph.dataset.type = s.chartType;
      typeGlyph.hidden = chartTypeIcon(s.chartType) === undefined;
      typeGlyph.innerHTML = typeGlyph.hidden ? '' : chromeIconSvg(`chart-${s.chartType}`);
    }
    typeLabel.textContent = widgetText(ctx, `schema.chartType.${s.chartType}`, {}, chartTypeLabel(s.chartType));
    typeSettings.refresh();
    setOff(setBtn, !opts.settingsAvailable());
    if (indBtn !== null) setOff(indBtn, !opts.indicatorsAvailable());
    if (goTo !== null) setOff(goTo, timeBuckets(s.interval) === null);
    if (themeBtn.dataset.theme !== s.theme) {
      themeBtn.dataset.theme = s.theme;
      themeGlyph.innerHTML = chromeIconSvg(s.theme === 'dark' ? 'sun' : 'moon');
    }
    ctx.tips.refreshLabel(themeBtn);
    ctx.tips.refreshLabel(setBtn);
    if (indBtn !== null) ctx.tips.refreshLabel(indBtn);
    const link = brandingLink(ctx.chart, ctx);
    if (link === null) {
      brandingAnchor?.remove();
      brandingAnchor = null;
    } else {
      if (brandingAnchor === null) {
        brandingAnchor = h(doc, 'a', 'oac-topbar__branding', {
          target: '_blank', rel: 'noopener noreferrer',
        });
        brandingSlot.appendChild(brandingAnchor);
      }
      brandingAnchor.setAttribute('href', link.href);
      brandingAnchor.textContent = link.label;
      brandingAnchor.setAttribute('aria-label', link.label);
    }
  };
  const offBranding = ctx.chart.on('branding:changed', refresh);
  refresh();

  return {
    el: host,
    openCapture,
    refresh,
    focusSymbol: () => { symInput.focus(); },
    destroy: () => {
      dataDialog?.close();
      typeSettings.close();
      offLayouts?.();
      offBranding();
      picker?.destroy();
      host.textContent = '';
    },
  };
}

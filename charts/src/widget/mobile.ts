import { widgetText } from './localization';
import { chartTypeIcon, chromeIconSvg, registeredDrawingTools } from 'openalgo-charts/draw';
import { h, glyph, historyPress, historyReady, type WidgetContext } from './context';
import { drawingActionState, runDrawingAction } from './drawing-actions';
import type { RailHandle } from './rail';
import {
  chartTypeChoices, chartTypeLabel, intervalLabel,
  brandingLink, type SymbolSearch, type TopbarState,
} from './topbar';
import { mountSymbolPicker, type SymbolPickerHandle } from './symbol-picker';
import { timeBuckets } from './date-navigator';
import { SCALE_TOGGLES, type BottombarControls } from './bottombar';

export type MobileMode = 'auto' | 'always' | 'never';

/** A container at most this many CSS px wide gets the compact controls, whatever the pointer. */
export const MOBILE_MAX_WIDTH = 640;
/**
 * The widest container a phone on its side gives the widget (the largest
 * phones are about 930 CSS px wide in landscape). Up to this width a coarse
 * pointer in a short container keeps the compact controls, so turning a phone
 * does not swap its chrome.
 */
export const PHONE_LANDSCAPE_MAX_WIDTH = 960;
/**
 * A coarse-pointer container at least this tall is a tablet, not a phone on
 * its side. Phones in landscape leave the page about 430 px or less, and a
 * tablet in landscape keeps about 690 px or more after the browser's bars, so
 * the cut sits between them. Height only splits the two while the width is
 * ambiguous: past {@link PHONE_LANDSCAPE_MAX_WIDTH} no phone is involved.
 */
export const TABLET_MIN_HEIGHT = 600;

/**
 * Whether the widget shows its compact controls for a container of the given
 * size. `auto` decides by the container, never the window, so a narrow chart
 * in a wide dashboard is compact too. A fine pointer switches at
 * {@link MOBILE_MAX_WIDTH}. A coarse pointer alone does not make a phone: a
 * tablet in either orientation, or a touch laptop, has room for the toolbar
 * and the drawing rail, which put every tool one tap away, where the compact
 * layout keeps them a sheet away. Only a phone on its side (wide but short)
 * widens the cutoff. An unmeasured container (width 0) is not compact.
 */
export function resolveMobileMode(mode: MobileMode, width: number, height: number, coarsePointer: boolean): boolean {
  if (mode !== 'auto') return mode === 'always';
  if (!(width > 0)) return false;
  if (width <= MOBILE_MAX_WIDTH) return true;
  return coarsePointer && width <= PHONE_LANDSCAPE_MAX_WIDTH && height > 0 && height < TABLET_MIN_HEIGHT;
}

export interface MobileOptions {
  mode?: MobileMode | undefined;
  container: HTMLElement;
  intervals: readonly string[];
  topbar: boolean;
  rail: RailHandle | null;
  tools?: readonly string[] | undefined;
  indicators: boolean;
  search?: SymbolSearch | undefined;
  state(): TopbarState;
  onSymbol(symbol: string, exchange?: string): void;
  onInterval(code: string): void;
  onChartType(id: string): void;
  onTheme(): void;
  onSettings(anchor: HTMLElement): boolean;
  onIndicators(anchor: HTMLElement): boolean;
  onObjects(anchor: HTMLElement): boolean;
  onDataWindow?(anchor: HTMLElement): void | boolean;
  onAlerts?(anchor: HTMLElement): boolean;
  onWatchlist?(anchor: HTMLElement): void | boolean;
  onNews?(anchor: HTMLElement): void | boolean;
  onCapture?(anchor: HTMLElement): void;
  onGoTo?(anchor: HTMLElement): void | boolean;
  /** Open the Layouts menu, centred. Omitted without a store. Since 2.5.10. */
  onLayouts?(anchor: HTMLElement): void | boolean;
  onProperties(anchor: HTMLElement): boolean;
  settingsAvailable(): boolean;
  indicatorsAvailable(): boolean;
  /**
   * The bottom bar's controls. The phone layout hides the bar, so the More
   * sheet lists them instead: the market status and the clock, the preset
   * ranges, the price scale toggles and the timezone.
   */
  bottombar?: BottombarControls | undefined;
}

export interface MobileHandle {
  readonly el: HTMLElement;
  active(): boolean;
  refresh(): void;
  destroy(): void;
}

interface OpenSheet {
  close(): void;
  repaint(): void;
}

interface ActionIdentity {
  action: string;
  tool?: string;
  interval?: string;
  chartType?: string;
  range?: string;
  scale?: string;
  zone?: string;
}

/** The data attributes an action's identity is read from, so a repaint can put focus back on the same control. */
const IDENTITY_KEYS = ['tool', 'interval', 'chartType', 'range', 'scale', 'zone'] as const;

/** Mount the narrow widget controls against the same chart and controllers as the desktop chrome. */
export function mountMobile(ctx: WidgetContext, opts: MobileOptions): MobileHandle {
  const doc = ctx.document;
  const mode = opts.mode ?? 'auto';
  const root = h(doc, 'div', 'oac-mobile');
  ctx.root.appendChild(root);

  let destroyed = false;
  let mobile = false;
  let modeApplied = false;
  let picker: SymbolPickerHandle | null = null;
  let symbolInput: HTMLInputElement | null = null;
  let sheet: OpenSheet | null = null;
  const offs: Array<() => void> = [];

  const stopPointer = (event: Event): void => { event.stopPropagation(); };
  root.addEventListener('pointerdown', stopPointer);

  const makeAction = (name: string, label: string, run: (button: HTMLButtonElement) => void): HTMLButtonElement => {
    const button = h(doc, 'button', 'oac-mobile__action', { type: 'button' });
    button.dataset.mobileAction = name;
    button.textContent = label;
    button.addEventListener('click', () => {
      if (button.getAttribute('aria-disabled') !== 'true') run(button);
    });
    return button;
  };

  /**
   * Undo and redo for the whole chart, shown disabled with nothing to take
   * back: the same timeline as the desktop chords and rail.
   */
  const historyActions = (): HTMLButtonElement[] => (['undo', 'redo'] as const).map((direction) => {
    const button = makeAction(direction, widgetText(ctx, direction === 'undo' ? 'Undo' : 'Redo'), () => { historyPress(ctx, direction); refresh(); });
    button.setAttribute('aria-disabled', String(!historyReady(ctx, direction)));
    return button;
  });

  const identityOf = (element: HTMLElement): ActionIdentity | null => {
    const button = element.closest('[data-mobile-action]') as HTMLElement | null;
    const action = button?.dataset.mobileAction;
    if (button === null || action === undefined) return null;
    const identity: ActionIdentity = { action };
    for (const key of IDENTITY_KEYS) if (button.dataset[key] !== undefined) identity[key] = button.dataset[key];
    return identity;
  };

  const findIdentity = (host: HTMLElement, identity: ActionIdentity): HTMLElement | null => {
    const candidates = Array.from(host.querySelectorAll('[data-mobile-action]')) as HTMLElement[];
    return candidates.find((button) => button.dataset.mobileAction === identity.action
      && IDENTITY_KEYS.every(key => button.dataset[key] === identity[key])) ?? null;
  };

  const closeSheet = (): void => {
    const current = sheet;
    sheet = null;
    current?.close();
  };

  const clearSearch = (): void => picker?.close();

  const openSheet = (
    title: string,
    anchor: HTMLElement,
    paint: (body: HTMLElement, close: () => void) => void,
    initialFocus: HTMLElement | null | undefined = undefined,
  ): void => {
    closeSheet();
    const panel = h(doc, 'section', 'oac-mobile-sheet', { 'aria-label': title });
    const head = h(doc, 'div', 'oac-mobile-sheet__head oac-dialog__head');
    const heading = h(doc, 'strong', 'oac-mobile-sheet__title');
    heading.textContent = title;
    const closeButton = makeAction('close', widgetText(ctx, 'Close'), () => closeSheet());
    head.append(heading, closeButton);
    const body = h(doc, 'div', 'oac-mobile-sheet__body');
    panel.append(head, body);
    const repaint = (): void => {
      if (destroyed || sheet?.repaint !== repaint) return;
      const focused = doc.activeElement as HTMLElement | null;
      const hadBodyFocus = focused !== null && body.contains(focused);
      const identity = hadBodyFocus ? identityOf(focused) : null;
      const scrollTop = body.scrollTop;
      body.textContent = '';
      paint(body, closeSheet);
      body.scrollTop = scrollTop;
      if (hadBodyFocus) {
        const next = identity === null ? null : findIdentity(body, identity);
        (next ?? body.querySelector<HTMLElement>('[data-mobile-action]'))?.focus();
      }
    };
    let closeOverlay: () => void = () => {};
    const entry: OpenSheet = {
      close: () => closeOverlay(),
      repaint,
    };
    sheet = entry;
    paint(body, closeSheet);
    closeOverlay = ctx.openOverlay(panel, {
      anchor,
      placement: 'center',
      dismissOnOutside: true,
      initialFocus,
      onClose: () => { if (sheet === entry) sheet = null; },
    });
  };

  let intervalButton: HTMLButtonElement | null = null;
  if (opts.topbar) {
    const header = h(doc, 'div', 'oac-mobile__header', { role: 'toolbar', 'aria-label': widgetText(ctx, 'Chart header') });
    symbolInput = h(doc, 'input', 'oac-mobile__symbol', {
      type: 'text', 'aria-label': widgetText(ctx, 'Symbol'), placeholder: widgetText(ctx, 'Symbol'), autocomplete: 'off', spellcheck: 'false',
    });
    intervalButton = makeAction('interval', '', (anchor) => {
      openSheet(widgetText(ctx, 'Interval'), anchor, (body, close) => {
        for (const code of opts.intervals) {
          const button = makeAction('pick-interval', intervalLabel(code), () => {
            opts.onInterval(code);
            close();
          });
          button.dataset.interval = code;
          const selected = opts.state().interval === code;
          button.setAttribute('aria-pressed', String(selected));
          body.appendChild(button);
        }
      });
    });
    const commitSymbol = (symbol: string, exchange?: string): void => {
      const value = symbol.trim().toUpperCase();
      clearSearch();
      if (value !== '') opts.onSymbol(value, exchange);
      refresh();
      symbolInput?.blur();
    };
    if (opts.search !== undefined) picker = mountSymbolPicker(ctx, symbolInput, {
      search: opts.search,
      onSelect: commitSymbol,
      context: () => `${opts.state().exchange}:${opts.state().symbol}:${opts.state().interval}`,
      variant: 'mobile',
    });
    symbolInput.addEventListener('keydown', (event) => {
      if ((event as KeyboardEvent).key === 'Enter') {
        event.preventDefault();
        // As in the top bar: a search still running decides what Enter picks.
        if (picker === null || picker.canCommitRaw()) commitSymbol(symbolInput?.value ?? '');
      }
    });
    header.append(symbolInput, intervalButton);
    root.appendChild(header);
  }

  const footer = h(doc, 'div', 'oac-mobile__footer');
  const selection = h(doc, 'div', 'oac-mobile__selection', { role: 'toolbar', 'aria-label': widgetText(ctx, 'Selected drawing') });
  let propertiesButton: HTMLButtonElement | null = null;
  let lockButton: HTMLButtonElement | null = null;
  let deleteButton: HTMLButtonElement | null = null;
  if (opts.rail !== null) {
    propertiesButton = makeAction('properties', widgetText(ctx, 'Properties'), (anchor) => { opts.onProperties(anchor); });
    // The rules every drawing surface keeps (drawing-actions.ts).
    lockButton = makeAction('lock', widgetText(ctx, 'Lock'), () => {
      runDrawingAction(ctx, 'lock', ctx.draw.selection());
      refresh();
    });
    deleteButton = makeAction('delete', widgetText(ctx, 'Delete'), () => {
      runDrawingAction(ctx, 'delete', ctx.draw.selection());
      refresh();
    });
    selection.append(propertiesButton, lockButton, deleteButton);
    footer.appendChild(selection);
  }

  const bar = h(doc, 'nav', 'oac-mobile__bar', { 'aria-label': widgetText(ctx, 'Chart controls') });
  let drawButton: HTMLButtonElement | null = null;
  let studiesButton: HTMLButtonElement | null = null;
  if (opts.rail !== null) {
    drawButton = makeAction('draw', widgetText(ctx, 'Draw'), (anchor) => {
      openSheet(widgetText(ctx, 'Drawing'), anchor, (body) => {
        const active = ctx.draw.activeTool();
        if (active !== null) {
          const controls = h(doc, 'div', 'oac-mobile-sheet__controls');
          controls.append(
            makeAction('finish', widgetText(ctx, 'Finish'), () => { ctx.draw.finish(); refresh(); }),
            makeAction('cancel', widgetText(ctx, 'Cancel'), () => { ctx.draw.cancel(); refresh(); }),
            ...historyActions(),
            makeAction('magnet', widgetText(ctx, 'Magnet: {mode}', { mode: widgetText(ctx, `schema.magnet.${opts.rail?.magnetMode() ?? 'off'}`, {}, opts.rail?.magnetMode() ?? 'off') }), () => { opts.rail?.cycleMagnet(); refresh(); }),
            makeAction('stay', widgetText(ctx, 'Keep tool active: {mode}', { mode: opts.rail?.stayMode() ? widgetText(ctx, 'on') : widgetText(ctx, 'off') }), () => {
              if (opts.rail !== null) opts.rail.setStayMode(!opts.rail.stayMode());
              refresh();
            }),
          );
          body.appendChild(controls);
        }
        const allowed = opts.tools === undefined ? null : new Set(opts.tools);
        for (const tool of registeredDrawingTools()) {
          if (allowed !== null && !allowed.has(tool.id)) continue;
          const button = makeAction('tool', widgetText(ctx, `schema.drawing.${tool.id}.name`, {}, tool.name), () => {
            ctx.draw.setTool(tool.id);
            closeSheet();
          });
          button.classList.add('oac-mobile__tool');
          button.dataset.tool = tool.id;
          button.setAttribute('aria-pressed', String(active === tool.id));
          body.appendChild(button);
        }
      });
    });
    bar.appendChild(drawButton);
  }
  if (opts.topbar && opts.indicators) {
    studiesButton = makeAction('studies', widgetText(ctx, 'Indicators'), (anchor) => { opts.onIndicators(anchor); });
    bar.appendChild(studiesButton);
  }
  if (opts.topbar) {
    bar.appendChild(makeAction('objects', widgetText(ctx, 'Objects'), (anchor) => { opts.onObjects(anchor); }));
    if (opts.onDataWindow) bar.appendChild(makeAction('data-window', widgetText(ctx, 'schema.ui.dataWindow', {}, 'Data'), (anchor) => { opts.onDataWindow?.(anchor); }));
    bar.appendChild(makeAction('more', widgetText(ctx, 'More'), (anchor) => {
      openSheet(widgetText(ctx, 'More'), anchor, (body, close) => {
        const bottom = opts.bottombar;
        // The bar's readout first, since the sheet stands in for the hidden bar.
        if (bottom !== undefined) body.appendChild(statusNote(bottom));
        // Then: a step taken on a narrow screen needs a way back that does not depend on a tool being active.
        body.append(...historyActions());
        if (opts.onCapture) body.appendChild(makeAction('capture', widgetText(ctx, 'Capture'), () => {
          close();
          opts.onCapture?.(anchor);
        }));
        // Layouts: the same menu as the top bar's button.
        if (opts.onLayouts) body.appendChild(makeAction('layouts', widgetText(ctx, 'schema.ui.layouts.title', {}, 'Layouts'), () => { close(); opts.onLayouts?.(anchor); }));
        for (const [key, label, handler] of [['watchlist', 'Watchlist', opts.onWatchlist], ['news', 'News', opts.onNews]] as const) {
          if (handler) body.appendChild(makeAction(key, widgetText(ctx, `schema.ui.dock.${key}`, {}, label), () => { close(); handler(anchor); }));
        }
        if (opts.onAlerts) body.appendChild(makeAction('alerts', widgetText(ctx, 'Alerts'), () => {
          close();
          opts.onAlerts?.(anchor);
        }));
        if (opts.onGoTo) {
          const goTo = makeAction('go-to', widgetText(ctx, 'Go to'), () => {
            close();
            opts.onGoTo?.(anchor);
          });
          goTo.setAttribute('aria-disabled', String(timeBuckets(opts.state().interval) === null));
          body.appendChild(goTo);
        }
        // An action, as the top bar's theme button words it: "Light theme" read as the state.
        const theme = makeAction('theme', opts.state().theme === 'dark' ? widgetText(ctx, 'Switch to the light theme') : widgetText(ctx, 'Switch to the dark theme'), () => {
          opts.onTheme();
          close();
        });
        body.appendChild(theme);
        const settings = makeAction('settings', widgetText(ctx, 'Chart settings'), () => {
          close();
          opts.onSettings(anchor);
        });
        settings.setAttribute('aria-disabled', String(!opts.settingsAvailable()));
        body.appendChild(settings);
        const link = brandingLink(ctx.chart, ctx);
        if (link !== null) {
          const branding = h(doc, 'a', 'oac-mobile__action oac-mobile__branding', {
            href: link.href, target: '_blank', rel: 'noopener noreferrer', 'aria-label': link.label,
          });
          branding.dataset.mobileAction = 'branding';
          branding.textContent = link.label;
          body.appendChild(branding);
        }
        if (bottom !== undefined) barRows(body, bottom, anchor, close);
        const heading = h(doc, 'div', 'oac-head');
        heading.textContent = widgetText(ctx, 'Chart type');
        body.appendChild(heading);
        for (const id of chartTypeChoices()) {
          const button = makeAction('chart-type', widgetText(ctx, `schema.chartType.${id}`, {}, chartTypeLabel(id)), () => {
            opts.onChartType(id);
            close();
          });
          // The same glyph as the desktop menu, beside the words a phone keeps.
          if (chartTypeIcon(id) !== undefined) button.prepend(glyph(doc, chromeIconSvg(`chart-${id}`), 'chrome'));
          button.dataset.chartType = id;
          button.setAttribute('aria-pressed', String(opts.state().chartType === id));
          body.appendChild(button);
        }
      });
    }));
  }
  if (bar.children.length > 0) footer.appendChild(bar);
  if (footer.children.length > 0) root.appendChild(footer);

  /** The market status and the clock, read when the sheet paints. */
  function statusNote(controls: BottombarControls): HTMLElement {
    const note = h(doc, 'p', 'oac-mobile-sheet__note');
    const reading = controls.marketStatus();
    if (reading !== null) {
      const state = h(doc, 'b');
      state.textContent = reading.label;
      note.append(state, doc.createTextNode(reading.detail === '' ? ' \u00b7 ' : ` ${reading.detail} \u00b7 `));
    }
    note.appendChild(doc.createTextNode(controls.clock()));
    return note;
  }

  /** The bar's ranges, scale toggles and zone as sheet rows. */
  function barRows(body: HTMLElement, controls: BottombarControls, anchor: HTMLElement, close: () => void): void {
    const head = (text: string): void => {
      const heading = h(doc, 'div', 'oac-head');
      heading.textContent = text;
      body.appendChild(heading);
    };
    /** A row of short choices across the sheet, so nine ranges take two rows rather than five. */
    const row = (cls: string, text: string): HTMLElement => {
      head(text);
      const group = h(doc, 'div', cls, { role: 'group', 'aria-label': text });
      body.appendChild(group);
      return group;
    };
    const ranges = controls.ranges();
    if (ranges.length > 0) {
      const group = row('oac-mobile-sheet__ranges', widgetText(ctx, 'schema.ui.bottombar.ranges', {}, 'Range'));
      const current = controls.range();
      for (const range of ranges) {
        const button = makeAction('range', widgetText(ctx, `schema.ui.range.${range.id}`, {}, range.label), () => {
          controls.setRange(range.id);
          close();
        });
        button.dataset.range = range.id;
        button.setAttribute('aria-pressed', String(current === range.id));
        group.appendChild(button);
      }
    }
    const scales = row('oac-mobile-sheet__scales', widgetText(ctx, 'schema.ui.bottombar.scale', {}, 'Price scale'));
    const scale = controls.scale();
    // Words, not the bar's glyphs: a phone has no hover to explain a glyph.
    for (const toggle of SCALE_TOGGLES) {
      const button = makeAction('scale', widgetText(ctx, toggle.key, {}, toggle.label), () => {
        controls.toggleScale(toggle.id);
        refresh();
      });
      button.dataset.scale = toggle.id;
      button.setAttribute('aria-pressed', String(scale !== null && scale[toggle.id]));
      button.setAttribute('aria-disabled', String(scale === null));
      scales.appendChild(button);
    }
    head(widgetText(ctx, 'schema.ui.bottombar.timezones', {}, 'Timezone'));
    const zone = makeAction('timezone', controls.timezone(), () => {
      openSheet(widgetText(ctx, 'schema.ui.bottombar.timezones', {}, 'Timezone'), anchor, (list, done) => {
        const current = controls.timezone();
        for (const name of controls.timezones()) {
          const choice = makeAction('pick-zone', name, () => {
            controls.setTimezone(name);
            done();
          });
          choice.dataset.zone = name;
          choice.setAttribute('aria-pressed', String(name === current));
          list.appendChild(choice);
        }
      });
    });
    zone.setAttribute('aria-label', widgetText(ctx, 'schema.ui.bottombar.timezone', { zone: controls.timezone() }, 'Timezone: {zone}'));
    zone.setAttribute('aria-haspopup', 'dialog');
    body.appendChild(zone);
  }

  function refresh(): void {
    if (destroyed) return;
    const state = opts.state();
    if (symbolInput !== null && doc.activeElement !== symbolInput) symbolInput.value = state.symbol;
    if (intervalButton !== null) intervalButton.textContent = intervalLabel(state.interval);
    if (drawButton !== null) drawButton.setAttribute('aria-pressed', String(ctx.draw.activeTool() !== null));
    if (studiesButton !== null) studiesButton.setAttribute('aria-disabled', String(!opts.indicatorsAvailable()));
    if (selection.parentNode !== null) {
      const ids = ctx.draw.selection();
      selection.hidden = ids.length === 0;
      // Lock has nothing to act on in a read-only selection, and delete keeps a locked one too.
      const state = drawingActionState(ctx, ids);
      if (ids.length > 0 && lockButton !== null) {
        // One name; the pressed state says locked.
        lockButton.setAttribute('aria-pressed', String(state.locked));
        lockButton.setAttribute('aria-disabled', String(state.editable.length === 0));
      }
      if (propertiesButton !== null) propertiesButton.setAttribute('aria-disabled', String(ids.length === 0));
      if (deleteButton !== null) deleteButton.setAttribute('aria-disabled', String(state.noDelete !== null || state.editable.length === 0));
    }
    sheet?.repaint();
  }

  const pointerQuery = mode === 'auto' ? doc.defaultView?.matchMedia?.('(pointer: coarse)') ?? null : null;
  // Any form field counts: a focused checkbox only delays a switch until blur,
  // and naming the keyboard-raising input types costs the tier bytes.
  const typing = (el: Element | null): boolean => el !== null && ctx.root.contains(el)
    && (/^(INPUT|TEXTAREA)$/.test(el.tagName) || (el as HTMLElement).isContentEditable === true);
  // Set when a switch waits for a text field to lose focus.
  let held = false;
  const apply = (whileTyping: boolean): void => {
    const rect = opts.container.getBoundingClientRect();
    const width = rect.width || opts.container.clientWidth;
    const height = rect.height || opts.container.clientHeight;
    // A container hidden or collapsed after it was measured reports 0 in one
    // dimension or both. Keep what it had rather than close an open sheet
    // over a size nobody can see.
    if (modeApplied && !(width * height > 0)) return;
    const next = resolveMobileMode(mode, width, height, pointerQuery?.matches === true);
    if (modeApplied && next === mobile) { held = false; return; }
    // An on-screen keyboard can shorten the container past the tablet
    // height; switching then would hide the field being typed in and
    // dismiss the keyboard. The switch waits for the field to lose focus.
    if (modeApplied && !whileTyping && typing(doc.activeElement)) { held = true; return; }
    held = false;
    modeApplied = true;
    mobile = next;
    ctx.root.classList.toggle('is-mobile', mobile);
    ctx.root.dataset.mobile = String(mobile);
    root.hidden = !mobile;
    if (!mobile) { closeSheet(); clearSearch(); }
  };
  const applyMode = (): void => apply(false);

  const Observer = (doc.defaultView as (Window & typeof globalThis) | null)?.ResizeObserver;
  let observer: ResizeObserver | null = null;
  if (mode === 'auto') {
    const onFocusOut = (event: Event): void => {
      if (held && !typing((event as FocusEvent).relatedTarget as Element | null)) apply(true);
    };
    ctx.root.addEventListener('focusout', onFocusOut);
    offs.push(() => ctx.root.removeEventListener('focusout', onFocusOut));
  }
  if (mode === 'auto' && Observer !== undefined) {
    observer = new Observer(applyMode);
    observer.observe(opts.container);
  } else if (mode === 'auto') {
    const win = doc.defaultView;
    if (win !== null && typeof win.addEventListener === 'function') {
      win.addEventListener('resize', applyMode);
      offs.push(() => win.removeEventListener('resize', applyMode));
    }
  }
  if (pointerQuery !== null) {
    if (typeof pointerQuery.addEventListener === 'function') {
      pointerQuery.addEventListener('change', applyMode);
      offs.push(() => pointerQuery.removeEventListener('change', applyMode));
    } else {
      pointerQuery.addListener(applyMode);
      offs.push(() => pointerQuery.removeListener(applyMode));
    }
  }

  for (const event of ['draw:tool', 'draw:select', 'drawing:select', 'drawing:change', 'draw:add', 'draw:remove', 'draw:update'] as const) {
    offs.push(ctx.chart.on(event, refresh));
  }
  if (ctx.history !== undefined) offs.push(ctx.history.subscribe(refresh));
  offs.push(ctx.bus.on('symbol', refresh));
  offs.push(ctx.bus.on('interval', refresh));
  offs.push(ctx.bus.on('theme', refresh));
  offs.push(ctx.chart.on('branding:changed', refresh));
  // A range, a zone or a scale changed from anywhere, or the market moved on.
  if (opts.bottombar !== undefined) offs.push(opts.bottombar.subscribe(refresh));
  applyMode();
  refresh();

  return {
    el: root,
    active: () => mobile,
    refresh,
    destroy: () => {
      if (destroyed) return;
      destroyed = true;
      picker?.destroy();
      closeSheet();
      observer?.disconnect();
      observer = null;
      for (const off of offs.splice(0)) off();
      root.removeEventListener('pointerdown', stopPointer);
      root.remove();
      ctx.root.classList.remove('is-mobile');
      delete ctx.root.dataset.mobile;
    },
  };
}

/**
 * The floating toolbar for the selected drawings, on a desktop layout: the
 * edits a trader makes most (colour, width, line style, lock, delete) one
 * click from the drawing, and the rest behind a "more" menu. The narrow
 * layout has its own selection bar (`mobile.ts`), so the stylesheet stands
 * this one down while that is active.
 *
 * It sits over the chart just above the selection, moved below it when the
 * top has no room and clamped inside the chart, and follows a pan, a zoom, a
 * resize or an edit. It steps aside while a drawing is being dragged or a
 * tool is placing, when it would sit on the thing being moved.
 *
 * A control appears only where every selected drawing's settings schema has
 * the field behind it, the rule the properties dialog keeps. When the
 * selected drawings disagree on a value the control says "mixed" rather than
 * showing the first one's. Each change is one `updateMany` (or one
 * transaction on the chart history), so one click is one undo step, and a
 * selection the user may not edit shows its controls greyed with the reason.
 */
import { applyDrawingSettings, chromeIconSvg, drawingSettingsSchema, LINE_STYLE_OPTIONS } from 'openalgo-charts/draw';
import type { Drawing, SettingsField } from 'openalgo-charts/draw';
import { boxIn, drawingToolOf, editableIds, historyStep, type WidgetContext } from './context';
import { drawingActionState, runDrawingAction, type DrawingAction } from './drawing-actions';
import { commandChord } from './keymap';
import { createColorPicker } from './color-picker';
import { button, chromeGlyph, el } from './form';
import { widgetText } from './localization';
import { openMenu, type MenuRow } from './menu';
import { commonSchema, mountDrawingProperties, resolvedDrawingValues } from './dialogs/drawing-properties';
import { chartContainer } from './dialogs/text-editor';
import { templateMenuRows, type DrawingTemplates } from './drawing-templates';

export interface DrawingToolbarOptions {
  /** The chart's container; the toolbar keeps inside it. Default: the chart's own. */
  chart?: HTMLElement;
  /** Saved looks, for the template rows of the more menu. */
  templates?: DrawingTemplates | null;
}

export interface DrawingToolbarHandle {
  readonly el: HTMLElement;
  /** Read the selection again: values, enabled states and position. */
  refresh(): void;
  destroy(): void;
}

/** Widths offered in the width menu: the steps a stroke visibly changes at. */
export const TOOLBAR_LINE_WIDTHS: readonly number[] = [1, 1.5, 2, 3, 4];

/**
 * The chrome glyph for each line style, and for a selection that disagrees
 * (a solid line over a dashed one). The solid line is `minus`, the same drawing.
 */
const LINE_STYLE_ICONS: Readonly<Record<string, string>> = {
  solid: 'minus', dashed: 'line-dashed', dotted: 'line-dotted', mixed: 'line-mixed',
};

/** Room kept between the toolbar and the selection, and between it and the chart's edge. */
const GAP = 10;
const PAD = 6;

const MIXED: unique symbol = Symbol('mixed');
type Across<T> = T | typeof MIXED | undefined;

/**
 * The value every drawing agrees on at `path`, `MIXED` when they differ, or
 * undefined when none has the field. Values are compared as JSON, so two
 * equal colours written the same way are one value.
 */
export function valueAcross(drawings: readonly Drawing[], field: SettingsField, themeLine: string): Across<unknown> {
  let first: unknown;
  let seen = false;
  for (const d of drawings) {
    const tool = drawingToolOf(d.tool);
    const value = resolvedDrawingValues(d, { fields: [field] }, tool, themeLine)[field.path];
    if (!seen) { first = value; seen = true; continue; }
    if (JSON.stringify(value) !== JSON.stringify(first)) return MIXED;
  }
  return seen ? first : undefined;
}

let sequence = 0;

/**
 * Mount the toolbar in `host` (the widget's stage), right after the chart in
 * the tab order, so Tab from the focused chart reaches it.
 */
export function mountDrawingToolbar(ctx: WidgetContext, host: HTMLElement, opts: DrawingToolbarOptions = {}): DrawingToolbarHandle {
  const { draw, chart } = ctx;
  const doc = ctx.document;
  const id = `oac-drawbar-${++sequence}`;
  const bar = el(doc, 'div', 'oac-drawbar');
  bar.setAttribute('role', 'toolbar');
  bar.setAttribute('aria-label', widgetText(ctx, 'Drawing toolbar'));
  // The widget's keymap gives this scope the arrows while focus is here, so
  // they walk the toolbar instead of nudging the drawing it edits.
  bar.dataset.keyScope = 'drawing-toolbar';
  bar.hidden = true;
  const container = (): HTMLElement | null => opts.chart ?? chartContainer(chart);
  const anchor = container();
  const siblings = Array.from(host.children);
  const at = anchor === null ? -1 : siblings.indexOf(anchor);
  host.insertBefore(bar, at < 0 ? null : siblings[at + 1] ?? null);

  const stop = (event: Event): void => { event.stopPropagation(); };
  bar.addEventListener('pointerdown', stop);
  bar.addEventListener('dblclick', stop);

  let ids: string[] = [];
  let live: Drawing[] = [];
  let fields = new Map<string, SettingsField>();
  let dragging = false;
  let destroyed = false;

  /** One of the shared drawing actions, on the selection or the one a menu opened for. */
  const run = (action: DrawingAction, targets: readonly string[] = ids): void => {
    runDrawingAction(ctx, action, targets);
    refresh();
  };
  const writable = (): string[] => editableIds(draw, ids);
  /** Write one setting to every editable selected drawing whose schema declares it. */
  const setField = (path: string, value: unknown): void => {
    const field = fields.get(path);
    if (field === undefined) return;
    const patches = writable().flatMap((target) => {
      const d = draw.get(target);
      // Through the drawing's own schema, which coerces the value to its field's kind.
      const patch = d === undefined ? {} : applyDrawingSettings(d, { [path]: value }, drawingSettingsSchema(d.tool));
      return Object.keys(patch).length > 0 ? [{ id: target, patch }] : [];
    });
    historyStep(ctx, path, () => { if (patches.length > 0) draw.updateMany(patches); });
    refresh();
  };

  // ── controls ───────────────────────────────────────────────────────────
  const color = createColorPicker(doc, {
    id: `${id}-color`, label: widgetText(ctx, 'Color'), value: '#000000', translate: ctx.translate,
    openOverlay: ctx.openOverlay, onChange: (value) => { setField('style.color', value); },
  });
  color.el.classList.add('oac-drawbar__color');
  const colorTrigger = color.trigger;

  const width = button(doc, { label: '', onClick: () => openWidths() });
  width.classList.add('oac-drawbar__width');
  width.setAttribute('aria-haspopup', 'menu');
  const style = button(doc, { label: '', iconOnly: true, onClick: () => openStyles() });
  style.setAttribute('aria-haspopup', 'menu');
  const styleGlyph = el(doc, 'span', 'oac-glyph oac-glyph--chrome');
  style.appendChild(styleGlyph);
  const lock = button(doc, { label: widgetText(ctx, 'Lock'), icon: 'lock', iconOnly: true, onClick: () => { run('lock'); } });
  const remove = button(doc, { label: widgetText(ctx, 'Delete'), icon: 'trash', iconOnly: true, variant: 'danger', onClick: () => { run('delete'); } });
  const more = button(doc, { label: widgetText(ctx, 'More drawing actions'), icon: 'more', iconOnly: true, onClick: () => openMore() });
  more.setAttribute('aria-haspopup', 'menu');
  const sep = (): HTMLElement => el(doc, 'span', 'oac-sep');
  const lineSep = sep();
  bar.append(color.el, width, style, lineSep, lock, remove, sep(), more);
  for (const [name, node] of [['color', colorTrigger], ['width', width], ['style', style], ['lock', lock], ['delete', remove], ['more', more]] as const) {
    node.dataset.drawbar = name;
  }

  const controls = (): HTMLElement[] => [colorTrigger, width, style, lock, remove, more]
    .filter((node) => !(node as HTMLButtonElement).disabled && !node.hidden && !(node === colorTrigger && color.el.hidden));

  /** One tab stop for the whole bar, on the control last used. */
  let current: HTMLElement = more;
  const setRoving = (target: HTMLElement): void => {
    current = target;
    for (const node of [colorTrigger, width, style, lock, remove, more]) node.tabIndex = node === target ? 0 : -1;
  };
  bar.addEventListener('focusin', (event) => {
    const target = (event.target as HTMLElement | null)?.closest?.('[data-drawbar]') as HTMLElement | null;
    if (target !== null && bar.contains(target)) setRoving(target);
  });
  const go = (index: number): void => {
    const all = controls();
    if (all.length === 0) return;
    const next = all[((index % all.length) + all.length) % all.length]!; // a non-empty list, index wrapped into it
    setRoving(next);
    next.focus();
  };
  const position = (): number => controls().indexOf(doc.activeElement as HTMLElement);
  const scoped = (combo: string, run: () => void, label: string, hidden = false): () => void =>
    ctx.keymap.register(combo, run, 'drawing-toolbar', { label, group: 'Drawing toolbar', layered: true, hidden });
  const unbind = [
    scoped('ArrowRight', () => { go(position() + 1); }, 'Next control'),
    scoped('ArrowLeft', () => { go(position() - 1); }, 'Previous control'),
    scoped('Home', () => { go(0); }, 'First control'),
    scoped('End', () => { go(controls().length - 1); }, 'Last control'),
    // Every arrow the widget binds to a nudge is claimed here, so no arrow
    // pressed in the bar moves the drawing it edits.
    scoped('ArrowDown', () => { go(position() + 1); }, 'Next control', true),
    scoped('ArrowUp', () => { go(position() - 1); }, 'Previous control', true),
    scoped('Shift+ArrowRight', () => { go(position() + 1); }, 'Next control', true),
    scoped('Shift+ArrowDown', () => { go(position() + 1); }, 'Next control', true),
    scoped('Shift+ArrowLeft', () => { go(position() - 1); }, 'Previous control', true),
    scoped('Shift+ArrowUp', () => { go(position() - 1); }, 'Previous control', true),
    // Back to the chart with the selection kept, where the editing keys act on it.
    scoped('Escape', () => { container()?.focus(); }, 'Back to the chart'),
  ];

  // ── menus ──────────────────────────────────────────────────────────────
  const menuOf = (anchorEl: HTMLElement, rows: ReadonlyArray<MenuRow | string>, label: string): void => {
    openMenu(ctx, anchorEl, rows, { ariaLabel: label });
  };
  function openWidths(): void {
    const field = fields.get('style.lineWidth');
    if (field === undefined) return;
    const now = valueAcross(live, field, ctx.chartTheme.lineColor);
    menuOf(width, TOOLBAR_LINE_WIDTHS.map((w) => ({
      label: widgetText(ctx, '{value} px', { value: w }), on: now === w, onSelect: () => setField('style.lineWidth', w),
    })), widgetText(ctx, 'Line width'));
  }
  function openStyles(): void {
    const field = fields.get('style.lineStyle');
    if (field === undefined) return;
    const now = valueAcross(live, field, ctx.chartTheme.lineColor);
    menuOf(style, LINE_STYLE_OPTIONS.map((o) => ({
      label: styleLabel(o.value), icon: LINE_STYLE_ICONS[o.value], on: now === o.value, onSelect: () => setField('style.lineStyle', o.value),
    })), widgetText(ctx, 'Line style'));
  }
  const styleLabel = (value: string): string => value === 'dashed' ? widgetText(ctx, 'Dashed') : value === 'dotted' ? widgetText(ctx, 'Dotted') : widgetText(ctx, 'Solid');
  function openMore(): void {
    const targets = ids.slice();
    const { hidden, readOnly: why } = drawingActionState(ctx, targets);
    const rows: Array<MenuRow | string> = [
      { label: widgetText(ctx, 'Properties...'), icon: 'settings', onSelect: () => { mountDrawingProperties(ctx, undefined, { ids: targets }); } },
      { label: widgetText(ctx, 'Duplicate'), icon: 'duplicate', key: commandChord(ctx.keymap, 'duplicate', 'Mod+D'), onSelect: () => { run('duplicate', targets); } },
      { label: hidden ? widgetText(ctx, 'Show') : widgetText(ctx, 'Hide'), icon: hidden ? 'eye-off' : 'eye', disabled: why !== null, sub: why ?? undefined,
        onSelect: () => { run('visible', targets); } },
      widgetText(ctx, 'Order'),
      { label: widgetText(ctx, 'Bring to front'), icon: 'front', onSelect: () => { run('front', targets); } },
      { label: widgetText(ctx, 'Send to back'), icon: 'back', onSelect: () => { run('back', targets); } },
      { label: widgetText(ctx, 'In front of the series'), icon: 'above-series', onSelect: () => { run('above', targets); } },
      { label: widgetText(ctx, 'Behind the series'), icon: 'behind-series', onSelect: () => { run('behind', targets); } },
    ];
    if (opts.templates) rows.push(...templateMenuRows(ctx, opts.templates, targets, more));
    menuOf(more, rows, widgetText(ctx, 'More drawing actions'));
  }

  // ── state ──────────────────────────────────────────────────────────────
  const hide = (): void => {
    if (bar.hidden) return;
    // Focus leaving with the bar goes back to the chart rather than to nothing.
    const had = bar.contains(doc.activeElement);
    bar.hidden = true;
    if (had) container()?.focus();
  };

  function paint(): void {
    const state = drawingActionState(ctx, ids);
    const why = state.readOnly;
    const theme = ctx.chartTheme.lineColor;
    const colorField = fields.get('style.color');
    color.el.hidden = colorField === undefined;
    if (colorField !== undefined) {
      const now = valueAcross(live, colorField, theme);
      color.el.classList.toggle('is-mixed', now === MIXED);
      if (now !== MIXED) color.write(now);
      // Two of the colours in use, split corner to corner: mixed, without a word.
      const [a, b] = [...new Set(live.map((d) => String(resolvedDrawingValues(d, { fields: [colorField] }, drawingToolOf(d.tool), theme)['style.color'])))];
      colorTrigger.style.backgroundImage = now === MIXED ? `linear-gradient(135deg, ${a} 0 50%, ${b ?? a} 50% 100%)` : '';
      colorTrigger.setAttribute('aria-label', now === MIXED
        ? widgetText(ctx, 'Color: {value}', { value: widgetText(ctx, 'mixed') })
        : widgetText(ctx, 'Color: {value}', { value: String(now ?? '') }));
      colorTrigger.disabled = why !== null;
      colorTrigger.title = why === null ? widgetText(ctx, 'Color') : `${widgetText(ctx, 'Color')} (${why})`;
    }
    const widthField = fields.get('style.lineWidth');
    width.hidden = widthField === undefined;
    if (widthField !== undefined) {
      const now = valueAcross(live, widthField, theme);
      const text = now === MIXED ? widgetText(ctx, 'Mixed') : widgetText(ctx, '{value} px', { value: Number(now ?? 1) });
      width.textContent = text;
      width.setAttribute('aria-label', widgetText(ctx, 'Line width: {value}', { value: now === MIXED ? widgetText(ctx, 'mixed') : text }));
      width.classList.toggle('is-mixed', now === MIXED);
      width.disabled = why !== null;
      width.title = why === null ? widgetText(ctx, 'Line width') : `${widgetText(ctx, 'Line width')} (${why})`;
    }
    const styleField = fields.get('style.lineStyle');
    style.hidden = styleField === undefined;
    if (styleField !== undefined) {
      const now = valueAcross(live, styleField, theme);
      const value = now === MIXED ? 'mixed' : typeof now === 'string' ? now : 'solid';
      styleGlyph.innerHTML = chromeIconSvg(LINE_STYLE_ICONS[value] ?? 'minus');
      style.classList.toggle('is-mixed', now === MIXED);
      const said = now === MIXED ? widgetText(ctx, 'mixed') : styleLabel(value);
      style.setAttribute('aria-label', widgetText(ctx, 'Line style: {style}', { style: said }));
      style.disabled = why !== null;
      style.title = why === null ? widgetText(ctx, 'Line style: {style}', { style: said }) : `${widgetText(ctx, 'Line style')} (${why})`;
    }
    lineSep.hidden = color.el.hidden && width.hidden && style.hidden;
    lock.replaceChildren(chromeGlyph(doc, state.locked ? 'lock' : 'unlock'));
    // One name; the pressed state says locked, and a partly locked selection is neither.
    lock.setAttribute('aria-label', widgetText(ctx, 'Lock'));
    lock.setAttribute('aria-pressed', state.locked ? 'true' : state.partlyLocked ? 'mixed' : 'false');
    lock.disabled = why !== null;
    lock.title = why === null ? widgetText(ctx, 'Lock') : `${widgetText(ctx, 'Lock')} (${why})`;
    const noDelete = state.noDelete;
    remove.disabled = noDelete !== null;
    // Why it is off, else the chord the user bound: none once Delete has no key.
    const note = noDelete ?? commandChord(ctx.keymap, 'delete', 'Delete');
    remove.title = note === undefined ? widgetText(ctx, 'Delete') : `${widgetText(ctx, 'Delete')} (${note})`;
    if (!controls().includes(current)) setRoving(controls()[0] ?? more);
    else setRoving(current);
  }

  function place(): void {
    const box = container();
    if (box === null || bar.hidden) return;
    const frame = boxIn(host, box);
    let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity;
    for (const target of ids) {
      for (const p of draw.screenPoints(target) ?? []) {
        if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) continue;
        left = Math.min(left, p.x); right = Math.max(right, p.x);
        top = Math.min(top, p.y); bottom = Math.max(bottom, p.y);
      }
    }
    const w = bar.offsetWidth;
    const h = bar.offsetHeight;
    const minX = frame.left + PAD;
    const maxX = Math.max(minX, frame.right - PAD - w);
    const minY = frame.top + PAD;
    const maxY = Math.max(minY, frame.bottom - PAD - h);
    let x: number;
    let y: number;
    if (!Number.isFinite(left)) {
      // Nothing of the selection on screen (a folded pane): the top of the chart, still reachable.
      x = frame.left + (frame.right - frame.left - w) / 2;
      y = minY;
    } else {
      // Centred on the part of the selection in view: an anchor scrolled off
      // one side would otherwise pull the bar to the edge.
      const span = frame.right - frame.left;
      const from = Math.max(0, Math.min(span, left));
      const to = Math.max(0, Math.min(span, right));
      x = frame.left + (from + to) / 2 - w / 2;
      const above = frame.top + top - GAP - h;
      const below = frame.top + bottom + GAP;
      y = above >= minY ? above : below <= maxY ? below : above;
    }
    bar.style.left = `${Math.round(Math.min(maxX, Math.max(minX, x)))}px`;
    bar.style.top = `${Math.round(Math.min(maxY, Math.max(minY, y)))}px`;
  }

  function refresh(): void {
    if (destroyed) return;
    ids = draw.selection().slice();
    live = ids.map((target) => draw.get(target)).filter((d): d is Drawing => d !== undefined);
    if (live.length === 0 || draw.activeTool() !== null || dragging) { hide(); return; }
    fields = new Map(commonSchema(live.map((d) => d.tool)).fields.map((f) => [f.path, f]));
    paint();
    bar.hidden = false;
    place();
  }
  const reposition = (): void => { if (!destroyed && !bar.hidden) place(); };

  const offs: Array<() => void> = [];
  for (const event of ['draw:select', 'drawing:select', 'draw:update', 'draw:remove', 'draw:add', 'draw:restore', 'drawing:change', 'draw:tool'] as const) {
    offs.push(chart.on(event, refresh));
  }
  // A tick that moves the autoscale, and a scale setter, move the drawing as surely as a pan.
  for (const event of ['pan', 'zoom', 'resize', 'paneResized', 'paneMoved', 'paneCollapsed', 'paneMaximized', 'paneAdded', 'paneRemoved', 'data:update', 'layout:change'] as const) {
    offs.push(chart.on(event, reposition));
  }
  // Dragging or wheeling a price axis rescales it with no chart event at all.
  // The chart's own listeners on the same element ran first, so the scale has
  // already moved when these read it.
  if (anchor !== null) {
    const pressed = (event: Event): void => { if ((event as PointerEvent).buttons !== 0) reposition(); };
    const pointerOpts: AddEventListenerOptions = { passive: true };
    anchor.addEventListener('pointermove', pressed, pointerOpts);
    for (const type of ['pointerup', 'wheel', 'dblclick']) anchor.addEventListener(type, reposition, pointerOpts);
    offs.push(() => {
      anchor.removeEventListener('pointermove', pressed, pointerOpts);
      for (const type of ['pointerup', 'wheel', 'dblclick']) anchor.removeEventListener(type, reposition, pointerOpts);
    });
  }
  // A drag moves the drawing under the bar; it comes back where the drawing lands.
  offs.push(chart.on('draw:preview', () => { if (!dragging) { dragging = true; hide(); } }));
  for (const event of ['draw:preview-clear', 'drag:end', 'drag:cancel'] as const) {
    offs.push(chart.on(event, () => { if (dragging) { dragging = false; refresh(); } }));
  }
  offs.push(ctx.bus.on('theme', refresh));
  if (ctx.history !== undefined) offs.push(ctx.history.subscribe(refresh));
  const Observer = (doc.defaultView as (Window & typeof globalThis) | null)?.ResizeObserver;
  let observer: ResizeObserver | null = null;
  if (Observer !== undefined && anchor !== null) {
    observer = new Observer(reposition);
    observer.observe(anchor);
  }
  refresh();

  return {
    el: bar,
    refresh,
    destroy: () => {
      if (destroyed) return;
      destroyed = true;
      for (const off of offs.splice(0)) off();
      for (const off of unbind.splice(0)) off();
      observer?.disconnect();
      color.destroy();
      bar.removeEventListener('pointerdown', stop);
      bar.removeEventListener('dblclick', stop);
      bar.remove();
    },
  };
}

/** Append beside the shared widget styles when mounting the toolbar yourself. */
export const DRAWING_TOOLBAR_CSS = `
.oac-widget .oac-drawbar { position: absolute; z-index: 25; display: flex; align-items: center; gap: 2px; padding: 3px;
  background: var(--oac-panel); border: 1px solid var(--oac-bd); border-radius: 9px; box-shadow: var(--oac-shadow); }
.oac-widget .oac-drawbar .oac-btn { height: 28px; }
.oac-widget .oac-drawbar .oac-sep { height: 18px; margin: 0 3px; }
.oac-widget .oac-drawbar__color { margin: 0 2px; }
.oac-widget .oac-drawbar__width { min-width: 44px; padding: 0 7px; font-size: 11.5px; font-variant-numeric: tabular-nums; color: var(--oac-tx); }
.oac-widget .oac-drawbar .is-mixed { color: var(--oac-mut); font-style: italic; }
.oac-widget .oac-drawbar .oac-btn[aria-pressed="mixed"] { border-color: var(--oac-on-bd); border-style: dashed; }
.oac-widget.is-mobile .oac-drawbar { display: none; }
/* The properties dialog edits the same selection in full; two surfaces for it would sit on each other. */
.oac-widget:has(.oac-layer > .oac-props) .oac-drawbar { visibility: hidden; }
`;

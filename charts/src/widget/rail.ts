/**
 * The drawing rail: the column of tool buttons down the left of the chart.
 *
 * Everything here routes through the controller's public API, and every glyph
 * comes from the draw tier's own registry: the sprite is injected once and
 * each button, flyout row and menu entry is a `<use>` into it, so the rail,
 * its flyouts and the armed cursor cannot drift apart.
 *
 * A group is one button standing for its last-used tool, with a chevron that
 * lists the rest. Favourites are pinned above the groups. The controls block
 * at the bottom carries the magnet mode, the stay toggle, lock, hide, delete,
 * undo and redo, each following the controller's state, and the button that
 * folds the rail away. Folded, the rail leaves a small tab at the chart's
 * bottom left that brings it back, and the chart takes the rail's width.
 * Preferences (pins, magnet, stay, each group's last pick, folded or not)
 * persist through the widget storage.
 */
import { widgetText } from './localization';
import type { Chart } from 'openalgo-charts';
import {
  hasDrawingTool, drawingShortcuts,
  iconSprite, iconUse, chromeIconSvg, toolCursor, DRAWING_TOOL_ICONS,
  type MagnetMode,
} from 'openalgo-charts/draw';
import { h, glyph, drawingToolOf, editableIds, historyPress, historyReady, TIP_DWELL_MS, type TipSpec, type WidgetContext } from './context';
import { commandChord } from './keymap';
import { chromeGlyph } from './form';
import { openMenu, type MenuRow } from './menu';
import { drawingActionState, runDrawingAction } from './drawing-actions';

export const MAGNET_MODES: readonly MagnetMode[] = ['off', 'weak', 'strong'];

export interface RailGroupItem { head?: string; tool?: string }
export interface RailGroup { id?: string; title?: string; items?: RailGroupItem[]; sep?: boolean }

/**
 * Rail groups. Only registered tools are shown, so a build that predates a
 * tool leaves a gap rather than a dead row. Names come from the descriptors,
 * not from here: the rail cannot spell a tool differently from the registry.
 */
export const RAIL_GROUPS: readonly RailGroup[] = [
  { id: 'lines', title: 'Lines', items: [
    { head: 'Lines' },
    { tool: 'trend-line' }, { tool: 'ray' }, { tool: 'extended-line' }, { tool: 'arrow' },
    { tool: 'info-line' }, { tool: 'trend-angle' },
    { head: 'Horizontal and vertical' },
    { tool: 'horizontal-line' }, { tool: 'horizontal-ray' }, { tool: 'vertical-line' }, { tool: 'cross-line' },
  ] },
  { id: 'channels', title: 'Channels', items: [
    { head: 'Channels' },
    { tool: 'parallel-channel' }, { tool: 'fib-channel' },
    { tool: 'disjoint-channel' }, { tool: 'flat-top-bottom' }, { tool: 'regression-channel' },
    { head: 'Pitchforks' },
    { tool: 'pitchfork' }, { tool: 'schiff-pitchfork' }, { tool: 'modified-schiff-pitchfork' }, { tool: 'inside-pitchfork' },
  ] },
  { id: 'fib', title: 'Fibonacci and Gann', items: [
    { head: 'Fibonacci' },
    { tool: 'fib-retracement' }, { tool: 'fib-extension' }, { tool: 'fib-time-zone' }, { tool: 'fib-fan' },
    { tool: 'fib-extension-two-point' }, { tool: 'fib-speed-resistance-fan' },
    { tool: 'trend-fib-time' }, { tool: 'fib-circles' }, { tool: 'fib-speed-resistance-arcs' },
    { tool: 'fib-wedge' }, { tool: 'fib-spiral' },
    { head: 'Gann' },
    { tool: 'gann-fan' }, { tool: 'gann-box' }, { tool: 'gann-square' },
  ] },
  { sep: true },
  { id: 'shapes', title: 'Shapes', items: [
    { head: 'Shapes' },
    { tool: 'rectangle' }, { tool: 'rotated-rectangle' }, { tool: 'ellipse' }, { tool: 'circle' }, { tool: 'triangle' },
    { head: 'Paths' },
    { tool: 'path' }, { tool: 'polyline' }, { tool: 'arc' }, { tool: 'curve' }, { tool: 'double-curve' },
  ] },
  { id: 'cycles', title: 'Cycles', items: [
    { head: 'Cycles' },
    { tool: 'cyclic-lines' }, { tool: 'time-cycles' }, { tool: 'sine-line' },
  ] },
  { id: 'patterns', title: 'Patterns', items: [
    { head: 'Patterns and waves' },
    { tool: 'xabcd-pattern' }, { tool: 'abcd-pattern' }, { tool: 'head-shoulders' },
    { tool: 'elliott-impulse' }, { tool: 'elliott-correction' },
    { head: 'Harmonic patterns' },
    { tool: 'gartley' }, { tool: 'bat' }, { tool: 'butterfly' }, { tool: 'crab' }, { tool: 'shark' }, { tool: 'cypher' },
  ] },
  { id: 'geometry', title: 'Geometric studies', items: [
    { head: 'Geometric studies' },
    { tool: 'sonic' }, { tool: 'supersonic' }, { tool: 'golden-sonic' }, { tool: 'golden-supersonic' },
    { tool: 'dedekind-tessellation' },
  ] },
  { id: 'marks', title: 'Arrows and marks', items: [
    { head: 'Arrows' },
    { tool: 'arrow-up' }, { tool: 'arrow-down' }, { tool: 'arrow-left' }, { tool: 'arrow-right' },
    { head: 'Marks' },
    { tool: 'flag-mark' }, { tool: 'icon-stamp' }, { tool: 'price-label' }, { tool: 'signpost' },
  ] },
  { sep: true },
  { id: 'forecast', title: 'Forecasting', items: [
    { head: 'Forecasting' },
    { tool: 'long-position' }, { tool: 'short-position' }, { tool: 'forecast' },
  ] },
  { id: 'analysis', title: 'Volume studies', items: [
    { head: 'Volume studies' },
    { tool: 'anchored-vwap' }, { tool: 'fixed-range-volume-profile' },
  ] },
  { id: 'measure', title: 'Measurers', items: [
    { head: 'Measurers' },
    { tool: 'price-range' }, { tool: 'date-range' }, { tool: 'measure' },
  ] },
  { sep: true },
  { id: 'text', title: 'Text and notes', items: [
    { head: 'Text and notes' },
    { tool: 'text' }, { tool: 'note' }, { tool: 'callout' }, { tool: 'balloon' }, { tool: 'comment' },
    { tool: 'price-note' }, { tool: 'table' },
    { head: 'Brushes' },
    { tool: 'brush' }, { tool: 'highlighter' },
  ] },
];

/** A tool's display name from the registry, or the id itself for one the registry lacks. */
export const toolName = (id: string | null): string =>
  (id === null ? null : drawingToolOf(id))?.name ?? String(id ?? 'Cursor');

export interface RailPrefs {
  favorites: string[];
  magnet: MagnetMode;
  stay: boolean;
  /** Group id to the tool its button stands for. */
  last: Record<string, string>;
  /** The rail is folded away, leaving its tab. Absent means shown. */
  collapsed?: boolean;
}

export interface RailOptions {
  /** Restrict the rail to these tool ids. Default: every registered tool the groups know. */
  tools?: readonly string[];
  /** Pins to start with when nothing is stored. */
  favorites?: readonly string[];
  /**
   * The element the armed tool's cursor goes on: the chart container. The
   * cursor rides a custom property the stylesheet reads, not the inline
   * cursor, which the engine owns for its own hover hints.
   */
  cursorTarget?: HTMLElement;
}

export interface RailHandle {
  readonly el: HTMLElement;
  /** Reflect the armed tool on the buttons. The controller's `draw:tool` event drives it; a host may call it too. */
  sync(tool: string | null): void;
  /** Re-read the controller for the controls block (selection, history). */
  refresh(): void;
  prefs(): RailPrefs;
  restorePrefs(prefs: unknown): void;
  magnetMode(): MagnetMode;
  setMagnetMode(mode: MagnetMode): void;
  /** off -> weak -> strong -> off. Returns the new mode. */
  cycleMagnet(): MagnetMode;
  stayMode(): boolean;
  setStayMode(on: boolean): void;
  favorites(): string[];
  isFavorite(id: string): boolean;
  toggleFavorite(id: string, on?: boolean): void;
  /** The double-click hold: one tool kept armed until something leaves it. */
  setDrawLock(on: boolean): void;
  drawLocked(): boolean;
  /**
   * Whether the rail is folded away behind its tab. Optional because a host
   * may hand `mountMobile` a handle of its own, written before the fold.
   */
  collapsed?(): boolean;
  /** Fold the rail away, leaving its tab, or bring it back. Optional, as `collapsed`. */
  setCollapsed?(on: boolean): void;
  /** Open a group's flyout beside its button. */
  openGroup(groupId: string, viaKeyboard?: boolean): void;
  closeFlyout(): void;
  flyoutOpen(): boolean;
  destroy(): void;
}

/** Storage key the preferences live under. */
export const RAIL_PREFS_KEY = 'rail';

const SPRITE_ID = 'oac-rail-sprite';

/** The icon sprite, once per document, on the body so it outlives any one widget. */
function ensureSprite(doc: Document): void {
  if (doc.getElementById(SPRITE_ID) !== null) return;
  const w = doc.createElement('div');
  w.id = SPRITE_ID;
  w.hidden = true;
  w.innerHTML = iconSprite();
  (doc.body ?? doc.documentElement).appendChild(w);
}

/**
 * A tool's glyph as a `<use>` into the sprite. A tool the tier has no glyph
 * for (a host-registered one) gets its initial instead of a throw, so one
 * custom tool cannot blank the rail.
 */
export function toolGlyph(doc: Document, id: string): HTMLElement {
  if (DRAWING_TOOL_ICONS[id] !== undefined) return glyph(doc, iconUse(id), 'tool');
  const span = h(doc, 'span', 'oac-glyph oac-glyph--text', { 'aria-hidden': 'true' });
  span.textContent = String(id).charAt(0).toUpperCase();
  return span;
}

/** Validate a stored preference object field by field, dropping what this build cannot honour. */
export function sanitizeRailPrefs(raw: unknown, groups: readonly RailGroup[], toolsOf: (g: RailGroup) => string[]): RailPrefs {
  const out: RailPrefs = { favorites: [], magnet: 'off', stay: false, last: {} };
  if (raw === null || typeof raw !== 'object') return out;
  const r = raw as Record<string, unknown>;
  if (Array.isArray(r.favorites)) {
    out.favorites = (r.favorites as unknown[]).filter((id, i, a): id is string =>
      typeof id === 'string' && hasDrawingTool(id) && a.indexOf(id) === i);
  }
  if (typeof r.magnet === 'string' && (MAGNET_MODES as readonly string[]).includes(r.magnet)) out.magnet = r.magnet as MagnetMode;
  out.stay = r.stay === true;
  if (r.collapsed === true) out.collapsed = true;
  if (r.last !== null && typeof r.last === 'object') {
    const last = r.last as Record<string, unknown>;
    for (const g of groups) {
      if (g.id !== undefined && typeof last[g.id] === 'string' && toolsOf(g).includes(last[g.id] as string)) out.last[g.id] = last[g.id] as string;
    }
  }
  return out;
}

interface RailKeyDeps {
  buttons(): HTMLElement[];
  setRoving(target: HTMLElement): void;
  /** Open a group's list from the keyboard; false when the button is not a group. */
  openGroup(groupId: string, anchor: HTMLElement): boolean;
  flyoutOpen(): boolean;
  closeFlyout(): void;
  /** Where Escape hands focus back: the chart. */
  chart: HTMLElement | undefined;
}

/**
 * The rail's keyboard. Arrow keys walk the rail, ArrowRight opens a group,
 * Escape hands focus back to the chart. Registered in the rail scope, so they
 * fire only while a rail button has focus and never shadow the editing keys
 * elsewhere.
 */
function railKeys(ctx: WidgetContext, host: HTMLElement, d: RailKeyDeps): { destroy(): void } {
  const doc = ctx.document;
  const current = (): HTMLElement | null => {
    const a = doc.activeElement as HTMLElement | null;
    return a !== null && host.contains(a) ? (a.closest('.oac-rail__btn') as HTMLElement | null) : null;
  };
  const go = (i: number): void => {
    const all = d.buttons();
    if (all.length === 0) return;
    const b = all[((i % all.length) + all.length) % all.length]!; // a non-empty list, index wrapped into it
    d.setRoving(b);
    b.focus();
  };
  const unbind: Array<() => void> = [];
  const bind = (combo: string, fn: () => boolean | void, label: string): void => {
    unbind.push(ctx.keymap.register(combo, fn, 'rail', { label, group: 'Tool rail' }));
  };
  bind('ArrowDown', () => { go(d.buttons().indexOf(current() as HTMLElement) + 1); }, 'Next tool');
  bind('ArrowUp', () => { go(d.buttons().indexOf(current() as HTMLElement) - 1); }, 'Previous tool');
  bind('Home', () => { go(0); }, 'First tool');
  bind('End', () => { go(d.buttons().length - 1); }, 'Last tool');
  bind('ArrowRight', () => {
    const cur = current();
    return cur !== null && cur.dataset.group !== undefined && cur.dataset.group !== '' && d.openGroup(cur.dataset.group, cur);
  }, 'Open the group');
  bind('Escape', () => {
    const hadFlyout = d.flyoutOpen();
    d.closeFlyout();
    ctx.tips.hide();
    const chartEl = d.chart;
    if (chartEl !== undefined && typeof chartEl.focus === 'function') chartEl.focus();
    else current()?.blur();
    // A click leaves focus on the button it armed, so with no flyout to close
    // the key is declined once focus has moved: the shell's Escape then
    // disarms the tool in the same press instead of asking for a second one.
    return hadFlyout;
  }, 'Back to the chart');
  const onFocusIn = (e: Event): void => {
    const t = e.target as HTMLElement | null;
    const b = t !== null && typeof t.closest === 'function' ? (t.closest('.oac-rail__btn') as HTMLElement | null) : null;
    if (b !== null) d.setRoving(b);
  };
  host.addEventListener('focusin', onFocusIn);
  return {
    destroy: () => {
      for (const u of unbind) u();
      host.removeEventListener('focusin', onFocusIn);
    },
  };
}

interface RailFoldStore {
  folded(): boolean;
  /** Record the choice; folding also closes whatever the rail has open. */
  store(on: boolean): void;
  /** Where focus goes when the rail comes back: the button that folds it. */
  unfoldTarget(): HTMLElement | undefined;
}

/**
 * The rail's fold: a class on the rail and a tab beside it in the stage, so
 * the tab stays when the rail is hidden. The tab stops the press: the chart's
 * pointer capture would otherwise eat it.
 */
function railFold(ctx: WidgetContext, host: HTMLElement, s: RailFoldStore): { apply(): void; set(on: boolean): void; destroy(): void } {
  const doc = ctx.document;
  const tab = h(doc, 'button', 'oac-rail-tab', { type: 'button' });
  tab.innerHTML = chromeIconSvg('chevrons-right');
  tab.hidden = true;
  ctx.tips.attach(tab, () => ({ title: widgetText(ctx, 'Show drawing tools'), side: 'right' }), TIP_DWELL_MS);
  tab.addEventListener('pointerdown', (e) => { e.stopPropagation(); });
  // A rail mounted with no parent yet has nowhere to put its tab; folding it
  // then only hides it, which is all such a host can show.
  host.parentNode?.insertBefore(tab, host.nextSibling);
  const apply = (): void => {
    const on = s.folded();
    host.classList.toggle('is-collapsed', on);
    tab.hidden = !on;
    ctx.tips.refreshLabel(tab);
  };
  const set = (on: boolean): void => {
    const next = on === true;
    if (s.folded() === next) return;
    // Focus follows the control that replaces the one pressed, so a keyboard
    // user is never left on a button that just disappeared.
    const hadFocus = next ? host.contains(doc.activeElement) : doc.activeElement === tab;
    if (next) ctx.tips.hide();
    s.store(next);
    apply();
    if (hadFocus) (next ? tab : s.unfoldTarget())?.focus();
  };
  tab.addEventListener('click', () => { set(false); });
  return {
    apply,
    set,
    destroy: () => {
      host.classList.remove('is-collapsed');
      tab.remove();
    },
  };
}

export function mountRail(ctx: WidgetContext, host: HTMLElement, opts: RailOptions = {}): RailHandle {
  const doc = ctx.document;
  const translatedTool = (id: string | null): string => widgetText(ctx, `schema.drawing.${id ?? 'cursor'}.name`, {}, toolName(id));
  const draw = ctx.draw;
  const chart: Chart = ctx.chart;
  ensureSprite(doc);

  const allowed = opts.tools === undefined ? null : new Set(opts.tools);
  const toolsOf = (g: RailGroup): string[] =>
    (g.items ?? []).filter((i) => i.tool !== undefined && hasDrawingTool(i.tool) && (allowed === null || allowed.has(i.tool)))
      .map((i) => i.tool as string);
  const groupById = (id: string): RailGroup | undefined => RAIL_GROUPS.find((g) => g.id === id);

  // ── preferences ──────────────────────────────────────────────────────
  let prefs = sanitizeRailPrefs(ctx.storage.get(RAIL_PREFS_KEY), RAIL_GROUPS, toolsOf);
  if (ctx.storage.get(RAIL_PREFS_KEY) === null && opts.favorites) {
    prefs.favorites = opts.favorites.filter((id, i, a) => hasDrawingTool(id) && a.indexOf(id) === i);
  }
  let latch = false;   // a double-click's hold on one tool
  const savePrefs = (): void => { ctx.storage.set(RAIL_PREFS_KEY, prefs); };
  const lastOf = (g: RailGroup): string | null => prefs.last[g.id ?? ''] ?? toolsOf(g)[0] ?? null;

  // Tips read the chord in force, so a tool the user moved shows where it
  // went. A keymap without the shell's commands (a host mounting the rail on
  // its own) falls back to the tool's declared chord, an unbound one to none.
  let chords: Record<string, string> | null = null;
  const chordFor = (command: string, fallback: string | undefined): string | undefined => commandChord(ctx.keymap, command, fallback);
  const chordOf = (id: string | null): string | undefined => {
    if (id === null) return undefined;
    if (chords === null) chords = drawingShortcuts();
    return chordFor(`tool:${id}`, chords[id]);
  };

  // ── controller plumbing ──────────────────────────────────────────────
  const selectionOf = (): string[] => draw.selection().slice();
  /** Lock, eye and trash read the selection by the rules every drawing surface keeps (drawing-actions.ts). */
  const stateOf = (ids: readonly string[]): ReturnType<typeof drawingActionState> => drawingActionState(ctx, ids);

  const armCursor = (tool: string | null): void => {
    const target = opts.cursorTarget;
    if (!target) return;
    if (tool !== null && DRAWING_TOOL_ICONS[tool] !== undefined) target.style.setProperty('--oac-tool-cursor', toolCursor(tool));
    else target.style.removeProperty('--oac-tool-cursor');
  };

  const applyMagnet = (): void => { draw.setOptions({ magnet: prefs.magnet }); };
  const applyStay = (): void => { draw.setOptions({ stayInDrawingMode: prefs.stay || latch }); };

  const setMagnetMode = (mode: MagnetMode): void => {
    if (!MAGNET_MODES.includes(mode)) throw new Error(`openalgo-charts widget: unknown magnet mode "${String(mode)}"`);
    prefs.magnet = mode;
    savePrefs();
    applyMagnet();
    refreshControls();
  };
  const cycleMagnet = (): MagnetMode => {
    const next = MAGNET_MODES[(MAGNET_MODES.indexOf(prefs.magnet) + 1) % MAGNET_MODES.length]!; // wrapped into the three modes
    setMagnetMode(next);
    // The magnet snaps to study values too (draw/snap.ts), not only to O/H/L/C.
    ctx.status(next === 'off' ? widgetText(ctx, 'Magnet off')
      : next === 'weak' ? widgetText(ctx, 'Magnet weak: snaps when a bar or study value is within a few pixels')
      : widgetText(ctx, 'Magnet strong: every anchor lands on the nearest bar or study value'));
    return next;
  };
  const setStayMode = (on: boolean): void => {
    prefs.stay = on === true;
    savePrefs();
    applyStay();
    refreshControls();
    ctx.status(prefs.stay ? widgetText(ctx, 'Tools stay active after each drawing') : widgetText(ctx, 'One drawing per pick'));
  };
  const setDrawLock = (on: boolean): void => {
    latch = on === true;
    applyStay();
    sync(draw.activeTool());
  };

  const arm = (tool: string | null): void => {
    draw.setTool(tool);
    // The event drives sync; a controller that emits nothing still leaves the rail truthful.
    sync(tool);
  };
  const hold = (tool: string): void => {
    setDrawLock(true);
    arm(tool);
    ctx.status(widgetText(ctx, '{name} stays active until Escape', { name: translatedTool(tool) }));
  };

  // ── building ─────────────────────────────────────────────────────────
  host.classList.add('oac-rail');
  host.setAttribute('role', 'toolbar');
  host.setAttribute('aria-orientation', 'vertical');
  host.setAttribute('aria-label', widgetText(ctx, 'Drawing tools'));

  interface BtnSpec {
    cls?: string;
    glyphEl: HTMLElement;
    tip: () => TipSpec | null;
    onClick: (e: MouseEvent) => void;
    onContext?: (e: MouseEvent) => void;
  }
  const makeBtn = (spec: BtnSpec): HTMLButtonElement => {
    const b = h(doc, 'button', 'oac-rail__btn' + (spec.cls ? ' ' + spec.cls : ''), { type: 'button' });
    b.tabIndex = -1;
    b.appendChild(spec.glyphEl);
    ctx.tips.attach(b, spec.tip, TIP_DWELL_MS);
    b.addEventListener('click', (e) => { if (!b.classList.contains('is-off')) spec.onClick(e as MouseEvent); });
    if (spec.onContext) {
      b.addEventListener('contextmenu', (e) => { e.preventDefault(); e.stopPropagation(); spec.onContext?.(e as MouseEvent); });
    }
    return b;
  };
  const setGlyph = (b: HTMLElement, next: HTMLElement): void => {
    const cur = b.querySelector('.oac-glyph');
    if (cur) cur.replaceWith(next); else b.insertBefore(next, b.firstChild);
  };
  const sep = (): HTMLElement => h(doc, 'div', 'oac-rail__sep', { role: 'separator' });

  const cursorButton = (): HTMLButtonElement => {
    const b = makeBtn({
      cls: 'oac-rail__tool',
      glyphEl: toolGlyph(doc, 'cursor'),
      tip: () => ({ title: widgetText(ctx, 'Cursor'), chord: 'Esc', side: 'right' }),
      onClick: () => { setDrawLock(false); arm(null); },
    });
    b.dataset.tools = '';
    return b;
  };

  const favoriteButton = (id: string): HTMLButtonElement => {
    const b = makeBtn({
      cls: 'oac-rail__tool oac-rail__fav',
      glyphEl: toolGlyph(doc, id),
      // Its name is not the group button's, which may show the same tool.
      tip: () => ({ title: widgetText(ctx, '{name} (pinned)', { name: translatedTool(id) }), chord: chordOf(id), sub: widgetText(ctx, 'Pinned. Right-click to unpin'), side: 'right' }),
      onClick: (e) => {
        if (e.detail >= 2 && !prefs.stay) { hold(id); return; }
        setDrawLock(false);
        arm(id);
      },
      onContext: () => openRailMenu(b, [{ label: widgetText(ctx, 'Unpin from rail'), icon: 'star', onSelect: () => toggleFavorite(id, false) }]),
    });
    b.dataset.tools = id;
    return b;
  };

  const groupButton = (g: RailGroup): HTMLButtonElement => {
    const tools = toolsOf(g);
    // Where the press went down, not where the click lands: a browser that
    // adjusts a touch onto the nearest target moves a tap on the face onto
    // the small chevron, which would open the list instead of the tool. A
    // touch opens the list by long press or by tapping the active tool again.
    let downOnChevron = false;
    const b = makeBtn({
      cls: 'oac-rail__tool oac-rail__group',
      glyphEl: toolGlyph(doc, lastOf(g) ?? tools[0]!), // the rail builds a group button only for a group with tools
      tip: () => ({
        title: translatedTool(lastOf(g)),
        chord: chordOf(lastOf(g)),
        sub: widgetText(ctx, prefs.stay ? '{group}: chevron for the rest' : '{group}: chevron for the rest. Double-click keeps it active', { group: g.title === undefined ? '' : widgetText(ctx, `schema.rail.${g.id}.title`, {}, g.title) }),
        side: 'right',
      }),
      onClick: (e) => {
        // A keyboard click (detail 0) never means the chevron, even after a
        // press that went down on it and was dragged away.
        const onChevron = downOnChevron && e.detail !== 0;
        downOnChevron = false;
        if (fly !== null && b.getAttribute('aria-expanded') === 'true') { closeFlyout(); return; }
        if (onChevron) { openGroupFlyout(g, b, false); return; }
        if (e.detail >= 2 && !prefs.stay) { const t = lastOf(g); if (t !== null) hold(t); return; }
        // A click on a tool that is already armed is a request for the list:
        // arming it again would do nothing the user could see.
        if (draw.activeTool() === lastOf(g)) { openGroupFlyout(g, b, false); return; }
        setDrawLock(false);
        arm(lastOf(g));
      },
      onContext: () => openGroupFlyout(g, b, false),
    });
    b.addEventListener('pointerdown', (e) => {
      const target = e.target as Element | null;
      downOnChevron = (e as PointerEvent).pointerType !== 'touch' && typeof target?.closest === 'function' && target.closest('.oac-rail__chev') !== null;
    });
    b.dataset.tools = tools.join(',');
    b.dataset.group = g.id ?? '';
    b.dataset.face = lastOf(g) ?? '';
    b.setAttribute('aria-haspopup', 'menu');
    b.setAttribute('aria-expanded', 'false');
    const chev = h(doc, 'span', 'oac-rail__chev', { 'aria-hidden': 'true' });
    chev.innerHTML = chromeIconSvg('chevron-right');
    b.appendChild(chev);
    return b;
  };

  // ── flyout ───────────────────────────────────────────────────────────
  let fly: { el: HTMLElement; close: () => void } | null = null;
  const closeFlyout = (): void => { fly?.close(); };

  const openGroupFlyout = (g: RailGroup, anchor: HTMLElement, viaKeyboard: boolean): void => {
    closeFlyout();
    ctx.tips.hide();
    const m = h(doc, 'div', 'oac-fly', { role: 'menu', 'aria-label': g.title === undefined ? widgetText(ctx, 'Tools') : widgetText(ctx, `schema.rail.${g.id}.title`, {}, g.title) });
    const armed = draw.activeTool();
    const rows: HTMLElement[] = [];
    for (const it of g.items ?? []) {
      if (it.head !== undefined) {
        const head = h(doc, 'div', 'oac-head');
        head.textContent = widgetText(ctx, `schema.rail.${g.id}.group.${it.head}`, {}, it.head);
        m.appendChild(head);
        continue;
      }
      const tool = it.tool;
      if (tool === undefined || !hasDrawingTool(tool) || (allowed !== null && !allowed.has(tool))) continue;
      const row = h(doc, 'div', 'oac-fly__row', { role: 'menuitemradio', 'aria-checked': String(armed === tool) });
      row.tabIndex = -1;
      row.dataset.tool = tool;
      row.appendChild(toolGlyph(doc, tool));
      const name = h(doc, 'span', 'oac-fly__name');
      name.textContent = translatedTool(tool);
      row.appendChild(name);
      const pinned = isFavorite(tool);
      // One name; the pressed state says pinned.
      const star = h(doc, 'button', 'oac-fly__star', {
        type: 'button', 'aria-pressed': String(pinned), 'aria-label': widgetText(ctx, 'Pin to rail'),
      });
      star.tabIndex = -1;
      star.innerHTML = chromeIconSvg(pinned ? 'star-filled' : 'star');
      row.appendChild(star);
      const chord = h(doc, 'kbd', 'oac-fly__chord');
      chord.textContent = chordOf(tool) ?? '';
      row.appendChild(chord);
      const togglePin = (): void => {
        const on = !isFavorite(tool);
        toggleFavorite(tool, on);
        star.setAttribute('aria-pressed', String(on));
        star.innerHTML = chromeIconSvg(on ? 'star-filled' : 'star');
      };
      star.addEventListener('click', (e) => { e.stopPropagation(); togglePin(); });
      row.addEventListener('click', (e) => {
        e.stopPropagation();
        pick(tool);
      });
      row.addEventListener('keydown', (e) => {
        const ke = e as KeyboardEvent;
        if (ke.key === 'Enter' || ke.key === ' ') {
          ke.preventDefault();
          ke.stopPropagation();
          if ((ke.target as HTMLElement).closest('.oac-fly__star') !== null) togglePin();
          else { pick(tool); anchor.focus(); }
        }
      });
      rows.push(row);
      m.appendChild(row);
    }
    const pick = (tool: string): void => {
      if (g.id !== undefined) { prefs.last[g.id] = tool; savePrefs(); }
      closeFlyout();
      setDrawLock(false);   // a pick from the list is one placement, like a single click
      arm(tool);
    };
    // Arrows walk the rows, ArrowRight reaches the row's star and ArrowLeft
    // comes back; Escape is the overlay stack's and returns focus to the button.
    m.addEventListener('keydown', (e) => {
      const ke = e as KeyboardEvent;
      const cur = (ke.target as HTMLElement).closest('.oac-fly__row') as HTMLElement | null;
      const at = cur === null ? -1 : rows.indexOf(cur);
      const go = (i: number): void => { rows[(i + rows.length) % rows.length]?.focus(); };
      switch (ke.key) {
        case 'ArrowDown': go(at + 1); break;
        case 'ArrowUp': go(at - 1); break;
        case 'Home': go(0); break;
        case 'End': go(rows.length - 1); break;
        case 'ArrowRight': (cur?.querySelector('.oac-fly__star') as HTMLElement | null)?.focus(); break;
        case 'ArrowLeft': cur?.focus(); break;
        default: return;
      }
      ke.preventDefault();
      ke.stopPropagation();
    });
    const first = rows.find((r) => r.getAttribute('aria-checked') === 'true') ?? rows[0] ?? null;
    const close = ctx.openOverlay(m, {
      anchor, placement: 'beside', edge: host,
      initialFocus: viaKeyboard ? first : m,
      onClose: () => { if (fly !== null && fly.el === m) fly = null; },
    });
    fly = { el: m, close };
  };

  // ── small context menu ───────────────────────────────────────────────
  // The chrome's own menu, opened beside the rail rather than under a button.
  const openRailMenu = (anchor: HTMLElement, rows: MenuRow[]): void => {
    ctx.tips.hide();
    openMenu(ctx, anchor, rows, { placement: 'beside', edge: host });
  };

  // ── controls block ───────────────────────────────────────────────────
  const ctl: Record<string, HTMLButtonElement> = {};
  const controlsBlock = (): HTMLElement => {
    const box = h(doc, 'div', 'oac-rail__ctl');
    ctl.magnet = makeBtn({
      cls: 'oac-rail__btn--chrome oac-rail__btn--magnet',
      glyphEl: chromeGlyph(doc, 'magnet'),
      tip: () => ({
        title: widgetText(ctx, 'Magnet: {mode}', { mode: widgetText(ctx, `schema.magnet.${prefs.magnet}`, {}, prefs.magnet) }),
        sub: prefs.magnet === 'off' ? widgetText(ctx, 'Click for weak: snaps when a bar or study value is within a few pixels')
          : prefs.magnet === 'weak' ? widgetText(ctx, 'Click for strong: every anchor lands on the nearest bar or study value')
          : widgetText(ctx, 'Click to switch the magnet off'),
        side: 'right',
      }),
      onClick: () => { cycleMagnet(); },
    });
    box.appendChild(ctl.magnet);
    ctl.stay = makeBtn({
      cls: 'oac-rail__btn--chrome',
      glyphEl: chromeGlyph(doc, 'link'),
      tip: () => ({
        title: widgetText(ctx, 'Keep tool active'),
        sub: prefs.stay ? widgetText(ctx, 'On: the tool stays active after each drawing') : widgetText(ctx, 'Off: one drawing per pick'),
        side: 'right',
      }),
      onClick: () => setStayMode(!prefs.stay),
    });
    box.appendChild(ctl.stay);
    box.appendChild(sep());
    // Lock and the eye keep one name each; the pressed state and the glyph say locked or hidden.
    ctl.lock = makeBtn({
      cls: 'oac-rail__btn--chrome',
      glyphEl: chromeGlyph(doc, 'unlock'),
      tip: () => {
        const sel = selectionOf();
        return { title: widgetText(ctx, 'Lock drawing'), sub: sel.length === 0 ? widgetText(ctx, 'Select a drawing first') : stateOf(sel).readOnly ?? undefined, side: 'right' };
      },
      onClick: () => {
        runDrawingAction(ctx, 'lock', selectionOf());
        refreshControls();
      },
    });
    box.appendChild(ctl.lock);
    ctl.eye = makeBtn({
      cls: 'oac-rail__btn--chrome',
      glyphEl: chromeGlyph(doc, 'eye'),
      tip: () => {
        const sel = selectionOf();
        const state = stateOf(sel);
        return { title: widgetText(ctx, 'Hide drawing'), side: 'right', sub: sel.length === 0 ? widgetText(ctx, 'Select a drawing first')
          : state.readOnly ?? (state.hidden ? undefined : widgetText(ctx, 'Stays selected, so the eye brings it back')) };
      },
      onClick: () => {
        runDrawingAction(ctx, 'visible', selectionOf());
        refreshControls();
      },
    });
    box.appendChild(ctl.eye);
    ctl.trash = makeBtn({
      cls: 'oac-rail__btn--chrome oac-rail__btn--danger',
      glyphEl: chromeGlyph(doc, 'trash'),
      tip: () => {
        const sel = selectionOf();
        const state = stateOf(sel);
        // The count is what the press deletes: read-only drawings stay, and a locked selection stays whole.
        const n = state.editable.length;
        const why = state.noDelete ?? undefined;
        return sel.length > 0
          ? { title: n > 1 ? widgetText(ctx, 'Delete {count} drawings', { count: n }) : widgetText(ctx, 'Delete drawing'), chord: chordFor('delete', 'Delete'), sub: why ?? widgetText(ctx, 'Right-click to remove all'), side: 'right' }
          : { title: widgetText(ctx, 'Delete drawing'), chord: chordFor('delete', 'Delete'), sub: widgetText(ctx, 'Select one first. Right-click to remove all'), side: 'right' };
      },
      onClick: () => {
        runDrawingAction(ctx, 'delete', selectionOf());
        refreshControls();
      },
      onContext: () => {
        // Each count is what the row would act on: an unselectable drawing
        // never joins a selection and a read-only one survives a clear.
        const all = draw.drawings();
        const picked = all.filter((d) => d.policy?.selectable !== false).length;
        const n = editableIds(draw, all.map((d) => d.id)).length;
        openRailMenu(ctl.trash!, [ // set by the makeBtn call this handler is part of
          { label: widgetText(ctx, 'Select all ({count})', { count: picked }), icon: 'cursor', disabled: picked === 0, onSelect: () => {
            draw.select(all.map((d) => d.id));
            refreshControls();
          } },
          { label: widgetText(ctx, 'Remove all drawings ({count})', { count: n }), icon: 'trash', danger: true, disabled: n === 0, onSelect: () => {
            draw.clear();   // one undo step, so it is recoverable
            refreshControls();
            ctx.status(n > 0 ? widgetText(ctx, n === 1 ? 'Removed {count} drawing' : 'Removed {count} drawings', { count: n }) : widgetText(ctx, 'No drawings to remove'));
          } },
        ]);
      },
    });
    box.appendChild(ctl.trash);
    box.appendChild(sep());
    ctl.undo = makeBtn({
      cls: 'oac-rail__btn--chrome',
      glyphEl: chromeGlyph(doc, 'undo'),
      tip: () => ({ title: widgetText(ctx, 'Undo'), chord: chordFor('undo', 'Mod+Z'), side: 'right' }),
      onClick: () => { historyPress(ctx, 'undo'); refreshControls(); },
    });
    box.appendChild(ctl.undo);
    ctl.redo = makeBtn({
      cls: 'oac-rail__btn--chrome',
      glyphEl: chromeGlyph(doc, 'redo'),
      // Ctrl+Y while it still redoes, else wherever the listed Redo went.
      tip: () => ({ title: widgetText(ctx, 'Redo'), chord: chordFor('redo-alt', 'Mod+Y') ?? chordFor('redo', undefined), side: 'right' }),
      onClick: () => { historyPress(ctx, 'redo'); refreshControls(); },
    });
    box.appendChild(ctl.redo);
    box.appendChild(sep());
    ctl.collapse = makeBtn({
      cls: 'oac-rail__btn--chrome oac-rail__collapse',
      glyphEl: chromeGlyph(doc, 'chevrons-left'),
      tip: () => ({ title: widgetText(ctx, 'Hide drawing tools'), sub: widgetText(ctx, 'The chart takes the space. The tab at its bottom left brings them back'), side: 'right' }),
      onClick: () => { setCollapsed(true); },
    });
    box.appendChild(ctl.collapse);
    return box;
  };

  const fold = railFold(ctx, host, {
    folded: () => prefs.collapsed === true,
    store: (on) => {
      if (on) { closeFlyout(); prefs.collapsed = true; } else delete prefs.collapsed;
      savePrefs();
    },
    unfoldTarget: () => ctl.collapse,
  });
  const setCollapsed = fold.set;

  interface BtnState { on?: boolean; off?: boolean; glyph?: string; pressed?: boolean }
  const setState = (b: HTMLButtonElement | undefined, s: BtnState): void => {
    if (b === undefined) return;
    b.classList.toggle('is-on', s.on === true);
    b.classList.toggle('is-off', s.off === true);
    b.setAttribute('aria-disabled', s.off === true ? 'true' : 'false');
    if (s.pressed !== undefined) b.setAttribute('aria-pressed', String(s.pressed));
    if (s.glyph !== undefined && b.dataset.glyph !== s.glyph) {
      b.dataset.glyph = s.glyph;
      setGlyph(b, chromeGlyph(doc, s.glyph));
    }
  };

  /** The controls follow the controller: cheap class flips, no rebuild. */
  const refreshControls = (): void => {
    if (ctl.magnet === undefined) return;
    setState(ctl.magnet, { on: prefs.magnet === 'strong', pressed: prefs.magnet !== 'off' });
    ctl.magnet.classList.toggle('is-weak', prefs.magnet === 'weak');
    ctl.magnet.dataset.mode = prefs.magnet;
    setState(ctl.stay, { on: prefs.stay, pressed: prefs.stay });
    const state = stateOf(selectionOf());
    // A read-only selection has nothing these three could change.
    const none = state.editable.length === 0;
    setState(ctl.lock, { off: none, on: state.locked, pressed: state.locked, glyph: state.locked ? 'lock' : 'unlock' });
    setState(ctl.eye, { off: none, on: state.hidden, pressed: state.hidden, glyph: state.hidden ? 'eye-off' : 'eye' });
    setState(ctl.trash, { off: state.noDelete !== null || none });
    setState(ctl.undo, { off: !historyReady(ctx, 'undo') });
    setState(ctl.redo, { off: !historyReady(ctx, 'redo') });
    // The accessible name follows the tip now, not what it said when it was
    // built or last hovered (the trash counts what it deletes).
    for (const b of Object.values(ctl)) ctx.tips.refreshLabel(b);
  };

  // ── favourites ───────────────────────────────────────────────────────
  let favWrap: HTMLElement | null = null;
  const favorites = (): string[] => prefs.favorites.slice();
  const isFavorite = (id: string): boolean => prefs.favorites.includes(id);
  const renderFavorites = (): void => {
    if (favWrap === null) return;
    favWrap.textContent = '';
    const favs = prefs.favorites.filter((id) => hasDrawingTool(id));
    if (favs.length === 0) return;
    favWrap.appendChild(sep());
    for (const id of favs) favWrap.appendChild(favoriteButton(id));
  };
  const toggleFavorite = (id: string, on: boolean = !isFavorite(id)): void => {
    if (!hasDrawingTool(id)) return;
    const has = isFavorite(id);
    if (on && !has) prefs.favorites.push(id);
    if (!on && has) prefs.favorites.splice(prefs.favorites.indexOf(id), 1);
    savePrefs();
    renderFavorites();
    sync(draw.activeTool());
  };

  // ── the rail itself ──────────────────────────────────────────────────
  const buttons = (): HTMLElement[] => Array.from(host.querySelectorAll('.oac-rail__btn')) as HTMLElement[];
  /** One tab stop for the whole rail: the arrow keys do the rest. */
  const setRoving = (target: HTMLElement): void => {
    for (const b of buttons()) b.tabIndex = b === target ? 0 : -1;
  };

  const build = (): void => {
    host.textContent = '';
    host.appendChild(cursorButton());
    favWrap = h(doc, 'div', 'oac-rail__favs');
    host.appendChild(favWrap);
    renderFavorites();
    host.appendChild(sep());
    for (const g of RAIL_GROUPS) {
      if (g.sep) { host.appendChild(sep()); continue; }
      if (toolsOf(g).length > 0) host.appendChild(groupButton(g));
    }
    host.appendChild(controlsBlock());
    sync(draw.activeTool());
  };

  const sync = (toolIn: string | null): void => {
    const tool = toolIn ?? null;
    let armed: HTMLElement | null = null;
    for (const b of Array.from(host.querySelectorAll('.oac-rail__tool')) as HTMLElement[]) {
      const tools = (b.dataset.tools ?? '').split(',').filter(Boolean);
      const on = tool === null ? tools.length === 0 : tools.includes(tool);
      b.classList.toggle('is-on', on);
      b.classList.toggle('is-held', on && latch && tools.length > 0);
      b.setAttribute('aria-pressed', String(on));
      if (on && armed === null) armed = b;
      // A group stands for whichever of its tools was armed last, however it
      // was armed: a chord or a restored layout counts as a pick.
      if (on && b.dataset.group && tools.length > 0 && tool !== null) {
        if (prefs.last[b.dataset.group] !== tool) { prefs.last[b.dataset.group] = tool; savePrefs(); }
        if (b.dataset.face !== tool) {
          b.dataset.face = tool;
          setGlyph(b, toolGlyph(doc, tool));
        }
      }
      ctx.tips.refreshLabel(b);
    }
    const active = doc.activeElement;
    if (armed !== null && !(active !== null && host.contains(active))) setRoving(armed);
    armCursor(tool);
    refreshControls();
  };

  const keys = railKeys(ctx, host, {
    buttons, setRoving,
    openGroup: (groupId, anchor) => {
      const g = groupById(groupId);
      if (g === undefined) return false;
      openGroupFlyout(g, anchor, true);
      return true;
    },
    flyoutOpen: () => fly !== null,
    closeFlyout,
    chart: opts.cursorTarget,
  });

  // ── follow the controller ────────────────────────────────────────────
  const offs: Array<() => void> = [];
  offs.push(chart.on('draw:tool', (p) => { sync((p as { tool: string | null }).tool); }));
  for (const ev of ['draw:select', 'drawing:select', 'drawing:change', 'draw:add', 'draw:remove', 'draw:update', 'draw:paste', 'draw:cut'] as const) {
    offs.push(chart.on(ev, refreshControls));
  }
  // A study, a pane or a setting is a step too, and none of them is a drawing event.
  if (ctx.history !== undefined) offs.push(ctx.history.subscribe(refreshControls));

  applyMagnet();
  applyStay();
  build();
  fold.apply();

  return {
    el: host,
    sync,
    refresh: refreshControls,
    prefs: () => ({
      favorites: prefs.favorites.slice(), magnet: prefs.magnet, stay: prefs.stay, last: { ...prefs.last },
      ...(prefs.collapsed === true ? { collapsed: true } : {}),
    }),
    restorePrefs: (raw) => {
      prefs = sanitizeRailPrefs(raw, RAIL_GROUPS, toolsOf);
      savePrefs();
      applyMagnet();
      applyStay();
      build();
      fold.apply();
    },
    magnetMode: () => prefs.magnet,
    setMagnetMode,
    cycleMagnet,
    stayMode: () => prefs.stay,
    setStayMode,
    favorites,
    isFavorite,
    toggleFavorite,
    setDrawLock,
    drawLocked: () => latch,
    collapsed: () => prefs.collapsed === true,
    setCollapsed,
    openGroup: (groupId, viaKeyboard = false) => {
      const g = groupById(groupId);
      const b = host.querySelector(`.oac-rail__group[data-group="${groupId}"]`) as HTMLElement | null;
      if (g !== undefined && b !== null) openGroupFlyout(g, b, viaKeyboard);
    },
    closeFlyout,
    flyoutOpen: () => fly !== null,
    destroy: () => {
      closeFlyout();
      for (const off of offs) off();
      keys.destroy();
      armCursor(null);
      fold.destroy();
      host.textContent = '';
    },
  };
}

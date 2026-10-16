/**
 * The right-click menu, built from what the chart says was under the pointer.
 *
 * The chart's `contextmenu` event carries the price, the pane and a classified
 * target, which is the part a canvas cannot tell a host by itself. The menu
 * reads that target and offers only what applies: order entry where a host
 * has wired it and there is a price to trade at, the drawing actions on a
 * drawing, an indicator's settings on an indicator, the axis switches on a
 * price scale. A row with nothing to act on is not drawn; a row whose action
 * exists but has no data right now (pin the price per bar on an unmeasured
 * scale) is drawn disabled with a word on why.
 *
 * The axis switches read `priceAxisState` and write back through the matching
 * `priceAxis*` calls, so the menu can never claim a state the axis is not in,
 * and the same rows serve the price ladder, a left-hand scale and an indicator
 * pane's.
 *
 * The pane rows move the pane under the pointer up or down a slot, the price
 * pane included, which is how a trader puts the price below the studies; a
 * study pane also folds to its header strip. The price pane is found by
 * `primaryPaneIndex`, never assumed to be the top one.
 */
import { widgetText } from '../localization';
import { checkTradingCapability, getIndicator, isReplaying, PRICE_SCALE_MODES } from 'openalgo-charts';
import type { Chart, ContextMenuEvent, ContextMenuTarget, PriceScaleId, PriceScaleMode, TradingCapabilityRequest, TradingCapabilitySource } from 'openalgo-charts';
import { drawingSettingsSchema } from 'openalgo-charts/draw';
import type { Drawing } from 'openalgo-charts/draw';
import { boxIn, historyStep, type WidgetContext } from '../context';
import { drawingActionState, runDrawingAction } from '../drawing-actions';
import { ariaKeys, commandChord } from '../keymap';
import { chromeGlyph, el, openPanel, placePanel, stopOwnKeys, type PanelHandle } from '../form';
import { mountDrawingProperties } from './drawing-properties';
import { mountIndicatorPicker } from './indicator-picker';
import { mountIndicatorSettings } from './indicator-settings';
import { mountLevelEditor } from './level-editor';
import { mountSettingsDialog } from './settings';
import { chartContainer, isTextContent, mountTextEditor } from './text-editor';
import { mountAlertEditor, mountAlertsPanel } from './alerts';

/** What the menu asks a host to do when an order row is picked. */
export interface OrderRequest {
  side: 'BUY' | 'SELL';
  type: 'MARKET' | 'LIMIT' | 'SL';
  /**
   * The price under the pointer, not snapped to the instrument's tick or
   * tick schedule, which the widget does not know; round it (`validatePrice`
   * does) before sending. Null for a market order raised off the plot.
   */
  price: number | null;
  paneIndex: number;
}

export interface MenuItem {
  kind?: 'item';
  label: string;
  /** Chrome icon id, or inline SVG markup starting with `<svg`. */
  icon?: string;
  /** Chord hint, shown at the right. */
  chord?: string | undefined;
  /** A switch (tick) or one option of a choice (dot). */
  mark?: 'check' | 'radio';
  on?: boolean;
  disabled?: boolean;
  /** Why a disabled row is disabled; an empty greyed row reads as a bug. */
  note?: string | undefined;
  danger?: boolean;
  /** Keep the menu up after running (a switch the user may flip twice). */
  keepOpen?: boolean;
  /** Stable id, for tests and for a host that wants to find a row. */
  id?: string;
  run?(): void;
}

export type MenuEntry = MenuItem | { kind: 'separator' } | { kind: 'header'; label: string };

export interface ContextMenuHooks {
  /** Order entry. Without it no trade rows are drawn: the engine places no orders itself. */
  onOrder?(order: OrderRequest): void;
  /** Omitted capabilities preserve the host's existing supported order routes. */
  tradingCapabilities?: TradingCapabilitySource | undefined;
  /** Required when the capability declaration limits live or analyzer mode. */
  tradingMode?: TradingCapabilityRequest['mode'];
  /** Host replay selection or workspace transitions that also prevent order entry. */
  tradingLocked?(): boolean;
  /** Extra rows a host appends, built per event. */
  items?(e: ContextMenuEvent): MenuEntry[];
}

export interface ContextMenuOptions {
  /** The chart's event. Without one the menu is the chart-level menu at the anchor. */
  event?: ContextMenuEvent;
  hooks?: ContextMenuHooks;
}

const SEP: MenuEntry = { kind: 'separator' };
const header = (label: string): MenuEntry => ({ kind: 'header', label });

/** Our words for the four scale modes, in the engine's order. */
const SCALE_MODE_LABELS: Readonly<Record<PriceScaleMode, string>> = {
  linear: 'Linear',
  logarithmic: 'Logarithmic',
  percentage: 'Percent',
  'indexed-to-100': 'Indexed to 100',
};

/** The drawing id behind a `drawing` target: `draw:<id>` for the body, `draw:<id>#<n>` for an anchor. */
export function drawingIdOf(target: ContextMenuTarget): string | null {
  if (target.kind !== 'drawing' || target.id === null || !target.id.startsWith('draw:')) return null;
  const rest = target.id.slice('draw:'.length);
  const hash = rest.indexOf('#');
  return hash < 0 ? rest : rest.slice(0, hash);
}

/** A price the way the pane's own axis prints it. */
function priceText(chart: Chart, paneIndex: number, price: number): string {
  const pane = chart.panes()[paneIndex];
  return pane === undefined ? String(price) : pane.readoutScale().format(price);
}

/** The rows for a drawing under the pointer, acting on the whole selection it belongs to. */
function drawingEntries(ctx: WidgetContext, primary: Drawing, ids: readonly string[]): MenuEntry[] {
  const { draw } = ctx;
  const schema = drawingSettingsSchema(primary.tool);
  const out: MenuEntry[] = [];
  // The rows read the whole selection by the rules every drawing surface
  // keeps (drawing-actions.ts), whichever drawing the pointer was on. A
  // selection between studies is on neither side: neither radio is on.
  const state = drawingActionState(ctx, ids);
  const act = (action: Parameters<typeof runDrawingAction>[1]) => (): void => { runDrawingAction(ctx, action, ids); };
  const many = ids.length > 1;
  // A selection with nothing the user may edit keeps its edit rows, greyed
  // with the reason; the controller would refuse each one anyway. Cut and
  // delete count only what they take.
  const mine = state.editable.length;
  const fixed = mine === 0;
  const why = state.readOnly ?? undefined;
  const noDelete = state.noDelete ?? undefined;
  out.push({ id: 'draw-props', label: many ? widgetText(ctx, 'Properties of the selection...') : widgetText(ctx, 'Properties...'), icon: 'settings',
    run: () => { mountDrawingProperties(ctx, undefined, { ids }); } });
  if (!many && isTextContent(primary)) {
    out.push({ id: 'draw-text', label: widgetText(ctx, 'Edit text'), icon: 'text', disabled: fixed, note: why, run: () => { mountTextEditor(ctx, undefined, { id: primary.id }); } });
  }
  if (schema.fields.some((f) => f.kind === 'levels')) {
    out.push({ id: 'draw-levels', label: widgetText(ctx, 'Edit levels...'), disabled: fixed, note: why, run: () => { mountLevelEditor(ctx, undefined, { ids }); } });
  }
  out.push(SEP);
  out.push({ id: 'draw-copy', label: many ? widgetText(ctx, 'Copy {count} drawings', { count: ids.length }) : widgetText(ctx, 'Copy drawing'), icon: 'copy', chord: commandChord(ctx.keymap, 'copy', 'Mod+C'), run: () => { void draw.copy(ids); } });
  out.push({ id: 'draw-cut', label: mine > 1 ? widgetText(ctx, 'Cut {count} drawings', { count: mine }) : widgetText(ctx, 'Cut drawing'), chord: commandChord(ctx.keymap, 'cut', 'Mod+X'), disabled: noDelete !== undefined, note: noDelete,
    run: () => { void draw.cut(ids); } });
  out.push({ id: 'draw-duplicate', label: widgetText(ctx, 'Duplicate'), icon: 'duplicate', chord: commandChord(ctx.keymap, 'duplicate', 'Mod+D'), run: act('duplicate') });
  out.push(SEP);
  // Checkbox rows keep their names; the check says locked or hidden.
  out.push({ id: 'draw-lock', label: widgetText(ctx, 'Lock'), icon: state.locked ? 'lock' : 'unlock', mark: 'check', on: state.locked, disabled: fixed, note: why, run: act('lock') });
  out.push({ id: 'draw-hide', label: widgetText(ctx, 'Hide'), icon: state.hidden ? 'eye-off' : 'eye', mark: 'check', on: state.hidden, disabled: fixed, note: why, run: act('visible') });
  out.push(SEP);
  out.push(header(widgetText(ctx, 'Order')));
  out.push({ id: 'draw-front', label: widgetText(ctx, 'Bring to front'), icon: 'front', run: act('front') });
  out.push({ id: 'draw-back', label: widgetText(ctx, 'Send to back'), icon: 'back', run: act('back') });
  out.push({ id: 'draw-above', label: widgetText(ctx, 'In front of the series'), icon: 'above-series', mark: 'radio', on: state.side === 'above', run: act('above') });
  out.push({ id: 'draw-behind', label: widgetText(ctx, 'Behind the series'), icon: 'behind-series', mark: 'radio', on: state.side === 'behind', run: act('behind') });
  out.push(SEP);
  out.push({ id: 'draw-delete', label: mine > 1 ? widgetText(ctx, 'Delete {count} drawings', { count: mine }) : widgetText(ctx, 'Delete'), icon: 'trash', chord: commandChord(ctx.keymap, 'delete', 'Delete'), danger: true,
    disabled: noDelete !== undefined, note: noDelete, run: act('delete') });
  return out;
}

/** Axis settings and placement stay attached to the target scale's identity. */
function axisEntries(ctx: WidgetContext, paneIndex: number, scaleId: PriceScaleId): MenuEntry[] {
  const { chart } = ctx;
  const state = (): ReturnType<Chart['priceAxisState']> => chart.priceAxisState(paneIndex, scaleId);
  const s = state();
  if (s === null) return [];
  const out: MenuEntry[] = [];
  out.push({ id: 'axis-autofit', label: widgetText(ctx, 'Auto-fit to the data'), mark: 'check', on: s.autoFit, keepOpen: true,
    run: () => { const now = state(); if (now !== null) chart.setPriceAxisAutoFit(paneIndex, scaleId, !now.autoFit); } });
  const primaryScale = (): boolean => {
    const primary = chart.primarySeries?.();
    return primary != null && primary.priceScale() === chart.panes()[paneIndex]?.scaleFor(scaleId);
  };
  if (primaryScale()) out.push({ id: 'axis-price-only', label: widgetText(ctx, 'Fit primary prices only'),
    mark: 'check', on: chart.priceOnlyAutoScale(), keepOpen: true,
    run: () => { if (primaryScale()) chart.setPriceOnlyAutoScale(!chart.priceOnlyAutoScale()); } });
  out.push({ id: 'axis-invert', label: widgetText(ctx, 'Invert'), mark: 'check', on: s.inverted, keepOpen: true,
    run: () => { const now = state(); if (now !== null) chart.setPriceAxisOptions(paneIndex, scaleId, { inverted: !now.inverted }); } });
  // Holding the price-per-bar ratio while the time axis zooms needs a measured
  // scale. Nothing has been measured on an empty pane, so the row stays,
  // greyed, saying why.
  out.push({ id: 'axis-lock', label: widgetText(ctx, 'Pin price per bar'), mark: 'check', on: s.lockRatio, keepOpen: true,
    disabled: !s.scaled, note: s.scaled ? undefined : widgetText(ctx, 'nothing measured'),
    run: () => {
      const now = state();
      if (now === null) return;
      if (!chart.setPriceAxisLockRatio(paneIndex, scaleId, !now.lockRatio)) ctx.toast(widgetText(ctx, 'Nothing measured on this scale yet'), 'info');
    } });
  out.push(SEP);
  out.push(header(widgetText(ctx, 'Scale')));
  for (const mode of PRICE_SCALE_MODES) {
    out.push({ id: `axis-mode-${mode}`, label: widgetText(ctx, `schema.scaleMode.${mode}`, {}, SCALE_MODE_LABELS[mode]), mark: 'radio', on: s.mode === mode, keepOpen: true,
      run: () => { chart.setPriceAxisOptions(paneIndex, scaleId, { mode }); } });
  }
  const placement = chart.priceAxisPlacement(paneIndex, scaleId);
  const columns = (side: 'left' | 'right'): ReturnType<Chart['priceAxisLayout']> =>
    chart.priceAxisLayout(paneIndex).filter(column => column.side === side).sort((a, b) => a.order - b.order);
  if (placement !== null && placement.side !== 'hidden') {
    out.push(SEP);
    out.push({ id: 'axis-move', label: placement.side === 'right' ? widgetText(ctx, 'Move the scale to the left') : widgetText(ctx, 'Move the scale to the right'),
      disabled: !s.active, note: s.active ? undefined : widgetText(ctx, 'nothing on this side'),
      run: () => {
        const now = chart.priceAxisPlacement(paneIndex, scaleId);
        if (!state()?.active || now === null || now.side === 'hidden') return;
        if (!chart.setPriceAxisPlacement(paneIndex, scaleId, now.side === 'right' ? 'left' : 'right')) {
          ctx.toast(widgetText(ctx, 'The scale could not be moved'), 'info');
        }
      } });
    const peers = columns(placement.side), index = peers.findIndex(column => column.scaleId === scaleId);
    if (index >= 0 && peers.length > 1) for (const delta of [-1, 1] as const) {
      out.push({ id: delta < 0 ? 'axis-closer' : 'axis-further',
        label: delta < 0 ? widgetText(ctx, 'Move the scale closer to the plot') : widgetText(ctx, 'Move the scale further from the plot'),
        disabled: peers[index + delta] === undefined, keepOpen: true,
        run: () => {
          const now = chart.priceAxisPlacement(paneIndex, scaleId);
          if (!state()?.active || now === null || now.side === 'hidden') return;
          const current = columns(now.side), at = current.findIndex(column => column.scaleId === scaleId);
          const neighbor = at < 0 ? undefined : current[at + delta];
          if (neighbor && !chart.setPriceAxisPlacement(paneIndex, scaleId, now.side, neighbor.order)) {
            ctx.toast(widgetText(ctx, 'The scale could not be moved'), 'info');
          }
        } });
    }
  }
  out.push(SEP);
  out.push({ id: 'axis-settings', label: widgetText(ctx, 'Axis settings...'), icon: 'settings', run: () => { mountSettingsDialog(ctx, undefined, { tab: 'axes' }); } });
  return out;
}

/**
 * Every row the menu shows for `e`, in order. Pure apart from the closures:
 * nothing is rendered, so a test (or a host building its own menu) can read
 * the list.
 */
export function contextMenuEntries(ctx: WidgetContext, e: ContextMenuEvent, hooks: ContextMenuHooks = {}): MenuEntry[] {
  const { chart, draw } = ctx;
  const target = e.target;
  const out: MenuEntry[] = [];
  const sep = (): void => { if (out.length > 0 && out[out.length - 1]!.kind !== 'separator') out.push(SEP); }; // length checked first

  if (target.kind === 'price-scale') {
    out.push(...axisEntries(ctx, e.paneIndex, target.scaleId ?? target.side ?? 'right'));
    return out;
  }
  // The price pane can sit below the studies, so it is found, never assumed.
  const pricePane = chart.primaryPaneIndex();

  // Order entry: only through a host hook, and only at a price when there is
  // one. Off the plot the order rows would be offering to trade at nothing,
  // and off the price pane at a study's reading: an RSI of 58 is not a limit
  // price, so a study pane offers the market rows alone.
  const onOrder = hooks.onOrder;
  if (onOrder !== undefined && target.kind !== 'time-scale') {
    const price = e.paneIndex === pricePane ? e.price : null;
    const source = { ...ctx.symbol(), interval: ctx.interval() };
    const capability = (type: OrderRequest['type']): ReturnType<typeof checkTradingCapability> =>
      checkTradingCapability(hooks.tradingCapabilities, { operation: 'place', type, mode: hooks.tradingMode, ...ctx.symbol() });
    const locked = (): string | undefined => {
      if (isReplaying(chart)) return widgetText(ctx, 'Order entry is locked during replay');
      try {
        if (hooks.tradingLocked?.()) return widgetText(ctx, 'Order entry is locked by the host');
      } catch { return widgetText(ctx, 'Order entry is unavailable'); }
      return undefined;
    };
    const lockReason = locked();
    const order = (side: OrderRequest['side'], type: OrderRequest['type']): MenuItem => ({
      id: `order-${side.toLowerCase()}-${type.toLowerCase()}`,
      icon: side === 'BUY' ? 'buy' : 'sell',
      label: type === 'MARKET'
        ? widgetText(ctx, side === 'BUY' ? 'Buy market' : 'Sell market')
        : widgetText(ctx, side === 'BUY' ? (type === 'LIMIT' ? 'Buy limit at {price}' : 'Buy stop at {price}') : (type === 'LIMIT' ? 'Sell limit at {price}' : 'Sell stop at {price}'), { price: priceText(chart, e.paneIndex, price as number) }),
      disabled: lockReason !== undefined,
      note: lockReason,
      run: () => {
        if (chart.isDestroyed) return;
        const current = ctx.symbol();
        if (current.symbol !== source.symbol || current.exchange !== source.exchange || ctx.interval() !== source.interval) {
          ctx.status(widgetText(ctx, 'The chart changed; reopen the menu before placing an order'), 'error');
          return;
        }
        const reason = locked();
        if (reason !== undefined) { ctx.status(reason, 'error'); return; }
        const supported = capability(type);
        if (!supported.supported) {
          ctx.status(widgetText(ctx, 'Order entry is unavailable: {reason}', { reason: supported.reason }), 'error');
          return;
        }
        onOrder({ side, type, price: type === 'MARKET' ? null : price, paneIndex: e.paneIndex });
      },
    });
    const candidates = (price === null ? ['MARKET'] as const : ['MARKET', 'LIMIT', 'SL'] as const)
      .map(type => ({ type, result: capability(type) }));
    const supported = candidates.filter(candidate => candidate.result.supported);
    if (supported.length > 0) {
      out.push(header(widgetText(ctx, 'Trade')));
      for (const { type } of supported) out.push(order('BUY', type), order('SELL', type));
    } else {
      const failure = candidates[0]!.result; // both type lists start with MARKET
      out.push({ id: 'trading-unavailable', label: widgetText(ctx, 'Order entry is unavailable'), disabled: true,
        note: failure.supported ? undefined : failure.reason });
    }
  }

  const hitId = drawingIdOf(target);
  const hit = hitId === null ? undefined : draw.get(hitId);
  if (ctx.alerts && target.kind !== 'time-scale') {
    sep();
    if (hit) {
      const info = draw.alertInfo(hit.id);
      out.push({ id: 'alert-drawing', label: widgetText(ctx, 'Create drawing alert...'), icon: 'bell', disabled: !info.available, note: info.reason,
        run: () => { mountAlertEditor(ctx, undefined, { source: { kind: 'drawing', drawingId: hit.id } }); } });
    } else if (target.kind === 'indicator' && target.instanceId) {
      const instance = chart.indicators().find(item => item.id === target.instanceId);
      const plot = instance && getIndicator(instance.indicatorId).plots.find(item =>
        (item.overlay ? pricePane : instance.paneIndex) === e.paneIndex && (target.plotKey === undefined || item.key === target.plotKey));
      if (instance && plot) out.push({ id: 'alert-indicator', label: widgetText(ctx, 'Create study alert...'), icon: 'bell', run: () => {
        const values = instance.values()[plot.key];
        const value = values?.[e.index ?? chart.primaryBars().length - 1];
        mountAlertEditor(ctx, undefined, { source: { kind: 'indicator', instanceId: instance.id, plotKey: plot.key, value: value ?? NaN } });
      } });
    } else if (e.paneIndex === pricePane && e.price !== null && Number.isFinite(e.price)) {
      out.push({ id: 'alert-create', label: widgetText(ctx, 'Create alert at {price}...', { price: priceText(chart, pricePane, e.price) }), icon: 'bell',
        run: () => { mountAlertEditor(ctx, undefined, { source: { kind: 'price', price: e.price! } }); } });
    }
    out.push({ id: 'chart-alerts', label: widgetText(ctx, 'Alerts...'), run: () => { mountAlertsPanel(ctx); } });
  }
  if (hit !== undefined) {
    // A right-click picks the drawing the way a click does, so the actions
    // read on the thing under the pointer and not on a stale selection.
    if (!draw.selection().includes(hit.id)) draw.select(hit.id);
    const ids = draw.selection().includes(hit.id) ? draw.selection().slice() : [hit.id];
    sep();
    out.push(...drawingEntries(ctx, hit, ids));
  }

  if (target.kind === 'indicator' && target.instanceId !== undefined) {
    const inst = chart.indicators().find((i) => i.id === target.instanceId);
    if (inst !== undefined) {
      sep();
      // A study its host protects shows the rows its policy withholds greyed,
      // with the reason, rather than rows that would silently do nothing.
      const policy = inst.policy();
      const note = (flag: 'configurable' | 'removable'): string | undefined => policy[flag] === false ? widgetText(ctx, 'protected') : undefined;
      out.push({ id: 'ind-settings', label: widgetText(ctx, '{name} settings...', { name: inst.name }), icon: 'settings',
        disabled: note('configurable') !== undefined, note: note('configurable'),
        run: () => { mountIndicatorSettings(ctx, undefined, { instanceId: inst.id }); } });
      out.push({ id: 'ind-visible', label: inst.visible() ? widgetText(ctx, 'Hide {name}', { name: inst.name }) : widgetText(ctx, 'Show {name}', { name: inst.name }), icon: inst.visible() ? 'eye' : 'eye-off',
        run: () => { inst.setVisible(!inst.visible()); } });
      out.push({ id: 'ind-remove', label: widgetText(ctx, 'Remove {name}', { name: inst.name }), icon: 'trash', danger: true,
        disabled: note('removable') !== undefined, note: note('removable'),
        run: () => { chart.removeIndicator(inst.id); } });
    }
  }

  // The pane under the pointer: it moves up or down a slot, the price pane
  // included when the host opted in (`movablePrimaryPane`),
  // and a study pane folds to its header strip and opens again. The price
  // pane stays open in any slot. A menu raised from a button names no pane,
  // and the time axis belongs to the whole chart, so neither gets these.
  if (target.kind !== 'time-scale' && !SYNTHETIC.has(e)) {
    const count = chart.panes().length, at = e.paneIndex;
    if (count > 1 && at >= 0 && at < count) {
      sep();
      // A pinned price pane refuses a swap that moves or displaces it, so the
      // row says so rather than doing nothing.
      const pinned = (to: number): boolean => !chart.movablePrimaryPane() && (at === pricePane || to === pricePane);
      const move = (id: string, label: 'Move pane up' | 'Move pane down', direction: -1 | 1, edge: boolean, where: 'at the top' | 'at the bottom'): MenuItem => {
        const note = edge ? widgetText(ctx, where) : pinned(at + direction) ? widgetText(ctx, 'price pane stays on top') : undefined;
        return { id, label: widgetText(ctx, label), disabled: note !== undefined, note, run: () => { chart.movePane(at, direction); } };
      };
      out.push(move('pane-up', 'Move pane up', -1, at === 0, 'at the top'));
      out.push(move('pane-down', 'Move pane down', 1, at === count - 1, 'at the bottom'));
    }
    if (at !== pricePane && at >= 0 && at < count) {
      const folded = chart.paneCollapsed(at);
      sep();
      out.push({ id: 'pane-collapse', label: widgetText(ctx, folded ? 'Expand pane' : 'Collapse pane'),
        run: () => { chart.setPaneCollapsed(at, !folded); } });
    }
  }

  if (target.kind !== 'time-scale') {
    sep();
    out.push({ id: 'draw-paste', label: widgetText(ctx, 'Paste'), icon: 'paste', chord: commandChord(ctx.keymap, 'paste', 'Mod+V'),
      run: () => { void draw.paste().then((made) => { if (made.length === 0) ctx.toast(widgetText(ctx, 'Nothing to paste'), 'info'); }); } });
    // What `clear` would take: a read-only drawing stays, so it is not counted.
    const n = draw.drawings().filter((d) => d.policy?.editable !== false).length;
    if (n > 0) {
      out.push({ id: 'draw-clear', label: widgetText(ctx, 'Remove all drawings ({count})', { count: n }), icon: 'trash', danger: true, run: () => { draw.clear(); } });
    }
  }

  sep();
  out.push({ id: 'chart-fit', label: widgetText(ctx, 'Fit all bars'), icon: 'fit', chord: commandChord(ctx.keymap, 'chart:fitContent'),
    disabled: chart.navigationOptions().zoomEnabled === false,
    run: () => { if (chart.navigationOptions().zoomEnabled !== false) chart.fitContent(); } });
  if (target.kind !== 'time-scale') {
    out.push({ id: 'chart-indicators', label: widgetText(ctx, 'Indicators...'), icon: 'indicators', run: () => { mountIndicatorPicker(ctx); } });
  }
  out.push({ id: 'chart-settings', label: widgetText(ctx, 'Settings...'), icon: 'settings', run: () => { mountSettingsDialog(ctx); } });

  const extra = hooks.items?.(e) ?? [];
  if (extra.length > 0) { sep(); out.push(...extra); }
  return out;
}

/** Events made for a menu raised from a button: they name no pane under a pointer. */
const SYNTHETIC = new WeakSet<ContextMenuEvent>();

/** A chart-level event for a menu raised from a button rather than the canvas. */
function syntheticEvent(chart: Chart): ContextMenuEvent {
  const event: ContextMenuEvent = {
    paneIndex: chart.primaryPaneIndex(), point: { x: 0, y: 0 }, price: null, time: null, index: null,
    target: { kind: 'empty', id: null }, preventDefault: () => {},
  };
  SYNTHETIC.add(event);
  return event;
}

/** One menu per widget; a second right-click replaces the first. */
const OPEN = new WeakMap<HTMLElement, PanelHandle>();

/**
 * Show the menu for `opts.event` at the pointer, or the chart-level menu below
 * `anchor` when no event is given.
 */
export function mountContextMenu(ctx: WidgetContext, anchor?: HTMLElement, opts: ContextMenuOptions = {}): PanelHandle {
  const doc = ctx.document;
  OPEN.get(ctx.root)?.close();
  const e = opts.event ?? syntheticEvent(ctx.chart);
  const hooks = opts.hooks ?? {};

  const menu = el(doc, 'div', 'oac-panel oac-ctx');
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', widgetText(ctx, 'Chart menu'));
  menu.tabIndex = -1;
  stopOwnKeys(menu);

  let rows: HTMLButtonElement[] = [];

  const focusRow = (i: number): void => {
    const live = rows.filter((r) => r.getAttribute('aria-disabled') !== 'true');
    if (live.length === 0) return;
    live[((i % live.length) + live.length) % live.length]!.focus(); // a non-empty list, index wrapped into it
  };

  function paint(focusIndex = -1): void {
    menu.innerHTML = '';
    rows = [];
    const entries = contextMenuEntries(ctx, e, hooks);
    for (const entry of entries) {
      if (entry.kind === 'separator') { menu.appendChild(el(doc, 'div', 'oac-ctx__hr')); continue; }
      if (entry.kind === 'header') { menu.appendChild(el(doc, 'div', 'oac-head', entry.label)); continue; }
      const item = entry;
      const row = el(doc, 'button', 'oac-ctx__row' + (item.danger === true ? ' is-danger' : ''));
      row.type = 'button';
      row.setAttribute('role', item.mark === 'check' ? 'menuitemcheckbox' : item.mark === 'radio' ? 'menuitemradio' : 'menuitem');
      if (item.mark !== undefined) row.setAttribute('aria-checked', item.on === true ? 'true' : 'false');
      if (item.id !== undefined) row.dataset.act = item.id;
      row.tabIndex = -1;
      // The marker column is drawn either way, so the labels keep one left
      // edge whether anything is set or not.
      const mark = el(doc, 'span', 'oac-ctx__mark');
      if (item.mark === 'radio' && item.on === true) mark.appendChild(el(doc, 'span', 'oac-ctx__dot'));
      else if (item.mark === 'check' && item.on === true) mark.appendChild(chromeGlyph(doc, 'check'));
      else if (item.icon !== undefined) {
        if (item.icon.startsWith('<svg')) { const g = el(doc, 'span', 'oac-glyph oac-glyph--chrome'); g.innerHTML = item.icon; mark.appendChild(g); }
        else mark.appendChild(chromeGlyph(doc, item.icon));
      }
      row.appendChild(mark);
      row.appendChild(el(doc, 'span', 'oac-ctx__label', item.label));
      if (item.note !== undefined && item.note !== '') row.appendChild(el(doc, 'span', 'oac-ctx__note', item.note));
      if (item.chord !== undefined) {
        // Shown beside the name, said as the row's shortcut rather than read into its name.
        const key = row.appendChild(el(doc, 'kbd', 'oac-ctx__key', item.chord));
        key.setAttribute('aria-hidden', 'true');
        row.setAttribute('aria-keyshortcuts', ariaKeys(item.chord));
      }
      if (item.disabled === true) {
        row.setAttribute('aria-disabled', 'true');
      } else {
        row.addEventListener('click', (ev) => {
          ev.stopPropagation();
          // One row is one step, including what the chart does not announce
          // (an axis mode, an auto-fit switch). A row that changes nothing
          // (fit, copy, an order) records nothing.
          if (item.run !== undefined) historyStep(ctx, item.id, item.run);
          if (item.keepOpen === true) paint(rows.indexOf(row));
          else handle.close();
        });
      }
      menu.appendChild(row);
      rows.push(row);
    }
    if (focusIndex >= 0 && rows[focusIndex] !== undefined) rows[focusIndex].focus();
  }
  paint();

  menu.addEventListener('keydown', (ev) => {
    const k = (ev as KeyboardEvent).key;
    const live = rows.filter((r) => r.getAttribute('aria-disabled') !== 'true');
    const at = live.indexOf(doc.activeElement as HTMLButtonElement);
    if (k === 'ArrowDown') { ev.preventDefault(); focusRow(at + 1); }
    else if (k === 'ArrowUp') { ev.preventDefault(); focusRow(at <= 0 ? live.length - 1 : at - 1); }
    else if (k === 'Home') { ev.preventDefault(); focusRow(0); }
    else if (k === 'End') { ev.preventDefault(); focusRow(live.length - 1); }
  });

  const first = rows.find((r) => r.getAttribute('aria-disabled') !== 'true') ?? menu;
  const handle = openPanel(
    ctx, menu,
    anchor !== undefined && opts.event === undefined
      ? { anchor, placement: 'below', initialFocus: first }
      : { placement: 'below', modal: false, dismissOnOutside: true, initialFocus: first },
    () => {},
  );
  if (anchor === undefined || opts.event !== undefined) {
    const container = chartContainer(ctx.chart);
    const off = container === null ? { left: 0, top: 0 } : boxIn(ctx.root, container);
    placePanel(ctx.root, menu, { point: { x: e.point.x + off.left, y: e.point.y + off.top } });
  }
  OPEN.set(ctx.root, handle);
  return handle;
}

/**
 * Wire the chart's `contextmenu` event to the menu. Returns the unsubscriber.
 * The browser's own menu is suppressed only once ours is up, so a host that
 * detaches this gets the native one back.
 */
export function attachContextMenu(ctx: WidgetContext, hooks: ContextMenuHooks = {}): () => void {
  return ctx.chart.on('contextmenu', (payload) => {
    const e = payload as ContextMenuEvent;
    e.preventDefault();
    mountContextMenu(ctx, undefined, { event: e, hooks });
  });
}

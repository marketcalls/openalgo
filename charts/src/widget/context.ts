/**
 * The contract between the widget shell and everything mounted inside it.
 *
 * `WidgetContext` is what the shell hands to the rail, the top bar, the
 * status line and every dialog: the chart and the drawing controller, the
 * root element, the theme in force, the keymap, a toast, an overlay opener
 * that positions, focus-traps and Escape-closes whatever it is given, and a
 * small event bus. A dialog module never reaches for the document on its own;
 * everything it needs to place itself or to hand focus back comes from here.
 *
 * The rest of this file is what every part of that contract shares: the
 * drawing and history helpers the controls act through, the bus, and the
 * dialog registry through which the dialog tier makes its mount functions
 * known. The furniture behind the contract has modules of its own, and this
 * one exports their names too: the DOM kit (dom.ts), the storage wrapper
 * (widget-storage.ts), and the overlay stack and the tooltip (overlays.ts).
 */
import type { AlertController, Chart, ChartObjects, ChartSettingsValues, ChartTheme, DataVariant } from 'openalgo-charts';
import { getDrawingTool, hasDrawingTool, type DrawingController, type DrawingTool } from 'openalgo-charts/draw';
import type { Keymap } from './keymap';
import type { ToastHandle, ToastKind } from './toast';
import type { WidgetThemeName } from './tokens';
import type { WidgetTranslator } from './localization';
import type { SymbolSearch } from './symbol-picker';
import type { ChartHistory } from './history';
import type { DrawingTemplates } from './drawing-templates';
import type { OverlayOptions, OverlayStack, TipController } from './overlays';
import type { WidgetStorage } from './widget-storage';

export { esc, h, glyph, inTextField, focusable, focusables, placeBeside, placeBelow, placeTip, boxIn } from './dom';
export type { Box, Size, TipSide } from './dom';
export { WidgetStorage, STORAGE_PREFIX, defaultStorage } from './widget-storage';
export type { StorageLike, AsyncStorageLike, WidgetStorageError, WidgetStorageOptions } from './widget-storage';
export { createOverlayStack, createTipController, TIP_DWELL_MS } from './overlays';
export type { OverlayOptions, OverlayStack, TipSpec, TipSource, TipController } from './overlays';

// ── drawing and history helpers ────────────────────────────────────────

/**
 * The ids among `ids` the user may edit: a drawing whose policy sets
 * `editable` false is not one of them. Every widget control that edits a
 * drawing takes its enabled state from this, so none is offered and then
 * refused by the controller.
 */
export function editableIds(draw: DrawingController, ids: readonly string[]): string[] {
  return ids.filter((id) => draw.get(id)?.policy?.editable !== false);
}

/** The registered tool a drawing names, or null for one this build does not carry. */
export function drawingToolOf(id: string): DrawingTool | null {
  return hasDrawingTool(id) ? getDrawingTool(id) : null;
}

/**
 * One undo or redo press from any control: the chart-wide timeline when the
 * context carries one, the drawing controller's own otherwise, so every
 * button, chord and sheet walks the same steps.
 */
export function historyPress(ctx: Pick<WidgetContext, 'draw' | 'history'>, direction: 'undo' | 'redo'): boolean {
  const history = ctx.history;
  if (history !== undefined && !history.isDestroyed) return direction === 'undo' ? history.undo() : history.redo();
  return direction === 'undo' ? ctx.draw.undo() : ctx.draw.redo();
}

/**
 * Run `run` as one step of the chart-wide timeline, however many controller
 * calls it makes, so one user action is one undo. A context without the
 * timeline runs it as it is.
 */
export function historyStep(ctx: Pick<WidgetContext, 'history'>, label: string | undefined, run: () => void): void {
  if (ctx.history !== undefined) ctx.history.transact(run, label);
  else run();
}

/** Whether that press would do anything, for the control's enabled state. */
export function historyReady(ctx: Pick<WidgetContext, 'draw' | 'history'>, direction: 'undo' | 'redo'): boolean {
  const history = ctx.history;
  if (history !== undefined && !history.isDestroyed) return direction === 'undo' ? history.canUndo() : history.canRedo();
  return direction === 'undo' ? ctx.draw.canUndo() : ctx.draw.canRedo();
}

// ── event bus ──────────────────────────────────────────────────────────

export type BusHandler<T = unknown> = (payload: T) => void;

/**
 * A tiny typed event bus. Handlers run in registration order; one that throws
 * does not stop the others, because a host's listener failing must not take
 * the shell's own bookkeeping with it.
 */
export class WidgetBus<Events extends Record<string, unknown> = Record<string, unknown>> {
  private readonly _handlers = new Map<string, Set<BusHandler>>();

  public on<K extends keyof Events & string>(event: K, handler: BusHandler<Events[K]>): () => void {
    let set = this._handlers.get(event);
    if (set === undefined) { set = new Set(); this._handlers.set(event, set); }
    set.add(handler as BusHandler);
    return () => this.off(event, handler);
  }

  public off<K extends keyof Events & string>(event: K, handler?: BusHandler<Events[K]>): void {
    if (handler === undefined) { this._handlers.delete(event); return; }
    this._handlers.get(event)?.delete(handler as BusHandler);
  }

  public emit<K extends keyof Events & string>(event: K, payload: Events[K]): void {
    const set = this._handlers.get(event);
    if (set === undefined) return;
    const errors: unknown[] = [];
    for (const fn of Array.from(set)) {
      try { fn(payload); } catch (e) { errors.push(e); }
    }
    if (errors.length > 0) throw errors[0];
  }

  public clear(): void { this._handlers.clear(); }
}

// ── dialog registry ────────────────────────────────────────────────────

/** What a dialog module's mount function returns. */
export interface DialogHandle { close(): void }

/** The mount signature every dialog exports: `(ctx, anchor?) => { close }`. */
export type DialogMount = (ctx: WidgetContext, anchor?: HTMLElement) => DialogHandle;

/**
 * The dialogs the shell knows how to ask for. Each is mounted by the dialog
 * tier and registered here; a shell built without one renders the control
 * that would open it disabled, with its state visible, rather than dead.
 */
export type WidgetDialogName =
  | 'settings' | 'indicatorPicker' | 'indicatorSettings' | 'drawingProperties'
  | 'contextMenu' | 'levelEditor' | 'textEditor' | 'alertEditor' | 'alerts';

const DIALOGS = new Map<WidgetDialogName, DialogMount>();

/** Make a dialog's mount function known to every shell. Returns a disposer. */
export function registerWidgetDialog(name: WidgetDialogName, mount: DialogMount): () => void {
  DIALOGS.set(name, mount);
  return () => { if (DIALOGS.get(name) === mount) DIALOGS.delete(name); };
}

/** Register several at once, from a module's exports. */
export function registerWidgetDialogs(mounts: Partial<Record<WidgetDialogName, DialogMount>>): () => void {
  const undo = Object.entries(mounts).map(([n, m]) => registerWidgetDialog(n as WidgetDialogName, m as DialogMount));
  return () => { for (const u of undo) u(); };
}

/** Take a dialog out of the registry. False when nothing was registered under the name. */
export function unregisterWidgetDialog(name: WidgetDialogName): boolean {
  return DIALOGS.delete(name);
}

/** The registered mount for a dialog, or null. */
export function widgetDialog(name: WidgetDialogName): DialogMount | null {
  return DIALOGS.get(name) ?? null;
}

export function registeredWidgetDialogs(): WidgetDialogName[] {
  return Array.from(DIALOGS.keys());
}

// ── the context ────────────────────────────────────────────────────────

/** The events the shell publishes on `ctx.bus`. */
export interface WidgetBusEvents {
  symbol: { symbol: string; exchange: string };
  interval: { interval: string };
  /** The data variant changed; undefined is the feed's default series. */
  variant: { variant?: Readonly<DataVariant> | undefined };
  theme: { theme: WidgetThemeName; chartTheme: ChartTheme };
  /** Something about the workspace changed: the chart type, a restored layout, a pane. */
  layout: { reason: string; chartType?: string };
  /** The status line's transient message changed. */
  status: { text: string; kind: 'info' | 'error' };
  /** A keymap registration collided with another binding. */
  'keymap:conflict': { combo: string; kept: string; shadowed: string };
  /** Bars finished loading, or failed to. */
  data: { symbol: string; interval: string; bars: number; error?: string | undefined };
  [key: string]: unknown;
}

export interface WidgetContext {
  readonly chart: Chart;
  readonly draw: DrawingController;
  /** Live inventory owned by the widget, optional for custom contexts. */
  readonly objects?: ChartObjects | undefined;
  /** Trader alerts owned by the widget, optional for custom contexts. */
  readonly alerts?: AlertController | undefined;
  /**
   * The chart-wide undo timeline. Every undo and redo control goes through it
   * when it is there; a custom context without one falls back to the drawing
   * controller's own history.
   */
  readonly history?: ChartHistory | undefined;
  /**
   * Saved drawing looks, when the host gave the widget a template store:
   * the properties dialog and the floating toolbar offer them.
   */
  readonly drawingTemplates?: DrawingTemplates | undefined;
  /** The `.oac-widget` element every piece of chrome lives in. */
  readonly root: HTMLElement;
  readonly document: Document;
  /** `dark` or `light`, following the chart theme in force. */
  readonly theme: WidgetThemeName;
  /** The engine palette the chart is drawing with. */
  readonly chartTheme: ChartTheme;
  readonly keymap: Keymap;
  readonly bus: WidgetBus<WidgetBusEvents>;
  /** Per-widget persisted preferences; `enabled` is false when `persist` is off. */
  readonly storage: WidgetStorage;
  readonly locale: string | undefined;
  readonly translate?: WidgetTranslator | undefined;
  /** Configured instrument lookup, shared by the header and indicator inputs. */
  readonly symbolSearch?: SymbolSearch | undefined;
  toast(message: string, kind?: ToastKind): ToastHandle;
  /**
   * Show `el` over the widget: positioned from `opts.anchor` (or centred as a
   * dialog), focus-trapped, closed by Escape and by a press outside. Returns
   * the closer.
   */
  openOverlay(el: HTMLElement, opts?: OverlayOptions): () => void;
  /** Put a transient message on the status line. */
  status(text: string, kind?: 'info' | 'error'): void;
  /** Hover labels for controls. */
  readonly tips: TipController;
  /** The overlay stack behind `openOverlay`, for a module that needs to ask what is open. */
  readonly overlays: OverlayStack;
  /** The current symbol and interval, for dialogs that name them. */
  symbol(): { symbol: string; exchange: string };
  interval(): string;
  /**
   * The intervals the host serves, when it named them (`WidgetOptions.intervals`):
   * a study's timeframe select offers these.
   */
  readonly intervals?: readonly string[] | undefined;
  /**
   * Settings the widget starts at a value of its own rather than the
   * engine's, keyed as the settings schema keys them (since 2.6.3). The
   * dialog's Restore returns to these, so it lands where a fresh widget
   * starts: the drag that moves time alone, not the engine's time and price.
   */
  readonly settingsDefaults?: Readonly<ChartSettingsValues> | undefined;
}

/**
 * Saved layouts and indicator templates for one widget, from the store its
 * host passes as `WidgetOptions.workspaces`: a layouts controller over the
 * widget itself (or the one a chart grid hands every chart), the Layouts menu
 * the top bar and the phone layout open, and the store the indicator picker
 * offers templates from.
 *
 * Its own module so widget.ts carries only the option and the mount call.
 * On creation it reopens the layout that was active when the page last
 * closed, so a reload continues where autosave left off; the layout replaces
 * the chart the host started with, as opening it from the menu would.
 *
 * The menu itself loads on first use (lazy.ts, layouts-menu.ts); what the
 * top bar and the grid bar show before anyone opens it, the held layout's
 * status and its button, is here.
 */
import type { WorkspaceStore } from 'openalgo-charts/workspace';
import type { WidgetContext } from './context';
import type { PanelHandle } from './form';
import { createLayoutsController, type LayoutsController, type LayoutsState } from './layouts';
import { widgetLayoutTarget } from './layouts-target';
import { bindTemplateStore } from './layouts-templates';
import { lazyPart, partFailed, usePart, type PartSlot } from './lazy';
import { errorText, widgetText } from './localization';
import type { Widget } from './widget';

type Text = (key: string, fallback: string, values?: Record<string, string | number>) => string;

/** The Layouts menu's messages, under `schema.ui.layouts`. Internal. */
export const layoutText = (ctx: WidgetContext): Text => (key, fallback, values = {}) =>
  widgetText(ctx, `schema.ui.layouts.${key}`, values, fallback);

/**
 * What the held layout's status line says, and what the top bar button's tip
 * repeats: the one sentence a user needs about whether the chart is kept.
 */
export function layoutStatusText(ctx: WidgetContext, state: LayoutsState): string {
  const text = layoutText(ctx);
  if (state.layoutId === null) return text('unsaved', 'This chart is not saved as a layout');
  if (state.conflict) return text('conflict', 'Changed in another window');
  if (state.catalog?.autosave) {
    if (state.autosave === 'saving') return text('saving', 'Saving');
    if (state.autosave === 'failed') return text('failed', 'Could not save');
    if (state.autosave === 'pending') return state.suspended ? text('suspended', 'Autosave waits for the replay to end') : text('pending', 'Waiting to save');
    return text('saved', 'Saved');
  }
  return state.dirty ? text('dirty', 'Unsaved changes') : text('saved', 'Saved');
}

/**
 * Say, once when it starts, that the autosave of a controller the widget or
 * the chart grid made itself has stopped, or that its layout was changed in
 * another window: the menu may be closed, and a screen reader hears no mark.
 * Returns the unsubscribe. Internal, shared with the chart grid.
 */
export function sayLayoutFailures(controller: LayoutsController, text: Text, say: (message: string) => void): () => void {
  let failing = false;
  return controller.subscribe(state => {
    const failed = state.autosave === 'failed' && !state.conflict;
    if (!failing && (failed || state.conflict)) {
      say(failed ? text('autosaveStopped', 'Autosave stopped: the layout could not be saved') : text('conflictStatus', 'The layout was changed in another window'));
    }
    failing = failed || state.conflict;
  });
}

/** Whether the top bar should mark the held layout: unsaved, failing or changed elsewhere. */
export function layoutNeedsAttention(state: LayoutsState): boolean {
  return state.layoutId !== null && (state.conflict || state.autosave === 'failed' || (state.dirty && !state.catalog?.autosave));
}

/** The Layouts menu, fetched when it first opens. Internal. */
export const layoutsMenuPart = lazyPart(() => import('./layouts-menu'));

/**
 * Open the Layouts menu for `controller`: under `anchor`, or centred as a
 * dialog without one and on a phone layout. The menu loads on first use
 * (since 2.5.10), so this resolves with its handle once it is open, and
 * rejects when it could not load or the widget was destroyed by then.
 */
export function openLayoutsMenu(ctx: WidgetContext, controller: LayoutsController, anchor?: HTMLElement): Promise<PanelHandle> {
  return layoutsMenuPart.load().then(module => {
    // A menu mounted on a destroyed widget would sit off the page, open and still following the controller.
    if (ctx.chart.isDestroyed) throw new Error('The widget was destroyed before its Layouts menu opened');
    return module.mountLayoutsMenu(ctx, controller, anchor);
  });
}

/** The menu a control of the shell opens, and the request it has on its way (lazy.ts). Internal. */
export interface LayoutsMenuSlot extends PartSlot { handle: PanelHandle | null }

/**
 * Open the menu for a control of the shell: at once when it has arrived,
 * else when it does, unless `live` says the control has gone by then or the
 * user has moved on, and once however often the control is pressed
 * meanwhile. Internal.
 */
export function showLayoutsMenu(ctx: WidgetContext, controller: LayoutsController, anchor: HTMLElement | undefined,
  menu: LayoutsMenuSlot, live: () => boolean): void {
  if (menu.handle?.isOpen()) { menu.handle.el.focus(); return; }
  usePart(layoutsMenuPart, module => { menu.handle = module.mountLayoutsMenu(ctx, controller, anchor); },
    error => ctx.toast(partFailed(ctx, layoutText(ctx)('title', 'Layouts'), error), 'error'), live, { slot: menu, doc: ctx.document, from: anchor });
}

/** The top bar's Layouts button, which shows before the menu has loaded. */
export const LAYOUTS_BUTTON_CSS = `
.oac-widget .oac-topbar__layouts { max-width: 190px; }
.oac-widget .oac-topbar__layouts-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* The name gives way before the bar wraps to a second row: the glyph, the unsaved mark, the tip and the
   accessible name still carry it. Measured on the default bar, which needs about 1000 px on one row. */
.oac-widget .oac-topbar.has-layouts { container: oac-topbar / inline-size; }
@container oac-topbar (max-width: 1199px) { .oac-widget .oac-topbar__layouts-name { max-width: 96px; } }
@container oac-topbar (max-width: 1139px) { .oac-widget .oac-topbar__layouts-name { display: none; } }
.oac-widget .oac-topbar__layouts[data-attention="true"]::after { content: ''; width: 6px; height: 6px; flex: none; border-radius: 50%; background: var(--oac-amber); }
`;

/** What the widget holds for its layouts; internal. */
export interface WidgetLayouts {
  /** What the Layouts menu drives, or null when the widget shows no menu. */
  readonly controller: LayoutsController | null;
  /** Open the Layouts menu, under `anchor` when given. False without a controller or after destroy. */
  open(anchor?: HTMLElement): boolean;
  destroy(): void;
}

interface WidgetLayoutsOptions {
  workspaces?: WorkspaceStore;
  layouts?: LayoutsController | false;
}

/** Wire `widget`'s layouts and templates, or null when its host passed neither a store nor a controller. */
export function attachWidgetLayouts(widget: Widget, options: WidgetLayoutsOptions): WidgetLayouts | null {
  const store = options.workspaces;
  const given = options.layouts === false ? null : options.layouts ?? null;
  if (store === undefined && given === null) return null;
  const ctx = widget.context;
  const text = layoutText(ctx);
  bindTemplateStore(ctx, store);
  // A controller handed over belongs to its maker (a grid, over all its charts): used, never reopened or destroyed here.
  const own = given === null && options.layouts !== false && store !== undefined ? createLayoutsController(store, widgetLayoutTarget(widget)) : null;
  const controller = given ?? own;
  const menu: LayoutsMenuSlot = { handle: null, waiting: null };
  let destroyed = false;
  const offState = own === null ? undefined : sayLayoutFailures(own, text, message => ctx.status(message, 'error'));
  // A change inside autosave's quiet period is written when the page is hidden:
  // a tab switched away from may be closed without coming back. Best effort on
  // pagehide, since the store's write may not finish before the page goes.
  const doc = ctx.document;
  const win = doc.defaultView;
  const flushHidden = (): void => { if (doc.visibilityState === 'hidden') void own?.flush(); };
  const flushGone = (): void => { void own?.flush(); };
  if (own !== null) {
    doc.addEventListener('visibilitychange', flushHidden);
    win?.addEventListener('pagehide', flushGone);
    void own.reload().then(async catalog => {
      if (destroyed || catalog.activeWorkspaceId === null) return;
      const report = await own.open(catalog.activeWorkspaceId);
      if (!report.applied && !destroyed) ctx.status(text('notReopened', 'The last layout could not open here: {error}', { error: report.reason ?? '' }), 'error');
    }).catch((error: unknown) => {
      if (!destroyed) ctx.status(text('notLoaded', 'Saved layouts could not be read: {error}', { error: errorText(ctx, error) }), 'error');
    });
  }
  return {
    controller,
    open(anchor) {
      if (destroyed || controller === null) return false;
      showLayoutsMenu(ctx, controller, anchor, menu, () => !destroyed);
      return true;
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      menu.handle?.close();
      offState?.();
      doc.removeEventListener('visibilitychange', flushHidden);
      win?.removeEventListener('pagehide', flushGone);
      own?.destroy();
      bindTemplateStore(ctx, undefined);
    },
  };
}

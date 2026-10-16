/**
 * The chart grid's saved layouts: one layouts controller over the whole
 * desk, which the grid bar's Layouts control opens the widget's own Layouts
 * menu on.
 *
 * Its own module so grid.ts carries only the option and the mount call. It
 * reaches the grid through its public API alone, as a host building its own
 * controller over a grid would.
 *
 * Three decisions worth recording:
 *
 * - **A layout of the desk is what is on the charts.** It is `getWorkspace`
 *   with each chart written as the widget writes one (`layoutChartState`:
 *   no view, no alert bookkeeping), and without the focus: which chart is
 *   active changes with every click, and a layout that held it would read as
 *   unsaved, and cost an autosave write, at each one. An opened layout makes
 *   its first chart active.
 * - **The grid builds its own controller only with the bar that shows it.**
 *   A controller that autosaves and reopens the last layout at page load,
 *   with no control to say so, would change a host's page behind its back.
 * - **The last layout reopens once the grid's own desk has landed**, so the
 *   two never race, and a layout replaces the persisted desk as opening it
 *   from the menu would. A desk opened before it could (a host's hand-off
 *   from another page, a file, the menu) is the newer choice, and stays.
 */
import { isReplaying } from 'openalgo-charts';
import type { WorkspacePayload, WorkspaceStore } from 'openalgo-charts/workspace';
import type { WidgetContext } from './context';
import type { ChartGrid } from './grid';
import { createLayoutsController, type LayoutsController, type LayoutTarget } from './layouts';
import { layoutChartState, widgetLayoutTarget } from './layouts-target';
import { layoutStatusText, sayLayoutFailures, showLayoutsMenu, type LayoutsMenuSlot } from './layouts-widget';
import { errorText, widgetText } from './localization';
import type { WidgetChartState } from './widget';

/** What the saved layouts read from the grid. */
interface GridSavedHost {
  readonly grid: ChartGrid;
  /** The grid's own persisted desk has landed. */
  readonly ready: Promise<void>;
  readonly workspaces?: WorkspaceStore | undefined;
  readonly layouts?: LayoutsController | false | undefined;
  /** The active chart's context over the grid's own layer: the menu opens there, and reports go to its status line. */
  context(): WidgetContext;
  /** Whether a desk was opened on the grid (`applyWorkspace`) since it was built. */
  opened(): boolean;
}

/** What the grid holds of its saved layouts; internal. */
export interface GridSaved {
  readonly controller: LayoutsController;
  /** Open the Layouts menu under `anchor`, or bring the open one forward. */
  open(anchor: HTMLElement): void;
  /** What the held layout's status line says, for the control's tip. */
  status(): string;
  /** Write a change still inside autosave's quiet period: the page is being hidden or left. */
  flush(): void;
  destroy(): void;
}

/** The layouts the grid bar drives, or null when the host gave neither a store nor a controller. */
export function attachGridSaved(host: GridSavedHost): GridSaved | null {
  const { grid } = host;
  const given = host.layouts === false ? null : host.layouts ?? null;
  if (host.layouts === false || (given === null && host.workspaces === undefined)) return null;
  const text = (key: string, fallback: string, values: Record<string, string | number> = {}): string =>
    widgetText(host.context(), `schema.ui.layouts.${key}`, values, fallback);
  const report = (message: string): void => { if (!grid.isDestroyed) host.context().status(message, 'error'); };

  let heard: (() => void) | null = null;
  let chartOffs: Array<() => void> = [];
  /** The grid raises no event for a change inside a chart: each chart is heard as the widget hears its own. */
  const wire = (): void => {
    for (const off of chartOffs.splice(0)) off();
    const listener = heard;
    if (listener !== null) chartOffs = grid.cells().map(cell => widgetLayoutTarget(cell.widget).subscribe!(listener));
  };
  const target: LayoutTarget = {
    capture(): WorkspacePayload {
      const payload = grid.getWorkspace(); // one pane per cell, and a grid is never without a cell
      return { ...payload, activePaneId: payload.panes[0]!.id,
        panes: payload.panes.map(pane => ({ ...pane, chart: layoutChartState(pane.chart as WidgetChartState) })) };
    },
    apply: payload => grid.applyWorkspace(payload),
    subscribe(listener) {
      heard = listener;
      wire();
      const offs = [
        // A new set of charts is heard afresh; a track, a swap or a link is a change of the desk's own.
        grid.on('layout', ({ reason }) => { if (reason === 'preset' || reason === 'workspace') wire(); listener(); }),
        grid.on('links', listener),
      ];
      return () => {
        heard = null;
        wire();
        for (const off of offs) off();
      };
    },
    suspended: () => grid.cells().some(cell => isReplaying(cell.widget.chart)),
  };
  // A controller handed over belongs to its maker: used, never reopened, flushed or destroyed here.
  const own = given === null ? createLayoutsController(host.workspaces as WorkspaceStore, target) : null;
  const controller = (given ?? own) as LayoutsController;
  const menu: LayoutsMenuSlot = { handle: null, waiting: null };
  let destroyed = false;
  if (own !== null) {
    // Said on the active chart's status line, as one widget says it. The controller's destroy lets go of this listener.
    sayLayoutFailures(own, text, report);
    void host.ready.then(() => (destroyed ? null : own.reload())).then(async catalog => {
      if (destroyed || catalog == null || catalog.activeWorkspaceId === null || host.opened()) return;
      const opened = await own.open(catalog.activeWorkspaceId);
      if (!opened.applied && !destroyed) report(text('notReopened', 'The last layout could not open here: {error}', { error: opened.reason ?? '' }));
    }).catch((error: unknown) => {
      if (!destroyed) report(text('notLoaded', 'Saved layouts could not be read: {error}', { error: errorText(host.context(), error) }));
    });
  }
  return {
    controller,
    open(anchor) {
      if (!destroyed) showLayoutsMenu(host.context(), controller, anchor, menu, () => !destroyed && !grid.isDestroyed);
    },
    status: () => layoutStatusText(host.context(), controller.state()),
    flush() { if (!destroyed) void own?.flush(); },
    // The menu lives in the grid's own layer, which the grid closes with everything in it.
    destroy() {
      if (destroyed) return;
      destroyed = true;
      own?.destroy();
    },
  };
}

/**
 * The chart's legend rows: stacking them per pane, the pane controls a study
 * pane's first row carries, the offsets that keep study rows clear of a
 * host's own readout, the study count toggle, and what a press on a legend
 * button does.
 *
 * Its own module because the toggle, the row it is reserved at and the offset
 * study rows start from belong to these methods alone. The chart reaches it
 * through `Chart._legendStack`, and it reaches the chart through
 * `LegendsHost`. `Chart._handleLegendAction` stays as a delegate because the
 * pointer release and tests route a press through it by name, and the public
 * status-line, collapse and icon-size setters stay on Chart with their bodies.
 * Members the chart calls are public on this internal class; no entry point
 * exports the class and the chart holds it in a private field, so none of it
 * reaches the published declarations.
 */
import { InvalidationLevel } from './invalidate-mask';
import type { Chart } from './chart';
import { paneLegendRowHeight, type PaneLegend, type PaneLegendAction } from '../primitives/pane-legend';
import { IndicatorLegendToggle, INDICATOR_LEGEND_TOGGLE } from '../primitives/indicator-legend-toggle';

/** PaneLegend's own defaults, restated so a pane can be reset to them. */
export const DEFAULT_LEGEND_TOP = 6;
const DEFAULT_LEGEND_LEFT = 8;
/** The controls the first study row of a lower pane carries for the pane itself. */
const PANE_ACTIONS: readonly PaneLegendAction[] = ['up', 'down', 'collapse', 'maximize'];

/** A study row's own actions, with the pane's controls before close when the row leads its pane. */
function leadActions(actions: readonly PaneLegendAction[] = [], lead: boolean): PaneLegendAction[] {
  const own = actions.filter(action => !PANE_ACTIONS.includes(action));
  if (lead) own.splice(own.includes('close') ? own.indexOf('close') : own.length, 0, ...PANE_ACTIONS);
  return own;
}

/**
 * The slice of the chart the legend rows read and drive. The chart itself is
 * the host: each member carries the name and the type of the chart's own, so
 * the moved code reads as it did in chart.ts, and a member the chart renames
 * or retypes fails to compile here.
 */
export interface LegendsHost {
  readonly _panes: Chart['_panes'];
  readonly _primaryPane: Chart['_primaryPane'];
  readonly _indicators: Chart['_indicators'];
  readonly _legends: Chart['_legends'];
  readonly _studyLegends: Chart['_studyLegends'];
  readonly _legendActions: Chart['_legendActions'];
  readonly _collapsed: Chart['_collapsed'];
  readonly _indicatorLegendCollapsed: Chart['_indicatorLegendCollapsed'];
  readonly _legendIconSize: Chart['_legendIconSize'];
  readonly _leftAxisWidth: Chart['_leftAxisWidth'];
  readonly _timeNav: Chart['_timeNav'];
  /** The chart's other collaborators, whose methods this code calls directly. */
  readonly _primitives: Chart['_primitives'];
  readonly _layout: Chart['_layout'];
  _primaryIndex: Chart['_primaryIndex'];
  _runShortcut: Chart['_runShortcut'];
  addPrimitive: Chart['addPrimitive'];
  removePrimitive: Chart['removePrimitive'];
  setIndicatorLegendCollapsed: Chart['setIndicatorLegendCollapsed'];
  removeIndicator: Chart['removeIndicator'];
  movePane: Chart['movePane'];
  setPaneCollapsed: Chart['setPaneCollapsed'];
  paneCollapsed: Chart['paneCollapsed'];
  maximizePane: Chart['maximizePane'];
  invalidate: Chart['invalidate'];
  _emit: Chart['_emit'];
}

export class ChartLegends {
  private readonly _host: LegendsHost;
  private _indicatorLegendToggle: IndicatorLegendToggle | null = null;
  private _indicatorLegendRow = 0;
  /** Where indicator legend rows start inside a pane (see `legendOffset`). */
  public readonly _legendOffset: { top: number; left: number } = { top: 6, left: 8 };

  public constructor(host: LegendsHost) {
    this._host = host;
  }

  public _syncLegendPanes(): void {
    for (const entry of this._host._legends) entry.paneIndex = this._host._panes.findIndex(pane => pane.hasPrimitive(entry.legend));
    this._restackLegends();
  }

  /**
   * Renumber legend rows per pane in insertion order, so removing one closes
   * the gap instead of leaving a hole where it used to sit.
   */
  public _restackLegends(): void {
    const rowByPane = new Map<number, number>();
    const top = this._host._primitives._priceCornerIndex(), count = this._host._indicators.length;
    const leads = new Map<number, PaneLegend>();
    for (const { legend, paneIndex } of this._host._legends) if (this._host._studyLegends.has(legend) && !leads.has(paneIndex)) leads.set(paneIndex, legend);
    // A study pane's first study row carries the pane controls, open or folded,
    // whether a removal, a move or a host row above it made it first, and no
    // other study row does. The price pane's rows never do, in any slot: its
    // rows are on-chart studies, and a row's controls would read as moving or
    // folding that study. On a strip its collapse control is the only way
    // back: the row goes first, above any row the host placed there, and
    // compact rows leave it showing. A strip is one row tall, so a row below
    // it neither draws nor answers the pointer: it would start inside the
    // strip's lower inset.
    const strip = (entry: { legend: PaneLegend; paneIndex: number }): boolean => leads.get(entry.paneIndex) === entry.legend && this._host._layout._collapsedShown(entry.paneIndex);
    // A row offers only what its study's policy lets the user do: no close
    // button on a study the user may not remove, no gear on one they may not
    // configure. The pane controls act on the pane and stay.
    const policies = new Map(this._host._indicators.map(study => [study.legend(), study.policy()]));
    let reserved = false;
    for (const entry of [...this._host._legends.filter(strip), ...this._host._legends.filter(entry => !strip(entry))]) {
      let row = rowByPane.get(entry.paneIndex) ?? 0;
      const owned = this._host._studyLegends.has(entry.legend);
      const folded = owned && this._host._indicatorLegendCollapsed && !strip(entry);
      entry.legend.setSuppressed(folded || row > 0 && this._host._layout._collapsedShown(entry.paneIndex));
      if (count > 0 && entry.paneIndex === top && owned && !reserved) {
        this._indicatorLegendRow = row++;
        reserved = true;
      }
      // A host row left behind on a removed pane is at -1 and has no pane, which the set never holds.
      const pane = this._host._panes[entry.paneIndex];
      const collapsed = (this._host._collapsed as { has(value: typeof pane): boolean }).has(pane);
      if (owned) {
        // A host that rewrote the row since (`legend().setOptions({ actions })`) keeps what it wrote.
        const kept = this._host._legendActions.get(entry.legend), shown = entry.legend.options().actions;
        const base = kept === undefined || kept[1] !== shown ? shown ?? [] : kept[0], policy = policies.get(entry.legend);
        const allowed = base.filter(action => !(action === 'close' && policy?.removable === false)
          && !(action === 'settings' && policy?.configurable === false));
        const actions = leadActions(allowed, pane !== undefined && pane !== this._host._primaryPane && leads.get(entry.paneIndex) === entry.legend);
        entry.legend.setOptions({ row, collapsed, actions });
        this._host._legendActions.set(entry.legend, [base, actions]);
      } else entry.legend.setOptions({ row });
      rowByPane.set(entry.paneIndex, row + (!folded && entry.legend.options().visible !== false ? 1 : 0));
    }
    if (!reserved) this._indicatorLegendRow = rowByPane.get(top) ?? 0;
    if (count > 0 && this._indicatorLegendToggle === null) {
      this._indicatorLegendToggle = new IndicatorLegendToggle();
      this._host.addPrimitive(this._indicatorLegendToggle, { anchor: 'primary-pane' });
    } else if (count === 0 && this._indicatorLegendToggle !== null) {
      const toggle = this._indicatorLegendToggle;
      this._indicatorLegendToggle = null;
      this._host.removePrimitive(toggle);
    }
    this._syncLegendOffsets();
  }

  /**
   * Apply `legendOffset` to the price pane wherever it sits, and to the pane
   * maximized over it while it is hidden, rather than to a fixed index.
   *
   * The offset describes the corner a host covers with its own readout of the
   * price: a symbol line, an OHLC row. That readout belongs to the price pane,
   * so it moves with it when the pane is moved below its studies. Maximizing a
   * study pane hides the price pane, and the maximized pane then renders in
   * the corner the host overlay covers; pinning the offset to one index left
   * it drawing its legend straight through the host's readout.
   *
   * Host-added legend rows are left alone: the host positions its own.
   */
  private _syncLegendOffsets(): void {
    const corner = this._host._primitives._priceCornerIndex(), primary = this._host._primaryIndex();
    const height = paneLegendRowHeight({ iconSize: this._host._legendIconSize });
    const defaultToggleTop = this._legendOffset.top + this._indicatorLegendRow * height;
    let toggleTop = defaultToggleTop;
    for (const entry of this._host._legends) {
      const options = entry.legend.options();
      if (this._host._studyLegends.has(entry.legend) || entry.paneIndex !== corner
        || options.visible === false || (options.row ?? 0) >= this._indicatorLegendRow) continue;
      toggleTop = Math.max(toggleTop, (options.top ?? DEFAULT_LEGEND_TOP) + ((options.row ?? 0) + 1) * paneLegendRowHeight(options));
    }
    for (const entry of this._host._legends) {
      if (!this._host._studyLegends.has(entry.legend)) continue;
      const covered = entry.paneIndex === corner || entry.paneIndex === primary;
      entry.legend.setOptions(
        covered
          ? { top: this._legendOffset.top + (this._indicatorLegendToggle ? toggleTop - defaultToggleTop : 0), left: this._legendOffset.left }
          : { top: DEFAULT_LEGEND_TOP, left: DEFAULT_LEGEND_LEFT },
      );
    }
    this._indicatorLegendToggle?.setOptions({ count: this._host._indicators.length, collapsed: this._host._indicatorLegendCollapsed,
      left: this._legendOffset.left, top: toggleTop, height });
  }

  /**
   * Route a pane-legend button press. Ids look like `indicator:<instanceId>::close`.
   * Returns true when the id was ours and was handled.
   */
  public _handleLegendAction(externalId: string): boolean {
    if (externalId === INDICATOR_LEGEND_TOGGLE) {
      this._host.setIndicatorLegendCollapsed(!this._host._indicatorLegendCollapsed);
      return true;
    }
    const sep = externalId.lastIndexOf('::');
    if (sep < 0) return false;
    const action = externalId.slice(sep + 2);
    // Navigator buttons run the same commands the keyboard does, so the two
    // paths can never drift apart.
    if (this._host._timeNav !== null && externalId.startsWith(`${this._host._timeNav.options().id}::`)) {
      if (this._host._runShortcut(action)) {
        this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
      }
      return true;
    }
    // A host-owned legend row (a symbol/OHLC row) also reveals on hover; swallow
    // its click so it never surfaces as a phantom id.
    if (action === 'row' && !externalId.startsWith('indicator:')) return true;
    if (!externalId.startsWith('indicator:')) return false;
    const instanceId = externalId.slice('indicator:'.length, sep);
    // `::row` is the hover target that reveals the controls, never an action.
    if (action === 'row') return true;
    const indicator = this._host._indicators.find((i) => i.id === instanceId);
    if (indicator === undefined) return false;
    const paneIndex = indicator.paneIndex;
    switch (action) {
      // A press on a button the policy withheld (a stale hit id) does nothing:
      // the user's press is exactly what a policy restricts.
      case 'close':
        this._host.removeIndicator(instanceId);   // prunes its pane if it emptied
        return true;
      case 'hide': indicator.setVisible(!indicator.visible()); return true;
      case 'up': this._host.movePane(paneIndex, -1); return true;
      case 'down': this._host.movePane(paneIndex, 1); return true;
      case 'collapse': this._host.setPaneCollapsed(paneIndex, !this._host.paneCollapsed(paneIndex)); return true;
      case 'maximize': this._host.maximizePane(paneIndex); return true;
      // The engine is canvas-only and ships no DOM, so the settings form is the
      // host's. Everything it needs to *generate* one is on the descriptor
      // (`inputs`), and applying it is `indicator.setSettings(patch)`.
      case 'settings':
        if (indicator.policy().configurable !== false) this._host._emit('indicatorSettings', { instanceId, indicatorId: indicator.indicatorId, paneIndex });
        return true;
      // Same payload as the gear, and for the same reason: the engine holds no
      // code and no DOM, so it says which indicator was asked about and the
      // host decides what to show.
      case 'source':
        this._host._emit('indicatorSource', { instanceId, indicatorId: indicator.indicatorId, paneIndex });
        return true;
      default: return false;
    }
  }

  public _indicatorLegendHit(paneIndex: number, x: number, y: number): boolean {
    return this._indicatorLegendToggle !== null
      && this._host._panes[paneIndex]?.hasPrimitive(this._indicatorLegendToggle) === true
      && this._indicatorLegendToggle.hitTest(x - this._host._leftAxisWidth, y) !== null;
  }
}

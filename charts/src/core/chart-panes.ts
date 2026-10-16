/**
 * The pane stack and its layout: making panes, removing, moving, maximizing
 * and folding them, the share of the chart's height each one gets, the
 * chart-wide price axis columns, the separators between panes, and the
 * boundary a divider drag resizes.
 *
 * Its own module because the layout is one computation that the DOM boxes,
 * the canvases and hit testing all read, and the maximized pane belongs to
 * these methods alone. The chart reaches it through `Chart._layout`, and it
 * reaches the chart through `PanesHost`. `removePane`, `movePane`,
 * `setPrimaryPaneIndex`, `maximizePane` and `setPaneCollapsed` stay public on
 * Chart as delegates and carry the documented contract. `_bottomPaneIndex`
 * and `_paneLayout` stay on Chart as delegates because the chart's own
 * callers and tests read them by name, and `_primaryIndex` stays on Chart
 * whole. Members the chart calls are public on this internal class; no entry
 * point exports the class and the chart holds it in a private field, so none
 * of it reaches the published declarations.
 */
import { InvalidationLevel } from './invalidate-mask';
import type { Chart } from './chart';
import { Pane } from './pane';
import { alignToDevicePixels } from './canvas';
import { DEFAULT_LEGEND_TOP } from './chart-legends';
import type { IndicatorEditOptions } from '../model/indicator-policy';
import { paneLegendRowHeight } from '../primitives/pane-legend';

/**
 * Decimals a pane that does not quote the instrument prints at least.
 *
 * Two, the same floor the percent-rebase branch of `PriceScale.precision`
 * settles on, and for the same reason: a reading a trader compares against a
 * level has to survive the comparison. It applies to every study on a pane of
 * its own, a host's own registered descriptor included, because it is keyed on
 * the pane rather than on anything the descriptor declares.
 */
export const NON_INSTRUMENT_PRECISION = 2;

/**
 * The slice of the chart the pane stack reads, writes and drives. The chart
 * itself is the host: each member carries the name and the type of the chart's
 * own, so the moved code reads as it did in chart.ts, and a member the chart
 * renames or retypes fails to compile here. The writable fields are the
 * chart's own, assigned here.
 */
export interface PanesHost {
  readonly _panes: Chart['_panes'];
  readonly _firstPane: Chart['_firstPane'];
  readonly _pricePanes: Chart['_pricePanes'];
  readonly _collapsed: Chart['_collapsed'];
  readonly _container: Chart['_container'];
  readonly _doc: Chart['_doc'];
  readonly _theme: Chart['_theme'];
  readonly _timeScale: Chart['_timeScale'];
  readonly _dataLayer: Chart['_dataLayer'];
  readonly _pixels: Chart['_pixels'];
  readonly _indicators: Chart['_indicators'];
  readonly _seriesProvenance: Chart['_seriesProvenance'];
  readonly _firstDataId: Chart['_firstDataId'];
  readonly _priceFormatter: Chart['_priceFormatter'];
  readonly _priceScaleOptions: Chart['_priceScaleOptions'];
  readonly _priceAxisWidth: Chart['_priceAxisWidth'];
  readonly _timeAxisHeight: Chart['_timeAxisHeight'];
  readonly _width: Chart['_width'];
  readonly _height: Chart['_height'];
  readonly _legendIconSize: Chart['_legendIconSize'];
  readonly _movablePrimaryPane: Chart['_movablePrimaryPane'];
  readonly _eventMarkers: Chart['_eventMarkers'];
  readonly _destroyed: Chart['_destroyed'];
  readonly _timeNav: Chart['_timeNav'];
  readonly _anchored: Chart['_anchored'];
  _primaryPane: Chart['_primaryPane'];
  _eventPane: Chart['_eventPane'];
  _drawingState: Chart['_drawingState'];
  _layoutRatio: Chart['_layoutRatio'];
  _leftAxisWidth: Chart['_leftAxisWidth'];
  _rightAxisWidth: Chart['_rightAxisWidth'];
  _axisColumnWidth: Chart['_axisColumnWidth'];
  _emptyPriceAxis: Chart['_emptyPriceAxis'];
  /** The chart's other collaborators, whose methods this code calls directly. */
  readonly _scales: Chart['_scales'];
  readonly _legendStack: Chart['_legendStack'];
  readonly _primitives: Chart['_primitives'];
  _pixelRatio: Chart['_pixelRatio'];
  _newBackend: Chart['_newBackend'];
  _primaryIndex: Chart['_primaryIndex'];
  _ensureScaled: Chart['_ensureScaled'];
  _policyAllows: Chart['_policyAllows'];
  _syncTimeNavPane: Chart['_syncTimeNavPane'];
  removePrimitive: Chart['removePrimitive'];
  _paintNow: Chart['_paintNow'];
  applySize: Chart['applySize'];
  movePane: Chart['movePane'];
  invalidate: Chart['invalidate'];
  _emit: Chart['_emit'];
}

export class ChartPanes {
  private readonly _host: PanesHost;
  /** Pane currently maximized, and the weights to restore when it un-maximizes. */
  public _maximizedPane: number | null = null;

  public constructor(host: PanesHost) {
    this._host = host;
  }

  /**
   * A pane whose prices have a place on screen, scaled. A strip has none: the
   * pointer events report no price there, and a conversion that still did
   * would put an overlay or a nudged drawing inside a strip nobody can read.
   */
  public _mappedPane(paneIndex: number): Pane | null {
    this._host._ensureScaled(paneIndex);
    return this._collapsedShown(paneIndex) ? null : this._host._panes[paneIndex] ?? null;
  }

  public _ensurePane(index: number): void {
    // A slot is a whole number of 0 or more. Any other index would add panes up
    // to it and still find none there, so it is refused before anything moves.
    if (!Number.isSafeInteger(index) || index < 0) throw new RangeError('Invalid pane index');
    const added: number[] = [];
    while (this._host._panes.length <= index) {
      // price pane (0) takes full weight; lower panes (volume/indicators) are shorter
      this._addPane(this._host._panes.length === 0 ? 1 : 0.32);
      added.push(this._host._panes.length - 1);
    }
    if (added.length === 0) return;
    this._relayout();
    // Making room resized every pane's canvases, which clears them, and may
    // have moved the time axis to another pane: all of them repaint, not only
    // the pane whatever asked for it goes on to write.
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
    // Panes are made lazily, when an indicator asks for one, and that used to be
    // silent: `paneRemoved` existed with no counterpart. A host with chrome at
    // the bottom of the chart had no way to learn the bottom had moved. Emitted
    // after the relayout so a listener reads settled geometry.
    this._host._primitives._rehomeAnchored();
    for (const paneIndex of added) this._host._emit('paneAdded', { paneIndex });
  }

  public _addPane(weight = 1): Pane {
    const pane = new Pane(this._host._doc, this._host._newBackend());
    pane.weight = weight;
    // The first pane is the primary one and quotes the instrument by
    // construction: it is where `addSeries` puts a series that names no pane,
    // and it exists before any host has said what goes on it. Every later
    // pane is made for an indicator, so it holds its own units until a price
    // series lands on it (`_claimPricePane`), and inherits the chart-wide
    // defaults without the instrument's tick.
    if (this._host._panes.length === 0) {
      this._host._pricePanes.add(pane);
      this._host._primaryPane = pane;
    } else {
      // Independent of whether a host ever declares a tick. Most do not, and an
      // oscillator on a chart with no tick at all still has to print a reading
      // fine enough to compare against its own levels.
      for (const scale of pane.scales()) scale.setOptions({ minPrecision: NON_INSTRUMENT_PRECISION });
    }
    pane.priceScale.setPriceFormatter(this._host._priceFormatter);
    if (this._host._priceScaleOptions) pane.priceScale.setOptions(this._host._scales._scalePatchFor(pane, this._host._priceScaleOptions));
    this._host._panes.push(pane);
    this._host._container.appendChild(pane.element);
    this._host._pixels._observeCanvases(pane, true);
    return pane;
  }

  /**
   * Measure the container once more, a frame after construction.
   *
   * The size read in the constructor is only what the browser has resolved so
   * far. A chart created from a script that runs before the flex/grid layout
   * settles measures a pre-layout box, lays its panes into it, and then hears
   * the *same* stale contentRect from the ResizeObserver in that frame, so
   * nothing corrects it until an unrelated resize: the reported symptom is a
   * large empty band under the chart that a refresh makes go away.
   *
   * Only a real measurement is allowed to win. Zero or absent means a container
   * that is hidden or not in the document yet, and overwriting a size the host
   * applied by hand with that would be a worse bug than the one being fixed;
   * the ResizeObserver still picks such a container up when it appears.
   */
  public _remeasure(): void {
    if (this._host._panes.length === 0) return; // destroyed before the frame ran
    const width = this._host._container.clientWidth;
    const height = this._host._container.clientHeight;
    if (!(width > 0) || !(height > 0)) return;
    this._host.applySize(width, height);
    // Inside an animation frame callback: a frame requested now runs in the
    // next one, after this one has shown the canvases the resize cleared.
    this._host._paintNow();
  }

  /**
   * Distribute height across panes by weight; sync the shared time-scale width.
   *
   * `geometryOnly` sizes the layout arithmetic (pane boxes, scale heights, the
   * time-scale width) and leaves the DOM and the canvases alone. The vector
   * export uses it to paint at a size that is not the screen's and then to put
   * the screen's back, without clearing a canvas or moving a flex box on the
   * way through.
   */
  public _relayout(geometryOnly = false): void {
    this._measureAxisColumns();
    if (!geometryOnly) {
      this._host._syncTimeNavPane();
      // Weights just changed, so the pane at the chart's top may have too.
      this._host._legendStack._restackLegends();
    }
    const dpr = this._host._pixelRatio();
    if (!geometryOnly) this._host._layoutRatio = dpr;
    const layout = this._paneLayout();
    const bottomPane = this._bottomPaneIndex();
    this._host._panes.forEach((pane, paneIndex) => {
      const h = layout[paneIndex]!.height; // the layout has a box for each pane
      if (geometryOnly) pane.setLayoutSize(this._host._width, h);
      else {
        // No share means gone, not merely short: a zero-height box still paints
        // its separator hairline, and its canvases still answer hit tests.
        pane.element.style.display = this._layoutWeight(paneIndex) > 0 ? '' : 'none';
        // The DOM box is given the SAME pixel height the canvas is sized to,
        // rather than a flex ratio. With `flex: w 1 0` the browser distributed the
        // container's *real* height while the canvas used `this._height`, so any
        // drift between the two (a container that resized before the observer
        // fired) silently offset every hit-test from what was drawn: pane
        // boundaries, legend buttons, and crosshair mapping all landed elsewhere.
        // Deriving both from one number makes layout == hit-test by construction.
        pane.element.style.flex = `0 0 ${h}px`;
        pane.resize(this._host._width, h, dpr);
      }
      // Scale height is a layout property (see Pane.setScaleHeights). A strip's
      // scales span the strip, so nothing measured against them reaches below it.
      pane.setScaleHeights(Math.max(0, h - (paneIndex === bottomPane ? this._host._timeAxisHeight : 0)));
    });
    if (!geometryOnly) this._syncSeparators();
    this._host._timeScale.setWidth(Math.max(0, this._host._width - this._host._rightAxisWidth - this._host._leftAxisWidth));
  }

  /**
   * A hairline between stacked panes: on every pane but the one against the
   * chart's top, whole device pixels tall, in the form `Pane.setSeparator`
   * picks for the ratio the panes were laid out at. It sits on the DOM box,
   * so it is exactly on the boundary the user drags.
   */
  public _syncSeparators(): void {
    const ratio = this._ratioForLayout();
    const topPane = this._topPaneIndex();
    this._host._panes.forEach((pane, i) => pane.setSeparator(i === topPane ? null : this._host._theme.paneSeparator, ratio));
  }

  /**
   * The device pixel ratio pane boundaries are rounded at: the one the panes
   * were last laid out at, so hit testing, `priceToCoordinate` and the DOM
   * boxes agree even when the ratio has moved with no event to say so (a
   * scale-only emulation, a browser with neither signal) until the next
   * relayout. Before the first layout, the ratio now.
   */
  public _ratioForLayout(): number {
    return this._host._layoutRatio > 0 ? this._host._layoutRatio : this._host._pixelRatio();
  }

  /**
   * Reserve the chart-wide axis columns: a left one as soon as any pane has a
   * left price scale in use, and the right one unless every scale in use has
   * moved off it. A chart with nothing on any scale keeps its right column,
   * which is where an empty chart's ladder belongs; the columns are chart-wide
   * rather than per pane because the panes share one time axis and their plots
   * have to start and end at the same x.
   */
  public _recomputeAxisColumns(): void {
    const before = [this._host._leftAxisWidth, this._host._rightAxisWidth, this._host._axisColumnWidth];
    this._measureAxisColumns();
    if (before[0] === this._host._leftAxisWidth && before[1] === this._host._rightAxisWidth && before[2] === this._host._axisColumnWidth) return;
    this._relayout();
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
  }

  private _measureAxisColumns(): void {
    let left = 0, right = 0;
    this._host._emptyPriceAxis = !this._host._panes.some(pane => pane.series().length > 0
      || pane.primitives().some(primitive => pane.primitiveScaleId(primitive) !== null));
    for (const pane of this._host._panes) {
      const axes = pane.visibleAxes(this._host._emptyPriceAxis);
      left = Math.max(left, axes.filter(axis => axis.side === 'left').length);
      right = Math.max(right, axes.filter(axis => axis.side === 'right').length);
    }
    this._host._axisColumnWidth = Math.max(0, Math.min(this._host._priceAxisWidth, this._host._width / (left + right + 1)));
    this._host._leftAxisWidth = left * this._host._axisColumnWidth;
    this._host._rightAxisWidth = right * this._host._axisColumnWidth;
  }

  /**
   * The share of the chart a pane gets. While one pane is maximized it takes
   * everything and the rest take nothing, so they lay out at zero height and
   * are hidden outright rather than collapsed to a sliver. A sliver still
   * paints a strip of squeezed candles and a separator hairline above the very
   * pane the user asked to see on its own.
   *
   * Stored weights are never touched, so restoring is exact and `getState`
   * cannot persist a placeholder.
   */
  public _layoutWeight(index: number): number {
    const pane = this._host._panes[index];
    if (pane === undefined) return 0;
    if (this._maximizedPane === null) return pane.weight;
    return index === this._maximizedPane ? 1 : 0;
  }

  /** First pane with a share of the chart: the one that sits against the top edge. */
  public _topPaneIndex(): number {
    for (let i = 0; i < this._host._panes.length; i++) if (this._layoutWeight(i) > 0) return i;
    return 0;
  }

  /**
   * Last pane with a share of the chart: the one that owns the time axis, even
   * as a strip, so the axis stays at the foot of the chart. `open` asks for the
   * last one with a plot instead, which is where chart furniture belongs.
   */
  public _bottomPaneIndex(open = false): number {
    for (let i = this._host._panes.length - 1; i >= 0; i--) if (this._layoutWeight(i) > 0 && !(open && this._collapsedShown(i))) return i;
    return this._host._panes.length - 1;
  }

  /** Drawn as a strip right now: a maximized pane shows whole whatever it is set to. */
  public _collapsedShown(index: number): boolean {
    // Asked of any index: one with no pane is not a strip.
    return this._maximizedPane === null && (this._host._collapsed as { has(value: Pane | undefined): boolean }).has(this._host._panes[index]);
  }

  /** Grab tolerance around a pane boundary, in media px. */
  private static readonly DIVIDER_GRAB = 4;

  /**
   * The two panes a press at `y` resizes, or null. Boundary `i` separates pane
   * `i` from pane `i + 1`; the last pane's bottom is the chart edge and is not
   * draggable. A strip keeps its height, so a boundary beside one moves height
   * between the nearest open panes either side of it. A pane hidden behind a
   * maximized one is never a side: dragging it would rewrite a weight nobody
   * can see.
   */
  public _dividerAt(y: number): [number, number] | null {
    const layout = this._paneLayout();
    const sizable = (i: number): boolean => this._layoutWeight(i) > 0 && !this._collapsedShown(i);
    for (let i = 0; i < layout.length - 1; i++) {
      if (Math.abs(y - layout[i]!.top - layout[i]!.height) > ChartPanes.DIVIDER_GRAB) continue;
      let a = i, b = i + 1;
      while (a >= 0 && !sizable(a)) a--;
      while (b < layout.length && !sizable(b)) b++;
      if (a >= 0 && b < layout.length) return [a, b];
    }
    return null;
  }

  /** The work of `Chart.removePane`, which carries the documented contract. */
  public removePane(index: number, options: IndicatorEditOptions): boolean {
    if (!Number.isInteger(index) || index < 0 || index >= this._host._panes.length || this._host._panes[index] === this._host._primaryPane) return false;
    if (this._host._indicators.some(study => study.paneIndex === index && !this._host._policyAllows(study, 'removable', options))) return false;
    if (this._host._eventPane === index) {
      // The strip goes home to the price pane, before the slots shift.
      const home = this._host._primaryIndex();
      if (this._host._eventMarkers !== null) {
        this._host.removePrimitive(this._host._eventMarkers);
        this._host._primitives._addPrimitive(home, this._host._eventMarkers);
        this._host._emit('events:change', undefined);
      }
      this._host._eventPane = home;
    }
    if (this._host._eventPane > index) this._host._eventPane -= 1;
    // Indicators own their series, so let them tear themselves down first,
    // otherwise their series rows would outlive the pane holding them.
    // Walked from the end, and each pass takes out only the study it removes.
    for (let i = this._host._indicators.length - 1; i >= 0; i--) {
      if (this._host._indicators[i]!.paneIndex !== index) continue;
      const [instance] = this._host._indicators.splice(i, 1);
      instance!.remove({ force: true });
    }
    const pane = this._host._panes[index]!; // an index in range, checked on entry
    for (const record of [...pane.series()]) {
      pane.removeSeries(record);
      this._host._dataLayer.removeSeries(record.dataId);
      this._host._seriesProvenance.delete(record.dataId);
      if (this._host._firstDataId.value === record.dataId) this._host._firstDataId.value = null;
    }
    this._host._pixels._observeCanvases(pane, false);
    pane.destroy();
    this._host._panes.splice(index, 1);
    // Keep the maximize target on the pane it named. Removing the maximized
    // pane leaves nothing maximized; removing one above it shifts it up. Left
    // alone, the index would point at whichever pane inherited the slot and
    // the wrong one would fill the chart.
    if (this._maximizedPane !== null) {
      if (this._maximizedPane === index) this._maximizedPane = null;
      else if (this._maximizedPane > index) this._maximizedPane -= 1;
    }
    // Indicators below the removed pane shift up one.
    for (const indicator of this._host._indicators) {
      if (indicator.paneIndex > index) indicator.shiftPane(-1);
    }
    this._host._timeScale.setBaseIndex(this._host._dataLayer.baseIndex);
    this._recomputeAxisColumns();
    this._relayout();
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
    this._host._primitives._rehomeAnchored();
    this._host._legendStack._syncLegendPanes();
    this._remapSavedDrawings(slot => slot === index ? null : slot > index ? slot - 1 : slot);
    this._host._emit('paneRemoved', { paneIndex: index });
    return true;
  }

  /**
   * Keep the saved drawings' slots in step with a pane that moved or went,
   * for the draw tier that has not loaded yet: it reads them from
   * `drawingState()` whenever it arrives, and a stale slot would put a drawing
   * on the wrong pane or recreate one that is gone. The slot is the draw
   * tier's document and opaque here, so only its pane field is touched, on a
   * copy, and a drawing on a removed pane goes with it, as the tier drops it.
   * A tier that is listening writes its own document right after the event.
   */
  private _remapSavedDrawings(map: (slot: number) => number | null): void {
    const saved = this._host._drawingState as { drawings?: unknown } | unknown[] | null | undefined;
    const list = Array.isArray(saved) ? saved : Array.isArray(saved?.drawings) ? saved.drawings as unknown[] : null;
    if (list === null) return;
    const next = list.flatMap(entry => {
      // An entry without a pane is on pane 0, the way the draw tier reads it.
      const slot = (entry as { paneIndex?: unknown } | null)?.paneIndex ?? 0;
      if (typeof entry !== 'object' || entry === null || !Number.isInteger(slot)) return [entry];
      const to = map(slot as number);
      return to === null ? [] : to === slot ? [entry] : [{ ...entry, paneIndex: to }];
    });
    this._host._drawingState = Array.isArray(saved) ? next : { ...saved, drawings: next };
  }

  /** The work of `Chart.movePane`, which carries the documented contract. */
  public movePane(index: number, direction: -1 | 1): boolean {
    const target = index + direction;
    if ((direction !== -1 && direction !== 1) || !Number.isInteger(index)
      || index < 0 || target < 0 || index >= this._host._panes.length || target >= this._host._panes.length) return false;
    const panes = this._host._panes;
    if (!this._host._movablePrimaryPane && (panes[index] === this._host._primaryPane || panes[target] === this._host._primaryPane)) return false;
    // Before the event, so a drawing tier listening to it writes over this with its own.
    this._remapSavedDrawings(slot => slot === index ? target : slot === target ? index : slot);
    [panes[index], panes[target]] = [panes[target]!, panes[index]!]; // both in range, checked on entry
    if (this._host._eventPane === index) this._host._eventPane = target;
    else if (this._host._eventPane === target) this._host._eventPane = index;
    if (this._host._eventMarkers !== null) this._host._emit('events:change', undefined);
    // The target names a slot, and the two panes just swapped slots.
    if (this._maximizedPane === index) this._maximizedPane = target;
    else if (this._maximizedPane === target) this._maximizedPane = index;
    for (const indicator of this._host._indicators) {
      if (indicator.paneIndex === index) indicator.shiftPane(direction);
      else if (indicator.paneIndex === target) indicator.shiftPane(-direction);
    }
    // Re-append in the new order so the DOM matches the pane array.
    for (const pane of panes) this._host._container.appendChild(pane.element);
    this._relayout();
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
    this._host._primitives._rehomeAnchored();
    this._host._legendStack._syncLegendPanes();
    this._host._emit('paneMoved', { from: index, to: target });
    return true;
  }

  /** The work of `Chart.setPrimaryPaneIndex`, which carries the documented contract. */
  public setPrimaryPaneIndex(index: number): boolean {
    if (this._host._destroyed || !this._host._movablePrimaryPane || !Number.isInteger(index) || index < 0 || index >= this._host._panes.length) return false;
    let at = this._host._primaryIndex();
    if (at === index) return false;
    // A `paneMoved` listener may itself move panes, so the walk follows the
    // pane rather than counting steps, and gives up rather than chase one
    // that keeps moving it back.
    for (let steps = 0; at !== index; steps++) {
      if (steps > 2 * this._host._panes.length || !this._host.movePane(at, index > at ? 1 : -1)) return false;
      at = this._host._primaryIndex();
    }
    return true;
  }

  /** Slot of the pane holding the primary series, the price pane before there is one. */
  public _firstPaneSlot(): number {
    const slot = this._host._firstPane === null ? -1 : this._host._panes.indexOf(this._host._firstPane);
    return slot < 0 ? this._host._primaryIndex() : slot;
  }

  /** The work of `Chart.maximizePane`, which carries the documented contract. */
  public maximizePane(index: number): boolean {
    // A fractional index matches no pane in the layout, which would then hide them all.
    if (!Number.isInteger(index) || index < 0 || index >= this._host._panes.length) return false;
    this._maximizedPane = this._maximizedPane === index ? null : index;
    this._relayout();
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
    // Maximize is the case a host cannot work around: it HIDES the other panes,
    // so chrome pinned to the price pane disappears rather than merely sitting wrong.
    this._host._primitives._rehomeAnchored();
    this._host._emit('paneMaximized', { paneIndex: this._maximizedPane });
    return true;
  }

  /**
   * Whether a pane other than the price pane is left with nothing a user put
   * there: no series, and no primitive but the chart's own furniture (the time
   * navigator, an anchored primitive, which moves to wherever it is anchored).
   * Moving a study away, a failed add and a restore prune such a pane. Removing
   * a study prunes its pane on the series alone, see `ChartStudies._forgetIndicator`.
   */
  public _holdsOnlyFurniture(pane: Pane): boolean {
    return pane !== this._host._primaryPane && pane.series().length === 0
      && pane.primitives().every(primitive => primitive === this._host._timeNav || this._host._anchored.some(entry => entry.primitive === primitive));
  }

  /** The work of `Chart.setPaneCollapsed`, which carries the documented contract. */
  public setPaneCollapsed(index: number, collapsed: boolean): boolean {
    const pane = this._host._panes[index];
    if (!Number.isInteger(index) || pane === undefined || pane === this._host._primaryPane
      || typeof collapsed !== 'boolean' || this._host._collapsed.has(pane) === collapsed) return false;
    if (collapsed) this._host._collapsed.add(pane);
    else this._host._collapsed.delete(pane);
    const ended = collapsed && this._maximizedPane === index;
    if (ended) this._maximizedPane = null;
    this._relayout();
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
    // The lowest open pane may have changed, and the brand mark lives there.
    this._host._primitives._rehomeAnchored();
    if (ended) this._host._emit('paneMaximized', { paneIndex: null });
    this._host._emit('paneCollapsed', { paneIndex: index, collapsed });
    return true;
  }

  /**
   * Cumulative top + height of each pane: the source of truth for the DOM
   * boxes, the canvases and hit-testing alike. A collapsed pane is a fixed
   * strip one legend row tall, with the time axis under it when it is the
   * bottom pane, and the open panes share what is left by weight, so folding
   * one never rewrites a stored weight.
   *
   * Every boundary between panes sits on a device pixel (`alignToDevicePixels`)
   * of the ratio the panes are laid out at (`_ratioForLayout`), so each canvas
   * covers a whole number of device pixels and the separator gets rows of its
   * own. It is done here rather than where the boxes are sized, so hit testing
   * reads the same boxes the DOM shows.
   */
  public _paneLayout(): { top: number; height: number }[] {
    return alignToDevicePixels(this._paneShares(), this._ratioForLayout());
  }

  /** The layout by weight and strip height alone, before device-pixel rounding. */
  private _paneShares(): { top: number; height: number }[] {
    const bottom = this._bottomPaneIndex();
    const strip = paneLegendRowHeight({ iconSize: this._host._legendIconSize }) + 2 * DEFAULT_LEGEND_TOP;
    const strips = this._host._panes.map((_, i) => this._collapsedShown(i) ? strip + (i === bottom ? this._host._timeAxisHeight : 0) : 0);
    let fixed = 0, total = 0;
    strips.forEach((h, i) => { fixed += h; if (!h) total += this._layoutWeight(i); });
    // Strips taller than the chart shrink together rather than overflow it.
    const shrink = fixed > this._host._height ? this._host._height / fixed : 1;
    const free = Math.max(0, this._host._height - fixed);
    let top = 0;
    return strips.map((h, i) => {
      const out = { top, height: h ? h * shrink : total > 0 ? (free * this._layoutWeight(i)) / total : 0 };
      top += out.height;
      return out;
    });
  }
}

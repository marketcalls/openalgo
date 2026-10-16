/**
 * Primitives on the chart and where they paint: attaching one to a pane and
 * detaching it, the chart anchors that re-home furniture as panes come and
 * go, the series band that orders the price source and the studies of a pane
 * with the primitives placed among them, and the event strip the chart owns.
 *
 * Its own module because attaching, stacking and re-homing are one set of
 * rules about which pane a primitive lives on and what it paints after, and
 * the switches the event strip filters by belong to these methods alone. The
 * chart reaches it through `Chart._primitives`, and it reaches the chart
 * through `PrimitivesHost`. The anchored list, the legend rows, the source's
 * placement and the strip itself stay on Chart, because the panes, the
 * studies, the restore and the data context read them too. `seriesStack`,
 * `moveInSeriesStack`, `setPrimitiveStackAbove`, `removePrimitive` and
 * `setEvents` stay public on Chart as delegates and carry the documented
 * contract; the other primitive and event methods keep their bodies there.
 * Members the chart calls are public on this internal class; no entry point
 * exports the class and the chart holds it in a private field, so none of it
 * reaches the published declarations.
 */
import { InvalidationLevel } from './invalidate-mask';
import type { Pane } from './pane';
import type { ChartEventClick, ChartEventOptions } from './chart-types';
import type { Chart, ChartClickEvent } from './chart';
import type { SeriesRecord } from '../model/series';
import type { IndicatorEditOptions } from '../model/indicator-policy';
import type { IPrimitive, PrimitiveHost, PrimitiveAnchor } from '../primitives/primitive';
import { EventMarkers, type ChartEvent } from '../primitives/event-markers';
import { PaneLegend, type PaneLegendOptions } from '../primitives/pane-legend';
import type { LooseOptional } from '../helpers/types';

/**
 * The slice of the chart the primitives, the series band and the event strip
 * read, write and drive. The chart itself is the host: each member carries the
 * name and the type of the chart's own, so the moved code reads as it did in
 * chart.ts, and a member the chart renames or retypes fails to compile here.
 * The writable fields are the chart's own, assigned here.
 */
export interface PrimitivesHost {
  readonly _panes: Chart['_panes'];
  readonly _indicators: Chart['_indicators'];
  readonly _primary: Chart['_primary'];
  readonly _seriesRecords: Chart['_seriesRecords'];
  readonly _seriesOwners: Chart['_seriesOwners'];
  readonly _legends: Chart['_legends'];
  readonly _anchored: Chart['_anchored'];
  readonly _statusLine: Chart['_statusLine'];
  readonly _legendIconSize: Chart['_legendIconSize'];
  readonly isDestroyed: Chart['isDestroyed'];
  readonly hasOpenInterest: Chart['hasOpenInterest'];
  _events: Chart['_events'];
  _eventMarkers: Chart['_eventMarkers'];
  _eventPane: Chart['_eventPane'];
  _sourceAbove: Chart['_sourceAbove'];
  /** The chart's other collaborators, whose methods this code calls directly. */
  readonly _layout: Chart['_layout'];
  readonly _legendStack: Chart['_legendStack'];
  readonly _studies: Chart['_studies'];
  _primaryIndex: Chart['_primaryIndex'];
  _bottomPaneIndex: Chart['_bottomPaneIndex'];
  _paneLayout: Chart['_paneLayout'];
  _policyAllows: Chart['_policyAllows'];
  seriesStack: Chart['seriesStack'];
  removePrimitive: Chart['removePrimitive'];
  invalidate: Chart['invalidate'];
  on: Chart['on'];
  _emit: Chart['_emit'];
}

export class ChartPrimitives {
  private readonly _host: PrimitivesHost;
  public readonly _eventVisible: ChartEventOptions = {};

  public constructor(host: PrimitivesHost) {
    this._host = host;
  }

  public setEvents(events: readonly ChartEvent[], paneIndex?: number): void {
    const markers = this._ensureEventMarkers();
    markers.setEvents(events);
    this._host._events = markers.events();
    const target = paneIndex ?? this._host._primaryIndex();
    if (target !== this._host._eventPane) {
      this._host.removePrimitive(markers);
      this._addPrimitive(target, markers);
    }
    this._host._eventPane = target;
    this._syncEvents();
  }

  public _ensureEventMarkers(): EventMarkers {
    if (this._host._eventMarkers === null) {
      this._host._eventMarkers = new EventMarkers();
      // A strip is born on the price pane wherever that sits; the slot a
      // previous strip was moved to means nothing once there is no strip.
      this._host._eventPane = this._host._primaryIndex();
      this._addPrimitive(this._host._eventPane, this._host._eventMarkers);
      this._host.on('click', payload => {
        const click = payload as ChartClickEvent;
        if (!click.id || click.viaDrag || click.paneIndex !== this._host._eventPane) return;
        const details = this._host._eventMarkers?.detailsForHit(click.id);
        if (details) this._host._emit('event:click', { ...details,
          point: { x: click.point.x, y: click.point.y + (this._host._paneLayout()[click.paneIndex]?.top ?? 0) },
          paneIndex: click.paneIndex } satisfies ChartEventClick);
      });
    }
    return this._host._eventMarkers;
  }

  public _syncEvents(): void {
    if (this._host._eventMarkers === null && this._host._events.length === 0) return;
    const visible = this._eventVisible as Record<string, boolean | undefined>;
    this._ensureEventMarkers().setEvents(this._host._events.filter((e) => visible[e.type] !== false));
    this._host._emit('events:change', undefined);
  }

  public seriesStack(paneIndex: number): string[] {
    const pane = this._host._panes[paneIndex];
    if (pane === undefined) return [];
    const owners = this._stackOwners(pane, paneIndex);
    const out: string[] = [];
    for (const record of pane.series()) {
      const id = owners.get(record);
      if (id !== undefined && !out.includes(id)) out.push(id);
    }
    return out;
  }

  public moveInSeriesStack(id: string, target: string, where: 'above' | 'below', options: IndicatorEditOptions): boolean {
    if (this._host.isDestroyed || id === target || (where !== 'above' && where !== 'below')) return false;
    const study = id.startsWith('indicator:') ? this._host._indicators.find(item => 'indicator:' + item.id === id) : undefined;
    const source = id === 'source:primary' && this._host._primary !== null ? this._host._seriesOwners.get(this._host._primary.api)?.pane : undefined;
    const paneIndex = study ? study.paneIndex : source ? this._host._panes.indexOf(source) : -1;
    const order = paneIndex < 0 ? [] : this._host.seriesStack(paneIndex);
    if (!order.includes(id) || !order.includes(target) || (study && !this._host._policyAllows(study, 'movable', options))) return false;
    const next = order.filter(item => item !== id);
    next.splice(next.indexOf(target) + (where === 'above' ? 1 : 0), 0, id);
    if (next.every((item, i) => item === order[i])) return false;
    // The studies of this pane take their slots in the study list in the new
    // order, which every band of theirs follows; studies elsewhere keep theirs.
    const studies = next.flatMap(item => this._host._indicators.filter(entry => 'indicator:' + entry.id === item));
    const members = new Set(studies);
    // Each slot a member holds takes the next study in order: one study per member slot.
    let k = 0;
    for (let i = 0; i < this._host._indicators.length; i++) if (members.has(this._host._indicators[i]!)) this._host._indicators[i] = studies[k++]!;
    const at = next.indexOf('source:primary');
    if (at >= 0) this._host._sourceAbove = at === 0 ? null : next[at - 1]!.slice('indicator:'.length);
    this._host._studies._reorderIndicatorResources();
    this._host.invalidate(m => m.invalidateGlobal(InvalidationLevel.Full));
    this._host._emit('objects:change', {});
    return true;
  }

  public setPrimitiveStackAbove(primitive: IPrimitive, above: string | null): boolean {
    const index = this._host._panes.findIndex(pane => pane.hasPrimitive(primitive));
    if (index < 0 || (above !== null && typeof above !== 'string')) return false;
    if (this._host._panes[index]!.primitiveStackAbove(primitive) === above) return true; // `index` was found above
    this._host._panes[index]!.setPrimitiveStackAbove(primitive, above);
    this._host.invalidate(m => m.invalidatePane(index, { level: InvalidationLevel.Light, autoScale: false }));
    return true;
  }

  /** Each series of a pane that belongs to one of its series-band entries, with that entry's id. */
  private _stackOwners(pane: Pane, paneIndex: number): Map<SeriesRecord, string> {
    const owners = new Map<SeriesRecord, string>();
    if (this._host._primary !== null && this._host._seriesOwners.get(this._host._primary.api)?.pane === pane) owners.set(this._host._primary.record, 'source:primary');
    for (const study of this._host._indicators) {
      if (study.paneIndex !== paneIndex) continue;
      for (const { api } of study.renderResources().series) {
        const record = this._host._seriesRecords.get(api);
        if (record !== undefined && this._host._seriesOwners.get(api)?.pane === pane) owners.set(record, 'indicator:' + study.id);
      }
    }
    return owners;
  }

  /** The series an entry paints last on a pane: what a primitive placed above it paints after. */
  public _stackSlot(paneIndex: number, entry: string): SeriesRecord | undefined {
    const pane = this._host._panes[paneIndex];
    if (pane === undefined) return undefined;
    const owners = this._stackOwners(pane, paneIndex);
    let last: SeriesRecord | undefined;
    for (const record of pane.series()) if (owners.get(record) === entry) last = record;
    return last;
  }

  /**
   * Put the price source where it was placed: directly above its study, or
   * behind every study of its pane. A source nobody placed stays where it was
   * added. Host series keep their slots, so only the source record moves, and
   * only when it is out of place.
   */
  public _placeSource(): void {
    const placed = this._host._sourceAbove;
    const owner = this._host._primary === null ? undefined : this._host._seriesOwners.get(this._host._primary.api);
    if (placed === undefined || owner === undefined) return;
    const pane = owner.pane, paneIndex = this._host._panes.indexOf(pane), source = this._host._primary!.record;
    const owners = this._stackOwners(pane, paneIndex);
    owners.delete(source);
    const records = pane.series(), at = records.indexOf(source);
    const after = placed === null ? undefined : this._stackSlot(paneIndex, 'indicator:' + placed);
    // A study that is gone leaves the source at the back, and says so when saved.
    if (after === undefined) this._host._sourceAbove = null;
    const from = after === undefined ? -1 : records.indexOf(after);
    const next = records.findIndex((record, i) => i > from && record !== source && owners.has(record));
    if (at > from && (next < 0 || at < next)) return;
    // The least that puts it in place: right after its study, or right before
    // the first study at the back, so a host series beside it keeps its side.
    // With no study to follow, `next` found one: it returned above otherwise.
    pane.moveSeries(source, after === undefined ? records[next]! : records[from + 1] ?? null);
  }

  /**
   * The study directly below the source, read from the band as it stands:
   * how the source keeps its place when the study it sat on leaves the pane.
   */
  public _reanchorSource(): void {
    const pane = this._host._primary === null ? undefined : this._host._seriesOwners.get(this._host._primary.api)?.pane;
    if (typeof this._host._sourceAbove !== 'string' || pane === undefined) return;
    const order = this._host.seriesStack(this._host._panes.indexOf(pane)), at = order.indexOf('source:primary');
    this._host._sourceAbove = at > 0 ? order[at - 1]!.slice('indicator:'.length) : null;
  }

  /** The pane a chart anchor currently resolves to. */
  public _anchorTarget(anchor: PrimitiveAnchor): number {
    if (anchor === 'chart-bottom') return this._host._bottomPaneIndex(true);
    return anchor === 'primary-pane' ? this._priceCornerIndex() : this._host._layout._topPaneIndex();
  }

  /**
   * The pane that wears the price pane's furniture: the primary pane while it
   * is on screen, else the pane at the top, which is the one maximized over
   * it. A host's symbol line and OHLC readout describe the price, so they,
   * the study count, the background text and the legend offset belong with
   * the price pane wherever it sits, and the price pane is hidden only while
   * another pane fills the chart in its place.
   */
  public _priceCornerIndex(): number {
    const primary = this._host._primaryIndex();
    return this._host._layout._layoutWeight(primary) > 0 ? primary : this._host._layout._topPaneIndex();
  }

  /**
   * Move every chart-anchored primitive to the pane its anchor now names.
   *
   * Called after anything that changes which pane sits at an edge or holds the
   * price: a pane added, removed, moved, collapsed or maximized. Maximize matters
   * most and is the case a host cannot easily handle itself: it HIDES the other
   * panes, so a mark pinned to the price pane vanishes with it rather than
   * merely sitting in the wrong place.
   */
  public _rehomeAnchored(): void {
    if (this._host._anchored.length === 0) return;
    for (const entry of this._host._anchored) {
      const target = this._anchorTarget(entry.anchor);
      const current = this._host._panes.findIndex((pane) => pane.hasPrimitive(entry.primitive));
      if (current === target) continue;
      if (current >= 0) this._host._panes[current]!.removePrimitive(entry.primitive);
      // `_addPrimitive` appends a legend row to `_legends`, so re-homing an
      // anchored PaneLegend without dropping its old record would register it
      // once per move and stack it against itself.
      const li = this._host._legends.findIndex((l) => l.legend === entry.primitive);
      if (li >= 0) this._host._legends.splice(li, 1);
      this._addPrimitive(target, entry.primitive);
    }
  }

  public _addPrimitive(paneIndex: number, primitive: IPrimitive): void {
    this._host._layout._ensurePane(paneIndex);
    const host: PrimitiveHost = {
      // A 'top' primitive is drawn only by `Pane.paintTop`, so repainting the
      // base canvas for it is work nothing consumes. That is the difference
      // between a cursor-following overlay costing one overlay repaint and it
      // costing a full series redraw on every mousemove, times every chart in a
      // linked grid. Read per call rather than captured at attach: `zOrder()`
      // is a method, and a primitive is free to change layer.
      requestUpdate: (): void => {
        const index = this._host._panes.findIndex(pane => pane.hasPrimitive(primitive));
        // One placed in the series band paints on the base canvas, whatever its own band.
        const top = primitive.zOrder() === 'top' && this._host._panes[index]?.primitiveStackAbove(primitive) == null;
        this._host.invalidate((m) => m.invalidatePane(index, { level: top ? InvalidationLevel.Cursor : InvalidationLevel.Light, autoScale: false }));
      },
    };
    this._host._panes[paneIndex]!.addPrimitive(primitive, host); // made by `_ensurePane` above, which refuses an index with no slot
    // Track legend rows however they were added: a host can add its own (a
    // symbol/OHLC row) and indicator legends must stack beneath it.
    if (primitive instanceof PaneLegend) {
      this._host._legends.push({ legend: primitive, paneIndex });
      primitive.setOptions({ hasOpenInterest: this._host.hasOpenInterest } satisfies LooseOptional<Partial<PaneLegendOptions>> as Partial<PaneLegendOptions>); // undefined: not known
      // A row added after the switches were set still obeys them; a legend that
      // brought its own `statusLine` keeps whatever it set on top. Skipped when
      // the chart has no switches to push, which is the usual case: `setOptions`
      // asks for a repaint, and asking for one to write an empty object is a
      // frame nobody needed.
      if (Object.keys(this._host._statusLine).length > 0) {
        const own = primitive.options().statusLine;
        primitive.setOptions({ statusLine: { ...this._host._statusLine, ...own } });
      }
      // A chart-wide size also governs host rows so their row heights agree.
      if (this._host._legendIconSize !== undefined) {
        primitive.setOptions({ iconSize: this._host._legendIconSize });
      }
      this._host._legendStack._restackLegends();
    }
    this._host.invalidate((m) => m.invalidatePane(paneIndex, { level: InvalidationLevel.Light, autoScale: false }));
  }

  public removePrimitive(primitive: IPrimitive): void {
    // Drop the anchor registration FIRST. Without this the pane copy goes but
    // the registry entry stays, and the next pane add, remove, move or maximize
    // calls `_rehomeAnchored` and puts the removed primitive back on the chart.
    // A remove that a later unrelated action silently undoes is worse than one
    // that fails loudly.
    const ai = this._host._anchored.findIndex((a) => a.primitive === primitive);
    if (ai >= 0) this._host._anchored.splice(ai, 1);
    const li = this._host._legends.findIndex((l) => l.legend === primitive);
    if (li >= 0) this._host._legends.splice(li, 1);
    for (let i = 0; i < this._host._panes.length; i++) {
      if (this._host._panes[i]!.removePrimitive(primitive)) {
        if (li >= 0) this._host._legendStack._restackLegends();
        this._host._layout._recomputeAxisColumns();
        this._host.invalidate((m) => m.invalidatePane(i, { level: InvalidationLevel.Light, autoScale: false }));
        return;
      }
    }
  }
}

import type { Chart } from '../core/chart';
import type { IndicatorDataStatus } from './indicator-registry';
import type { LooseOptional } from '../helpers/types';

export type ChartObjectKind = 'source' | 'indicator' | 'drawing' | 'profile' | 'group';

/**
 * Where a row paints on its pane, back to front: `below` the series (a drawing
 * sent behind them), in the `series` band (the price source, each study, and a
 * drawing placed directly above one of them), or `above` everything the series
 * band holds (drawings in front, the default).
 */
export type ChartObjectBand = 'below' | 'series' | 'above';

export interface ChartObjectCapabilities {
  readonly select: boolean;
  readonly visibility: boolean;
  readonly lock: boolean;
  readonly remove: boolean;
  readonly settings: boolean;
  readonly focus: boolean;
  readonly reorder?: boolean;
  readonly move?: boolean;
  /** Takes part in its pane's stack and can be moved in it with `place`. */
  readonly place?: boolean;
}

/** One immutable row in a chart's object inventory. */
export interface ChartObjectSnapshot {
  readonly id: string;
  readonly sourceId: string;
  readonly kind: ChartObjectKind;
  readonly name: string;
  readonly paneIndex: number;
  readonly visible: boolean;
  readonly locked?: boolean;
  readonly selected: boolean;
  readonly groupId?: string;
  readonly dataStatus?: Readonly<IndicatorDataStatus>;
  readonly capabilities: ChartObjectCapabilities;
  /** The band it paints in, for a row that is part of its pane's stack (see `stack`). */
  readonly band?: ChartObjectBand;
  /** For a drawing in the series band: the id of the source or study row it paints directly above. */
  readonly stackAbove?: string;
  /**
   * True for a drawing whose interval range leaves out the chart's interval,
   * and for a group all of whose drawings it leaves out: kept and listed so it
   * can be found, but not on the chart. `visible` stays the user's switch.
   */
  readonly hiddenOnInterval?: boolean;
}

/** State supplied by a host for an explicitly managed profile or source. */
export interface ChartObjectDefinition {
  kind: ChartObjectKind;
  name: string;
  /** Slot of the pane it belongs to; omitted means the price pane, wherever it sits. */
  paneIndex?: number;
  visible?: boolean;
  locked?: boolean;
  selected?: boolean;
  groupId?: string | undefined;
  dataStatus?: Readonly<IndicatorDataStatus> | undefined;
  /** Kept but not on the chart at its current interval; see `ChartObjectSnapshot.hiddenOnInterval`. */
  hiddenOnInterval?: boolean;
}

/** Actions are synchronous and offered only when their callback exists. */
export interface ChartObjectProvider {
  id: string;
  get(): ChartObjectDefinition | null;
  subscribe?(listener: () => void): () => void;
  select?(): void;
  setVisible?(visible: boolean): void;
  setLocked?(locked: boolean): void;
  remove?(): void;
  openSettings?(): void;
  focus?(): void;
  reorder?(direction: -1 | 1): boolean;
  move?(paneIndex: number): boolean;
}

/** Structural contract keeps the base tier independent of drawing code. */
export interface ChartObjectDrawing {
  id: string;
  tool: string;
  paneIndex: number;
  points: readonly { time: number; price: number }[];
  visible?: boolean;
  locked?: boolean;
  zIndex?: number;
  /** The source or study it paints directly above, when it is placed in the series band. */
  stackAbove?: string;
  /**
   * The drawing tier's policy flags the inventory honours: `listed` false
   * leaves the drawing out, `selectable` false withholds select, and
   * `editable` false withholds hide, lock and remove.
   */
  policy?: { readonly selectable?: boolean; readonly editable?: boolean; readonly listed?: boolean };
}

export interface ChartObjectDrawingGroup {
  id: string;
  name: string;
  members: readonly string[];
}

export interface ChartObjectDrawingSource {
  drawings(): readonly ChartObjectDrawing[];
  get(id: string): ChartObjectDrawing | undefined;
  selection(): readonly string[];
  select(id: string | readonly string[] | null, additive?: boolean): void;
  update(id: string, patch: { visible?: boolean; locked?: boolean }): void;
  remove(id: string): boolean;
  /** Delete several as one undo step; a group row holding an unlisted drawing needs it to offer remove. */
  removeMany?(ids: readonly string[]): void;
  reorder?(id: string, direction: -1 | 1): boolean;
  /**
   * Move a drawing directly above or below another drawing or a series-band
   * entry of its pane, as one undo step. Without it drawings cannot be placed.
   */
  placeInStack?(id: string, target: { drawing: string } | { entry: string }, where: 'above' | 'below'): boolean;
  groups?(): readonly ChartObjectDrawingGroup[];
  createGroup?(name: string, ids: readonly string[]): ChartObjectDrawingGroup | null;
  renameGroup?(id: string, name: string): boolean;
  removeGroup?(id: string, removeDrawings?: boolean): boolean;
  updateMany?(patches: ReadonlyArray<{ id: string; patch: { visible?: boolean; locked?: boolean } }>): void;
  /**
   * The ids of the drawings the chart's interval leaves off the chart. Each
   * one's row is marked `hiddenOnInterval` and offers no focus, which would
   * bring into view a place where nothing is drawn. Asked once per refresh,
   * as a list, so a large inventory costs one pass rather than a lookup per
   * row. Without it every drawing is shown.
   */
  hiddenOnInterval?(): readonly string[];
}

export interface ChartObjectsOptions {
  drawings?: ChartObjectDrawingSource;
  /** Opens the host's existing editor for a built-in object. */
  onSettings?(object: ChartObjectSnapshot): void;
  /**
   * A drawing row's name from its tool id, such as the draw registry's
   * display name. This tier cannot read that registry, so without it the
   * row is named from the id ("Trend line"). Since 2.5.10.
   */
  drawingName?(tool: string): string;
}

type Actions = Pick<ChartObjectProvider, 'select' | 'setVisible' | 'setLocked' | 'remove' | 'openSettings' | 'focus' | 'reorder' | 'move'>
  & { ungroup?(): boolean; place?(target: string, where: 'above' | 'below'): boolean };
interface Entry { row: ChartObjectSnapshot; actions: Actions }
interface Registration { provider: ChartObjectProvider; off?: (() => void) | undefined }
const EMPTY: readonly ChartObjectSnapshot[] = Object.freeze([]);
const sameRows = (a: readonly ChartObjectSnapshot[], b: readonly ChartObjectSnapshot[]): boolean =>
  a.length === b.length && a.every((x, i) => {
    const y = b[i]!; // the lengths match
    return x.id === y.id && x.name === y.name && x.kind === y.kind && x.paneIndex === y.paneIndex
      && x.band === y.band && x.stackAbove === y.stackAbove && x.hiddenOnInterval === y.hiddenOnInterval
      && x.visible === y.visible && x.locked === y.locked && x.selected === y.selected && x.groupId === y.groupId
      && x.dataStatus?.state === y.dataStatus?.state
      && (x.dataStatus?.state !== 'error' || (y.dataStatus?.state === 'error' && x.dataStatus.error === y.dataStatus.error))
      && (Object.keys(x.capabilities) as (keyof ChartObjectCapabilities)[])
        .every(key => x.capabilities[key] === y.capabilities[key]);
  });

/** Shared object operations for widgets and custom terminals. No DOM is created. */
export class ChartObjects {
  private readonly _chart: Chart;
  private readonly _options: ChartObjectsOptions;
  private readonly _off: (() => void)[] = [];
  private readonly _providers = new Map<string, Registration>();
  private readonly _listeners = new Set<(objects: readonly ChartObjectSnapshot[]) => void>();
  private _entries = new Map<string, Entry>();
  /** Each drawing row's place among the drawings of its slot: its z-index, then its list position. */
  private _order = new Map<string, readonly [number, number]>();
  /**
   * The draw order the rows were last published with. A restack changes no
   * row, only the order `stack` reads, and a panel listing that order still
   * has to hear of it.
   */
  private _stackKey = '';
  private _publishedStackKey = '';
  private _rows = EMPTY;
  private _selected: string | null = null;
  private _destroyed = false;
  private _refreshing = false;
  private _pending = false;

  public constructor(chart: Chart, options: ChartObjectsOptions = {}) {
    this._chart = chart;
    this._options = options;
    if (chart.isDestroyed) { this._destroyed = true; return; }
    for (const event of ['objects:change', 'indicatorRemoved', 'paneRemoved', 'paneMoved',
      'paneAdded', 'data:context', 'indicator:data-status', 'drawing:change', 'drawing:select'] as const) {
      this._off.push(chart.on(event, () => this.refresh()));
    }
    let hasData = chart.dataLayer.length > 0;
    this._off.push(chart.on('data:range', () => {
      const next = chart.dataLayer.length > 0;
      if (next === hasData) return;
      hasData = next;
      this.refresh();
    }));
    this._off.push(chart.on('destroy', () => this.destroy()));
    this.refresh();
  }

  /** Current immutable inventory, also refreshed for hosts with unsignalled provider state. */
  public list(): readonly ChartObjectSnapshot[] { if (!this._refreshing) this.refresh(); return this._rows; }
  public get(id: string): ChartObjectSnapshot | undefined { if (!this._refreshing) this.refresh(); return this._entries.get(id)?.row; }

  /** Delivers current state immediately, then only inventory changes. */
  public subscribe(listener: (objects: readonly ChartObjectSnapshot[]) => void): () => void {
    this.refresh();
    if (!this._destroyed) this._listeners.add(listener);
    try { listener(this._rows); } catch { /* An observer cannot interrupt chart ownership. */ }
    return () => { this._listeners.delete(listener); };
  }

  /** Provider IDs receive a custom: prefix and cannot replace built-in objects. */
  public register(provider: ChartObjectProvider): () => void {
    if (this._destroyed) return () => {};
    if (typeof provider.id !== 'string' || provider.id.trim() === '') throw new Error('An object provider needs an id');
    const id = 'custom:' + provider.id;
    if (this._providers.has(id)) throw new Error('Object provider already registered: ' + provider.id);
    const registration: Registration = { provider };
    this._providers.set(id, registration);
    try { registration.off = provider.subscribe?.(() => this.refresh()); }
    catch (error) {
      if (this._providers.get(id) === registration) this._providers.delete(id);
      this.refresh();
      throw error;
    }
    // A synchronous provider notification may destroy this inventory while subscribing.
    if (this._destroyed || this._providers.get(id) !== registration) {
      try { registration.off?.(); } catch { /* Continue releasing the registration. */ }
      return () => {};
    }
    this.refresh();
    return () => {
      if (this._providers.get(id) !== registration) return;
      this._providers.delete(id);
      try { registration.off?.(); } catch { /* One provider cannot retain its peers. */ }
      this.refresh();
    };
  }

  /** Re-read explicitly registered host state without installing a polling timer. */
  public refresh(): void {
    if (this._destroyed) return;
    if (this._refreshing) { this._pending = true; return; }
    this._refreshing = true;
    try {
      do {
        this._pending = false;
        const entries = this._read();
        if (this._destroyed) break;
        this._entries = entries;
        if (this._selected !== null && !entries.has(this._selected)) this._selected = null;
        const rows = Object.freeze([...entries.values()].map(entry => entry.row));
        if (sameRows(rows, this._rows) && this._stackKey === this._publishedStackKey) continue;
        this._rows = rows;
        this._publishedStackKey = this._stackKey;
        for (const listener of [...this._listeners]) {
          if (this._destroyed) break;
          try { listener(rows); } catch { /* Other observers still receive the state. */ }
        }
      } while (this._pending && !this._destroyed);
    } finally { this._refreshing = false; }
  }

  public select(id: string | null, additive = false): boolean {
    if (this._destroyed) return false;
    if (id === null) {
      this._selected = null;
      this._options.drawings?.select(null);
      this.refresh();
      return true;
    }
    const row = this.get(id);
    if (!row?.capabilities.select) return false;
    try {
      this._selected = row.kind === 'drawing' ? null : id;
      if (id.startsWith('drawing:')) this._options.drawings?.select(row.sourceId, additive);
      else {
        this._options.drawings?.select(null);
        this._entries.get(id)?.actions.select?.();
      }
      this.refresh();
      return true;
    } catch { this.refresh(); return false; }
  }

  /** Pane targets include one new pane after the current stack. */
  public paneCount(): number { return this._chart.panes().length; }

  /** The price pane's slot among the targets, so a list can name it wherever it sits. */
  public primaryPaneIndex(): number { return this._chart.primaryPaneIndex(); }

  public canReorder(id: string, direction: -1 | 1): boolean {
    const row = this.get(id);
    if (!row?.capabilities.reorder || (direction !== -1 && direction !== 1)) return false;
    if (this._providers.has(id)) return true;
    const drawing = row.kind === 'drawing' ? this._options.drawings?.get(row.sourceId) : undefined;
    const peers = this._rows.filter(item => item.kind === row.kind && item.paneIndex === row.paneIndex
      && (drawing === undefined || ((this._options.drawings?.get(item.sourceId)?.zIndex ?? 0) < 0) === ((drawing.zIndex ?? 0) < 0)));
    const index = peers.findIndex(item => item.id === id) + direction;
    return index >= 0 && index < peers.length;
  }

  public reorder(id: string, direction: -1 | 1): boolean {
    if (!this.get(id)?.capabilities.reorder || this._destroyed) return false;
    try { const result = this._entries.get(id)?.actions.reorder?.(direction) === true; this.refresh(); return result; }
    catch { this.refresh(); return false; }
  }

  public move(id: string, paneIndex: number): boolean {
    if (!this.get(id)?.capabilities.move || this._destroyed) return false;
    try { const result = this._entries.get(id)?.actions.move?.(paneIndex) === true; this.refresh(); return result; }
    catch { this.refresh(); return false; }
  }

  /**
   * A pane's stack in paint order, back to front: drawings behind the series,
   * then each series-band entry (the price source, each study) followed by
   * the drawings placed directly above it, then the drawings in front. Group
   * rows, profiles and other rows outside the stack are not in it.
   */
  public stack(paneIndex: number): readonly ChartObjectSnapshot[] {
    if (!this._refreshing) this.refresh();
    return this._stackOf(paneIndex);
  }

  /** Whether `place` would move `id` and paint the result. */
  public canPlace(id: string, targetId: string, where: 'above' | 'below'): boolean {
    return this._plan(id, targetId, where) !== null;
  }

  /**
   * Move a row directly above or below another row of its pane's stack. A
   * drawing goes anywhere in its pane: next to a drawing it joins that
   * drawing's slot, above an entry it is placed on that entry, below one it
   * goes on top of the slot under it. A source or study moves between whole
   * slots, taking the drawings placed on it along, since nothing can paint
   * between an entry and a drawing placed on it: such a move, one out of the
   * series band, and one across panes are refused, not approximated.
   */
  public place(id: string, targetId: string, where: 'above' | 'below'): boolean {
    const run = this._plan(id, targetId, where);
    if (run === null) return false;
    try { const result = run(); this.refresh(); return result; }
    catch { this.refresh(); return false; }
  }

  private _stackOf(paneIndex: number): ChartObjectSnapshot[] {
    const rows = this._rows.filter(row => row.paneIndex === paneIndex && row.band !== undefined);
    const drawings = (band: ChartObjectBand, above?: string): ChartObjectSnapshot[] => rows
      .filter(row => row.kind === 'drawing' && row.band === band && row.stackAbove === above)
      .sort((a, b) => { const x = this._order.get(a.id)!, y = this._order.get(b.id)!; return x[0] - y[0] || x[1] - y[1]; });
    const out = drawings('below');
    for (const entry of this._chart.seriesStack(paneIndex)) {
      const row = rows.find(item => item.id === entry && item.kind !== 'drawing');
      if (row) out.push(row);
      out.push(...drawings('series', entry));
    }
    return [...out, ...drawings('above')];
  }

  /** The move `place` would make, or null for one it refuses or that changes nothing. */
  private _plan(id: string, targetId: string, where: 'above' | 'below'): (() => boolean) | null {
    if (this._destroyed || id === targetId || (where !== 'above' && where !== 'below')) return null;
    const row = this.get(id), target = this.get(targetId);
    if (!row?.capabilities.place || !target || row.paneIndex !== target.paneIndex) return null;
    // By id: `get` reads the latest refresh, the stack the rows it kept.
    const stack = this._stackOf(row.paneIndex), at = stack.findIndex(item => item.id === id), to = stack.findIndex(item => item.id === targetId);
    if (at < 0 || to < 0) return null;
    const slot = (item: ChartObjectSnapshot): string => item.band === 'series' ? 'series:' + item.stackAbove : item.band!;
    if (row.kind === 'drawing') {
      const draw = this._options.drawings!;
      if (target.kind === 'drawing') {
        if (slot(row) === slot(target) && at === to + (where === 'above' ? 1 : -1)) return null;
        return () => draw.placeInStack!(row.sourceId, { drawing: target.sourceId }, where);
      }
      if (where === 'above' ? row.stackAbove === target.id && at === to + 1 : at === to - 1) return null;
      return () => draw.placeInStack!(row.sourceId, { entry: target.id }, where);
    }
    // An entry lands only on a boundary between slots.
    const entries = this._chart.seriesStack(row.paneIndex);
    const next = stack[to + 1], previous = stack[to - 1];
    let anchor: string | undefined, side = where;
    if (target.kind !== 'drawing') {
      // Not between an entry and a drawing placed on it.
      if (where === 'below' || !(next?.kind === 'drawing' && next.stackAbove === target.id)) anchor = target.id;
    } else if (target.band === 'series' && where === 'above' && (next === undefined || slot(next) !== slot(target))) {
      anchor = target.stackAbove;
    } else if (target.band === 'below' && where === 'above' && next?.band !== 'below') {
      [anchor, side] = [entries[0], 'below'];
    } else if (target.band === 'above' && where === 'below' && previous?.band !== 'above') {
      [anchor, side] = [entries[entries.length - 1], 'above'];
    }
    if (anchor === undefined || anchor === id || !entries.includes(anchor)) return null;
    const order = entries.filter(item => item !== id);
    order.splice(order.indexOf(anchor) + (side === 'above' ? 1 : 0), 0, id);
    if (order.every((item, i) => item === entries[i])) return null;
    const [a, s] = [anchor, side];
    return () => this._entries.get(id)?.actions.place?.(a, s) === true;
  }

  public canGroup(): boolean { return !this._destroyed && typeof this._options.drawings?.createGroup === 'function'; }

  /** Accept inventory ids so callers never need to strip provider prefixes. */
  public createGroup(name: string, ids: readonly string[]): string | null {
    if (!this.canGroup()) return null;
    const members = ids.flatMap(id => {
      const row = this.get(id);
      return row?.kind === 'drawing' && id === 'drawing:' + row.sourceId ? [row.sourceId] : [];
    });
    const group = this._options.drawings!.createGroup!(name, members);
    this.refresh();
    return group ? 'group:' + group.id : null;
  }

  public renameGroup(id: string, name: string): boolean {
    const row = this.get(id);
    if (this._destroyed || row?.kind !== 'group' || id !== 'group:' + row.sourceId) return false;
    const result = this._options.drawings?.renameGroup?.(row.sourceId, name) === true;
    this.refresh();
    return result;
  }

  public ungroup(id: string): boolean {
    const ungroup = this._destroyed ? undefined : this._entries.get(id)?.actions.ungroup;
    if (!ungroup) return false;
    const result = ungroup();
    this.refresh();
    return result;
  }

  public setVisible(id: string, on: boolean): boolean { return this._act(id, 'visibility', a => a.setVisible!(on)); }
  public setLocked(id: string, on: boolean): boolean { return this._act(id, 'lock', a => a.setLocked!(on)); }
  public remove(id: string): boolean { return this._act(id, 'remove', a => a.remove!()); }
  public openSettings(id: string): boolean { return this._act(id, 'settings', a => a.openSettings!()); }
  public focus(id: string): boolean { return this._act(id, 'focus', a => a.focus!()); }

  private _act(id: string, capability: keyof ChartObjectCapabilities, run: (actions: Actions) => void): boolean {
    const row = this.get(id);
    if (this._destroyed || !row?.capabilities[capability]) return false;
    try { run(this._entries.get(id)!.actions); this.refresh(); return true; }
    catch { this.refresh(); return false; }
  }

  private _read(): Map<string, Entry> {
    const rows = new Map<string, Entry>();
    const order = new Map<string, readonly [number, number]>();
    const draw = this._options.drawings;
    const selected = draw?.selection() ?? [];
    if (selected.length > 0) this._selected = null;
    const add = (id: string, sourceId: string, state: ChartObjectDefinition, actions: Actions,
      band?: ChartObjectBand, stackAbove?: string): void => {
      const capabilities = Object.freeze({
        select: typeof actions.select === 'function', visibility: typeof actions.setVisible === 'function',
        lock: typeof actions.setLocked === 'function', remove: typeof actions.remove === 'function',
        settings: typeof actions.openSettings === 'function', focus: typeof actions.focus === 'function',
        reorder: typeof actions.reorder === 'function', move: typeof actions.move === 'function',
        // A host provider's own `place` is not part of the stack contract.
        place: typeof actions.place === 'function' && !id.startsWith('custom:'),
      });
      const row: ChartObjectSnapshot = Object.freeze({
        id, sourceId, kind: state.kind, name: state.name, paneIndex: state.paneIndex ?? this._chart.primaryPaneIndex(),
        visible: state.visible !== false, locked: state.locked, groupId: state.groupId, selected: state.selected === true || this._selected === id,
        dataStatus: state.dataStatus ? Object.freeze({ ...state.dataStatus }) : undefined, capabilities,
        ...(band === undefined ? {} : { band }), ...(stackAbove === undefined ? {} : { stackAbove }),
        ...(state.hiddenOnInterval === true ? { hiddenOnInterval: true } : {}),
      } satisfies LooseOptional<ChartObjectSnapshot> as ChartObjectSnapshot); // an unset `locked`, `groupId` or `dataStatus` goes as undefined, read as absent
      rows.set(id, { row, actions });
    };
    const settings = (id: string): Pick<Actions, 'openSettings'> => this._options.onSettings
      ? { openSettings: () => { const row = this.get(id); if (row) this._options.onSettings!(row); } } : {};
    const chart = this._chart;
    // The series band of each pane that has one, read once per refresh.
    const stacks = new Map<number, string[]>();
    const entries = (paneIndex: number): string[] => {
      let list = stacks.get(paneIndex);
      if (!list) stacks.set(paneIndex, list = chart.seriesStack(paneIndex));
      return list;
    };
    const place = (id: string): Pick<Actions, 'place'> =>
      ({ place: (target, where) => chart.moveInSeriesStack(id, target, where) });
    if (chart.primarySeries() !== null) {
      const context = chart.getDataContext();
      const inBand = entries(chart.primaryPaneIndex()).includes('source:primary');
      add('source:primary', 'primary', {
        kind: 'source', name: context?.symbol || 'Price',
        visible: chart.primarySeriesInfo()?.style.visible !== false,
      }, { ...settings('source:primary'), ...(inBand ? place('source:primary') : {}) }, inBand ? 'series' : undefined);
    }
    for (const indicator of chart.indicators()) {
      // Each flag withholds the actions that would do what it forbids; an
      // unlisted study has no row, so nothing here reaches it.
      const policy = indicator.policy();
      if (policy.listed === false) continue;
      const id = 'indicator:' + indicator.id;
      const inBand = entries(indicator.paneIndex).includes(id);
      add(id, indicator.id, {
        kind: 'indicator', name: indicator.name, paneIndex: indicator.paneIndex,
        visible: indicator.visible(), dataStatus: indicator.dataStatus() ?? undefined,
      }, {
        select: () => {}, setVisible: on => indicator.setVisible(on),
        ...(policy.movable !== false ? {
          reorder: (direction: -1 | 1) => chart.reorderIndicator(indicator.id, direction),
          move: (paneIndex: number) => chart.moveIndicator(indicator.id, paneIndex),
          ...(inBand ? place(id) : {}),
        } : {}),
        ...(policy.removable !== false ? { remove: () => { chart.removeIndicator(indicator.id); } } : {}),
        ...(policy.configurable !== false ? settings(id) : {}),
      }, inBand ? 'series' : undefined);
    }
    if (draw) {
      // An unlisted drawing is not in the inventory at all, so no row, group
      // or group-wide action reaches it from here.
      const listed = (drawing: ChartObjectDrawing): boolean => drawing.policy?.listed !== false;
      const hidden = new Set(draw.hiddenOnInterval?.() ?? []);
      const offInterval = (drawing: ChartObjectDrawing): boolean => hidden.has(drawing.id);
      const membership = new Map<string, string>();
      for (const group of draw.groups?.() ?? []) {
        // A member the source no longer holds is skipped, as it always was.
        const found = group.members.flatMap(id => { const drawing = draw.get(id); return drawing ? [drawing] : []; });
        // Typed non-empty for the reads below, which the check on the next line guards.
        const members = found.filter(listed) as [ChartObjectDrawing, ...ChartObjectDrawing[]];
        if (!members.length) continue;
        const id = 'group:' + group.id;
        for (const member of members) membership.set(member.id, id);
        const patch = (value: { visible?: boolean; locked?: boolean }): void => {
          if (draw.updateMany) draw.updateMany(members.map(member => ({ id: member.id, patch: value })));
          else for (const member of members) draw.update(member.id, value);
        };
        const pickable = members.filter(member => member.policy?.selectable !== false);
        // Removing or dissolving the whole group would reach its unlisted
        // members too, so a group holding one removes just the members
        // listed here, and is not ungrouped from here at all.
        const whole = members.length === found.length;
        const remove = whole ? draw.removeGroup && (() => { draw.removeGroup!(group.id, true); })
          : draw.removeMany && (() => { draw.removeMany!(members.map(member => member.id)); });
        add(id, group.id, { kind: 'group', name: group.name, paneIndex: members[0].paneIndex,
          visible: members.some(member => member.visible !== false), locked: members.every(member => member.locked === true),
          selected: pickable.length > 0 && pickable.every(member => selected.includes(member.id)),
          hiddenOnInterval: members.every(offInterval),
        }, {
          ...(pickable.length ? { select: () => draw.select(pickable.map(member => member.id)) } : {}),
          ...(whole && draw.removeGroup ? { ungroup: () => draw.removeGroup!(group.id, false) === true } : {}),
          // A group-wide switch that skipped a read-only member would leave
          // the group half done, so a group holding one offers none.
          ...(members.every(member => member.policy?.editable !== false) ? {
            setVisible: (visible: boolean) => patch({ visible }), setLocked: (locked: boolean) => patch({ locked }),
            ...(remove ? { remove } : {}),
          } : {}),
        });
      }
      const positions = new Map(draw.drawings().map((drawing, index) => [drawing.id, index]));
      for (const drawing of [...draw.drawings()].filter(listed).sort((a, b) => (a.zIndex ?? 0) - (b.zIndex ?? 0))) {
        const id = 'drawing:' + drawing.id;
        // The slot it paints in: over the entry it names while that entry is
        // in its pane's series band, else the side of the series its z-index gives.
        const above = drawing.stackAbove !== undefined && entries(drawing.paneIndex).includes(drawing.stackAbove) ? drawing.stackAbove : undefined;
        const band: ChartObjectBand = above !== undefined ? 'series' : (drawing.zIndex ?? 0) < 0 ? 'below' : 'above';
        order.set(id, [drawing.zIndex ?? 0, positions.get(drawing.id) ?? 0]);
        const hiddenOnInterval = offInterval(drawing);
        const canFocus = !hiddenOnInterval && chart.dataLayer.length > 0 && drawing.points.length > 0
          && drawing.points.every(p => Number.isFinite(p.time) && Number.isFinite(p.price))
          && chart.panes()[drawing.paneIndex] !== undefined;
        add(id, drawing.id, {
          kind: 'drawing', groupId: membership.get(drawing.id), name: this._options.drawingName?.(drawing.tool) ?? drawing.tool.replace(/-/g, ' ').replace(/^./, c => c.toUpperCase()),
          paneIndex: drawing.paneIndex, visible: drawing.visible !== false,
          locked: drawing.locked === true, selected: selected.includes(drawing.id), hiddenOnInterval,
        }, {
          ...(draw.reorder ? { reorder: (direction: -1 | 1) => draw.reorder!(drawing.id, direction) } : {}),
          ...(draw.placeInStack ? { place: () => false } : {}),
          ...(drawing.policy?.selectable !== false ? { select: () => draw.select(drawing.id) } : {}),
          ...(drawing.policy?.editable !== false ? {
            setVisible: (on: boolean) => draw.update(drawing.id, { visible: on }),
            setLocked: (on: boolean) => draw.update(drawing.id, { locked: on }), remove: () => { draw.remove(drawing.id); },
          } : {}),
          ...(canFocus ? { focus: () => this._focusDrawing(drawing) } : {}), ...settings(id),
        }, band, above);
      }
    }
    for (const [id, { provider }] of this._providers) {
      try {
        const state = provider.get();
        if (!state || typeof state.name !== 'string'
          || !['source', 'indicator', 'drawing', 'profile', 'group'].includes(state.kind)) continue;
        add(id, provider.id, state, provider);
      } catch { /* A failing optional provider cannot hide usable chart objects. */ }
    }
    this._order = order;
    this._stackKey = JSON.stringify([[...stacks], [...order]]);
    return rows;
  }

  private _focusDrawing(drawing: ChartObjectDrawing): void {
    const chart = this._chart;
    const indices = drawing.points.map(point => chart.dataLayer.timeToIndexFloat(point.time));
    if (!indices.every(Number.isFinite)) return;
    const from = Math.min(...indices);
    const to = Math.max(...indices);
    const current = chart.getVisibleLogicalRange();
    const span = Math.max(current.to - current.from, (to - from) * 1.2, 10);
    // `_act` refreshes first, and a row offers focus only while its pane is there.
    const scale = chart.panes()[drawing.paneIndex]!.readoutScale();
    const prices = drawing.points.map(point => point.price);
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const pad = Math.max((max - min) * 0.15, Math.abs(max) * 0.001, scale.options.minMove);
    scale.setAutoScale(false);
    scale.setPriceRange({ min: min - pad, max: max + pad });
    const maximized = chart.maximizedPane();
    if (maximized !== null && maximized !== drawing.paneIndex) chart.maximizePane(maximized);
    // A strip draws nothing, so focusing a drawing on one opens its pane.
    chart.setPaneCollapsed(drawing.paneIndex, false);
    chart.setVisibleLogicalRange({ from: (from + to - span) / 2, to: (from + to + span) / 2 });
  }

  /** Detach this observer and its providers, leaving chart objects in place. */
  public destroy(): void {
    if (this._destroyed) return;
    this._destroyed = true;
    for (const off of this._off.splice(0)) off();
    const providers = [...this._providers.values()];
    this._providers.clear();
    this._entries.clear();
    this._rows = EMPTY;
    this._selected = null;
    for (const { off } of providers) {
      try { off?.(); } catch { /* Continue releasing other providers. */ }
    }
    const listeners = [...this._listeners];
    this._listeners.clear();
    for (const listener of listeners) {
      try { listener(EMPTY); } catch { /* Destruction must finish for every observer. */ }
    }
  }
}

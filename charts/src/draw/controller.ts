/**
 * Drawing controller: the interaction and persistence layer over
 * `DrawingLayer`. It is **headless**: no DOM, no toolbar. A host sets the
 * active tool (from its own button, a shortcut, a command palette) and the
 * controller runs placement, selection, dragging, undo, and serialisation.
 *
 * It listens on the chart's event bus (`click`, `crosshair:move`, `drag`,
 * `drag:end`) rather than `subscribeClick`/`subscribeDrag`, which stay the
 * host's for its own order lines.
 *
 * Selection is a list. Every method that edits takes the whole list into one
 * undo entry, so a multi-drag, a batch delete or a paste of ten shapes is one
 * Ctrl+Z, which is what the hand that did it expects.
 */
// Shared types come from the package entry, not a relative path: each tier
// bundles its own .d.ts, so a relative import gets *inlined* as a second
// declaration. Classes with private members are nominal, so that second copy
// is a different type, and a consumer passing the real one got "separate
// declarations of a private property". The entry is external to tier builds,
// so this survives as `from 'openalgo-charts'` and stays one identity.
import type { AlertDrawingValue, AlertDrawingInfo } from 'openalgo-charts';
import type {
  Drawing, DrawingInput, DrawingPatch, DrawingPoint, DrawingPolicy, DrawingStyle, DrawingTool, DrawingsDocument,
  MagnetMode, ScreenPoint, DrawingGroup, DrawingSpace, DrawingStackTarget,
} from './types';
import type {
  DrawingChartHost, DrawingControllerOptions, DrawingGestureOptions, DrawingPlacementOptions,
  DrawingChangeKind, DrawingChangeEvent, DrawingEditOptions, DrawingToolEvent,
} from './controller-types';
import { placeViewportAnchors, readOnly, sortByZIndex, type DrawingPointerKind } from './layer';
import { getDrawingTool, hasDrawingTool, viewportDrawingTool } from './registry';
import { readViewportPoints } from './viewport';
import { DrawingClipboard, cloneDrawing, freshCopy } from './clipboard';
import { migrateDrawings, migrateGroups } from './migrate';
import { InputAnchors, type InputAnchorStep } from './input-anchors';
import { DrawingScreen, type PaneProjection, type PointerSample } from './screen';
import { magnetModeOf, magnetPoint, type SnapBar } from './snap';
import { DrawingGestures, type GestureKeys } from './gestures';
import { contextInterval, drawingsDocumentVersion, intervalFilter, passingContext, readIntervalRange } from './intervals';
import { changedAnchor } from './patches';
import { DrawingHistory, type DrawingHistoryEntry, type HistoryHost } from './drawing-history';
import { DrawingDrag, type DragHost } from './drawing-drag';
import { PaneLayerSet, slotOf, type LayerSetHost } from './pane-layers';

export type {
  DrawingChartHost, DrawingControllerOptions, DrawingGestureOptions, DrawingPlacementOptions,
  DrawingChangeKind, DrawingChangeEvent, DrawingEditOptions,
} from './controller-types';

/**
 * The pointer facts the chart attaches to every gesture payload. Read
 * defensively throughout: a host built against an older engine, or a
 * synthetic event in a test, carries none of them, and the fallbacks are a
 * plain mouse click with nothing held.
 */
interface PointerFacts {
  modifiers?: { shift?: boolean; alt?: boolean; ctrl?: boolean; meta?: boolean };
  pointerType?: string;
  pressure?: number;
}

interface ClickPayload extends PointerFacts {
  id: string | null;
  time: number;
  price: number | null;
  paneIndex: number;
  point: { x: number; y: number };
  /** Set on the release half of a press-drag-release gesture. */
  viaDrag?: boolean;
  /**
   * The flat copy of `modifiers` the chart still sends on a click. It goes in
   * 3.0.0 with the matching `ChartClickEvent` fields, so `modifiers` is read first.
   */
  shiftKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
}

export interface DragPayload extends PointerFacts {
  id: string;
  price: number;
  time: number;
  paneIndex: number;
  /** Container x, pane-local y. What a viewport drag measures, where the bars cannot. */
  point?: { x: number; y: number };
  /** Where the gesture was grabbed; deltas measure from here, not frame one. */
  fromPrice?: number;
  fromTime?: number;
}

/**
 * What a crosshair move carries, beyond the pointer facts: the bar under the
 * pointer for the magnet, `pressed` for freehand inking, and, while pressed,
 * every position the pointer passed through since the last move (`samples`),
 * so a fast stroke keeps its curve rather than its frame-rate corners.
 */
interface CrosshairPayload extends PointerFacts {
  time?: number | null;
  price?: number | null;
  paneIndex?: number | null;
  point?: { x: number; y: number } | null;
  bar?: { open: number; high: number; low: number; close: number } | null;
  pressed?: boolean;
  samples?: PointerSample[];
}

let nextId = 1;

const sameIds = (a: readonly string[], b: readonly string[]): boolean =>
  a.length === b.length && a.every((id, i) => id === b[i]);

/**
 * Whether a key is held, from either form the payload carries it in. The flat
 * flags on a click are deprecated (removed in 3.0.0): `modifiers` is read
 * first so nothing here depends on them, and they are still read so that a
 * synthetic payload carrying only them behaves the same until then.
 */
const held = (p: PointerFacts & { shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean },
  key: 'shift' | 'ctrl' | 'meta'): boolean => p.modifiers?.[key] === true || p[`${key}Key` as const] === true;

/** The pointer kind behind a payload; anything unnamed is a mouse. */
const keysOf = (p: PointerFacts & { shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean }): GestureKeys =>
  ({ shift: held(p, 'shift'), mod: held(p, 'ctrl') || held(p, 'meta'), alt: p.modifiers?.alt === true });

const pointerKindOf = (p: PointerFacts): DrawingPointerKind =>
  p.pointerType === 'touch' || p.pointerType === 'pen' ? p.pointerType : 'mouse';

type ControllerOptions = Required<Omit<DrawingControllerOptions, 'defaultStyle' | 'clipboard' | 'clipboardFallbackToMemory' | 'magnet' | 'inputAnchors' | 'gestures'>>
  & { defaultStyle: DrawingStyle; magnet: MagnetMode; gestures: Required<DrawingGestureOptions> };

/** Every gesture on, and a host's choice over it. */
const gesturesOf = (base: Required<DrawingGestureOptions>, patch: DrawingGestureOptions = {}): Required<DrawingGestureOptions> =>
  ({ ...base, ...Object.fromEntries(Object.entries(patch).filter(([key, on]) => key in base && typeof on === 'boolean')) });
const ALL_GESTURES: Required<DrawingGestureOptions> = { snapModifier: true, measure: true, boxSelect: true, dragCopy: true };

/** @internal Reserved persistence metadata; a duplicate is a new drawing lineage. */
export const DRAWING_LINK_METADATA_KEY = 'openalgo-charts/drawing-link';

export class DrawingController {
  private readonly _chart: DrawingChartHost;
  private _opts: ControllerOptions;
  private readonly _clipboard: DrawingClipboard;
  /** Every conversion between data space and the screen. */
  private readonly _screen: DrawingScreen;
  /** The gestures that make no drawing: the temporary measure, box select and the eraser. */
  private readonly _gestures: DrawingGestures;
  /** Every pane's drawing layers; see pane-layers.ts. */
  private readonly _layerSet = new PaneLayerSet(this as unknown as LayerSetHost);
  private _drawings: Drawing[] = [];
  private _groups: DrawingGroup[] = [];
  private _nextGroup = 1;
  private readonly _linkedPreviews = new Map<string, Drawing>();
  private _destroyed = false;
  private _tool: string | null = null;
  /** The space the armed tool places in; data whenever no tool is armed. */
  private _toolSpace: DrawingSpace = 'data';
  private _pending: DrawingPoint[] = [];
  private _pendingPane = 0;
  /** Selected ids, in the order they were picked. The first is the primary. */
  private _selection: string[] = [];
  /** The drawing under the pointer, from the chart's own hit-test. */
  private _hovered: string | null = null;
  /** Shift as of the last pointer report: what angle lock reads mid-preview. */
  private _shift = false;
  /** Ctrl or Cmd as of the last pointer report: the strong magnet while held. */
  private _strong = false;
  /** Placement mode as this controller last set it. */
  private _placing = false;
  /** The chart interval drawings are shown for; see `interval()`. */
  private _interval: string | null = null;
  /** The device behind the last pointer report, for target sizing. */
  private _pointerKind: DrawingPointerKind = 'mouse';
  /** Undo, redo and the host's own edits; see drawing-history.ts. */
  private readonly _history = new DrawingHistory(this as unknown as HistoryHost);
  /** The drag of a drawing or its handle; see drawing-drag.ts. */
  private readonly _drag = new DrawingDrag(this as unknown as DragHost);
  private readonly _off: (() => void)[] = [];
  private _anchors: InputAnchors | null = null;
  /** The host's timeline an anchor step goes to instead of this history; see `delegateInputAnchorSteps`. */
  private _anchorSteps: ((step: InputAnchorStep) => void) | null = null;
  private _lastCursor: { time: number; price: number; paneIndex: number } | null = null;
  /**
   * Bar under the cursor, carried by the crosshair event, with the time the
   * crosshair reported for it: the magnet lands anchors on that bar's values
   * at that bar's time.
   */
  private _lastBar: { time: number; open: number; high: number; low: number; close: number } | null = null;

  public constructor(chart: DrawingChartHost, options: DrawingControllerOptions = {}) {
    this._chart = chart;
    this._screen = new DrawingScreen(chart);
    this._gestures = new DrawingGestures({
      tool: () => this._tool,
      options: () => this._opts.gestures,
      aim: (point, pane) => this._aimPoint(point, pane),
      style: () => this._opts.defaultStyle,
      preview: () => this._layerSet._syncPreview(),
      emit: (event, payload) => this._chart.emit(event, payload),
      // What the interval hides is not on the chart, so no box or sweep reaches it.
      drawings: () => this._drawings.filter(this._shownFilter()),
      selection: () => this._selection,
      select: (ids) => this.select(ids),
      layer: (pane, make) => make === true ? this._layerSet._layerFor(pane).top : this._layerSet._layers.get(pane)?.top,
      hide: (ids) => { this._layerSet._hidden = ids; this._layerSet._syncLayers(); },
      erase: (ids) => { this._removeIds(ids, true); },
      plotRect: (pane) => this._chart.plotRect?.(pane) ?? null,
      placement: () => { if (!this._destroyed && this._placementWanted() !== this._placing) this._setPlacementMode(!this._placing); },
    });
    this._opts = {
      magnet: magnetModeOf(options.magnet),
      gestures: gesturesOf(ALL_GESTURES, options.gestures),
      stayInDrawingMode: options.stayInDrawingMode ?? false,
      historyLimit: options.historyLimit ?? 50,
      pasteOffsetBars: options.pasteOffsetBars ?? 2,
      pasteOffsetPixels: options.pasteOffsetPixels ?? 16,
      defaultStyle: options.defaultStyle ?? {},
    };
    this._clipboard = new DrawingClipboard({
      ...(options.clipboard === undefined ? {} : { port: options.clipboard }),
      ...(options.clipboardFallbackToMemory === undefined
        ? {}
        : { fallbackToMemory: options.clipboardFallbackToMemory }),
    });
    this._off.push(chart.on('click', (p) => this._onClick(p as ClickPayload)));
    this._off.push(chart.on('crosshair:move', (p) => this._onCrosshair(p as CrosshairPayload)));
    this._off.push(chart.on('hover', (p) => this._onHover(p as { id?: string | null })));
    this._off.push(chart.on('drag', (p) => this._drag._onDrag(p as DragPayload)));
    this._off.push(chart.on('drag:end', () => this._drag._onDragEnd()));
    this._off.push(chart.on('drag:cancel', () => { this.cancelDrag(); }));
    this._off.push(chart.on('data:context', context => { this.cancelDrag(); this._gestures.reset(); this._followInterval(context); }));
    this._off.push(chart.on('dblclick', () => { this.finish(); }));
    this._off.push(chart.on('drawings:restore', document => this.fromJSON(document)));
    this._off.push(chart.on('pick:start', () => this._gestures.picking(true)));
    this._off.push(chart.on('pick:end', () => this._gestures.picking(false)));
    // Restore anything a previous session left in the chart state. A 1.9.x
    // save is a bare array; the migration upgrades it in place.
    const saved = chart.drawingState();
    if (saved !== undefined && saved !== null) {
      const document = migrateDrawings(saved);
      this._drawings = document.drawings;
      this._groups = document.groups ?? [];
    }
    this._off.push(chart.on('paneRemoved', value => {
      const { paneIndex } = value as { paneIndex: number };
      this._remapPanes(index => index === paneIndex ? null : index > paneIndex ? index - 1 : index);
    }));
    this._off.push(chart.on('paneMoved', value => {
      const { from, to } = value as { from: number; to: number };
      this._remapPanes(index => index === from ? to : index === to ? from : index);
    }));
    // A study added, removed, moved or restacked changes which slot a drawing
    // placed in the series band paints in, and nothing else of it: only the
    // layers are re-listed, and only when a slot changed. Writing the chart
    // state here would announce a change of its own and come straight back.
    for (const event of ['objects:change', 'indicatorRemoved']) {
      this._off.push(chart.on(event, () => { if (this._layerSet._slotKey !== this._layerSet._slotSignature()) this._layerSet._syncLayers(); }));
    }
    this._interval = contextInterval(chart.getDataContext?.());
    this._sync();
    if (options.inputAnchors !== false && typeof chart.indicators === 'function') {
      this._anchors = new InputAnchors(chart, {
        record: (step, outside) => this._history._recordStep(step, outside),
        placing: () => this._tool !== null,
      });
    }
  }

  // ── public API ──────────────────────────────────────────────────────────

  /**
   * Arm a tool for placement, or pass null to return to the cursor. With
   * `options.space` set to `'viewport'` the drawing it places is pinned to the
   * screen; a tool that cannot be (see `DrawingTool.viewport`) throws.
   */
  public setTool(toolId: string | null, options: DrawingPlacementOptions = {}): void {
    if (toolId !== null && !hasDrawingTool(toolId)) {
      throw new Error(`openalgo-charts: unknown drawing tool "${toolId}"`);
    }
    const space: DrawingSpace = toolId !== null && options.space === 'viewport' ? 'viewport' : 'data';
    if (space === 'viewport' && !viewportDrawingTool(toolId as string)) {
      throw new Error(`openalgo-charts: drawing tool "${toolId}" cannot be anchored to the viewport`);
    }
    this.cancelDrag();
    this._gestures.reset();
    this._gestures.setEraser(false);
    this._tool = toolId;
    this._toolSpace = space;
    this._pending = [];
    this._setPlacementMode(this._placementWanted());
    this._layerSet._syncPreview();
    this._layerSet._syncSnapRing();
    this._emitTool();
  }

  /** The space the armed tool places in: `'data'` unless it was armed for the viewport. */
  public activeToolSpace(): DrawingSpace {
    return this._toolSpace;
  }

  /** `draw:tool`, carrying the space only when it is not the default, as the payload always has. */
  private _emitTool(): void {
    this._chart.emit('draw:tool', (this._toolSpace === 'viewport' ? { tool: this._tool, space: 'viewport' } : { tool: this._tool }) satisfies DrawingToolEvent);
  }

  /**
   * Ask the chart to stop panning and report gestures as anchor placement.
   * Guarded so a base bundle predating `setPlacementMode` still loads the tier.
   */
  private _setPlacementMode(active: boolean): void {
    this._placing = active;
    this._chart.setPlacementMode?.(active);
  }

  /**
   * The armed tool's placement mode, or a gesture's. The gestures are asked even with a tool
   * armed: their answer is also how they read the next press, and a stale one would take it.
   */
  private _placementWanted(): boolean {
    const gesture = this._gestures.wantsPlacement();
    return this._tool !== null || gesture;
  }

  public activeTool(): string | null {
    return this._tool;
  }

  public setOptions(patch: DrawingControllerOptions): void {
    // `clipboard` is a port, not a stored option: it is applied to the live
    // clipboard so a host can hand one over after the user grants permission,
    // and the memory fallback goes to the same place. `inputAnchors` is read
    // once, when the controller is built.
    const { clipboard, clipboardFallbackToMemory, inputAnchors: _built, magnet, gestures, ...rest } = patch;
    void _built;
    this._opts = {
      ...this._opts, ...rest,
      defaultStyle: patch.defaultStyle ?? this._opts.defaultStyle,
      magnet: magnet === undefined ? this._opts.magnet : magnetModeOf(magnet),
      gestures: gesturesOf(this._opts.gestures, gestures),
    };
    if (clipboard !== undefined) this._clipboard.setPort(clipboard);
    if (clipboardFallbackToMemory !== undefined) this._clipboard.setFallbackToMemory(clipboardFallbackToMemory);
    this._layerSet._syncSnapRing();
  }

  /** The snap mode in force, after the boolean form has been folded. */
  public magnetMode(): MagnetMode {
    return this._opts.magnet;
  }

  /**
   * Whether a temporary measure (Shift+click on empty space) is on the chart.
   * `draw:measure` (`{ active }`) fires when one starts and when it goes. A
   * host routing Escape to `cancel()` only while placing passes this too.
   */
  public measuring(): boolean {
    return this._gestures.measuring();
  }

  /**
   * Eraser mode: a click on a drawing deletes it, and a drag deletes every
   * drawing it crosses, as one undo step on release. What the user could not
   * delete by selecting it (read-only, locked, unselectable or hidden) stays.
   * While it is on the chart is in placement mode, so a drag erases rather
   * than pans. Turning it on disarms any tool; arming a tool, `cancel()` and
   * `setEraser(false)` turn it off. `draw:eraser` (`{ active }`) fires on
   * each change.
   */
  public setEraser(active: boolean): void {
    if (this._destroyed || active === this._gestures.erasing()) return;
    if (active) {
      this.cancelDrag();
      this._gestures.reset();
      if (this._tool !== null) {
        this._tool = null;
        this._toolSpace = 'data';
        this._pending = [];
        this._layerSet._syncPreview();
        this._layerSet._syncSnapRing();
        this._emitTool();
      }
    }
    this._gestures.setEraser(active);
  }

  /** Whether eraser mode is on. */
  public erasing(): boolean {
    return this._gestures.erasing();
  }

  /**
   * The drawing under the pointer, selected or not, as the chart's hit-test
   * last reported it. What a host passes as `hasTarget` to the key mapping,
   * and what a context menu opens on.
   */
  public hovered(): string | null {
    return this._hovered;
  }

  /** The clipboard behind copy / cut / paste, for a host reporting failures. */
  public clipboard(): DrawingClipboard {
    return this._clipboard;
  }

  /** Named drawing sets, returned as detached records. */
  public groups(): readonly DrawingGroup[] {
    return this._groups.map(group => ({ ...group, members: [...group.members] }));
  }

  /**
   * Group live drawings, replacing any previous membership for those ids. A
   * read-only drawing's group is the host's, so it is left where it is
   * unless `options.force` is set.
   */
  public createGroup(name: string, ids: readonly string[], options: DrawingEditOptions = {}): DrawingGroup | null {
    const members = [...new Set(ids)].filter(id => this.get(id) !== undefined && (options.force || !readOnly(this.get(id))));
    if (this._destroyed || !name.trim() || !members.length) return null;
    let id: string;
    // An id that only a recorded step still holds is taken as well: that
    // step would bring its group back over this one. Serialised, a group id
    // is its quoted self; the same text anywhere else only skips a number.
    do { id = `group-${this._nextGroup++}`; } while (this._groups.some(group => group.id === id)
      || [...this._history._undo, ...this._history._redo].some(entry => (entry.before + entry.after).includes(`"${id}"`)));
    const group = { id, name: name.trim(), members };
    const moved = new Set(members);
    this._regroup(options.force, groups => groups
      .map(previous => ({ ...previous, members: previous.members.filter(member => !moved.has(member)) }))
      .concat({ ...group, members: [...members] }));
    this._sync();
    this._emitChange(members, 'update');
    return { ...group, members: [...members] };
  }

  /** Rename a group. One that holds a read-only drawing is the host's, and needs `options.force`. */
  public renameGroup(id: string, name: string, options: DrawingEditOptions = {}): boolean {
    const group = this._group(id, options);
    if (!group || !name.trim()) return false;
    this._regroup(options.force, groups => groups.map(item => item.id === id ? { ...item, name: name.trim() } : item));
    this._sync();
    this._emitChange(group.members, 'update');
    return true;
  }

  /**
   * Remove a group, optionally deleting all its drawings as one edit. One
   * that holds a read-only drawing is the host's, and needs `options.force`.
   */
  public removeGroup(id: string, removeDrawings = false, options: DrawingEditOptions = {}): boolean {
    const group = this._group(id, options);
    if (!group) return false;
    this._regroup(options.force, groups => groups.filter(item => item.id !== id));
    if (!removeDrawings || this._removeIds(group.members, false, options.force).length === 0) { this._sync(); this._emitChange(group.members, 'update'); }
    return true;
  }

  /**
   * Make a grouping edit. The host's forced one is its own act, so every
   * recorded step takes it as well, and no undo or redo reverses it.
   */
  private _regroup(force: boolean | undefined, edit: (groups: DrawingGroup[]) => DrawingGroup[]): void {
    this._history._begin(!force);
    this._groups = edit(this._groups);
    if (force) this._history._rebase(document => { document.groups = edit(document.groups ?? []); });
  }

  /** The live group `id`, unless it holds a read-only drawing and the call is not forced. */
  private _group(id: string, options: DrawingEditOptions): DrawingGroup | undefined {
    const group = this._groups.find(item => item.id === id);
    return this._destroyed || (!options.force && group?.members.some(member => readOnly(this.get(member)))) ? undefined : group;
  }

  /**
   * Move one step through the rendered stack, within the slot it paints in:
   * its side of the series, or the entry it is placed above. `placeInStack`
   * moves it between slots.
   */
  public reorder(id: string, direction: -1 | 1): boolean {
    const drawing = this.get(id);
    if (!drawing || this._destroyed || (direction !== -1 && direction !== 1)) return false;
    const entries = this._entries(drawing.paneIndex), slot = slotOf(drawing, entries);
    const band = this._drawings.filter(item => item.paneIndex === drawing.paneIndex && slotOf(item, entries) === slot)
      .sort((a, b) => a.zIndex - b.zIndex);
    const index = band.indexOf(drawing);
    const target = index + direction;
    if (target < 0 || target >= band.length) return false;
    this._history._pushUndo();
    [band[index], band[target]] = [band[target]!, band[index]!]; // the drawing is in its band; target is checked
    const members = new Set(band);
    let cursor = 0;
    this._drawings = this._drawings.map(item => members.has(item) ? band[cursor++]! : item); // one per member
    band.forEach((item, position) => { item.zIndex = slot === 'below' ? position - band.length : position; });
    this._sync();
    for (const item of band) this._chart.emit('draw:update', { drawing: item });
    this._emitChange(band.map(item => item.id), 'reorder');
    return true;
  }

  /**
   * Move a drawing directly above or below `target` in its pane's paint
   * order, as one undo step. Next to another drawing it joins the slot that
   * drawing paints in; above a series-band entry (`chart.seriesStack`) it is
   * placed on that entry, under the drawings already there; below one it goes
   * on top of the slot under that entry, the drawings behind the series when
   * the entry is the first. A slot's drawings are renumbered, below the series
   * up to -1 and elsewhere from 0. False, with nothing recorded, for a target
   * on another pane, one the host cannot report, or a move that changes nothing.
   * Like `reorder`, it is outside a drawing's policy.
   */
  public placeInStack(id: string, target: DrawingStackTarget, where: 'above' | 'below'): boolean {
    const d = this.get(id);
    if (d === undefined || this._destroyed || (where !== 'above' && where !== 'below') || target === null || typeof target !== 'object') return false;
    const entries = this._entries(d.paneIndex);
    let slot: string, index: number;
    if ('drawing' in target) {
      const t = this.get(target.drawing);
      if (t === undefined || t === d || t.paneIndex !== d.paneIndex) return false;
      slot = slotOf(t, entries);
      index = this._slotMembers(d.paneIndex, slot, entries).filter(m => m !== d).indexOf(t) + (where === 'above' ? 1 : 0);
    } else {
      const at = entries.indexOf((target as { entry: string }).entry);
      if (at < 0) return false;
      slot = where === 'above' ? 'entry:' + entries[at] : at === 0 ? 'below' : 'entry:' + entries[at - 1];
      index = where === 'above' ? 0 : this._slotMembers(d.paneIndex, slot, entries).filter(m => m !== d).length;
    }
    const members = this._slotMembers(d.paneIndex, slot, entries);
    if (slotOf(d, entries) === slot && members.indexOf(d) === index) return false;
    this._history._pushUndo();
    const next = members.filter(m => m !== d);
    next.splice(index, 0, d);
    if (slot.startsWith('entry:')) d.stackAbove = slot.slice('entry:'.length);
    else delete d.stackAbove;
    next.forEach((m, position) => { m.zIndex = slot === 'below' ? position - next.length : position; });
    this._sync();
    for (const m of next) this._chart.emit('draw:update', { drawing: m });
    this._emitChange(next.map(m => m.id), 'reorder');
    return true;
  }

  /** A pane's series band as the chart reports it, or none on a host that cannot. */
  private _entries(paneIndex: number): readonly string[] {
    return this._chart.seriesStack?.(paneIndex) ?? [];
  }

  /** The drawings of one slot of a pane, in paint order. */
  private _slotMembers(paneIndex: number, slot: string, entries: readonly string[]): Drawing[] {
    return sortByZIndex(this._drawings.filter(d => d.paneIndex === paneIndex && slotOf(d, entries) === slot));
  }

  private _remapPanes(map: (index: number) => number | null): void {
    // Cancel without syncing to numeric slots which have already shifted.
    this._drag.cancelDrag(false);
    this._pending = [];
    this._lastCursor = null;
    this._gestures.reset();
    this._linkedPreviews.clear();
    const remapSnapshot = (value: string): string => {
      const document = migrateDrawings(JSON.parse(value));
      document.drawings = document.drawings.filter(drawing => {
        const pane = map(drawing.paneIndex);
        if (pane === null) return false;
        drawing.paneIndex = pane;
        return true;
      });
      document.groups = migrateGroups(document.groups, document.drawings);
      return JSON.stringify(document);
    };
    for (const entry of new Set([...this._history._undo, ...this._history._redo])) {
      entry.before = remapSnapshot(entry.before);
      entry.after = remapSnapshot(entry.after);
    }
    const removed: Drawing[] = [];
    this._drawings = this._drawings.filter(drawing => {
      const pane = map(drawing.paneIndex);
      if (pane === null) { removed.push(drawing); return false; }
      drawing.paneIndex = pane;
      return true;
    });
    const layers = [...this._layerSet._layers.entries()];
    this._layerSet._layers.clear();
    for (const [index, pair] of layers) {
      const pane = map(index);
      if (pane !== null) this._layerSet._layers.set(pane, pair);
    }
    this._pruneSelection();
    this._sync();
    for (const drawing of removed) this._chart.emit('draw:remove', { drawing });
    this._emitChange(this._drawings.map(drawing => drawing.id), 'update');
  }

  /**
   * Every drawing, in list order, those the interval hides included. That is
   * creation order until a z-order call moves one; the list is the tie-break
   * for equal `zIndex`, so it is also the paint order within a band.
   */
  public drawings(): readonly Drawing[] {
    return this._drawings;
  }

  public get(id: string): Drawing | undefined {
    return this._drawings.find((d) => d.id === id);
  }

  /**
   * The chart interval drawings are shown for: the data context's `interval`
   * when the controller was built, then as each `data:context` announces it,
   * or null when the host names none (or a blank one), and then every drawing
   * shows. Each drawing's `intervals` range is read against it.
   */
  public interval(): string | null {
    return this._interval;
  }

  /**
   * Whether a drawing is on the chart at the chart's interval: false for an
   * unknown id and for one whose `intervals` range leaves that interval out.
   * `visible` is not read; it is the user's own switch.
   */
  public shownOnInterval(id: string): boolean {
    const d = this.get(id);
    return d !== undefined && this._shownFilter()(d);
  }

  /**
   * The ids of the drawings the chart's interval leaves off the chart, in
   * model order. One pass for a caller asking about every drawing, as the
   * object inventory does on each refresh: `shownOnInterval` per id would
   * look each one up.
   */
  public hiddenOnInterval(): string[] {
    const shown = this._shownFilter();
    return this._drawings.filter(d => !shown(d)).map(d => d.id);
  }

  /** The test of whether a drawing is shown at the chart's interval, resolved once for a pass over many. */
  private _shownFilter(): (d: Pick<Drawing, 'intervals'>) => boolean {
    return intervalFilter(this._interval);
  }

  /**
   * Follow a change of the chart's interval: what it hides leaves the layers
   * and the selection, what it shows comes back. The layers are listed again
   * only when that set changed, since a list under the series costs the
   * series a repaint and a new symbol on the same interval changes nothing.
   */
  private _followInterval(context: unknown): void {
    if (this._destroyed || passingContext(context)) return;
    const read = this._chart.getDataContext;
    this._interval = contextInterval(read === undefined ? context : read.call(this._chart));
    if (this.hiddenOnInterval().join('\u0000') === this._layerSet._offInterval) return;
    const shown = this._shownFilter();
    this._layerSet._syncLayers();
    const kept = this._selection.filter(id => { const d = this.get(id); return d !== undefined && shown(d); });
    if (!sameIds(kept, this._selection)) this._setSelection(kept);
    if (this._hovered !== null && !this.shownOnInterval(this._hovered)) this._setHovered(null);
  }

  public get isDestroyed(): boolean { return this._destroyed; }

  /** Apply a linked commit without adding to this chart's local undo history. */
  public applyLinkedDrawing(id: string, drawing: Drawing | null): void {
    if (this._destroyed || this._chart.isDestroyed === true) return;
    if (this._drag._dragStart?.items.some(item => item.id === id)) this.cancelDrag();
    const index = this._drawings.findIndex(item => item.id === id);
    this._linkedPreviews.delete(id);
    if (drawing === null) {
      if (index < 0) return;
      this._drawings.splice(index, 1);
      this._pruneSelection();
    } else {
      const copy = cloneDrawing({ ...drawing, id });
      const was = JSON.stringify(this._drawings[index]?.policy);
      if (index < 0) this._drawings.push(copy);
      else this._drawings[index] = copy;
      // A policy the other chart's host changed holds here too, history included; a removed one is written as undefined.
      if (JSON.stringify(copy.policy) !== was) {
        this._history._rebase(document => { for (const d of document.drawings) if (d.id === id) (d as { policy?: DrawingPolicy | undefined }).policy = copy.policy; });
      }
    }
    this._sync();
    this._chart.emit('drawing:change', { ids: [id], kind: drawing === null ? 'remove' : index < 0 ? 'add' : 'update', linked: true } satisfies DrawingChangeEvent);
  }

  /** A linked drag paints over its committed drawing without changing saved state. */
  public setLinkedPreview(id: string, drawing: Drawing | null): void {
    if (this._destroyed || this._chart.isDestroyed === true) return;
    if (drawing === null) this._linkedPreviews.delete(id);
    else if (this.get(id) !== undefined) this._linkedPreviews.set(id, cloneDrawing({ ...drawing, id }));
    this._sync();
  }

  /** Reorder related drawings inside their existing slots, preserving unrelated local order. */
  public reorderLinkedDrawings(ids: readonly string[]): void {
    if (this._destroyed || this._chart.isDestroyed === true) return;
    const ordered = [...new Set(ids)].map(id => this.get(id)).filter((d): d is Drawing => d !== undefined);
    const selected = new Set(ordered.map(d => d.id));
    let index = 0;
    const next = this._drawings.map(d => selected.has(d.id) ? ordered[index++]! : d); // one per selected
    if (next.every((d, i) => d === this._drawings[i])) return;
    this._drawings = next;
    this._sync();
    this._chart.emit('drawing:change', { ids: ordered.map(d => d.id), kind: 'reorder', linked: true } satisfies DrawingChangeEvent);
  }

  /** Supported numeric levels, independent of whether the queried time lies on the shape. */
  public alertInfo(id: string): AlertDrawingInfo {
    const drawing = this.get(id);
    if (!drawing || !hasDrawingTool(drawing.tool)) return { available: false, reason: 'Drawing is unavailable', levels: [] };
    const tool = getDrawingTool(drawing.tool);
    // A pinned drawing sits over whatever price is under it at the moment,
    // which changes with every pan: there is no level to watch.
    if (drawing.space === 'viewport') return { available: false, reason: 'A drawing pinned to the screen has no price', paneIndex: drawing.paneIndex, levels: [] };
    if (!tool.alertValue) return { available: false, reason: 'This tool has no numeric alert value', paneIndex: drawing.paneIndex, levels: [] };
    const levels = tool.alertLevels?.(drawing) ?? [{ id: 'line', title: 'Line' }];
    if (!this._chart.timeToCoordinate || !this._chart.priceToCoordinate || !this._chart.coordinateToPrice) {
      return { available: false, reason: 'Drawing coordinate maps are unavailable', levels: [], paneIndex: drawing.paneIndex };
    }
    return { available: levels.length > 0, reason: levels.length ? undefined : 'No active drawing levels',
      paneIndex: drawing.paneIndex, levels: levels.map(level => ({ ...level })) };
  }

  /** Numeric drawing value using the actual pane projection and collapsed time axis. */
  public valueAt(id: string, time: number, level?: string): AlertDrawingValue | undefined {
    const drawing = this.get(id);
    if (!drawing || drawing.space === 'viewport' || !hasDrawingTool(drawing.tool) || !Number.isFinite(time)) return undefined;
    const tool = getDrawingTool(drawing.tool);
    const toX = this._chart.timeToCoordinate;
    const toPrice = this._chart.coordinateToPrice;
    if (!tool.alertValue || !toX || !toPrice) return undefined;
    const pane = drawing.paneIndex;
    let fromY = (y: number): number | null => toPrice.call(this._chart, y, pane);
    let pts = drawing.points.map(point => this._screen.toPixel(point, pane));
    if (pts.includes(null)) {
      // A pane folded to a strip has no place on screen, so the chart maps no
      // price there, yet an alert on it must keep firing. The pane's own scale
      // keeps the projection it was drawn in, and every alert level is a line
      // through the anchors, which the height of that scale cannot move.
      const own = this._chart.panes?.()[pane] as PaneProjection | undefined;
      if (typeof own?.priceToY !== 'function' || typeof own.yToPrice !== 'function') return undefined;
      pts = drawing.points.map(point => ({ x: toX.call(this._chart, point.time), y: own.priceToY(point.price) }));
      fromY = y => own.yToPrice(y);
    }
    const x = toX.call(this._chart, time);
    if (!Number.isFinite(x)) return undefined;
    const value = tool.alertValue({ drawing, pts: pts as ScreenPoint[], time, x, fromY }, level);
    if (!value || !Number.isFinite(value.price) || (value.upperPrice !== undefined && !Number.isFinite(value.upperPrice))) return undefined;
    return { ...value, paneIndex: drawing.paneIndex };
  }

  /**
   * Add a fully-specified drawing (import, or a host-authored one). One that
   * carries a restriction is the host's, and placing it is not a step the
   * user can take back, so it is not recorded.
   */
  public add(drawing: DrawingInput): Drawing {
    // Refused before anything is recorded: a bad viewport drawing is the
    // caller's mistake, and leaves no undo step behind.
    if (drawing.space === 'viewport' && (!viewportDrawingTool(drawing.tool) || readViewportPoints(drawing.viewportPoints) === null)) {
      throw new Error(`openalgo-charts: a "${drawing.tool}" drawing cannot be anchored to the viewport with those viewportPoints`);
    }
    this._history._begin(!Object.values(drawing.policy ?? {}).includes(false));
    const created = this._insert(drawing);
    this._sync();
    this._chart.emit('draw:add', { drawing: created });
    this._emitChange([created.id], 'add');
    return created;
  }

  /**
   * Append one drawing without touching history or the layers. Split out so a
   * paste of several drawings is a single undo step rather than one per shape.
   */
  private _insert(drawing: DrawingInput): Drawing {
    const tool = getDrawingTool(drawing.tool);
    let id = drawing.id ?? this._mintId();
    // A restored layout can hold an id the counter has not reached yet.
    while (drawing.id === undefined && this.get(id) !== undefined) id = this._mintId();
    const { id: _dropped, ...rest } = drawing;
    void _dropped;
    const created: Drawing = {
      ...rest,
      id,
      style: { ...this._opts.defaultStyle, ...tool.defaultStyle, ...drawing.style },
      zIndex: Number.isFinite(drawing.zIndex) ? (drawing.zIndex as number) : 0,
      createdAt: drawing.createdAt ?? Date.now(),
    };
    // A copy: the object the caller keeps is not a switch on this drawing.
    if (drawing.policy) created.policy = { ...drawing.policy };
    // One space, one set of anchors: a viewport drawing keeps no data anchors
    // that could be mistaken for its position, and data is never written out.
    if (drawing.space === 'viewport') {
      created.points = [];
      created.viewportPoints = readViewportPoints(drawing.viewportPoints) ?? [];
    } else {
      delete created.space;
      delete created.viewportPoints;
    }
    // A copy, and only a range that names a bound: an empty one limits nothing.
    const intervals = readIntervalRange(drawing.intervals);
    if (intervals === null) delete created.intervals;
    else created.intervals = intervals;
    if (created.props?.[DRAWING_LINK_METADATA_KEY] !== undefined) {
      created.props = { ...created.props };
      delete created.props[DRAWING_LINK_METADATA_KEY];
    }
    if (drawing.text !== undefined || tool.defaultText !== undefined) {
      created.text = { value: '', ...tool.defaultText, ...drawing.text };
    }
    this._drawings.push(created);
    return created;
  }

  private _mintId(): string {
    return `d${nextId++}`;
  }

  /**
   * Patch one drawing. False when there is no such drawing, or when it is
   * read-only to the user and `options.force` is not set. A patch that
   * carries `policy` is the host's, and like a forced one records no step.
   *
   * Also false when the patch asks for a `space` the drawing could not be
   * moved to (a tool without viewport support, or a pane with no place on
   * screen, folded or hidden behind a maximized pane): the rest of the patch
   * still applies, and the false tells a host that the drawing is not in the
   * space it asked for, which a control showing that space has to say.
   */
  public update(id: string, patch: DrawingPatch, options: DrawingEditOptions = {}): boolean {
    const d = this.get(id);
    if (d === undefined || (readOnly(d) && options.force !== true)) return false;
    this.updateMany([{ id, patch }], options);
    return patch.space === undefined || (d.space === 'viewport') === (patch.space === 'viewport');
  }

  /**
   * Patch several drawings as one undo entry: a colour change across a
   * multi-selection is one edit to the user, so it is one Ctrl+Z too. Ids that
   * no longer exist are skipped, and so are read-only drawings unless
   * `options.force` is set; nothing is recorded when nothing is left, or
   * when every patch is the host's (forced, or carrying `policy`).
   */
  public updateMany(patches: ReadonlyArray<{ id: string; patch: DrawingPatch }>, options: DrawingEditOptions = {}): void {
    const live = patches
      .map((p) => ({ d: this.get(p.id), patch: p.patch }))
      .filter((p): p is { d: Drawing; patch: DrawingPatch } => p.d !== undefined && (options.force === true || !readOnly(p.d)))
      // A change of space the controller cannot make leaves nothing for that
      // drawing to do, and it is not an edit to record.
      .map(({ d, patch }) => ({ d, patch: this._spacePatch(d, patch), asked: Object.keys(patch).length }))
      .filter(({ patch, asked }) => asked === 0 || Object.keys(patch).length > 0);
    if (live.length === 0) return;
    this._history._begin(!options.force && live.some(({ patch }) => !patch.policy));
    for (const { d, patch } of live) this._applyPatch(d, patch);
    let rewrite = false;
    for (const { d, patch: { points, ...rest } } of live) {
      if (!options.force && !rest.policy) continue;
      // The host's patch, whole, and the anchors exactly where they landed:
      // a constraint run again on an older shape could put them elsewhere.
      const held = this._history._hostPatches.get(d.id) ?? {};
      this._applyPatch(held as Drawing, rest);
      // Data is stored as an absent space, so the held patch names it outright.
      if (rest.space !== undefined) held.space = rest.space;
      // Likewise a drawing taken out of the series band.
      if (rest.stackAbove !== undefined) (held as DrawingPatch).stackAbove = rest.stackAbove;
      // And a range, cleared or set, as the drawing now holds it.
      if (rest.intervals !== undefined) (held as DrawingPatch).intervals = d.intervals === undefined ? null : { ...d.intervals };
      if (points) held.points = d.points;
      this._history._hostPatches.set(d.id, held);
      // History cannot reach a read-only drawing's content until its policy
      // changes, and that change is a rewrite which takes this patch first,
      // so moving one (a trailing level, every tick) costs no rewrite. Its
      // place in the stack is within history's reach.
      rewrite ||= !readOnly(d) || !!rest.policy || rest.zIndex !== undefined || rest.stackAbove !== undefined;
    }
    if (rewrite) this._history._rebase();
    this._sync();
    for (const { d } of live) this._chart.emit('draw:update', { drawing: d });
    this._emitChange(live.map((p) => p.d.id), 'update');
  }

  /**
   * A patch as it applies to `d`. A change of space comes out complete, with
   * the anchors of the new space (converted at the view on screen unless the
   * patch gives them), or is left out when it cannot be made; anchors of the
   * space the drawing will not be in are left out too, so one drawing never
   * carries two positions.
   */
  private _spacePatch(d: Drawing, patch: DrawingPatch): DrawingPatch {
    const { space, points, viewportPoints, ...rest } = patch;
    const from: DrawingSpace = d.space === 'viewport' ? 'viewport' : 'data';
    let to: DrawingSpace = space === undefined ? from : space === 'viewport' ? 'viewport' : 'data';
    if (to === 'viewport' && from === 'data' && !viewportDrawingTool(d.tool)) to = 'data';
    if (to === 'viewport') {
      const given = viewportPoints === undefined ? null : readViewportPoints(viewportPoints);
      if (to === from) return given === null ? rest : { ...rest, viewportPoints: given };
      const anchors = given ?? this._screen.toViewport(points ?? d.points, d.paneIndex, d);
      return anchors === null ? rest : { ...rest, space: 'viewport', points: [], viewportPoints: anchors };
    }
    if (to === from) return points === undefined ? rest : { ...rest, points };
    const anchors = points ?? this._screen.fromViewport(readViewportPoints(viewportPoints) ?? d.viewportPoints ?? [], d.paneIndex, d);
    return anchors === null ? rest : { ...rest, space: 'data', points: anchors };
  }

  private _applyPatch(d: Drawing, patch: DrawingPatch): void {
    if (patch.points !== undefined) {
      const points = patch.points.map((p) => ({ ...p }));
      const tool = hasDrawingTool(d.tool) ? getDrawingTool(d.tool) : undefined;
      // A patch that moved exactly one anchor (a price typed into a settings
      // field) is told which, so the constraint leaves that one where it was
      // put, the same as a drag of its handle would. A move to the viewport
      // empties the list, which leaves nothing to constrain.
      d.points = tool?.constrain === undefined || points.length === 0 ? points : tool.constrain(points, changedAnchor(d.points, points));
    }
    if (patch.space !== undefined) {
      if (patch.space === 'viewport') d.space = 'viewport';
      else { delete d.space; delete d.viewportPoints; }
    }
    if (patch.viewportPoints !== undefined) d.viewportPoints = patch.viewportPoints.map((p) => ({ x: p.x, y: p.y }));
    if (patch.style !== undefined) d.style = { ...d.style, ...patch.style };
    if (patch.text !== undefined) d.text = { ...d.text, ...patch.text };
    if (patch.props !== undefined) d.props = { ...d.props, ...patch.props };
    if (patch.locked !== undefined) d.locked = patch.locked;
    if (patch.visible !== undefined) d.visible = patch.visible;
    if (patch.intervals !== undefined) {
      const range = patch.intervals === null ? null : readIntervalRange(patch.intervals);
      if (range === null) delete d.intervals;
      else d.intervals = range;
    }
    if (patch.zIndex !== undefined && Number.isFinite(patch.zIndex)) d.zIndex = patch.zIndex;
    if (patch.policy !== undefined) d.policy = { ...d.policy, ...patch.policy };
    if (typeof patch.stackAbove === 'string' && patch.stackAbove !== '') d.stackAbove = patch.stackAbove;
    else if (patch.stackAbove === null) delete d.stackAbove;
  }

  /** Delete one drawing. A read-only one goes only with `options.force`. */
  public remove(id: string, options: DrawingEditOptions = {}): boolean {
    return this._removeIds([id], true, options.force).length > 0;
  }

  /**
   * Delete several drawings as one undo entry. Unknown ids are ignored, and
   * read-only drawings stay unless `options.force` is set.
   */
  public removeMany(ids: readonly string[], options: DrawingEditOptions = {}): void {
    this._removeIds(ids, true, options.force);
  }

  /**
   * The delete shared by `remove`, `removeMany`, `cut` and `clear`. Returns
   * what went, and records nothing when nothing did.
   */
  private _removeIds(ids: readonly string[], pushUndo: boolean, force = false): Drawing[] {
    const wanted = new Set(ids);
    const removed = this._drawings.filter((d) => wanted.has(d.id) && (force || !readOnly(d)));
    if (removed.length === 0) return [];
    if (pushUndo) this._history._begin(!force);
    const set = new Set(removed.map((d) => d.id));
    this._drawings = this._drawings.filter((d) => !set.has(d.id));
    if (force) this._history._rebase(document => { document.drawings = document.drawings.filter((d) => !set.has(d.id)); });
    this._selection = this._selection.filter((id) => !set.has(id));
    this._sync();
    for (const d of removed) this._chart.emit('draw:remove', { drawing: d });
    this._emitChange(removed.map((d) => d.id), 'remove');
    return removed;
  }

  /** Delete every drawing the user may, as one undo entry; `options.force` takes the read-only ones too. */
  public clear(options: DrawingEditOptions = {}): void {
    if (this._drawings.length === 0) return;
    this._removeIds(this._drawings.map((d) => d.id), true, options.force);
    this._setSelection([]);
  }

  // ── selection ───────────────────────────────────────────────────────────

  /**
   * Replace the selection, or with `additive` toggle each id into it (the
   * shift-click gesture). Ids that name nothing, or a drawing whose policy
   * says it cannot be selected, are ignored, so the selection only ever holds
   * drawings that are there to act on. Pass null to clear.
   */
  public select(id: string | readonly string[] | null, additive = false): void {
    const wanted = id === null ? [] : typeof id === 'string' ? [id] : id;
    const known: string[] = [];
    for (const x of wanted) {
      if (this._selectable(x) && !known.includes(x)) known.push(x);
    }
    if (!additive) {
      this._setSelection(known);
      return;
    }
    const next = this._selection.slice();
    for (const x of known) {
      const i = next.indexOf(x);
      if (i >= 0) next.splice(i, 1);
      else next.push(x);
    }
    this._setSelection(next);
  }

  private _selectable(id: string): boolean {
    const d = this.get(id);
    return d !== undefined && d.policy?.selectable !== false;
  }

  /** The primary selection: the first id picked, or null. */
  public selected(): string | null {
    return this._selection.length === 0 ? null : this._selection[0]!;
  }

  /** Every selected id, in the order they were picked. */
  public selection(): readonly string[] {
    return this._selection;
  }

  private _setSelection(next: string[]): void {
    const changed = !sameIds(next, this._selection);
    this._selection = next;
    for (const layer of this._layerSet._allLayers()) layer.setSelected(next);
    if (!changed) return;
    this._chart.emit('draw:select', { id: this.selected() });
    this._chart.emit('drawing:select', { ids: next.slice() });
  }

  private _emitChange(ids: readonly string[], kind: DrawingChangeKind): void {
    const recorded = this._history._pendingHistory;
    if (recorded !== null) {
      recorded.after = this._historyText();
      this._history._pendingHistory = null;
    }
    this._history._takeInHostEdit();
    const change: DrawingChangeEvent = { ids: ids.slice(), kind };
    // A trim can push the step out of the branch while it is being recorded,
    // and a step nothing holds is not one to report.
    if (recorded !== null && this._history._undo.includes(recorded)) change.step = recorded.step;
    this._chart.emit('drawing:change', change);
  }

  // ── z-order ─────────────────────────────────────────────────────────────
  //
  // `zIndex` is the primary key and list position the tie-break, so "front"
  // and "back" are settled by moving both: the extreme `zIndex` of the pane
  // plus the end of the list. Whether a drawing sits under the series is a
  // separate choice made by the sign alone, and the two series calls change
  // nothing else, so they never reorder a stack the user has arranged.

  public setZIndex(id: string, z: number): void {
    const d = this.get(id);
    if (d === undefined || !Number.isFinite(z) || d.zIndex === z) return;
    this._history._pushUndo();
    d.zIndex = z;
    this._sync();
    this._chart.emit('draw:update', { drawing: d });
    this._emitChange([id], 'reorder');
  }

  /** In front of every other drawing in its slot: its side of the series, or the entry it is placed above. */
  public bringToFront(id: string): void {
    const d = this.get(id);
    if (d === undefined) return;
    const band = this._band(d);
    const z = band.length === 0 ? d.zIndex : Math.max(...band.map((o) => o.zIndex));
    this._reorder(d, z, 'end');
  }

  /** Behind every other drawing in its slot: its side of the series, or the entry it is placed above. */
  public sendToBack(id: string): void {
    const d = this.get(id);
    if (d === undefined) return;
    const band = this._band(d);
    const z = band.length === 0 ? d.zIndex : Math.min(...band.map((o) => o.zIndex));
    this._reorder(d, z, 'start');
  }

  /**
   * Under the series (`zIndex` -1), out of the series band when it was placed
   * in it. A no-op for a drawing already there.
   */
  public sendBehindSeries(id: string): void {
    const d = this.get(id);
    // A placement kept for a study that is gone goes too: the user chose a side.
    if (d !== undefined && (d.stackAbove !== undefined || slotOf(d, this._entries(d.paneIndex)) !== 'below')) this._crossSeries(d, -1);
  }

  /**
   * Over the series (`zIndex` 0), out of the series band when it was placed
   * in it. A no-op for a drawing already there.
   */
  public bringAboveSeries(id: string): void {
    const d = this.get(id);
    if (d !== undefined && (d.stackAbove !== undefined || slotOf(d, this._entries(d.paneIndex)) !== 'above')) this._crossSeries(d, 0);
  }

  private _crossSeries(d: Drawing, z: number): void {
    this._history._pushUndo();
    d.zIndex = z;
    delete d.stackAbove;
    this._sync();
    this._chart.emit('draw:update', { drawing: d });
    this._emitChange([d.id], 'reorder');
  }

  /** The other drawings sharing `d`'s pane and slot. */
  private _band(d: Drawing): Drawing[] {
    const entries = this._entries(d.paneIndex), slot = slotOf(d, entries);
    return this._drawings.filter((o) => o !== d && o.paneIndex === d.paneIndex && slotOf(o, entries) === slot);
  }

  private _reorder(d: Drawing, z: number, where: 'start' | 'end'): void {
    const i = this._drawings.indexOf(d);
    const target = where === 'end' ? this._drawings.length - 1 : 0;
    if (i === target && d.zIndex === z) return;
    this._history._pushUndo();
    d.zIndex = z;
    this._drawings.splice(i, 1);
    if (where === 'end') this._drawings.push(d);
    else this._drawings.unshift(d);
    this._sync();
    this._chart.emit('draw:update', { drawing: d });
    this._emitChange([d.id], 'reorder');
  }

  // ── moving ──────────────────────────────────────────────────────────────

  /**
   * Move drawings by a screen distance, `dx` right and `dy` down in media px,
   * as one undo entry. Pixels rather than data units so an arrow key moves a
   * shape the same visible amount on every pane and scale. Locked and
   * read-only drawings stay put.
   */
  public nudge(ids: readonly string[], dxPx: number, dyPx: number): void {
    if (dxPx === 0 && dyPx === 0) return;
    const list = this._targets(ids).filter((d) => d.locked !== true && !readOnly(d));
    if (list.length === 0) return;
    this._history._pushUndo();
    for (const d of list) {
      if (d.space === 'viewport') {
        const frame = this._screen.plotFrame(d.paneIndex);
        if (frame !== null) d.viewportPoints = this._screen.shiftPinned(d, d.viewportPoints ?? [], dxPx, dyPx, frame);
        continue;
      }
      d.points = d.points.map((p) => ({
        time: this._screen.offsetTime(p.time, dxPx),
        price: this._screen.offsetPrice(p.price, d.paneIndex, dyPx),
      }));
    }
    this._sync();
    for (const d of list) this._chart.emit('draw:update', { drawing: d });
    this._emitChange(list.map((d) => d.id), 'update');
  }

  /**
   * Clone drawings, offset like a paste so the copies are visibly new, and
   * select the clones. One undo entry. Ids that name nothing are ignored. A
   * clone is the user's own drawing, so it carries no policy.
   */
  public duplicate(ids: readonly string[]): Drawing[] {
    const sources = this._targets(ids);
    if (sources.length === 0) return [];
    this._history._pushUndo();
    const clones = sources.map((d) => this._insert({ ...freshCopy(d), ...this._offsetAnchors(d, d.paneIndex) }));
    this._sync();
    for (const c of clones) this._chart.emit('draw:add', { drawing: c });
    this._emitChange(clones.map((c) => c.id), 'add');
    this.select(clones.map((c) => c.id));
    return clones;
  }

  // ── clipboard ───────────────────────────────────────────────────────────
  //
  // Async because the OS clipboard is: `navigator.clipboard` returns promises
  // and can reject on a permission the user has not granted. The host owns the
  // key bindings (the engine installs no listeners), so these are plain calls.

  /**
   * Put drawings on the clipboard. Defaults to the selection; pass an id or a
   * list of ids to copy something else. Resolves false when there was nothing
   * to copy, or when the payload could not be stored anywhere.
   */
  public async copy(target?: string | readonly string[] | null): Promise<boolean> {
    const list = this._targets(target);
    if (list.length === 0) return false;
    const ok = await this._clipboard.write(this._portable(list));
    if (ok) this._chart.emit('draw:copy', { drawings: list.map(cloneDrawing) });
    return ok;
  }

  /**
   * Copy, then delete. The delete happens **only** after the clipboard write
   * resolves successfully, so a refused write leaves the model exactly as it
   * was rather than destroying a drawing that went nowhere. A read-only
   * drawing cannot be deleted, so it is not cut either: it stays, uncopied.
   */
  public async cut(target?: string | readonly string[] | null): Promise<boolean> {
    const list = this._targets(target).filter((d) => !readOnly(d));
    if (list.length === 0) return false;
    const ok = await this._clipboard.write(this._portable(list));
    if (!ok) return false;
    // One undo step for the whole cut, and the drawings are re-read here
    // because the await above gave other code a chance to change the model.
    const removed = this._removeIds(list.map((d) => d.id), true);
    if (removed.length === 0) return false;
    this._chart.emit('draw:cut', { drawings: removed });
    return true;
  }

  /**
   * Paste whatever is on the clipboard into this chart, offset from the
   * original so the copy is visibly a second object, and select the result.
   * Each pasted drawing is a fresh object with a fresh id, never a second
   * reference to the one copied, so editing the paste cannot alter its source
   * (or the clipboard).
   *
   * Anything that is not our payload (foreign text, a truncated or hand-edited
   * copy, a newer format) pastes nothing and resolves to an empty array: a
   * paste shortcut must not throw at the host because the user last copied a
   * spreadsheet cell.
   */
  public async paste(): Promise<Drawing[]> {
    const entries = await this._clipboard.read();
    if (entries === null || entries.length === 0) return [];
    // Everything is prepared before the model is touched: a tool that has since
    // been unregistered would throw inside `_insert` and leave a half-applied
    // paste plus an undo entry describing a state that never existed.
    for (const e of entries) {
      if (!hasDrawingTool(e.tool)) return [];
    }
    const shown = this._shownFilter();
    const prepared = entries.map((e) => {
      const paneIndex = this._clampPane(e.paneIndex);
      // A paste never lands hidden: a range leaving out this chart's interval
      // would make the paste look like it did nothing, so it is not carried.
      return { ...e, paneIndex, ...this._offsetAnchors(e, paneIndex), ...(shown(e) ? {} : { intervals: undefined }) } as DrawingInput; // `_insert` reads no range there
    });
    this._history._pushUndo();
    const created = prepared.map((p) => this._insert(p));
    this._sync();
    for (const d of created) this._chart.emit('draw:add', { drawing: d });
    this._emitChange(created.map((d) => d.id), 'add');
    this._chart.emit('draw:paste', { drawings: created });
    this.select(created.map((d) => d.id));
    return created;
  }

  /** Resolve an id list to live drawings; defaults to the selection. */
  private _targets(target?: string | readonly string[] | null): Drawing[] {
    const ids = target === undefined || target === null ? this._selection
      : typeof target === 'string' ? [target] : target;
    const out: Drawing[] = [];
    for (const id of ids) {
      const d = this.get(id);
      if (d !== undefined && !out.includes(d)) out.push(d);
    }
    return out;
  }

  /** The slot this chart keeps its price pane in, read at each use because a host can move it. */
  private _pricePane(): number {
    return this._chart.primaryPaneIndex?.() ?? 0;
  }

  /**
   * Drawings as the clipboard carries them: panes counted price pane first,
   * the study panes after it in their order, the way a portable template
   * counts them. A price pane at the top, where every build before the move
   * kept it, is written exactly as before, and a drawing copied beside the
   * candles pastes beside the candles on any chart in any arrangement.
   */
  private _portable(list: readonly Drawing[]): Drawing[] {
    const price = this._pricePane();
    return list.map((d) => ({ ...d, paneIndex: d.paneIndex === price ? 0 : d.paneIndex < price ? d.paneIndex + 1 : d.paneIndex }));
  }

  /**
   * Fold a clipboard pane onto a pane this chart actually has: clamped to the
   * pane count in clipboard order, so a study drawing from a taller stack
   * lands on the last study pane rather than on the price pane, then put in
   * this chart's own slots around its price pane.
   */
  private _clampPane(paneIndex: number): number {
    const panes = this._chart.panes;
    const n = panes === undefined ? paneIndex + 1 : panes.call(this._chart).length;
    const slot = n === 0 ? 0 : Math.min(paneIndex, n - 1), price = this._pricePane();
    return slot === 0 ? price : slot <= price ? slot - 1 : slot;
  }

  /**
   * A copy's anchors, offset from the original's in its own space. A viewport
   * copy moves the paste offset in pixels on both axes, as a fraction of the
   * pane it lands on, so it reads the same on a chart of any size, and stays
   * on that pane's plot when the original sits at its edge.
   */
  private _offsetAnchors(d: Omit<Drawing, 'id'>, paneIndex: number): Pick<Drawing, 'points' | 'viewportPoints'> {
    if (d.space !== 'viewport') return { points: this._offsetPoints(d.points, paneIndex) };
    const anchors = d.viewportPoints ?? [];
    const frame = this._screen.plotFrame(paneIndex);
    const px = this._opts.pasteOffsetPixels;
    return {
      points: [],
      viewportPoints: frame === null ? anchors.map((p) => ({ x: p.x, y: p.y })) : this._screen.shiftPinned({ ...d, id: '' }, anchors, px, px, frame),
    };
  }

  /** Nudge every anchor so a pasted copy is not hidden under its original. */
  private _offsetPoints(points: readonly DrawingPoint[], paneIndex: number): DrawingPoint[] {
    const dt = this._screen.barSeconds() * this._opts.pasteOffsetBars;
    const px = this._opts.pasteOffsetPixels;
    return points.map((p) => ({ time: p.time + dt, price: this._screen.offsetPrice(p.price, paneIndex, px) }));
  }

  /**
   * Move a study's input anchor (a price input declared with `timeKey` and
   * `anchor: true`) to `point` as the user, the way dragging its handle does:
   * the time snaps to the bar under it, both halves stay inside the bounds the
   * inputs declare, a study the user may not configure refuses it, and the move
   * is one undo step in this history. For a host control that sets the point
   * another way, such as a point pick on the chart, so Undo takes it back like
   * a drag. A point written through the study's settings instead (a settings
   * dialog's Pick point) is one step of this history as well, unless it is
   * written inside `untracked` or forced on a study the user may not
   * configure, which are the host's own. False when the study has no anchor for `key` (or the controller was
   * built without input anchors), the study refuses, or it already holds the point.
   */
  public moveInputAnchor(studyId: string, key: string, point: { time: number; price: number }): boolean {
    return this._anchors?.move(studyId, key, point.time, point.price) ?? false;
  }

  /**
   * Hand the step each study input anchor move makes (a handle dragged, a
   * `moveInputAnchor`) to a timeline of the host's instead of this history,
   * until the returned function gives them back. For a host keeping one undo
   * history for the whole chart that already records the settings patch the
   * move writes, as the widget's `ChartHistory` does: held here as well, one
   * move would be taken back twice, and a press here would reach a step the
   * other timeline had already taken back. `record` is called once the patch
   * is written, in the same turn, with the step's own `undo` and `redo`
   * (each false once the settings have moved on from it); this history
   * records nothing for it and emits no `drawing:change`. A move made inside
   * `untracked` is the host's own and reaches neither. A later call takes
   * the steps from an earlier one. A point written to the settings some other
   * way, which this history otherwise holds as a step of its own, is not
   * handed over: the host's timeline sees that write itself.
   */
  public delegateInputAnchorSteps(record: (step: InputAnchorStep) => void): () => void {
    this._anchorSteps = record;
    return () => { if (this._anchorSteps === record) this._anchorSteps = null; };
  }

  // ── history and persistence ─────────────────────────────────────────────

  public undo(): boolean {
    return this._history.undo();
  }

  public redo(): boolean {
    return this._history.redo();
  }

  /** Drop selected ids the model no longer holds, or that can no longer be selected. */
  private _pruneSelection(): void {
    const next = this._selection.filter((id) => this._selectable(id));
    if (!sameIds(next, this._selection)) this._setSelection(next);
  }

  public canUndo(): boolean { return this._history._undo.length > 0; }
  public canRedo(): boolean { return this._history._redo.length > 0; }

  /**
   * The steps each branch holds, oldest first, by the number `drawing:change`
   * reported them under. For a host that keeps one timeline across drawings
   * and its own edits: a step missing from both branches has been taken away
   * (a reset, a trim, a host edit that left it nothing to do), and pressing
   * undo for it would reach an older step instead. A step still being
   * recorded, a drag in progress, is not listed until its change closes it.
   */
  public historySteps(): { undo: number[]; redo: number[] } {
    const closed = (entry: DrawingHistoryEntry): boolean => entry !== this._history._pendingHistory;
    return { undo: this._history._undo.filter(closed).map(entry => entry.step), redo: this._history._redo.map(entry => entry.step) };
  }

  /**
   * Run `fn` as the host's own act. An edit it makes records no undo step and
   * leaves both branches as they are, and every step already recorded takes
   * it in, the way a forced call does, so no later undo or redo reverses it.
   * Unlike `force` it reaches no read-only drawing, and `undo` or `redo`
   * inside it still moves along the branches. For a host keeping one timeline
   * across drawings and its own changes, whose own changes are never steps.
   */
  public untracked<T>(fn: () => T): T {
    return this._history.untracked(fn);
  }

  /**
   * Serialisable document, the same shape `ChartState.drawings` carries.
   * Transient drawings (`policy.persistent` false) are left out, and so is
   * their group membership.
   */
  public toJSON(): DrawingsDocument {
    return this._document(this._drawings.filter(d => d.policy?.persistent !== false));
  }

  /** `drawings` as a document, with the groups narrowed to them. */
  private _document(drawings: readonly Drawing[]): DrawingsDocument {
    const groups = migrateGroups(this._groups, drawings);
    return { version: drawingsDocumentVersion(drawings), drawings: drawings.map(cloneDrawing), ...(groups.length ? { groups } : {}) };
  }

  /** Every drawing, transient ones too: an undo in the session reaches them. */
  private _historyText(): string {
    return JSON.stringify(this._document(this._drawings));
  }

  /**
   * Replace every drawing. Accepts a {@link DrawingsDocument} or a 1.9.x bare
   * `Drawing[]`; both go through the migration, so an old save upgrades on
   * load. Clears the selection and history.
   */
  public fromJSON(data: unknown): void {
    this.cancelDrag();
    this._gestures.reset();
    this._linkedPreviews.clear();
    const document = migrateDrawings(data);
    this._drawings = document.drawings;
    this._groups = document.groups ?? [];
    this._history._undo = [];
    this._history._redo = [];
    this._history._hostPatches.clear();
    this._history._pendingHistory = null;
    this._setSelection([]);
    this._sync();
    this._chart.emit('draw:restore', {});
    this._emitChange(this._drawings.map(drawing => drawing.id), 'update');
  }

  public destroy(): void {
    if (this._destroyed) return;
    this.cancelDrag();
    this._gestures.reset();
    this._gestures.setEraser(false);
    this._destroyed = true;
    this._linkedPreviews.clear();
    this._chart.emit('draw:destroy', { controller: this });
    this._anchors?.destroy();
    this._setPlacementMode(false);   // never leave the chart unable to pan
    for (const off of this._off) off();
    this._off.length = 0;
    for (const l of this._layerSet._layers.values()) {
      l.top.setBelow(null);
      this._chart.removePrimitive(l.top);
      this._chart.removePrimitive(l.bottom);
      for (const layer of l.series.values()) this._chart.removePrimitive(layer);
    }
    this._layerSet._layers.clear();
  }

  // ── interaction ─────────────────────────────────────────────────────────

  private _onCrosshair(p: CrosshairPayload): void {
    const barTime = p.time ?? null;
    // No hovered bar does not mean the pointer left the plot. Empty time-axis
    // space still has a drawable position, while legends retain their null bar.
    const time = barTime ?? (p.point ? this._chart.coordinateToTime?.(p.point.x) ?? null : null);
    const price = p.price ?? null;
    const paneIndex = p.paneIndex ?? null;
    this._lastCursor = time === null || !Number.isFinite(time) || price === null || paneIndex === null
      ? null : { time, price, paneIndex };
    const bar = p.bar ?? null;
    this._lastBar = bar === null || barTime === null ? null : { time: barTime, ...bar };
    this._noteKeys(p);
    this._notePointer(p);
    this._gestures.pointer({ paneIndex, point: p.point ?? null, pressed: p.pressed === true, keys: keysOf(p), touch: this._pointerKind === 'touch' });
    // The pointer left the plot: nothing is under it any more.
    if (time === null && price === null) this._setHovered(null);
    // Freehand tools ink while the pointer is held rather than on clicks.
    if (this._tool !== null && p.pressed === true && this._isFreehand()
      && time !== null && price !== null && paneIndex !== null
      && Number.isFinite(time) && Number.isFinite(price)) {
      for (const q of this._screen.coalesced(p, { time, price }, paneIndex)) this._inkPoint(q, paneIndex);
      return;
    }
    this._layerSet._syncSnapRing();
    // A tool mid-placement previews against the live cursor, and so does a ruler.
    if ((this._tool !== null && this._pending.length > 0) || this._gestures.follow(this._lastCursor)) this._layerSet._syncPreview();
  }

  /** The chart's hit-test answer for the pointer position, whenever it changes. */
  private _onHover(p: { id?: string | null }): void {
    const id = p.id ?? null;
    this._gestures.hover(id);
    const hit = id !== null && id.startsWith('draw:') ? id.slice('draw:'.length).split('#')[0]! : null; // a split has a first part
    // What cannot be selected is not a target for the keys either.
    this._setHovered(hit !== null && this._selectable(hit) ? hit : null);
  }

  private _setHovered(id: string | null): void {
    if (id === this._hovered) return;
    this._hovered = id;
    for (const layer of this._layerSet._allLayers()) layer.setHovered(id);
    this._chart.emit('drawing:hover', { id });
  }

  /** Remember the device behind a report and size the layers' targets for it. */
  private _notePointer(p: PointerFacts): void {
    const kind = pointerKindOf(p);
    if (kind === this._pointerKind) return;
    this._pointerKind = kind;
    for (const layer of this._layerSet._allLayers()) layer.setPointerType(kind);
  }

  /**
   * Let a tool turn the clicked anchors into its full set (the position tools
   * build a 1:1 box off one click). Identity for tools without the hook.
   */
  private _expand(tool: DrawingTool, clicked: DrawingPoint[]): DrawingPoint[] {
    if (tool.expand === undefined) return clicked;
    const range = this._chart.getVisibleLogicalRange();
    const visibleBars = range === null ? 60 : Math.max(1, range.to - range.from);
    const pane = this._pendingPane;
    // The pixel mapping is offered only when the host has one, so a tool can
    // tell "cannot map" from "mapped to nothing" and size in chart units.
    const mapped = this._chart.timeToCoordinate !== undefined && this._chart.priceToCoordinate !== undefined
      && this._chart.coordinateToTime !== undefined && this._chart.coordinateToPrice !== undefined;
    const expanded = tool.expand(clicked, {
      barSeconds: this._screen.barSeconds(),
      visibleBars,
      ...(mapped ? {
        toPixel: (p: DrawingPoint) => this._screen.toPixel(p, pane),
        fromPixel: (at: ScreenPoint) => this._screen.fromPixel(at, pane),
      } : {}),
    });
    return tool.constrain === undefined ? expanded : tool.constrain(expanded, null);
  }

  private _isFreehand(): boolean {
    return this._tool !== null && getDrawingTool(this._tool).freehand === true;
  }

  /**
   * Append one sample to the stroke in progress. Points arriving closer than a
   * bar-eighth apart in time carry no shape and would bloat the saved drawing,
   * so they collapse into the last one: a pointer can fire far faster than the
   * stroke actually changes direction.
   */
  private _inkPoint(point: DrawingPoint, paneIndex: number): void {
    if (this._pending.length === 0) {
      this._pendingPane = paneIndex;
    } else if (paneIndex !== this._pendingPane) {
      return;                       // a stroke belongs to the pane it started in
    } else {
      const last = this._pending[this._pending.length - 1]!; // not empty on this branch
      if (last.time === point.time && last.price === point.price) return;
    }
    this._pending.push(point);
    this._layerSet._syncPreview();
  }

  /** Commit `pts` as a drawing of the armed tool and leave placement. */
  private _commit(pts: DrawingPoint[]): void {
    const tool = getDrawingTool(this._tool as string);
    const pane = this._pendingPane;
    // Placement runs in data space, where the preview already works; a tool
    // armed for the viewport converts at the moment it lands, which is
    // exactly where each anchor was clicked (the magnet does not pull for
    // it). Its box is measured with the text the drawing will be given.
    const text = tool.defaultText === undefined ? {} : { text: { ...tool.defaultText } };
    const viewportAnchors = this._toolSpace === 'viewport'
      ? this._screen.toViewport(pts, pane, { id: '', tool: tool.id, points: [], style: {}, paneIndex: pane, zIndex: 0, ...text })
      : null;
    const created = this.add(viewportAnchors === null
      ? { tool: tool.id, points: pts, style: {}, paneIndex: pane }
      : { tool: tool.id, points: [], space: 'viewport', viewportPoints: viewportAnchors, style: {}, paneIndex: pane });
    this._pending = [];
    if (!this._opts.stayInDrawingMode) {
      this._tool = null;
      this._toolSpace = 'data';
      this._setPlacementMode(this._placementWanted());   // hand panning back to the chart
    }
    this._layerSet._syncPreview();
    this._layerSet._syncSnapRing();
    this.select(created.id);
    this._emitTool();
  }

  /**
   * Commit the stroke a freehand gesture built, if it has any extent. The
   * samples are thinned first: a pointer reports every few px, and a stroke
   * kept whole costs a time and price conversion per sample on every frame
   * and a row per sample in every save, for a curve the eye cannot tell from
   * the thinned one. Thinning happens in screen space, since the tolerance is
   * a pixel one; a host that cannot map to pixels keeps every sample.
   */
  private _finishFreehand(): void {
    const pts = this._pending;
    this._pending = [];
    if (pts.length < 2) {           // a tap is not a stroke
      this._layerSet._syncPreview();
      return;
    }
    this._commit(this._screen.thinStroke(pts, this._pendingPane));
  }

  /**
   * End a variable-anchor shape (polyline, path) at the anchors placed so far.
   * Those tools declare `points: 0`, so nothing else can ever complete them;
   * without this they collected vertices forever. Bound to double-click, and
   * public so a host can offer Esc / Enter too. No-op when there is nothing
   * placeable, so a stray double-click costs nothing.
   */
  public finish(): boolean {
    if (this._tool === null || this._pending.length === 0) return false;
    const tool = getDrawingTool(this._tool);
    if (tool.points !== 0 || tool.freehand === true) return false;
    const pts = this._pending;
    if (pts.length < 2) {           // a single vertex is not a shape
      this._pending = [];
      this._layerSet._syncPreview();
      return false;
    }
    this._commit(pts);
    return true;
  }

  /**
   * Abandon whatever is being placed: the anchors so far are dropped and,
   * unless the controller stays in drawing mode, the tool is disarmed too, so
   * one Escape returns the chart to the cursor the way a finished shape
   * would. With nothing pending, an armed tool is simply disarmed. Returns
   * whether anything changed, so a host can let the key fall through when it
   * did nothing.
   */
  public cancel(): boolean {
    if (this.cancelDrag() || this._gestures.endMeasure() || this._gestures.setEraser(false)) return true;
    if (this._tool === null) return false;
    const hadPending = this._pending.length > 0;
    this._pending = [];
    if (!hadPending || !this._opts.stayInDrawingMode) {
      this._tool = null;
      this._toolSpace = 'data';
      this._setPlacementMode(this._placementWanted());
      this._layerSet._syncPreview();
      this._layerSet._syncSnapRing();
      this._chart.emit('draw:tool', { tool: null });
      return true;
    }
    this._layerSet._syncPreview();
    return true;
  }

  /**
   * Remove the last anchor placed on a variable-anchor tool (polyline, path)
   * still being drawn: the Backspace of placement. A fixed-anchor tool has
   * nothing to pop, since its anchors commit the moment the last one lands,
   * and a freehand stroke is one gesture rather than a list. Returns whether
   * an anchor went.
   */
  public popAnchor(): boolean {
    if (this._tool === null || this._pending.length === 0) return false;
    const tool = getDrawingTool(this._tool);
    if (tool.points !== 0 || tool.freehand === true) return false;
    this._pending.pop();
    this._layerSet._syncPreview();
    return true;
  }

  private _onClick(p: ClickPayload): void {
    this._notePointer(p);
    if (this._gestures.click({ ...p, keys: keysOf(p) })) return;
    // Placement takes precedence: while a tool is armed, a click is an anchor.
    if (this._tool !== null) {
      // A freehand stroke was already collected move-by-move; the click pair a
      // drag produces is its end signal, not two more anchors.
      if (this._isFreehand()) {
        if (p.viaDrag === true) this._finishFreehand();
        return;
      }
      // The release half of a drag only means something while a shape is part
      // way through. A single-anchor tool (text, horizontal line) is already
      // finished by the press, so treating the release as another anchor would
      // drop a second drawing wherever the user let go.
      if (p.viaDrag === true && this._pending.length === 0) return;
      // Reject an unmappable click outright: a NaN anchor serialises as null
      // and produces a drawing that can never be rendered or hit-tested.
      if (p.price === null || !Number.isFinite(p.price) || !Number.isFinite(p.time)) return;
      this._noteKeys(p);
      this._placePoint(this._aimPoint({ time: p.time, price: p.price }, p.paneIndex), p.paneIndex);
      return;
    }
    // Shift, Ctrl or Cmd adds to the selection.
    const additive = (['shift', 'ctrl', 'meta'] as const).some(key => held(p, key));
    if (p.id !== null && p.id.startsWith('draw:')) {
      this.select(p.id.slice('draw:'.length).split('#')[0]!, additive); // a split has a first part
      return;
    }
    // A click on empty space clears, unless it is the additive gesture, which
    // on nothing means nothing.
    if (p.id === null && !additive) this.select(null);
  }

  private _placePoint(point: DrawingPoint, paneIndex: number): void {
    if (this._pending.length === 0) this._pendingPane = paneIndex;
    this._pending.push(point);
    const tool = getDrawingTool(this._tool as string);
    if (tool.points > 0 && this._pending.length >= tool.points) {
      this._commit(this._expand(tool, this._pending));
    } else {
      this._layerSet._syncPreview();
    }
  }

  /**
   * Where a click at `point` actually lands for the armed tool: on the 45
   * degree lock while Shift holds the free end of a line, else on the magnet
   * when it pulls, else where it was. The lock wins over the magnet because a
   * snapped price would bend the exact angle the lock exists to give.
   */
  private _aimPoint(point: DrawingPoint, paneIndex: number): DrawingPoint {
    const locked = this._lockedPoint(point, paneIndex);
    if (locked !== null) return locked;
    return this._snapPoint(point, paneIndex) ?? point;
  }

  /**
   * The free end of a two-anchor line under angle lock, or null when the lock
   * does not apply: no Shift, a tool without the flag, no anchor yet to
   * measure from, or a host that cannot map pixels (the lock is a screen
   * angle, so there is nothing to lock to in data space).
   */
  private _lockedPoint(point: DrawingPoint, paneIndex: number): DrawingPoint | null {
    if (!this._shift || this._tool === null || this._pending.length !== 1) return null;
    if (getDrawingTool(this._tool).angleLock !== true || paneIndex !== this._pendingPane) return null;
    return this._screen.lockAngle(this._pending[0]!, point, paneIndex); // exactly one, checked above
  }

  /**
   * Where the magnet lands `point`, or null when it does not pull: the
   * nearest O/H/L/C of `bar` on the price pane, the nearest plotted value on
   * a study pane (`snap.ts`). Ctrl held pulls as the strong magnet whatever
   * the mode. A placement reads the bar the chart reported under the
   * pointer; a drag, which reports none, passes the bar under its time.
   */
  private _snapPoint(point: DrawingPoint, paneIndex: number, bar: SnapBar | null = this._lastBar): DrawingPoint | null {
    const mode = this._strong ? 'strong' : this._opts.magnet;
    // A drawing pinned to the screen lands where it is clicked: a bar's price
    // is no reference for something that will not follow the bars.
    if (mode === 'off' || this._toolSpace === 'viewport') return null;
    return magnetPoint(this._chart, point, paneIndex, mode, this._pricePane(), bar);
  }

  /** Shift and Ctrl (Cmd) as the last pointer report carried them: the angle lock and the strong magnet. */
  private _noteKeys(p: PointerFacts & { shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean }): void {
    this._shift = held(p, 'shift');
    this._strong = this._opts.gestures.snapModifier && (held(p, 'ctrl') || held(p, 'meta'));
  }

  /** Roll back an interrupted drag and leave the pre-gesture undo/redo stacks intact. */
  public cancelDrag(): boolean {
    return this._drag.cancelDrag();
  }

  /**
   * The drawing's anchors in container media px, the space `timeToCoordinate`
   * and `priceToCoordinate` answer in, whichever space it is anchored in. What
   * a host places an overlay by (an inline editor, a popover). Null for an
   * unknown id, or when the drawing's pane has no place on screen (folded to
   * a strip, or hidden behind a maximized pane).
   */
  public screenPoints(id: string): ScreenPoint[] | null {
    const d = this.get(id);
    if (d === undefined) return null;
    if (d.space !== 'viewport') {
      const out: ScreenPoint[] = [];
      for (const p of d.points) {
        const at = this._screen.toPixel(p, d.paneIndex);
        if (at === null) return null;
        out.push(at);
      }
      return out;
    }
    const frame = this._screen.plotFrame(d.paneIndex);
    if (frame === null) return null;
    return placeViewportAnchors(d, d.viewportPoints ?? [], frame.width, frame.height)
      .map((p) => ({ x: frame.left + p.x, y: frame.top + p.y }));
  }

  // ── plumbing ────────────────────────────────────────────────────────────

  /** Push the current list into each pane's layers and into the chart state. */
  private _sync(): void {
    this._groups = migrateGroups(this._groups, this._drawings);
    this._layerSet._syncLayers();
    // A hover or a selection on a drawing that has just gone, or has just
    // been made unselectable, would otherwise outlive it until the pointer
    // next moves.
    this._pruneSelection();
    if (this._hovered !== null && (!this._selectable(this._hovered) || !this.shownOnInterval(this._hovered))) this._setHovered(null);
    this._chart.setDrawingState(this.toJSON());
  }

}

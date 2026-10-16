/**
 * Drawings shared between linked charts of one instrument: a drawing made,
 * moved or removed on one chart is made, moved or removed on the others,
 * each with its own undo history. A shared drawing carries a lineage mark in
 * its props, so the link finds it again after a restore.
 */
import { DRAWING_LINK_METADATA_KEY, type DrawingController, type DrawingChartHost } from './controller';
import type { Drawing } from './types';
import { cloneDrawing } from './clipboard';

/** Both fields must be known. A host may use its feed namespace as the exchange. */
export interface DrawingLinkContext { symbol?: string; exchange?: string }
/** Resolve a host-owned identity without modifying the chart's data context. */
export type DrawingLinkContextSource = DrawingLinkContext | (() => DrawingLinkContext | null | undefined);
export interface DrawingLinkOptions { enabled?: boolean }
export interface DrawingLinkChart extends Pick<DrawingChartHost, 'on' | 'primaryPaneIndex'> {
  readonly isDestroyed?: boolean;
  getDataContext?(): Readonly<DrawingLinkContext> | undefined;
}

interface Member {
  chart: DrawingLinkChart;
  controller: DrawingController;
  context: string | null;
  resolveContext: (() => DrawingLinkContext | null | undefined) | null;
  drawings: Map<string, SharedDrawing>;
  off: (() => void)[];
}

interface Binding { id: string; local: boolean }
interface SharedDrawing {
  context: string;
  lineage: string;
  id: string;
  drawing: Drawing | null;
  bindings: Map<Member, Binding>;
  previewFrom: Member | null;
}

function contextKey(context: DrawingLinkContext | undefined): string | null {
  if (typeof context?.symbol !== 'string' || !context.symbol.trim()
    || typeof context.exchange !== 'string' || !context.exchange.trim()) return null;
  return JSON.stringify([context.symbol, context.exchange]);
}

function resolveContext(source: DrawingLinkContextSource | undefined): DrawingLinkContext | undefined {
  try { return (typeof source === 'function' ? source() : source) ?? undefined; }
  catch { return undefined; }
}

let nextLinkedId = 1;
let sessionId: string | undefined;
let nextLineage = 1;

/**
 * This page's lineage namespace, made when a group first shares a drawing.
 * Made then rather than on import, so a runtime without Web Crypto still
 * loads the tier, and is refused only when it links charts.
 */
function session(): string {
  if (sessionId === undefined) {
    const crypto = globalThis.crypto;
    if (typeof crypto?.randomUUID === 'function') sessionId = crypto.randomUUID();
    else if (typeof crypto?.getRandomValues !== 'function') throw new Error('openalgo-charts: drawing links require Web Crypto');
    else sessionId = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
  }
  return sessionId;
}

/**
 * Whether a drawing can travel between linked charts: on this chart's price
 * pane, in whatever slot it keeps there, and in data space. A viewport drawing
 * is a place on this chart's screen, and the same fraction of another chart's
 * pane would sit over different bars at a different size, so it stays on the
 * chart it was drawn on.
 */
const linkable = (drawing: Drawing, pricePane: number): boolean => drawing.paneIndex === pricePane && drawing.space !== 'viewport';

function lineageOf(drawing: Drawing, context: string): string | undefined {
  const value = drawing.props?.[DRAWING_LINK_METADATA_KEY] as { version?: unknown; id?: unknown; context?: unknown } | null | undefined;
  return value?.version === 1 && value.context === context && typeof value.id === 'string' && value.id.length > 0
    ? value.id : undefined;
}

/**
 * Existing local drawings stay local until `share` is called. Persisted shared
 * lineage reconnects across restores. Only price-pane drawings participate; time anchors
 * cross the boundary unchanged so each interval uses its own coordinate map.
 *
 * The price pane is each chart's own, in whatever slot that chart keeps it: one
 * chart can hold it at the top and another below its studies. A shared drawing
 * is therefore kept on slot 0 and put on each member's price pane as it is
 * applied there, never copied across by slot.
 *
 * A drawing pinned to the viewport never participates, and pinning a shared one
 * takes it out of the link on that chart alone: the other charts keep their copy.
 */
export class DrawingLinkGroup {
  private readonly _members = new Map<DrawingLinkChart, Member>();
  private _enabled: boolean;
  private _broadcasting = false;
  private _destroyed = false;

  public constructor(options: DrawingLinkOptions = {}) { this._enabled = options.enabled ?? false; }

  public options(): Required<DrawingLinkOptions> { return { enabled: this._enabled }; }

  public add(chart: DrawingLinkChart, controller: DrawingController, context?: DrawingLinkContextSource): void {
    if (this._destroyed || chart.isDestroyed === true || controller.isDestroyed) return;
    const existing = this._members.get(chart);
    if (existing?.controller === controller) {
      if (context !== undefined) {
        existing.resolveContext = typeof context === 'function' ? context : null;
        this.setContext(chart, resolveContext(context));
      }
      return;
    }
    if (existing !== undefined) this.remove(chart);
    const member: Member = { chart, controller,
      context: contextKey(resolveContext(context ?? (() => chart.getDataContext?.()))),
      resolveContext: typeof context === 'function' ? context : null, drawings: new Map(), off: [],
    };
    this._members.set(chart, member);
    for (const event of ['draw:add', 'draw:update', 'draw:remove']) {
      member.off.push(chart.on(event, payload => {
        const change = payload as { drawing?: Drawing; history?: boolean } | null;
        if (change?.drawing === undefined) return;
        this._change(member, change.drawing, event === 'draw:remove', event === 'draw:add' && change.history !== true);
      }));
    }
    member.off.push(
      chart.on('draw:preview', payload => {
        const drawings = (payload as { drawings?: Drawing[] } | null)?.drawings;
        if (drawings !== undefined) this._preview(member, drawings);
      }),
      chart.on('draw:preview-clear', () => this._clearMemberPreviews(member)),
      chart.on('drawing:change', payload => {
        if ((payload as { linked?: boolean } | null)?.linked !== true) this._syncOrder(member);
      }),
      chart.on('data:context', context => this.setContext(chart,
        member.resolveContext === null ? context as DrawingLinkContext | undefined : resolveContext(member.resolveContext))),
      chart.on('symbol', () => this.setContext(chart, resolveContext(member.resolveContext ?? undefined))),
      chart.on('draw:restore', () => { this._detachDrawings(member, false); this._reconnect(member); }),
      chart.on('draw:destroy', payload => {
        if ((payload as { controller?: DrawingController } | null)?.controller === controller) this.remove(chart);
      }),
      chart.on('destroy', () => this.remove(chart)),
    );
    this._reconnect(member);
  }

  public setOptions(options: DrawingLinkOptions): void {
    if (options.enabled === undefined || this._destroyed) return;
    if (!options.enabled) for (const member of this._members.values()) this._clearMemberPreviews(member);
    this._enabled = options.enabled;
    if (this._enabled) for (const member of this._members.values()) this._reconnect(member);
  }

  /** Report the current instrument. Unknown identity stops sharing immediately. */
  public setContext(chart: DrawingLinkChart, context: DrawingLinkContext | undefined): void {
    const member = this._members.get(chart);
    if (member === undefined) return;
    const key = contextKey(context);
    for (const shared of member.drawings.values()) this._clearPreview(shared);
    if (key === member.context) return;
    member.controller.cancelDrag();
    this._detachDrawings(member, true);
    member.context = key;
    this._reconnect(member);
  }

  /** Share selected ids, or every existing eligible drawing when ids are omitted. */
  public share(chart: DrawingLinkChart, ids?: readonly string[]): number {
    const member = this._members.get(chart);
    if (member === undefined || !this._eligible(member) || this._broadcasting) return 0;
    let count = 0;
    for (const id of new Set(ids ?? member.controller.drawings().map(d => d.id))) {
      const drawing = member.controller.get(id);
      if (drawing === undefined || !linkable(drawing, this._pricePane(member))) continue;
      const shared = member.drawings.get(id) ?? this._create(member, drawing);
      this._commit(shared, member, drawing, true);
      count++;
    }
    this._syncOrder(member);
    return count;
  }

  public has(chart: DrawingLinkChart): boolean { return this._members.has(chart); }

  /** Committed drawings remain on peers; transient previews are discarded. */
  public remove(chart: DrawingLinkChart): void {
    const member = this._members.get(chart);
    if (member === undefined) return;
    this._detachDrawings(member, false);
    for (const off of member.off) off();
    this._members.delete(chart);
  }

  public destroy(): void {
    this._destroyed = true;
    for (const chart of [...this._members.keys()]) this.remove(chart);
  }

  /** The slot this member keeps its price pane in, read at each use because it moves. */
  private _pricePane(member: Member): number {
    return member.chart.primaryPaneIndex?.() ?? 0;
  }

  /** A shared drawing as it lands on one member: on that member's own price pane. */
  private _onPricePane<T extends Drawing | null>(member: Member, drawing: T): T {
    return (drawing === null ? null : { ...drawing, paneIndex: this._pricePane(member) }) as T;
  }

  private _eligible(member: Member): boolean {
    return !this._destroyed && this._enabled && member.context !== null
      && this._members.get(member.chart) === member && member.chart.isDestroyed !== true && !member.controller.isDestroyed;
  }

  private _create(member: Member, drawing: Drawing): SharedDrawing {
    const context = member.context as string;
    const lineage = lineageOf(drawing, context) ?? `${session()}:${nextLineage++}`;
    for (const peer of this._members.values()) {
      for (const shared of peer.drawings.values()) {
        if (shared.context !== context || shared.lineage !== lineage) continue;
        shared.bindings.set(member, { id: drawing.id, local: true });
        member.drawings.set(drawing.id, shared);
        return shared;
      }
    }
    const shared: SharedDrawing = {
      id: drawing.id, context, lineage, drawing: cloneDrawing({ ...drawing, paneIndex: 0 }),
      bindings: new Map([[member, { id: drawing.id, local: true }]]), previewFrom: null,
    };
    member.drawings.set(drawing.id, shared);
    return shared;
  }

  private _reconnect(member: Member): void {
    if (this._broadcasting || !this._eligible(member)) return;
    const context = member.context as string;
    const authorities = new Set<Member>();
    this._broadcasting = true;
    try {
      for (const drawing of [...member.controller.drawings()]) {
        if (!linkable(drawing, this._pricePane(member)) || member.drawings.has(drawing.id)) continue;
        const lineage = lineageOf(drawing, context);
        if (lineage === undefined) continue;
        for (const peer of this._members.values()) {
          if (peer === member || !this._eligible(peer) || peer.context !== context) continue;
          let shared = [...peer.drawings.values()].find(value => value.context === context && value.lineage === lineage);
          if (shared === undefined) {
            const copy = peer.controller.drawings().find(value => linkable(value, this._pricePane(peer)) && lineageOf(value, context) === lineage);
            if (copy !== undefined) shared = this._create(peer, copy);
          }
          if (shared === undefined) continue;
          // A live peer is authoritative over an older saved copy, including
          // a deletion retained for undo. Unmarked local drawings never match.
          shared.bindings.set(member, { id: drawing.id, local: false });
          member.drawings.set(drawing.id, shared);
          member.controller.applyLinkedDrawing(drawing.id, this._onPricePane(member, shared.drawing));
          authorities.add(peer);
          break;
        }
      }
      for (const peer of authorities) this._orderFrom(peer, member);
    } finally { this._broadcasting = false; }
  }

  private _change(member: Member, drawing: Drawing, removed: boolean, added: boolean): void {
    if (this._broadcasting || !this._eligible(member) || drawing.paneIndex !== this._pricePane(member)) return;
    if (!removed && drawing.space === 'viewport') { this._unlink(member, drawing); return; }
    let shared = member.drawings.get(drawing.id);
    if (shared === undefined && !added && !removed) shared = this._rejoin(member, drawing);
    const first = shared === undefined && added;
    if (shared === undefined && added) shared = this._create(member, drawing);
    if (shared !== undefined) this._commit(shared, member, removed ? null : drawing, first);
  }

  /**
   * A shared drawing pinned to the screen leaves the link on this chart. Its
   * lineage mark goes too, or a restore would find the peers' copy by it and
   * pull the drawing back to where they keep it.
   */
  private _unlink(member: Member, drawing: Drawing): void {
    const shared = member.drawings.get(drawing.id);
    if (shared !== undefined) {
      this._clearPreview(shared);
      shared.bindings.delete(member);
      member.drawings.delete(drawing.id);
    }
    if (drawing.props?.[DRAWING_LINK_METADATA_KEY] === undefined) return;
    const props = { ...drawing.props };
    delete props[DRAWING_LINK_METADATA_KEY];
    this._broadcasting = true;
    try { member.controller.applyLinkedDrawing(drawing.id, { ...drawing, props }); } finally { this._broadcasting = false; }
  }

  /**
   * An unbound drawing that carries this chart's lineage mark, while a peer
   * still holds that lineage, is one that left the link by being pinned and
   * came back by undo: the undo put the mark back but no binding. It joins
   * again, as the newest edit, so its state goes to the peers the way any
   * other undo on a linked drawing does. If the peers have since deleted
   * their copies it stays on this chart alone and loses the mark, since an
   * edit never brings back another chart's deletion, and a later restore
   * must not apply that deletion here. A mark no peer holds is left for a
   * peer that has yet to join, as after any restore.
   */
  private _rejoin(member: Member, drawing: Drawing): SharedDrawing | undefined {
    const lineage = lineageOf(drawing, member.context as string);
    if (lineage === undefined || !linkable(drawing, this._pricePane(member))) return undefined;
    for (const peer of this._members.values()) {
      for (const shared of peer.drawings.values()) {
        if (shared.context !== member.context || shared.lineage !== lineage) continue;
        if (shared.drawing === null) { this._unlink(member, drawing); return undefined; }
        shared.bindings.set(member, { id: drawing.id, local: true });
        member.drawings.set(drawing.id, shared);
        return shared;
      }
    }
    return undefined;
  }

  private _commit(shared: SharedDrawing, from: Member, drawing: Drawing | null, includeNew: boolean): void {
    this._broadcasting = true;
    try {
      this._clearPreview(shared);
      const stamped = drawing === null ? null : { ...drawing, props: { ...drawing.props,
        [DRAWING_LINK_METADATA_KEY]: { version: 1, id: shared.lineage, context: shared.context },
      } };
      if (stamped !== null && lineageOf(drawing as Drawing, shared.context) !== shared.lineage) {
        from.controller.applyLinkedDrawing(drawing!.id, stamped);
      }
      shared.drawing = stamped === null ? null : cloneDrawing({ ...stamped, id: shared.id, paneIndex: 0 });
      for (const target of [...this._members.values()]) {
        if (target === from || !this._eligible(target) || target.context !== shared.context) continue;
        let binding = shared.bindings.get(target);
        if (binding === undefined) {
          if (drawing === null || !includeNew) continue;
          const restored = target.controller.drawings().find(d => linkable(d, this._pricePane(target))
            && !target.drawings.has(d.id) && lineageOf(d, shared.context) === shared.lineage);
          let id = restored?.id ?? shared.id;
          if (restored === undefined) {
            while (target.controller.get(id) !== undefined || target.drawings.has(id)) id = `linked${nextLinkedId++}`;
          }
          binding = { id, local: false };
          shared.bindings.set(target, binding);
          target.drawings.set(id, shared);
        }
        target.controller.applyLinkedDrawing(binding.id, this._onPricePane(target, shared.drawing));
      }
    } finally { this._broadcasting = false; }
  }

  private _preview(from: Member, drawings: readonly Drawing[]): void {
    if (this._broadcasting || !this._eligible(from)) return;
    for (const drawing of drawings) {
      const shared = from.drawings.get(drawing.id);
      if (shared === undefined) continue;
      shared.previewFrom = from;
      for (const [target, binding] of shared.bindings) {
        if (target !== from && this._eligible(target) && target.context === shared.context) {
          target.controller.setLinkedPreview(binding.id, this._onPricePane(target, drawing));
        }
      }
    }
  }

  private _syncOrder(from: Member): void {
    if (this._broadcasting || !this._eligible(from)) return;
    this._broadcasting = true;
    try {
      for (const target of this._members.values()) {
        if (target === from || !this._eligible(target) || target.context !== from.context) continue;
        this._orderFrom(from, target);
      }
    } finally { this._broadcasting = false; }
  }

  private _orderFrom(from: Member, target: Member): void {
    const ids = from.controller.drawings().map(d => from.drawings.get(d.id)?.bindings.get(target)?.id)
      .filter((id): id is string => id !== undefined);
    target.controller.reorderLinkedDrawings(ids);
  }

  private _clearPreview(shared: SharedDrawing): void {
    if (shared.previewFrom === null) return;
    for (const [member, binding] of shared.bindings) member.controller.setLinkedPreview(binding.id, null);
    shared.previewFrom = null;
  }

  private _clearMemberPreviews(member: Member): void {
    for (const shared of member.drawings.values()) {
      if (shared.previewFrom === member) this._clearPreview(shared);
    }
  }

  private _detachDrawings(member: Member, removeIncoming: boolean): void {
    for (const shared of member.drawings.values()) {
      const binding = shared.bindings.get(member);
      this._clearPreview(shared);
      shared.bindings.delete(member);
      if (removeIncoming && binding?.local === false) member.controller.applyLinkedDrawing(binding.id, null);
    }
    member.drawings.clear();
  }
}

export function createDrawingLinkGroup(options: DrawingLinkOptions = {}): DrawingLinkGroup {
  return new DrawingLinkGroup(options);
}

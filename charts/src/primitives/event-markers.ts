/** Time-anchored event badges. Event feeds and detail loading belong to the host. */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from './primitive';
import { isPlainObject } from '../helpers/validate';

export interface EventDetailField { label: string; value: string }

/** A run of text in a rich block, shown as text: nothing in it is read as markup. */
export interface EventDetailSpan {
  text: string;
  strong?: boolean;
  em?: boolean;
  /** Opened in a new tab when it is an absolute http or https URL; any other value shows the text alone. */
  href?: string;
}

/** One plain run, or runs with emphasis and links. */
export type EventDetailInline = string | readonly EventDetailSpan[];

/** Rich detail content as structure, never as markup, so a feed's text cannot run as code. */
export type EventDetailBlock =
  | { type: 'heading' | 'paragraph'; text: EventDetailInline }
  | { type: 'list'; items: readonly EventDetailInline[] };

/** Detail content. Every string is plain text: none is interpreted as markup. */
export interface ChartEventDetails {
  summary?: string;
  fields?: readonly EventDetailField[];
  /** Headings, paragraphs and lists shown after the fields. */
  blocks?: readonly EventDetailBlock[];
}

export interface ChartEvent {
  /** Original UTC timestamp in seconds, including times between candles. */
  time: number;
  type: 'earnings' | 'dividend' | 'split' | 'news' | string;
  label: string;
  color?: string;
  id?: string;
  title?: string;
  details?: string | ChartEventDetails;
  group?: string;
}

export interface EventGroup {
  id: string;
  label: string;
  parentId?: string;
  /** Local visibility. A hidden ancestor also hides this group. */
  visible?: boolean;
}

export interface EventMarkersOptions {
  /** Combine nearby badges. Defaults to false. */
  clustering: boolean;
  /** Maximum distance between cluster members in CSS pixels, from 1 to 200. Default 18. */
  clusterRadius: number;
}

export interface EventMarkerDetails {
  id: string;
  cluster: boolean;
  /** Independent copies, in timestamp order. */
  events: ChartEvent[];
}

const TYPE_COLOR: Record<string, string> = {
  earnings: '#f0a020',
  dividend: '#26a69a',
  split: '#4f8cff',
  news: '#9aa0b4',
};

/**
 * Details copied all the way down, so a caller's later edits cannot reach an
 * installed event: fields and blocks arrive from feeds in any shape. Only
 * arrays and plain objects (a record without a prototype among them) are
 * copied; anything else is shared, as before.
 */
function copyData<T>(value: T): T {
  if (Array.isArray(value)) return value.map(copyData) as T;
  if (!isPlainObject(value)) return value;
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, copyData(v)])) as T;
}

/** An event a caller can keep: the widget's details popup copies with this too. */
export function copyEvent(event: ChartEvent): ChartEvent {
  return { ...event, ...(typeof event.details === 'object' ? { details: copyData(event.details) } : {}) };
}

interface Entry { event: ChartEvent; key: string }
/** A badge starts from one entry and only ever gains more. */
interface Badge { x: number; firstX: number; entries: [Entry, ...Entry[]] }
interface Position { id: string; x: number; y: number; r: number; entries: Entry[] }

export class EventMarkers implements IPrimitive {
  private _entries: Entry[] = [];
  private _groups = new Map<string, EventGroup>();
  private _options: EventMarkersOptions = { clustering: false, clusterRadius: 18 };
  private _host: PrimitiveHost | null = null;
  private _positions: Position[] = [];
  private _hits = new Map<string, Position>();
  private _providedIds = new Set<string>();
  private _duplicateIds = new Set<string>();
  private _width = 0;
  private _height = 0;

  public constructor(options: Partial<EventMarkersOptions> = {}) { this.setOptions(options); }
  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; this._invalidate(); }
  public zOrder(): ZOrder { return 'normal'; }

  /** Replace data atomically. Caller mutations never change installed events. */
  public setEvents(events: readonly ChartEvent[]): void {
    const sorted = events.map(event => {
      if (!Number.isFinite(event.time)) throw new Error('openalgo-charts: event time must be finite');
      return copyEvent(event);
    }).sort((a, b) => a.time - b.time);
    const counts = new Map<string, number>();
    this._entries = sorted.map(event => {
      const identity = event.id === undefined
        ? JSON.stringify([event.time, event.type, event.label, event.group ?? null])
        : JSON.stringify(event.id);
      const occurrence = counts.get(identity) ?? 0;
      counts.set(identity, occurrence + 1);
      return { event, key: `${identity}:${occurrence}` };
    });
    this._providedIds = new Set(sorted.flatMap(event => event.id === undefined ? [] : [event.id]));
    this._duplicateIds = new Set([...this._providedIds].filter(id => (counts.get(JSON.stringify(id)) ?? 0) > 1));
    this._invalidate();
  }

  public events(): ChartEvent[] { return this._entries.map(entry => copyEvent(entry.event)); }

  /** Replace the hierarchy; duplicate IDs, missing parents and cycles are rejected. */
  public setGroups(groups: readonly EventGroup[]): void {
    const next = new Map<string, EventGroup>();
    for (const group of groups) {
      if (!group.id || next.has(group.id)) throw new Error('openalgo-charts: event group IDs must be nonempty and unique');
      next.set(group.id, { ...group });
    }
    const complete = new Set<string>();
    for (const id of next.keys()) {
      const path = new Set<string>();
      let current: string | undefined = id;
      while (current !== undefined && !complete.has(current)) {
        if (path.has(current)) throw new Error('openalgo-charts: event group cycle');
        const group = next.get(current);
        if (group === undefined) throw new Error('openalgo-charts: event group parent is missing');
        path.add(current);
        current = group.parentId;
      }
      for (const visited of path) complete.add(visited);
    }
    this._groups = next;
    this._invalidate();
  }

  public groups(): EventGroup[] { return Array.from(this._groups.values(), group => ({ ...group })); }

  public setGroupVisible(id: string, visible: boolean): void {
    const group = this._groups.get(id);
    if (group === undefined) throw new Error(`openalgo-charts: unknown event group ${id}`);
    group.visible = visible;
    this._invalidate();
  }

  /** Ungrouped events and group IDs not yet configured remain visible. */
  public isGroupVisible(id: string): boolean {
    let group = this._groups.get(id);
    while (group !== undefined) {
      if (group.visible === false) return false;
      group = group.parentId === undefined ? undefined : this._groups.get(group.parentId);
    }
    return true;
  }

  public setOptions(options: Partial<EventMarkersOptions>): void {
    const radius = options.clusterRadius ?? this._options.clusterRadius;
    if (!Number.isFinite(radius) || radius < 1 || radius > 200) {
      throw new Error('openalgo-charts: event clusterRadius must be from 1 to 200');
    }
    this._options = { clustering: options.clustering ?? this._options.clustering, clusterRadius: radius };
    this._invalidate();
  }

  public options(): EventMarkersOptions { return { ...this._options }; }

  /** Resolve only hits from the latest layout, with independent member details. */
  public detailsForHit(externalId: string): EventMarkerDetails | null {
    const hit = this._hits.get(externalId);
    return hit === undefined ? null : {
      id: hit.id, cluster: hit.entries.length > 1, events: hit.entries.map(entry => copyEvent(entry.event)),
    };
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this._positions = [];
    this._hits.clear();
    this._width = rc.plotWidth;
    this._height = rc.plotHeight;
    if (this._entries.length === 0 || !(rc.dpr > 0) || !Number.isFinite(rc.dpr)
      || !(rc.plotWidth > 0) || !(rc.plotHeight > 0)) return;
    const badges: Badge[] = [];
    for (const entry of this._entries) {
      if (entry.event.group !== undefined && !this.isGroupVisible(entry.event.group)) continue;
      const index = rc.dataLayer.timeToIndexFloat(entry.event.time);
      const x = rc.timeScale.indexToX(index);
      if (!Number.isFinite(x)) continue;
      const last = badges[badges.length - 1];
      if (this._options.clustering && last !== undefined && x - last.firstX <= this._options.clusterRadius) {
        last.entries.push(entry);
        last.x += (x - last.x) / last.entries.length;
      } else badges.push({ x, firstX: x, entries: [entry] });
    }
    const r = 8;
    const cy = rc.plotHeight - r - 4;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, rc.plotWidth * rc.dpr, rc.plotHeight * rc.dpr);
    ctx.clip();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = `${10 * rc.dpr}px system-ui, sans-serif`;
    for (const badge of badges) {
      if (badge.x + r < 0 || badge.x - r > rc.plotWidth || cy + r < 0) continue;
      const ev = badge.entries[0].event;
      const cluster = badge.entries.length > 1;
      let id = ev.id;
      if (cluster || id === undefined || this._duplicateIds.has(id)) {
        id = `${cluster ? 'event-cluster:' : 'event:'}${JSON.stringify(badge.entries.map(entry => entry.key).sort())}`;
        // Host IDs remain exact even when they use our generated-handle prefix.
        while (this._providedIds.has(id)) id = ':' + id;
      }
      ctx.fillStyle = ev.color ?? TYPE_COLOR[ev.type] ?? '#9aa0b4';
      ctx.beginPath();
      ctx.arc(badge.x * rc.dpr, cy * rc.dpr, r * rc.dpr, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#0d0e12';
      const label = cluster ? (badge.entries.length > 99 ? '99+' : String(badge.entries.length)) : ev.label.slice(0, 2);
      ctx.fillText(label, badge.x * rc.dpr, cy * rc.dpr);
      const position = { id, x: badge.x, y: cy, r, entries: badge.entries };
      this._positions.push(position);
      this._hits.set(id, position);
    }
    ctx.restore();
  }

  public hitTest(x: number, y: number): PrimitiveHit | null {
    if (x < 0 || y < 0 || x > this._width || y > this._height) return null;
    let best: PrimitiveHit | null = null;
    for (const p of this._positions) {
      const d = Math.hypot(p.x - x, p.y - y);
      if (d <= p.r && (best === null || d <= best.distance)) {
        best = { externalId: p.id, zOrder: 'normal', distance: d, cursor: 'pointer' };
      }
    }
    return best;
  }

  private _invalidate(): void {
    this._positions = [];
    this._hits.clear();
    this._host?.requestUpdate();
  }
}

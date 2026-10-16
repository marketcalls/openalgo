import type { PriceScaleId } from './series';

/**
 * Whether a value is a {@link PriceScaleId}. The one copy of the rule: a scale
 * id arrives untyped from saved state and script hosts, and a pane answers its
 * right scale for any id it does not know, so every reader checks here first.
 */
export function isPriceScaleId(value: unknown): value is PriceScaleId {
  return typeof value === 'string' && (value === 'right' || value === 'left' || value === '' || value.startsWith('overlay:'));
}

export type PriceAxisSide = 'left' | 'right' | 'hidden';

/** Placement is independent of scale identity, formatting and numeric range. */
export interface PriceAxisPlacement {
  side: PriceAxisSide;
  /** Zero is nearest the plot; hidden scales retain an order for restoration. */
  order: number;
}

/** A visible axis column. Chart.priceAxisLayout returns x in pane CSS coordinates. */
export interface PriceAxisSlot {
  scaleId: PriceScaleId;
  side: 'left' | 'right';
  order: number;
  x: number;
  width: number;
}

const sides: readonly PriceAxisSide[] = ['left', 'right', 'hidden'];

function defaultSide(id: PriceScaleId): PriceAxisSide {
  return id === 'left' || id === 'right' ? id : 'hidden';
}

/** Retains placement for vacant scales; a pane decides which registered scales are active. */
export class PriceAxisLayout {
  private readonly _configured = new Set<PriceScaleId>();
  private readonly _placements = new Map<PriceScaleId, PriceAxisPlacement>([
    ['right', { side: 'right', order: 0 }],
  ]);

  register(id: PriceScaleId): void {
    if (isPriceScaleId(id) && !this._placements.has(id)) this._placements.set(id, this.get(id));
  }

  /** A prospective default does not create a scale merely because a caller inspects it. */
  get(id: PriceScaleId): PriceAxisPlacement {
    const value = this._placements.get(id);
    if (value) return { ...value };
    const side = defaultSide(id);
    let order = 0;
    for (const placement of this._placements.values()) if (placement.side === side) order++;
    return { side, order };
  }

  /** Insert at a clamped rank. An omitted rank retains the current side's order or appends. */
  set(id: PriceScaleId, side: PriceAxisSide, order?: number): boolean {
    if (!isPriceScaleId(id) || !sides.includes(side)
      || (order !== undefined && (!Number.isSafeInteger(order) || order < 0))) return false;
    const previous = this.get(id);
    const destination = this._sideIds(side).filter(value => value !== id);
    const rank = Math.min(order ?? (previous.side === side ? previous.order : destination.length), destination.length);
    if (previous.side === side && previous.order === rank) return false;
    this.register(id);
    destination.splice(rank, 0, id);
    if (previous.side !== side) this._reorder(previous.side, this._sideIds(previous.side).filter(value => value !== id));
    this._reorder(side, destination);
    return true;
  }

  /** Registration order is stable even when a scale changes side or rank. */
  entries(): readonly { scaleId: PriceScaleId; side: PriceAxisSide; order: number }[] {
    return Array.from(this._placements, ([scaleId, placement]) => ({ scaleId, ...placement }));
  }

  /** A requested placement also configures peers whose ranks it changes. */
  configured(id: PriceScaleId): boolean {
    return this._configured.has(id);
  }

  /** Apply a validated snapshot, resetting omitted entries to defaults before ranking each side. */
  restore(overrides: ReadonlyMap<PriceScaleId, PriceAxisPlacement>): void {
    this._configured.clear();
    for (const id of overrides.keys()) this._configured.add(id);
    for (const id of overrides.keys()) this.register(id);
    const next: Record<PriceAxisSide, number> = { left: 0, right: 0, hidden: 0 };
    for (const id of this._placements.keys()) {
      const side = defaultSide(id);
      const fallback = { side, order: next[side]++ };
      this._placements.set(id, { ...(overrides.get(id) ?? fallback) });
    }
    for (const side of sides) this._reorder(side, this._sideIds(side));
  }

  private _sideIds(side: PriceAxisSide): PriceScaleId[] {
    return this.entries().filter(placement => placement.side === side)
      .sort((a, b) => a.order - b.order).map(placement => placement.scaleId);
  }

  private _reorder(side: PriceAxisSide, ids: readonly PriceScaleId[]): void {
    ids.forEach((id, order) => {
      const previous = this._placements.get(id);
      if (previous?.side !== side || previous.order !== order) this._configured.add(id);
      this._placements.set(id, { side, order });
    });
  }
}

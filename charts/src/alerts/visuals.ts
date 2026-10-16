import { PriceLine, type PriceLineOptions } from '../primitives/price-line';
import type { PrimitiveHit, PrimitiveRenderContext } from '../primitives/primitive';
import type { PriceScale } from '../scale/price-scale';
import type { Alert, AlertChartHost, AlertDrawingValue } from './types';
import type { LooseOptional } from '../helpers/types';

const COLORS = { armed: '#3b82f6', triggered: '#22c55e', disabled: '#64748b', expired: '#d97706' };

interface AlertVisualHost extends AlertChartHost {
  panes?(): readonly { priceScale: PriceScale }[];
  primarySeries?(): { priceScale(): PriceScale } | null;
}

/**
 * The badge on an alert's line.
 *
 * `armed` is the ordinary state and the word is the engine's, not a trader's:
 * a line on a chart saying "Armed" reads as jargon for the state every alert
 * is in almost all the time. It says what the line IS instead. The other three
 * stay, because each one tells you something the line cannot: that it has
 * already fired, that it has run out, that it is switched off.
 */
function badgeFor(state: Alert['state'], paused: boolean): string {
  if (paused) return 'Paused';
  if (state === 'armed') return 'Alert';
  return state[0]!.toUpperCase() + state.slice(1); // no state name is empty
}

/**
 * The line an alert draws at its own price.
 *
 * Draggable when the price is the alert's to own, which is a price or a study
 * threshold: moving the line is the fastest way to say "not there, here", and
 * it beats opening a dialog to retype a number.
 *
 * Not draggable when the price belongs to something else. A drawing-sourced
 * alert sits ON a trend line and follows it, so a grab there has to reach the
 * drawing: the alert has no price of its own to move, and intercepting the
 * gesture would pin the label while the line it is labelling slid away.
 */
class AlertPriceLine extends PriceLine {
  private _movable = false;
  private _committedPrice = this.price;
  private _context: PrimitiveRenderContext | undefined;
  private _resolveScale: (rc: PrimitiveRenderContext) => PriceScale = rc => rc.priceScale;
  private _canAutoscale: () => boolean = () => true;

  public bind(movable: boolean, price: number, resolveScale: (rc: PrimitiveRenderContext) => PriceScale, canAutoscale: () => boolean): void {
    this._movable = movable;
    this._committedPrice = price;
    this._resolveScale = resolveScale;
    this._canAutoscale = canAutoscale;
  }

  public override zOrder(): 'top' { return 'top'; }

  public override autoscaleInfo(): { min: number; max: number } | null {
    if (!this._canAutoscale()) return null;
    if (this._context && this._resolveScale(this._context) !== this._context.priceScale) return null;
    return { min: this._committedPrice, max: this._committedPrice };
  }

  public override draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this._context = rc;
    const priceScale = this._resolveScale(rc);
    ctx.save();
    // A left or overlay scale must not label the pane's right axis in different units.
    if (priceScale !== rc.priceScale) {
      ctx.beginPath(); ctx.rect(0, 0, rc.plotWidth * rc.dpr, rc.plotHeight * rc.dpr); ctx.clip();
    }
    super.draw(ctx, { ...rc, priceScale });
    ctx.restore();
  }

  public override hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    this._context = rc;
    const hit = this._movable ? super.hitTest(x, y, { ...rc, priceScale: this._resolveScale(rc) }) : null;
    return hit ? { ...hit, zOrder: 'top', draggable: true, cancelOnEscape: true } : null;
  }

  public coordinateToPrice(y: number): number | undefined {
    return this._context ? this._resolveScale(this._context).yToPrice(y) : undefined;
  }
}

/** Which sources carry a price the trader may move by hand. */
function movable(alert: Alert): boolean {
  return alert.source.kind === 'price' || alert.source.kind === 'indicator';
}

/** `alert:<id>:<index>` taken apart, or null for an id that is not ours. */
export function parseAlertLineId(externalId: string): { id: string; index: number } | null {
  const match = /^alert:(.+):(\d+)$/.exec(externalId);
  if (match === null) return null;
  const index = Number(match[2]);
  return index === 0 || index === 1 ? { id: match[1]!, index } : null; // `(.+)` takes part in every match
}

/** One reusable line per bound. Evaluation and host notifications never depend on drawing. */
export class AlertVisuals {
  private readonly _lines = new Map<string, { pane: number; lines: AlertPriceLine[] }>();
  public constructor(private readonly _chart: AlertVisualHost) {}

  public update(alert: Alert, value: AlertDrawingValue | undefined, paused: boolean, timeframe?: string): void {
    if (!this._chart.addPrimitive || !this._chart.removePrimitive) return;
    if (!value) { this.remove(alert.id); return; }
    const prices = value.upperPrice === undefined ? [value.price] : [value.price, value.upperPrice];
    const canMove = movable(alert) && alert.state === 'armed' && !paused;
    const { source } = alert;
    const sourceScale = (): PriceScale | undefined => source.kind === 'indicator'
      ? this._chart.indicators?.().find(item => item.id === source.instanceId)?.series(source.plotKey)?.priceScale()
      : source.kind === 'price' ? this._chart.primarySeries?.()?.priceScale() : undefined;
    const resolveScale = (rc: PrimitiveRenderContext): PriceScale => source.kind === 'indicator'
      ? sourceScale() ?? rc.priceScale : source.kind === 'price' ? rc.readoutPriceScale ?? rc.priceScale : rc.priceScale;
    // Autoscale runs before the first draw, so it cannot infer ownership from a render context.
    const canAutoscale = (): boolean => {
      const rightScale = this._chart.panes?.()[value.paneIndex]?.priceScale;
      return rightScale === undefined || (sourceScale() ?? rightScale) === rightScale;
    };
    let group = this._lines.get(alert.id);
    if (group && (group.pane !== value.paneIndex || group.lines.length !== prices.length)) {
      this.remove(alert.id);
      group = undefined;
    }
    if (!group) {
      group = { pane: value.paneIndex, lines: [] };
      this._lines.set(alert.id, group);
    }
    // `i` stays inside `prices`, the one or two bounds this line group draws.
    for (let i = 0; i < prices.length; i++) {
      const options = {
        price: prices[i]!, color: COLORS[alert.state], lineStyle: alert.state === 'armed' ? 'dashed' as const : 'dotted' as const,
        badge: badgeFor(alert.state, paused),
        leftLabel: alert.title + (timeframe === undefined ? '' : ` (${timeframe})`)
          + (prices.length === 2 ? (i === 0 ? ' (lower)' : ' (upper)') : ''),
        // The hint is what tells anybody the line can be moved at all. A line
        // that drags with no cursor change is a feature nobody finds.
        cursor: canMove ? 'ns-resize' : undefined,
      } satisfies LooseOptional<Omit<PriceLineOptions, 'id'>> as Omit<PriceLineOptions, 'id'>; // no cursor goes as undefined, which the line reads as none
      const existing = group.lines[i];
      if (existing) {
        existing.bind(canMove, prices[i]!, resolveScale, canAutoscale);
        const previous = existing.options();
        if (Object.entries(options).some(([key, value]) => previous[key as keyof typeof previous] !== value)) existing.setOptions(options);
      } else {
        const line = new AlertPriceLine({ ...options, id: `alert:${alert.id}:${i}` });
        line.bind(canMove, prices[i]!, resolveScale, canAutoscale);
        group.lines.push(line);
        this._chart.addPrimitive(line, value.paneIndex);
      }
    }
  }

  /** Preview affects only the primitive; the controller owns the committed threshold. */
  public preview(externalId: string, price: number): void {
    const parsed = parseAlertLineId(externalId);
    if (parsed) this._lines.get(parsed.id)?.lines[parsed.index]?.setPrice(price);
  }

  public coordinateToPrice(externalId: string, y: number): number | undefined {
    const parsed = parseAlertLineId(externalId);
    return parsed ? this._lines.get(parsed.id)?.lines[parsed.index]?.coordinateToPrice(y) : undefined;
  }

  public remove(id: string): void {
    const group = this._lines.get(id);
    if (!group) return;
    this._lines.delete(id);
    for (const line of group.lines) this._chart.removePrimitive?.(line);
  }

  public destroy(): void { for (const id of this._lines.keys()) this.remove(id); }
}

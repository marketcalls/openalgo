import { roundToTick } from '../helpers/math';
import { later } from '../helpers/timers';
import type { Bar } from '../model/bar';
import { getIndicator, hasIndicator } from '../model/indicator-registry';
import { numericMatch, touchMatch } from './conditions';
import { getBarCondition } from './bar-conditions';
import { AlertVisuals, parseAlertLineId } from './visuals';
import { copyAlert as copy, parseAlertsDocument, validateAlert as validate } from './document';
import { dataVariantKey, normalizeDataVariant, passingDataContext, type DataVariant } from '../feed/data-variant';
import type {
  Alert, AlertChartHost, AlertControllerOptions, AlertInput, AlertPatch, AlertScope,
  AlertTriggeredPayload, ChartDataUpdate, AlertAvailability, IndicatorAlertSource,
  AlertDrawingProvider, AlertDrawingValue, DrawingAlertSource, AlertsDocument, AlertsChangedEvent,
} from './types';
import type { LooseOptional } from '../helpers/types';

interface RecordState {
  alert: Alert;
  /** The newest element this record has judged or seeded on, and where it sat, so an update can tell what it appended. */
  tail?: Bar | undefined;
  index?: number | undefined;
  value?: number | undefined;
  errorTime?: number;
  plotPane?: number | undefined;
}

interface AlertDragEvent {
  id?: unknown;
  price?: unknown;
  point?: { y?: unknown };
  paneIndex?: unknown;
}

interface AlertDrag {
  externalId: string;
  record: RecordState;
  index: number;
  paneIndex: number;
  startPrice: number;
  startY?: number | undefined;
  moved: boolean;
}

const owners = new WeakSet<AlertChartHost>();
let nextId = 1;
const scopeOf = (chart: AlertChartHost): AlertScope => {
  const context = chart.getDataContext();
  // The default series names no variant, so a scope from it is what it always
  // was. One the chart was handed malformed is kept as it is: validation
  // refuses to set an alert on it and no comparison matches it.
  // A context the chart lacks leaves its fields undefined, which a scope reads as absent.
  let variant: DataVariant | undefined = context?.variant;
  try { variant = normalizeDataVariant(variant); } catch { /* see above */ }
  return { symbol: context?.symbol, exchange: context?.exchange, interval: context?.interval,
    ...(variant ? { variant: { ...variant } } : {}) } satisfies LooseOptional<AlertScope> as AlertScope;
};
/** One string per series, and one no valid variant can produce for a malformed one, never a throw inside a listener. */
const variantOf = (scope: AlertScope): string => { try { return dataVariantKey(scope.variant); } catch { return 'invalid'; } };
const sameInstrument = (a: AlertScope, b: AlertScope): boolean =>
  a.symbol === b.symbol && a.exchange === b.exchange;
/** A fixed price means the same on another timeframe, session or adjustment, not in another currency or unit. */
const samePrices = (a: AlertScope, b: AlertScope): boolean =>
  sameInstrument(a, b) && a.variant?.currency === b.variant?.currency && a.variant?.unit === b.variant?.unit;
const sameScope = (a: AlertScope, b: AlertScope): boolean =>
  sameInstrument(a, b) && a.interval === b.interval && variantOf(a) === variantOf(b);
/** Whether an element is still what an alert last read, so an update that appended after it did not also revise it. */
const sameBar = (a: Bar, b: Bar): boolean => a.time === b.time && a.open === b.open && a.high === b.high
  && a.low === b.low && a.close === b.close && a.volume === b.volume && a.oi === b.oi;
/** Where a level evaluates, for its label on a chart that shows something else. */
const scopeLabel = (scope: AlertScope, context: AlertScope): string => {
  const timeframe = scope.interval ?? 'original timeframe';
  if (variantOf(scope) === variantOf(context)) return timeframe;
  const variant = scope.variant;
  const words = variant ? [variant.session, variant.adjustment, variant.currency, variant.unit].filter(Boolean) : [];
  return `${timeframe}, ${words.length ? words.join(' ') : 'default series'}`;
};

/** Headless, chart-owned trader alerts. Hosts subscribe to alert:triggered for delivery. */
export class AlertController {
  private readonly _records = new Map<string, RecordState>();
  /** The alert whose line the pointer is over, for a key that acts on it. */
  private _hovered: string | undefined;
  private readonly _off: (() => void)[];
  private readonly _now: () => number;
  private readonly _drawings: AlertDrawingProvider | undefined;
  /** Whether a spent alert keeps its line; the host's choice, default 'show'. */
  private readonly _spentLines: 'show' | 'hide';
  private readonly _visuals: AlertVisuals | undefined;
  private _timer: ReturnType<typeof setTimeout> | undefined;
  private _timerAt: number | undefined;
  private _paused = false;
  private _restoring = false;
  private _replay = false;
  private _destroyed = false;
  private _revision = 0;
  private _drag: AlertDrag | undefined;

  public constructor(private readonly _chart: AlertChartHost, options: AlertControllerOptions = {}) {
    if (owners.has(_chart)) throw new Error('An alert controller already owns this chart');
    this._now = options.now ?? (() => Date.now() / 1000);
    this._drawings = options.drawings;
    this._spentLines = options.spentLines ?? 'show';
    this._visuals = options.visuals === false ? undefined : new AlertVisuals(_chart);
    owners.add(_chart);
    this._off = [
      _chart.on('data:update', payload => this._onData(payload as ChartDataUpdate)),
      // The context a variant-only change passes through is replaced at once;
      // seeding and saving for it would only be done again.
      _chart.on('data:context', context => { if (!passingDataContext(context)) this._seedAll(); }),
      _chart.on('objects:change', () => this._onObjects()),
      _chart.on('paneMoved', () => this._onObjects()),
      _chart.on('state:restore:start', () => { this._hovered = undefined; this._cancelDrag(); this._restoring = true; this._revision++; }),
      _chart.on('state:restore:end', () => { this._restoring = false; this._seedAll(); }),
      _chart.on('alerts:restore', document => this.fromJSON(document)),
      _chart.on('replay:start', () => { this._replay = true; this._seedAll(); }),
      _chart.on('replay:stop', () => { this._replay = false; this._seedAll(); }),
      _chart.on('destroy', () => this.destroy()),
      _chart.on('drag:start', payload => this._startDrag(payload as AlertDragEvent)),
      // Which alert the pointer is over, so a key can act on it. The drawing
      // tier keeps the same fact for the same reason: Delete has to know what
      // it would be deleting before anybody presses it.
      _chart.on('hover', payload => {
        const id = (payload as { id?: unknown } | undefined)?.id;
        const parsed = typeof id === 'string' ? parseAlertLineId(id) : null;
        this._hovered = parsed !== null && this._records.has(parsed.id) ? parsed.id : undefined;
      }),
      _chart.on('drag', payload => this._onDrag(payload as AlertDragEvent, false)),
      _chart.on('drag:end', payload => this._onDrag(payload as AlertDragEvent, true)),
      _chart.on('drag:cancel', payload => {
        if ((payload as AlertDragEvent).id === this._drag?.externalId) this._cancelDrag();
      }),
    ];
    try {
      const saved = _chart.alertState?.();
      if (saved !== undefined) this.fromJSON(saved);
    } catch (error) { this.destroy(); throw error; }
  }

  private _dragAvailability(record: RecordState, index: number): AlertAvailability {
    const source = record.alert.source;
    if (this._destroyed || this._restoring || record.alert.state !== 'armed' || this._records.get(record.alert.id) !== record
      || (source.kind !== 'price' && source.kind !== 'indicator')
      || (index !== 0 && (index !== 1 || (source.kind === 'price' ? source.upperPrice : source.upperValue) === undefined))) {
      return { available: false };
    }
    return this.availability(record.alert.id);
  }

  /**
   * The alert the pointer is over, or none.
   *
   * Offered so a host can bind a key to it. The controller does not bind keys
   * itself: it owns no input and a chart embedded without the widget shell has
   * its own idea of what a keystroke means.
   */
  public hovered(): string | undefined {
    const record = this._hovered === undefined ? undefined : this._records.get(this._hovered);
    return record && this._dragAvailability(record, 0).available ? record.alert.id : undefined;
  }

  private _dragPrice(payload: AlertDragEvent, externalId: string, paneIndex?: number): number | undefined {
    const y = payload.point?.y;
    const converted = typeof y === 'number' && Number.isFinite(y) ? this._visuals?.coordinateToPrice(externalId, y) : undefined;
    const price = converted ?? payload.price;
    if (typeof price !== 'number' || !Number.isFinite(price)) return undefined;
    const parsed = parseAlertLineId(externalId);
    const source = parsed && this._records.get(parsed.id)?.alert.source;
    const scale = source?.kind === 'price' ? this._chart.primarySeries?.()?.priceScale()
      : source?.kind === 'indicator'
        ? this._chart.indicators?.().find(item => item.id === source.instanceId)?.series(source.plotKey)?.priceScale()
        : undefined;
    const pane = paneIndex ?? payload.paneIndex;
    // A price alert is in the instrument's own prices, so a tick schedule
    // outranks the scale's one tick, which is only the grid every band lies on.
    const ticks = source?.kind === 'price' ? this._chart.tickSchedule?.() ?? null : null;
    // The source scale owns both units and tick size, even on a left or overlay axis.
    const snapped = ticks ? ticks.round(price) : scale ? roundToTick(price, scale.options.minMove)
      : typeof pane === 'number' ? this._chart.snapPrice?.(pane, price) ?? price : price;
    let result = Number.isFinite(snapped) ? snapped : price;
    if (parsed && (source?.kind === 'price' || source?.kind === 'indicator')) {
      const bound = parsed.index === 0
        ? source.kind === 'price' ? source.upperPrice : source.upperValue
        : source.kind === 'price' ? source.price : source.value;
      if (bound !== undefined && (parsed.index === 0 ? result > bound : result < bound)) {
        result = bound;
        const step = scale?.options.minMove ?? 0;
        if (ticks) {
          // The band's own neighbour, not the grid's: the tick below a bound
          // in a coarse band is a whole band tick away.
          result = ticks.round(bound);
          if (parsed.index === 0 ? result > bound : result < bound) result = ticks.step(result, parsed.index === 0 ? -1 : 1);
        } else if (step > 0) {
          result = roundToTick(bound, step);
          const tolerance = Number.EPSILON * Math.max(1, Math.abs(bound)) * 4;
          if (Math.abs(result - bound) <= tolerance) result = bound;
          // A manually entered opposite bound may itself sit between ticks.
          else if (parsed.index === 0 ? result > bound : result < bound) {
            result = roundToTick(bound + (parsed.index === 0 ? -step : step), step);
          }
        } else if (!scale && typeof pane === 'number' && this._chart.snapPrice) {
          result = this._chart.snapPrice(pane, bound);
          // A callback without tick metadata cannot find an adjacent tick safely.
          // Reject this move instead of inventing a tick or crossing the range.
          if (!Number.isFinite(result) || (parsed.index === 0 ? result > bound : result < bound)) return undefined;
        }
      }
    }
    return result;
  }

  private _startDrag(payload: AlertDragEvent): void {
    this._cancelDrag();
    if (typeof payload.id !== 'string') return;
    const parsed = parseAlertLineId(payload.id);
    const record = parsed && this._records.get(parsed.id);
    if (!parsed || !record) return;
    const available = this._dragAvailability(record, parsed.index);
    const price = this._dragPrice(payload, payload.id, available.paneIndex);
    if (!available.available || available.paneIndex === undefined || price === undefined
      || (payload.paneIndex !== undefined && payload.paneIndex !== available.paneIndex)) return;
    this._drag = { externalId: payload.id, record, index: parsed.index, paneIndex: available.paneIndex,
      startPrice: price, startY: typeof payload.point?.y === 'number' ? payload.point.y : undefined, moved: false };
  }

  private _cancelDrag(id?: string): void {
    const drag = this._drag;
    if (!drag || (id !== undefined && drag.record.alert.id !== id)) return;
    this._drag = undefined;
    const record = this._records.get(drag.record.alert.id);
    if (record) this._syncVisual(record);
  }

  /** Market evaluation keeps the committed source until a moved, owned gesture ends. */
  private _onDrag(payload: AlertDragEvent, done: boolean): void {
    this._expireDue();
    const drag = this._drag;
    if (!drag || payload.id !== drag.externalId) return;
    const available = this._dragAvailability(drag.record, drag.index);
    if (!available.available || available.paneIndex !== drag.paneIndex
      || (payload.paneIndex !== undefined && payload.paneIndex !== drag.paneIndex)) { this._cancelDrag(); return; }
    const proposed = this._dragPrice(payload, drag.externalId, drag.paneIndex);
    if (proposed === undefined) { if (done) this._cancelDrag(); return; }
    const y = payload.point?.y;
    drag.moved ||= drag.startY !== undefined && typeof y === 'number' ? y !== drag.startY : proposed !== drag.startPrice;
    const source = drag.record.alert.source;
    if (source.kind !== 'price' && source.kind !== 'indicator') { this._cancelDrag(); return; }
    const lower = source.kind === 'price' ? source.price : source.value;
    const upper = source.kind === 'price' ? source.upperPrice : source.upperValue;
    const price = drag.index === 0 ? Math.min(proposed, upper ?? Infinity) : Math.max(proposed, lower);
    if (!done) { if (drag.moved) this._visuals?.preview(drag.externalId, price); return; }
    this._cancelDrag();
    if (!drag.moved || price === (drag.index === 0 ? lower : upper)) return;
    const next = source.kind === 'price'
      ? { ...source, ...(drag.index === 0 ? { price } : { upperPrice: price }) }
      : { ...source, ...(drag.index === 0 ? { value: price } : { upperValue: price }) };
    this.update(drag.record.alert.id, { source: next });
    this._chart.emit('alerts:changed', { id: drag.record.alert.id, reason: 'dragged' } satisfies AlertsChangedEvent);
  }

  public add(input: AlertInput): Alert {
    this._assertAlive();
    let id = input.id;
    if (id === undefined) do { id = `alert-${nextId++}`; } while (this._records.has(id));
    if (this._records.has(id)) throw new Error(`Duplicate alert id: ${id}`);
    const alert: Alert = {
      ...input, id, source: { ...input.source }, condition: input.condition ?? (input.source.kind === 'barCondition' ? 'matches' : 'crossing'),
      policy: input.policy ?? 'onBarClose', repeat: input.repeat ?? 'once', state: input.state ?? 'armed',
      title: input.title ?? 'Chart alert', cooldownSeconds: input.cooldownSeconds ?? 0, scope: scopeOf(this._chart),
    };
    validate(alert);
    alert.source = copy(alert).source;
    if (alert.state === 'armed' && alert.expiresAt !== undefined && this._now() >= alert.expiresAt) alert.state = 'expired';
    const record: RecordState = { alert };
    this._seed(record);
    this._records.set(id, record);
    this._syncVisual(record);
    this._scheduleExpiry();
    this._saveState();
    this._chart.emit('alert:created', { alert: copy(alert) });
    return copy(alert);
  }

  public update(id: string, patch: AlertPatch): Alert | undefined {
    this._assertAlive();
    const previous = this._records.get(id);
    if (!previous) return undefined;
    const alert: Alert = { ...previous.alert, ...patch, id, source: { ...(patch.source ?? previous.alert.source) } };
    validate(alert);
    alert.source = copy(alert).source;
    this._cancelDrag(id);
    if (alert.state === 'armed' && alert.expiresAt !== undefined && this._now() >= alert.expiresAt) alert.state = 'expired';
    const record: RecordState = { ...previous, alert };
    this._seed(record);
    this._records.set(id, record);
    this._syncVisual(record);
    this._scheduleExpiry();
    this._saveState();
    this._chart.emit('alert:updated', { alert: copy(alert) });
    return copy(alert);
  }

  public remove(id: string): boolean {
    return this._remove(id, 'removed');
  }

  private _remove(id: string, reason: string): boolean {
    const record = this._records.get(id);
    if (!record) return false;
    this._cancelDrag(id);
    this._records.delete(id);
    if (this._hovered === id) this._hovered = undefined;
    this._visuals?.remove(id);
    this._scheduleExpiry();
    this._saveState();
    this._chart.emit('alert:removed', { alert: copy(record.alert), reason });
    return true;
  }

  public list(): Alert[] { return [...this._records.values()].map(record => copy(record.alert)); }

  public toJSON(): AlertsDocument { return parseAlertsDocument({ version: 1, alerts: this.list() }); }

  /** Validate the complete replacement before touching current alerts or their visuals. */
  public fromJSON(input: unknown): void {
    this._assertAlive();
    const document = parseAlertsDocument(input);
    const next = new Map<string, RecordState>();
    const removed: { alert: Alert; reason: string }[] = [];
    const context = scopeOf(this._chart);
    for (const alert of document.alerts) {
      const source = alert.source;
      let reason: string | undefined;
      if (this._drawingGone(alert, context)) reason = 'drawing-missing';
      const plot = source.kind === 'indicator' ? source : source.kind === 'drawing' ? source.input : undefined;
      if (!reason && plot && this._chart.indicators) {
        const instance = this._chart.indicators().find(item => item.id === plot.instanceId);
        if (!instance) reason = 'indicator-missing';
        else if (!instance.series(plot.plotKey)) reason = 'plot-missing';
      }
      if (reason) { removed.push({ alert, reason }); continue; }
      if (alert.state === 'armed' && alert.expiresAt !== undefined && this._now() >= alert.expiresAt) alert.state = 'expired';
      if (alert.lastTriggeredTime !== undefined) {
        const key = alert.policy === 'onTouch' ? 'lastTouchedTime' : 'lastClosedTime';
        alert[key] = Math.max(alert[key] ?? -Infinity, alert.lastTriggeredTime);
      }
      const record = { alert };
      this._seed(record);
      next.set(alert.id, record);
    }
    this._cancelDrag();
    this._revision++;
    this._visuals?.destroy();
    this._hovered = undefined;
    this._records.clear();
    for (const [id, record] of next) { this._records.set(id, record); this._syncVisual(record); }
    this._scheduleExpiry();
    this._saveState();
    for (const event of removed) {
      if (this._destroyed) break;
      this._chart.emit('alert:removed', { ...event, alert: copy(event.alert) });
    }
    if (!this._destroyed) this._chart.emit('alerts:restored', { alerts: this.list() });
  }

  private _saveState(): void {
    if (!this._destroyed) this._chart.setAlertState?.({ version: 1, alerts: this.list() });
  }

  /** Availability is independent of lifecycle state; disabled records can still have valid anchors. */
  public availability(id: string): AlertAvailability {
    const record = this._records.get(id);
    if (!record) return { available: false, reason: 'Alert is unavailable' };
    if (this._paused || this._replay) return { available: false, reason: 'Alerts are paused' };
    const context = scopeOf(this._chart);
    if (!sameInstrument(record.alert.scope, context)) return { available: false, reason: 'Instrument context differs' };
    if (record.alert.scope.interval !== context.interval) return {
      available: false, reason: `Switch to ${record.alert.scope.interval ?? 'the original timeframe'} to evaluate this alert`,
    };
    if (variantOf(record.alert.scope) !== variantOf(context)) return {
      available: false, reason: 'Switch to the data variant this alert was set on to evaluate it',
    };
    const { source } = record.alert;
    const bars = this._chart.primaryBars();
    if (source.kind === 'drawing') {
      const info = this._drawings?.alertInfo(source.drawingId);
      if (!info?.available) return { available: false, reason: info?.reason ?? 'Drawing provider is unavailable' };
      if (info.paneIndex !== this._pricePane() && !source.input) return { available: false, reason: 'Select an input plot for this drawing pane' };
      const bounds = this._drawingValue(record.alert, bars[bars.length - 1]?.time);
      // The provider may leave the pane undefined, which availability reads as absent.
      return bounds ? { available: true, paneIndex: bounds.paneIndex }
        : { available: false, reason: 'Drawing level, time, input plot or condition is unavailable', paneIndex: info.paneIndex } satisfies LooseOptional<AlertAvailability> as AlertAvailability;
    }
    if (source.kind === 'indicator') {
      const resolved = this._plot(source);
      if (!resolved.values) return { available: false, reason: resolved.reason };
      return Number.isFinite(resolved.values[bars.length - 1])
        ? { available: true, paneIndex: resolved.paneIndex }
        : { available: false, reason: 'Plot value is unavailable', paneIndex: resolved.paneIndex };
    }
    if (source.kind === 'barCondition' && !getBarCondition(source.id)) return { available: false, reason: 'Bar condition is unavailable' };
    return bars.length ? { available: true, paneIndex: this._pricePane() } : { available: false, reason: 'Source data is unavailable' };
  }
  public enable(id: string): Alert | undefined { return this.update(id, { state: 'armed' }); }
  public disable(id: string): Alert | undefined { return this.update(id, { state: 'disabled' }); }

  /** Explicit host pause is independent of replay and never delivers a backlog. */
  public setPaused(paused: boolean): void {
    this._assertAlive();
    if (this._paused === paused) return;
    this._paused = paused;
    this._seedAll();
  }

  public destroy(): void {
    if (this._destroyed) return;
    this._destroyed = true;
    this._drag = undefined;
    this._revision++;
    for (const off of this._off) off();
    this._clearTimer();
    this._visuals?.destroy();
    this._hovered = undefined;
    this._records.clear();
    owners.delete(this._chart);
  }

  /**
   * Whether a drawing alert has lost its drawing. Only an alert on the
   * instrument the chart shows can tell: a host that keeps drawings per
   * instrument has another instrument's drawings off the chart, and an id in
   * one instrument's document may name an unrelated drawing in another's. So
   * an alert set on another instrument keeps its drawing reference, waits
   * without evaluating, and is judged when its instrument is back.
   */
  private _drawingGone(alert: Alert, context: AlertScope): boolean {
    const source = alert.source;
    return source.kind === 'drawing' && this._drawings !== undefined && sameInstrument(alert.scope, context)
      && this._drawings.get(source.drawingId) == null;
  }

  /** The slot the chart keeps its price pane in now; it moves, so it is never kept. */
  private _pricePane(): number {
    return this._chart.primaryPaneIndex?.() ?? 0;
  }

  private _assertAlive(): void {
    if (this._destroyed) throw new Error('Alert controller is destroyed');
  }

  private _seed(record: RecordState): void {
    // Finer bars from another timeframe must not consume an original-timeframe close.
    if (!sameScope(record.alert.scope, scopeOf(this._chart))) {
      record.tail = undefined;
      record.index = undefined;
      record.value = undefined;
      record.plotPane = undefined;
      return;
    }
    const bars = this._chart.primaryBars();
    const tail = bars[bars.length - 1];
    record.tail = tail ? { ...tail } : undefined;
    record.index = tail ? bars.length - 1 : undefined;
    if (record.alert.source.kind === 'indicator') {
      const plot = this._plot(record.alert.source);
      record.value = this._reading(plot.values, bars.length - 1);
      record.plotPane = plot.paneIndex;
    } else if (record.alert.source.kind === 'drawing' && record.alert.source.input) {
      record.value = this._reading(this._plot(record.alert.source.input).values, bars.length - 1);
    }
    const closed = bars[bars.length - 2]?.time;
    // A history reload can move backwards; it cannot make a judged bar new again.
    if (closed !== undefined) record.alert.lastClosedTime = Math.max(record.alert.lastClosedTime ?? -Infinity, closed);
  }

  private _seedAll(): void {
    this._cancelDrag();
    this._revision++;
    for (const record of this._records.values()) { this._seed(record); this._syncVisual(record); }
    if (!this._restoring) {
      this._saveState();
      if (!this._destroyed && this._records.size) this._chart.emit('alerts:checkpoint', {});
    }
  }

  private _onObjects(): void {
    if (this._destroyed || this._restoring) return;
    this._cancelDrag();
    const revision = ++this._revision;
    const context = scopeOf(this._chart);
    for (const record of [...this._records.values()]) {
      if (this._destroyed || this._revision !== revision) break;
      const source = record.alert.source;
      if (this._drawingGone(record.alert, context)) {
        this._remove(record.alert.id, 'drawing-removed');
      } else if (source.kind === 'indicator' || source.kind === 'drawing') {
        this._seed(record);
        this._syncVisual(record);
      } else if (source.kind === 'price') {
        // Its line follows the price pane, which a move can put in another slot.
        this._syncVisual(record);
      }
    }
  }

  private _syncVisual(record: RecordState): void {
    if (!this._visuals) return;
    const { alert } = record;
    const { source } = alert;
    // A host that asked for it draws nothing for an alert that is finished
    // with. `triggered` is reached only by `repeat: 'once'`, which `_trigger`
    // sets under exactly that condition, so a repeating alert goes on firing
    // and keeps its line; `expired` is spent in the same way. The record is
    // untouched, which is what stops a once-only alert firing again after a
    // host reloads it.
    if (this._spentLines === 'hide' && (alert.state === 'triggered' || alert.state === 'expired')) {
      this._visuals.update(alert, undefined, true);
      return;
    }
    const context = scopeOf(this._chart);
    const matches = sameScope(alert.scope, context);
    let value: AlertDrawingValue | undefined;
    // A fixed price remains meaningful across timeframes and sessions, not
    // across currencies or units; study and drawing values may not be.
    if (source.kind === 'price' && samePrices(alert.scope, context)) {
      value = { price: source.price, upperPrice: source.upperPrice, paneIndex: this._pricePane() } satisfies LooseOptional<AlertDrawingValue> as AlertDrawingValue;
    }
    if (matches) {
      if (source.kind === 'indicator') {
        if (record.plotPane !== undefined) value = { price: source.value, upperPrice: source.upperValue, paneIndex: record.plotPane } satisfies LooseOptional<AlertDrawingValue> as AlertDrawingValue;
      }
      if (source.kind === 'drawing') {
        const bars = this._chart.primaryBars();
        value = this._drawingValue(alert, bars[bars.length - 1]?.time);
      }
    }
    this._visuals.update(alert, value, this._paused || this._replay || (!matches && alert.state === 'armed'),
      matches ? undefined : scopeLabel(alert.scope, context));
  }

  private _onData(update: ChartDataUpdate): void {
    if (this._destroyed || this._restoring) return;
    const revision = ++this._revision;
    this._expireDue();
    if (this._drag && !this._dragAvailability(this._drag.record, this._drag.index).available) this._cancelDrag();
    if (this._destroyed || revision !== this._revision) return;
    if (this._paused || this._replay) return;
    if (update.kind !== 'update') { this._seedAll(); return; }
    const bars = this._chart.primaryBars();
    const tail = bars[bars.length - 1];
    if (!tail || update.time !== tail.time) return;
    const scope = scopeOf(this._chart);
    // One update can append several elements: a bar that completes two Renko
    // bricks, or a host that writes two bars before it says so. Each is judged
    // in turn, every alert at one element before any moves to the next, which
    // is what as many single appends would have delivered, in that order.
    const steps = [...this._records.values()].filter(record => sameScope(record.alert.scope, scope))
      .map(record => ({ record, from: this._firstNew(record, bars) }));
    let changed = false;
    for (let index = Math.min(...steps.map(step => step.from)); index < bars.length && revision === this._revision; index++) {
      for (const { record, from } of steps) {
        if (this._destroyed || revision !== this._revision) break;
        if (index >= from && this._records.get(record.alert.id) === record) changed = this._judge(record, bars, index, revision) || changed;
      }
    }
    if (changed) {
      this._saveState();
      if (!this._destroyed) this._chart.emit('alerts:checkpoint', {});
    }
  }

  /**
   * The first element of this update a record has not judged. An update that
   * still has the record's tail at its index, at its time or later (a forming
   * Kagi vertex or range bar is dated again as bars arrive), appended the
   * elements after it: the tail is judged again only when it changed, then
   * each newer element. Fewer bars, or a tail that moved because history
   * changed, leave nothing to attribute, and the update is judged as one to
   * the newest element against the tail the record last saw.
   */
  private _firstNew(record: RecordState, bars: readonly Bar[]): number {
    const last = bars.length - 1;
    const { tail, index } = record;
    if (!tail || index === undefined || index >= last) return last;
    const kept = bars[index];
    if (!kept || kept.time < tail.time) return last;
    return sameBar(kept, tail) ? index + 1 : index;
  }

  /**
   * Judge `bars[index]` for one record, as the single update that brought it
   * would have: an element newer than the record's tail closes the one before
   * it, and a touch is measured from that tail. Returns whether a checkpoint
   * moved.
   */
  private _judge(record: RecordState, bars: readonly Bar[], index: number, revision: number): boolean {
    const tail = bars[index]!; // `_onData` steps through indices it read from `bars`
    const previous = record.tail;
    record.tail = { ...tail };
    record.index = index;
    if (record.alert.source.kind === 'drawing' && index === bars.length - 1 && previous?.time !== tail.time) this._syncVisual(record);
    if (this._destroyed || revision !== this._revision || record.alert.state !== 'armed' || !previous) return false;
    const { alert } = record;
    if (alert.policy === 'onBarClose') {
      // The newest element is forming; one is closed only once a newer one follows it.
      const closed = bars[index - 1];
      if (tail.time <= previous.time || !closed || closed.time !== previous.time
        || (alert.lastClosedTime !== undefined && closed.time <= alert.lastClosedTime)) return false;
      alert.lastClosedTime = closed.time;
      const price = this._closedMatch(record, bars, index - 1);
      if (price !== undefined && revision === this._revision && this._records.get(alert.id) === record) {
        this._trigger(record, closed, index - 1, price);
      }
      return true;
    }
    if (tail.time < previous.time || (alert.lastTouchedTime !== undefined && tail.time <= alert.lastTouchedTime)) return false;
    const price = this._touchMatch(record, bars, index, previous);
    if (price === undefined || revision !== this._revision || this._records.get(alert.id) !== record) return false;
    // A suppressed match is consumed too: an old wick cannot wake after cooldown.
    alert.lastTouchedTime = tail.time;
    this._trigger(record, tail, index, price);
    return true;
  }

  private _plot(source: Pick<IndicatorAlertSource, 'instanceId' | 'plotKey'>):
    { values: readonly (number | null)[]; paneIndex: number; reason?: undefined } | { values?: undefined; paneIndex?: undefined; reason: string } {
    const instance = this._chart.indicators?.().find(item => item.id === source.instanceId);
    if (!instance) return { reason: 'Indicator instance is unavailable' };
    if (!instance.series(source.plotKey)) return { reason: 'Indicator plot is unavailable' };
    const values = instance.values()[source.plotKey];
    const overlay = instance.indicatorId && hasIndicator(instance.indicatorId)
      && getIndicator(instance.indicatorId).plots.some(plot => plot.key === source.plotKey && plot.overlay);
    return values ? { values, paneIndex: overlay ? this._pricePane() : instance.paneIndex } : { reason: 'Indicator plot is unavailable' };
  }

  private _reading(values: readonly (number | null)[] | undefined, index: number): number | undefined {
    const value = values?.[index];
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
  }

  // `index` is the closed element `_judge` read from `bars`, so `bars[index]` is there.
  private _closedMatch(record: RecordState, bars: readonly Bar[], index: number): number | undefined {
    const { source, condition } = record.alert;
    if (source.kind === 'barCondition') return this._barMatch(record, bars, index) ? bars[index]!.close : undefined;
    if (source.kind === 'drawing') {
      const bounds = this._drawingValue(record.alert, bars[index]!.time);
      const beforeBounds = this._drawingValue(record.alert, bars[index - 1]?.time);
      const values = source.input ? this._plot(source.input).values : undefined;
      const current = source.input ? this._reading(values, index) : bars[index]!.close;
      const previous = source.input ? this._reading(values, index - 1) : bars[index - 1]?.close;
      if (!bounds || current === undefined) return undefined;
      return numericMatch(condition, beforeBounds ? previous : undefined, current, bounds.price, bounds.upperPrice,
        beforeBounds?.price, beforeBounds?.upperPrice) ? current : undefined;
    }
    if (source.kind === 'price') return numericMatch(condition, bars[index - 1]?.close, bars[index]!.close, source.price, source.upperPrice)
      ? bars[index]!.close : undefined;
    const values = this._plot(source).values;
    const current = this._reading(values, index);
    return current !== undefined && numericMatch(condition, this._reading(values, index - 1), current, source.value, source.upperValue)
      ? current : undefined;
  }

  private _touchMatch(record: RecordState, bars: readonly Bar[], index: number, previous: Bar): number | undefined {
    const { source, condition } = record.alert;
    const tail = bars[index]!; // `_judge` passes an element it read from `bars`
    if (source.kind === 'barCondition') return this._barMatch(record, bars, index) ? tail.close : undefined;
    if (source.kind === 'drawing') return this._drawingTouch(record, source, bars, index, previous);
    if (source.kind === 'indicator') {
      const values = this._plot(source).values;
      const current = this._reading(values, index);
      // A consumed touch stops delivery, not updates to the preceding bar's close.
      const before = tail.time > previous.time ? this._reading(values, index - 1) : record.value;
      record.value = current;
      if (current === undefined || (current === before && tail.time === previous.time)) return undefined;
      return numericMatch(condition, before, current, source.value, source.upperValue) ? current : undefined;
    }
    const isNew = tail.time > previous.time;
    const changed = isNew || tail.close !== previous.close || tail.high > previous.high || tail.low < previous.low;
    if (!changed) return undefined;
    const high = Math.max(previous.close, tail.close, isNew || tail.high > previous.high ? tail.high : -Infinity);
    const low = Math.min(previous.close, tail.close, isNew || tail.low < previous.low ? tail.low : Infinity);
    return touchMatch(condition, previous.close, low, high, source.price, source.upperPrice);
  }

  private _barMatch(record: RecordState, bars: readonly Bar[], index: number): boolean {
    const source = record.alert.source;
    if (source.kind !== 'barCondition' || record.errorTime === bars[index]!.time) return false; // callers pass a bar they read
    const condition = getBarCondition(source.id);
    if (!condition) return false;
    try {
      return condition.when({ bars: bars.slice(0, index + 1), index }) === true;
    } catch (error) {
      record.errorTime = bars[index]!.time;
      this._chart.emit('alert:error', { alert: copy(record.alert), error });
      return false;
    }
  }

  private _drawingValue(alert: Alert, time: number | undefined): AlertDrawingValue | undefined {
    const source = alert.source;
    if (source.kind !== 'drawing' || time === undefined) return undefined;
    const value = this._drawings?.valueAt(source.drawingId, time, source.level);
    if (!value || (value.paneIndex !== this._pricePane() && !source.input)) return undefined;
    if (source.input && this._plot(source.input).paneIndex !== value.paneIndex) return undefined;
    const band = alert.condition === 'enteringRange' || alert.condition === 'leavingRange';
    // A band has two boundaries: a crossing needs the trader to choose one explicitly.
    if (band !== (value.upperPrice !== undefined)) return undefined;
    return value;
  }

  private _drawingTouch(record: RecordState, source: DrawingAlertSource, bars: readonly Bar[], index: number, previous: Bar): number | undefined {
    const tail = bars[index]!; // reached through `_touchMatch`, which reads the same element
    const bounds = this._drawingValue(record.alert, tail.time);
    const beforeBounds = this._drawingValue(record.alert, previous.time);
    if (source.input) {
      const values = this._plot(source.input).values;
      const current = this._reading(values, index);
      const before = tail.time > previous.time ? this._reading(values, index - 1) : record.value;
      record.value = current;
      if (!bounds || current === undefined || (current === before && tail.time === previous.time)) return undefined;
      return numericMatch(record.alert.condition, beforeBounds ? before : undefined, current, bounds.price, bounds.upperPrice,
        beforeBounds?.price, beforeBounds?.upperPrice) ? current : undefined;
    }
    if (!bounds || !beforeBounds) return undefined;
    const isNew = tail.time > previous.time;
    if (!isNew && tail.close === previous.close && tail.high <= previous.high && tail.low >= previous.low) return undefined;
    const high = Math.max(previous.close, tail.close, isNew || tail.high > previous.high ? tail.high : -Infinity);
    const low = Math.min(previous.close, tail.close, isNew || tail.low < previous.low ? tail.low : Infinity);
    return touchMatch(record.alert.condition, previous.close, low, high, bounds.price, bounds.upperPrice,
      beforeBounds.price, beforeBounds.upperPrice);
  }

  private _trigger(record: RecordState, bar: Bar, index: number, price: number): void {
    const { alert } = record;
    const now = this._now();
    if (alert.expiresAt !== undefined && now >= alert.expiresAt) { this._expireDue(); return; }
    if (alert.lastTriggeredAt !== undefined && now - alert.lastTriggeredAt < alert.cooldownSeconds) return;
    this._cancelDrag(alert.id);
    alert.lastTriggeredAt = now;
    alert.lastTriggeredTime = bar.time;
    if (alert.repeat === 'once') alert.state = 'triggered';
    this._syncVisual(record);
    this._scheduleExpiry();
    this._saveState();
    // An alert without a message leaves it undefined, which the payload reads as absent.
    const payload = {
      alertId: alert.id, title: alert.title, message: alert.message, time: bar.time, index, price, alert: copy(alert),
    } satisfies LooseOptional<AlertTriggeredPayload> as AlertTriggeredPayload;
    this._chart.emit('alert:triggered', payload);
  }

  private _expireDue(): void {
    const now = this._now();
    const expired: RecordState[] = [];
    for (const record of this._records.values()) {
      const { alert } = record;
      if (alert.state === 'armed' && alert.expiresAt !== undefined && now >= alert.expiresAt) {
        this._cancelDrag(alert.id);
        alert.state = 'expired';
        this._syncVisual(record);
        expired.push(record);
      }
    }
    this._scheduleExpiry();
    if (expired.length) this._saveState();
    for (const record of expired) {
      if (this._destroyed) break;
      if (this._records.get(record.alert.id) === record) this._chart.emit('alert:expired', { alert: copy(record.alert) });
    }
  }

  private _clearTimer(): void {
    if (this._timer !== undefined) clearTimeout(this._timer);
    this._timer = undefined;
    this._timerAt = undefined;
  }

  private _scheduleExpiry(): void {
    if (this._destroyed) return;
    let next: number | undefined;
    for (const { alert } of this._records.values()) {
      if (alert.state === 'armed' && alert.expiresAt !== undefined) next = Math.min(next ?? Infinity, alert.expiresAt);
    }
    if (next === this._timerAt) return;
    this._clearTimer();
    if (next === undefined) return;
    this._timerAt = next;
    this._timer = later(() => {
      this._timer = undefined;
      this._timerAt = undefined;
      if (!this._destroyed) this._expireDue();
    }, Math.max(1, (next - this._now()) * 1000));
  }
}

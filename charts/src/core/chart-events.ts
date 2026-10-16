/**
 * The chart's event bus: every name `chart.on(...)` takes, the payload each
 * carries, and the registry behind `on`, `once`, `off` and the engine's emit.
 *
 * {@link ChartEventMap} is the one inventory of the bus. The engine emits each
 * name in it, except the three a host emits for a link group (`symbol`,
 * `interval`, `chartType`); tests/chart-event-map.test.ts holds every emit and
 * subscription in src to it with the compiler. A lazy tier adds its own names
 * by declaration merging (the draw tier's are in src/draw/events.ts), which is
 * also how a host types an event of its own:
 *
 * ```ts
 * declare module 'openalgo-charts' {
 *   interface ChartEventMap { 'myapp:signal': { price: number } }
 * }
 * ```
 *
 * Names. A new name is `namespace:action`, lower case, words joined by a
 * hyphen, in the present tense (`objects:change`, `draw:preview-clear`). The
 * names that predate the rule (the camelCase pane and indicator events, the
 * single words, `trading:*` in snake case, and the past tense of
 * `branding:changed`, `timezone:changed`, `alerts:changed` and
 * `alerts:restored`) keep their spelling: renaming one would break every
 * listener on it.
 *
 * Payloads. One shape per name. An event with nothing to say carries an empty
 * object ({@link EmptyEvent}), except `events:change`, which has always carried
 * `undefined`.
 */
import type { ChartClickEvent } from './chart';
import type {
  BrandingChangedEvent, ChartDragEndEvent, ChartDragEvent, ChartEventClick, ContextMenuEvent, CrosshairMoveEvent,
  DoubleClickEvent, LayoutChangeEvent, RendererFallbackEvent,
} from './chart-types';
import type { TradingBracketModifyEvent, TradingOrder, TradingOrderModifyEvent, TradingPosition } from './trading-controller';
import type { ChartDataContext, IndicatorAlertPayload, IndicatorDataStatus } from '../model/indicator-registry';
import type { PriceScaleId } from '../model/series';
import type { PriceAxisPlacement } from '../model/price-axis-layout';
import type {
  AlertChangeEvent, AlertErrorEvent, AlertRemovedEvent, AlertsChangedEvent, AlertsDocument, AlertsRestoredEvent,
  AlertTriggeredPayload, ChartDataUpdate,
} from '../alerts/types';
import type { ReplayState } from '../replay/controller';
import type { PickKind, PickPoint } from '../input/pick';
import type { LinkAppearanceValues } from '../link/appearance';
import { dispatch } from '../helpers/dispatch';

/** Payload of an event with nothing to report but that it happened: an empty object. */
export type EmptyEvent = Record<string, never>;

/** Payload of `hover`: the hit id under the pointer, or null when it left every primitive. */
export interface ChartHoverEvent {
  id: string | null;
}

/** Payload of `drag:cancel`: a primitive drag ended without a commit. */
export interface ChartDragCancelEvent {
  id: string;
  paneIndex: number;
  reason: 'pointercancel' | 'pinch' | 'escape';
}

/**
 * Payload of `pan` and `zoom`. `from` and `to` are UTC seconds, or null where
 * that edge falls outside the loaded data; the logical pair is the raw
 * fractional bar range.
 */
export interface ChartViewportEvent {
  from: number | null;
  to: number | null;
  logicalFrom: number;
  logicalTo: number;
}

/** Payload of `resize`: the container's new size in CSS pixels. */
export interface ChartResizeEvent {
  width: number;
  height: number;
}

/** Payload of `lazy-load`: the window that neared the oldest bar, in UTC seconds. */
export interface LazyLoadEvent {
  from: number | null;
  to: number | null;
  direction: 'backward';
}

/** Payload of `paneAdded`, `paneRemoved` and `paneResized`. */
export interface PaneEvent {
  paneIndex: number;
}

/** Payload of `paneMoved`: the two slots whose panes swapped. */
export interface PaneMovedEvent {
  from: number;
  to: number;
}

/** Payload of `paneMaximized`: the maximized pane, or null when none is any more. */
export interface PaneMaximizedEvent {
  paneIndex: number | null;
}

/** Payload of `paneCollapsed`. */
export interface PaneCollapsedEvent {
  paneIndex: number;
  collapsed: boolean;
}

/** Payload of `priceAxisPlacementChanged`: where the scale draws now. It keeps its id. */
export interface PriceAxisPlacementChangedEvent extends PriceAxisPlacement {
  paneIndex: number;
  scaleId: PriceScaleId;
}

/** Payload of `indicatorRemoved`, `indicatorSettings` and `indicatorSource`. */
export interface IndicatorInstanceEvent {
  instanceId: string;
  indicatorId: string;
  paneIndex: number;
}

/** Payload of `indicator:data-status`. `id` is the instance id. */
export interface IndicatorDataStatusEvent {
  id: string;
  indicatorId: string;
  status: Readonly<IndicatorDataStatus>;
}

/** Payload of `timezone:changed`: the IANA zone the axis and studies now use. */
export interface TimezoneChangedEvent {
  timezone: string;
}

/** Payload of `pick:start`. */
export interface PickStartEvent {
  kind: PickKind | 'point';
}

/** Payload of `pick:end`: the picked value, or null when the pick was cancelled. */
export interface PickEndEvent extends PickStartEvent {
  value: number | PickPoint | null;
}

/**
 * Every event on the chart's bus, by name, with the payload a listener
 * receives. `chart.on`, `once` and `off` take these names and type the
 * listener from here; the draw tier adds the `draw:*` and `drawing:*` names.
 * Add a name of your own by declaration merging (see the module note).
 */
export interface ChartEventMap {
  // Lifecycle.
  /** Once, on the microtask after the chart is built, so a listener added on the next line still hears it. */
  ready: EmptyEvent;
  /** Once, at the end of `destroy()`, with the chart already torn down. Every listener is dropped after it. */
  destroy: EmptyEvent;
  /** The container size changed, by the resize observer or an `applySize` that changed it. */
  resize: ChartResizeEvent;
  /** A GPU backend lost its context or proved unusable; every pane draws through canvas2d from now on. */
  'renderer:fallback': RendererFallbackEvent;
  /** The brand mark changed; the payload is its options, or false when it was removed. */
  'branding:changed': BrandingChangedEvent;

  // Pointer.
  /** The pointer moved over the plot, or left it (every field null). */
  'crosshair:move': CrosshairMoveEvent;
  /** Every crosshair position a readout should show: the pointer's, and a linked chart's (`source: 'linked'`). */
  'crosshair:readout': CrosshairMoveEvent;
  click: ChartClickEvent;
  /** Set `handled` to stop the chart's own double-click action. */
  dblclick: DoubleClickEvent;
  /** The pointer entered or left a hit-testable primitive. */
  hover: ChartHoverEvent;
  /** A press on a draggable primitive, before it moves. */
  'drag:start': ChartDragEndEvent;
  drag: ChartDragEvent;
  'drag:end': ChartDragEndEvent;
  'drag:cancel': ChartDragCancelEvent;
  /** A right click, axis strips included. Call `preventDefault` to show your own menu. */
  contextmenu: ContextMenuEvent;
  /** A timeline event marker was clicked. */
  'event:click': ChartEventClick;
  /** `beginPick` started. */
  'pick:start': PickStartEvent;
  /** A pick resolved or was cancelled. */
  'pick:end': PickEndEvent;

  // Viewport and layout.
  /** The visible window moved without changing its span. */
  pan: ChartViewportEvent;
  /** The visible window's span changed. */
  zoom: ChartViewportEvent;
  /** The view neared the oldest bar and the history loader ran. */
  'lazy-load': LazyLoadEvent;
  paneAdded: PaneEvent;
  paneRemoved: PaneEvent;
  paneMoved: PaneMovedEvent;
  paneMaximized: PaneMaximizedEvent;
  paneCollapsed: PaneCollapsedEvent;
  /** A pane divider drag was released. */
  paneResized: PaneEvent;
  /**
   * `movePriceAxis` moved a pane's prices to the other strip.
   *
   * @deprecated Removed in 3.0.0 with `movePriceAxis`, the only call that emits it.
   *   Listen for `priceAxisPlacementChanged` (since 2.5.4).
   */
  priceAxisMoved: { paneIndex: number; from: 'right' | 'left'; to: 'right' | 'left' };
  priceAxisPlacementChanged: PriceAxisPlacementChangedEvent;
  /** A setter that changes the saved layout, and has no event of its own, ran. */
  'layout:change': LayoutChangeEvent;
  /** The source, study or chart object inventory changed. Re-read it; the payload says nothing. */
  'objects:change': EmptyEvent;
  /** Chart-owned timeline events, or their visibility, changed. */
  'events:change': undefined;
  /** Appearance settings a link group mirrors were applied, as the values that changed. */
  'style:change': LinkAppearanceValues;
  'timezone:changed': TimezoneChangedEvent;

  // Data.
  /** `setDataContext` changed the instrument, interval or variant; the payload is the new context. */
  'data:context': Readonly<ChartDataContext> | undefined;
  /** The primary source was written: a live bar, a reset or a page of history. */
  'data:update': ChartDataUpdate;
  /** Studies were invalidated because the primary bars or the clock they read changed; a write fires it before `data:update`. */
  'data:range': EmptyEvent;
  /** `setBarsProvider` or `invalidateRequestedData` ran; studies that fetch ask again. */
  'data:requests': EmptyEvent;

  // Saved state.
  /** `restoreState` began. A listener may start a newer restore, which supersedes this one. */
  'state:restore:start': EmptyEvent;
  'state:restore:end': EmptyEvent;
  /** The drawings a restore carries, for the draw tier to load. Opaque to the base. */
  'drawings:restore': unknown;
  /** The alerts a restore carries, for an `AlertController` to load. */
  'alerts:restore': AlertsDocument;

  // Studies.
  indicatorRemoved: IndicatorInstanceEvent;
  /** A study legend's settings button was pressed. The engine ships no form. */
  indicatorSettings: IndicatorInstanceEvent;
  /** A study legend's source button was pressed (a descriptor with `hasSource: true`). */
  indicatorSource: IndicatorInstanceEvent;
  /** A condition a study descriptor declared came true on a live bar. */
  'indicator:alert': IndicatorAlertPayload;
  'indicator:data-status': IndicatorDataStatusEvent;

  // Alerts, emitted by an AlertController attached to the chart.
  'alert:created': AlertChangeEvent;
  'alert:updated': AlertChangeEvent;
  'alert:removed': AlertRemovedEvent;
  'alert:expired': AlertChangeEvent;
  'alert:triggered': AlertTriggeredPayload;
  'alert:error': AlertErrorEvent;
  'alerts:changed': AlertsChangedEvent;
  'alerts:restored': AlertsRestoredEvent;
  /** Evaluation advanced what the alerts have consumed; save the chart state, deliver nothing. */
  'alerts:checkpoint': EmptyEvent;

  // Replay, emitted by a ReplayController or ReplayGroup driving the chart.
  'replay:start': ReplayState;
  'replay:frame': ReplayState;
  'replay:play': ReplayState;
  'replay:pause': ReplayState;
  'replay:end': ReplayState;
  'replay:stop': ReplayState;

  // Trading, the same names and payloads `chart.trading.on` delivers.
  'trading:order_modify': TradingOrderModifyEvent;
  'trading:order_cancel': { orderId: string };
  'trading:order_click': { order: TradingOrder };
  'trading:position_close': { positionId: string };
  'trading:position_click': { position: TradingPosition };
  'trading:bracket_modify': TradingBracketModifyEvent;

  // Emitted by a host, never by the engine: a link group follows them.
  /** The host switched instrument. The widget emits it; a link group and a drawing link follow it. */
  symbol: { symbol: string; exchange?: string } | string;
  /** The host switched timeframe. A link group follows it. */
  interval: { interval: string } | string;
  /** The host switched chart type. A link group follows it. */
  chartType: { chartType: string } | string;
}

type Listener = (payload: unknown) => void;

/**
 * The chart's listener registry. Names are plain strings here: typing them is
 * the job of the overloads on `Chart`, so one registry serves the typed names,
 * the deprecated string form and a host's merged names alike.
 */
export class ChartEventBus {
  private readonly _listeners = new Map<string, Set<Listener>>();

  public on(event: string, cb: (payload: never) => void): () => void {
    let set = this._listeners.get(event);
    if (set === undefined) {
      set = new Set();
      this._listeners.set(event, set);
    }
    set.add(cb as Listener);
    return (): void => this.off(event, cb);
  }

  public once(event: string, cb: (payload: never) => void): () => void {
    const wrap = (payload: never): void => {
      this.off(event, wrap);
      cb(payload);
    };
    return this.on(event, wrap);
  }

  /** Remove one listener, or every listener for the name when `cb` is omitted. */
  public off(event: string, cb?: (payload: never) => void): void {
    if (cb === undefined) this._listeners.delete(event);
    else this._listeners.get(event)?.delete(cb as Listener);
  }

  public emit(event: string, payload: unknown): void {
    dispatch(this._listeners.get(event), payload);
  }

  /** Whether anything listens for `event`, so an emitter can skip a payload nobody reads. */
  public has(event: string): boolean {
    return (this._listeners.get(event)?.size ?? 0) > 0;
  }

  public clear(): void {
    this._listeners.clear();
  }
}

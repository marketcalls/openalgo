// OpenAlgo Charts public API: the base tier, the `openalgo-charts` entry.
// Every other tier has an entry of its own and imports its base from here.

export { VERSION, version } from './version';

export { createChart, Chart, compactVolume, PRICE_SCALE_MODES } from './core/chart';
export type {
  ChartOptions, ChartNavigationOptions, ChartWatermarkOptions, BrandingChangedEvent, PlotRect, AddSeriesOptions, CrosshairMoveEvent, ChartEventOptions,
  AddIndicatorOptions, ChartApplyOptions,
  ContextMenuEvent, ContextMenuTarget, ContextMenuTargetKind, PriceAxisState, LayoutChangeEvent, LayoutSetter,
  AxisChromeOptions, ZoomAnchor, DoubleClickAction, DoubleClickEvent, ExportSvgOptions,
  PointerModifiers, PointerKind, PointerSample, PointerInfo,
  ChartClickEvent, ChartEventClick, ChartDragEvent, ChartDragEndEvent, RendererFallbackEvent,
} from './core/chart';
// The bus's inventory: every name `chart.on` takes and its payload. A tier or a
// host adds names by declaration merging into `ChartEventMap`.
export type {
  ChartEventMap, EmptyEvent, ChartHoverEvent, ChartDragCancelEvent, ChartViewportEvent, ChartResizeEvent, LazyLoadEvent,
  PaneEvent, PaneMovedEvent, PaneMaximizedEvent, PaneCollapsedEvent, PriceAxisPlacementChangedEvent,
  IndicatorInstanceEvent, IndicatorDataStatusEvent, TimezoneChangedEvent, PickStartEvent, PickEndEvent,
} from './core/chart-events';
// vector export: the serialising context behind `chart.exportSVG`, exported so
// a host can run its own primitives or a bare renderer into one.
export { SvgContext, SvgLinearGradient } from './render/svg-export';
export type { SvgContextOptions } from './render/svg-export';
export { exportChartDataCsv } from './model/chart-data-export';
export type { ChartDataCsvOptions, ChartDataCsvRange, ChartDataColumn, ChartDataProjectionContext, ChartDataCsvFormatters } from './model/chart-data-export';
export { Pane } from './core/pane';
export { ChartObjects } from './model/chart-objects';
export type {
  ChartObjectKind, ChartObjectCapabilities, ChartObjectSnapshot, ChartObjectDefinition,
  ChartObjectProvider, ChartObjectDrawing, ChartObjectDrawingSource, ChartObjectDrawingGroup, ChartObjectsOptions,
  ChartObjectBand,
} from './model/chart-objects';
export { darkTheme, lightTheme, DEFAULT_THEME } from './theme';
export type { ChartTheme } from './theme';
export { verticalGradient, withAlpha, fromGradient } from './render/gradient';
// eased wheel zoom (the counterpart to the kinetic pan a flick already gets)
export { ZoomGlide, DEFAULT_ZOOM_GLIDE_OPTIONS } from './input/zoom-glide';
export type { ZoomGlideOptions } from './input/zoom-glide';
export { InvalidationLevel } from './core/invalidate-mask';
export type { PaneInvalidation, TimeScaleOp } from './core/invalidate-mask';
export { bitmapSize, snapToDevicePixel } from './helpers/math';
export type { Size } from './helpers/math';

export { PriceScale, autoscaleRange, isRebasing, DEFAULT_PRICE_SCALE_OPTIONS } from './scale/price-scale';
export type { PriceRange, PriceScaleOptions, PriceScaleMode } from './scale/price-scale';
export { TimeScale, DEFAULT_TIME_SCALE_OPTIONS } from './scale/time-scale';
export type { LogicalRange, TimeScaleOptions } from './scale/time-scale';
export { niceTicks, precisionForStep } from './scale/ticks';
// `AxisStyle` is what `resolveScaleStyle` returns, so it belongs with it.
export type { TickMarkType, AxisStyle } from './render/axis';
export type { PriceAxisSide, PriceAxisPlacement, PriceAxisSlot } from './model/price-axis-layout';

// canvas option block (grid, crosshair, scales, margins). The resolvers are
// values because a host building its own settings dialog previews with them.
export { dashPattern, resolveGridStyle, resolveScaleStyle, resolvePlotMargins, SCALE_FONT_MIN, SCALE_FONT_MAX } from './render/grid';
export type {
  CanvasOptions, CanvasLineStyle, GridOptions, GridStyle, GridAxisStyle,
  ScaleCanvasOptions, PlotMarginOptions,
} from './render/grid';
export { resolveCrosshairStyle } from './render/crosshair';
export type { CrosshairOptions, CrosshairStyle } from './render/crosshair';

export { DEFAULT_CANDLE_STYLE, optimalBarWidth, candleTier, candleGeometry } from './render/candles';
export type { CandleStyle, CandleTier, CandleGeometry } from './render/candles';

// render backend port: the 2D backend ships here and registers itself; the
// GPU backend registers under 'webgl2' from its own lazy tier
// ('openalgo-charts/webgl') and `renderer: 'auto'` picks it up. Nothing under
// render/webgl is imported here: that is what keeps it out of the base bundle.
export {
  registerRenderBackend, unregisterRenderBackend, registeredRenderBackends,
  resolveRenderBackend, createRenderBackend, backendDegradation,
} from './render/backend';
export type {
  IRenderBackend, RenderBackendKind, RendererChoice, RenderBackendFactory, RenderDevice, RendererFallbackReason,
} from './render/backend';
export { Canvas2dBackend } from './render/canvas2d-backend';
export { DEFAULT_HISTOGRAM_STYLE } from './render/histogram';
export type { HistogramStyle } from './render/histogram';
export type { SeriesStyle } from './render/series-style';

export { registerChartType, getChartType, registeredChartTypes } from './model/chart-type-registry';
export type { SeriesType, RendererEntry, DrawItem, SeriesRenderContext } from './model/chart-type-registry';

// indicator registry (built-in descriptors ship in 'openalgo-charts/indicators')
export {
  registerIndicator,
  getIndicator,
  hasIndicator,
  registeredIndicators,
  indicatorDefaults,
  indicatorStyleInputs,
  plotStyleKeys,
  INDICATOR_LINE_STYLES,
  INDICATOR_PLOT_STYLES,
  sourceValue,
  sourceValues,
  INDICATOR_SOURCES,
  IndicatorInputError,
} from './model/indicator-registry';
export type {
  IndicatorDescriptor,
  IndicatorInput,
  IndicatorInputCondition,
  IndicatorInputConditionValue,
  IndicatorInputPresentation,
  IndicatorPlot,
  PlotBarColor,
  IndicatorBarsRequest,
  IndicatorBarsProvider,
  IndicatorBarsProviderAccess,
  IndicatorSnapshotRequest,
  IndicatorRequestState,
  RequestedBarsSnapshot,
  IndicatorFillSpec,
  IndicatorTableSpec,
  IndicatorLevel,
  IndicatorLevelContext,
  IndicatorLineStyle,
  IndicatorSettings,
  IndicatorSource,
  IndicatorStudySource,
  IndicatorStudyOutput,
  IndicatorStore,
  IndicatorValues,
  IndicatorAttachContext,
  IndicatorCalcContext,
  IndicatorExecutionContext,
  IndicatorAlertSpec,
  IndicatorAlertFrequency,
  IndicatorAlertContext,
  IndicatorAlertPayload,
  IndicatorDrawing,
  IndicatorMarker,
  IndicatorOutputTarget,
  IndicatorBackgroundSpec,
  DrawAnchor,
} from './model/indicator-registry';
export type { IndicatorApi, IndicatorHost } from './model/indicator-instance';
// Which bars a study computes on under a transformed chart.
export type { IndicatorBarSource } from './model/indicator-bar-source';
// What a user may do with a study, and the host's way past it.
export { parseIndicatorPolicy } from './model/indicator-policy';
export type { IndicatorPolicy, IndicatorEditOptions } from './model/indicator-policy';

// serialisable chart state (saved layouts / templates / drawings passthrough)
export { CHART_STATE_VERSION, parsePaneState } from './model/chart-state';
export type {
  ChartState,
  PaneState,
  PriceScaleState,
  SeriesState,
  IndicatorState,
  RestoreReport,
  ChartRestoreOptions,
} from './model/chart-state';

// settings dialog: a declarative schema in the same control vocabulary the
// indicator form already uses, plus its round-trip pair
export { chartSettingsSchema, readChartSettings, applyChartSettings } from './model/chart-settings';
export type {
  ChartSettingsTab, ChartSettingsTabId, ChartSettingsValue, ChartSettingsValues, ChartSettingsState,
  // `ChartSettingsTab.inputs` is typed as these, so a host building its own
  // settings dialog cannot annotate the value it is handed without the name.
  ChartSettingsInput, ChartSettingsColorPairInput,
} from './model/chart-settings';

// headless market replay (host renders its own transport bar)
export { ReplayController } from './replay/controller';
export { isReplaying } from './model/replay-window';
export type {
  ReplayOptions, ReplayState, ReplaySimulation, ReplayScheduler, ReplayChartHost, ReplayViewport,
} from './replay/controller';
export type { ReplayTiming, ReplayBarEndTime } from './replay/timeline';
export { ReplayGroup } from './replay/group';
export type { ReplayScope, ReplayGroupChartHost, ReplayGroupMember, ReplayGroupOptions, ReplayGroupState } from './replay/group';

// headless multi-symbol comparison (host renders its own symbol chips)
export { addComparison, comparisonController, ComparisonController } from './compare/controller';
export type {
  ComparisonOptions, ComparisonHandle, ComparisonMode, ComparisonBaseline,
  ComparisonControllerOptions, ComparisonChartHost, ComparisonPane,
} from './compare/controller';
export { alignToPrimary } from './compare/align';
export type { ComparisonAlignment } from './compare/align';

// chart linking (headless: the host draws its own link badge and colour chips).
// Everything crosses a chart boundary as a time, never as a logical index, so a
// daily chart and an hourly one stay on the same instant.
export { LinkGroup, createLinkGroup, followerIndex, followerRange, LinkCrosshair, LINK_CROSSHAIR_ALPHA, filterLinkAppearance } from './link/index';
export type {
  LinkChart, LinkOptions, LinkMemberOptions, ResolvedLinkOptions,
  LinkDataLayer, LinkMissingPolicy,
  LinkAppearanceAdapter, LinkAppearanceValues, LinkDrawingsAdapter,
} from './link/index';

export { CandleBuilder, DEFAULT_CANDLE_BUILDER_OPTIONS } from './feed/candle-builder';
export type { CandleBuilderOptions, Tick, CandleUpdate, VolumeMode, LateTickPolicy } from './feed/candle-builder';

export type { SeriesApi, PriceScaleId, PriceFormat, BarConfirmationOptions, SeriesUpdateOptions, SeriesDataState } from './model/series';

// primitives / plugin API
export { bestHit } from './primitives/primitive';
export type { IPrimitive, PrimitiveHit, PrimitiveHost, PrimitiveRenderContext, PrimitiveAnchor, PrimitivePlacement, ZOrder } from './primitives/primitive';
export { IndicatorFill } from './primitives/indicator-fill';
export type { IndicatorFillOptions, FillPoint, FillGradient } from './primitives/indicator-fill';
export { IndicatorDrawings } from './primitives/indicator-draws';
export { IndicatorBackground } from './primitives/indicator-background';
// `chart.dataLayer` is public, so its type has to be nameable by a consumer,
// and a tier that takes one in its own public API needs to name *this* one.
export type { DataLayer, IndexedBar, SeriesId, SessionCalendarSource } from './model/data-layer';
export { PriceLine } from './primitives/price-line';
export type { PriceLineOptions } from './primitives/price-line';
// price-level family: previous close, session high/low, extended-hours opens
// and closes, bid/ask: each a line and an axis tag that toggle together.
export {
  PriceLevels, PRICE_LEVEL_KINDS, computePriceLevels,
  lastPriceLevelFromSeriesStyle, seriesStyleForLastPriceLevel,
} from './primitives/price-levels';
export type {
  PriceLevelKind, PriceLevelStyle, PriceLevelsOptions, PriceLevelValues,
  PriceLevelInput, PriceLevelQuote, MarketPhase, MarketPhaseFn,
} from './primitives/price-levels';
export { SeriesMarkers, markerSizePx, effectiveMarkerPx, drawShape, drawLabel } from './primitives/markers';
export type { SeriesMarker, MarkerShape, MarkerPosition, MarkerSize } from './primitives/markers';
export { LogoWatermark, watermarkRect } from './primitives/watermark';
export type { LogoWatermarkOptions, WatermarkPosition } from './primitives/watermark';
export { TextWatermark } from './primitives/text-watermark';
export type { TextWatermarkOptions } from './primitives/text-watermark';
export { ReplayShade } from './primitives/replay-shade';
export type { ReplayShadeOptions } from './primitives/replay-shade';
// opt-in wash behind pre-open, post-close and extended-hours bars, from a session calendar
export { SessionShade, attachSessionShading } from './primitives/session-shade';
export type { SessionShadeOptions, SessionShading } from './primitives/session-shade';
export { BuySellButtons } from './primitives/buy-sell-buttons';
export type { BuySellButtonsOptions } from './primitives/buy-sell-buttons';
export { ChartTable, tableOrigin, DEFAULT_CHART_TABLE_OPTIONS } from './primitives/table';
export type { TableCell, TablePosition, ChartTableOptions } from './primitives/table';
export { PaneLegend } from './primitives/pane-legend';
export type {
  PaneLegendOptions, PaneLegendAction, LegendValue, LegendField, LegendTitleMode,
  LegendStatusData, LegendStatusSource, LegendStatusLineOptions,
} from './primitives/pane-legend';
export { TimeNavigator, DEFAULT_TIME_NAVIGATOR_OPTIONS } from './primitives/time-navigator';
export type { TimeNavigatorOptions, TimeNavigatorAction } from './primitives/time-navigator';
export { EventMarkers } from './primitives/event-markers';
export type { ChartEvent, ChartEventDetails, EventDetailField, EventDetailSpan, EventDetailInline, EventDetailBlock, EventGroup, EventMarkersOptions, EventMarkerDetails } from './primitives/event-markers';

// indicators
export { ema, emaSeries } from './indicators/ema';
export { rsi, rsiSeries } from './indicators/rsi';
export { atr, trueRange } from './indicators/atr';
export { supertrend, supertrendSeries, type SupertrendPoint } from './indicators/supertrend';

// optional OHLC-preserving conflation / downsampling (§4.4)
export { conflationGroupSize, conflateBars, conflateItems, mergeBars } from './model/conflation';

// Family-B transforms live in the lazy 'openalgo-charts/transform' entry point
// (importing it also registers the 'point-figure' and 'kagi' renderers), so they
// are intentionally NOT re-exported from the base bundle. The registry they
// fill for in-chart transforms (`chart.setSeriesTransform`) is here, so a chart
// that never draws one never loads one.
export { getSeriesTransform, registeredSeriesTransforms } from './model/series-transform';
export { registerSeriesTransform } from './core/chart-series-transform';
export type { SeriesTransformSpec, SeriesTransformRun, SeriesTransformDefinition } from './model/series-transform';
export type { Bar, LinePoint, Whitespace, SeriesDataItem, UTCSeconds, OriginalTime } from './model/bar';
export { isWhitespace, toBar } from './model/bar';

export type { DataFeed, TradeFeed, BarsRequest, BarsPageRequest, BarsPage, BarSubscriptionOptions, LiveBarMeta, MarketDepth, DepthLevel, OrderSide, OrderType, PlaceOrder, UnsubscribeFn, SymbolMatch, SymbolSearchRequest } from './feed/types';
export type { InstrumentKey, QuoteSnapshot, QuoteRequest, QuoteStreamStatus, QuoteStreamHandlers, QuoteFeed, NewsRequest, NewsItem, NewsPage, NewsFeed } from './feed/types';
export { Instrument, SessionCalendar } from './feed/instrument';
export type { InstrumentMetadata, InstrumentCalendar, InstrumentSession, SessionCalendarSpec } from './feed/instrument';
// market phases and status, derived from a calendar when the host supplies none
export { marketStatusAt, calendarMarketPhase } from './feed/market-status';
export type { SessionPhase, SessionPhaseSpan, SessionPhaseSource, MarketStatus } from './feed/market-status';
export { TickSchedule } from './feed/tick-schedule';
export type { TickBand } from './feed/tick-schedule';
export { checkTradingCapability, assertTradingCapability, TradingCapabilityError } from './feed/trading-capabilities';
export type { TradingOperation, TradingCapabilities, TradingCapabilityRequest, TradingCapabilitySource, TradingCapabilityResult } from './feed/trading-capabilities';
export { HistoryRequestPool, sharedHistoryRequests } from './feed/request-pool';
export type { HistoryRequestPoolOptions } from './feed/request-pool';
export { DataLoadingController } from './feed/data-controller';
export {
  normalizeDataVariant, dataVariantKey, unsupportedDataVariant, dataVariantError, publishDataContext,
} from './feed/data-variant';
export type {
  DataVariant, DataSession, DataAdjustment, DataVariantDimension, DataVariantCapabilities, DataVariantQuery, DataContextTarget,
} from './feed/data-variant';
export type { DataLoadingOptions, DataLoadingSnapshot, DataLoadingStatus, HistoryLoadingStatus, DataUpdateReason } from './feed/data-controller';
export type { ChartDataContext, IndicatorDataChange, IndicatorDataStatus } from './model/indicator-registry';
export { OpenAlgoDataFeed, mapHistoryResponse, rowTimeToUtcSeconds } from './feed/openalgo-rest';
export type { OpenAlgoConfig } from './feed/openalgo-rest';
export { OpenAlgoWsFeed, parseMessage, formatSubscribe, formatUnsubscribe, parseTopic, classifyAuthAck, readSequence, backoffDelayMs } from './feed/openalgo-ws';
export type { OpenAlgoWsConfig, SocketLike, SocketFactory, WsMode, LtpEvent, WsState, WsControlMessage, WsClientWarning, OrderUpdateEvent } from './feed/openalgo-ws';
export { OpenAlgoTradeFeed, mapOrder, mapPosition, decodeOrder, mapOrderStatus } from './feed/openalgo-trade';
export type { OpenAlgoTradeConfig, ModeCheck, RawOrder, DecodedOrder, OrderBookSnapshot, QuarantinedRow, OrderDecodeIssue, OrderDecodeCode, OrderDecodeResult } from './feed/openalgo-trade';
export { OpenAlgoLiveDataFeed, intervalToSeconds } from './feed/openalgo-live';
export type { OpenAlgoLiveConfig } from './feed/openalgo-live';
export { FakeDataFeed, generateBars } from './feed/fake-feed';
export type { FeedScheduler } from './feed/fake-feed';
export { TickBarAggregator } from './feed/tick-aggregator';
// `TickTimeframe` now lives in ./feed/intervals and is re-exported by the
// aggregator; it is deliberately exported from one place only, or the barrel
// would carry the same name twice.
export type { TickTimeframe, AggTick, BarUpdate, TickBarOptions } from './feed/tick-aggregator';

// warm-load bar caching: a DataFeed -> DataFeed wrapper, so any custom feed
// gets it, not just OpenAlgoDataFeed.
export { withBarCache, BarCache, barCacheKey, barCloseSec, BAR_CACHE_VERSION } from './feed/cache';
export type {
  BarCacheOptions, BarCacheStore, BarCacheStats, CachedBars, CachedBarsRequest, MaybePromise,
} from './feed/cache';

// interval registry: an interval code resolves to a bucketing rule, which is
// not always a duration (a month and a 500-tick bar both have no fixed length).
export {
  registerInterval, unregisterInterval, registeredIntervals,
  resolveInterval, tryResolveInterval, isKnownInterval,
  bucketStartOf, nextBucketStart, isTimeBucketed, UnknownIntervalError,
  intervalParts, isIntradayInterval, isDailyInterval, isSecondsInterval, isTickInterval,
} from './feed/intervals';
export type {
  IntervalDescriptor, Bucketing, IntervalBucketing, CalendarBucketing,
  TickCountBucketing, VolumeBucketing, CalendarUnit, IntervalParts,
} from './feed/intervals';
export {
  epochMsToUtcSeconds,
  istStringToUtcSeconds,
  utcSecondsToIstParts,
  utcSecondsToIstDateString,
  formatIstTime,
  formatIstTimeSeconds,
  formatIstDate,
  formatIstCrosshairLabel,
  isNewIstDay,
  sessionStartIndices,
  sessionStartFlags,
  calendarPeriodFlags,
  IST_OFFSET_SECONDS,
  // zone-aware forms: the general case the IST helpers above are one instance of
  DEFAULT_TIMEZONE,
  isValidTimezone,
  utcSecondsToZonedParts,
  utcSecondsToZonedDateString,
  zonedStringToUtcSeconds,
  zonedWallClockToUtcSeconds,
  zoneOffsetSeconds,
  zonedDayIndex,
  zonedWeekIndex,
  startOfZonedDay,
  startOfZonedWeek,
  startOfZonedMonth,
  isNewZonedDay,
  isNewZonedWeek,
  isNewZonedMonth,
  isNewZonedQuarter,
  isNewZonedYear,
  isNewZonedPeriod,
  formatZonedTime,
  formatZonedTimeSeconds,
  formatZonedDate,
  formatZonedCrosshairLabel,
  parseSessionSpec,
  inSessionAt,
  sessionFlags,
} from './feed/time';
export type { IstParts, ZonedParts, ZonedPeriod, SessionSpec } from './feed/time';

export { clamp, lerp, roundToTick } from './helpers/math';

export { TradingController, TradeMarkersPrimitive, DEFAULT_TRADING_COLORS } from './core/trading-controller';
export type {
  TradingHost,
  TradingPosition,
  TradingOrder,
  TradingTrade,
  TradingSyncPayload,
  TradingOrderModifyEvent,
  TradingBracketModifyEvent,
  TradingColors,
  TradingSettings,
  PositionSide,
  TradingOrderSide,
  TradingOrderType,
  TradeMarkerVariant,
  TradingLineVariant,
  TradingLineStyle,
} from './core/trading-controller';

export {
  ShortcutManager,
  DEFAULT_KEYMAP,
  ALT_PRESET,
  BUILTIN_COMMANDS,
  parseCombo,
  normalizeCombo,
  formatCombo,
  isValidCombo,
  isReservedCombo,
  eventToCombo,
} from './input/shortcuts';
export type {
  ShortcutScope,
  ShortcutPreset,
  KeymapEntry,
  CustomShortcut,
  ShortcutManagerOptions,
  ShortcutTriggerEvent,
  ShortcutListItem,
} from './input/shortcuts';

export { beginPick } from './input/pick';
export type { PickKind, PickHost, PickOptions, PickHandle, PickPoint } from './input/pick';

export { AlertController } from './alerts/controller';
export { alertSettingsSchema } from './alerts/schema';
export type {
  Alert, AlertChartHost, AlertCondition, AlertControllerOptions, AlertInput, AlertPatch,
  AlertPolicy, AlertRepeat, AlertScope, AlertSource, AlertState, AlertTriggeredPayload, ChartDataUpdate,
  AlertAvailability, AlertEventPayload, PriceAlertSource, IndicatorAlertSource, BarConditionAlertSource,
  BarCondition, BarConditionContext,
  AlertDrawingValue, AlertDrawingLevel, AlertDrawingInfo, AlertDrawingProvider,
  DrawingAlertSource,
  AlertsDocument, AlertChangeEvent, AlertRemovedEvent, AlertErrorEvent, AlertsChangedEvent, AlertsRestoredEvent,
} from './alerts/types';
export { parseAlertsDocument } from './alerts/document';
export { registerBarCondition, unregisterBarCondition, getBarCondition, registeredBarConditions } from './alerts/bar-conditions';

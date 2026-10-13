/**
 * The bottom bar under the chart grid: preset ranges, Go to, the market
 * status, the IST clock and the price scale toggles.
 *
 * One bar for the whole grid, pointed at the focused pane, so an eight chart
 * layout spends 28px on it rather than eight strips. The bar itself is the
 * library's (`mountBottombar`); what is this terminal's is how a range or a
 * date reaches the broker's history (through the pane's own loader), what a
 * trader is told when the broker has less history than a range asks for, and
 * where the choices are kept (the pane's own preferences, beside its symbol
 * and interval).
 *
 * Loaded lazily with the widget tier, so a chart paints before any of this is
 * fetched; the strip's height is reserved by the page meanwhile.
 */
import { type Chart, type ChartTheme, readChartSettings } from 'openalgo-charts'
import {
  applyTokens,
  type BottombarHandle,
  type BottombarScaleToggle,
  createOverlayStack,
  createTipController,
  DateNavigator,
  type DateNavigationResult,
  DEFAULT_RANGES,
  type HistoryReach,
  injectWidgetStyles,
  mountBottombar,
  openDateNavigation,
  type PanelHandle,
  rangeInterval,
  rangeWindow,
  WIDGET_COMPONENT_CSS,
  type WidgetContext,
  type WidgetRange,
  widgetTokens,
} from 'openalgo-charts/widget'

/** What the bar reads and drives on a pane. `TradingTerminal` is one. */
export interface BottomBarPane {
  liveChart(): Chart | null
  chartElement(): HTMLElement
  currentInterval(): string
  supportedIntervals(): readonly string[]
  showInterval(interval: string): Promise<boolean>
  loadHistoryBack(time: number): Promise<HistoryReach>
  activeRange(): string | null
  setActiveRange(id: string | null): void
  applyChartSettings(patch: Record<string, string | number | boolean>): Promise<void>
}

export interface BottomBarOptions {
  /** The focused pane, read at every use. */
  pane(): BottomBarPane | null
  /** Something a trader should read: a range that fell short, a date the chart cannot show yet. */
  notify(text: string, kind: 'info' | 'error'): void
}

export interface TradingBottomBar {
  /** Read the focused pane again: after focus moves. */
  refresh(): void
  /** A pane finished loading: put its range back on the new bars. */
  paneLoaded(pane: BottomBarPane): void
  setTheme(theme: ChartTheme, name: 'light' | 'dark'): void
  destroy(): void
}

const LOCALE = 'en-IN'

/**
 * Narrow strips drop the presets traders reach for least, rather than letting
 * the row scroll or clip: 1D, 1M, 1Y and All stay longest. The library already turns
 * Go to and the status into their glyphs below 760px and drops the zone below
 * 600px.
 */
const HOST_CSS = `
.oa-bottombar-root > .oac-bottombar { position: absolute; left: 0; right: 0; bottom: 0; pointer-events: auto; }
.oa-bottombar-root .oac-bottombar__ranges { overflow: hidden; min-width: 0; }
@container oac-bottombar (max-width: 700px) {
  .oa-bottombar-root .oac-bottombar__range:is([data-range="5D"], [data-range="3M"], [data-range="6M"]) { display: none; }
}
@container oac-bottombar (max-width: 540px) {
  .oa-bottombar-root .oac-bottombar__range:is([data-range="YTD"], [data-range="5Y"]) { display: none; }
}
@container oac-bottombar (max-width: 420px) {
  .oa-bottombar-root .oac-bottombar__range:is([data-range="1M"], [data-range="ALL"]) { display: none; }
}
`
const HOST_CSS_ID = 'oa-bottombar-css'

function injectHostCss(doc: Document): void {
  if (doc.getElementById(HOST_CSS_ID)) return
  const style = doc.createElement('style')
  style.id = HOST_CSS_ID
  style.textContent = HOST_CSS
  doc.head.appendChild(style)
}

/* ── history and placement ─────────────────────────────────────────────── */

const navigators = new WeakMap<BottomBarPane, DateNavigator>()
const requests = new WeakMap<BottomBarPane, number>()

/**
 * Older history for a placement, page by page through the pane's own loader.
 * A press or a wheel on the chart while it loads is the trader moving on, so
 * the request is dropped rather than jumping the view afterwards.
 */
async function loadWatched(pane: BottomBarPane, time: number): Promise<HistoryReach> {
  const el = pane.chartElement()
  const moved = () => navigators.get(pane)?.cancel()
  el.addEventListener('pointerdown', moved, true)
  el.addEventListener('wheel', moved, { capture: true, passive: true })
  try {
    return await pane.loadHistoryBack(time)
  } finally {
    el.removeEventListener('pointerdown', moved, true)
    el.removeEventListener('wheel', moved, true)
  }
}

function navigatorFor(pane: BottomBarPane): DateNavigator {
  let navigator = navigators.get(pane)
  if (!navigator) {
    navigator = new DateNavigator({
      chart: () => pane.liveChart(),
      interval: () => pane.currentInterval(),
      loadHistory: (time) => loadWatched(pane, time),
    })
    navigators.set(pane, navigator)
  }
  return navigator
}

const cancelled: DateNavigationResult = { status: 'cancelled' }

/**
 * The words a failed history load is shown with. The feed's own message can
 * carry a status code or an endpoint, which is for the log, not a trader.
 */
const HISTORY_FAILED = 'the broker did not return older bars. Try again in a moment'
const plainError = (result: DateNavigationResult): DateNavigationResult =>
  result.status === 'error' ? { ...result, error: new Error(HISTORY_FAILED) } : result
const bump = (pane: BottomBarPane) => {
  const next = (requests.get(pane) ?? 0) + 1
  requests.set(pane, next)
  return next
}

/** Place `range` on the bars the pane holds, loading older history it needs. */
export async function placeRange(
  pane: BottomBarPane,
  range: WidgetRange,
  mine = bump(pane)
): Promise<DateNavigationResult> {
  const chart = pane.liveChart()
  const bars = chart?.primaryBars() ?? []
  const last = bars[bars.length - 1]
  if (!chart || !last) return { status: 'no-data' }
  // All asks the broker for everything rather than reading the bars held,
  // which are only an ordinary lookback.
  const all = range.unit === 'all'
  const window = rangeWindow(range, {
    end: last.time,
    zone: chart.timezone(),
    calendar: chart.dataLayer.sessionCalendar,
    bars: all ? undefined : bars,
  })
  let result = await navigatorFor(pane).goTo(window)
  if (mine !== requests.get(pane) || chart.isDestroyed) return cancelled
  // For All, history that ends is the range itself, not a shortfall.
  if (
    all &&
    result.status === 'partial' &&
    (result.history === 'exhausted' || result.history === 'empty')
  )
    result = {
      status: result.clipped ? 'partial' : 'placed',
      from: result.from,
      to: result.to,
      ...(result.clipped ? { clipped: true } : {}),
    }
  if (result.status !== 'partial' || !result.clipped) return result
  // Wider than the plot: keep the latest bars in view, not the oldest.
  const lastIndex = chart.dataLayer.timeToIndex(last.time) ?? bars.length - 1
  const view = chart.getVisibleLogicalRange()
  const from = lastIndex + 0.5 - (view.to - view.from)
  chart.setVisibleLogicalRange({ from, to: lastIndex + 0.5 })
  return {
    ...result,
    from: chart.dataLayer.indexToTime(Math.ceil(from + 0.5)) ?? result.from,
    to: last.time,
  }
}

/** Switch the pane to the range's interval, among those the broker offers, then place it. */
export async function applyRange(pane: BottomBarPane, id: string): Promise<DateNavigationResult> {
  const range = DEFAULT_RANGES.find((r) => r.id === id)
  if (!range) return { status: 'invalid' }
  const mine = bump(pane)
  const interval = rangeInterval(range, pane.supportedIntervals())
  const ready = await pane.showInterval(interval)
  // A load that failed has already told the trader why, in the pane's own words.
  if (mine !== requests.get(pane) || !ready) return cancelled
  pane.setActiveRange(range.id)
  return placeRange(pane, range, mine)
}

/** What a range came to, in a trader's words, or null when the chart says it plainly. */
export function rangeMessage(
  range: WidgetRange,
  result: DateNavigationResult,
  zone: string
): string | null {
  let format: Intl.DateTimeFormat
  try {
    format = new Intl.DateTimeFormat(LOCALE, { timeZone: zone, dateStyle: 'medium' })
  } catch {
    format = new Intl.DateTimeFormat(LOCALE, { dateStyle: 'medium' })
  }
  const date = result.from === undefined ? '' : format.format(new Date(result.from * 1000))
  switch (result.status) {
    case 'no-data':
      return `No bars to show for ${range.label}.`
    case 'error':
      return `${range.label} could not be shown: ${HISTORY_FAILED}.`
    case 'partial':
      if (result.clipped)
        return `${range.label} holds more bars than the chart can fit. Showing the most recent ones.`
      if (result.history === 'unavailable')
        return `Older history cannot load right now. ${range.label} shows from ${date}.`
      return `The broker's history at this interval starts on ${date}, so ${range.label} shows from there.`
    default:
      return null
  }
}

/* ── the bar ───────────────────────────────────────────────────────────── */

/**
 * Mount the bar. `root` covers the chart grid so the bar's menus and the Go
 * to panel open over the charts; only the strip and those popovers take the
 * pointer.
 */
export function mountTradingBottomBar(
  root: HTMLElement,
  options: BottomBarOptions
): TradingBottomBar {
  const doc = root.ownerDocument
  injectWidgetStyles(doc, WIDGET_COMPONENT_CSS)
  injectHostCss(doc)
  root.classList.add('oac-widget', 'oac-alert-host', 'oa-bottombar-root')
  const strip = doc.createElement('div')
  root.appendChild(strip)
  const overlays = createOverlayStack(root, doc)
  const tips = createTipController(root, overlays.layer, doc)
  // The page's Escape handler leaves an open popover to close itself first.
  const announce = () => {
    root.dataset.tradingDialogOpen = String(overlays.size() > 0)
  }
  const openOverlay: WidgetContext['openOverlay'] = (el, opts) => {
    const close = overlays.open(el, {
      ...opts,
      onClose: () => {
        opts?.onClose?.()
        announce()
      },
    })
    announce()
    return close
  }
  // Typing a date must not reach the chart's shortcuts.
  const stopKeys = (event: KeyboardEvent) => event.stopPropagation()
  root.addEventListener('keydown', stopKeys)

  let goTo: PanelHandle | null = null
  const openGoTo = (anchor: HTMLElement): boolean => {
    const pane = options.pane()
    const chart = pane?.liveChart()
    if (!pane || !chart) {
      options.notify('Wait for the chart to finish loading, then pick a date.', 'info')
      return false
    }
    goTo?.close()
    const navigator = navigatorFor(pane)
    // The panel needs the chart, its interval and a place to open; it reads
    // nothing else of a full widget context.
    const context = {
      chart,
      document: doc,
      locale: LOCALE,
      tips,
      openOverlay,
      interval: () => pane.currentInterval(),
      // The panel shows every outcome itself and stays open on any shortfall.
      status: () => {},
    } as unknown as WidgetContext
    goTo = openDateNavigation(context, anchor, {
      navigate: async (target) => plainError(await navigator.goTo(target)),
      cancel: () => navigator.cancel(),
    })
    return true
  }

  const bar: BottombarHandle = mountBottombar(
    {
      document: doc,
      locale: LOCALE,
      tips,
      openOverlay,
      // The bar reports a range's outcome here as well; the range path below
      // words its own, and the timezone menu only lists zones that exist.
      status: () => {},
    },
    strip,
    {
      target: () => {
        const pane = options.pane()
        const chart = pane?.liveChart()
        if (!pane || !chart) return null
        return {
          chart,
          interval: () => pane.currentInterval(),
          range: () => pane.activeRange(),
          setRange: async (id: string) => {
            const range = DEFAULT_RANGES.find((r) => r.id === id)
            const result = await applyRange(pane, id)
            const zone = pane.liveChart()?.timezone() ?? 'Asia/Kolkata'
            const text = range ? rangeMessage(range, result, zone) : null
            if (text) options.notify(text, result.status === 'error' ? 'error' : 'info')
            return result
          },
        }
      },
      onGoTo: openGoTo,
      // The zone joins the pane's chart settings, so a rebuild keeps it.
      onTimezone: (zone) => {
        void options.pane()?.applyChartSettings({ 'time.timezone': zone })
      },
    }
  )

  // A scale toggle is kept like the same switch in Chart settings, which is
  // what a theme or chart type rebuild restores from.
  const onScaleClick = (event: MouseEvent) => {
    const button = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-scale]')
    if (!button || button.getAttribute('aria-disabled') === 'true') return
    const pane = options.pane()
    const chart = pane?.liveChart()
    if (!pane || !chart) return
    const which = button.dataset.scale as BottombarScaleToggle
    const key = which === 'auto' ? 'scales.autoScale' : 'scales.mode'
    const value = readChartSettings(chart)[key]
    if (value !== undefined) void pane.applyChartSettings({ [key]: value })
  }
  strip.addEventListener('click', onScaleClick)

  return {
    refresh: () => bar.refresh(),
    paneLoaded: (pane) => {
      const id = pane.activeRange()
      const range = DEFAULT_RANGES.find((r) => r.id === id)
      if (!range) return
      const mine = bump(pane)
      // Called from inside the load: wait for it to settle, then place.
      void pane.showInterval(pane.currentInterval()).then((ready) => {
        if (ready && mine === requests.get(pane) && pane.activeRange() === range.id)
          void placeRange(pane, range, mine)
      })
    },
    setTheme: (theme, name) => {
      root.dataset.theme = name
      applyTokens(root, widgetTokens(theme, name))
    },
    destroy: () => {
      goTo?.close()
      strip.removeEventListener('click', onScaleClick)
      root.removeEventListener('keydown', stopKeys)
      bar.destroy()
      tips.destroy()
      overlays.destroy()
      strip.remove()
      root.classList.remove('oac-widget', 'oac-alert-host', 'oa-bottombar-root')
      delete root.dataset.tradingDialogOpen
    },
  }
}

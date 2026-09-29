/**
 * Historify charts: the full charting engine over locally downloaded data.
 *
 * Everything drawn here comes out of the DuckDB store, never a broker. There is
 * no live feed and no order path anywhere on the page, and neither is switched
 * off by a setting: the feed implements no subscription and the chart component
 * has no order callback to pass. See `createHistorifyFeed` and `OpenAlgoChart`.
 *
 * The page owns instrument selection and the grid; each pane owns its own
 * chart. The symbol list is restricted to the catalog, which is the whole point
 * of the surface: it shows you what you hold, not what you could trade.
 */

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { historifyApi, historifyError } from '@/api/historify'
import { ChartGrid, ChartLayoutPicker } from '@/components/chart/ChartGrid'
import { HistorifyChartPane, type PaneState } from '@/components/historify/HistorifyChartPane'
import { Navbar } from '@/components/layout/Navbar'
import { Button } from '@/components/ui/button'
import { createHistorifyFeed } from '@/lib/chart/feeds/historifyFeed'
import { layoutById } from '@/lib/chart/layouts'
import { findCatalogSymbol, toCatalogSymbols } from '@/lib/historify/catalog'
import { availableIntervals } from '@/lib/historify/intervals'
import { showToast } from '@/utils/toast'

const LAYOUT_KEY = 'historify-charts-layout'
const PANES_KEY = 'historify-charts-panes'

const BLANK_PANE: PaneState = {
  symbol: '',
  exchange: 'NSE',
  interval: 'D',
  chartType: 'candlestick',
}

function readLayout(): string {
  try {
    return localStorage.getItem(LAYOUT_KEY) ?? 'single'
  } catch {
    return 'single'
  }
}

/**
 * One stored pane, with every field checked rather than asserted.
 *
 * `JSON.parse` returns `any`, and casting it to `PaneState` is a claim about
 * data this code did not write. Anything that survived a release that changed
 * the shape, or a hand-edited store, arrives here; a non-string `symbol` then
 * reaches `symbol.toUpperCase()` in the API layer and throws where nothing is
 * expecting a throw. A wrong field is replaced with the blank pane's value,
 * because a chart that opens on a default is a better answer than one that
 * does not open.
 */
export function toPaneState(value: unknown): PaneState {
  const row = (value ?? {}) as Record<string, unknown>
  const text = (field: unknown, fallback: string) =>
    typeof field === 'string' && field.length <= 64 ? field : fallback

  return {
    symbol: text(row.symbol, BLANK_PANE.symbol),
    exchange: text(row.exchange, BLANK_PANE.exchange),
    interval: text(row.interval, BLANK_PANE.interval),
    chartType: text(row.chartType, BLANK_PANE.chartType),
  }
}

function readPanes(): PaneState[] {
  try {
    const raw = localStorage.getItem(PANES_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    // Capped at the largest grid so a tampered or stale store cannot make the
    // page build an unbounded number of panes.
    return Array.isArray(parsed) ? parsed.slice(0, 8).map(toPaneState) : []
  } catch {
    // A cleared or blocked store is not an error worth reporting. The page
    // simply opens on a blank pane, which is where a first visit starts anyway.
    return []
  }
}

export default function HistorifyCharts() {
  const navigate = useNavigate()
  const { symbol: urlSymbol } = useParams()
  const [searchParams] = useSearchParams()

  const [layoutId, setLayoutId] = useState(readLayout)
  const [panes, setPanes] = useState<PaneState[]>(readPanes)
  const [focused, setFocused] = useState(0)

  const preset = layoutById(layoutId)

  /**
   * One feed for the page.
   *
   * Memoized because its identity is what tells every chart whether its data
   * source changed; a new object each render would rebuild all of them and
   * throw away the viewport, drawings and studies on every keystroke.
   */
  const feed = useMemo(() => createHistorifyFeed(), [])

  const catalog = useQuery({
    queryKey: ['historify', 'catalog-metadata'],
    queryFn: ({ signal }) => historifyApi.catalogMetadata(signal),
    // The store only changes when a download finishes, which is a different
    // page, so there is nothing to gain from refetching on every focus.
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })

  const symbols = useMemo(() => toCatalogSymbols(catalog.data ?? []), [catalog.data])

  // The current page reported a catalog failure by doing nothing at all, which
  // left an empty picker and no way to tell "nothing downloaded" from "the
  // request failed".
  useEffect(() => {
    if (!catalog.isError) return
    showToast.error(
      historifyError(
        catalog.error,
        'Your downloaded data could not be listed. Reload the page, and check that OpenAlgo is still running if it keeps failing.'
      ),
      'historify'
    )
  }, [catalog.isError, catalog.error])

  useEffect(() => {
    try {
      localStorage.setItem(LAYOUT_KEY, layoutId)
    } catch {
      // Not remembering the layout is a small loss and never worth an error.
    }
  }, [layoutId])

  useEffect(() => {
    try {
      localStorage.setItem(PANES_KEY, JSON.stringify(panes))
    } catch {
      // As above.
    }
  }, [panes])

  const paneAt = useCallback((index: number) => panes[index] ?? BLANK_PANE, [panes])

  const updatePane = useCallback((index: number, next: Partial<PaneState>) => {
    setPanes((previous) => {
      const copy = [...previous]
      while (copy.length <= index) copy.push({ ...BLANK_PANE })
      copy[index] = { ...copy[index], ...next }
      return copy
    })
  }, [])

  /**
   * Adopt a deep link from the Historify manager, once the catalog is known.
   *
   * It waits for the catalog because the link carries no timeframe guarantee:
   * a symbol downloaded at 1m only cannot open on D, and landing on an empty
   * chart is a worse answer than landing on a timeframe it has.
   */
  const [linkApplied, setLinkApplied] = useState(false)
  useEffect(() => {
    if (linkApplied || !urlSymbol || symbols.length === 0) return
    const exchange = (searchParams.get('exchange') || 'NSE').toUpperCase()
    const wanted = searchParams.get('interval') || 'D'
    const row = findCatalogSymbol(symbols, urlSymbol.toUpperCase(), exchange)

    setLinkApplied(true)
    if (!row) {
      showToast.error(
        `${urlSymbol.toUpperCase()} has not been downloaded on ${exchange} yet. Download it from Historify to chart it.`,
        'historify'
      )
      return
    }
    const options = availableIntervals(row.sources)
    updatePane(0, {
      symbol: row.symbol,
      exchange: row.exchange,
      interval: options.includes(wanted) ? wanted : (options[0] ?? wanted),
    })
  }, [linkApplied, urlSymbol, searchParams, symbols, updatePane])

  /**
   * Keep the address bar pointing at the focused chart.
   *
   * The page this replaces wrote only the query string, so the path kept the
   * symbol it was opened with and a copied link sent someone to the wrong
   * instrument.
   */
  const lead = paneAt(0)
  useEffect(() => {
    if (!lead.symbol) return
    const next = `/historify/charts/${encodeURIComponent(lead.symbol)}?exchange=${encodeURIComponent(lead.exchange)}&interval=${encodeURIComponent(lead.interval)}`
    navigate(next, { replace: true })
  }, [lead.symbol, lead.exchange, lead.interval, navigate])

  /**
   * The page's own controls, folded into the first pane's toolbar.
   *
   * They used to sit on a full-width strip, which put a third row of chrome
   * above the chart where /trading manages with two, and spent that height on
   * four controls. They are page-level, so only pane zero is given them.
   */
  const pageControls = (
    <>
      <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" asChild>
        <Link to="/historify" title="Back to Historify">
          <ArrowLeft className="h-4 w-4" />
        </Link>
      </Button>
      <ChartLayoutPicker layoutId={layoutId} onChange={setLayoutId} className="h-7 w-7 shrink-0" />
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 shrink-0"
        title={
          catalog.isLoading
            ? 'Reading your local data'
            : `Reload downloaded symbols (${symbols.length})`
        }
        onClick={() => void catalog.refetch()}
        disabled={catalog.isFetching}
      >
        <RefreshCw className={catalog.isFetching ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
      </Button>
    </>
  )

  return (
    <>
      <Navbar fluid />
      <div className="flex flex-1 flex-col overflow-hidden">
        <ChartGrid
          preset={preset}
          renderPane={(paneId, index) => (
            <HistorifyChartPane
              paneId={paneId}
              feed={feed}
              symbols={symbols}
              state={paneAt(index)}
              onChange={(next) => updatePane(index, next)}
              loading={catalog.isLoading}
              focused={focused === index && preset.cells.length > 1}
              onFocus={() => setFocused(index)}
              persistKey={`historify-charts-pane-${index}`}
              pageControls={index === 0 ? pageControls : undefined}
            />
          )}
        />
      </div>
    </>
  )
}

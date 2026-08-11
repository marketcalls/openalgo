import {
  Activity,
  BarChart3,
  Briefcase,
  Layers,
  LineChart,
  Sparkles,
  TrendingUp,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { apiClient } from '@/api/client'
import { oiProfileApi } from '@/api/oi-profile'
import { optionChainApi } from '@/api/option-chain'
import { type PortfolioEntry, strategyPortfolioApi, type Watchlist } from '@/api/strategy-portfolio'
import { EditLegDialog } from '@/components/strategy-builder/EditLegDialog'
import { GreeksTab, type LegGreeks } from '@/components/strategy-builder/GreeksTab'
import { type LegDraft, ManualLegBuilder } from '@/components/strategy-builder/ManualLegBuilder'
import MultiStrikeOITab from '@/components/strategy-builder/MultiStrikeOITab'
import { PayoffChart } from '@/components/strategy-builder/PayoffChart'
import { PnLTab } from '@/components/strategy-builder/PnLTab'
import { PositionsPanel } from '@/components/strategy-builder/PositionsPanel'
import { SaveStrategyDialog } from '@/components/strategy-builder/SaveStrategyDialog'
import { Simulators } from '@/components/strategy-builder/Simulators'
import StrategyChartTab from '@/components/strategy-builder/StrategyChartTab'
import { SymbolHeader } from '@/components/strategy-builder/SymbolHeader'
import {
  type ResolvedTemplateLeg,
  TemplateDialog,
} from '@/components/strategy-builder/TemplateDialog'
import { TemplateGrid } from '@/components/strategy-builder/TemplateGrid'
import { ExecuteBasketDialog } from '@/components/trading/ExecuteBasketDialog'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useOptionChainLive } from '@/hooks/useOptionChainLive'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import {
  type ChainIdentity,
  chainIdentity,
  chainMatches,
  contractPriceKey,
  type ListedOptionChainResponse,
  resolveOptionContract,
} from '@/lib/strategyContracts'
import {
  buildFutureSymbol,
  buildOptionSymbol,
  computePayoff,
  daysToExpiry,
  daysToYears,
  nearestLegDays,
  netCredit,
  payoffPriceRange,
  probabilityOfProfit,
  type StrategyLeg,
  totalPnlAt,
  totalPremium,
} from '@/lib/strategyMath'
import type { Direction, StrategyTemplate } from '@/lib/strategyTemplates'
import {
  canReuseChainContract,
  normalizeExpiryCode,
  resolveListedContract,
} from '@/lib/templateResolution'
import { useAuthStore } from '@/stores/authStore'
import { showToast } from '@/utils/toast'

function optionExchangeFor(exchange: string): string {
  if (exchange === 'NFO' || exchange === 'NSE_INDEX') return 'NFO'
  if (exchange === 'BFO' || exchange === 'BSE_INDEX') return 'BFO'
  return exchange
}

function underlyingExchangeFor(exchange: string, symbol: string): string {
  const INDEXES_NSE = new Set(['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50'])
  const INDEXES_BSE = new Set(['SENSEX', 'BANKEX', 'SENSEX50'])
  if (INDEXES_NSE.has(symbol)) return 'NSE_INDEX'
  if (INDEXES_BSE.has(symbol)) return 'BSE_INDEX'
  return exchange
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10)
}

interface PendingIdentityChange {
  kind: 'exchange' | 'underlying'
  value: string
}

/**
 * Serialize every broker-backed API call this page issues.
 *
 * The remaining broker APIs on this page (expiry discovery, margin, and
 * explicitly resolved cross-expiry contracts) share a backend HTTP client.
 * HTTP/2 httpx client occasionally races on stream reads when ~3+
 * requests multiplex simultaneously, surfacing as
 * ``[Errno 35] Resource temporarily unavailable``.
 *
 * A module-level promise chain is the smallest-possible fix scoped to
 * this page: every call waits its turn, the backend sees one request at
 * a time from this page, the race cannot occur. The extra latency
 * (~150ms per serialized call × 5 = ~750ms on cold load) is acceptable
 * since every call here is backed by a broker fetch that already takes
 * ~150-250ms individually. Other pages keep their parallel behaviour.
 */
let strategyBuilderCallChain: Promise<unknown> = Promise.resolve()
function queuedFetch<T>(fn: () => Promise<T>): Promise<T> {
  const next = strategyBuilderCallChain.then(fn, fn)
  // Swallow errors on the chain so one failure doesn't break the next
  // caller — each caller still sees its own rejection via the returned
  // promise.
  strategyBuilderCallChain = next.catch(() => undefined)
  return next
}

export default function StrategyBuilder() {
  const { apiKey } = useAuthStore()
  const {
    toolsFnoExchanges: fnoExchanges,
    defaultToolsFnoExchange: defaultFnoExchange,
    defaultUnderlyings,
  } = useSupportedExchanges()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [isHydrating, setIsHydrating] = useState(() => {
    const loadId = Number(searchParams.get('load'))
    return searchParams.has('load') && Number.isFinite(loadId)
  })

  const [selectedExchange, setSelectedExchange] = useState(defaultFnoExchange)
  const [underlyings, setUnderlyings] = useState<string[]>(
    defaultUnderlyings[defaultFnoExchange] || []
  )
  const [selectedUnderlying, setSelectedUnderlying] = useState(
    defaultUnderlyings[defaultFnoExchange]?.[0] || ''
  )
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [expiries, setExpiries] = useState<string[]>([])
  const [futureExpiries, setFutureExpiries] = useState<string[]>([])
  const [selectedExpiry, setSelectedExpiry] = useState('')

  const [chainData, setChainData] = useState<ListedOptionChainResponse | null>(null)
  const [legs, setLegs] = useState<StrategyLeg[]>([])
  const [direction, setDirection] = useState<Direction>('BULLISH')

  const [activeTemplate, setActiveTemplate] = useState<StrategyTemplate | null>(null)
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false)

  const [spotShiftPct, setSpotShiftPct] = useState(0)
  const [ivShiftPct, setIvShiftPct] = useState(0)
  const [daysElapsed, setDaysElapsed] = useState(0)

  const [payoffClock, setPayoffClock] = useState(() => Date.now())

  const [editLegId, setEditLegId] = useState<string | null>(null)
  const [marginRequired, setMarginRequired] = useState<number | null>(null)
  const [isMarginLoading, setIsMarginLoading] = useState(false)
  // null = unknown yet; true/false once we've probed the broker.
  const [marginSupported, setMarginSupported] = useState<boolean | null>(null)

  // Portfolio persistence state
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [loadedEntry, setLoadedEntry] = useState<PortfolioEntry | null>(null)
  const [pendingIdentityChange, setPendingIdentityChange] =
    useState<PendingIdentityChange | null>(null)

  // Basket execution dialog
  const [executeDialogOpen, setExecuteDialogOpen] = useState(false)

  const marginGenerationRef = useRef(0)
  const marginSupportedRef = useRef<boolean | null>(null)
  const hydratedIdentityRef = useRef<ChainIdentity | null>(null)

  const requestIdentity = useMemo<ChainIdentity>(
    () => ({
      exchange: optionExchangeFor(selectedExchange),
      underlying: selectedUnderlying,
      expiry: normalizeExpiryCode(selectedExpiry),
    }),
    [selectedExchange, selectedUnderlying, selectedExpiry]
  )

  const liveEnabled =
    !isHydrating &&
    Boolean(apiKey && requestIdentity.underlying && requestIdentity.expiry) &&
    expiries.includes(requestIdentity.expiry)
  const {
    data: liveData,
    forwardPrice,
    clockOffsetMs,
    isLoading: isLiveLoading,
    isStreaming,
    isPaused,
    lastStreamUpdate,
    dataIdentity,
    refetch: refetchLiveChain,
  } = useOptionChainLive(
    apiKey,
    requestIdentity.underlying,
    underlyingExchangeFor(selectedExchange, requestIdentity.underlying),
    requestIdentity.exchange,
    requestIdentity.expiry,
    20,
    { enabled: liveEnabled, oiRefreshInterval: 30_000, pauseWhenHidden: true }
  )

  useEffect(() => {
    if (!liveData || !dataIdentity) {
      setChainData(null)
      return
    }
    const tagged: ListedOptionChainResponse = {
      ...liveData,
      exchange: dataIdentity.exchange,
    }
    setChainData(chainMatches(tagged, dataIdentity) ? tagged : null)
  }, [liveData, dataIdentity])

  const activeChain = useMemo(
    () => (chainData && chainMatches(chainData, requestIdentity) ? chainData : null),
    [chainData, requestIdentity]
  )
  const connectionStatus = useMemo<'live' | 'refreshing' | 'stale' | 'idle'>(() => {
    if (isLiveLoading) return 'refreshing'
    if (!activeChain) return 'idle'
    const isRecent =
      lastStreamUpdate !== null && payoffClock - lastStreamUpdate.getTime() <= 60_000
    return isStreaming && !isPaused && isRecent ? 'live' : 'stale'
  }, [activeChain, isLiveLoading, isPaused, isStreaming, lastStreamUpdate, payoffClock])

  // OpenAlgo-symbol → tick size map, built from the live option chain.
  // Powers per-leg price snapping in the Execute Basket dialog so options
  // priced in 0.05 ticks never leak floating-point drift into the order,
  // and crypto legs with 0.0001 / 0.5 ticks are respected too.
  const tickSizeBySymbol = useMemo(() => {
    if (!activeChain?.chain) return {}
    const map: Record<string, number> = {}
    for (const row of activeChain.chain) {
      if (row.ce?.symbol && row.ce.tick_size > 0) map[row.ce.symbol] = row.ce.tick_size
      if (row.pe?.symbol && row.pe.tick_size > 0) map[row.pe.symbol] = row.pe.tick_size
    }
    return map
  }, [activeChain])

  // Dynamic, read-only strategy name sent to /basketorder. Prefers the
  // saved portfolio entry name; otherwise synthesises from current state.
  const computedStrategyName = useMemo(() => {
    if (loadedEntry?.name) return loadedEntry.name
    const activeCount = legs.filter((l) => l.active).length
    const template = activeTemplate?.name
    const parts = [selectedUnderlying || 'Strategy']
    if (template) parts.push(template)
    if (selectedExpiry) parts.push(selectedExpiry)
    if (activeCount > 0) parts.push(`(${activeCount}L)`)
    return parts.join(' ')
  }, [loadedEntry, legs, activeTemplate, selectedUnderlying, selectedExpiry])

  // Reset all expiry- / chain-derived state in the same event handler as the
  // underlying or exchange change so React batches them into a single render.
  // Without this, dependent chain orchestration gets one frame where
  // `selectedUnderlying` is new but `selectedExpiry` is
  // still the previous underlying's, and fire an invalid pair at the broker.
  // OptionChain uses the same pattern.
  const resetExpiryAndChainState = useCallback(() => {
    setExpiries([])
    setFutureExpiries([])
    setSelectedExpiry('')
    setChainData(null)
  }, [])

  const resetStrategyState = useCallback(() => {
    marginGenerationRef.current += 1
    marginSupportedRef.current = null
    setLegs([])
    setSpotShiftPct(0)
    setIvShiftPct(0)
    setDaysElapsed(0)
    setMarginRequired(null)
    setMarginSupported(null)
    setIsMarginLoading(false)
    setActiveTemplate(null)
    setTemplateDialogOpen(false)
    setEditLegId(null)
    setLoadedEntry(null)
  }, [])

  const applyIdentityChange = useCallback(
    (change: PendingIdentityChange, clearStrategy: boolean) => {
      if (clearStrategy) resetStrategyState()
      resetExpiryAndChainState()
      hydratedIdentityRef.current = null
      if (change.kind === 'exchange') setSelectedExchange(change.value)
      else setSelectedUnderlying(change.value)
      setPendingIdentityChange(null)
    },
    [resetExpiryAndChainState, resetStrategyState]
  )

  const requestIdentityChange = useCallback(
    (change: PendingIdentityChange) => {
      const current = change.kind === 'exchange' ? selectedExchange : selectedUnderlying
      if (change.value === current) return
      if (legs.length > 0) {
        setPendingIdentityChange(change)
        return
      }
      applyIdentityChange(change, false)
    },
    [applyIdentityChange, legs.length, selectedExchange, selectedUnderlying]
  )

  const handleUnderlyingChange = useCallback(
    (next: string) => {
      requestIdentityChange({ kind: 'underlying', value: next })
    },
    [requestIdentityChange]
  )

  const handleExchangeChange = useCallback(
    (next: string) => {
      requestIdentityChange({ kind: 'exchange', value: next })
    },
    [requestIdentityChange]
  )

  const handleExpiryChange = useCallback(
    (next: string) => {
      const normalized = normalizeExpiryCode(next)
      if (normalized === normalizeExpiryCode(selectedExpiry)) return
      setSelectedExpiry(normalized)
      setChainData(null)
    },
    [selectedExpiry]
  )

  // Re-sync exchange when broker capabilities load async
  useEffect(() => {
    if (isHydrating) return
    setSelectedExchange((prev) =>
      prev && fnoExchanges.some((ex) => ex.value === prev) ? prev : defaultFnoExchange
    )
  }, [defaultFnoExchange, fnoExchanges, isHydrating])

  // Populate the underlyings dropdown. The hard-coded `defaultUnderlyings`
  // map only covers the major indices (NIFTY / BANKNIFTY / ...), so we mirror
  // the Option Chain page and fetch the full F&O list from
  // /search/api/underlyings — which includes every F&O stock (RELIANCE,
  // TCS, HDFCBANK, etc.) in addition to indices. Defaults are shown
  // immediately for fast paint, then replaced when the API resolves.
  useEffect(() => {
    if (isHydrating) return
    const defaults = defaultUnderlyings[selectedExchange] || []
    const hydratedIdentity = hydratedIdentityRef.current
    const preservedUnderlying =
      hydratedIdentity?.exchange === optionExchangeFor(selectedExchange)
        ? hydratedIdentity.underlying
        : null
    setUnderlyings(
      preservedUnderlying && !defaults.includes(preservedUnderlying)
        ? [preservedUnderlying, ...defaults]
        : defaults
    )
    setSelectedUnderlying((prev) =>
      preservedUnderlying ?? (defaults.includes(prev) ? prev : defaults[0] || '')
    )

    let cancelled = false
    ;(async () => {
      try {
        const response = await oiProfileApi.getUnderlyings(selectedExchange)
        if (cancelled) return
        if (response.status === 'success' && response.underlyings.length > 0) {
          setUnderlyings(response.underlyings)
          setSelectedUnderlying((prev) =>
            response.underlyings.includes(prev) ? prev : response.underlyings[0]
          )
        }
      } catch {
        // Keep defaults on failure.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedExchange, defaultUnderlyings, isHydrating])

  // Load expiries (options + futures — different calendars on MCX/CDS especially).
  // Expiries are normalised to the OpenAlgo DDMMMYY format at the source so that
  // every downstream component (header, dialogs, symbol builders) sees a single
  // consistent string — otherwise the Edit dialog can't match leg.expiry
  // ("21APR26") against the raw API value ("21-APR-2026") and the field blanks.
  useEffect(() => {
    if (isHydrating || !apiKey || !selectedUnderlying) return
    // IMPORTANT: clear expiries + selectedExpiry + chainData synchronously
    // BEFORE the fetch starts. Otherwise live-chain orchestration sees the previous underlying's
    // selectedExpiry (e.g. NIFTY's 21APR26) alongside the new
    // selectedUnderlying (BANKNIFTY) and fire an invalid (underlying,
    // expiry) request into the broker, which logs "No strikes found" until
    // the fresh expiries finally arrive.
    const hydratedIdentity = hydratedIdentityRef.current
    const preserveHydratedExpiry =
      hydratedIdentity !== null &&
      chainIdentity(
        hydratedIdentity.exchange,
        hydratedIdentity.underlying,
        hydratedIdentity.expiry
      ) ===
        chainIdentity(
          optionExchangeFor(selectedExchange),
          selectedUnderlying,
          hydratedIdentity.expiry
        )
    const hydratedExpiry = preserveHydratedExpiry ? hydratedIdentity.expiry : ''
    setExpiries(hydratedExpiry ? [hydratedExpiry] : [])
    setFutureExpiries([])
    setSelectedExpiry(hydratedExpiry)
    setChainData(null)
    let cancelled = false
    ;(async () => {
      try {
        const optionExchange = optionExchangeFor(selectedExchange)
        // Serialize the two `/expiry` calls through the page queue so they
        // don't multiplex with each other or with the other mount-time
        // fetches below.
        const optsRes = await queuedFetch(() =>
          optionChainApi.getExpiries(apiKey, selectedUnderlying, optionExchange, 'options')
        )
        const futsRes = await queuedFetch(() =>
          optionChainApi
            .getExpiries(apiKey, selectedUnderlying, optionExchange, 'futures')
            .catch(() => ({ status: 'error' as const, data: [] as string[] }))
        )
        if (cancelled) return
        const normaliseList = (list: string[]) =>
          // Preserve order but drop empties and de-dupe after normalisation.
          Array.from(new Set(list.filter(Boolean).map(normalizeExpiryCode)))
        if (
          optsRes.status === 'success' &&
          Array.isArray(optsRes.data) &&
          optsRes.data.length > 0
        ) {
          const normalised = normaliseList(optsRes.data)
          setExpiries(normalised)
          setSelectedExpiry((prev) => (normalised.includes(prev) ? prev : normalised[0]))
        } else {
          setExpiries([])
          setSelectedExpiry('')
        }
        if (futsRes.status === 'success' && Array.isArray(futsRes.data)) {
          setFutureExpiries(normaliseList(futsRes.data))
        } else {
          setFutureExpiries([])
        }
      } catch (_err) {
        if (!cancelled) {
          showToast.error('Failed to fetch expiries')
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiKey, selectedUnderlying, selectedExchange, isHydrating])

  // Derived: ATM strike, lot size, spot
  const spotPrice = activeChain?.underlying_ltp ?? null
  const atmStrike = activeChain?.atm_strike ?? null
  const futuresPrice = activeChain ? forwardPrice : null
  const atmIv = useMemo(() => {
    if (!activeChain) return null
    const atmRow = activeChain.chain.find((row) => row.strike === activeChain.atm_strike)
    const ivs = [atmRow?.ce?.implied_volatility, atmRow?.pe?.implied_volatility].filter(
      (iv): iv is number => typeof iv === 'number' && iv > 0
    )
    return ivs.length > 0 ? ivs.reduce((sum, iv) => sum + iv, 0) / ivs.length : null
  }, [activeChain])
  const lotSize = useMemo(() => {
    if (!activeChain?.chain) return null
    const atmRow = activeChain.chain.find((s) => s.strike === activeChain.atm_strike)
    return atmRow?.ce?.lotsize ?? atmRow?.pe?.lotsize ?? null
  }, [activeChain])

  // Common strike step — try to detect from chain spacing
  const strikeStep = useMemo(() => {
    if (!activeChain?.chain || activeChain.chain.length < 2) return 50
    const sorted = [...activeChain.chain].map((s) => s.strike).sort((a, b) => a - b)
    let minDiff = Infinity
    for (let i = 1; i < sorted.length; i++) {
      const d = sorted[i] - sorted[i - 1]
      if (d > 0 && d < minDiff) minDiff = d
    }
    return Number.isFinite(minDiff) ? minDiff : 50
  }, [activeChain])

  useEffect(() => {
    const interval = window.setInterval(() => setPayoffClock(Date.now()), 60_000)
    return () => window.clearInterval(interval)
  }, [])
  const marketClock = payoffClock + clockOffsetMs

  // DTE of the header-selected expiry (for the metadata badge only).
  const rawDays = useMemo(() => {
    if (!selectedExpiry) return null
    if (activeChain?.expiry_ts) {
      return Math.max(0, activeChain.expiry_ts * 1000 - marketClock) / 86_400_000
    }
    const expiryCode = normalizeExpiryCode(selectedExpiry)
    return daysToExpiry(expiryCode, new Date(marketClock))
  }, [selectedExpiry, activeChain?.expiry_ts, marketClock])

  // For the payoff curve: "At Expiry" uses the NEAREST leg's days-to-expiry
  // so calendar / diagonal spreads render correctly (the far leg retains
  // remaining time value). Falls back to the header expiry when no legs yet.
  const nearestDays = useMemo(() => {
    if (legs.length === 0) return rawDays ?? 0
    return nearestLegDays(legs, new Date(marketClock))
  }, [legs, rawDays, marketClock])

  // Simulator caps "days forward" to the nearest expiry so the T+0 slider
  // can't go past the first leg's expiration.
  const maxSimulatorDays = Math.max(0, Math.floor(nearestDays))
  const clampedDaysElapsed = Math.min(daysElapsed, maxSimulatorDays)

  // Remaining "simulated" years to the near expiry — for σ bands / PoP.
  const simulatedYearsToNearExpiry = daysToYears(Math.max(nearestDays - clampedDaysElapsed, 0))

  // Shifted spot for the payoff calculations
  const simulatedSpot = spotPrice !== null ? spotPrice * (1 + spotShiftPct / 100) : 0

  const liveContractsByKey = useMemo(() => {
    const contracts = new Map<
      string,
      NonNullable<ListedOptionChainResponse['chain'][number]['ce']>
    >()
    if (!activeChain) return contracts
    for (const row of activeChain.chain) {
      if (row.ce) contracts.set(contractPriceKey(activeChain.exchange, row.ce.symbol), row.ce)
      if (row.pe) contracts.set(contractPriceKey(activeChain.exchange, row.pe.symbol), row.pe)
    }
    return contracts
  }, [activeChain])

  const greeksByLeg = useMemo<Record<string, LegGreeks>>(() => {
    const greeks: Record<string, LegGreeks> = {}
    for (const leg of legs) {
      const contract = leg.exchange
        ? liveContractsByKey.get(contractPriceKey(leg.exchange, leg.symbol))
        : undefined
      greeks[leg.id] = {
        legId: leg.id,
        iv: contract?.implied_volatility ?? (leg.iv > 0 ? leg.iv : null),
        delta: contract?.delta ?? leg.marketGreeks?.delta ?? null,
        gamma: contract?.gamma ?? leg.marketGreeks?.gamma ?? null,
        theta: contract?.theta ?? leg.marketGreeks?.theta ?? null,
        vega: contract?.vega ?? leg.marketGreeks?.vega ?? null,
      }
    }
    return greeks
  }, [legs, liveContractsByKey])

  // Refresh only market metadata. Entry price is intentionally immutable: a
  // live tick changes current P&L, never the premium at which the leg was added.
  useEffect(() => {
    if (!activeChain) return
    setLegs((previous) => {
      let changed = false
      const next = previous.map((leg) => {
        if (leg.segment !== 'OPTION' || !leg.exchange) return leg
        const contract = liveContractsByKey.get(contractPriceKey(leg.exchange, leg.symbol))
        if (!contract) return leg
        const market = {
          marketPrice: contract.ltp,
          iv: contract.implied_volatility ?? 0,
          referenceUnderlying: activeChain.underlying_ltp,
          forwardPrice: activeChain.forward_price ?? undefined,
          expiryTs: activeChain.expiry_ts ?? null,
          tickSize: contract.tick_size,
          lotSize: contract.lotsize,
        }
        if (
          leg.marketPrice === market.marketPrice &&
          leg.iv === market.iv &&
          leg.referenceUnderlying === market.referenceUnderlying &&
          leg.forwardPrice === market.forwardPrice &&
          leg.expiryTs === market.expiryTs &&
          leg.tickSize === market.tickSize &&
          leg.lotSize === market.lotSize
        ) {
          return leg
        }
        changed = true
        return { ...leg, ...market }
      })
      return changed ? next : previous
    })
  }, [activeChain, liveContractsByKey])

  const marginRequestKey = useMemo(() => {
    const exchange = optionExchangeFor(selectedExchange)
    return JSON.stringify(
      legs
        .filter((leg) => leg.active && !(leg.exitPrice !== undefined && leg.exitPrice > 0))
        .map((leg) => ({
          exchange: leg.exchange ?? exchange,
          symbol: leg.symbol,
          action: leg.side,
          quantity: String(leg.lots * leg.lotSize),
          product: 'NRML',
          pricetype: leg.price > 0 ? 'LIMIT' : 'MARKET',
          price: leg.price > 0 ? String(leg.price) : '0',
        }))
    )
  }, [legs, selectedExchange])

  // Margin depends on the normalized broker request, not live market metadata
  // or the capability response produced by the request itself.
  useEffect(() => {
    const generation = ++marginGenerationRef.current
    let cancelled = false
    const isCurrent = () => !cancelled && generation === marginGenerationRef.current
    if (!apiKey) {
      return () => {
        cancelled = true
      }
    }
    const positions = JSON.parse(marginRequestKey) as Array<{
      exchange: string
      symbol: string
      action: string
      quantity: string
      product: string
      pricetype: string
      price: string
    }>
    if (positions.length === 0) {
      setMarginRequired(null)
      setIsMarginLoading(false)
      return () => {
        cancelled = true
      }
    }
    // If we've already determined the broker doesn't support margin,
    // don't keep probing — just skip.
    if (marginSupportedRef.current === false) {
      return () => {
        cancelled = true
      }
    }

    const handle = setTimeout(async () => {
      if (!isCurrent()) return
      setIsMarginLoading(true)
      try {
        // NOTE: MarginPositionSchema declares `quantity` and `price` as
        // Str fields — sending them as numbers fails Marshmallow validation
        // with a 400 (no descriptive message), which earlier silently
        // suppressed the Margin row. Keep these as strings.
        const res = await queuedFetch(() =>
          apiClient.post<{
            status: string
            data?: {
              total_margin_required?: number
              total_margin?: number
              margin_required?: number
            }
            message?: string
          }>(
            '/margin',
            { apikey: apiKey, positions },
            // Let 4xx/5xx responses resolve instead of throw so we can inspect them.
            { validateStatus: () => true }
          )
        )
        if (!isCurrent()) return
        // Response key varies slightly across brokers — accept any of the
        // three field names the service has been observed to return.
        const total =
          res.data?.data?.total_margin_required ??
          res.data?.data?.total_margin ??
          res.data?.data?.margin_required ??
          null
        if (res.status === 200 && res.data.status === 'success' && typeof total === 'number') {
          setMarginRequired(total)
          marginSupportedRef.current = true
          setMarginSupported(true)
        } else {
          // Any non-success response (404/501/error message about unsupported
          // broker) means this broker doesn't expose margin — hide the metric.
          const msg = (res.data?.message || '').toLowerCase()
          const unsupported =
            res.status === 404 ||
            res.status === 501 ||
            msg.includes('not support') ||
            msg.includes('unsupported') ||
            msg.includes('not implemented')
          if (unsupported) {
            marginSupportedRef.current = false
            setMarginSupported(false)
          }
          setMarginRequired(null)
          // Surface the failure in the dev console so future schema
          // mismatches or broker quirks are easier to diagnose.
          console.warn('Margin calculation failed', {
            status: res.status,
            body: res.data,
          })
        }
      } catch {
        // Network failures shouldn't permanently disable — just clear for now.
        if (isCurrent()) setMarginRequired(null)
      } finally {
        if (isCurrent()) setIsMarginLoading(false)
      }
    }, 400)
    return () => {
      cancelled = true
      clearTimeout(handle)
    }
  }, [apiKey, marginRequestKey])

  // Backfill price for legs that were added without one (typically the far-
  // expiry leg of a calendar/diagonal — the loaded chain only covers the
  // near expiry, so those legs start at price=0 and we need /multiquotes
  // to supply the LTP). Runs only for legs whose price is still 0 and
  // haven't been edited closed.
  useEffect(() => {
    if (!apiKey) return
    const needs = legs.filter(
      (l) => l.price === 0 && !(l.exitPrice !== undefined && l.exitPrice > 0) && l.symbol
    )
    if (needs.length === 0) return
    const exchange = optionExchangeFor(selectedExchange)
    let cancelled = false
    ;(async () => {
      try {
        const res = await queuedFetch(() =>
          apiClient.post<{
            status: string
            results?: Array<{ symbol: string; exchange: string; data?: { ltp?: number } }>
          }>('/multiquotes', {
            apikey: apiKey,
            symbols: needs.map((l) => ({ symbol: l.symbol, exchange })),
          })
        )
        if (cancelled) return
        if (res.data.status === 'success' && res.data.results) {
          const priceBySymbol: Record<string, number> = {}
          for (const r of res.data.results) {
            if (r.data?.ltp !== undefined && r.data.ltp > 0) {
              priceBySymbol[r.symbol] = r.data.ltp
            }
          }
          if (Object.keys(priceBySymbol).length === 0) return
          setLegs((prev) =>
            prev.map((l) => {
              if (l.price > 0) return l
              const p = priceBySymbol[l.symbol]
              return p !== undefined ? { ...l, price: p } : l
            })
          )
        }
      } catch {
        /* non-fatal */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiKey, legs, selectedExchange])

  // F&O exchange for all leg symbols (used for WebSocket subscription).
  const fnoExchange = useMemo(() => optionExchangeFor(selectedExchange), [selectedExchange])

  // Chain-derived fallback prices (used until the first WS tick arrives).
  // PnLTab itself handles real-time streaming internally to scope tick-
  // driven re-renders (so ticks don't cascade into PayoffChart/Greeks/etc).
  const fallbackPricesByLeg = useMemo(() => {
    const map: Record<string, number> = {}
    if (!activeChain) return map
    for (const leg of legs) {
      if (leg.segment !== 'OPTION' || leg.strike === undefined || !leg.optionType) continue
      const row = activeChain.chain.find((s) => s.strike === leg.strike)
      const side = leg.optionType === 'CE' ? row?.ce : row?.pe
      if (side?.ltp !== undefined) map[leg.id] = side.ltp
    }
    return map
  }, [activeChain, legs])

  // Add legs from a template
  const handleTemplatePick = useCallback(
    (tpl: StrategyTemplate) => {
      if (!activeChain || atmStrike === null) {
        showToast.error('Option chain not loaded yet')
        return
      }
      setActiveTemplate(tpl)
      setTemplateDialogOpen(true)
    },
    [activeChain, atmStrike]
  )

  const handleTemplateConfirm = useCallback(
    async (resolved: ResolvedTemplateLeg[], totalLots: number) => {
      if (!lotSize) {
        showToast.error('Lot size not detected — load the chain first')
        return
      }
      if (!apiKey || !activeChain) {
        showToast.error('Option chain not loaded yet')
        return
      }

      const chainsByExpiry = new Map<string, ListedOptionChainResponse>([
        [normalizeExpiryCode(activeChain.expiry_date || selectedExpiry), activeChain],
      ])
      const requiredExpiries = Array.from(
        new Set(resolved.map((leg) => normalizeExpiryCode(leg.resolvedExpiry)))
      )
      try {
        for (const legExpiry of requiredExpiries) {
          if (chainsByExpiry.has(legExpiry)) continue
          const farChain = await queuedFetch(() =>
            optionChainApi.getOptionChain(
              apiKey,
              selectedUnderlying,
              underlyingExchangeFor(selectedExchange, selectedUnderlying),
              legExpiry,
              20,
              { withGreeks: true }
            )
          )
          if (farChain.status !== 'success' || !Array.isArray(farChain.chain)) {
            showToast.error(`Unable to validate option contracts for ${legExpiry}`)
            return
          }
          const listedFarChain: ListedOptionChainResponse = {
            ...farChain,
            exchange: requestIdentity.exchange,
          }
          if (
            !chainMatches(listedFarChain, {
              exchange: requestIdentity.exchange,
              underlying: selectedUnderlying,
              expiry: legExpiry,
            })
          ) {
            showToast.error(`Received a mismatched option chain for ${legExpiry}`)
            return
          }
          chainsByExpiry.set(legExpiry, listedFarChain)
        }
      } catch {
        showToast.error('Unable to validate every template contract')
        return
      }

      const validated = resolved.map((leg) => {
        const legExpiry = normalizeExpiryCode(leg.resolvedExpiry)
        const response = chainsByExpiry.get(legExpiry)
        const market = response
          ? resolveOptionContract(response, leg.optionType, leg.resolvedStrike)
          : null
        return market ? { leg, legExpiry, market } : null
      })
      const missing = validated.find((item) => item === null)
      if (missing) {
        showToast.error('A required option contract is not available for this template')
        return
      }

      const newLegs: StrategyLeg[] = validated.map((item) => {
        if (item === null) throw new Error('Validated template contract is missing')
        const { leg: r, legExpiry, market } = item
        // Each leg keeps its own expiry — calendars / diagonals span two.
        // Preserve the template's per-leg ratio (e.g. butterfly body = 2 lots,
        // wings = 1 lot) and scale it by the user's chosen lot multiplier.
        // Without this, all legs come in at `totalLots` and ratio spreads /
        // butterflies / condors collapse into wrong shapes.
        const legLots = Math.max(1, (r.lots ?? 1) * totalLots)
        return {
          id: uid(),
          segment: 'OPTION',
          side: r.side,
          lots: legLots,
          lotSize: market.lotSize,
          expiry: legExpiry,
          strike: r.resolvedStrike,
          optionType: r.optionType,
          price: market.marketPrice,
          iv: market.iv,
          active: true,
          symbol: market.symbol,
          exchange: market.exchange,
          expiryTs: market.expiryTs,
          tickSize: market.tickSize,
          marketPrice: market.marketPrice,
          referenceUnderlying: market.referenceUnderlying,
          forwardPrice: market.forwardPrice ?? undefined,
          marketGreeks: market.greeks,
        }
      })
      setLegs((prev) => [...prev, ...newLegs])
      setTemplateDialogOpen(false)
      setActiveTemplate(null)
    },
    [
      lotSize,
      apiKey,
      activeChain,
      selectedExpiry,
      selectedUnderlying,
      selectedExchange,
      requestIdentity.exchange,
    ]
  )

  // Manual leg add
  const handleAddManualLeg = useCallback(
    (draft: LegDraft) => {
      if (!lotSize && draft.segment === 'OPTION') {
        showToast.error('Lot size not detected')
        return
      }
      const expiryCode = normalizeExpiryCode(draft.expiry)

      // Prefer the broker-provided symbol from the live chain whenever
      // possible — some brokers (notably crypto exchanges like Delta) don't
      // follow the standard BASE[DDMMMYY][STRIKE][CE|PE] concatenation, so
      // constructing it locally would produce an invalid symbol.
      let symbol: string
      let optionContract: NonNullable<ListedOptionChainResponse['chain'][number]['ce']> | null = null
      if (draft.segment === 'OPTION' && draft.strike !== undefined && draft.optionType) {
        const row = activeChain?.chain.find((s) => s.strike === draft.strike)
        const side = draft.optionType === 'CE' ? row?.ce : row?.pe
        if (!activeChain || !side) {
          showToast.error('The selected option contract is not available in the active chain')
          return
        }
        optionContract = side
        symbol = side.symbol
      } else {
        symbol = buildFutureSymbol(selectedUnderlying, expiryCode)
      }

      // For futures, fall back to the synthetic-future price when the draft
      // didn't carry one — otherwise the payoff calc treats entry as 0 and
      // returns a runaway positive P&L.
      let entryPrice = draft.price
      if (draft.segment === 'FUTURE' && entryPrice <= 0 && futuresPrice !== null) {
        entryPrice = futuresPrice
      }

      const newLeg: StrategyLeg = {
        id: uid(),
        segment: draft.segment,
        side: draft.side,
        lots: draft.lots,
        lotSize: lotSize ?? 1,
        expiry: expiryCode,
        strike: draft.strike,
        optionType: draft.optionType,
        price: entryPrice,
        iv: 0,
        active: true,
        symbol,
        exchange: optionExchangeFor(selectedExchange),
        expiryTs: optionContract ? (activeChain?.expiry_ts ?? null) : undefined,
        tickSize: optionContract?.tick_size,
        marketPrice: optionContract?.ltp,
        referenceUnderlying: optionContract ? activeChain?.underlying_ltp : undefined,
        forwardPrice: optionContract ? (activeChain?.forward_price ?? undefined) : undefined,
      }
      setLegs((prev) => [...prev, newLeg])
    },
    [lotSize, selectedUnderlying, selectedExchange, futuresPrice, activeChain]
  )

  // Payoff
  const payoff = useMemo(() => {
    if (!spotPrice) {
      return {
        samples: [],
        maxProfit: 0,
        maxLoss: 0,
        breakevens: [],
        zeroCrossings: [],
      }
    }
    // Keep every active strike and the complete ±2σ context in view. This
    // prevents wide structures and high-IV expiries from losing breakevens,
    // payoff kinks, or volatility markers outside a fixed percentage window.
    const range = payoffPriceRange(spotPrice, legs, atmIv ?? 0, simulatedYearsToNearExpiry)
    // "At Expiry" curve → advance calendar time to the nearest leg's expiry;
    // far-dated legs (calendar / diagonal) keep their remaining time value.
    // "T+0" curve → advance by the simulator's days-forward value.
    return computePayoff(
      legs,
      spotPrice,
      nearestDays,
      clampedDaysElapsed,
      range,
      240,
      ivShiftPct,
      atmIv ?? 0,
      new Date(marketClock)
    )
  }, [
    legs,
    spotPrice,
    nearestDays,
    clampedDaysElapsed,
    ivShiftPct,
    atmIv,
    simulatedYearsToNearExpiry,
    marketClock,
  ])

  const pop = useMemo(() => {
    if (!spotPrice || atmIv === null || simulatedYearsToNearExpiry <= 0) return 0
    return probabilityOfProfit(payoff.samples, spotPrice, atmIv, simulatedYearsToNearExpiry)
  }, [payoff.samples, spotPrice, atmIv, simulatedYearsToNearExpiry])

  const totalPnlNow = useMemo(() => {
    if (!spotPrice) return 0
    return totalPnlAt(
      legs,
      simulatedSpot,
      clampedDaysElapsed,
      ivShiftPct,
      atmIv ?? 0,
      new Date(marketClock)
    )
  }, [legs, simulatedSpot, clampedDaysElapsed, ivShiftPct, spotPrice, atmIv, marketClock])

  const credit = useMemo(() => netCredit(legs), [legs])
  const premium = useMemo(() => totalPremium(legs), [legs])

  // Handlers
  const toggleLeg = useCallback((id: string) => {
    setLegs((prev) => prev.map((l) => (l.id === id ? { ...l, active: !l.active } : l)))
  }, [])
  const toggleLegSide = useCallback((id: string) => {
    setLegs((prev) =>
      prev.map((l) => (l.id === id ? { ...l, side: l.side === 'BUY' ? 'SELL' : 'BUY' } : l))
    )
  }, [])
  const removeLeg = useCallback((id: string) => {
    setLegs((prev) => prev.filter((l) => l.id !== id))
  }, [])
  const saveEditedLeg = useCallback(
    (updated: StrategyLeg) => {
      // Normalise expiry to the OpenAlgo DDMMMYY format — the dropdown may
      // have supplied an API-format value like "21-APR-26" which would wreck
      // symbol construction and leg-row rendering otherwise.
      const normalisedExpiry = normalizeExpiryCode(updated.expiry)

      // Prefer the live chain's symbol whenever available so crypto / non-
      // standard option symbols stay correct across edits.
      let rebuiltSymbol: string
      if (updated.segment === 'OPTION' && updated.strike !== undefined && updated.optionType) {
        const side =
          activeChain &&
          canReuseChainContract(normalisedExpiry, activeChain.expiry_date || selectedExpiry)
            ? resolveListedContract(activeChain.chain, updated.strike, updated.optionType)
            : null
        rebuiltSymbol =
          side?.symbol ??
          buildOptionSymbol(
            selectedUnderlying,
            normalisedExpiry,
            updated.strike,
            updated.optionType
          )
      } else {
        rebuiltSymbol = buildFutureSymbol(selectedUnderlying, normalisedExpiry)
      }

      setLegs((prev) =>
        prev.map((l) =>
          l.id === updated.id
            ? {
                ...updated,
                expiry: normalisedExpiry,
                symbol: rebuiltSymbol,
                exchange: updated.exchange ?? optionExchangeFor(selectedExchange),
              }
            : l
        )
      )
      setEditLegId(null)
    },
    [selectedUnderlying, selectedExpiry, activeChain, selectedExchange]
  )
  const toggleAll = useCallback((active: boolean) => {
    setLegs((prev) => prev.map((l) => ({ ...l, active })))
  }, [])
  const resetLegs = useCallback(() => {
    setLegs([])
    setSpotShiftPct(0)
    setIvShiftPct(0)
    setDaysElapsed(0)
  }, [])
  const resetSimulators = useCallback(() => {
    setSpotShiftPct(0)
    setIvShiftPct(0)
    setDaysElapsed(0)
  }, [])

  // Load a saved strategy when arriving with ?load=<id>. We restore symbol,
  // exchange, expiry, and legs; greeks / synthetic-future will refetch
  // automatically once the chain effect hooks pick up the change.
  useEffect(() => {
    const loadId = searchParams.get('load')
    if (!loadId) return
    const id = Number(loadId)
    if (!Number.isFinite(id)) return
    let cancelled = false
    ;(async () => {
      try {
        const entry = await strategyPortfolioApi.get(id)
        if (cancelled) return
        const hydratedExpiry = normalizeExpiryCode(entry.expiry ?? '')
        hydratedIdentityRef.current = {
          exchange: optionExchangeFor(entry.exchange),
          underlying: entry.underlying,
          expiry: hydratedExpiry,
        }
        // Apply the saved identity and legs in one React batch. Defaulting and
        // broker-fetch effects stay gated until this complete snapshot exists.
        setSelectedExchange(entry.exchange)
        setSelectedUnderlying(entry.underlying)
        setSelectedExpiry(hydratedExpiry)
        setChainData(null)
        // Hydrate legs. Mark them loaded so we don't overwrite user IV later.
        const restored: StrategyLeg[] = entry.legs.map((l) => ({
          id: l.id ?? uid(),
          segment: l.segment,
          side: l.side,
          lots: l.lots,
          lotSize: l.lotSize,
          expiry: normalizeExpiryCode(l.expiry),
          strike: l.strike,
          optionType: l.optionType,
          price: l.price,
          iv: l.iv ?? 0,
          active: l.active ?? true,
          symbol: l.symbol,
          exchange: optionExchangeFor(entry.exchange),
          exitPrice: l.exitPrice,
        }))
        setLegs(restored)
        setSpotShiftPct(0)
        setIvShiftPct(0)
        setDaysElapsed(0)
        setLoadedEntry(entry)
        setIsHydrating(false)
        showToast.success(`Loaded "${entry.name}"`)
        // Remove the ?load param so subsequent state changes don't re-fire.
        const nextParams = new URLSearchParams(searchParams)
        nextParams.delete('load')
        setSearchParams(nextParams, { replace: true })
      } catch (err) {
        if (!cancelled) {
          setIsHydrating(false)
          showToast.error(err instanceof Error ? err.message : 'Failed to load strategy')
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [searchParams, setSearchParams])

  const saveOrUpdateStrategy = useCallback(
    async (name: string, watchlist: Watchlist) => {
      if (legs.length === 0) {
        showToast.error('Add at least one leg before saving')
        return
      }
      setIsSaving(true)
      try {
        // Strip volatile runtime-only fields we don't need to persist.
        const legPayload = legs.map((l) => ({
          id: l.id,
          segment: l.segment,
          side: l.side,
          lots: l.lots,
          lotSize: l.lotSize,
          expiry: l.expiry,
          strike: l.strike,
          optionType: l.optionType,
          price: l.price,
          iv: l.iv,
          active: l.active,
          symbol: l.symbol,
          exitPrice: l.exitPrice,
        }))
        const payload = {
          name,
          watchlist,
          underlying: selectedUnderlying,
          exchange: selectedExchange,
          expiry: selectedExpiry || null,
          legs: legPayload,
        }
        const saved = loadedEntry
          ? await strategyPortfolioApi.update(loadedEntry.id, payload)
          : await strategyPortfolioApi.create(payload)
        setLoadedEntry(saved)
        setSaveDialogOpen(false)
        showToast.success(loadedEntry ? 'Strategy updated' : 'Strategy saved')
      } finally {
        setIsSaving(false)
      }
    },
    [legs, selectedExchange, selectedUnderlying, selectedExpiry, loadedEntry]
  )

  return (
    <div className="space-y-5 py-6">
      {/* Page header — Save/Portfolio actions moved down next to the Payoff
          tabs where the user is actually working, so no scrolling back to
          the top is needed. */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          <Sparkles className="h-3 w-3" />
          Tools / Strategy Builder
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-bold tracking-tight">Strategy Builder</h1>
          {loadedEntry && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-violet-700 dark:text-violet-400">
              <span className="h-1.5 w-1.5 rounded-full bg-violet-500" />
              {loadedEntry.name}
            </span>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          Design and analyse multi-leg options strategies with live Greeks and payoff.
        </p>
      </div>

      {/* Symbol header */}
      <SymbolHeader
        exchanges={fnoExchanges}
        selectedExchange={selectedExchange}
        onExchangeChange={handleExchangeChange}
        underlyings={underlyings}
        selectedUnderlying={selectedUnderlying}
        onUnderlyingChange={handleUnderlyingChange}
        underlyingOpen={underlyingOpen}
        onUnderlyingOpenChange={setUnderlyingOpen}
        expiries={expiries}
        selectedExpiry={selectedExpiry}
        onExpiryChange={handleExpiryChange}
        spotPrice={spotPrice}
        futuresPrice={futuresPrice}
        lotSize={lotSize}
        atmIv={atmIv}
        daysToExpiry={rawDays}
        onRefresh={refetchLiveChain}
        isRefreshing={isLiveLoading}
        connectionStatus={connectionStatus}
      />

      {/* Template grid */}
      <div className="overflow-hidden rounded-xl border bg-card p-5 shadow-sm">
        <TemplateGrid
          direction={direction}
          onDirectionChange={setDirection}
          onPick={handleTemplatePick}
        />
      </div>

      {/* Manual leg adder */}
      <ManualLegBuilder
        expiries={activeChain ? expiries : []}
        futureExpiries={activeChain ? futureExpiries : []}
        chain={activeChain?.chain ?? null}
        selectedExpiry={selectedExpiry}
        atmStrike={atmStrike}
        strikeStep={strikeStep}
        onAdd={handleAddManualLeg}
      />

      {/* Main working area — only revealed once the user has at least one leg.
          This avoids an empty-looking Strategy Positions panel and a flat
          payoff chart on first load, which looked like a broken state. */}
      {legs.length === 0 ? (
        <div className="relative overflow-hidden rounded-xl border border-dashed bg-gradient-to-br from-muted/30 via-background to-muted/20 px-6 py-14 shadow-sm">
          {/* Decorative floating icons */}
          <div className="pointer-events-none absolute -left-4 top-6 h-16 w-16 rounded-full bg-emerald-500/5 blur-2xl" />
          <div className="pointer-events-none absolute right-12 top-10 h-20 w-20 rounded-full bg-violet-500/10 blur-3xl" />
          <div className="pointer-events-none absolute bottom-4 left-1/2 h-20 w-40 -translate-x-1/2 rounded-full bg-blue-500/5 blur-3xl" />

          <div className="relative mx-auto max-w-xl space-y-4 text-center">
            <div className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl border bg-background shadow-sm">
              <div className="relative">
                <BarChart3 className="h-7 w-7 text-violet-500/60" />
                <span className="absolute -right-1 -top-1 inline-flex h-3 w-3 items-center justify-center rounded-full bg-emerald-500 ring-2 ring-background">
                  <TrendingUp className="h-2 w-2 text-white" />
                </span>
              </div>
            </div>

            <div className="space-y-1.5">
              <h3 className="text-base font-semibold">Your canvas awaits</h3>
              <p className="mx-auto max-w-md text-[13px] text-muted-foreground">
                Pick a pre-built strategy above, or add a position manually. Payoff chart, Greeks
                and live P&amp;L will materialize here.
              </p>
            </div>

            <div className="flex flex-wrap items-center justify-center gap-2 pt-2">
              <span className="inline-flex items-center gap-1 rounded-full border bg-background/80 px-2.5 py-1 text-[10px] font-medium text-muted-foreground">
                <LineChart className="h-3 w-3" /> Payoff diagrams
              </span>
              <span className="inline-flex items-center gap-1 rounded-full border bg-background/80 px-2.5 py-1 text-[10px] font-medium text-muted-foreground">
                <Sparkles className="h-3 w-3" /> Greeks &amp; IV
              </span>
              <span className="inline-flex items-center gap-1 rounded-full border bg-background/80 px-2.5 py-1 text-[10px] font-medium text-muted-foreground">
                <TrendingUp className="h-3 w-3" /> What-if sims
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
          {/* Left column: positions */}
          <div className="min-w-0">
            <PositionsPanel
              legs={legs}
              onToggleLeg={toggleLeg}
              onToggleSide={toggleLegSide}
              onEditLeg={setEditLegId}
              onRemoveLeg={removeLeg}
              onToggleAll={toggleAll}
              onReset={resetLegs}
              probOfProfit={pop}
              maxProfit={payoff.maxProfit}
              maxLoss={payoff.maxLoss}
              breakevens={payoff.breakevens}
              totalPnl={totalPnlNow}
              netCredit={credit}
              estPremium={premium}
              marginRequired={marginRequired}
              isMarginLoading={isMarginLoading}
              marginSupported={marginSupported}
              atmStrike={atmStrike}
              strikeStep={strikeStep}
              onSaveStrategy={() => setSaveDialogOpen(true)}
              onExecute={() => setExecuteDialogOpen(true)}
              isUpdating={loadedEntry !== null}
              executeDisabled={!apiKey}
            />
          </div>

          {/* Right column: tabs + simulators */}
          <div className="min-w-0 space-y-5">
            <Tabs defaultValue="payoff" className="w-full">
              {/* Tabs on the left, Save/Portfolio actions aligned to the right
                  so they're always visible directly above the Payoff graph —
                  no scrolling back to the page header. */}
              <div className="flex flex-wrap items-center justify-between gap-3">
                <TabsList className="inline-flex h-10 gap-1 rounded-xl border bg-card p-1 shadow-sm">
                  <TabsTrigger
                    value="payoff"
                    className="rounded-lg px-4 text-xs font-semibold data-[state=active]:bg-gradient-to-br data-[state=active]:from-background data-[state=active]:to-muted/60 data-[state=active]:shadow-sm"
                  >
                    <LineChart className="mr-1.5 h-3.5 w-3.5" />
                    Payoff
                  </TabsTrigger>
                  <TabsTrigger
                    value="greeks"
                    className="rounded-lg px-4 text-xs font-semibold data-[state=active]:bg-gradient-to-br data-[state=active]:from-background data-[state=active]:to-muted/60 data-[state=active]:shadow-sm"
                  >
                    <Sparkles className="mr-1.5 h-3.5 w-3.5" />
                    Greeks
                  </TabsTrigger>
                  <TabsTrigger
                    value="pnl"
                    className="rounded-lg px-4 text-xs font-semibold data-[state=active]:bg-gradient-to-br data-[state=active]:from-background data-[state=active]:to-muted/60 data-[state=active]:shadow-sm"
                  >
                    <TrendingUp className="mr-1.5 h-3.5 w-3.5" />
                    P&amp;L
                  </TabsTrigger>
                  <TabsTrigger
                    value="strategychart"
                    className="rounded-lg px-4 text-xs font-semibold data-[state=active]:bg-gradient-to-br data-[state=active]:from-background data-[state=active]:to-muted/60 data-[state=active]:shadow-sm"
                  >
                    <Activity className="mr-1.5 h-3.5 w-3.5" />
                    Strategy Chart
                  </TabsTrigger>
                  <TabsTrigger
                    value="multistrikeoi"
                    className="rounded-lg px-4 text-xs font-semibold data-[state=active]:bg-gradient-to-br data-[state=active]:from-background data-[state=active]:to-muted/60 data-[state=active]:shadow-sm"
                  >
                    <Layers className="mr-1.5 h-3.5 w-3.5" />
                    Multi Strike OI
                  </TabsTrigger>
                </TabsList>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => navigate('/strategybuilder/portfolio')}
                    className="h-10 gap-1.5 px-4 text-xs font-semibold"
                  >
                    <Briefcase className="h-3.5 w-3.5" />
                    Portfolio
                  </Button>
                </div>
              </div>
              <TabsContent value="payoff" className="pt-4">
                <div className="overflow-hidden rounded-xl border bg-card p-2 shadow-sm">
                  {spotPrice ? (
                    <PayoffChart
                      title={`${selectedUnderlying} — ${selectedExpiry || '—'}`}
                      spot={spotPrice}
                      atmIv={atmIv ?? 0}
                      tYears={simulatedYearsToNearExpiry}
                      payoff={payoff}
                    />
                  ) : (
                    <div className="flex h-[440px] items-center justify-center text-sm text-muted-foreground">
                      Load an option chain to see the payoff chart.
                    </div>
                  )}
                </div>
              </TabsContent>
              <TabsContent value="greeks" className="pt-4">
                <GreeksTab legs={legs} greeksByLeg={greeksByLeg} />
              </TabsContent>
              <TabsContent value="pnl" className="pt-4">
                <PnLTab
                  legs={legs}
                  fnoExchange={fnoExchange}
                  fallbackPrices={fallbackPricesByLeg}
                />
              </TabsContent>
              <TabsContent value="strategychart" className="pt-4">
                <StrategyChartTab
                  underlying={selectedUnderlying}
                  exchange={selectedExchange}
                  legs={legs}
                  optionExchange={fnoExchange}
                />
              </TabsContent>
              <TabsContent value="multistrikeoi" className="pt-4">
                <MultiStrikeOITab
                  underlying={selectedUnderlying}
                  exchange={selectedExchange}
                  legs={legs}
                  optionExchange={fnoExchange}
                />
              </TabsContent>
            </Tabs>

            <Simulators
              spotShiftPct={spotShiftPct}
              ivShiftPct={ivShiftPct}
              daysElapsed={daysElapsed}
              maxDays={maxSimulatorDays}
              onSpotShiftChange={setSpotShiftPct}
              onIvShiftChange={setIvShiftPct}
              onDaysElapsedChange={setDaysElapsed}
              onReset={resetSimulators}
            />
          </div>
        </div>
      )}

      <TemplateDialog
        open={templateDialogOpen}
        onOpenChange={setTemplateDialogOpen}
        template={activeTemplate}
        expiry={selectedExpiry}
        expiries={expiries}
        onExpiryChange={handleExpiryChange}
        chain={activeChain?.chain ?? null}
        atmStrike={atmStrike}
        strikeStep={strikeStep}
        onConfirm={handleTemplateConfirm}
      />

      <EditLegDialog
        open={editLegId !== null}
        onOpenChange={(open) => {
          if (!open) setEditLegId(null)
        }}
        leg={legs.find((l) => l.id === editLegId) ?? null}
        optionExpiries={expiries}
        futureExpiries={futureExpiries}
        chain={activeChain?.chain ?? null}
        chainExpiry={selectedExpiry}
        underlying={selectedUnderlying}
        optionExchange={optionExchangeFor(selectedExchange)}
        apiKey={apiKey ?? ''}
        atmStrike={atmStrike}
        strikeStep={strikeStep}
        onSave={saveEditedLeg}
        onDelete={removeLeg}
      />

      <SaveStrategyDialog
        open={saveDialogOpen}
        onOpenChange={setSaveDialogOpen}
        onSave={saveOrUpdateStrategy}
        defaultName={loadedEntry?.name ?? ''}
        defaultWatchlist={loadedEntry?.watchlist ?? 'mytrades'}
        isUpdate={loadedEntry !== null}
        busy={isSaving}
      />

      <AlertDialog
        open={pendingIdentityChange !== null}
        onOpenChange={(open) => {
          if (!open) setPendingIdentityChange(null)
        }}
      >
        <AlertDialogContent role="alertdialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Clear the current strategy?</AlertDialogTitle>
            <AlertDialogDescription>
              Changing the {pendingIdentityChange?.kind} clears every leg and resets the current
              scenario so contracts cannot be mixed across strategy identities.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingIdentityChange) applyIdentityChange(pendingIdentityChange, true)
              }}
            >
              Clear strategy
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <ExecuteBasketDialog
        open={executeDialogOpen}
        onOpenChange={setExecuteDialogOpen}
        legs={legs}
        exchange={optionExchangeFor(selectedExchange)}
        strategyName={computedStrategyName}
        tickSizeBySymbol={tickSizeBySymbol}
        apiKey={apiKey ?? ''}
      />
    </div>
  )
}

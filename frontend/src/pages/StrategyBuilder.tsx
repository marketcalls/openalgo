import { Briefcase, Save } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { apiClient } from '@/api/client'
import { optionChainApi } from '@/api/option-chain'
import {
  strategyPortfolioApi,
  type PortfolioEntry,
  type Watchlist,
} from '@/api/strategy-portfolio'
import { EditLegDialog } from '@/components/strategy-builder/EditLegDialog'
import { GreeksTab, type LegGreeks } from '@/components/strategy-builder/GreeksTab'
import { type LegDraft, ManualLegBuilder } from '@/components/strategy-builder/ManualLegBuilder'
import { PayoffChart } from '@/components/strategy-builder/PayoffChart'
import { PnLTab } from '@/components/strategy-builder/PnLTab'
import { PositionsPanel } from '@/components/strategy-builder/PositionsPanel'
import { SaveStrategyDialog } from '@/components/strategy-builder/SaveStrategyDialog'
import { Simulators } from '@/components/strategy-builder/Simulators'

import { SymbolHeader } from '@/components/strategy-builder/SymbolHeader'
import {
  type ResolvedTemplateLeg,
  TemplateDialog,
} from '@/components/strategy-builder/TemplateDialog'
import { TemplateGrid } from '@/components/strategy-builder/TemplateGrid'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import {
  buildFutureSymbol,
  buildOptionSymbol,
  computePayoff,
  daysToExpiry,
  daysToYears,
  nearestLegDays,
  netCredit,
  probabilityOfProfit,
  type StrategyLeg,
  totalPnlAt,
  totalPremium,
} from '@/lib/strategyMath'
import type { Direction, StrategyTemplate } from '@/lib/strategyTemplates'
import { useAuthStore } from '@/stores/authStore'
import type { OptionChainResponse } from '@/types/option-chain'
import { showToast } from '@/utils/toast'

// Convert DD-MMM-YYYY (API-returned expiry) to DDMMMYY (OpenAlgo symbol format).
function convertExpiryForSymbol(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

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

export default function StrategyBuilder() {
  const { apiKey } = useAuthStore()
  const { fnoExchanges, defaultFnoExchange, defaultUnderlyings } = useSupportedExchanges()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

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

  const [chainData, setChainData] = useState<OptionChainResponse | null>(null)
  const [atmIv, setAtmIv] = useState<number | null>(null)
  const [futuresPrice, setFuturesPrice] = useState<number | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [legs, setLegs] = useState<StrategyLeg[]>([])
  const [direction, setDirection] = useState<Direction>('BULLISH')

  const [activeTemplate, setActiveTemplate] = useState<StrategyTemplate | null>(null)
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false)

  const [spotShiftPct, setSpotShiftPct] = useState(0)
  const [ivShiftPct, setIvShiftPct] = useState(0)
  const [daysElapsed, setDaysElapsed] = useState(0)

  const [greeksByLeg, setGreeksByLeg] = useState<Record<string, LegGreeks>>({})
  const [livePricesByLeg, setLivePricesByLeg] = useState<Record<string, number>>({})

  const [editLegId, setEditLegId] = useState<string | null>(null)
  const [marginRequired, setMarginRequired] = useState<number | null>(null)
  const [isMarginLoading, setIsMarginLoading] = useState(false)
  // null = unknown yet; true/false once we've probed the broker.
  const [marginSupported, setMarginSupported] = useState<boolean | null>(null)

  // Portfolio persistence state
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [loadedEntry, setLoadedEntry] = useState<PortfolioEntry | null>(null)

  const requestIdRef = useRef(0)

  // Re-sync exchange when broker capabilities load async
  useEffect(() => {
    setSelectedExchange((prev) =>
      prev && fnoExchanges.some((ex) => ex.value === prev) ? prev : defaultFnoExchange
    )
  }, [defaultFnoExchange, fnoExchanges])

  // Fetch underlyings + expiries on exchange / underlying change
  useEffect(() => {
    const defaults = defaultUnderlyings[selectedExchange] || []
    setUnderlyings(defaults)
    setSelectedUnderlying((prev) => (defaults.includes(prev) ? prev : defaults[0] || ''))
  }, [selectedExchange, defaultUnderlyings])

  // Load expiries (options + futures — different calendars on MCX/CDS especially).
  // Expiries are normalised to the OpenAlgo DDMMMYY format at the source so that
  // every downstream component (header, dialogs, symbol builders) sees a single
  // consistent string — otherwise the Edit dialog can't match leg.expiry
  // ("21APR26") against the raw API value ("21-APR-2026") and the field blanks.
  useEffect(() => {
    if (!apiKey || !selectedUnderlying) return
    let cancelled = false
    ;(async () => {
      try {
        const optionExchange = optionExchangeFor(selectedExchange)
        const [optsRes, futsRes] = await Promise.all([
          optionChainApi.getExpiries(apiKey, selectedUnderlying, optionExchange, 'options'),
          optionChainApi
            .getExpiries(apiKey, selectedUnderlying, optionExchange, 'futures')
            .catch(() => ({ status: 'error' as const, data: [] as string[] })),
        ])
        if (cancelled) return
        const normaliseList = (list: string[]) =>
          // Preserve order but drop empties and de-dupe after normalisation.
          Array.from(new Set(list.filter(Boolean).map(convertExpiryForSymbol)))
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
      } catch (err) {
        if (!cancelled) {
          showToast.error('Failed to fetch expiries')
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiKey, selectedUnderlying, selectedExchange])

  // Load option chain
  const loadOptionChain = useCallback(async () => {
    if (!apiKey || !selectedUnderlying || !selectedExpiry) return
    const reqId = ++requestIdRef.current
    setIsRefreshing(true)
    try {
      const exchange = underlyingExchangeFor(selectedExchange, selectedUnderlying)
      const expiryCode = convertExpiryForSymbol(selectedExpiry)
      const data = await optionChainApi.getOptionChain(
        apiKey,
        selectedUnderlying,
        exchange,
        expiryCode,
        20
      )
      if (reqId !== requestIdRef.current) return
      if (data.status === 'success') {
        setChainData(data)
        // ATM IV: mid of CE/PE IV at ATM strike — we'll use the smile service later;
        // for now compute via greeks of ATM CE once legs are known.
      } else {
        showToast.error(data.message || 'Failed to load option chain')
      }
    } catch (err) {
      showToast.error('Failed to load option chain')
    } finally {
      if (reqId === requestIdRef.current) setIsRefreshing(false)
    }
  }, [apiKey, selectedExchange, selectedUnderlying, selectedExpiry])

  useEffect(() => {
    loadOptionChain()
  }, [loadOptionChain])

  // Seed ATM IV directly from the ATM CE as soon as the chain loads.
  // (The leg-Greeks fetch is gated on having at least one leg, so without this
  // the ATM IV badge would stay blank until the user adds a position.)
  useEffect(() => {
    if (!apiKey || !chainData || !chainData.atm_strike) return
    const atmRow = chainData.chain.find((s) => s.strike === chainData.atm_strike)
    const atmSymbol = atmRow?.ce?.symbol
    if (!atmSymbol) return
    let cancelled = false
    ;(async () => {
      try {
        const exchange = optionExchangeFor(selectedExchange)
        const underlyingExchange = underlyingExchangeFor(selectedExchange, selectedUnderlying)
        const res = await apiClient.post<{
          status: string
          implied_volatility?: number
        }>('/optiongreeks', {
          apikey: apiKey,
          symbol: atmSymbol,
          exchange,
          underlying_symbol: selectedUnderlying,
          underlying_exchange: underlyingExchange,
        })
        if (cancelled) return
        if (
          res.data.status === 'success' &&
          typeof res.data.implied_volatility === 'number' &&
          res.data.implied_volatility > 0
        ) {
          setAtmIv(res.data.implied_volatility)
        }
      } catch {
        /* non-fatal */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiKey, chainData, selectedExchange, selectedUnderlying])

  // Load synthetic future for the selected expiry
  useEffect(() => {
    if (!apiKey || !selectedUnderlying || !selectedExpiry) return
    let cancelled = false
    ;(async () => {
      try {
        const exchange = underlyingExchangeFor(selectedExchange, selectedUnderlying)
        const expiryCode = convertExpiryForSymbol(selectedExpiry)
        const res = await apiClient.post<{
          status: string
          synthetic_future_price?: number
        }>('/syntheticfuture', {
          apikey: apiKey,
          underlying: selectedUnderlying,
          exchange,
          expiry_date: expiryCode,
        })
        if (cancelled) return
        if (res.data.status === 'success' && res.data.synthetic_future_price) {
          setFuturesPrice(res.data.synthetic_future_price)
        } else {
          setFuturesPrice(null)
        }
      } catch {
        if (!cancelled) setFuturesPrice(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiKey, selectedExchange, selectedUnderlying, selectedExpiry])

  // Derived: ATM strike, lot size, spot
  const spotPrice = chainData?.underlying_ltp ?? null
  const atmStrike = chainData?.atm_strike ?? null
  const lotSize = useMemo(() => {
    if (!chainData?.chain) return null
    const atmRow = chainData.chain.find((s) => s.strike === chainData.atm_strike)
    return atmRow?.ce?.lotsize ?? atmRow?.pe?.lotsize ?? null
  }, [chainData])

  // Common strike step — try to detect from chain spacing
  const strikeStep = useMemo(() => {
    if (!chainData?.chain || chainData.chain.length < 2) return 50
    const sorted = [...chainData.chain].map((s) => s.strike).sort((a, b) => a - b)
    let minDiff = Infinity
    for (let i = 1; i < sorted.length; i++) {
      const d = sorted[i] - sorted[i - 1]
      if (d > 0 && d < minDiff) minDiff = d
    }
    return isFinite(minDiff) ? minDiff : 50
  }, [chainData])

  // DTE of the header-selected expiry (for the metadata badge only).
  const rawDays = useMemo(() => {
    if (!selectedExpiry) return null
    const expiryCode = convertExpiryForSymbol(selectedExpiry)
    return daysToExpiry(expiryCode)
  }, [selectedExpiry])

  // For the payoff curve: "At Expiry" uses the NEAREST leg's days-to-expiry
  // so calendar / diagonal spreads render correctly (the far leg retains
  // remaining time value). Falls back to the header expiry when no legs yet.
  const nearestDays = useMemo(() => {
    if (legs.length === 0) return rawDays ?? 0
    return nearestLegDays(legs)
  }, [legs, rawDays])

  // Simulator caps "days forward" to the nearest expiry so the T+0 slider
  // can't go past the first leg's expiration.
  const maxSimulatorDays = Math.max(0, Math.floor(nearestDays))
  const clampedDaysElapsed = Math.min(daysElapsed, maxSimulatorDays)

  // Remaining "simulated" years to the near expiry — for σ bands / PoP.
  const simulatedYearsToNearExpiry = daysToYears(
    Math.max(nearestDays - clampedDaysElapsed, 0)
  )

  // Shifted spot for the payoff calculations
  const simulatedSpot = spotPrice !== null ? spotPrice * (1 + spotShiftPct / 100) : 0

  // Batch load Greeks for all legs (also used to fill ATM IV for the header)
  useEffect(() => {
    if (!apiKey || legs.length === 0) {
      setGreeksByLeg({})
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const exchange = optionExchangeFor(selectedExchange)
        const underlyingExchange = underlyingExchangeFor(selectedExchange, selectedUnderlying)
        const symbols = legs
          .filter((l) => l.segment === 'OPTION' && l.symbol)
          .map((l) => ({
            symbol: l.symbol,
            exchange,
            underlying_symbol: selectedUnderlying,
            underlying_exchange: underlyingExchange,
          }))
        if (symbols.length === 0) return
        const res = await apiClient.post<{
          status: string
          data?: Array<{
            symbol: string
            implied_volatility?: number
            greeks?: { delta?: number; gamma?: number; theta?: number; vega?: number }
          }>
        }>('/multioptiongreeks', {
          apikey: apiKey,
          symbols,
        })
        if (cancelled) return
        if (res.data.status === 'success' && res.data.data) {
          const map: Record<string, LegGreeks> = {}
          for (const leg of legs) {
            const hit = res.data.data.find((r) => r.symbol === leg.symbol)
            map[leg.id] = {
              legId: leg.id,
              iv: hit?.implied_volatility ?? null,
              delta: hit?.greeks?.delta ?? null,
              gamma: hit?.greeks?.gamma ?? null,
              theta: hit?.greeks?.theta ?? null,
              vega: hit?.greeks?.vega ?? null,
            }
          }
          setGreeksByLeg(map)

          // Fill ATM IV for header — use the leg at ATM if we find one, else avg of all IVs
          const atmLegIv = legs
            .map((l) => {
              const grk = map[l.id]
              if (grk?.iv !== null && grk?.iv !== undefined && l.strike === atmStrike) {
                return grk.iv
              }
              return null
            })
            .find((v) => v !== null)

          if (atmLegIv !== null && atmLegIv !== undefined) {
            setAtmIv(atmLegIv)
          } else {
            const ivs = Object.values(map)
              .map((g) => g.iv)
              .filter((v): v is number => v !== null && v !== undefined)
            if (ivs.length > 0) {
              setAtmIv(ivs.reduce((a, b) => a + b, 0) / ivs.length)
            }
          }

          // Backfill IV into legs for simulator pricing if missing
          setLegs((prev) =>
            prev.map((l) => {
              if (l.iv > 0) return l
              const iv = map[l.id]?.iv
              return iv ? { ...l, iv } : l
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
  }, [apiKey, legs.length, selectedExchange, selectedUnderlying, atmStrike])

  // Margin fetch — whenever legs change, call the broker margin service.
  // Debounced so rapid edits don't hammer the endpoint.
  useEffect(() => {
    if (!apiKey) return
    const openLegs = legs.filter(
      (l) => l.active && !(l.exitPrice !== undefined && l.exitPrice > 0)
    )
    if (openLegs.length === 0) {
      setMarginRequired(null)
      return
    }
    // If we've already determined the broker doesn't support margin,
    // don't keep probing — just skip.
    if (marginSupported === false) return

    const handle = setTimeout(async () => {
      setIsMarginLoading(true)
      try {
        const exchange = optionExchangeFor(selectedExchange)
        // NOTE: MarginPositionSchema declares `quantity` and `price` as
        // Str fields — sending them as numbers fails Marshmallow validation
        // with a 400 (no descriptive message), which earlier silently
        // suppressed the Margin row. Keep these as strings.
        const positions = openLegs.map((l) => ({
          exchange,
          symbol: l.symbol,
          action: l.side,
          quantity: String(l.lots * l.lotSize),
          product: 'NRML',
          pricetype: l.price > 0 ? 'LIMIT' : 'MARKET',
          price: l.price > 0 ? String(l.price) : '0',
        }))
        const res = await apiClient.post<{
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
        // Response key varies slightly across brokers — accept any of the
        // three field names the service has been observed to return.
        const total =
          res.data?.data?.total_margin_required ??
          res.data?.data?.total_margin ??
          res.data?.data?.margin_required ??
          null
        if (res.status === 200 && res.data.status === 'success' && typeof total === 'number') {
          setMarginRequired(total)
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
        setMarginRequired(null)
      } finally {
        setIsMarginLoading(false)
      }
    }, 400)
    return () => clearTimeout(handle)
  }, [apiKey, legs, selectedExchange, marginSupported])

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
        const res = await apiClient.post<{
          status: string
          results?: Array<{ symbol: string; exchange: string; data?: { ltp?: number } }>
        }>('/multiquotes', {
          apikey: apiKey,
          symbols: needs.map((l) => ({ symbol: l.symbol, exchange })),
        })
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

  // Refresh live prices from chain whenever chain updates
  useEffect(() => {
    if (!chainData) return
    const byId: Record<string, number> = {}
    for (const leg of legs) {
      if (leg.segment !== 'OPTION' || leg.strike === undefined || !leg.optionType) continue
      const row = chainData.chain.find((s) => s.strike === leg.strike)
      const side = leg.optionType === 'CE' ? row?.ce : row?.pe
      if (side?.ltp !== undefined) byId[leg.id] = side.ltp
    }
    setLivePricesByLeg(byId)
  }, [chainData, legs])

  // Add legs from a template
  const handleTemplatePick = useCallback(
    (tpl: StrategyTemplate) => {
      if (!chainData || atmStrike === null) {
        showToast.error('Option chain not loaded yet')
        return
      }
      setActiveTemplate(tpl)
      setTemplateDialogOpen(true)
    },
    [chainData, atmStrike]
  )

  const handleTemplateConfirm = useCallback(
    (resolved: ResolvedTemplateLeg[], totalLots: number) => {
      if (!lotSize) {
        showToast.error('Lot size not detected — load the chain first')
        return
      }
      const newLegs: StrategyLeg[] = resolved.map((r) => {
        // Each leg keeps its own expiry — calendars / diagonals span two.
        const legExpiry = convertExpiryForSymbol(r.resolvedExpiry)
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
          lotSize,
          expiry: legExpiry,
          strike: r.resolvedStrike,
          optionType: r.optionType,
          price: r.price,
          iv: 0,
          active: true,
          symbol:
            r.symbol ??
            buildOptionSymbol(selectedUnderlying, legExpiry, r.resolvedStrike, r.optionType),
        }
      })
      setLegs((prev) => [...prev, ...newLegs])
      setTemplateDialogOpen(false)
      setActiveTemplate(null)
    },
    [lotSize, selectedUnderlying]
  )

  // Manual leg add
  const handleAddManualLeg = useCallback(
    (draft: LegDraft) => {
      if (!lotSize && draft.segment === 'OPTION') {
        showToast.error('Lot size not detected')
        return
      }
      const expiryCode = convertExpiryForSymbol(draft.expiry)

      // Prefer the broker-provided symbol from the live chain whenever
      // possible — some brokers (notably crypto exchanges like Delta) don't
      // follow the standard BASE[DDMMMYY][STRIKE][CE|PE] concatenation, so
      // constructing it locally would produce an invalid symbol.
      let symbol: string
      if (draft.segment === 'OPTION' && draft.strike !== undefined && draft.optionType) {
        const row = chainData?.chain.find((s) => s.strike === draft.strike)
        const side = draft.optionType === 'CE' ? row?.ce : row?.pe
        symbol =
          side?.symbol ??
          buildOptionSymbol(selectedUnderlying, expiryCode, draft.strike, draft.optionType)
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
      }
      setLegs((prev) => [...prev, newLeg])
    },
    [lotSize, selectedUnderlying, futuresPrice]
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
    // ±10% band around spot — tight enough to focus on the strategy's
    // action zone and wide enough to contain the ±2σ shading for typical
    // NIFTY/BANKNIFTY IV on weekly/monthly expiries. For very high-IV
    // names or long-dated expiries the σ bands may extend beyond — the
    // range can be widened later if needed.
    const range: [number, number] = [spotPrice * 0.9, spotPrice * 1.1]
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
      atmIv ?? 0
    )
  }, [legs, spotPrice, nearestDays, clampedDaysElapsed, ivShiftPct, atmIv])

  const pop = useMemo(() => {
    if (!spotPrice || atmIv === null || simulatedYearsToNearExpiry <= 0) return 0
    return probabilityOfProfit(payoff.samples, spotPrice, atmIv, simulatedYearsToNearExpiry)
  }, [payoff.samples, spotPrice, atmIv, simulatedYearsToNearExpiry])

  const totalPnlNow = useMemo(() => {
    if (!spotPrice) return 0
    return totalPnlAt(legs, simulatedSpot, clampedDaysElapsed, ivShiftPct, atmIv ?? 0)
  }, [legs, simulatedSpot, clampedDaysElapsed, ivShiftPct, spotPrice, atmIv])

  const credit = useMemo(() => netCredit(legs), [legs])
  const premium = useMemo(() => totalPremium(legs), [legs])

  // Handlers
  const toggleLeg = useCallback((id: string) => {
    setLegs((prev) => prev.map((l) => (l.id === id ? { ...l, active: !l.active } : l)))
  }, [])
  const toggleLegSide = useCallback((id: string) => {
    setLegs((prev) =>
      prev.map((l) =>
        l.id === id ? { ...l, side: l.side === 'BUY' ? 'SELL' : 'BUY' } : l
      )
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
      const normalisedExpiry = convertExpiryForSymbol(updated.expiry)

      // Prefer the live chain's symbol whenever available so crypto / non-
      // standard option symbols stay correct across edits.
      let rebuiltSymbol: string
      if (
        updated.segment === 'OPTION' &&
        updated.strike !== undefined &&
        updated.optionType
      ) {
        const row = chainData?.chain.find((s) => s.strike === updated.strike)
        const side = updated.optionType === 'CE' ? row?.ce : row?.pe
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
            ? { ...updated, expiry: normalisedExpiry, symbol: rebuiltSymbol }
            : l
        )
      )
      setEditLegId(null)
    },
    [selectedUnderlying, chainData]
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
        // Hydrate primary selectors. They'll trigger their own fetches.
        setSelectedExchange(entry.exchange)
        setSelectedUnderlying(entry.underlying)
        if (entry.expiry) setSelectedExpiry(entry.expiry)
        // Hydrate legs. Mark them loaded so we don't overwrite user IV later.
        const restored: StrategyLeg[] = entry.legs.map((l) => ({
          id: l.id ?? uid(),
          segment: l.segment,
          side: l.side,
          lots: l.lots,
          lotSize: l.lotSize,
          expiry: l.expiry,
          strike: l.strike,
          optionType: l.optionType,
          price: l.price,
          iv: l.iv ?? 0,
          active: l.active ?? true,
          symbol: l.symbol,
          exitPrice: l.exitPrice,
        }))
        setLegs(restored)
        setLoadedEntry(entry)
        showToast.success(`Loaded "${entry.name}"`)
        // Remove the ?load param so subsequent state changes don't re-fire.
        searchParams.delete('load')
        setSearchParams(searchParams, { replace: true })
      } catch (err) {
        showToast.error(err instanceof Error ? err.message : 'Failed to load strategy')
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
      } catch (err) {
        // Propagate to the dialog's inline error banner.
        throw err
      } finally {
        setIsSaving(false)
      }
    },
    [legs, selectedExchange, selectedUnderlying, selectedExpiry, loadedEntry]
  )

  return (
    <div className="space-y-4 py-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">
            Strategy Builder
            {loadedEntry && (
              <span className="ml-2 rounded bg-violet-500/10 px-2 py-0.5 align-middle text-xs font-medium text-violet-700 dark:text-violet-400">
                {loadedEntry.name}
              </span>
            )}
          </h1>
          <p className="text-sm text-muted-foreground">
            Design and analyse multi-leg options strategies with live Greeks and payoff.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate('/tools/strategy/portfolio')}
          >
            <Briefcase className="mr-1.5 h-3.5 w-3.5" />
            Portfolio
          </Button>
          <Button
            size="sm"
            onClick={() => setSaveDialogOpen(true)}
            disabled={legs.length === 0}
            title={legs.length === 0 ? 'Add at least one leg to save' : ''}
          >
            <Save className="mr-1.5 h-3.5 w-3.5" />
            {loadedEntry ? 'Update Strategy' : 'Save Strategy'}
          </Button>
        </div>
      </div>

      {/* Symbol header */}
      <SymbolHeader
        exchanges={fnoExchanges}
        selectedExchange={selectedExchange}
        onExchangeChange={setSelectedExchange}
        underlyings={underlyings}
        selectedUnderlying={selectedUnderlying}
        onUnderlyingChange={setSelectedUnderlying}
        underlyingOpen={underlyingOpen}
        onUnderlyingOpenChange={setUnderlyingOpen}
        expiries={expiries}
        selectedExpiry={selectedExpiry}
        onExpiryChange={setSelectedExpiry}
        spotPrice={spotPrice}
        futuresPrice={futuresPrice}
        lotSize={lotSize}
        atmIv={atmIv}
        daysToExpiry={rawDays}
        onRefresh={loadOptionChain}
        isRefreshing={isRefreshing}
      />

      {/* Template grid */}
      <div className="rounded-lg border bg-card p-4">
        <TemplateGrid
          direction={direction}
          onDirectionChange={setDirection}
          onPick={handleTemplatePick}
        />
      </div>

      {/* Manual leg adder */}
      <ManualLegBuilder
        expiries={expiries}
        futureExpiries={futureExpiries}
        chain={chainData?.chain ?? null}
        selectedExpiry={selectedExpiry}
        atmStrike={atmStrike}
        onAdd={handleAddManualLeg}
      />

      {/* Main working area — only revealed once the user has at least one leg.
          This avoids an empty-looking Strategy Positions panel and a flat
          payoff chart on first load, which looked like a broken state. */}
      {legs.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed bg-card/40 px-6 py-12 text-center">
          <p className="text-sm font-medium">No positions yet</p>
          <p className="max-w-md text-xs text-muted-foreground">
            Pick a strategy template above, or use the <b>Add Position</b> form to add your
            first leg. The payoff chart, Greeks and P&L tabs will appear here once you do.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
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
            />
          </div>

          {/* Right column: tabs + simulators */}
          <div className="min-w-0 space-y-4">
            <Tabs defaultValue="payoff" className="w-full">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="payoff">Payoff Chart</TabsTrigger>
                <TabsTrigger value="greeks">Greeks</TabsTrigger>
                <TabsTrigger value="pnl">P&L</TabsTrigger>
              </TabsList>
              <TabsContent value="payoff" className="pt-3">
                <div className="rounded-lg border bg-card p-2">
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
              <TabsContent value="greeks" className="pt-3">
                <GreeksTab legs={legs} greeksByLeg={greeksByLeg} />
              </TabsContent>
              <TabsContent value="pnl" className="pt-3">
                <PnLTab legs={legs} currentPrices={livePricesByLeg} />
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
        onExpiryChange={setSelectedExpiry}
        chain={chainData?.chain ?? null}
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
        chain={chainData?.chain ?? null}
        chainExpiry={selectedExpiry}
        underlying={selectedUnderlying}
        optionExchange={optionExchangeFor(selectedExchange)}
        apiKey={apiKey ?? ''}
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
    </div>
  )
}

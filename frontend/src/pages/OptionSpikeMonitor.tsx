import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    AlertTriangle,
    Check,
    CheckCircle2,
    ChevronsUpDown,
    Filter,
    Play,
    RefreshCw,
    Settings2,
    Square,
    Star,
    TrendingDown,
    TrendingUp,
    X,
} from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { optionChainApi } from '@/api/option-chain'
import { oiProfileApi } from '@/api/oi-profile'
import { useMarketData } from '@/hooks/useMarketData'
import { apiClient } from '@/api/client'
import type { OptionChainResponse } from '@/types/option-chain'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from '@/components/ui/command'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '@/components/ui/popover'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@/components/ui/tooltip'
import { showToast } from '@/utils/toast'
import { cn } from '@/lib/utils'

// Types
interface MonitorConfig {
    exchange: 'NFO' | 'BFO' | 'CDS' | 'MCX'
    underlying: string
    expiry: string
    minOtmStrike: number  // 0-50: start from this OTM strike index (0 = first OTM from ATM)
    maxOtmStrike: number  // 0-50: fetch and show up to this OTM strike index (always > minOtmStrike)
    // Shared thresholds (used when filtersLinked = true)
    distanceThreshold: number
    premiumThreshold: number
    ivThreshold: number
    spikeThresholdPercent: number
    // CE-specific thresholds (used when filtersLinked = false)
    distanceThresholdCE: number
    premiumThresholdCE: number
    ivThresholdCE: number
    spikeThresholdPercentCE: number
    // PE-specific thresholds (used when filtersLinked = false)
    distanceThresholdPE: number
    premiumThresholdPE: number
    ivThresholdPE: number
    spikeThresholdPercentPE: number
    spikeReference: 'OPEN' | 'PREV_CLOSE' | 'LAST_X_MIN'
    lastXMinutes: number
    skipIvWhenDistanceFail: boolean
    skipIvWhenPremiumFail: boolean
}

interface MonitoredStrike {
    symbol: string
    type: 'CE' | 'PE'
    strike: number
    baseSymbol: string
}

interface StrikeStatus {
    distance: number
    currentPremium: number
    currentIv: number
    spikePercent: number
    optionRefPrice: number
    optionRefTime: number | null  // epoch ms of the reference tick (null for OPEN/PREV_CLOSE which are day-level)
    lastTickTime: number
    isDistancePass: boolean
    isPremiumPass: boolean
    isIvPass: boolean
    isSpikePass: boolean
    isHistoryPass: boolean
    isAllPass: boolean
}

// A single price tick stored in the local ring buffer (for LAST_X_MIN spike mode)
interface Tick {
    t: number  // epoch ms
    p: number  // LTP at that moment
}

interface IvSummary {
    status: 'success' | 'partial' | 'error'
    total: number
    success: number
    failed: number
}

interface GreeksData {
    iv: number
    delta: number
    gamma: number
    theta: number
    vega: number
    daysToExpiry: number
}

interface BestStrikeConfig {
    romWeight: number      // 0-100
    thetaWeight: number    // 0-100
    safetyWeight: number   // 0-100
    lotSize: number
    applyDistanceFilter: boolean  // restrict best strike to strikes beyond config distance threshold
    applyPremiumFilter: boolean   // restrict best strike to strikes within config premium threshold
}

interface ScoredRow {
    symbol: string
    type: 'CE' | 'PE'
    strike: number
    currentPremium: number
    theta: number
    thetaIncome: number   // |theta| * lotSize per day (theoretical)
    maxCollectible: number // premium * lotSize (actual max income if expires worthless)
    daysToExpiry: number
    rom: number | null    // null if margin unavailable
    distancePct: number   // % OTM
    score: number         // 0-100 composite
}

const LS_KEY = 'openalgo_strike_monitor_session'

interface PersistedSession {
    expiresOn: string   // YYYY-MM-DD
    config: MonitorConfig
    filtersLinked: boolean
    monitoredStrikes: MonitoredStrike[]
    greeksData: Record<string, GreeksData>
    marginData: Record<string, number>
    marginFetchedAt: number | null  // epoch ms
    bestStrikeConfig: BestStrikeConfig
    isMonitoring: boolean
}

function getTodayDateStr(): string {
    return new Date().toISOString().slice(0, 10)
}

function loadSession(): PersistedSession | null {
    try {
        const raw = localStorage.getItem(LS_KEY)
        if (!raw) return null
        const parsed: PersistedSession = JSON.parse(raw)
        if (parsed.expiresOn !== getTodayDateStr()) {
            localStorage.removeItem(LS_KEY)
            return null
        }
        return parsed
    } catch {
        return null
    }
}

function clearSession() {
    localStorage.removeItem(LS_KEY)
}

const DEFAULT_CONFIG: MonitorConfig = {
    exchange: 'NFO',
    underlying: 'NIFTY',
    expiry: '',
    minOtmStrike: 0,
    maxOtmStrike: 10,
    distanceThreshold: 500,
    premiumThreshold: 5,
    ivThreshold: 30,
    spikeThresholdPercent: 10,
    distanceThresholdCE: 500,
    premiumThresholdCE: 5,
    ivThresholdCE: 30,
    spikeThresholdPercentCE: 10,
    distanceThresholdPE: 500,
    premiumThresholdPE: 5,
    ivThresholdPE: 30,
    spikeThresholdPercentPE: 10,
    spikeReference: 'OPEN',
    lastXMinutes: 5,
    skipIvWhenDistanceFail: false,
    skipIvWhenPremiumFail: false,
}

const FNO_EXCHANGES = [
    { value: 'NFO', label: 'NFO' },
    { value: 'BFO', label: 'BFO' },
]

const DEFAULT_BEST_STRIKE_CONFIG: BestStrikeConfig = {
    romWeight: 40,
    thetaWeight: 40,
    safetyWeight: 20,
    lotSize: 50,
    applyDistanceFilter: false,
    applyPremiumFilter: false,
}

export default function OptionSpikeMonitor() {
    const { apiKey } = useAuthStore()

    // Load persisted session once on mount
    const persistedSession = useMemo(() => loadSession(), [])

    // Configuration State — rehydrate from localStorage if available
    const [config, setConfig] = useState<MonitorConfig>(persistedSession?.config ?? DEFAULT_CONFIG)
    const [filtersLinked, setFiltersLinked] = useState(persistedSession?.filtersLinked ?? true)
    // Always start as not-monitoring on mount — restoring active monitoring state
    // would require restarting WebSocket, timers, etc. which is error-prone.
    // Config, greeksData and marginData are restored so user just clicks Start.
    const [isMonitoring, setIsMonitoring] = useState(false)
    const [isConfigOpen, setIsConfigOpen] = useState(true)

    // Best Strike Config
    const [bestStrikeConfig, setBestStrikeConfig] = useState<BestStrikeConfig>(
        persistedSession?.bestStrikeConfig ?? DEFAULT_BEST_STRIKE_CONFIG
    )

    // Greeks data (full — IV + Delta + Theta + Gamma + Vega)
    const [greeksData, setGreeksData] = useState<Record<string, GreeksData>>(
        persistedSession?.greeksData ?? {}
    )

    // Margin data
    const [marginData, setMarginData] = useState<Record<string, number>>(
        persistedSession?.marginData ?? {}
    )
    const [marginFetchedAt, setMarginFetchedAt] = useState<number | null>(
        persistedSession?.marginFetchedAt ?? null
    )
    const [isFetchingMargin, setIsFetchingMargin] = useState(false)
    const [isFetchingIv, setIsFetchingIv] = useState(false)

    // Helper: get the effective threshold for a given type and field
    const getThreshold = useCallback((type: 'CE' | 'PE', field: 'distance' | 'premium' | 'iv' | 'spike') => {
        if (filtersLinked) {
            if (field === 'distance') return config.distanceThreshold
            if (field === 'premium') return config.premiumThreshold
            if (field === 'iv') return config.ivThreshold
            return config.spikeThresholdPercent
        }
        if (type === 'CE') {
            if (field === 'distance') return config.distanceThresholdCE
            if (field === 'premium') return config.premiumThresholdCE
            if (field === 'iv') return config.ivThresholdCE
            return config.spikeThresholdPercentCE
        }
        if (field === 'distance') return config.distanceThresholdPE
        if (field === 'premium') return config.premiumThresholdPE
        if (field === 'iv') return config.ivThresholdPE
        return config.spikeThresholdPercentPE
    }, [filtersLinked, config])

    // Helper: update a linked field (syncs both CE and PE when linked)
    const setLinkedFilter = useCallback((field: 'distanceThreshold' | 'premiumThreshold' | 'ivThreshold' | 'spikeThresholdPercent', value: number) => {
        if (filtersLinked) {
            const ceField = `${field}CE` as keyof MonitorConfig
            const peField = `${field}PE` as keyof MonitorConfig
            setConfig(p => ({ ...p, [field]: value, [ceField]: value, [peField]: value }))
        } else {
            setConfig(p => ({ ...p, [field]: value }))
        }
    }, [filtersLinked])

    // Data State
    const [underlyings, setUnderlyings] = useState<string[]>([])
    const [expiries, setExpiries] = useState<string[]>([])
    const [selectedUnderlying, setSelectedUnderlying] = useState(persistedSession?.config?.underlying ?? '')
    const [selectedExpiry, setSelectedExpiry] = useState(persistedSession?.config?.expiry ?? '')
    const [optionChain, setOptionChain] = useState<OptionChainResponse | null>(null)
    // ivData is derived from greeksData for backward compat
    const ivData = useMemo(() => {
        const result: Record<string, number> = {}
        for (const [sym, g] of Object.entries(greeksData)) {
            result[sym] = g.iv
        }
        return result
    }, [greeksData])
    const [ivSummary, setIvSummary] = useState<IvSummary | null>(null)
    const [tickTimes, setTickTimes] = useState<Record<string, number>>({})
    // True while seedTickBuffers() is running (only relevant for LAST_X_MIN mode)
    const [isSeeding, setIsSeeding] = useState(false)
    const ivRetryTimeoutRef = useRef<number | null>(null)
    const ivRetrySymbolsRef = useRef<Record<string, { symbol: string; exchange: string }>>({})

    // Local tick ring-buffer: symbol → array of { t: epochMs, p: ltp }
    // Used by LAST_X_MIN spike mode to look up price from exactly X minutes ago
    // without any further API calls. Max window = 30 min to keep memory tiny.
    const TICK_BUFFER_MAX_MS = 30 * 60 * 1000  // 30 min
    const tickBuffers = useRef<Map<string, Tick[]>>(new Map())

    // Reference price buffer: symbol → { open, prevClose }
    // Populated at start via /history API so OPEN and PREV_CLOSE spike modes work
    // reliably across all brokers (some brokers return 0 for ohlc fields in multiquotes).
    const refPriceBuffer = useRef<Map<string, { open: number; prevClose: number }>>(new Map())

    // Binary-search helper: find the last tick at or before targetMs.
    // Returns undefined if the buffer is empty or all ticks are after targetMs.
    const findTickBefore = useCallback((buffer: Tick[], targetMs: number): Tick | undefined => {
        if (buffer.length === 0) return undefined
        let lo = 0, hi = buffer.length - 1, found: Tick | undefined = undefined
        while (lo <= hi) {
            const mid = (lo + hi) >> 1
            if (buffer[mid].t <= targetMs) {
                found = buffer[mid]
                lo = mid + 1
            } else {
                hi = mid - 1
            }
        }
        return found
    }, [])

    const getUnderlyingExchange = useCallback((exchange: MonitorConfig['exchange']) => {
        if (exchange === 'NFO') return 'NSE_INDEX'
        if (exchange === 'BFO') return 'BSE_INDEX'
        if (exchange === 'CDS') return 'CDS'
        if (exchange === 'MCX') return 'MCX'
        return 'NSE_INDEX'
    }, [])

    // Helper state
    const [underlyingOpen, setUnderlyingOpen] = useState(false)
    const [isLoadingChain, setIsLoadingChain] = useState(false)

    // Derived list of symbols to monitor (for WS subscription)
    const [monitoredStrikes, setMonitoredStrikes] = useState<MonitoredStrike[]>(
        persistedSession?.monitoredStrikes ?? []
    )
    const wsSymbols = useMemo(() => {
        const symbols: Array<{ symbol: string; exchange: string }> = monitoredStrikes.map(s => ({
            symbol: s.symbol,
            exchange: config.exchange
        }))
        // Add underlying for spot price (use index exchange, not derivatives exchange)
        if (config.underlying) {
            symbols.push({
                symbol: config.underlying,
                exchange: getUnderlyingExchange(config.exchange)
            })
        }
        return symbols
    }, [monitoredStrikes, config.exchange, config.underlying, getUnderlyingExchange])

    // WebSocket Hook
    const { data: wsData } = useMarketData({
        symbols: wsSymbols,
        mode: 'LTP',
        enabled: isMonitoring && wsSymbols.length > 0
    })

    // Format helpers
    const formatPrice = (num: number | undefined) => num?.toFixed(2) ?? '0.00'

    const resolveReferenceLabel = () => {
        if (config.spikeReference === 'OPEN') return "Today's Open"
        if (config.spikeReference === 'PREV_CLOSE') return "Yesterday's Close"
        return `Last ${config.lastXMinutes} Minutes`
    }

    // Load Underlyings
    useEffect(() => {
        const fetchUnderlyings = async () => {
            try {
                const response = await oiProfileApi.getUnderlyings(config.exchange)
                if (response.status === 'success') {
                    setUnderlyings(response.underlyings)
                    if (!response.underlyings.includes(selectedUnderlying)) {
                        let defaultUnderlying = ''
                        if (config.exchange === 'BFO') {
                            defaultUnderlying = response.underlyings.includes('SENSEX') ? 'SENSEX' : response.underlyings[0] || ''
                        } else if (config.exchange === 'NFO') {
                            defaultUnderlying = response.underlyings.includes('NIFTY') ? 'NIFTY' : response.underlyings[0] || ''
                        } else {
                            defaultUnderlying = response.underlyings[0] || ''
                        }
                        setSelectedUnderlying(defaultUnderlying)
                        setConfig(prev => ({ ...prev, underlying: defaultUnderlying }))
                    }
                }
            } catch (err) {
                console.error('Failed to fetch underlyings', err)
            }
        }
        fetchUnderlyings()
    }, [config.exchange, selectedUnderlying])

    // Load Expiries
    useEffect(() => {
        if (!config.underlying) return
        const fetchExpiries = async () => {
            try {
                const response = await oiProfileApi.getExpiries(config.exchange, config.underlying)
                if (response.status === 'success') {
                    setExpiries(response.expiries)
                    if (!response.expiries.includes(selectedExpiry)) {
                        const defaultExpiry = response.expiries[0] || ''
                        setSelectedExpiry(defaultExpiry)
                        setConfig(prev => ({ ...prev, expiry: defaultExpiry }))
                    }
                }
            } catch (err) {
                console.error('Failed to fetch expiries', err)
            }
        }
        fetchExpiries()
    }, [config.exchange, config.underlying, selectedExpiry])

    // Seed the tick buffer with historical 1-min candles so LAST_X_MIN works immediately
    // on start (before X minutes of live ticks have accumulated).
    // Also populates refPriceBuffer with today's open and yesterday's close for
    // OPEN / PREV_CLOSE spike modes — more reliable than multiquotes ohlc fields
    // which some brokers return as 0.
    // All symbols are fetched in parallel (Promise.all) — no serial loop.
    // After seeding, live WebSocket ticks keep the buffer current automatically.
    const seedTickBuffers = useCallback(async (symbols: { symbol: string; exchange: string }[]) => {
        if (!apiKey || symbols.length === 0) return

        setIsSeeding(true)
        const now = Date.now()
        const today = new Date(now).toISOString().slice(0, 10)
        // Fetch 2 days of 1m candles: today + yesterday (for prev_close)
        const twoDaysAgo = new Date(now - 2 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
        // Window for ring-buffer eviction (unchanged)
        const ringCutoff = now - TICK_BUFFER_MAX_MS

        await Promise.all(symbols.map(async (item) => {
            try {
                const response = await apiClient.post('/history', {
                    apikey: apiKey,
                    symbol: item.symbol,
                    exchange: item.exchange,
                    interval: '1m',
                    start_date: twoDaysAgo,
                    end_date: today,
                    source: 'api'
                })

                if (response.data.status === 'success' && response.data.data?.length) {
                    const parseTs = (rawTs: string): number => {
                        // History API returns timestamps as "YYYY-MM-DD HH:MM:SS" (space-separated).
                        // new Date() on that format returns Invalid Date in some browsers because
                        // the spec only requires ISO 8601 ("T"-separated). Replace space with "T"
                        // so parsing is reliable cross-browser.
                        return new Date(rawTs.includes('T') ? rawTs : rawTs.replace(' ', 'T')).getTime()
                    }

                    const allCandles = response.data.data.map((c: any) => {
                        const rawTs = String(c.timestamp ?? c.date ?? c.time ?? '')
                        return {
                            t: parseTs(rawTs),
                            p: Number(c.close ?? c.c ?? c.last_price ?? 0),
                            o: Number(c.open ?? c.o ?? 0),
                            dateStr: rawTs.slice(0, 10), // "YYYY-MM-DD"
                        }
                    }).filter((c: any) => c.p > 0 && !isNaN(c.t))

                    // ── Populate refPriceBuffer ───────────────────────────────
                    // Today's open = open of the very first 1m candle of today
                    const todayCandles = allCandles.filter((c: any) => c.dateStr === today)
                    const prevCandles = allCandles.filter((c: any) => c.dateStr < today)

                    const todayOpen = todayCandles.length > 0 ? todayCandles[0].o : 0
                    // prev_close = close of the last candle before today
                    const prevClose = prevCandles.length > 0 ? prevCandles[prevCandles.length - 1].p : 0

                    if (todayOpen > 0 || prevClose > 0) {
                        refPriceBuffer.current.set(item.symbol, { open: todayOpen, prevClose })
                    }

                    // ── Populate ring-buffer (LAST_X_MIN mode) ───────────────
                    const todayTicks: Tick[] = todayCandles.map((c: any) => ({ t: c.t, p: c.p }))

                    // Merge into buffer (seed entries behind live ticks)
                    const existing = tickBuffers.current.get(item.symbol) ?? []
                    const existingTimes = new Set(existing.map(e => e.t))
                    const merged = [
                        ...todayTicks.filter(c => !existingTimes.has(c.t)),
                        ...existing,
                    ].sort((a, b) => a.t - b.t)

                    // Evict entries older than max window
                    tickBuffers.current.set(item.symbol, merged.filter(e => e.t >= ringCutoff))
                }
            } catch (error) {
                console.error('[OptionSpikeMonitor] Failed to seed tick buffer', item.symbol, error)
            }
        }))

        setIsSeeding(false)
    }, [apiKey, TICK_BUFFER_MAX_MS])

    // Fetch Greeks Data (Multi-Option Greeks) — stores full Greeks not just IV
    const fetchIvData = useCallback(async (overrideSymbols?: { symbol: string; exchange: string }[], strikesList?: MonitoredStrike[]) => {
        const activeStrikes = strikesList ?? monitoredStrikes
        console.log('[OptionSpikeMonitor][fetchIvData] ENTRY - apiKey:', !!apiKey, 'activeStrikes:', activeStrikes.length, 'override:', overrideSymbols?.length)
        
        if (!apiKey) {
            console.log('[OptionSpikeMonitor][fetchIvData] SKIPPED - no API key')
            return
        }
        if (!overrideSymbols && activeStrikes.length === 0) {
            console.log('[OptionSpikeMonitor][fetchIvData] SKIPPED - no monitored strikes')
            return
        }

        setIsFetchingIv(true)
        try {
            const spotPrice = wsData.get(
                `${getUnderlyingExchange(config.exchange)}:${config.underlying}`
            )?.data?.ltp ?? optionChain?.underlying_ltp

            console.log('[OptionSpikeMonitor][fetchIvData] spotPrice:', spotPrice, 'wsData size:', wsData.size, 'optionChain?.underlying_ltp:', optionChain?.underlying_ltp)

            const symbols = overrideSymbols && overrideSymbols.length > 0
                // When called with explicit pre-mapped symbols, use directly
                ? overrideSymbols
                // When called with strikesList (initial fetch from handleStart),
                // skip distance/premium filtering — no WS prices yet
                : strikesList && strikesList.length > 0
                ? strikesList.map(s => ({ symbol: s.symbol, exchange: config.exchange }))
                : activeStrikes
                    .filter(s => {
                        if (spotPrice === undefined) {
                            const allow = !config.skipIvWhenDistanceFail
                            console.log('[OptionSpikeMonitor][fetchIvData] spotPrice undefined, skipIvWhenDistanceFail:', config.skipIvWhenDistanceFail, 'allow:', allow)
                            return allow
                        }

                        if (config.skipIvWhenDistanceFail) {
                            const distance = Math.abs(spotPrice - s.strike)
                            const distThreshold = getThreshold(s.type, 'distance')
                            if (distance <= distThreshold) {
                                console.log('[OptionSpikeMonitor][fetchIvData] FILTERED OUT (distance):', s.symbol, 'distance:', distance, 'threshold:', distThreshold)
                                return false
                            }
                        }

                        if (config.skipIvWhenPremiumFail) {
                            const wsKey = `${config.exchange}:${s.symbol}`
                            const ltp = wsData.get(wsKey)?.data?.ltp ?? 0
                            const premThreshold = getThreshold(s.type, 'premium')
                            if (ltp <= premThreshold) {
                                console.log('[OptionSpikeMonitor][fetchIvData] FILTERED OUT (premium):', s.symbol, 'ltp:', ltp, 'threshold:', premThreshold)
                                return false
                            }
                        }

                        return true
                    })
                    .map(s => ({
                        symbol: s.symbol,
                        exchange: config.exchange
                    }))

            console.log('[OptionSpikeMonitor][fetchIvData] Filtered symbols count:', symbols.length)

            if (symbols.length === 0) {
                console.log('[OptionSpikeMonitor][fetchIvData] SKIPPED - no symbols after filtering')
                return
            }

            const response = await apiClient.post('/multioptiongreeks', {
                apikey: apiKey,
                symbols: symbols
            })

            console.log('[OptionSpikeMonitor] fetchIvData request:', symbols)
            console.log('[OptionSpikeMonitor] fetchIvData response:', response.data)

            if ((response.data.status === 'success' || response.data.status === 'partial') && response.data.data) {
                const newGreeksData: Record<string, GreeksData> = {}
                const successSymbols = new Set<string>()
                response.data.data.forEach((item: any) => {
                    if (item.status === 'success' && item.implied_volatility !== undefined && item.symbol) {
                        const g = item.greeks ?? {}
                        newGreeksData[item.symbol] = {
                            iv: item.implied_volatility ?? 0,
                            delta: g.delta ?? 0,
                            gamma: g.gamma ?? 0,
                            theta: g.theta ?? 0,
                            vega: g.vega ?? 0,
                            daysToExpiry: item.days_to_expiry ?? 0,
                        }
                        successSymbols.add(item.symbol)
                    }
                })
                if (Object.keys(newGreeksData).length > 0) {
                    setGreeksData(prev => ({ ...prev, ...newGreeksData }))
                }
                setIvSummary({
                    status: response.data.status,
                    total: response.data.summary?.total ?? response.data.data.length,
                    success: response.data.summary?.success ?? Object.keys(newGreeksData).length,
                    failed: response.data.summary?.failed ?? response.data.data.length - Object.keys(newGreeksData).length
                })

                if (response.data.status === 'partial') {
                    const failedSymbols = symbols.filter(sym => !successSymbols.has(sym.symbol))
                    if (failedSymbols.length > 0) {
                        const retryMap: Record<string, { symbol: string; exchange: string }> = {}
                        failedSymbols.forEach(sym => {
                            retryMap[sym.symbol] = sym
                        })
                        ivRetrySymbolsRef.current = retryMap
                        if (ivRetryTimeoutRef.current) {
                            window.clearTimeout(ivRetryTimeoutRef.current)
                        }
                        ivRetryTimeoutRef.current = window.setTimeout(() => {
                            const retrySymbols = Object.values(ivRetrySymbolsRef.current)
                            if (retrySymbols.length > 0) {
                                fetchIvData(retrySymbols)
                            }
                        }, 5000)
                    } else {
                        setIsFetchingIv(false)
                    }
                } else {
                    setIsFetchingIv(false)
                }
            }
        } catch (err) {
            console.error('[OptionSpikeMonitor] Error fetching IV data', err)
            setIsFetchingIv(false)
        }
    }, [apiKey, monitoredStrikes, config.exchange, config.underlying, config.skipIvWhenDistanceFail, config.skipIvWhenPremiumFail, wsData, optionChain, getUnderlyingExchange, getThreshold])

    // Fetch Margin Data for all monitored strikes (once on start, or manual refresh)
    const fetchMarginData = useCallback(async (strikes: MonitoredStrike[]) => {
        if (!apiKey || strikes.length === 0) return
        setIsFetchingMargin(true)
        try {
            const newMargin: Record<string, number> = {}
            // Fetch margin per-strike individually so we get accurate per-symbol margin
            // The /margin API returns basket margin (total for all positions combined),
            // so we call it once per strike to get individual margin requirements
            await Promise.all(strikes.map(async (s) => {
                try {
                    const response = await apiClient.post('/margin', {
                        apikey: apiKey,
                        positions: [
                            {
                                symbol: s.symbol,
                                exchange: config.exchange,
                                action: 'SELL',
                                product: 'NRML',
                                pricetype: 'MARKET',
                                quantity: String(bestStrikeConfig.lotSize),
                                price: '1',
                            }
                        ],
                    })
                    if (response.data.status === 'success' && response.data.data) {
                        const data = response.data.data
                        // Response: { total_margin_required, span_margin, exposure_margin }
                        const margin = Number(
                            data.total_margin_required ?? data.total_margin ?? data.margin ?? 0
                        )
                        if (margin > 0) newMargin[s.symbol] = margin
                    }
                } catch {
                    // individual strike margin fetch failed — skip silently
                }
            }))

            if (Object.keys(newMargin).length > 0) {
                setMarginData(prev => ({ ...prev, ...newMargin }))
                setMarginFetchedAt(Date.now())
            }
        } catch (err) {
            console.error('[OptionSpikeMonitor] Error fetching margin data', err)
        } finally {
            setIsFetchingMargin(false)
        }
    }, [apiKey, config.exchange, bestStrikeConfig.lotSize])

    // Persist session to localStorage whenever key state changes
    const saveSession = useCallback((overrides: Partial<PersistedSession> = {}) => {
        try {
            const session: PersistedSession = {
                expiresOn: getTodayDateStr(),
                config,
                filtersLinked,
                monitoredStrikes,
                greeksData,
                marginData,
                marginFetchedAt,
                bestStrikeConfig,
                isMonitoring: false, // never restore as true — user must click Start again
                ...overrides,
            }
            localStorage.setItem(LS_KEY, JSON.stringify(session))
        } catch {
            // localStorage may be full or unavailable — silently ignore
        }
    }, [config, filtersLinked, monitoredStrikes, greeksData, marginData, marginFetchedAt, bestStrikeConfig, isMonitoring])

    // Auto-save session whenever key state changes (while monitoring)
    useEffect(() => {
        if (isMonitoring) {
            saveSession()
        }
    }, [isMonitoring, config, monitoredStrikes, greeksData, marginData, marginFetchedAt, bestStrikeConfig, saveSession])

    // Start Monitoring Logic
    const handleStart = async () => {
        if (!apiKey || !config.expiry) {
            showToast.error('Please configure expiry and ensure API key is set')
            return
        }

        setIsLoadingChain(true)
        setIsConfigOpen(false) // Auto collapse config

        try {
            // 1. Fetch Option Chain
            const expiryFormatted = config.expiry.split('-').length === 3
                ? `${config.expiry.split('-')[0]}${config.expiry.split('-')[1].toUpperCase()}${config.expiry.split('-')[2].slice(-2)}`
                : config.expiry

            const chainResponse = await optionChainApi.getOptionChain(
                apiKey,
                config.underlying,
                config.exchange,
                expiryFormatted,
                config.maxOtmStrike
            )

            if (chainResponse && chainResponse.chain) {
                setOptionChain(chainResponse)

                // Auto-populate lot size from chain data (use first available CE or PE lotsize)
                const firstLotSize = chainResponse.chain.find(s => s.ce?.lotsize || s.pe?.lotsize)
                const detectedLotSize = firstLotSize?.ce?.lotsize ?? firstLotSize?.pe?.lotsize ?? null
                if (detectedLotSize && detectedLotSize > 0) {
                    setBestStrikeConfig(prev => ({ ...prev, lotSize: detectedLotSize }))
                }

                // Filter strikes (OTM Only) based on ATM
                const atm = chainResponse.atm_strike
                const strikes: MonitoredStrike[] = []

                // Collect OTM strikes sorted by distance from ATM (closest first)
                // CE OTM: Strike > ATM, sorted ascending (closest to ATM first)
                const ceStrikes = chainResponse.chain
                    .filter(s => s.strike > atm && s.ce)
                    .sort((a, b) => a.strike - b.strike)

                // PE OTM: Strike < ATM, sorted descending (closest to ATM first)
                const peStrikes = chainResponse.chain
                    .filter(s => s.strike < atm && s.pe)
                    .sort((a, b) => b.strike - a.strike)

                // Apply min/max OTM index filter:
                // minOtmStrike=0 means start from index 0 (first OTM strike from ATM)
                // maxOtmStrike=10 means include up to but not including index 10
                const { minOtmStrike, maxOtmStrike } = config
                ceStrikes.slice(minOtmStrike, maxOtmStrike).forEach(s => {
                    strikes.push({
                        symbol: s.ce!.symbol,
                        type: 'CE',
                        strike: s.strike,
                        baseSymbol: config.underlying
                    })
                })
                peStrikes.slice(minOtmStrike, maxOtmStrike).forEach(s => {
                    strikes.push({
                        symbol: s.pe!.symbol,
                        type: 'PE',
                        strike: s.strike,
                        baseSymbol: config.underlying
                    })
                })

                setMonitoredStrikes(strikes)

                // Reset data on new start
                setGreeksData({})
                setMarginData({})
                setMarginFetchedAt(null)
                setTickTimes({})
                tickBuffers.current.clear()
                refPriceBuffer.current.clear()

                // Start Monitoring
                setIsMonitoring(true)

                // Always seed ALL option strike buffers (for refPriceBuffer used in OPEN/PREV_CLOSE)
                // + underlying spot buffer (for spot trend indicator)
                const underlyingSymbol = { symbol: config.underlying, exchange: getUnderlyingExchange(config.exchange) }
                const historySymbols = [
                    underlyingSymbol,
                    ...strikes.map(strike => ({ symbol: strike.symbol, exchange: config.exchange }))
                ]
                seedTickBuffers(historySymbols)

                // Initial Greeks Fetch (delayed to allow WS to connect)
                console.log('[OptionSpikeMonitor][handleStart] Scheduling initial Greeks fetch in 1s, strikes count:', strikes.length)
                setTimeout(() => {
                    console.log('[OptionSpikeMonitor][handleStart] FIRING initial Greeks fetch now with', strikes.length, 'strikes')
                    fetchIvData(undefined, strikes)
                }, 1000)

                // Fetch margin once (delayed to not overload on start)
                setTimeout(() => {
                    fetchMarginData(strikes)
                }, 2000)

            } else {
                showToast.error('No option chain data found')
            }

        } catch (err) {
            console.error('Error starting monitor', err)
            showToast.error('Failed to start monitoring')
        } finally {
            setIsLoadingChain(false)
        }
    }

    const handleStop = () => {
        setIsMonitoring(false)
        setIsConfigOpen(true)
        setIsSeeding(false)
        tickBuffers.current.clear()
        clearSession()
    }

    // Cleanup on stop
    useEffect(() => {
        if (!isMonitoring) {
            if (ivRetryTimeoutRef.current) {
                window.clearTimeout(ivRetryTimeoutRef.current)
            }
        }
    }, [isMonitoring])

    // Track WS Ticks — also push every tick into the local ring buffer for LAST_X_MIN spike mode
    useEffect(() => {
        if (!isMonitoring) return

        const now = Date.now()
        const cutoff = now - TICK_BUFFER_MAX_MS

        wsData.forEach((data, key) => {
            const symbol = key.split(':')[1]
            const ltp = data?.data?.ltp

            // Update tick times
            if (data.lastUpdate) {
                setTickTimes(prev => ({
                    ...prev,
                    [symbol]: data.lastUpdate ?? now
                }))
            }

            // Push to ring buffer (only for monitored option strikes, not the underlying index)
            if (ltp !== undefined && ltp > 0) {
                const buf = tickBuffers.current.get(symbol) ?? []
                // Avoid duplicate timestamps (same tick fired twice)
                const lastTick = buf[buf.length - 1]
                if (!lastTick || now - lastTick.t >= 500) {
                    buf.push({ t: now, p: ltp })
                    // Evict entries older than max window to keep memory bounded
                    const trimStart = buf.findIndex(e => e.t >= cutoff)
                    tickBuffers.current.set(symbol, trimStart > 0 ? buf.slice(trimStart) : buf)
                }
            }
        })
    }, [wsData, isMonitoring, TICK_BUFFER_MAX_MS])


    // Calculate Table Rows
    const {
        spikeReference,
        exchange,
        underlying,
    } = config

    const tableRows = useMemo(() => {
        if (!optionChain || !monitoredStrikes.length) return []

        const spotPrice = wsData.get(
            `${getUnderlyingExchange(exchange)}:${underlying}`
        )?.data?.ltp ?? optionChain.underlying_ltp

        const rows: (MonitoredStrike & StrikeStatus)[] = monitoredStrikes.map(s => {
            const wsKey = `${exchange}:${s.symbol}`
            const ltp = wsData.get(wsKey)?.data?.ltp ?? 0

            const distance = Math.abs(spotPrice - s.strike)
            const currentIv = ivData[s.symbol]

            const chainItem = optionChain.chain.find(i => i.strike === s.strike)
            const optionData = s.type === 'CE' ? chainItem?.ce : chainItem?.pe

            // refPriceBuffer is seeded from /history at start — more reliable than
            // multiquotes ohlc fields which some brokers return as 0.
            const refBuf = refPriceBuffer.current.get(s.symbol)

            let optionRefPrice = 0
            let optionRefTime: number | null = null
            if (spikeReference === 'OPEN') {
                // Prefer history-derived open; fall back to option chain quote
                optionRefPrice = (refBuf?.open ?? 0) > 0
                    ? refBuf!.open
                    : (optionData?.open ?? 0)
                // No specific tick time for day-level OPEN
            } else if (spikeReference === 'PREV_CLOSE') {
                // Prefer history-derived prev_close; fall back to option chain quote
                optionRefPrice = (refBuf?.prevClose ?? 0) > 0
                    ? refBuf!.prevClose
                    : (optionData?.prev_close ?? 0)
                // No specific tick time for day-level PREV_CLOSE
            } else {
                // LAST_X_MIN: look up price from X minutes ago in the local tick buffer.
                const buf = tickBuffers.current.get(s.symbol)
                if (buf) {
                    const targetMs = Date.now() - config.lastXMinutes * 60 * 1000
                    const tick = findTickBefore(buf, targetMs)
                    if (tick) {
                        optionRefPrice = tick.p
                        optionRefTime = tick.t  // capture actual timestamp of the reference tick
                    }
                }
            }

            // If Ref Price is still 0 (e.g. no trade today), cascade through fallbacks:
            // history open → history prev_close → chain prev_close
            if (optionRefPrice === 0) optionRefPrice = (refBuf?.open ?? 0) > 0 ? refBuf!.open : 0
            if (optionRefPrice === 0) optionRefPrice = (refBuf?.prevClose ?? 0) > 0 ? refBuf!.prevClose : 0
            if (optionRefPrice === 0) optionRefPrice = optionData?.prev_close ?? 0

            const spikePercent = optionRefPrice > 0 ? ((ltp - optionRefPrice) / optionRefPrice) * 100 : 0

            const lastTick = tickTimes[s.symbol] ?? 0
            const isLive = Date.now() - lastTick < 30000 // 30s heartbeat

            const isDistancePass = distance > getThreshold(s.type, 'distance')
            const isPremiumPass = ltp > getThreshold(s.type, 'premium')
            const isIvPass = currentIv !== undefined && currentIv > getThreshold(s.type, 'iv')
            const isSpikePass = spikePercent > getThreshold(s.type, 'spike')
            const isHistoryPass = isLive

            const isAllPass = isDistancePass && isPremiumPass && isIvPass && isSpikePass && isHistoryPass

            return {
                ...s,
                distance,
                currentPremium: ltp,
                currentIv: currentIv ?? 0,
                spikePercent,
                optionRefPrice,
                optionRefTime,
                lastTickTime: lastTick,
                isDistancePass,
                isPremiumPass,
                isIvPass,
                isSpikePass,
                isHistoryPass,
                isAllPass
            }
        })

        return rows
            .filter(row => {
                if (config.skipIvWhenDistanceFail && !row.isDistancePass) return false
                if (config.skipIvWhenPremiumFail && !row.isPremiumPass) return false
                return true
            })
            .sort((a, b) => {
                if (a.isAllPass !== b.isAllPass) {
                    return a.isAllPass ? -1 : 1
                }
                return a.strike - b.strike
            })
    // isSeeding is included so the useMemo re-runs once seedTickBuffers() finishes and
    // refPriceBuffer / tickBuffers (both refs) have been populated. Without this, the
    // memoised rows would never see the seeded data because ref mutations don't trigger renders.
    }, [monitoredStrikes, wsData, optionChain, tickTimes, ivData, spikeReference, exchange, underlying, getUnderlyingExchange, config.skipIvWhenPremiumFail, config.skipIvWhenDistanceFail, config.lastXMinutes, getThreshold, findTickBefore, isSeeding])

    // Spot trend: compare current spot LTP vs the price X minutes ago from the tick buffer.
    // Works for any spikeReference mode since we always seed the underlying buffer on start.
    const spotTrend = useMemo((): { direction: 'up' | 'down' | 'flat'; changePercent: number; refPrice: number } | null => {
        if (!isMonitoring || !config.underlying) return null

        const spotKey = `${getUnderlyingExchange(exchange)}:${underlying}`
        const currentSpot = wsData.get(spotKey)?.data?.ltp ?? optionChain?.underlying_ltp ?? 0
        if (!currentSpot) return null

        const buf = tickBuffers.current.get(config.underlying)
        if (!buf || buf.length === 0) return null

        const targetMs = Date.now() - config.lastXMinutes * 60 * 1000
        const foundTick = findTickBefore(buf, targetMs)
        const refPrice = foundTick?.p
        if (!refPrice) return null

        const changePercent = ((currentSpot - refPrice) / refPrice) * 100
        return {
            direction: changePercent > 0.05 ? 'up' : changePercent < -0.05 ? 'down' : 'flat',
            changePercent,
            refPrice,
        }
    }, [isMonitoring, config.underlying, config.lastXMinutes, wsData, optionChain, exchange, underlying, getUnderlyingExchange, tickTimes, findTickBefore])

    const hiddenCounts = useMemo(() => {
        if (!optionChain || !monitoredStrikes.length) return { distance: 0, premium: 0 }

        const spotPrice = wsData.get(
            `${getUnderlyingExchange(config.exchange)}:${config.underlying}`
        )?.data?.ltp ?? optionChain.underlying_ltp

        let distanceCount = 0
        let premiumCount = 0

        // Only count hidden strikes when respective switches are enabled
        if (config.skipIvWhenDistanceFail || config.skipIvWhenPremiumFail) {
            monitoredStrikes.forEach(s => {
                const distance = Math.abs(spotPrice - s.strike)
                const isDistanceFail = distance <= getThreshold(s.type, 'distance')

                const wsKey = `${config.exchange}:${s.symbol}`
                const ltp = wsData.get(wsKey)?.data?.ltp ?? 0
                const isPremiumFail = ltp <= getThreshold(s.type, 'premium')

                // Count distance failures (when switch is ON)
                if (config.skipIvWhenDistanceFail && isDistanceFail) {
                    distanceCount++
                }

                // Count premium failures (when switch is ON and distance passes)
                // Premium check only matters if distance passed (or distance switch is OFF)
                if (config.skipIvWhenPremiumFail && isPremiumFail) {
                    if (!config.skipIvWhenDistanceFail || !isDistanceFail) {
                        premiumCount++
                    }
                }
            })
        }

        return { distance: distanceCount, premium: premiumCount }
    }, [monitoredStrikes, wsData, optionChain, getThreshold, getUnderlyingExchange, config.exchange, config.underlying, config.skipIvWhenDistanceFail, config.skipIvWhenPremiumFail])

    // ─── Best Strike Scoring ───────────────────────────────────────────────────
    const scoredRows = useMemo((): ScoredRow[] => {
        if (!optionChain || !monitoredStrikes.length) return []

        const spotPrice = wsData.get(
            `${getUnderlyingExchange(config.exchange)}:${config.underlying}`
        )?.data?.ltp ?? optionChain.underlying_ltp

        if (!spotPrice) return []

        const { lotSize, romWeight, thetaWeight, safetyWeight } = bestStrikeConfig

        // Compute raw values for each strike
        const rawRows = monitoredStrikes.map(s => {
            const wsKey = `${config.exchange}:${s.symbol}`
            const ltp = wsData.get(wsKey)?.data?.ltp ?? 0
            const greeks = greeksData[s.symbol]
            // py_vollib black_theta() returns annualized theta (per year).
            // Divide by 365 to get daily theta per unit, then multiply by lot size.
            const theta = greeks?.theta ?? 0
            const daysToExpiry = greeks?.daysToExpiry ?? 0
            const thetaDaily = Math.abs(theta) / 365        // daily decay per unit
            const thetaIncome = thetaDaily * lotSize        // ₹ per day seller earns
            const maxCollectible = ltp * lotSize             // actual max if expires worthless
            const margin = marginData[s.symbol] ?? null
            const rom = margin && margin > 0 ? (ltp * lotSize / margin) * 100 : null
            const distancePct = spotPrice > 0 ? (Math.abs(spotPrice - s.strike) / spotPrice) * 100 : 0

            return {
                symbol: s.symbol,
                type: s.type,
                strike: s.strike,
                currentPremium: ltp,
                theta,
                thetaIncome,
                maxCollectible,
                daysToExpiry,
                rom,
                distancePct,
                score: 0,  // placeholder
            } as ScoredRow
        })

        if (rawRows.length === 0) return []

        // Apply optional filters (controlled by toggles inside Best Strike card)
        const filteredRows = rawRows.filter(r => {
            const isCE = r.type === 'CE'

            // Distance filter: CE strike must be >= spot + distance, PE strike <= spot - distance
            if (bestStrikeConfig.applyDistanceFilter && spotPrice > 0) {
                const distancePoints = filtersLinked
                    ? config.distanceThreshold
                    : isCE ? config.distanceThresholdCE : config.distanceThresholdPE
                if (isCE && r.strike < spotPrice + distancePoints) return false
                if (!isCE && r.strike > spotPrice - distancePoints) return false
            }

            // Premium filter: strike premium must be within configured premium threshold
            if (bestStrikeConfig.applyPremiumFilter) {
                const maxPremium = filtersLinked
                    ? config.premiumThreshold
                    : isCE ? config.premiumThresholdCE : config.premiumThresholdPE
                if (r.currentPremium > maxPremium) return false
            }

            return true
        })

        // If all strikes are filtered out, fall back to full rawRows so we always show something
        const rowsToScore = filteredRows.length > 0 ? filteredRows : rawRows

        // Min-max normalize a set of values → 0..100
        const normalize = (values: number[]): number[] => {
            const min = Math.min(...values)
            const max = Math.max(...values)
            if (max === min) return values.map(() => 50)
            return values.map(v => ((v - min) / (max - min)) * 100)
        }

        // Determine effective weights (ROM disabled if no margin data available)
        const hasMargin = rawRows.some(r => r.rom !== null)
        let effectiveRom = hasMargin ? romWeight : 0
        const effectiveTheta = thetaWeight
        const effectiveSafety = safetyWeight
        const totalWeight = effectiveRom + effectiveTheta + effectiveSafety
        // Normalize weights to sum to 1
        const wRom = totalWeight > 0 ? effectiveRom / totalWeight : 0
        const wTheta = totalWeight > 0 ? effectiveTheta / totalWeight : 0
        const wSafety = totalWeight > 0 ? effectiveSafety / totalWeight : 0

        // Normalize within filtered set (scoring is relative to eligible strikes only)
        const thetaValues = normalize(rowsToScore.map(r => r.thetaIncome))
        const safetyValues = normalize(rowsToScore.map(r => r.distancePct))
        const romValues = hasMargin
            ? normalize(rowsToScore.map(r => r.rom ?? 0))
            : rowsToScore.map(() => 0)

        // Score the filtered rows
        const filteredScored = rowsToScore.map((r, i) => ({
            ...r,
            score: Math.round(
                wRom * romValues[i] +
                wTheta * thetaValues[i] +
                wSafety * safetyValues[i]
            ),
        }))

        // Rows outside the filter get score 0 (still shown in table, not eligible for best strike)
        const filteredSymbols = new Set(rowsToScore.map(r => r.symbol))
        const allScored = rawRows.map(r =>
            filteredSymbols.has(r.symbol)
                ? filteredScored.find(s => s.symbol === r.symbol)!
                : { ...r, score: 0 }
        )

        return allScored.sort((a, b) => b.score - a.score)
    }, [monitoredStrikes, wsData, optionChain, greeksData, marginData, bestStrikeConfig, config, filtersLinked, getUnderlyingExchange])

    // Best CE and PE by score
    const bestCE = useMemo(() => scoredRows.find(r => r.type === 'CE') ?? null, [scoredRows])
    const bestPE = useMemo(() => scoredRows.find(r => r.type === 'PE') ?? null, [scoredRows])

    // Map symbol → score for quick table lookup
    const scoreBySymbol = useMemo(() => {
        const map: Record<string, number> = {}
        scoredRows.forEach(r => { map[r.symbol] = r.score })
        return map
    }, [scoredRows])

    // Margin age label
    const marginAgeLabel = useMemo(() => {
        if (!marginFetchedAt) return null
        const mins = Math.round((Date.now() - marginFetchedAt) / 60000)
        if (mins < 1) return 'just now'
        if (mins === 1) return '1 min ago'
        return `${mins} mins ago`
    }, [marginFetchedAt])

    const hasMarginData = Object.keys(marginData).length > 0

    return (
        <div className="py-6 space-y-6">
            {/* Configuration Panel */}
            <Card className="w-full">
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
                    <CardTitle className="flex items-center gap-2">
                        <Settings2 className="h-5 w-5" />
                        Configuration
                    </CardTitle>
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setIsConfigOpen(!isConfigOpen)}
                    >
                        {isConfigOpen ? <ChevronsUpDown className="h-4 w-4 rotate-180" /> : <ChevronsUpDown className="h-4 w-4" />}
                    </Button>
                </CardHeader>
                {isConfigOpen && (
                    <CardContent>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 items-start">
                            <div className="space-y-2">
                                <Label>Exchange & Underlying</Label>
                                <div className="flex gap-2">
                                    <Select value={config.exchange} onValueChange={(v) => setConfig(p => ({ ...p, exchange: v as MonitorConfig['exchange'] }))}>
                                        <SelectTrigger className="w-24">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {FNO_EXCHANGES.map(e => <SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>)}
                                        </SelectContent>
                                    </Select>
                                    <Popover open={underlyingOpen} onOpenChange={setUnderlyingOpen}>
                                        <PopoverTrigger asChild>
                                            <Button variant="outline" role="combobox" aria-expanded={underlyingOpen} className="flex-1 justify-between">
                                                {selectedUnderlying || "Select"}
                                                <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                                            </Button>
                                        </PopoverTrigger>
                                        <PopoverContent className="w-[200px] p-0">
                                            <Command>
                                                <CommandInput placeholder="Search..." />
                                                <CommandList>
                                                    <CommandEmpty>No underlying found.</CommandEmpty>
                                                    <CommandGroup>
                                                        {underlyings.map(u => (
                                                            <CommandItem key={u} value={u} onSelect={() => {
                                                                setSelectedUnderlying(u)
                                                                setConfig(p => ({ ...p, underlying: u }))
                                                                setUnderlyingOpen(false)
                                                            }}>
                                                                <Check className={cn("mr-2 h-4 w-4", selectedUnderlying === u ? "opacity-100" : "opacity-0")} />
                                                                {u}
                                                            </CommandItem>
                                                        ))}
                                                    </CommandGroup>
                                                </CommandList>
                                            </Command>
                                        </PopoverContent>
                                    </Popover>
                                </div>
                            </div>

                            <div className="space-y-2">
                                <Label>Expiry & OTM Range</Label>
                                <Select
                                    value={selectedExpiry}
                                    onValueChange={(v) => {
                                        setSelectedExpiry(v)
                                        setConfig(p => ({ ...p, expiry: v }))
                                    }}
                                >
                                    <SelectTrigger className="w-full">
                                        <SelectValue placeholder="Expiry" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {expiries.map(e => <SelectItem key={e} value={e}>{e}</SelectItem>)}
                                    </SelectContent>
                                </Select>
                                <div className="flex gap-2 items-end">
                                    <div className="flex-1 space-y-1">
                                        <span className="text-xs text-muted-foreground">Min OTM Strike</span>
                                        <Input
                                            type="number"
                                            min={0}
                                            max={49}
                                            value={config.minOtmStrike}
                                            onChange={e => {
                                                const val = Math.min(49, Math.max(0, Number(e.target.value)))
                                                setConfig(p => ({
                                                    ...p,
                                                    minOtmStrike: val,
                                                    // Ensure maxOtmStrike stays > minOtmStrike
                                                    maxOtmStrike: p.maxOtmStrike <= val ? val + 1 : p.maxOtmStrike
                                                }))
                                            }}
                                        />
                                    </div>
                                    <div className="flex-1 space-y-1">
                                        <span className="text-xs text-muted-foreground">Max OTM Strike</span>
                                        <Input
                                            type="number"
                                            min={1}
                                            max={50}
                                            value={config.maxOtmStrike}
                                            onChange={e => {
                                                const val = Math.min(50, Math.max(1, Number(e.target.value)))
                                                setConfig(p => ({
                                                    ...p,
                                                    maxOtmStrike: val,
                                                    // Ensure minOtmStrike stays < maxOtmStrike
                                                    minOtmStrike: p.minOtmStrike >= val ? val - 1 : p.minOtmStrike
                                                }))
                                            }}
                                        />
                                    </div>
                                </div>
                                <p className="text-xs text-muted-foreground">
                                    Showing strikes {config.minOtmStrike}–{config.maxOtmStrike} OTM ({config.maxOtmStrike - config.minOtmStrike} per side)
                                </p>
                            </div>

                            <div className="space-y-2 lg:col-span-2">
                                <div className="flex items-center justify-between">
                                    <Label>Filters ( &gt; )</Label>
                                    <label className="flex items-center gap-1.5 cursor-pointer select-none">
                                        <input
                                            type="checkbox"
                                            checked={filtersLinked}
                                            onChange={e => {
                                                const linked = e.target.checked
                                                setFiltersLinked(linked)
                                                // When re-linking, sync CE/PE values to the shared value
                                                if (linked) {
                                                    setConfig(p => ({
                                                        ...p,
                                                        distanceThresholdCE: p.distanceThreshold,
                                                        distanceThresholdPE: p.distanceThreshold,
                                                        premiumThresholdCE: p.premiumThreshold,
                                                        premiumThresholdPE: p.premiumThreshold,
                                                        ivThresholdCE: p.ivThreshold,
                                                        ivThresholdPE: p.ivThreshold,
                                                        spikeThresholdPercentCE: p.spikeThresholdPercent,
                                                        spikeThresholdPercentPE: p.spikeThresholdPercent,
                                                    }))
                                                }
                                            }}
                                            className="accent-primary h-3.5 w-3.5"
                                        />
                                        <span className="text-xs text-muted-foreground">Same for CE & PE</span>
                                    </label>
                                </div>

                                {filtersLinked ? (
                                    /* Linked mode — single values for both CE & PE */
                                    <div className="grid grid-cols-4 gap-2">
                                        <div className="space-y-1">
                                            <span className="text-xs text-muted-foreground">Dist (Pts)</span>
                                            <Input
                                                type="number"
                                                value={config.distanceThreshold}
                                                onChange={e => setLinkedFilter('distanceThreshold', Number(e.target.value))}
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <span className="text-xs text-muted-foreground">Prem (Min)</span>
                                            <Input
                                                type="number"
                                                value={config.premiumThreshold}
                                                onChange={e => setLinkedFilter('premiumThreshold', Number(e.target.value))}
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <span className="text-xs text-muted-foreground">IV (Max)</span>
                                            <Input
                                                type="number"
                                                value={config.ivThreshold}
                                                onChange={e => setLinkedFilter('ivThreshold', Number(e.target.value))}
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <span className="text-xs text-muted-foreground">Spike %</span>
                                            <Input
                                                type="number"
                                                value={config.spikeThresholdPercent}
                                                onChange={e => setLinkedFilter('spikeThresholdPercent', Number(e.target.value))}
                                            />
                                        </div>
                                    </div>
                                ) : (
                                    /* Unlinked mode — separate CE and PE values */
                                    <div className="space-y-2">
                                        {/* Column headers */}
                                        <div className="grid grid-cols-5 gap-2 items-center">
                                            <div className="text-xs font-medium text-muted-foreground" />
                                            <div className="text-xs font-medium text-center text-green-500">Dist (Pts)</div>
                                            <div className="text-xs font-medium text-center text-green-500">Prem (Min)</div>
                                            <div className="text-xs font-medium text-center text-green-500">IV (Max)</div>
                                            <div className="text-xs font-medium text-center text-green-500">Spike %</div>
                                        </div>
                                        {/* CE row */}
                                        <div className="grid grid-cols-5 gap-2 items-center">
                                            <div className="text-xs font-bold text-green-500 bg-green-500/10 rounded px-2 py-1 text-center">CE</div>
                                            <Input
                                                type="number"
                                                className="h-8 text-xs"
                                                value={config.distanceThresholdCE}
                                                onChange={e => setConfig(p => ({ ...p, distanceThresholdCE: Number(e.target.value) }))}
                                            />
                                            <Input
                                                type="number"
                                                className="h-8 text-xs"
                                                value={config.premiumThresholdCE}
                                                onChange={e => setConfig(p => ({ ...p, premiumThresholdCE: Number(e.target.value) }))}
                                            />
                                            <Input
                                                type="number"
                                                className="h-8 text-xs"
                                                value={config.ivThresholdCE}
                                                onChange={e => setConfig(p => ({ ...p, ivThresholdCE: Number(e.target.value) }))}
                                            />
                                            <Input
                                                type="number"
                                                className="h-8 text-xs"
                                                value={config.spikeThresholdPercentCE}
                                                onChange={e => setConfig(p => ({ ...p, spikeThresholdPercentCE: Number(e.target.value) }))}
                                            />
                                        </div>
                                        {/* PE row */}
                                        <div className="grid grid-cols-5 gap-2 items-center">
                                            <div className="text-xs font-bold text-red-500 bg-red-500/10 rounded px-2 py-1 text-center">PE</div>
                                            <Input
                                                type="number"
                                                className="h-8 text-xs"
                                                value={config.distanceThresholdPE}
                                                onChange={e => setConfig(p => ({ ...p, distanceThresholdPE: Number(e.target.value) }))}
                                            />
                                            <Input
                                                type="number"
                                                className="h-8 text-xs"
                                                value={config.premiumThresholdPE}
                                                onChange={e => setConfig(p => ({ ...p, premiumThresholdPE: Number(e.target.value) }))}
                                            />
                                            <Input
                                                type="number"
                                                className="h-8 text-xs"
                                                value={config.ivThresholdPE}
                                                onChange={e => setConfig(p => ({ ...p, ivThresholdPE: Number(e.target.value) }))}
                                            />
                                            <Input
                                                type="number"
                                                className="h-8 text-xs"
                                                value={config.spikeThresholdPercentPE}
                                                onChange={e => setConfig(p => ({ ...p, spikeThresholdPercentPE: Number(e.target.value) }))}
                                            />
                                        </div>
                                    </div>
                                )}
                            </div>

                            <div className="space-y-2 lg:col-span-4">
                                <Label>Spike Reference</Label>
                                <div className="flex gap-4 items-center">
                                    <Select value={config.spikeReference} onValueChange={(v) => setConfig(p => ({ ...p, spikeReference: v as MonitorConfig['spikeReference'] }))}>
                                        <SelectTrigger className="w-48">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="OPEN">Today's Open</SelectItem>
                                            <SelectItem value="PREV_CLOSE">Yesterday's Close</SelectItem>
                                            <SelectItem value="LAST_X_MIN">Last X Minutes</SelectItem>
                                        </SelectContent>
                                    </Select>

                                    {config.spikeReference === 'LAST_X_MIN' && (
                                        <div className="flex items-center gap-2">
                                            <Input
                                                type="number"
                                                className="w-20"
                                                value={config.lastXMinutes}
                                                onChange={e => setConfig(p => ({ ...p, lastXMinutes: Number(e.target.value) }))}
                                            />
                                            <span className="text-sm">mins ago</span>
                                        </div>
                                    )}
                                </div>
                            </div>

                        </div>

                        <div className="flex justify-end gap-2 mt-6">
                            <Button
                                variant={isMonitoring ? "destructive" : "default"}
                                onClick={isMonitoring ? handleStop : handleStart}
                                disabled={isLoadingChain}
                            >
                                {isLoadingChain ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> :
                                    isMonitoring ? <Square className="mr-2 h-4 w-4 fill-current" /> :
                                        <Play className="mr-2 h-4 w-4 fill-current" />}
                                {isMonitoring ? "Stop Monitor" : "Start Monitor"}
                            </Button>
                        </div>
                    </CardContent>
                )}
            </Card>

            {/* Main Content */}
            {isMonitoring && optionChain && (
                <div className="space-y-4">
                    {/* Control Panel */}
                    <Card>
                        <CardContent className="p-4">
                            <div className="flex flex-wrap items-center gap-4">
                                <Button
                                    variant="outline"
                                    onClick={() => fetchIvData()}
                                    disabled={monitoredStrikes.length === 0 || isFetchingIv}
                                >
                                    <RefreshCw className={cn("mr-2 h-4 w-4", isFetchingIv && "animate-spin")} />
                                    {isFetchingIv ? 'Fetching IV...' : 'Fetch IV'}
                                </Button>
                                
                                <div className="flex items-center gap-2 px-3 py-2 rounded-md border">
                                    <Switch
                                        checked={config.skipIvWhenDistanceFail}
                                        onCheckedChange={(checked) => setConfig(p => ({ ...p, skipIvWhenDistanceFail: checked }))}
                                    />
                                    <div>
                                        <p className="text-xs font-medium">Skip IV if distance fails</p>
                                        <p className="text-[10px] text-muted-foreground">Reduce IV calls for near strikes</p>
                                    </div>
                                </div>

                                <div className="flex items-center gap-2 px-3 py-2 rounded-md border">
                                    <Switch
                                        checked={config.skipIvWhenPremiumFail}
                                        onCheckedChange={(checked) => setConfig(p => ({ ...p, skipIvWhenPremiumFail: checked }))}
                                    />
                                    <div>
                                        <p className="text-xs font-medium">Skip IV if premium fails</p>
                                        <p className="text-[10px] text-muted-foreground">Skip IV for low premium strikes</p>
                                    </div>
                                </div>
                            </div>
                        </CardContent>
                    </Card>

                    {/* Status Cards */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <Card>
                            <CardContent className="p-4 flex items-center justify-between">
                                <div>
                                    <p className="text-sm font-medium text-muted-foreground">
                                        {spotTrend ? (
                                            <TooltipProvider>
                                                <Tooltip>
                                                    <TooltipTrigger asChild>
                                                        <span className="cursor-help inline-flex items-center gap-1">
                                                            Spot Price
                                                            <span className={cn(
                                                                "text-xs font-semibold",
                                                                spotTrend.direction === 'up' ? 'text-green-500' : spotTrend.direction === 'down' ? 'text-red-500' : 'text-muted-foreground'
                                                            )}>
                                                                {spotTrend.direction === 'up' ? '▲' : spotTrend.direction === 'down' ? '▼' : '—'}
                                                                {' '}{Math.abs(spotTrend.changePercent).toFixed(2)}%
                                                            </span>
                                                        </span>
                                                    </TooltipTrigger>
                                                    <TooltipContent side="bottom" className="text-xs space-y-1">
                                                        <p className="font-semibold">{config.underlying} — Last {config.lastXMinutes} min trend</p>
                                                        <p>
                                                            <span className="text-muted-foreground">Ref price ({config.lastXMinutes}m ago):</span>{' '}
                                                            <span className="font-mono font-medium">{spotTrend.refPrice.toFixed(2)}</span>
                                                        </p>
                                                        <p>
                                                            <span className="text-muted-foreground">Change:</span>{' '}
                                                            <span className={cn(
                                                                "font-mono font-semibold",
                                                                spotTrend.direction === 'up' ? 'text-green-500' : spotTrend.direction === 'down' ? 'text-red-500' : ''
                                                            )}>
                                                                {spotTrend.changePercent > 0 ? '+' : ''}{spotTrend.changePercent.toFixed(2)}%
                                                            </span>
                                                        </p>
                                                    </TooltipContent>
                                                </Tooltip>
                                            </TooltipProvider>
                                        ) : (
                                            'Spot Price'
                                        )}
                                    </p>
                                    <h2 className="text-2xl font-bold">
                                        {formatPrice(
                                            wsData.get(`${getUnderlyingExchange(config.exchange)}:${config.underlying}`)?.data?.ltp
                                            ?? optionChain.underlying_ltp
                                        )}
                                    </h2>
                                </div>
                                {spotTrend?.direction === 'down'
                                    ? <TrendingDown className="h-8 w-8 text-red-500 opacity-70" />
                                    : spotTrend?.direction === 'up'
                                    ? <TrendingUp className="h-8 w-8 text-green-500 opacity-70" />
                                    : <TrendingUp className="h-8 w-8 text-primary opacity-50" />
                                }
                            </CardContent>
                        </Card>
                        <Card>
                            <CardContent className="p-4 flex items-center justify-between">
                                <div>
                                    <p className="text-sm font-medium text-muted-foreground">
                                        Reference Basis
                                        {isSeeding && config.spikeReference === 'LAST_X_MIN' && (
                                            <span className="ml-2 inline-flex items-center gap-1 text-xs text-amber-500 font-medium">
                                                <span className="inline-block h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                                                Seeding buffer…
                                            </span>
                                        )}
                                    </p>
                                    <h2 className="text-xl font-bold">
                                        {resolveReferenceLabel()}
                                    </h2>
                                    <p className="text-xs text-muted-foreground">
                                        {config.spikeReference === 'LAST_X_MIN'
                                            ? 'Using option history'
                                            : "Using option's static data"}
                                    </p>
                                </div>
                                <Filter className="h-8 w-8 text-blue-500 opacity-50" />
                            </CardContent>
                        </Card>
                        <Card>
                            <CardContent className="p-4 flex items-center justify-between">
                                <div>
                                    <p className="text-sm font-medium text-muted-foreground">Monitored Strikes</p>
                                    <h2 className="text-2xl font-bold">{monitoredStrikes.length}</h2>
                                    <p className="text-xs text-green-500">
                                        {tableRows.filter(r => r.isAllPass).length} Passing
                                    </p>
                                    {hiddenCounts.distance > 0 && (
                                        <p className="text-xs text-amber-600">
                                            {hiddenCounts.distance} Hidden (distance)
                                        </p>
                                    )}
                                    {hiddenCounts.premium > 0 && (
                                        <p className="text-xs text-amber-600">
                                            {hiddenCounts.premium} Hidden (premium)
                                        </p>
                                    )}
                                </div>
                                <CheckCircle2 className="h-8 w-8 text-green-500 opacity-50" />
                            </CardContent>
                        </Card>
                    </div>

                    {/* Best Strike Recommendation Card */}
                    {scoredRows.length > 0 && (
                        <Card className="border-primary/20 bg-primary/5">
                            <CardHeader className="pb-3">
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                    <CardTitle className="flex items-center gap-2 text-base">
                                        <Star className="h-4 w-4 text-yellow-500 fill-yellow-500" />
                                        Best Strike Recommendation
                                        {!hasMarginData && (
                                            <span className="text-xs font-normal text-muted-foreground ml-1">(ROM disabled — margin not available)</span>
                                        )}
                                    </CardTitle>
                                    <div className="flex items-center gap-2">
                                        {marginAgeLabel && (
                                            <span className="text-xs text-muted-foreground">Margin: {marginAgeLabel}</span>
                                        )}
                                        <Button
                                            variant="outline"
                                            size="sm"
                                            className="h-7 text-xs"
                                            disabled={isFetchingMargin || monitoredStrikes.length === 0}
                                            onClick={() => fetchMarginData(monitoredStrikes)}
                                        >
                                            <RefreshCw className={cn("mr-1 h-3 w-3", isFetchingMargin && "animate-spin")} />
                                            {isFetchingMargin ? 'Fetching...' : 'Refresh Margin'}
                                        </Button>
                                        <Button
                                            variant="outline"
                                            size="sm"
                                            className="h-7 text-xs"
                                            disabled={isFetchingIv || monitoredStrikes.length === 0}
                                            onClick={() => fetchIvData()}
                                        >
                                            <RefreshCw className={cn("mr-1 h-3 w-3", isFetchingIv && "animate-spin")} />
                                            {isFetchingIv ? 'Fetching...' : 'Refresh Theta'}
                                        </Button>
                                    </div>
                                </div>

                                {/* Scoring Weight Controls */}
                                <div className="mt-3">
                                    <div className="flex items-center gap-1.5 mb-2">
                                        <span className="text-xs font-medium text-muted-foreground">Scoring Weights</span>
                                        <TooltipProvider>
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <span className="cursor-help text-muted-foreground hover:text-foreground transition-colors">
                                                        <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                            <circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>
                                                        </svg>
                                                    </span>
                                                </TooltipTrigger>
                                                <TooltipContent side="top" className="max-w-[300px] p-3 space-y-2">
                                                    <div className="font-bold">How Scoring Works</div>
                                                    <div className="space-y-1.5 text-[11px]">
                                                        <div>
                                                            <span className="font-semibold">ROM (Return on Margin)</span>
                                                            <div className="opacity-80">Higher weight = prefer strikes that generate more premium relative to the margin blocked. Best for capital-efficient selling. Requires margin data.</div>
                                                        </div>
                                                        <div>
                                                            <span className="font-semibold">Theta</span>
                                                            <div className="opacity-80">Higher weight = prefer strikes with higher daily time decay (₹/day). Best for maximising daily income from options selling.</div>
                                                        </div>
                                                        <div>
                                                            <span className="font-semibold">Safety</span>
                                                            <div className="opacity-80">Higher weight = prefer strikes farther OTM (% distance from spot). Best for conservative sellers who want more buffer before the strike is tested.</div>
                                                        </div>
                                                    </div>
                                                    <div className="opacity-60 text-[10px] border-t border-current/20 pt-1.5">
                                                        Weights are auto-normalised — they don't need to add up to 100. Each strike is ranked 0–100 on each axis and the weighted average becomes its final score.
                                                    </div>
                                                </TooltipContent>
                                            </Tooltip>
                                        </TooltipProvider>
                                    </div>
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 items-end">
                                    <div className="space-y-1">
                                        <div className="flex justify-between text-xs text-muted-foreground">
                                            <span>ROM Weight</span>
                                            <span className={cn("font-medium", !hasMarginData && "line-through opacity-40")}>{bestStrikeConfig.romWeight}%</span>
                                        </div>
                                        <input
                                            type="range" min={0} max={100} step={5}
                                            value={bestStrikeConfig.romWeight}
                                            disabled={!hasMarginData}
                                            onChange={e => setBestStrikeConfig(p => ({ ...p, romWeight: Number(e.target.value) }))}
                                            className="w-full accent-primary h-1.5 disabled:opacity-30"
                                        />
                                    </div>
                                    <div className="space-y-1">
                                        <div className="flex justify-between text-xs text-muted-foreground">
                                            <span>Theta Weight</span>
                                            <span className="font-medium">{bestStrikeConfig.thetaWeight}%</span>
                                        </div>
                                        <input
                                            type="range" min={0} max={100} step={5}
                                            value={bestStrikeConfig.thetaWeight}
                                            onChange={e => setBestStrikeConfig(p => ({ ...p, thetaWeight: Number(e.target.value) }))}
                                            className="w-full accent-primary h-1.5"
                                        />
                                    </div>
                                    <div className="space-y-1">
                                        <div className="flex justify-between text-xs text-muted-foreground">
                                            <span>Safety Weight</span>
                                            <span className="font-medium">{bestStrikeConfig.safetyWeight}%</span>
                                        </div>
                                        <input
                                            type="range" min={0} max={100} step={5}
                                            value={bestStrikeConfig.safetyWeight}
                                            onChange={e => setBestStrikeConfig(p => ({ ...p, safetyWeight: Number(e.target.value) }))}
                                            className="w-full accent-primary h-1.5"
                                        />
                                    </div>
                                    <div className="space-y-1">
                                        <label className="text-xs text-muted-foreground">Lot Size</label>
                                        <Input
                                            type="number" min={1}
                                            value={bestStrikeConfig.lotSize}
                                            onChange={e => setBestStrikeConfig(p => ({ ...p, lotSize: Math.max(1, Number(e.target.value)) }))}
                                            className="h-7 text-xs"
                                        />
                                    </div>
                                </div>

                                {/* Filter Toggles */}
                                <div className="flex flex-wrap gap-4 mt-3 pt-3 border-t border-border">
                                    <div className="flex items-center gap-2">
                                        <button
                                            type="button"
                                            role="switch"
                                            aria-checked={bestStrikeConfig.applyDistanceFilter}
                                            onClick={() => setBestStrikeConfig(p => ({ ...p, applyDistanceFilter: !p.applyDistanceFilter }))}
                                            className={cn(
                                                "relative inline-flex h-4 w-8 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
                                                bestStrikeConfig.applyDistanceFilter ? "bg-primary" : "bg-muted"
                                            )}
                                        >
                                            <span className={cn(
                                                "pointer-events-none inline-block h-3 w-3 rounded-full bg-white shadow-lg transition-transform",
                                                bestStrikeConfig.applyDistanceFilter ? "translate-x-4" : "translate-x-0"
                                            )} />
                                        </button>
                                        <span className="text-xs text-muted-foreground">Distance Filter</span>
                                        <TooltipProvider>
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <span className="cursor-help text-muted-foreground/60 hover:text-muted-foreground">
                                                        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                                                    </span>
                                                </TooltipTrigger>
                                                <TooltipContent side="top" className="max-w-[220px] text-xs p-2">
                                                    <p className="font-medium mb-1">Distance Filter</p>
                                                    <p className="opacity-80">When ON, only considers strikes that are safely beyond the configured distance threshold:</p>
                                                    <p className="mt-1 opacity-80">• CE: strike ≥ spot + distance</p>
                                                    <p className="opacity-80">• PE: strike ≤ spot - distance</p>
                                                    <p className="mt-1 opacity-60 text-[10px]">Uses the distance threshold from Configuration section.</p>
                                                </TooltipContent>
                                            </Tooltip>
                                        </TooltipProvider>
                                    </div>

                                    <div className="flex items-center gap-2">
                                        <button
                                            type="button"
                                            role="switch"
                                            aria-checked={bestStrikeConfig.applyPremiumFilter}
                                            onClick={() => setBestStrikeConfig(p => ({ ...p, applyPremiumFilter: !p.applyPremiumFilter }))}
                                            className={cn(
                                                "relative inline-flex h-4 w-8 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
                                                bestStrikeConfig.applyPremiumFilter ? "bg-primary" : "bg-muted"
                                            )}
                                        >
                                            <span className={cn(
                                                "pointer-events-none inline-block h-3 w-3 rounded-full bg-white shadow-lg transition-transform",
                                                bestStrikeConfig.applyPremiumFilter ? "translate-x-4" : "translate-x-0"
                                            )} />
                                        </button>
                                        <span className="text-xs text-muted-foreground">Premium Filter</span>
                                        <TooltipProvider>
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <span className="cursor-help text-muted-foreground/60 hover:text-muted-foreground">
                                                        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                                                    </span>
                                                </TooltipTrigger>
                                                <TooltipContent side="top" className="max-w-[220px] text-xs p-2">
                                                    <p className="font-medium mb-1">Premium Filter</p>
                                                    <p className="opacity-80">When ON, only considers strikes whose current premium is within the configured premium threshold.</p>
                                                    <p className="mt-1 opacity-60 text-[10px]">Uses the premium threshold from Configuration section.</p>
                                                </TooltipContent>
                                            </Tooltip>
                                        </TooltipProvider>
                                    </div>
                                </div>
                                </div>
                            </CardHeader>
                            <CardContent className="pt-0">
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                    {/* Best CE */}
                                    {bestCE && (
                                        <div className="rounded-lg border border-green-500/30 bg-green-500/5 p-3 space-y-2">
                                            <div className="flex items-center justify-between">
                                                <div className="flex items-center gap-2">
                                                    <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20 text-xs">CE</Badge>
                                                    <span className="font-bold text-sm">{bestCE.strike}</span>
                                                    <span className="text-xs text-muted-foreground font-mono">{bestCE.symbol}</span>
                                                </div>
                                                <div className={cn(
                                                    "text-lg font-black tabular-nums",
                                                    bestCE.score >= 70 ? "text-green-500" : bestCE.score >= 40 ? "text-yellow-500" : "text-red-500"
                                                )}>
                                                    {bestCE.score}<span className="text-xs font-normal text-muted-foreground">/100</span>
                                                </div>
                                            </div>
                                            <div className="grid grid-cols-3 gap-2 text-xs">
                                                <div className="text-center">
                                                    <div className="text-muted-foreground">Premium</div>
                                                    <div className="font-semibold">₹{bestCE.currentPremium.toFixed(2)}</div>
                                                </div>
                                                <div className="text-center">
                                                    <div className="text-muted-foreground">θ/day</div>
                                                    <div className="font-semibold text-blue-500">₹{bestCE.thetaIncome.toFixed(2)}</div>
                                                </div>
                                                <div className="text-center">
                                                    <div className="text-muted-foreground">{bestCE.rom !== null ? 'ROM' : '% OTM'}</div>
                                                    <div className="font-semibold text-purple-500">
                                                        {bestCE.rom !== null ? `${bestCE.rom.toFixed(1)}%` : `${bestCE.distancePct.toFixed(1)}%`}
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                    {/* Best PE */}
                                    {bestPE && (
                                        <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 space-y-2">
                                            <div className="flex items-center justify-between">
                                                <div className="flex items-center gap-2">
                                                    <Badge variant="outline" className="bg-red-500/10 text-red-500 border-red-500/20 text-xs">PE</Badge>
                                                    <span className="font-bold text-sm">{bestPE.strike}</span>
                                                    <span className="text-xs text-muted-foreground font-mono">{bestPE.symbol}</span>
                                                </div>
                                                <div className={cn(
                                                    "text-lg font-black tabular-nums",
                                                    bestPE.score >= 70 ? "text-green-500" : bestPE.score >= 40 ? "text-yellow-500" : "text-red-500"
                                                )}>
                                                    {bestPE.score}<span className="text-xs font-normal text-muted-foreground">/100</span>
                                                </div>
                                            </div>
                                            <div className="grid grid-cols-3 gap-2 text-xs">
                                                <div className="text-center">
                                                    <div className="text-muted-foreground">Premium</div>
                                                    <div className="font-semibold">₹{bestPE.currentPremium.toFixed(2)}</div>
                                                </div>
                                                <div className="text-center">
                                                    <div className="text-muted-foreground">θ/day</div>
                                                    <div className="font-semibold text-blue-500">₹{bestPE.thetaIncome.toFixed(2)}</div>
                                                </div>
                                                <div className="text-center">
                                                    <div className="text-muted-foreground">{bestPE.rom !== null ? 'ROM' : '% OTM'}</div>
                                                    <div className="font-semibold text-purple-500">
                                                        {bestPE.rom !== null ? `${bestPE.rom.toFixed(1)}%` : `${bestPE.distancePct.toFixed(1)}%`}
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </CardContent>
                        </Card>
                    )}

                    {/* Monitor Table */}
                    <Card>
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>SYMBOL</TableHead>
                                    <TableHead className="text-center">STRIKE</TableHead>
                                    <TableHead className="text-right">PREMIUM</TableHead>
                                    <TableHead className="text-center">DISTANCE</TableHead>
                                    <TableHead className="text-center">
                                        {filtersLinked
                                            ? <>PREM &gt; {config.premiumThreshold}</>
                                            : <><span className="text-green-500">CE:{config.premiumThresholdCE}</span> / <span className="text-red-500">PE:{config.premiumThresholdPE}</span></>
                                        }
                                    </TableHead>
                                    <TableHead className="text-center">
                                        <div className="flex items-center justify-center gap-2">
                                            {filtersLinked
                                                ? <span>IV &gt; {config.ivThreshold}</span>
                                                : <span><span className="text-green-500">CE:{config.ivThresholdCE}</span> / <span className="text-red-500">PE:{config.ivThresholdPE}</span></span>
                                            }
                                            {ivSummary && ivSummary.status === 'partial' && (
                                                <Badge
                                                    variant="outline"
                                                    className="text-[10px] uppercase text-amber-600 border-amber-500/40 bg-amber-500/10"
                                                >
                                                    partial {ivSummary.success}/{ivSummary.total}
                                                </Badge>
                                            )}
                                        </div>
                                    </TableHead>
                                    <TableHead className="text-center">HISTORY</TableHead>
                                    <TableHead className="text-center">
                                        {filtersLinked
                                            ? <>SPIKE &gt; {config.spikeThresholdPercent}%</>
                                            : <><span className="text-green-500">CE:{config.spikeThresholdPercentCE}%</span> / <span className="text-red-500">PE:{config.spikeThresholdPercentPE}%</span></>
                                        }
                                    </TableHead>
                                    <TableHead className="text-center">θ/DAY</TableHead>
                                    {hasMarginData && <TableHead className="text-center">ROM%</TableHead>}
                                    <TableHead className="text-center">SCORE</TableHead>
                                    <TableHead className="text-center">ALL PASS</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {tableRows.map((row) => {
                                    const scored = scoredRows.find(r => r.symbol === row.symbol)
                                    const score = scoreBySymbol[row.symbol] ?? null
                                    return (
                                    <TableRow key={row.symbol} className={cn(
                                        row.isAllPass ? 'bg-green-500/10' : '',
                                        scored?.symbol === bestCE?.symbol || scored?.symbol === bestPE?.symbol ? 'ring-1 ring-inset ring-yellow-500/40' : ''
                                    )}>
                                        <TableCell className="font-medium text-xs">
                                            <div className="flex items-center gap-1">
                                                {(scored?.symbol === bestCE?.symbol || scored?.symbol === bestPE?.symbol) && (
                                                    <Star className="h-3 w-3 text-yellow-500 fill-yellow-500 shrink-0" />
                                                )}
                                                <span className={row.type === 'CE' ? 'text-green-500' : 'text-red-400'}>
                                                    {row.symbol}
                                                </span>
                                            </div>
                                        </TableCell>
                                        <TableCell className="text-center font-bold">{row.strike}</TableCell>
                                        <TableCell className="text-right font-mono text-base font-semibold">
                                            {formatPrice(row.currentPremium)}
                                        </TableCell>
                                        <TableCell className="text-center">
                                            <div className={cn("text-xs font-medium", row.isDistancePass ? "text-green-500" : "text-red-500")}>
                                                {formatPrice(row.distance)}
                                            </div>
                                        </TableCell>
                                        <TableCell className="text-center">
                                            {row.isPremiumPass ? <Check className="h-4 w-4 mx-auto text-green-500" /> : <X className="h-4 w-4 mx-auto text-red-500" />}
                                        </TableCell>
                                        <TableCell className="text-center">
                                            <div className={cn("text-xs font-medium", row.isIvPass ? "text-green-500" : "text-red-500")}>
                                                {row.currentIv.toFixed(2)}%
                                            </div>
                                        </TableCell>
                                        <TableCell className="text-center">
                                            {row.isHistoryPass ?
                                                <CheckCircle2 className="h-4 w-4 mx-auto text-green-500 animate-pulse" /> :
                                                <AlertTriangle className="h-4 w-4 mx-auto text-red-500" />
                                            }
                                        </TableCell>
                                        <TableCell className="text-center">
                                            <div className={cn("font-bold text-xs", row.isSpikePass ? "text-green-500" : "text-red-500")}>
                                                <TooltipProvider delayDuration={100}>
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <span className="cursor-default">
                                                                {(isSeeding || row.currentPremium === 0 || row.optionRefPrice === 0)
                                                                    ? <span className="text-muted-foreground animate-pulse">…</span>
                                                                    : `${row.spikePercent.toFixed(1)}%`
                                                                }
                                                            </span>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="left" className="text-xs space-y-1 min-w-[160px]">
                                                            {(isSeeding || row.optionRefPrice === 0) ? (
                                                                <p className="text-muted-foreground">Loading reference price…</p>
                                                            ) : (
                                                                <>
                                                                    <p className="font-medium text-muted-foreground">
                                                                        {spikeReference === 'LAST_X_MIN'
                                                                            ? `Ref: ${config.lastXMinutes}min ago`
                                                                            : `Ref: ${resolveReferenceLabel()}`
                                                                        }
                                                                    </p>
                                                                    <p className="font-semibold text-sm">₹{row.optionRefPrice.toFixed(2)}</p>
                                                                    {row.optionRefTime !== null && (
                                                                        <p className="text-muted-foreground text-[10px]">
                                                                            @ {new Date(row.optionRefTime).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}
                                                                        </p>
                                                                    )}
                                                                    {row.currentPremium > 0 && (
                                                                        <p className="text-muted-foreground text-[10px]">
                                                                            Now: ₹{row.currentPremium.toFixed(2)}
                                                                        </p>
                                                                    )}
                                                                </>
                                                            )}
                                                        </TooltipContent>
                                                    </Tooltip>
                                                </TooltipProvider>
                                            </div>
                                        </TableCell>
                                        {/* θ/day */}
                                        <TableCell className="text-center">
                                            {scored ? (
                                                <TooltipProvider delayDuration={100}>
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <span className="text-xs font-medium text-blue-500 cursor-help underline decoration-dotted">
                                                                ₹{scored.thetaIncome.toFixed(2)}
                                                            </span>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="top" className="min-w-[240px] p-2">
                                                            <div className="font-bold mb-2">Daily Theta Decay</div>
                                                            <div className="flex justify-between gap-4">
                                                                <span className="opacity-70">Raw θ (annualised)</span>
                                                                <span>{scored.theta.toFixed(4)}</span>
                                                            </div>
                                                            <div className="flex justify-between gap-4">
                                                                <span className="opacity-70">÷ 365 (daily per unit)</span>
                                                                <span>{(Math.abs(scored.theta) / 365).toFixed(4)}</span>
                                                            </div>
                                                            <div className="flex justify-between gap-4">
                                                                <span className="opacity-70">× Lot size</span>
                                                                <span>× {bestStrikeConfig.lotSize}</span>
                                                            </div>
                                                            <div className="flex justify-between gap-4">
                                                                <span className="opacity-70">Days to expiry</span>
                                                                <span>{scored.daysToExpiry.toFixed(2)} days</span>
                                                            </div>
                                                            <div className="border-t border-current/20 pt-1 mt-1 flex justify-between gap-4">
                                                                <span className="opacity-70">θ/day (theoretical)</span>
                                                                <span className="font-bold">₹{scored.thetaIncome.toFixed(2)}</span>
                                                            </div>
                                                            <div className="flex justify-between gap-4">
                                                                <span className="opacity-70">Max collectible</span>
                                                                <span className="font-bold">₹{scored.maxCollectible.toFixed(2)}</span>
                                                            </div>
                                                            <div className="opacity-60 text-[10px] pt-1 border-t border-current/20 mt-1">
                                                                py_vollib returns annualised θ. Divide by 365 for daily decay. Max collectible = premium × lot (actual income if expires worthless).
                                                            </div>
                                                        </TooltipContent>
                                                    </Tooltip>
                                                </TooltipProvider>
                                            ) : <span className="text-xs text-muted-foreground">—</span>}
                                        </TableCell>
                                        {/* ROM% */}
                                        {hasMarginData && (
                                            <TableCell className="text-center">
                                                {scored ? (
                                                    <TooltipProvider delayDuration={100}>
                                                        <Tooltip>
                                                            <TooltipTrigger asChild>
                                                                <span className="text-xs font-medium text-purple-500 cursor-help underline decoration-dotted">
                                                                    {scored.rom != null ? `${scored.rom.toFixed(1)}%` : '—'}
                                                                </span>
                                                            </TooltipTrigger>
                                                            <TooltipContent side="top" className="min-w-[200px] p-2">
                                                                <div className="font-bold mb-2">Return on Margin</div>
                                                                <div className="flex justify-between gap-4">
                                                                    <span className="opacity-70">Premium (LTP)</span>
                                                                    <span>₹{scored.currentPremium.toFixed(2)}</span>
                                                                </div>
                                                                <div className="flex justify-between gap-4">
                                                                    <span className="opacity-70">Lot size</span>
                                                                    <span>× {bestStrikeConfig.lotSize}</span>
                                                                </div>
                                                                <div className="flex justify-between gap-4">
                                                                    <span className="opacity-70">Premium collected</span>
                                                                    <span>₹{(scored.currentPremium * bestStrikeConfig.lotSize).toFixed(2)}</span>
                                                                </div>
                                                                <div className="flex justify-between gap-4">
                                                                    <span className="opacity-70">Margin required</span>
                                                                    <span>₹{marginData[row.symbol] != null ? marginData[row.symbol]!.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—'}</span>
                                                                </div>
                                                                <div className="border-t border-border pt-1 flex justify-between gap-4 font-semibold">
                                                                    <span className="opacity-70">ROM</span>
                                                                    <span className="font-bold">{scored.rom != null ? `${scored.rom.toFixed(2)}%` : '—'}</span>
                                                                </div>
                                                                <div className="opacity-60 text-[10px] pt-1 border-t border-current/20 mt-1">
                                                                    (Premium × Lot) ÷ Margin × 100
                                                                </div>
                                                            </TooltipContent>
                                                        </Tooltip>
                                                    </TooltipProvider>
                                                ) : <span className="text-xs text-muted-foreground">—</span>}
                                            </TableCell>
                                        )}
                                        {/* Score */}
                                        <TableCell className="text-center">
                                            {score !== null ? (
                                                <span className={cn(
                                                    "inline-flex items-center justify-center rounded-full px-2 py-0.5 text-xs font-bold",
                                                    score >= 70 ? "bg-green-500/15 text-green-500" :
                                                    score >= 40 ? "bg-yellow-500/15 text-yellow-500" :
                                                    "bg-red-500/15 text-red-500"
                                                )}>
                                                    {score}
                                                </span>
                                            ) : <span className="text-xs text-muted-foreground">—</span>}
                                        </TableCell>
                                        <TableCell className="text-center">
                                            {row.isAllPass ?
                                                <div className="flex justify-center"><div className="h-6 w-6 rounded-full bg-green-500 flex items-center justify-center text-white"><Check className="h-4 w-4" /></div></div> :
                                                <div className="flex justify-center"><div className="h-6 w-6 rounded-full bg-red-500/20 flex items-center justify-center text-red-500"><X className="h-4 w-4" /></div></div>
                                            }
                                        </TableCell>
                                    </TableRow>
                                    )
                                })}
                                {tableRows.length === 0 && (
                                    <TableRow>
                                        <TableCell colSpan={13} className="h-24 text-center">
                                            No strikes match the criteria or market is closed.
                                        </TableCell>
                                    </TableRow>
                                )}
                            </TableBody>
                        </Table>
                    </Card>
                </div>
            )}

            {!isMonitoring && !optionChain && (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground space-y-4">
                    <div className="h-16 w-16 bg-muted rounded-full flex items-center justify-center">
                        <Settings2 className="h-8 w-8 opacity-50" />
                    </div>
                    <h3 className="text-lg font-medium">Ready to Monitor</h3>
                    <p className="max-w-sm text-center">Configure the parameters above and click 'Start Monitor' to begin tracking option spikes.</p>
                </div>
            )}
        </div>
    )
}

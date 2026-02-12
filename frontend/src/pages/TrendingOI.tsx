import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, Check, ChevronsUpDown, Loader2, RefreshCcw, Settings2, X } from 'lucide-react'
import { useThemeStore } from '@/stores/themeStore'
import {
    timeseriesApi,
    type TimeseriesChainResponse,
    type ColumnarDataResponse,
    type TimeseriesRawRow,
    type TimeseriesRow,
} from '@/api/timeseries'
import { Card, CardContent } from '@/components/ui/card'
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { showToast } from '@/utils/toast'

// ── Constants ──────────────────────────────────────────────────────

const FNO_EXCHANGES = [
    { value: 'NFO', label: 'NFO' },
    { value: 'BFO', label: 'BFO' },
]

const DEFAULT_UNDERLYINGS: Record<string, string[]> = {
    NFO: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'],
    BFO: ['SENSEX', 'BANKEX'],
}

const INTERVALS = ['1m', '3m', '5m', '15m', '1h']

const INTERVAL_MINUTES: Record<string, number> = {
    '1m': 1, '3m': 3, '5m': 5, '15m': 15, '1h': 60,
}

const RANGE_OPTIONS = Array.from({ length: 25 }, (_, i) => i + 1)

type StrikeMode = 'range' | 'custom'
type AtmMode = 'auto' | 'fixed'

// Column group visibility toggles
interface ColumnVisibility {
    total: boolean
    dayChange: boolean
    change: boolean
    volume: boolean
    sentiment: boolean
}

const DEFAULT_VISIBILITY: ColumnVisibility = {
    total: false,      // hidden by default
    dayChange: true,
    change: true,
    volume: false,     // hidden by default
    sentiment: true,
}

// ── Sentiment logic ────────────────────────────────────────────────
// LTP↑ + OI↑ = Long Buildup    (strong green)
// LTP↓ + OI↑ = Short Buildup   (strong red)
// LTP↑ + OI↓ = Short Covering  (lighter green — bullish unwind)
// LTP↓ + OI↓ = Long Unwinding  (lighter red — bearish unwind)

type Sentiment = 'Long Buildup' | 'Short Buildup' | 'Short Cover' | 'Long Unwind' | '—'

function computeSentiment(
    futLtpChange: number,
    futOiChange: number
): Sentiment {
    // If either change is 0, no clear sentiment
    if (futLtpChange === 0 || futOiChange === 0) return '—'
    if (futLtpChange > 0 && futOiChange > 0) return 'Long Buildup'
    if (futLtpChange > 0 && futOiChange < 0) return 'Short Cover'
    if (futLtpChange < 0 && futOiChange > 0) return 'Short Buildup'
    if (futLtpChange < 0 && futOiChange < 0) return 'Long Unwind'
    return '—'
}

function getSentimentStyle(s: Sentiment): string {
    switch (s) {
        case 'Long Buildup': return 'bg-green-600 text-white'
        case 'Short Cover': return 'bg-green-400/80 text-white'
        case 'Short Buildup': return 'bg-red-600 text-white'
        case 'Long Unwind': return 'bg-red-400/80 text-white'
        default: return 'bg-muted text-muted-foreground'
    }
}

// ── Utility functions ──────────────────────────────────────────────

function convertExpiryForAPI(expiry: string): string {
    if (!expiry) return ''
    const parts = expiry.split('-')
    if (parts.length === 3) {
        return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
    }
    return expiry.replace(/-/g, '').toUpperCase()
}

function parseTimestamp(raw: string | number): Date | null {
    if (!raw) return null
    if (typeof raw === 'number') return new Date(raw > 1e12 ? raw : raw * 1000)
    const s = String(raw).trim()
    const d = new Date(s)
    if (!Number.isNaN(d.getTime())) return d
    if (s.includes(' ') && !s.includes('T')) {
        const d2 = new Date(s.replace(' ', 'T'))
        if (!Number.isNaN(d2.getTime())) return d2
    }
    return null
}

function formatTime(timestamp: string): string {
    if (!timestamp) return ''
    const d = parseTimestamp(timestamp)
    if (!d) return String(timestamp)
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function formatNumber(val: number, decimals = 0): string {
    if (val === 0) return '0'
    const abs = Math.abs(val)
    if (abs >= 1e7) return `${(val / 1e7).toFixed(2)}Cr`
    if (abs >= 1e5) return `${(val / 1e5).toFixed(2)}L`
    if (abs >= 1e3) return `${(val / 1e3).toFixed(1)}K`
    return val.toFixed(decimals)
}

const MONTH_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Format timestamp as "10 Feb 11:23:07 AM" */
function formatUpdatedTimestamp(timestamp: string): string {
    const d = parseTimestamp(timestamp)
    if (!d) return ''
    const day = d.getDate()
    const mon = MONTH_SHORT[d.getMonth()]
    let h = d.getHours()
    const ampm = h >= 12 ? 'PM' : 'AM'
    h = h % 12 || 12
    const mm = String(d.getMinutes()).padStart(2, '0')
    const ss = String(d.getSeconds()).padStart(2, '0')
    return `${day} ${mon} ${h}:${mm}:${ss} ${ampm}`
}

/**
 * Heatmap: <=0 red, >0 green. Intensity relative to column max.
 * Alpha capped at 0.45 to keep white text clearly readable.
 */
function getHeatmapBg(value: number, colMax: number, isDark: boolean): string {
    if (value === 0 || colMax === 0) return 'transparent'
    const intensity = Math.min(Math.abs(value) / colMax, 1)
    const alpha = 0.10 + intensity * 0.35  // range 0.10–0.45, keeps text readable
    if (value > 0) return isDark ? `rgba(34,197,94,${alpha})` : `rgba(22,163,74,${alpha})`
    return isDark ? `rgba(239,68,68,${alpha})` : `rgba(220,38,38,${alpha})`
}

function getValueColor(value: number): string {
    if (value > 0) return 'text-emerald-400'
    if (value < 0) return 'text-rose-400'
    return 'text-muted-foreground'
}

// ── Columnar → aggregated conversion ───────────────────────────────

// Frontend-built metadata for each symbol (from chain data)
interface SymbolMeta {
    type: 'CE' | 'PE' | 'FUT'
    strike?: number | null
}

function aggregateColumnarToRaw(
    data: ColumnarDataResponse,
    symbolsMeta: Record<string, SymbolMeta>,
    selectedStrikes?: number[]
): TimeseriesRawRow[] {
    if (!data.timestamps?.length) return []
    const OI = data.columns.indexOf('oi')
    const LTP = data.columns.indexOf('ltp')
    const VOL = data.columns.indexOf('volume')
    const strikeSet = selectedStrikes?.length ? new Set(selectedStrikes) : null
    // Classify symbols using frontend-built metadata
    const ceSyms = Object.entries(symbolsMeta)
        .filter(([, m]) => m.type === 'CE' && (!strikeSet || (m.strike != null && strikeSet.has(m.strike))))
        .map(([s]) => s)
    const peSyms = Object.entries(symbolsMeta)
        .filter(([, m]) => m.type === 'PE' && (!strikeSet || (m.strike != null && strikeSet.has(m.strike))))
        .map(([s]) => s)
    const futSym = Object.entries(symbolsMeta).find(([, m]) => m.type === 'FUT')?.[0]

    // Volume is per-candle (incremental), not a snapshot like OI.
    // Accumulate into running totals so downstream diff logic produces:
    //   Total = cumulative volume, DayChange = vol since start, Change = vol in this interval
    let ceVolCum = 0, peVolCum = 0, futVolCum = 0
    return data.timestamps.map((ts, i) => {
        if (VOL >= 0) {
            ceVolCum += ceSyms.reduce((sum, s) => sum + (data.symbol_data[s]?.[VOL]?.[i] ?? 0), 0)
            peVolCum += peSyms.reduce((sum, s) => sum + (data.symbol_data[s]?.[VOL]?.[i] ?? 0), 0)
            if (futSym) futVolCum += data.symbol_data[futSym]?.[VOL]?.[i] ?? 0
        }
        return {
            timestamp: ts,
            ce_oi: ceSyms.reduce((sum, s) => sum + (data.symbol_data[s]?.[OI]?.[i] ?? 0), 0),
            pe_oi: peSyms.reduce((sum, s) => sum + (data.symbol_data[s]?.[OI]?.[i] ?? 0), 0),
            ce_volume: ceVolCum,
            pe_volume: peVolCum,
            fut_ltp: futSym ? (data.symbol_data[futSym]?.[LTP]?.[i] ?? 0) : 0,
            fut_oi: futSym ? (data.symbol_data[futSym]?.[OI]?.[i] ?? 0) : 0,
            fut_volume: futVolCum,
        }
    })
}

// ── Data processing (all derived metrics on frontend) ──────────────

function processRawData(
    rawData: TimeseriesRawRow[],
    intervalMinutes: number
): TimeseriesRow[] {
    if (!rawData.length) return []

    // Sample the end of each interval block but keep the START timestamp
    const sampled: TimeseriesRawRow[] = []
    for (let i = 0; i < rawData.length; i += intervalMinutes) {
        const startRow = rawData[i]
        const endIdx = Math.min(i + intervalMinutes - 1, rawData.length - 1)
        const endRow = rawData[endIdx]

        sampled.push({
            ...endRow,
            timestamp: startRow.timestamp // Use the start-of-interval time (e.g., 9:15)
        })
    }
    if (!sampled.length) return []

    // Baseline for day_change is ALWAYS the very first candle (9:15 1m)
    const absoluteFirst = rawData[0]
    const firstPCR = absoluteFirst.ce_oi > 0 ? Math.round((absoluteFirst.pe_oi / absoluteFirst.ce_oi) * 100) / 100 : 0
    const firstPeCe = absoluteFirst.pe_oi - absoluteFirst.ce_oi

    const result: TimeseriesRow[] = []

    for (let i = 0; i < sampled.length; i++) {
        const r = sampled[i]
        const prev = i > 0 ? result[i - 1] : null

        const pe_ce_oi = r.pe_oi - r.ce_oi
        const pcr = r.ce_oi > 0 ? Math.round((r.pe_oi / r.ce_oi) * 100) / 100 : 0

        result.push({
            timestamp: r.timestamp,
            ce_oi: r.ce_oi,
            pe_oi: r.pe_oi,
            pe_ce_oi,
            pcr,
            ce_volume: r.ce_volume,
            pe_volume: r.pe_volume,
            fut_ltp: r.fut_ltp,
            fut_oi: r.fut_oi,
            fut_volume: r.fut_volume,
            // OI Day Change: current snapshot - morning snapshot
            ce_oi_day_change: r.ce_oi - absoluteFirst.ce_oi,
            pe_oi_day_change: r.pe_oi - absoluteFirst.pe_oi,
            // Volume Day Change: basically matches Total since vol starts at 0
            ce_volume_day_change: r.ce_volume,
            pe_volume_day_change: r.pe_volume,
            pe_ce_oi_day_change: pe_ce_oi - firstPeCe,
            pcr_day_change: Math.round((pcr - firstPCR) * 100) / 100,
            fut_ltp_day_change: r.fut_ltp - absoluteFirst.fut_ltp,
            fut_oi_day_change: r.fut_oi - absoluteFirst.fut_oi,
            fut_volume_day_change: r.fut_volume,
            // Row change (from previous visible row)
            ce_oi_change: prev ? r.ce_oi - prev.ce_oi : r.ce_oi - absoluteFirst.ce_oi,
            pe_oi_change: prev ? r.pe_oi - prev.pe_oi : r.pe_oi - absoluteFirst.pe_oi,
            // Volume change is current total - previous total
            ce_volume_change: prev ? r.ce_volume - prev.ce_volume : r.ce_volume,
            pe_volume_change: prev ? r.pe_volume - prev.pe_volume : r.pe_volume,
            pe_ce_oi_change: prev ? pe_ce_oi - prev.pe_ce_oi : pe_ce_oi - firstPeCe,
            pcr_change: prev ? Math.round((pcr - prev.pcr) * 100) / 100 : Math.round((pcr - firstPCR) * 100) / 100,
            fut_ltp_change: prev ? r.fut_ltp - prev.fut_ltp : r.fut_ltp - absoluteFirst.fut_ltp,
            fut_oi_change: prev ? r.fut_oi - prev.fut_oi : r.fut_oi - absoluteFirst.fut_oi,
            fut_volume_change: prev ? r.fut_volume - prev.fut_volume : r.fut_volume,
        })
    }
    return result
}

function colMax(data: TimeseriesRow[], key: keyof TimeseriesRow): number {
    if (!data.length) return 0
    return Math.max(...data.map((r) => Math.abs(r[key] as number)))
}

// ── Divider style constant ─────────────────────────────────────────
const DIV = 'border-r-2 border-border'     // thick divider between groups
const SUBDIV = 'border-r border-border/50'  // light divider within group

// ── Component ──────────────────────────────────────────────────────

export default function TrendingOI() {
    const { mode, appMode } = useThemeStore()
    const isDark = mode === 'dark' || appMode === 'analyzer'

    // Selection states
    const [selectedExchange, setSelectedExchange] = useState('NFO')
    const [underlyings, setUnderlyings] = useState<string[]>(DEFAULT_UNDERLYINGS.NFO)
    const [underlyingOpen, setUnderlyingOpen] = useState(false)
    const [selectedUnderlying, setSelectedUnderlying] = useState('NIFTY')
    const [expiries, setExpiries] = useState<string[]>([])
    const [selectedExpiry, setSelectedExpiry] = useState('')
    const [selectedInterval, setSelectedInterval] = useState('3m')
    const [historicalDate, setHistoricalDate] = useState(new Date().toISOString().split('T')[0])
    const [strikeRange, setStrikeRange] = useState(3)
    const [sortAsc, setSortAsc] = useState(false)

    // Strike selection mode
    const [strikeMode, setStrikeMode] = useState<StrikeMode>('range')
    const [atmMode, setAtmMode] = useState<AtmMode>('auto')
    const [fixedCenterStrike, setFixedCenterStrike] = useState<number | null>(null)
    const [customStrikes, setCustomStrikes] = useState<number[]>([])
    const [strikeDropdownOpen, setStrikeDropdownOpen] = useState(false)

    // Column visibility
    const [colVis, setColVis] = useState<ColumnVisibility>(DEFAULT_VISIBILITY)
    const [settingsOpen, setSettingsOpen] = useState(false)

    // Data states
    const [chainData, setChainData] = useState<TimeseriesChainResponse | null>(null)
    const [rawData, setRawData] = useState<ColumnarDataResponse | null>(null)
    const [symbolsMeta, setSymbolsMeta] = useState<Record<string, SymbolMeta> | null>(null)
    const [loadedConfig, setLoadedConfig] = useState<{
        exchange: string,
        underlying: string,
        expiry: string,
        date: string
    } | null>(null)
    const [isLoading, setIsLoading] = useState(false)
    const requestIdRef = useRef(0)

    // All available strikes from chain (sorted)
    const availableStrikes = useMemo(() => {
        if (!chainData?.symbols) return []
        const strikes = [...new Set(
            chainData.symbols.filter(s => s.strike != null).map(s => s.strike!)
        )].sort((a, b) => a - b)
        return strikes
    }, [chainData])

    // Set defaults when chain data arrives
    useEffect(() => {
        if (chainData?.atm_strike != null) {
            setFixedCenterStrike(chainData.atm_strike)
            setCustomStrikes([chainData.atm_strike])
        }
    }, [chainData?.atm_strike])

    // Effective strikes based on current mode
    const effectiveStrikes = useMemo(() => {
        if (!availableStrikes.length) return []
        if (strikeMode === 'custom') return customStrikes.sort((a, b) => a - b)
        // Range mode
        const center = atmMode === 'fixed' && fixedCenterStrike != null
            ? fixedCenterStrike
            : chainData?.atm_strike ?? 0
        const idx = availableStrikes.indexOf(center)
        if (idx === -1) return availableStrikes.slice(0, strikeRange * 2 + 1)
        const start = Math.max(0, idx - strikeRange)
        const end = Math.min(availableStrikes.length, idx + strikeRange + 1)
        return availableStrikes.slice(start, end)
    }, [availableStrikes, strikeMode, atmMode, fixedCenterStrike, strikeRange, customStrikes, chainData?.atm_strike])

    // Min/max strike from effective selection
    const strikeInfo = useMemo(() => {
        if (!effectiveStrikes.length) return null
        return { min: effectiveStrikes[0], max: effectiveStrikes[effectiveStrikes.length - 1] }
    }, [effectiveStrikes])

    // ── Fetch underlyings / expiries (still auto) ──

    useEffect(() => {
        const defaults = DEFAULT_UNDERLYINGS[selectedExchange] || []
        setUnderlyings(defaults)
        setSelectedUnderlying(defaults[0] || '')
        setExpiries([])
        setSelectedExpiry('')
        setChainData(null)
        setRawData(null)

        let cancelled = false
            ; (async () => {
                try {
                    const res = await timeseriesApi.getUnderlyings(selectedExchange)
                    if (cancelled) return
                    if (res.status === 'success' && res.underlyings.length > 0) {
                        setUnderlyings(res.underlyings)
                        if (!res.underlyings.includes(defaults[0])) setSelectedUnderlying(res.underlyings[0])
                    }
                } catch { /* keep defaults */ }
            })()
        return () => { cancelled = true }
    }, [selectedExchange])

    useEffect(() => {
        if (!selectedUnderlying) return
        setExpiries([])
        setSelectedExpiry('')
        setChainData(null)
        setRawData(null)

        let cancelled = false
            ; (async () => {
                try {
                    const res = await timeseriesApi.getExpiries(selectedExchange, selectedUnderlying)
                    if (cancelled) return
                    if (res.status === 'success' && res.expiries.length > 0) {
                        setExpiries(res.expiries)
                        setSelectedExpiry(res.expiries[0])
                    }
                } catch {
                    if (!cancelled) setExpiries([])
                }
            })()
        return () => { cancelled = true }
    }, [selectedExchange, selectedUnderlying])

    // ── Auto-fetch chain when expiry changes ──

    useEffect(() => {
        if (!selectedExpiry) return
        setRawData(null)

        let cancelled = false
            ; (async () => {
                try {
                    const expiryForAPI = convertExpiryForAPI(selectedExpiry)
                    const chainRes = await timeseriesApi.getChain({
                        underlying: selectedUnderlying,
                        exchange: selectedExchange,
                        expiry_date: expiryForAPI,
                        strike_count: 25,
                    })
                    if (cancelled) return
                    if (chainRes.status === 'success') {
                        setChainData(chainRes)
                    }
                } catch { /* ignore */ }
            })()
        return () => { cancelled = true }
    }, [selectedExpiry, selectedUnderlying, selectedExchange])

    // ── Manual Load action (history only, uses existing chainData) ──

    const handleLoad = useCallback(async () => {
        if (!chainData || !selectedExpiry) return
        const requestId = ++requestIdRef.current

        // Clear previous data immediately so we don't show stale/partial results while fetching
        setRawData(null)
        setLoadedConfig(null)

        setIsLoading(true)
        try {
            const allSymbols = chainData.symbols || []
            // Use effectiveStrikes (already reactive to range/mode changes)
            const strikeSet = effectiveStrikes.length > 0 ? new Set(effectiveStrikes) : null
            const filteredSymbols = strikeSet
                ? allSymbols.filter(s => s.strike == null || strikeSet.has(s.strike))
                : allSymbols

            // Include futures as a regular symbol in the list
            const symbolsToFetch = [...filteredSymbols]
            if (chainData.futures?.symbol && chainData.futures?.exchange) {
                symbolsToFetch.push({
                    symbol: chainData.futures.symbol,
                    exchange: chainData.futures.exchange,
                    type: 'FUT' as const,
                })
            }

            // Build symbols_meta locally — frontend owns classification
            const localMeta: Record<string, SymbolMeta> = {}
            for (const s of symbolsToFetch) {
                const uniqueKey = `${s.symbol}:${s.exchange}`
                localMeta[uniqueKey] = { type: s.type ?? 'CE', strike: s.strike ?? null }
            }
            setSymbolsMeta(localMeta)

            const dataRes = await timeseriesApi.getData({
                symbols: symbolsToFetch.map(s => ({ symbol: s.symbol, exchange: s.exchange })),
                interval: '1m',
                start_date: historicalDate,
                end_date: historicalDate,
            })
            if (requestIdRef.current !== requestId) return
            if (dataRes.status === 'success') {
                setRawData(dataRes)
                setLoadedConfig({
                    exchange: selectedExchange,
                    underlying: selectedUnderlying,
                    expiry: selectedExpiry,
                    date: historicalDate
                })
            } else {
                showToast.error(dataRes.message || 'Failed to fetch timeseries data')
            }
        } catch {
            if (requestIdRef.current === requestId) showToast.error('Failed to load data')
        } finally {
            if (requestIdRef.current === requestId) setIsLoading(false)
        }
    }, [chainData, selectedExpiry, effectiveStrikes, historicalDate, selectedExchange, selectedUnderlying])

    // ── Frontend computation ──

    // Check if the currently selected strikes and parameters match the loaded data
    const isDataSufficient = useMemo(() => {
        if (!symbolsMeta || !loadedConfig) return false

        // Match core parameters
        if (loadedConfig.exchange !== selectedExchange ||
            loadedConfig.underlying !== selectedUnderlying ||
            loadedConfig.expiry !== selectedExpiry ||
            loadedConfig.date !== historicalDate) {
            return false
        }

        const loadedStrikes = new Set(
            Object.values(symbolsMeta)
                .filter(m => m.strike != null)
                .map(m => m.strike!)
        )
        // Every selected strike must be in the loaded dataset
        return effectiveStrikes.every(s => loadedStrikes.has(s))
    }, [symbolsMeta, loadedConfig, selectedExchange, selectedUnderlying, selectedExpiry, historicalDate, effectiveStrikes])

    const processedData = useMemo(() => {
        if (!rawData?.timestamps?.length || !symbolsMeta || !isDataSufficient) return []
        const aggregated = aggregateColumnarToRaw(rawData, symbolsMeta, effectiveStrikes.length > 0 ? effectiveStrikes : undefined)
        return processRawData(aggregated, INTERVAL_MINUTES[selectedInterval] || 1)
    }, [rawData, selectedInterval, effectiveStrikes, symbolsMeta, isDataSufficient])

    const sortedData = useMemo(() => {
        if (!processedData.length) return []
        return [...processedData].sort((a, b) => {
            const tA = parseTimestamp(a.timestamp)?.getTime() ?? 0
            const tB = parseTimestamp(b.timestamp)?.getTime() ?? 0
            return sortAsc ? tA - tB : tB - tA
        })
    }, [processedData, sortAsc])

    // Per-column max for heatmap
    const mx = useMemo(() => {
        const d = processedData
        return {
            pe_oi: colMax(d, 'pe_oi'),
            ce_oi: colMax(d, 'ce_oi'),
            pe_volume: colMax(d, 'pe_volume'),
            ce_volume: colMax(d, 'ce_volume'),
            pe_ce_oi: colMax(d, 'pe_ce_oi'),
            fut_oi: colMax(d, 'fut_oi'),
            fut_volume: colMax(d, 'fut_volume'),
            pe_oi_day: colMax(d, 'pe_oi_day_change'),
            ce_oi_day: colMax(d, 'ce_oi_day_change'),
            pe_volume_day: colMax(d, 'pe_volume_day_change'),
            ce_volume_day: colMax(d, 'ce_volume_day_change'),
            pe_ce_oi_day: colMax(d, 'pe_ce_oi_day_change'),
            pcr_day: colMax(d, 'pcr_day_change'),
            fut_oi_day: colMax(d, 'fut_oi_day_change'),
            fut_volume_day: colMax(d, 'fut_volume_day_change'),
            fut_ltp_day: colMax(d, 'fut_ltp_day_change'),
        }
    }, [processedData])

    // ── Helper: column counts for group headers ──

    function putCallGroupCols(): number {
        let n = 0
        if (colVis.total) n++
        if (colVis.dayChange) n++
        if (colVis.change) n++
        return n
    }

    function volumeGroupCols(): number {
        let n = 0
        if (colVis.volume && colVis.total) n++
        // Volume Day Change is redundant (starts at 0), so not shown
        if (colVis.volume && colVis.change) n++
        return n
    }

    function peCeGroupCols(): number {
        let n = 0
        if (colVis.total) n++
        if (colVis.dayChange) n++
        if (colVis.change) n++
        return n
    }

    function pcrGroupCols(): number {
        let n = 0
        if (colVis.total) n++
        if (colVis.dayChange) n++
        if (colVis.change) n++
        return n
    }

    function futOIGroupCols(): number {
        let n = 1 // LTP always shown
        if (colVis.total) n++     // OI Total
        if (colVis.dayChange) n++ // OI Day Change
        if (colVis.change) n++    // OI Change
        return n
    }

    function futVolGroupCols(): number {
        let n = 0
        if (colVis.volume && colVis.total) n++
        // Volume Day Change is redundant, so not shown
        if (colVis.volume && colVis.change) n++
        return n
    }

    const anyVisible = putCallGroupCols() > 0 || volumeGroupCols() > 0 || peCeGroupCols() > 0 || pcrGroupCols() > 0 || futOIGroupCols() > 0 || futVolGroupCols() > 0 || colVis.sentiment

    // ── Render ──

    return (
        <div className="py-6 space-y-4">
            {/* Header Controls */}
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <h1 className="text-2xl font-bold">Trending OI</h1>
                <div className="flex items-center gap-2 flex-wrap">
                    {/* Exchange */}
                    <Select value={selectedExchange} onValueChange={setSelectedExchange}>
                        <SelectTrigger className="w-[80px]"><SelectValue placeholder="Exchange" /></SelectTrigger>
                        <SelectContent>
                            {FNO_EXCHANGES.map((ex) => (
                                <SelectItem key={ex.value} value={ex.value}>{ex.label}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>

                    {/* Underlying */}
                    <Popover open={underlyingOpen} onOpenChange={setUnderlyingOpen}>
                        <PopoverTrigger asChild>
                            <Button variant="outline" role="combobox" aria-expanded={underlyingOpen} className="w-[140px] justify-between">
                                {selectedUnderlying || 'Underlying'}
                                <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                            </Button>
                        </PopoverTrigger>
                        <PopoverContent className="w-48 p-0" align="start">
                            <Command>
                                <CommandInput placeholder="Search..." />
                                <CommandList>
                                    <CommandEmpty>No underlying found</CommandEmpty>
                                    <CommandGroup>
                                        {underlyings.map((u) => (
                                            <CommandItem key={u} value={u} onSelect={() => { setSelectedUnderlying(u); setUnderlyingOpen(false) }}>
                                                <Check className={`mr-2 h-4 w-4 ${selectedUnderlying === u ? 'opacity-100' : 'opacity-0'}`} />
                                                {u}
                                            </CommandItem>
                                        ))}
                                    </CommandGroup>
                                </CommandList>
                            </Command>
                        </PopoverContent>
                    </Popover>

                    {/* Expiry */}
                    <Select value={selectedExpiry} onValueChange={setSelectedExpiry} disabled={expiries.length === 0}>
                        <SelectTrigger className="w-[130px]"><SelectValue placeholder="Expiry" /></SelectTrigger>
                        <SelectContent>
                            {expiries.map((e) => (<SelectItem key={e} value={e}>{e}</SelectItem>))}
                        </SelectContent>
                    </Select>

                    {/* Interval buttons */}
                    <div className="flex bg-muted rounded-md p-0.5">
                        {INTERVALS.map((int) => (
                            <button key={int} onClick={() => setSelectedInterval(int)}
                                className={`px-2 py-1 text-xs rounded transition-colors ${selectedInterval === int ? 'bg-primary text-primary-foreground' : 'hover:bg-muted-foreground/10'}`}
                            >{int}</button>
                        ))}
                    </div>

                    {/* Date */}
                    <Input type="date" value={historicalDate} onChange={(e) => setHistoricalDate(e.target.value)} className="w-[130px] text-xs" />

                    {/* Table Settings */}
                    <Popover open={settingsOpen} onOpenChange={setSettingsOpen}>
                        <PopoverTrigger asChild>
                            <Button variant="outline" size="icon"><Settings2 className="h-4 w-4" /></Button>
                        </PopoverTrigger>
                        <PopoverContent className="w-48 p-3" align="end">
                            <p className="text-xs font-semibold mb-2">Show Columns</p>
                            {([
                                ['total', 'Total'],
                                ['dayChange', 'Day Change'],
                                ['change', 'Change'],
                                ['volume', 'Volume'],
                                ['sentiment', 'Sentiment'],
                            ] as [keyof ColumnVisibility, string][]).map(([key, label]) => (
                                <label key={key} className="flex items-center gap-2 py-1 cursor-pointer text-sm">
                                    <input
                                        type="checkbox"
                                        checked={colVis[key]}
                                        onChange={() => setColVis((v) => ({ ...v, [key]: !v[key] }))}
                                        className="rounded"
                                    />
                                    {label}
                                </label>
                            ))}
                        </PopoverContent>
                    </Popover>
                </div>
            </div>

            {/* Row 2: Strike Selection + Load */}
            <div className="flex items-center gap-2 flex-wrap">
                {/* Strike Mode toggle: Range | Custom */}
                <div className="flex bg-muted rounded-md p-0.5">
                    <button onClick={() => setStrikeMode('range')}
                        className={`px-3 py-1 text-xs rounded transition-colors ${strikeMode === 'range' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted-foreground/10'}`}
                    >Range</button>
                    <button onClick={() => setStrikeMode('custom')}
                        className={`px-3 py-1 text-xs rounded transition-colors ${strikeMode === 'custom' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted-foreground/10'}`}
                    >Custom</button>
                </div>

                {strikeMode === 'range' ? (
                    <>
                        {/* ATM Mode: Auto ATM | Fixed */}
                        <div className="flex bg-muted rounded-md p-0.5">
                            <button onClick={() => setAtmMode('auto')}
                                className={`px-3 py-1 text-xs rounded transition-colors ${atmMode === 'auto' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted-foreground/10'}`}
                            >Auto ATM</button>
                            <button onClick={() => setAtmMode('fixed')}
                                className={`px-3 py-1 text-xs rounded transition-colors ${atmMode === 'fixed' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted-foreground/10'}`}
                            >Fixed</button>
                        </div>

                        {/* Fixed center strike selector */}
                        {atmMode === 'fixed' && availableStrikes.length > 0 && (
                            <Select
                                value={fixedCenterStrike != null ? String(fixedCenterStrike) : ''}
                                onValueChange={(v) => setFixedCenterStrike(Number(v))}
                            >
                                <SelectTrigger className="w-[110px]">
                                    <SelectValue placeholder="Center" />
                                </SelectTrigger>
                                <SelectContent>
                                    {availableStrikes.map((s) => (
                                        <SelectItem key={s} value={String(s)}>
                                            {s}{s === chainData?.atm_strike ? ' (ATM)' : ''}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        )}

                        {/* Range count */}
                        <Select value={String(strikeRange)} onValueChange={(v) => setStrikeRange(Number(v))}>
                            <SelectTrigger className="w-[70px]"><SelectValue placeholder="Range" /></SelectTrigger>
                            <SelectContent>
                                {RANGE_OPTIONS.map((r) => (<SelectItem key={r} value={String(r)}>±{r}</SelectItem>))}
                            </SelectContent>
                        </Select>
                    </>
                ) : (
                    /* Custom mode: multi-select strikes */
                    <div className="flex items-center gap-1 flex-wrap min-w-[200px]">
                        {/* Selected strike tags */}
                        {customStrikes.sort((a, b) => a - b).map((s) => (
                            <Badge key={s} variant="secondary" className="text-xs px-2 py-0.5 gap-1">
                                {s}{s === chainData?.atm_strike ? '*' : ''}
                                <button
                                    onClick={() => setCustomStrikes((prev) => prev.filter((v) => v !== s))}
                                    className="ml-0.5 hover:text-destructive"
                                    aria-label={`Remove strike ${s}`}
                                >
                                    <X className="h-3 w-3" />
                                </button>
                            </Badge>
                        ))}

                        {/* Add strike dropdown */}
                        <Popover open={strikeDropdownOpen} onOpenChange={setStrikeDropdownOpen}>
                            <PopoverTrigger asChild>
                                <Button variant="outline" size="sm" className="h-7 text-xs px-2" disabled={availableStrikes.length === 0}>
                                    + Strike
                                </Button>
                            </PopoverTrigger>
                            <PopoverContent className="w-48 p-0" align="start">
                                <Command>
                                    <CommandInput placeholder="Search strike..." />
                                    <CommandList>
                                        <CommandEmpty>No strikes available</CommandEmpty>
                                        <CommandGroup>
                                            {availableStrikes.map((s) => (
                                                <CommandItem
                                                    key={s}
                                                    value={String(s)}
                                                    onSelect={() => {
                                                        setCustomStrikes((prev) =>
                                                            prev.includes(s) ? prev.filter((v) => v !== s) : [...prev, s]
                                                        )
                                                    }}
                                                >
                                                    <Check className={`mr-2 h-4 w-4 ${customStrikes.includes(s) ? 'opacity-100' : 'opacity-0'}`} />
                                                    {s}{s === chainData?.atm_strike ? ' (ATM)' : ''}
                                                </CommandItem>
                                            ))}
                                        </CommandGroup>
                                    </CommandList>
                                </Command>
                            </PopoverContent>
                        </Popover>
                    </div>
                )}

                {/* Load Button */}
                <Button onClick={handleLoad} disabled={isLoading || !selectedExpiry} className="min-w-[80px]">
                    {isLoading ? (
                        <><Loader2 className="mr-1 h-4 w-4 animate-spin" />Loading...</>
                    ) : (
                        <><RefreshCcw className="mr-1 h-4 w-4" />Load</>
                    )}
                </Button>
            </div>

            {/* Info badges */}
            {chainData && chainData.status === 'success' && (
                <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary" className="text-sm px-3 py-1">Spot: {chainData.underlying_ltp?.toFixed(1)}</Badge>
                    <Badge variant="secondary" className="text-sm px-3 py-1">ATM: {chainData.atm_strike}</Badge>
                    <Badge variant="secondary" className="text-sm px-3 py-1">Lot: {chainData.lot_size}</Badge>
                    {chainData.futures && (
                        <Badge variant="secondary" className="text-sm px-3 py-1">Futures: {chainData.futures.symbol}</Badge>
                    )}
                    <Badge variant="secondary" className="text-sm px-3 py-1">
                        Strikes: {strikeMode === 'custom' ? `${effectiveStrikes.length} selected` : `±${strikeRange}`}{strikeInfo && ` (${strikeInfo.min}–${strikeInfo.max})`}{effectiveStrikes.length > 0 && ` [${effectiveStrikes.length} strikes]`}
                    </Badge>
                    <Badge variant="secondary" className="text-sm px-3 py-1">Rows: {sortedData.length}</Badge>
                </div>
            )}

            {/* Updated timestamp + Data Table */}
            <div className="flex items-center justify-between mb-1">
                <div />
                {sortedData.length > 0 && rawData?.timestamps?.length && (
                    <span className="text-xs text-muted-foreground">
                        Updated: {formatUpdatedTimestamp(rawData.timestamps[rawData.timestamps.length - 1] || '')}
                    </span>
                )}
            </div>
            <Card>
                <CardContent className="p-0 overflow-x-auto">
                    {isLoading && !rawData ? (
                        <div className="flex items-center justify-center h-[500px] text-muted-foreground">
                            <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading timeseries data...
                        </div>
                    ) : sortedData.length > 0 && anyVisible ? (
                        <table className="w-full text-sm border-collapse">
                            <thead className="sticky top-0 bg-background z-10">
                                {/* Row 1: Group headers */}
                                <tr className="border-b border-border">
                                    {/* Time */}
                                    <th rowSpan={2}
                                        className={`px-3 py-2 text-center font-semibold ${DIV} cursor-pointer select-none hover:bg-muted/50`}
                                        onClick={() => setSortAsc((p) => !p)}
                                    >
                                        <div className="flex items-center justify-center gap-1">
                                            Time
                                            {sortAsc ? <ArrowUp className="h-3.5 w-3.5 text-muted-foreground" /> : <ArrowDown className="h-3.5 w-3.5 text-muted-foreground" />}
                                        </div>
                                    </th>

                                    {/* Put OI group */}
                                    {putCallGroupCols() > 0 && (
                                        <th colSpan={putCallGroupCols()} className={`px-2 py-1 text-center font-semibold ${DIV} text-rose-400`}>Put OI</th>
                                    )}
                                    {/* Put Volume group */}
                                    {volumeGroupCols() > 0 && (
                                        <th colSpan={volumeGroupCols()} className={`px-2 py-1 text-center font-semibold ${DIV} text-rose-300`}>Put Vol</th>
                                    )}
                                    {/* Call OI group */}
                                    {putCallGroupCols() > 0 && (
                                        <th colSpan={putCallGroupCols()} className={`px-2 py-1 text-center font-semibold ${DIV} text-emerald-400`}>Call OI</th>
                                    )}
                                    {/* Call Volume group */}
                                    {volumeGroupCols() > 0 && (
                                        <th colSpan={volumeGroupCols()} className={`px-2 py-1 text-center font-semibold ${DIV} text-emerald-300`}>Call Vol</th>
                                    )}
                                    {/* PE-CE OI */}
                                    {peCeGroupCols() > 0 && (
                                        <th colSpan={peCeGroupCols()} className={`px-2 py-1 text-center font-semibold ${DIV}`}>PE-CE OI</th>
                                    )}
                                    {/* PCR */}
                                    {pcrGroupCols() > 0 && (
                                        <th colSpan={pcrGroupCols()} className={`px-2 py-1 text-center font-semibold ${DIV}`}>PCR</th>
                                    )}
                                    {/* Futures OI */}
                                    {futOIGroupCols() > 0 && (
                                        <th colSpan={futOIGroupCols()} className={`px-2 py-1 text-center font-semibold ${DIV}`}>Futures OI</th>
                                    )}
                                    {/* Futures Vol */}
                                    {futVolGroupCols() > 0 && (
                                        <th colSpan={futVolGroupCols()} className={`px-2 py-1 text-center font-semibold ${DIV}`}>Futures Vol</th>
                                    )}
                                    {/* Sentiment */}
                                    {colVis.sentiment && (
                                        <th rowSpan={2} className="px-2 py-1 text-center font-semibold">Sentiment</th>
                                    )}
                                </tr>
                                {/* Row 2: Sub-headers */}
                                <tr className="border-b border-border text-xs text-muted-foreground">
                                    {/* Put OI sub */}
                                    {colVis.total && <th className={`px-2 py-1 text-center ${SUBDIV}`}>Total</th>}
                                    {colVis.dayChange && <th className={`px-2 py-1 text-center ${SUBDIV}`}>Day Change</th>}
                                    {colVis.change && <th className={`px-2 py-1 text-center ${DIV}`}>Change</th>}
                                    {/* Put Volume sub */}
                                    {colVis.volume && colVis.total && <th className={`px-2 py-1 text-center ${SUBDIV}`}>Total</th>}
                                    {colVis.volume && colVis.change && <th className={`px-2 py-1 text-center ${DIV}`}>Change</th>}
                                    {/* Call OI sub */}
                                    {colVis.total && <th className={`px-2 py-1 text-center ${SUBDIV}`}>Total</th>}
                                    {colVis.dayChange && <th className={`px-2 py-1 text-center ${SUBDIV}`}>Day Change</th>}
                                    {colVis.change && <th className={`px-2 py-1 text-center ${DIV}`}>Change</th>}
                                    {/* Call Volume sub */}
                                    {colVis.volume && colVis.total && <th className={`px-2 py-1 text-center ${SUBDIV}`}>Total</th>}
                                    {colVis.volume && colVis.change && <th className={`px-2 py-1 text-center ${DIV}`}>Change</th>}
                                    {/* PE-CE sub */}
                                    {colVis.total && <th className={`px-2 py-1 text-center ${SUBDIV}`}>Total</th>}
                                    {colVis.dayChange && <th className={`px-2 py-1 text-center ${SUBDIV}`}>Day Change</th>}
                                    {colVis.change && <th className={`px-2 py-1 text-center ${DIV}`}>Change</th>}
                                    {/* PCR sub */}
                                    {colVis.total && <th className={`px-2 py-1 text-center ${SUBDIV}`}>Total</th>}
                                    {colVis.dayChange && <th className={`px-2 py-1 text-center ${SUBDIV}`}>Day Change</th>}
                                    {colVis.change && <th className={`px-2 py-1 text-center ${DIV}`}>Change</th>}
                                    {/* Futures OI sub */}
                                    <th className={`px-2 py-1 text-center ${SUBDIV}`}>LTP</th>
                                    {colVis.total && <th className={`px-2 py-1 text-center ${SUBDIV}`}>OI Total</th>}
                                    {colVis.dayChange && <th className={`px-2 py-1 text-center ${SUBDIV}`}>Day Change</th>}
                                    {colVis.change && <th className={`px-2 py-1 text-center ${DIV}`}>OI Change</th>}
                                    {/* Futures Vol sub */}
                                    {colVis.volume && colVis.total && <th className={`px-2 py-1 text-center ${SUBDIV}`}>Total</th>}
                                    {colVis.volume && colVis.change && <th className={`px-2 py-1 text-center ${DIV}`}>Change</th>}
                                </tr>
                            </thead>
                            <tbody>
                                {sortedData.map((row, idx) => {
                                    const sentiment = computeSentiment(row.fut_ltp_change, row.fut_oi_change)
                                    return (
                                        <tr key={row.timestamp} className={`border-b border-border/50 hover:bg-muted/30 ${idx === 0 ? 'font-medium' : ''}`}>
                                            {/* Time */}
                                            <td className={`px-3 py-1.5 text-center whitespace-nowrap ${DIV}`}>{formatTime(row.timestamp)}</td>

                                            {/* ── Put OI ── */}
                                            {colVis.total && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}
                                                    style={{ backgroundColor: getHeatmapBg(row.pe_oi, mx.pe_oi, isDark) }}>
                                                    <span className="text-white font-medium">{formatNumber(row.pe_oi)}</span>
                                                </td>
                                            )}
                                            {colVis.dayChange && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}
                                                    style={{ backgroundColor: getHeatmapBg(row.pe_oi_day_change, mx.pe_oi_day, isDark) }}>
                                                    <span className="text-white font-medium">{formatNumber(row.pe_oi_day_change)}</span>
                                                </td>
                                            )}
                                            {colVis.change && (
                                                <td className={`px-2 py-1.5 text-center ${DIV}`}>
                                                    <span className={getValueColor(row.pe_oi_change)}>{formatNumber(row.pe_oi_change)}</span>
                                                </td>
                                            )}

                                            {/* ── Put Volume ── */}
                                            {colVis.volume && colVis.total && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}
                                                    style={{ backgroundColor: getHeatmapBg(row.pe_volume, mx.pe_volume, isDark) }}>
                                                    <span className="text-white font-medium">{formatNumber(row.pe_volume)}</span>
                                                </td>
                                            )}
                                            {colVis.volume && colVis.change && (
                                                <td className={`px-2 py-1.5 text-center ${DIV}`}>
                                                    <span className={getValueColor(row.pe_volume_change)}>{formatNumber(row.pe_volume_change)}</span>
                                                </td>
                                            )}

                                            {/* ── Call OI ── */}
                                            {colVis.total && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}
                                                    style={{ backgroundColor: getHeatmapBg(row.ce_oi, mx.ce_oi, isDark) }}>
                                                    <span className="text-white font-medium">{formatNumber(row.ce_oi)}</span>
                                                </td>
                                            )}
                                            {colVis.dayChange && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}
                                                    style={{ backgroundColor: getHeatmapBg(row.ce_oi_day_change, mx.ce_oi_day, isDark) }}>
                                                    <span className="text-white font-medium">{formatNumber(row.ce_oi_day_change)}</span>
                                                </td>
                                            )}
                                            {colVis.change && (
                                                <td className={`px-2 py-1.5 text-center ${DIV}`}>
                                                    <span className={getValueColor(row.ce_oi_change)}>{formatNumber(row.ce_oi_change)}</span>
                                                </td>
                                            )}

                                            {/* ── Call Volume ── */}
                                            {colVis.volume && colVis.total && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}
                                                    style={{ backgroundColor: getHeatmapBg(row.ce_volume, mx.ce_volume, isDark) }}>
                                                    <span className="text-white font-medium">{formatNumber(row.ce_volume)}</span>
                                                </td>
                                            )}
                                            {colVis.volume && colVis.change && (
                                                <td className={`px-2 py-1.5 text-center ${DIV}`}>
                                                    <span className={getValueColor(row.ce_volume_change)}>{formatNumber(row.ce_volume_change)}</span>
                                                </td>
                                            )}

                                            {/* ── PE-CE OI ── */}
                                            {colVis.total && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}
                                                    style={{ backgroundColor: getHeatmapBg(row.pe_ce_oi, mx.pe_ce_oi, isDark) }}>
                                                    <span className="text-white font-medium">{formatNumber(row.pe_ce_oi)}</span>
                                                </td>
                                            )}
                                            {colVis.dayChange && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}
                                                    style={{ backgroundColor: getHeatmapBg(row.pe_ce_oi_day_change, mx.pe_ce_oi_day, isDark) }}>
                                                    <span className="text-white font-medium">{formatNumber(row.pe_ce_oi_day_change)}</span>
                                                </td>
                                            )}
                                            {colVis.change && (
                                                <td className={`px-2 py-1.5 text-center ${DIV}`}>
                                                    <span className={getValueColor(row.pe_ce_oi_change)}>{formatNumber(row.pe_ce_oi_change)}</span>
                                                </td>
                                            )}

                                            {/* ── PCR ── */}
                                            {colVis.total && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}>{row.pcr.toFixed(2)}</td>
                                            )}
                                            {colVis.dayChange && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}
                                                    style={{ backgroundColor: getHeatmapBg(row.pcr_day_change, mx.pcr_day, isDark) }}>
                                                    <span className="text-white font-medium">
                                                        {row.pcr_day_change > 0 ? '+' : ''}{row.pcr_day_change.toFixed(2)}
                                                    </span>
                                                </td>
                                            )}
                                            {colVis.change && (
                                                <td className={`px-2 py-1.5 text-center ${DIV}`}>
                                                    <span className={getValueColor(row.pcr_change)}>
                                                        {row.pcr_change > 0 ? '+' : ''}{row.pcr_change.toFixed(2)}
                                                    </span>
                                                </td>
                                            )}

                                            {/* ── Futures OI ── */}
                                            <td className={`px-2 py-1.5 text-center font-medium ${SUBDIV}`}>
                                                <span className={idx > 0 ? getValueColor(row.fut_ltp - sortedData[idx - 1].fut_ltp) : ''}>
                                                    {row.fut_ltp.toFixed(1)}
                                                </span>
                                            </td>
                                            {colVis.total && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}
                                                    style={{ backgroundColor: getHeatmapBg(row.fut_oi, mx.fut_oi, isDark) }}>
                                                    <span className="text-white font-medium">{formatNumber(row.fut_oi)}</span>
                                                </td>
                                            )}
                                            {colVis.dayChange && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}
                                                    style={{ backgroundColor: getHeatmapBg(row.fut_oi_day_change, mx.fut_oi_day, isDark) }}>
                                                    <span className="text-white font-medium">{formatNumber(row.fut_oi_day_change)}</span>
                                                </td>
                                            )}
                                            {colVis.change && (
                                                <td className={`px-2 py-1.5 text-center ${DIV}`}>
                                                    <span className={getValueColor(row.fut_oi_change)}>{formatNumber(row.fut_oi_change)}</span>
                                                </td>
                                            )}

                                            {/* ── Futures Volume ── */}
                                            {colVis.volume && colVis.total && (
                                                <td className={`px-2 py-1.5 text-center ${SUBDIV}`}
                                                    style={{ backgroundColor: getHeatmapBg(row.fut_volume, mx.fut_volume, isDark) }}>
                                                    <span className="text-white font-medium">{formatNumber(row.fut_volume)}</span>
                                                </td>
                                            )}
                                            {colVis.volume && colVis.change && (
                                                <td className={`px-2 py-1.5 text-center ${DIV}`}>
                                                    <span className={getValueColor(row.fut_volume_change)}>{formatNumber(row.fut_volume_change)}</span>
                                                </td>
                                            )}

                                            {/* ── Sentiment ── */}
                                            {colVis.sentiment && (
                                                <td className="px-2 py-1 text-center">
                                                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${getSentimentStyle(sentiment)}`}>
                                                        {sentiment}
                                                    </span>
                                                </td>
                                            )}
                                        </tr>
                                    )
                                })}
                            </tbody>
                        </table>
                    ) : (
                        <div className="flex items-center justify-center h-[500px] text-muted-foreground text-center px-6">
                            {!rawData
                                ? 'Select options and click Load to view Trending OI'
                                : !isDataSufficient
                                    ? 'Selection has changed (Underlying/Expiry/Date/Strikes). Click Load to refresh data.'
                                    : 'No data available for the selected parameters'}
                        </div>
                    )}
                </CardContent>
            </Card>
        </div>
    )
}

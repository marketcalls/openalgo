/**
 * ExpiredFnoTab — Historical data download for expired F&O contracts.
 *
 * 3-phase workflow:
 *   Phase 1 — Select underlying → Fetch Expiries (from Upstox API)
 *   Phase 2 — Select multiple expiries + contract types → Fetch Contracts
 *   Phase 3 — Configure look-back period → Start Download (background job)
 */

import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Download,
  Loader2,
  RefreshCw,
  TrendingUp,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Socket } from 'socket.io-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
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
import { showToast } from '@/utils/toast'
import {
  cancelJob,
  fetchContracts,
  fetchExpiries,
  getBrokerCapabilities,
  getContracts,
  getExpiredFnoCapability,
  getExpiredFnoStats,
  getExpiries,
  getFnoStocks,
  getJobStatus,
  listExpiredFnoJobs,
  startDownloadJob,
} from '@/api/expiredFno'
import type {
  BrokerCapabilityRow,
  ExpiredContract,
  ExpiredExpiry,
  ExpiredFnoCapability,
  ExpiredFnoJob,
  ExpiredFnoStats,
  FnoStock,
  LookBack,
} from '@/api/expiredFno'

interface Props {
  socket: Socket | null
}

const CONTRACT_TYPES = ['CE', 'PE', 'FUT'] as const
type ContractType = (typeof CONTRACT_TYPES)[number]

const LOOK_BACK_OPTIONS: { value: LookBack; label: string }[] = [
  { value: '1M', label: '1 Month' },
  { value: '3M', label: '3 Months' },
  { value: '6M', label: '6 Months' },
  { value: '1Y', label: '1 Year' },
  { value: '2Y', label: '2 Years' },
  { value: '5Y', label: '5 Years' },
]

export function ExpiredFnoTab({ socket }: Props) {
  // ── Capability ──────────────────────────────────────────────────────────
  const [capability, setCapability] = useState<ExpiredFnoCapability | null>(null)
  const [capLoading, setCapLoading] = useState(true)

  // ── Phase 1 ─────────────────────────────────────────────────────────────
  const [underlying, setUnderlying] = useState('')           // index dropdown value
  const [underlyingMode, setUnderlyingMode] = useState<'index' | 'stock'>('index')
  const [stockInput, setStockInput] = useState('')           // free-text for stocks
  const [fnoStockList, setFnoStockList] = useState<FnoStock[]>([])
  const [fnoStockListLoaded, setFnoStockListLoaded] = useState(false)
  const [stockDropdownOpen, setStockDropdownOpen] = useState(false)
  const [stockSearchQuery, setStockSearchQuery] = useState('')
  const [expiries, setExpiries] = useState<ExpiredExpiry[]>([])
  const [fetchingExpiries, setFetchingExpiries] = useState(false)

  // ── Phase 2 ─────────────────────────────────────────────────────────────
  const [selectedExpiries, setSelectedExpiries] = useState<Set<string>>(new Set())
  const [contractTypes, setContractTypes] = useState<ContractType[]>(['CE', 'PE', 'FUT'])
  const [contracts, setContracts] = useState<ExpiredContract[]>([])
  const [fetchingContracts, setFetchingContracts] = useState(false)

  // ── Phase 3 ─────────────────────────────────────────────────────────────
  const [lookBack, setLookBack] = useState<LookBack>('6M')
  const [incremental, setIncremental] = useState(true)
  const [activeJob, setActiveJob] = useState<ExpiredFnoJob | null>(null)
  const [jobPercent, setJobPercent] = useState(0)
  const [startingJob, setStartingJob] = useState(false)
  const [cancelling, setCancelling] = useState(false)

  // ── Stats ────────────────────────────────────────────────────────────────
  const [stats, setStats] = useState<ExpiredFnoStats | null>(null)

  // ── Recent jobs (persists across refresh) ────────────────────────────────
  const [recentJobs, setRecentJobs] = useState<ExpiredFnoJob[]>([])

  // ── Broker capability matrix (shown when unsupported) ────────────────────
  const [brokerMatrix, setBrokerMatrix] = useState<BrokerCapabilityRow[]>([])

  const jobPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── Clear polling interval on unmount ────────────────────────────────────
  useEffect(() => {
    return () => {
      if (jobPollRef.current) {
        clearInterval(jobPollRef.current)
        jobPollRef.current = null
      }
    }
  }, [])

  // ── Load F&O stock list when Stocks mode is active ───────────────────────
  useEffect(() => {
    if (underlyingMode === 'stock' && !fnoStockListLoaded) {
      getFnoStocks()
        .then((stocks) => {
          setFnoStockList(stocks)
          setFnoStockListLoaded(true)
        })
        .catch(() => {
          // silent fail — plain text input still works
        })
    }
  }, [underlyingMode, fnoStockListLoaded])

  // ── Load capability on mount ─────────────────────────────────────────────
  useEffect(() => {
    getExpiredFnoCapability()
      .then((cap) => {
        setCapability(cap)
        if (!cap.supported) {
          getBrokerCapabilities().then(setBrokerMatrix).catch(() => {})
        }
      })
      .catch(() => {
        setCapability({ supported: false, broker: null, note: null, supported_underlyings: [] })
        getBrokerCapabilities().then(setBrokerMatrix).catch(() => {})
      })
      .finally(() => setCapLoading(false))

    loadStats()
    loadJobs()
  }, [])

  // ── Socket.IO — listen for job progress ──────────────────────────────────
  useEffect(() => {
    if (!socket) return

    // Capture the effective underlying at the time the effect runs so the
    // callback closure always sees the current value (avoids TDZ risk when
    // effectiveUnderlying is declared later in the component body).
    const capturedUnderlying =
      underlyingMode === 'index' ? underlying : stockInput.trim().toUpperCase()

    const onProgress = (data: {
      job_id: string
      job_type: string
      percent: number
      completed: number
      failed: number
      total: number
    }) => {
      if (data.job_type !== 'expired_fno') return
      setJobPercent(data.percent)
    }

    const onComplete = (data: { job_id: string; job_type: string }) => {
      if (data.job_type !== 'expired_fno') return
      clearJobPoll()
      if (activeJob) {
        getJobStatus(activeJob.id)
          .then(({ job }) => setActiveJob(job))
          .catch(() => null)
      }
      loadStats()
      loadJobs()
      if (capturedUnderlying && selectedExpiries.size > 0) {
        loadCachedContracts(capturedUnderlying, Array.from(selectedExpiries))
      }
    }

    socket.on('historify_progress', onProgress)
    socket.on('historify_job_complete', onComplete)
    return () => {
      socket.off('historify_progress', onProgress)
      socket.off('historify_job_complete', onComplete)
    }
  }, [socket, activeJob, underlying, underlyingMode, stockInput, selectedExpiries])

  // ── Job list helpers ──────────────────────────────────────────────────────
  async function loadJobs() {
    try {
      const { jobs } = await listExpiredFnoJobs(undefined, 20)
      setRecentJobs(jobs)
      // Restore a running/pending job on page load (survives refresh)
      const running = jobs.find((j) => j.status === 'running' || j.status === 'pending')
      if (running) {
        const { job, percent } = await getJobStatus(running.id)
        setActiveJob(job)
        setJobPercent(percent)
        if (job.status === 'running' || job.status === 'pending') {
          startJobPoll(running.id)
        }
      }
    } catch {
      // non-critical
    }
  }

  // ── Helpers ──────────────────────────────────────────────────────────────
  function clearJobPoll() {
    if (jobPollRef.current) {
      clearInterval(jobPollRef.current)
      jobPollRef.current = null
    }
  }

  function startJobPoll(jobId: string) {
    clearJobPoll()
    jobPollRef.current = setInterval(async () => {
      try {
        const { job, percent } = await getJobStatus(jobId)
        setActiveJob(job)
        setJobPercent(percent)
        if (job.status !== 'running' && job.status !== 'pending') {
          clearJobPoll()
          loadStats()
        }
      } catch {
        clearJobPoll()
      }
    }, 3000)
  }

  const loadStats = useCallback(async () => {
    try {
      const s = await getExpiredFnoStats()
      setStats(s)
    } catch {
      // non-critical
    }
  }, [])

  async function loadCachedContracts(und: string, exps: string[]) {
    if (!exps.length) return
    try {
      const { contracts: c } = await getContracts(und, exps)
      setContracts(c)
    } catch {
      // non-critical
    }
  }

  // ── Phase 1 actions ──────────────────────────────────────────────────────
  async function handleFetchExpiries() {
    if (!effectiveUnderlying) return
    setFetchingExpiries(true)
    setExpiries([])
    setSelectedExpiries(new Set())
    setContracts([])
    try {
      await fetchExpiries(effectiveUnderlying)
      const { expiries: cached } = await getExpiries(effectiveUnderlying)
      setExpiries(cached)
      showToast.success(`Loaded ${cached.length} expiry dates for ${effectiveUnderlying}`)
    } catch (err: any) {
      showToast.error(err?.response?.data?.message || 'Failed to fetch expiries')
    } finally {
      setFetchingExpiries(false)
    }
  }

  // ── Phase 2 — expiry multi-select ────────────────────────────────────────
  function toggleExpiry(date: string) {
    setSelectedExpiries((prev) => {
      const next = new Set(prev)
      if (next.has(date)) next.delete(date)
      else next.add(date)
      return next
    })
    setContracts([])
  }

  function selectAllExpiries() {
    setSelectedExpiries(new Set(expiries.map((e) => e.expiry_date)))
    setContracts([])
  }

  function clearAllExpiries() {
    setSelectedExpiries(new Set())
    setContracts([])
  }

  async function handleFetchContracts() {
    if (!effectiveUnderlying || selectedExpiries.size === 0) return
    setFetchingContracts(true)
    setContracts([])
    const exps = Array.from(selectedExpiries)
    try {
      const { contract_count } = await fetchContracts(effectiveUnderlying, exps, contractTypes)
      const { contracts: cached } = await getContracts(effectiveUnderlying, exps)
      setContracts(cached)
      const newMsg = contract_count > 0 ? ` (${contract_count} new from API)` : ''
      showToast.success(`Loaded ${cached.length} contracts across ${exps.length} expir${exps.length === 1 ? 'y' : 'ies'}${newMsg}`)
    } catch (err: any) {
      showToast.error(err?.response?.data?.message || 'Failed to fetch contracts')
    } finally {
      setFetchingContracts(false)
    }
  }

  function toggleContractType(ct: ContractType) {
    setContractTypes((prev) =>
      prev.includes(ct) ? prev.filter((c) => c !== ct) : [...prev, ct]
    )
    setContracts([])
  }

  // ── Phase 3 actions ──────────────────────────────────────────────────────
  async function handleStartDownload() {
    if (!effectiveUnderlying) return
    setStartingJob(true)
    try {
      const exps = selectedExpiries.size > 0 ? Array.from(selectedExpiries) : null
      const { job_id, total_contracts } = await startDownloadJob(
        effectiveUnderlying, exps, contractTypes, lookBack, incremental
      )
      showToast.success(`Download started: ${total_contracts} contracts queued`)
      const { job, percent } = await getJobStatus(job_id)
      setActiveJob(job)
      setJobPercent(percent)
      startJobPoll(job_id)
      loadJobs()
    } catch (err: any) {
      showToast.error(err?.response?.data?.message || 'Failed to start download')
    } finally {
      setStartingJob(false)
    }
  }

  async function handleCancelJob() {
    if (!activeJob) return
    setCancelling(true)
    try {
      await cancelJob(activeJob.id)
      showToast.success('Cancellation requested')
      clearJobPoll()
    } catch (err: any) {
      showToast.error(err?.response?.data?.message || 'Failed to cancel job')
    } finally {
      setCancelling(false)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────
  if (capLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!capability?.supported) {
    return (
      <div className="space-y-4 p-2">
        <Card className="border-yellow-500/30 bg-yellow-500/5">
          <CardContent className="pt-6">
            <div className="flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-yellow-500 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium text-yellow-600 dark:text-yellow-400">
                  Upstox Required
                </p>
                <p className="text-sm text-muted-foreground mt-1">
                  Expired F&O historical data requires an{' '}
                  <strong>Upstox</strong> broker account (Plus Plan).
                  {capability?.broker && capability.broker !== 'upstox' && (
                    <span> Your current broker is <strong>{capability.broker}</strong>.</span>
                  )}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
        {brokerMatrix.length > 0 && <BrokerCapabilityMatrix rows={brokerMatrix} currentBroker={capability?.broker ?? null} />}
        {stats && <StatsCards stats={stats} />}
      </div>
    )
  }

  const effectiveUnderlying = underlyingMode === 'index' ? underlying : stockInput.trim().toUpperCase()
  const pendingContracts = contracts.filter((c) => !c.data_fetched)
  const isJobActive = activeJob?.status === 'running' || activeJob?.status === 'pending'

  return (
    <div className="space-y-4 p-2">
      {/* Stats */}
      {stats && <StatsCards stats={stats} />}

      {/* Phase 1 — Instrument Selection */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Step 1 — Select Underlying & Fetch Expiries
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-3">
            {/* Mode toggle */}
            {capability.supports_custom_underlying && (
              <div className="flex items-center gap-1 rounded-md border w-fit p-0.5">
                <button
                  onClick={() => {
                    setUnderlyingMode('index')
                    setExpiries([])
                    setSelectedExpiries(new Set())
                    setContracts([])
                  }}
                  className={`px-3 py-1 text-xs rounded-sm transition-colors ${
                    underlyingMode === 'index'
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  Indices
                </button>
                <button
                  onClick={() => {
                    setUnderlyingMode('stock')
                    setExpiries([])
                    setSelectedExpiries(new Set())
                    setContracts([])
                  }}
                  className={`px-3 py-1 text-xs rounded-sm transition-colors ${
                    underlyingMode === 'stock'
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  Stocks
                </button>
              </div>
            )}

            <div className="flex flex-wrap items-end gap-3">
              {underlyingMode === 'index' ? (
                <div className="space-y-1.5">
                  <Label>Underlying</Label>
                  <Select
                    value={underlying}
                    onValueChange={(v) => {
                      setUnderlying(v)
                      setExpiries([])
                      setSelectedExpiries(new Set())
                      setContracts([])
                    }}
                  >
                    <SelectTrigger className="w-44">
                      <SelectValue placeholder="Select..." />
                    </SelectTrigger>
                    <SelectContent>
                      {(capability.supported_underlyings || []).map((u) => (
                        <SelectItem key={u} value={u}>{u}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : (
                <div className="space-y-1.5">
                  <Label>Stock Symbol</Label>
                  <div className="relative w-44">
                    <Input
                      className="w-full uppercase"
                      placeholder="e.g. RELIANCE"
                      value={stockInput}
                      onChange={(e) => {
                        const val = e.target.value.toUpperCase()
                        setStockInput(val)
                        setStockSearchQuery(val)
                        setStockDropdownOpen(val.length > 0 && fnoStockList.length > 0)
                        setExpiries([])
                        setSelectedExpiries(new Set())
                        setContracts([])
                      }}
                      onFocus={() => {
                        if (fnoStockList.length > 0) {
                          setStockSearchQuery(stockInput)
                          setStockDropdownOpen(true)
                        }
                      }}
                      onBlur={() => setTimeout(() => setStockDropdownOpen(false), 150)}
                    />
                    {stockDropdownOpen && (
                      <div className="absolute z-50 w-full mt-1 bg-background border border-border rounded-md shadow-lg max-h-48 overflow-y-auto">
                        {fnoStockList
                          .filter((s) => s.symbol.includes(stockSearchQuery.toUpperCase()))
                          .slice(0, 20)
                          .map((s) => (
                            <div
                              key={s.symbol}
                              className="px-3 py-1.5 text-sm cursor-pointer hover:bg-accent"
                              onMouseDown={(e) => {
                                e.preventDefault()
                                setStockInput(s.symbol)
                                setStockDropdownOpen(false)
                              }}
                            >
                              {s.symbol}
                            </div>
                          ))}
                      </div>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    NSE F&O stock symbol (master contracts required)
                  </p>
                </div>
              )}
              <Button
                onClick={handleFetchExpiries}
                disabled={!effectiveUnderlying || fetchingExpiries}
                variant="outline"
                size="sm"
              >
                {fetchingExpiries ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
                ) : (
                  <RefreshCw className="h-4 w-4 mr-1.5" />
                )}
                Fetch Expiries
              </Button>
            </div>
          </div>

          {/* Multi-expiry selection */}
          {expiries.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>
                  Select Expiries
                  <span className="ml-1.5 text-xs text-muted-foreground">
                    ({selectedExpiries.size}/{expiries.length} selected)
                  </span>
                </Label>
                <div className="flex gap-2">
                  <button
                    onClick={selectAllExpiries}
                    className="text-xs text-primary underline-offset-2 hover:underline"
                  >
                    All
                  </button>
                  <span className="text-xs text-muted-foreground">·</span>
                  <button
                    onClick={clearAllExpiries}
                    className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                  >
                    None
                  </button>
                  <span className="text-xs text-muted-foreground">·</span>
                  <button
                    onClick={() => {
                      setSelectedExpiries(new Set(
                        expiries
                          .filter(e => (e.total_contracts ?? 0) === 0 || (e.downloaded_contracts ?? 0) < (e.total_contracts ?? 0))
                          .map(e => e.expiry_date)
                      ))
                    }}
                    className="text-xs text-orange-500 underline-offset-2 hover:underline"
                  >
                    Incomplete
                  </button>
                </div>
              </div>
              <ScrollArea className="h-44 rounded-md border p-2">
                <div className="space-y-1">
                  {expiries.map((e) => (
                    <div
                      key={e.expiry_date}
                      className="flex items-center gap-2.5 py-0.5 px-1 rounded hover:bg-muted/40 cursor-pointer"
                      onClick={() => toggleExpiry(e.expiry_date)}
                    >
                      <Checkbox
                        id={`exp-${e.expiry_date}`}
                        checked={selectedExpiries.has(e.expiry_date)}
                        onCheckedChange={() => toggleExpiry(e.expiry_date)}
                        onClick={(ev) => ev.stopPropagation()}
                      />
                      <label
                        htmlFor={`exp-${e.expiry_date}`}
                        className="flex items-center gap-2 text-sm cursor-pointer select-none flex-1"
                        onClick={(ev) => ev.stopPropagation()}
                      >
                        <span className="font-mono">{e.expiry_date}</span>
                        {e.is_weekly && (
                          <Badge variant="outline" className="text-xs h-4 px-1">W</Badge>
                        )}
                        {(() => {
                          const total = e.total_contracts ?? 0
                          const done = e.downloaded_contracts ?? 0
                          if (total === 0) return null
                          if (done === total)
                            return <span className="ml-auto text-xs text-green-600 font-mono tabular-nums">{done} ✓</span>
                          if (done === 0)
                            return <span className="ml-auto text-xs text-orange-500 font-mono tabular-nums">0/{total}</span>
                          return <span className="ml-auto text-xs text-yellow-600 font-mono tabular-nums">{done}/{total}</span>
                        })()}
                      </label>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Phase 2 — Contract Types & Fetch */}
      {selectedExpiries.size > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Download className="h-4 w-4" />
              Step 2 — Select Contract Types & Fetch Contracts
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-4">
              {CONTRACT_TYPES.map((ct) => (
                <div key={ct} className="flex items-center gap-2">
                  <Checkbox
                    id={`ct-${ct}`}
                    checked={contractTypes.includes(ct)}
                    onCheckedChange={() => toggleContractType(ct)}
                  />
                  <Label htmlFor={`ct-${ct}`} className="cursor-pointer">
                    {ct === 'CE' ? 'Call (CE)' : ct === 'PE' ? 'Put (PE)' : 'Futures (FUT)'}
                  </Label>
                </div>
              ))}
            </div>

            <Button
              onClick={handleFetchContracts}
              disabled={selectedExpiries.size === 0 || contractTypes.length === 0 || fetchingContracts}
              variant="outline"
              size="sm"
            >
              {fetchingContracts ? (
                <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
              ) : (
                <RefreshCw className="h-4 w-4 mr-1.5" />
              )}
              Fetch Contracts ({selectedExpiries.size} expir{selectedExpiries.size === 1 ? 'y' : 'ies'})
            </Button>

            {/* Contract table */}
            {contracts.length > 0 && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-sm text-muted-foreground">
                    {contracts.length} contracts &middot;{' '}
                    {pendingContracts.length} pending download
                  </p>
                  <Badge variant={pendingContracts.length > 0 ? 'default' : 'secondary'}>
                    {contracts.filter((c) => c.data_fetched).length} downloaded
                  </Badge>
                </div>
                <ScrollArea className="h-48 rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Symbol</TableHead>
                        <TableHead>Expiry</TableHead>
                        <TableHead>Type</TableHead>
                        <TableHead className="text-right">Strike</TableHead>
                        <TableHead className="text-right">Candles</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {contracts.map((c) => (
                        <TableRow key={c.expired_instrument_key}>
                          <TableCell className="font-mono text-xs">{c.openalgo_symbol}</TableCell>
                          <TableCell className="text-xs text-muted-foreground font-mono">
                            {c.expiry_date}
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant="outline"
                              className={
                                c.contract_type === 'CE'
                                  ? 'text-green-600 border-green-600'
                                  : c.contract_type === 'PE'
                                    ? 'text-red-600 border-red-600'
                                    : 'text-blue-600 border-blue-600'
                              }
                            >
                              {c.contract_type}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right text-sm">
                            {c.strike_price ?? '—'}
                          </TableCell>
                          <TableCell className="text-right text-sm">{c.candle_count}</TableCell>
                          <TableCell>
                            {c.data_fetched ? (
                              <CheckCircle className="h-4 w-4 text-green-500" />
                            ) : (
                              <span className="text-xs text-muted-foreground">Pending</span>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </ScrollArea>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Active job restored from server (shown even without Phase 1–2 state) */}
      {isJobActive && contracts.length === 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Download className="h-4 w-4" />
              Download in Progress
            </CardTitle>
          </CardHeader>
          <CardContent>
            <JobProgressPanel
              job={activeJob!}
              percent={jobPercent}
              onCancel={handleCancelJob}
              cancelling={cancelling}
            />
          </CardContent>
        </Card>
      )}

      {/* Recent Jobs history */}
      {recentJobs.length > 0 && !isJobActive && (
        <RecentJobsTable jobs={recentJobs.slice(0, 10)} />
      )}

      {/* Phase 3 — Download */}
      {contracts.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Download className="h-4 w-4" />
              Step 3 — Configure & Download
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Download options */}
            {!isJobActive && !activeJob && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* Look-back period */}
                <div className="space-y-1.5">
                  <Label>Look-back Period</Label>
                  <Select value={lookBack} onValueChange={(v) => setLookBack(v as LookBack)}>
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {LOOK_BACK_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* Data interval (informational) */}
                <div className="space-y-1.5">
                  <Label>Data Granularity</Label>
                  <div className="flex h-9 items-center rounded-md border bg-muted/30 px-3 text-sm gap-2">
                    <span className="font-medium">1 Minute</span>
                    <span className="text-xs text-muted-foreground">
                      (5m · 15m · 30m · 1h computed on-the-fly)
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Incremental toggle */}
            {!isJobActive && !activeJob && (
              <div
                className="flex items-center gap-2 cursor-pointer"
                onClick={() => setIncremental((v) => !v)}
              >
                <Checkbox
                  id="incremental"
                  checked={incremental}
                  onCheckedChange={(v) => setIncremental(!!v)}
                  onClick={(e) => e.stopPropagation()}
                />
                <Label htmlFor="incremental" className="cursor-pointer text-sm">
                  Only download new data after last stored timestamp
                </Label>
              </div>
            )}

            {isJobActive ? (
              <JobProgressPanel
                job={activeJob!}
                percent={jobPercent}
                onCancel={handleCancelJob}
                cancelling={cancelling}
              />
            ) : activeJob ? (
              <div className="space-y-3">
                <CompletedJobPanel job={activeJob} />
                <Button
                  onClick={() => { setActiveJob(null); setJobPercent(0) }}
                  variant="outline"
                  size="sm"
                >
                  Start New Download
                </Button>
              </div>
            ) : (
              <div className="flex items-center gap-3">
                <Button
                  onClick={handleStartDownload}
                  disabled={contracts.length === 0 || startingJob}
                  size="sm"
                >
                  {startingJob ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
                  ) : (
                    <Download className="h-4 w-4 mr-1.5" />
                  )}
                  Start Download
                  {incremental
                    ? ` (${pendingContracts.length + contracts.filter(c => c.data_fetched).length} contracts)`
                    : ` (${contracts.length} contracts)`}
                </Button>
                {incremental && pendingContracts.length === 0 && contracts.length > 0 && (
                  <p className="text-sm text-muted-foreground">
                    All downloaded — will fetch only new candles.
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatsCards({ stats }: { stats: ExpiredFnoStats }) {
  const items = [
    { label: 'Expiries Cached', value: stats.total_expiries },
    { label: 'Contracts Cached', value: stats.total_contracts },
    { label: 'Downloaded', value: stats.downloaded_contracts },
    { label: 'Total Candles', value: stats.total_candles.toLocaleString() },
  ]
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {items.map(({ label, value }) => (
        <Card key={label}>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="text-lg font-semibold mt-0.5">{value}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function JobProgressPanel({
  job,
  percent,
  onCancel,
  cancelling,
}: {
  job: ExpiredFnoJob
  percent: number
  onCancel: () => void
  cancelling: boolean
}) {
  const expirySummary = job.expiry_date
    ? job.expiry_date.includes('|')
      ? `${job.expiry_date.split('|').length} expiries`
      : job.expiry_date
    : 'all expiries'

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium">
            Downloading {job.underlying} — {expirySummary}
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {job.completed_contracts} completed &middot; {job.failed_contracts} failed &middot; {job.total_contracts} total
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onCancel}
          disabled={cancelling}
          className="text-destructive hover:text-destructive"
        >
          {cancelling ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <X className="h-4 w-4 mr-1" />
          )}
          Cancel
        </Button>
      </div>
      <Progress value={percent} className="h-2" />
      <p className="text-xs text-muted-foreground text-right">{percent}%</p>
    </div>
  )
}

function CompletedJobPanel({ job }: { job: ExpiredFnoJob }) {
  const isSuccess = job.status === 'completed'
  return (
    <div className="flex items-start gap-3 rounded-md border p-3">
      {isSuccess ? (
        <CheckCircle className="h-5 w-5 text-green-500 shrink-0 mt-0.5" />
      ) : (
        <AlertTriangle className="h-5 w-5 text-yellow-500 shrink-0 mt-0.5" />
      )}
      <div>
        <p className="text-sm font-medium capitalize">{job.status}</p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {job.completed_contracts} downloaded &middot; {job.failed_contracts} failed &middot; {job.total_contracts} total
        </p>
        {job.error_message && (
          <p className="text-xs text-destructive mt-1">{job.error_message}</p>
        )}
      </div>
    </div>
  )
}

// ── Recent Jobs Table ──────────────────────────────────────────────────────────

const JOB_STATUS_STYLE: Record<string, string> = {
  completed: 'text-green-600 dark:text-green-400',
  running:   'text-blue-600 dark:text-blue-400',
  pending:   'text-yellow-600 dark:text-yellow-400',
  failed:    'text-destructive',
  cancelled: 'text-muted-foreground',
}

function formatDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt) return '—'
  const start = new Date(startedAt).getTime()
  const end = completedAt ? new Date(completedAt).getTime() : Date.now()
  const secs = Math.round((end - start) / 1000)
  if (secs < 60) return `${secs}s`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`
}

function RecentJobsTable({ jobs }: { jobs: ExpiredFnoJob[] }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Clock className="h-4 w-4" />
          Recent Download Jobs
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Underlying</TableHead>
                <TableHead>Types</TableHead>
                <TableHead>Interval</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Progress</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.map((job) => {
                const expirySummary = job.expiry_date
                  ? job.expiry_date.includes('|')
                    ? `${job.expiry_date.split('|').length} expiries`
                    : job.expiry_date
                  : 'all'
                const types = job.contract_types ?? '—'
                const statusStyle = JOB_STATUS_STYLE[job.status] ?? 'text-muted-foreground'
                const progress = job.total_contracts > 0
                  ? `${job.completed_contracts}/${job.total_contracts}`
                  : '—'
                const startedAt = job.started_at
                  ? new Date(job.started_at).toLocaleString(undefined, {
                      month: 'short', day: 'numeric',
                      hour: '2-digit', minute: '2-digit',
                    })
                  : '—'
                return (
                  <TableRow key={job.id}>
                    <TableCell className="pl-4 font-medium">
                      {job.underlying}
                      <span className="ml-1.5 text-xs text-muted-foreground font-normal">
                        ({expirySummary})
                      </span>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{types}</TableCell>
                    <TableCell className="text-xs font-mono">{job.interval}</TableCell>
                    <TableCell className={`text-xs font-medium capitalize ${statusStyle}`}>
                      {job.status}
                    </TableCell>
                    <TableCell className="text-right text-xs">{progress}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{startedAt}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDuration(job.started_at, job.completed_at)}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

// ── Broker Capability Matrix ───────────────────────────────────────────────────

const CAP_LABEL: Record<string, { label: string; className: string }> = {
  full:    { label: '✅ Full',    className: 'text-green-600 dark:text-green-400' },
  limited: { label: '⚠️ Limited', className: 'text-yellow-600 dark:text-yellow-400' },
  none:    { label: '❌ None',    className: 'text-muted-foreground' },
}

function BrokerCapabilityMatrix({
  rows,
  currentBroker,
}: {
  rows: BrokerCapabilityRow[]
  currentBroker: string | null
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          Broker Historical Data Support
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Broker</TableHead>
                <TableHead>Futures Historical</TableHead>
                <TableHead>Options Historical</TableHead>
                <TableHead>Expired Contracts</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(({ broker, capabilities }) => {
                const isCurrent = broker === currentBroker
                return (
                  <TableRow key={broker} className={isCurrent ? 'bg-muted/50' : undefined}>
                    <TableCell className="pl-4 font-medium capitalize">
                      {broker}
                      {isCurrent && (
                        <Badge variant="outline" className="ml-2 text-xs">current</Badge>
                      )}
                    </TableCell>
                    <TableCell className={CAP_LABEL[capabilities.futures_historical]?.className}>
                      {CAP_LABEL[capabilities.futures_historical]?.label ?? '—'}
                    </TableCell>
                    <TableCell className={CAP_LABEL[capabilities.options_historical]?.className}>
                      {CAP_LABEL[capabilities.options_historical]?.label ?? '—'}
                    </TableCell>
                    <TableCell className={CAP_LABEL[capabilities.expired_contracts]?.className}>
                      {CAP_LABEL[capabilities.expired_contracts]?.label ?? '—'}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

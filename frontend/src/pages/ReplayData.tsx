import {
  AlertTriangle,
  Clock,
  Database,
  FastForward,
  FileUp,
  Loader2,
  Pause,
  Play,
  Radio,
  Square,
  Upload,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { showToast } from '@/utils/toast'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { type PaperPriceSource, useSandboxStore } from '@/stores/sandboxStore'

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token
}

interface UploadStats {
  status: string
  message?: string
  upload_type?: string
  rows_upserted?: number
  symbols_count?: number
  min_timestamp?: number | null
  max_timestamp?: number | null
  errors?: string[]
  files_processed?: number
}

interface ReplayState {
  enabled: boolean
  status: string
  current_ts: number | null
  start_ts: number | null
  end_ts: number | null
  speed: number
  universe_mode: string
}

const UPLOAD_TYPES = [
  {
    key: 'CM_BHAVCOPY',
    title: 'CM Bhavcopy (Equity)',
    description: 'NSE Cash Market daily bhavcopy ZIP. Contains SYMBOL, OPEN, HIGH, LOW, CLOSE, VOLUME data for equity.',
    icon: Database,
  },
  {
    key: 'FO_BHAVCOPY',
    title: 'FO Bhavcopy (F&O)',
    description: 'NSE F&O daily bhavcopy ZIP. Contains futures/options OHLCV + OI data.',
    icon: Database,
  },
  {
    key: 'INTRADAY_1M',
    title: 'Intraday 1-Min',
    description: 'ZIP with 1-minute OHLCV CSVs. Columns: timestamp, symbol, exchange, open, high, low, close, volume, oi.',
    icon: Clock,
  },
]

const SPEED_OPTIONS = [
  { value: '1', label: '1x (1 min/sec)' },
  { value: '5', label: '5x' },
  { value: '10', label: '10x' },
  { value: '30', label: '30x' },
  { value: '60', label: '60x (1 hr/sec)' },
  { value: '300', label: '300x (5 hr/sec)' },
]

function formatEpoch(epoch: number | null): string {
  if (!epoch) return '—'
  const d = new Date(epoch * 1000)
  return d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })
}

function epochToDateInput(epoch: number | null): string {
  if (!epoch) return ''
  const d = new Date(epoch * 1000)
  // Format as YYYY-MM-DDTHH:mm for datetime-local input
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function dateInputToEpoch(val: string): number | null {
  if (!val) return null
  const d = new Date(val)
  if (Number.isNaN(d.getTime())) return null
  return Math.floor(d.getTime() / 1000)
}

export default function ReplayData() {
  // Upload state
  const [uploading, setUploading] = useState<string | null>(null)
  const [uploadResults, setUploadResults] = useState<Record<string, UploadStats>>({})
  const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({})

  // Replay state
  const [replay, setReplay] = useState<ReplayState>({
    enabled: false,
    status: 'stopped',
    current_ts: null,
    start_ts: null,
    end_ts: null,
    speed: 1,
    universe_mode: 'all',
  })
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [speed, setSpeed] = useState('1')
  const [replayLoading, setReplayLoading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Paper price source
  const { paperPriceSource, isFetchingSource, isSettingSource, fetchPaperPriceSource, setPaperPriceSource } =
    useSandboxStore()

  // Fetch replay status
  const fetchReplayStatus = useCallback(async () => {
    try {
      const response = await fetch('/replay/api/replay/status', { credentials: 'include' })
      if (response.ok) {
        const data = await response.json()
        if (data.status === 'success' && data.replay) {
          setReplay(data.replay)
        }
      }
    } catch {
      // Silently fail
    }
  }, [])

  useEffect(() => {
    fetchReplayStatus()
    fetchPaperPriceSource()
  }, [fetchReplayStatus, fetchPaperPriceSource])

  // Poll when running
  useEffect(() => {
    if (replay.status === 'running') {
      pollRef.current = setInterval(fetchReplayStatus, 1000)
    } else {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [replay.status, fetchReplayStatus])

  // Price source toggle
  const handlePriceSourceToggle = async (newSource: PaperPriceSource) => {
    const csrfToken = await fetchCSRFToken()
    const result = await setPaperPriceSource(newSource, csrfToken)
    if (result.success) {
      showToast.success(result.message || `Price source set to ${newSource}`)
    } else {
      showToast.error(result.message || 'Failed to update price source')
    }
  }

  // Upload handler
  const handleUpload = async (uploadType: string) => {
    const input = fileInputRefs.current[uploadType]
    if (!input?.files?.length) {
      showToast.error('Please select a ZIP file first')
      return
    }

    setUploading(uploadType)
    try {
      const csrfToken = await fetchCSRFToken()
      const formData = new FormData()
      formData.append('file', input.files[0])
      formData.append('upload_type', uploadType)

      const response = await fetch('/replay/api/upload', {
        method: 'POST',
        credentials: 'include',
        headers: { 'X-CSRFToken': csrfToken },
        body: formData,
      })

      const result: UploadStats = await response.json()
      setUploadResults((prev) => ({ ...prev, [uploadType]: result }))

      if (result.status === 'success') {
        showToast.success(result.message || 'Upload successful')
      } else {
        showToast.error(result.message || 'Upload failed')
      }
    } catch (error) {
      showToast.error('Upload failed')
    } finally {
      setUploading(null)
      if (input) input.value = ''
    }
  }

  // Replay controls
  const replayAction = async (
    endpoint: string,
    method: 'GET' | 'POST' = 'POST',
    body?: Record<string, unknown>,
  ) => {
    setReplayLoading(true)
    try {
      const csrfToken = method === 'POST' ? await fetchCSRFToken() : ''
      const options: RequestInit = {
        method,
        credentials: 'include',
        headers: {
          ...(method === 'POST' ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      }
      const response = await fetch(endpoint, options)
      const data = await response.json()

      if (data.replay) setReplay(data.replay)
      if (data.status === 'success') {
        if (data.message) showToast.success(data.message)
      } else {
        showToast.error(data.message || 'Action failed')
      }
    } catch {
      showToast.error('Action failed')
    } finally {
      setReplayLoading(false)
    }
  }

  const handleConfigure = () => {
    const start_ts = dateInputToEpoch(startDate)
    const end_ts = dateInputToEpoch(endDate)
    if (!start_ts || !end_ts) {
      showToast.error('Please set valid start and end dates')
      return
    }
    replayAction('/replay/api/replay/config', 'POST', {
      start_ts,
      end_ts,
      speed: Number.parseFloat(speed),
    })
  }

  return (
    <div className="container mx-auto p-4 space-y-6 max-w-5xl">
      <div className="flex items-center gap-2 mb-4">
        <Database className="h-6 w-6" />
        <h1 className="text-2xl font-bold">Replay Data Manager</h1>
      </div>

      {/* Paper Price Source Toggle */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Radio className="h-4 w-4" />
            Paper Trading Price Source
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Controls which price feed the sandbox uses for order fills and MTM.
            Switch to <strong>Replay</strong> to use uploaded historical data instead of live broker quotes.
          </p>
          <div className="flex gap-2">
            {(['LIVE', 'REPLAY'] as PaperPriceSource[]).map((src) => (
              <Button
                key={src}
                size="sm"
                variant={paperPriceSource === src ? 'default' : 'outline'}
                onClick={() => handlePriceSourceToggle(src)}
                disabled={isFetchingSource || isSettingSource || paperPriceSource === src}
              >
                {isSettingSource && paperPriceSource !== src ? (
                  <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                ) : null}
                {src === 'LIVE' ? '📡 Live Quotes' : '🎞️ Replay Data'}
              </Button>
            ))}
          </div>

          {/* Warning: REPLAY selected but clock not running */}
          {paperPriceSource === 'REPLAY' && replay.status !== 'running' && (
            <Alert variant="destructive" className="py-2">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription className="text-xs">
                Price source is set to <strong>Replay</strong> but the replay clock is{' '}
                <strong>{replay.status}</strong>. Orders will remain pending until you configure
                a date range and press <em>Start</em> below.
              </AlertDescription>
            </Alert>
          )}

          {paperPriceSource === 'REPLAY' && replay.status === 'running' && (
            <div className="text-xs text-green-600 dark:text-green-400 flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Replay running — quotes sourced from DuckDB at {formatEpoch(replay.current_ts)}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Upload Section */}
      <div>
        <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
          <Upload className="h-5 w-5" />
          Upload Market Data
        </h2>
        <div className="grid gap-4 md:grid-cols-3">
          {UPLOAD_TYPES.map(({ key, title, description, icon: Icon }) => {
            const result = uploadResults[key]
            const isUploading = uploading === key
            return (
              <Card key={key}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Icon className="h-4 w-4" />
                    {title}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <p className="text-xs text-muted-foreground">{description}</p>
                  <Input
                    type="file"
                    accept=".zip"
                    ref={(el) => { fileInputRefs.current[key] = el }}
                    disabled={isUploading}
                    className="text-xs"
                  />
                  <Button
                    size="sm"
                    className="w-full"
                    onClick={() => handleUpload(key)}
                    disabled={isUploading}
                  >
                    {isUploading ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                        Importing...
                      </>
                    ) : (
                      <>
                        <FileUp className="h-4 w-4 mr-1" />
                        Upload & Import
                      </>
                    )}
                  </Button>
                  {result && (
                    <div className={`text-xs p-2 rounded ${result.status === 'success' ? 'bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-300' : 'bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300'}`}>
                      <p className="font-medium">{result.message}</p>
                      {result.rows_upserted !== undefined && (
                        <p>Rows: {result.rows_upserted} | Symbols: {result.symbols_count}</p>
                      )}
                      {result.min_timestamp && (
                        <p className="text-[10px]">
                          Range: {formatEpoch(result.min_timestamp)} — {formatEpoch(result.max_timestamp ?? null)}
                        </p>
                      )}
                      {result.errors && result.errors.length > 0 && (
                        <details className="mt-1">
                          <summary className="cursor-pointer text-[10px]">
                            {result.errors.length} warning(s)
                          </summary>
                          <ul className="list-disc pl-3 text-[10px]">
                            {result.errors.map((err, i) => (
                              <li key={`err-${key}-${i}`}>{err}</li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      </div>

      {/* Replay Controller */}
      <div>
        <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
          <Play className="h-5 w-5" />
          Replay Controller
        </h2>
        <Card>
          <CardContent className="pt-6 space-y-4">
            {/* Status */}
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-sm font-medium">Status:</span>
              <span
                className={`text-sm font-bold px-2 py-0.5 rounded ${
                  replay.status === 'running'
                    ? 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300'
                    : replay.status === 'paused'
                      ? 'bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400'
                }`}
              >
                {replay.status.toUpperCase()}
              </span>
              {replay.current_ts && (
                <span className="text-sm text-muted-foreground ml-2">
                  <Clock className="h-3 w-3 inline mr-1" />
                  {formatEpoch(replay.current_ts)}
                </span>
              )}
            </div>

            {/* Configuration */}
            <div className="grid gap-3 md:grid-cols-4">
              <div>
                <Label className="text-xs">Start Date/Time</Label>
                <Input
                  type="datetime-local"
                  value={startDate || epochToDateInput(replay.start_ts)}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="text-xs"
                />
              </div>
              <div>
                <Label className="text-xs">End Date/Time</Label>
                <Input
                  type="datetime-local"
                  value={endDate || epochToDateInput(replay.end_ts)}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="text-xs"
                />
              </div>
              <div>
                <Label className="text-xs">Speed</Label>
                <Select value={speed} onValueChange={setSpeed}>
                  <SelectTrigger className="text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SPEED_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-end">
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full"
                  onClick={handleConfigure}
                  disabled={replayLoading}
                >
                  <FastForward className="h-4 w-4 mr-1" />
                  Configure
                </Button>
              </div>
            </div>

            {/* Playback controls */}
            <div className="flex items-center gap-2 pt-2 flex-wrap">
              <Button
                size="sm"
                onClick={() => replayAction('/replay/api/replay/start')}
                disabled={replayLoading || replay.status === 'running'}
              >
                <Play className="h-4 w-4 mr-1" />
                {replay.status === 'paused' ? 'Resume' : 'Start'}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => replayAction('/replay/api/replay/pause')}
                disabled={replayLoading || replay.status !== 'running'}
              >
                <Pause className="h-4 w-4 mr-1" />
                Pause
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => replayAction('/replay/api/replay/stop')}
                disabled={replayLoading || replay.status === 'stopped'}
              >
                <Square className="h-4 w-4 mr-1" />
                Stop
              </Button>
              {replay.start_ts && replay.end_ts && (
                <div className="flex items-center gap-2 ml-4 flex-1 min-w-[200px]">
                  <span className="text-xs text-muted-foreground whitespace-nowrap">Seek:</span>
                  <input
                    type="range"
                    min={replay.start_ts}
                    max={replay.end_ts}
                    value={replay.current_ts ?? replay.start_ts}
                    onChange={(e) => {
                      replayAction('/replay/api/replay/seek', 'POST', {
                        target_ts: Number.parseInt(e.target.value),
                      })
                    }}
                    className="flex-1"
                    disabled={replay.status === 'stopped'}
                  />
                </div>
              )}
            </div>

            {/* Info */}
            {replay.start_ts && replay.end_ts && (
              <div className="text-xs text-muted-foreground grid grid-cols-2 gap-1">
                <span>Start: {formatEpoch(replay.start_ts)}</span>
                <span>End: {formatEpoch(replay.end_ts)}</span>
                <span>Speed: {replay.speed}x (1 min = {(1 / replay.speed).toFixed(2)}s real)</span>
                <span>Mode: {replay.universe_mode}</span>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

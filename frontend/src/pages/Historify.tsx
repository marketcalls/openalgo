import {
  BarChart3,
  BookOpen,
  CheckCircle,
  Database,
  DownloadCloud,
  FileDown,
  HardDrive,
  Home,
  LineChart,
  ListPlus,
  Loader2,
  LogOut,
  Moon,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Settings,
  Square,
  Sun,
  Target,
  Trash2,
  TrendingUp,
  Upload,
  X,
  XCircle,
  Zap,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { showToast } from '@/utils/toast'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Switch } from '@/components/ui/switch'
import { useSocket } from '@/hooks/useSocket'
import { cn } from '@/lib/utils'
import { profileMenuItems } from '@/config/navigation'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'

// Types
interface SearchResult {
  symbol: string
  name: string
  exchange: string
  token: string
}

interface WatchlistItem {
  id: number
  symbol: string
  exchange: string
  display_name?: string
  added_at: string
}

interface CatalogItem {
  symbol: string
  exchange: string
  interval: string
  first_timestamp: number
  last_timestamp: number
  record_count: number
  first_date?: string
  last_date?: string
}

// Grouped catalog item - groups all intervals for a symbol
interface GroupedCatalogItem {
  symbol: string
  exchange: string
  intervals: {
    interval: string
    record_count: number
    first_date?: string
    last_date?: string
  }[]
  total_records: number
  earliest_date?: string
  latest_date?: string
}

interface IntervalData {
  seconds: string[]
  minutes: string[]
  hours: string[]
  days: string[]
  weeks: string[]
  months: string[]
}

// FNOSymbol interface (will be used when FNO Discovery is enabled)
// interface FNOSymbol {
//   symbol: string
//   name: string
//   exchange: string
//   token: string
//   expiry?: string
//   strike?: number
//   lotsize?: number
//   instrumenttype?: string
//   tick_size?: number
// }

interface DownloadJob {
  id: string
  job_type: string
  status: 'pending' | 'running' | 'paused' | 'completed' | 'completed_with_errors' | 'failed' | 'cancelled'
  total_symbols: number
  completed_symbols: number
  failed_symbols: number
  interval: string
  start_date: string
  end_date: string
  config?: string
  created_at: string
  started_at?: string
  completed_at?: string
  error_message?: string
}

interface JobProgress {
  job_id: string
  current: number
  total: number
  symbol: string
  percent: number
}

interface Stats {
  database_size_mb: number
  total_records: number
  total_symbols: number
  watchlist_count: number
}

interface Schedule {
  id: string
  name: string
  description?: string
  schedule_type: 'interval' | 'daily'
  interval_value?: number
  interval_unit?: 'minutes' | 'hours'
  time_of_day?: string
  download_source?: 'watchlist'  // Always watchlist, kept for API compatibility
  data_interval: '1m' | 'D'
  lookback_days: number
  is_enabled: boolean
  is_paused: boolean
  status: 'idle' | 'running' | 'error'
  apscheduler_job_id?: string
  created_at: string
  last_run_at?: string
  next_run_at?: string
  last_run_status?: string
  total_runs: number
  successful_runs: number
  failed_runs: number
}

interface ScheduleExecution {
  id: number
  schedule_id: string
  download_job_id?: string
  status: 'running' | 'completed' | 'failed'
  started_at: string
  completed_at?: string
  symbols_processed: number
  symbols_success: number
  symbols_failed: number
  records_downloaded: number
  error_message?: string
}

// Helper functions
async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token
}

// Date range presets
const DATE_PRESETS = [
  { label: '1M', months: 1 },
  { label: '3M', months: 3 },
  { label: '6M', months: 6 },
  { label: '1Y', months: 12 },
  { label: '2Y', months: 24 },
  { label: '5Y', months: 60 },
]

function getDateFromPreset(months: number): string {
  const d = new Date()
  d.setMonth(d.getMonth() - months)
  return d.toISOString().split('T')[0]
}

export default function Historify() {
  const { appMode, toggleAppMode, mode, toggleMode, isTogglingMode } = useThemeStore()
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  // Core state
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([])
  const [catalog, setCatalog] = useState<CatalogItem[]>([])
  const [_intervals, setIntervals] = useState<IntervalData | null>(null)
  const [historifyIntervals, setHistorifyIntervals] = useState<{
    storage_intervals: string[]
    computed_intervals: string[]
    all_intervals: string[]
  } | null>(null)
  const [exchanges, setExchanges] = useState<string[]>(['NSE', 'BSE', 'NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NSE_INDEX', 'BSE_INDEX'])
  const [stats, setStats] = useState<Stats>({ database_size_mb: 0, total_records: 0, total_symbols: 0, watchlist_count: 0 })

  // Tab state
  const [activeTab, setActiveTab] = useState<string>('watchlist')

  // Symbol search state
  const [newSymbol, setNewSymbol] = useState('')
  const [newExchange, setNewExchange] = useState('NSE')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [showSearchResults, setShowSearchResults] = useState(false)
  const searchContainerRef = useRef<HTMLDivElement>(null)

  // Download settings
  const [selectedInterval, setSelectedInterval] = useState<string>('D')
  const [startDate, setStartDate] = useState(() => getDateFromPreset(1))
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split('T')[0])
  const [incrementalDownload, setIncrementalDownload] = useState(false)

  // FNO Discovery state (disabled for now - will be added later)
  // const [fnoExchange, setFnoExchange] = useState<string>('NFO')
  // const [fnoUnderlyings, setFnoUnderlyings] = useState<string[]>([])
  // const [fnoSelectedUnderlying, setFnoSelectedUnderlying] = useState<string>('')
  // const [fnoExpiries, setFnoExpiries] = useState<string[]>([])
  // const [fnoSelectedExpiry, setFnoSelectedExpiry] = useState<string>('')
  // const [fnoInstrumentType, setFnoInstrumentType] = useState<string>('__all__')
  // const [fnoStrikeMin, setFnoStrikeMin] = useState<string>('')
  // const [fnoStrikeMax, setFnoStrikeMax] = useState<string>('')
  // const [fnoSymbols, setFnoSymbols] = useState<FNOSymbol[]>([])
  // const [fnoSelectedSymbols, setFnoSelectedSymbols] = useState<Set<string>>(new Set())
  // const [fnoLoading, setFnoLoading] = useState(false)

  // Job management state
  const [jobs, setJobs] = useState<DownloadJob[]>([])
  const [selectedJob, setSelectedJob] = useState<DownloadJob | null>(null)
  const [jobProgress, setJobProgress] = useState<Record<string, JobProgress>>({})
  const [jobsLoading, setJobsLoading] = useState(false)

  // Scheduler state
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [schedulesLoading, setSchedulesLoading] = useState(false)
  const [scheduleDialogOpen, setScheduleDialogOpen] = useState(false)
  const [editingSchedule, setEditingSchedule] = useState<Schedule | null>(null)
  const [scheduleExecutions, setScheduleExecutions] = useState<Record<string, ScheduleExecution[]>>({})
  const [expandedSchedule, setExpandedSchedule] = useState<string | null>(null)

  // Schedule form state
  const [scheduleName, setScheduleName] = useState('')
  const [scheduleDescription, setScheduleDescription] = useState('')
  const [scheduleType, setScheduleType] = useState<'interval' | 'daily'>('daily')
  const [scheduleIntervalValue, setScheduleIntervalValue] = useState(5)
  const [scheduleIntervalUnit, setScheduleIntervalUnit] = useState<'minutes' | 'hours'>('minutes')
  const [scheduleTimeOfDay, setScheduleTimeOfDay] = useState('09:15')
  const [scheduleDataInterval, setScheduleDataInterval] = useState<'1m' | 'D'>('D')
  const [scheduleLookbackDays, setScheduleLookbackDays] = useState(1)
  const [isCreatingSchedule, setIsCreatingSchedule] = useState(false)

  // Dialog states
  const [bulkAddDialogOpen, setBulkAddDialogOpen] = useState(false)
  const [bulkAddText, setBulkAddText] = useState('')
  const [isBulkAdding, setIsBulkAdding] = useState(false)
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false)
  const [uploadSymbol, setUploadSymbol] = useState('')
  const [uploadExchange, setUploadExchange] = useState('NSE')
  const [uploadInterval, setUploadInterval] = useState('D')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<{ symbol: string; exchange: string; interval?: string } | null>(null)
  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false)
  const [isBulkDeleting, setIsBulkDeleting] = useState(false)
  const [bulkWatchlistDeleteDialogOpen, setBulkWatchlistDeleteDialogOpen] = useState(false)
  const [isBulkWatchlistDeleting, setIsBulkWatchlistDeleting] = useState(false)

  // Export dialog state
  const [exportDialogOpen, setExportDialogOpen] = useState(false)
  const [exportFormat, setExportFormat] = useState<'csv' | 'txt' | 'zip' | 'parquet'>('csv')
  const [exportSymbols, setExportSymbols] = useState<'all' | 'selected'>('all')
  const [exportIntervals, setExportIntervals] = useState<Set<string>>(new Set(['D']))  // Multi-select intervals
  const [catalogSelectedSymbols, setCatalogSelectedSymbols] = useState<Set<string>>(new Set())
  const [isExporting, setIsExporting] = useState(false)

  // Custom export interval state
  const [customExportValue, setCustomExportValue] = useState('25')
  const [customExportUnit, setCustomExportUnit] = useState<'m' | 'h' | 'W' | 'M' | 'Q' | 'Y'>('m')

  // Watchlist selection state (for downloading specific symbols)
  const [watchlistSelectedSymbols, setWatchlistSelectedSymbols] = useState<Set<string>>(new Set())

  // Catalog filtering
  const [catalogFilter, setCatalogFilter] = useState({ exchange: '', interval: '', search: '' })

  // Socket.IO for real-time progress
  const { socket } = useSocket()

  // Computed values (allIntervals not needed for now since we use storage_intervals)
  // const allIntervals = intervals
  //   ? [...intervals.seconds, ...intervals.minutes, ...intervals.hours, ...intervals.days, ...intervals.weeks, ...intervals.months]
  //   : ['D']

  // Group catalog by symbol+exchange to show unique symbols with all their intervals
  const groupedCatalog = useMemo((): GroupedCatalogItem[] => {
    const groups = new Map<string, GroupedCatalogItem>()

    for (const item of catalog) {
      const key = `${item.symbol}:${item.exchange}`

      if (!groups.has(key)) {
        groups.set(key, {
          symbol: item.symbol,
          exchange: item.exchange,
          intervals: [],
          total_records: 0,
          earliest_date: item.first_date,
          latest_date: item.last_date,
        })
      }

      const group = groups.get(key)!
      group.intervals.push({
        interval: item.interval,
        record_count: item.record_count,
        first_date: item.first_date,
        last_date: item.last_date,
      })
      group.total_records += item.record_count

      // Update date range
      if (item.first_date && (!group.earliest_date || item.first_date < group.earliest_date)) {
        group.earliest_date = item.first_date
      }
      if (item.last_date && (!group.latest_date || item.last_date > group.latest_date)) {
        group.latest_date = item.last_date
      }
    }

    // Sort intervals within each group
    for (const group of groups.values()) {
      group.intervals.sort((a, b) => {
        const order = ['1m', '5m', '15m', '30m', '1h', 'D', 'W', 'M']
        return order.indexOf(a.interval) - order.indexOf(b.interval)
      })
    }

    return Array.from(groups.values()).sort((a, b) => a.symbol.localeCompare(b.symbol))
  }, [catalog])

  // Filter grouped catalog
  const filteredGroupedCatalog = useMemo(() => {
    return groupedCatalog.filter((item) => {
      if (catalogFilter.exchange && catalogFilter.exchange !== '__all__' && item.exchange !== catalogFilter.exchange) return false
      if (catalogFilter.interval && catalogFilter.interval !== '__all__') {
        // Show symbols that have the selected interval
        if (!item.intervals.some((i) => i.interval === catalogFilter.interval)) return false
      }
      if (catalogFilter.search && !item.symbol.toLowerCase().includes(catalogFilter.search.toLowerCase())) return false
      return true
    })
  }, [groupedCatalog, catalogFilter])

  // Note: filteredCatalog not currently used - export uses catalogSelectedSymbols directly
  // const filteredCatalog = useMemo(() => {
  //   return catalog.filter((item) => {
  //     if (catalogFilter.exchange && catalogFilter.exchange !== '__all__' && item.exchange !== catalogFilter.exchange) return false
  //     if (catalogFilter.interval && catalogFilter.interval !== '__all__' && item.interval !== catalogFilter.interval) return false
  //     if (catalogFilter.search && !item.symbol.toLowerCase().includes(catalogFilter.search.toLowerCase())) return false
  //     return true
  //   })
  // }, [catalog, catalogFilter])

  // Load data on mount
  useEffect(() => {
    loadWatchlist()
    loadCatalog()
    loadIntervals()
    loadHistorifyIntervals()
    loadStats()
    loadExchanges()
    loadJobs()
    loadSchedules()
  }, [])

  // Socket.IO event handlers
  useEffect(() => {
    if (!socket) return

    const handleProgress = (data: JobProgress) => {
      setJobProgress((prev) => ({ ...prev, [data.job_id]: data }))
      setJobs((prevJobs) =>
        prevJobs.map((job) =>
          job.id === data.job_id ? { ...job, completed_symbols: data.current, status: 'running' } : job
        )
      )
    }

    const handleJobComplete = (data: { job_id: string; completed: number; failed: number; status: string }) => {
      setJobProgress((prev) => {
        const newProgress = { ...prev }
        delete newProgress[data.job_id]
        return newProgress
      })
      loadJobs()
      loadCatalog()
      loadStats()
      showToast.success(`Job completed: ${data.completed} success, ${data.failed} failed`, 'historify')
    }

    const handleJobPaused = (data: { job_id: string }) => {
      setJobs((prevJobs) =>
        prevJobs.map((job) => (job.id === data.job_id ? { ...job, status: 'paused' } : job))
      )
    }

    const handleJobCancelled = (data: { job_id: string }) => {
      setJobs((prevJobs) =>
        prevJobs.map((job) => (job.id === data.job_id ? { ...job, status: 'cancelled' } : job))
      )
      // Clear progress for cancelled job
      setJobProgress((prev) => {
        const newProgress = { ...prev }
        delete newProgress[data.job_id]
        return newProgress
      })
      showToast.info('Job cancelled', 'historify')
    }

    socket.on('historify_progress', handleProgress)
    socket.on('historify_job_complete', handleJobComplete)
    socket.on('historify_job_paused', handleJobPaused)
    socket.on('historify_job_cancelled', handleJobCancelled)

    // Scheduler event handlers
    const handleScheduleUpdated = () => {
      loadSchedules()
    }

    const handleScheduleExecutionStarted = (data: { schedule_id: string; execution_id: number; job_id: string }) => {
      showToast.info(`Schedule execution started`, 'historify')
      loadSchedules()
      loadJobs()
      if (expandedSchedule === data.schedule_id) {
        loadScheduleExecutions(data.schedule_id)
      }
    }

    const handleScheduleExecutionComplete = (data: { schedule_id: string; execution_id: number; status: string }) => {
      loadSchedules()
      if (expandedSchedule === data.schedule_id) {
        loadScheduleExecutions(data.schedule_id)
      }
    }

    socket.on('historify_schedule_created', handleScheduleUpdated)
    socket.on('historify_schedule_updated', handleScheduleUpdated)
    socket.on('historify_schedule_deleted', handleScheduleUpdated)
    socket.on('historify_schedule_execution_started', handleScheduleExecutionStarted)
    socket.on('historify_schedule_execution_complete', handleScheduleExecutionComplete)

    return () => {
      socket.off('historify_progress', handleProgress)
      socket.off('historify_job_complete', handleJobComplete)
      socket.off('historify_job_paused', handleJobPaused)
      socket.off('historify_job_cancelled', handleJobCancelled)
      socket.off('historify_schedule_created', handleScheduleUpdated)
      socket.off('historify_schedule_updated', handleScheduleUpdated)
      socket.off('historify_schedule_deleted', handleScheduleUpdated)
      socket.off('historify_schedule_execution_started', handleScheduleExecutionStarted)
      socket.off('historify_schedule_execution_complete', handleScheduleExecutionComplete)
    }
  }, [socket, expandedSchedule])

  // FNO data loading (disabled for now)
  // useEffect(() => {
  //   if (fnoExchange) loadFnoUnderlyings()
  // }, [fnoExchange])

  // useEffect(() => {
  //   if (fnoSelectedUnderlying && fnoExchange) loadFnoExpiries()
  // }, [fnoSelectedUnderlying, fnoExchange])

  // Click outside handler for search
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (searchContainerRef.current && !searchContainerRef.current.contains(event.target as Node)) {
        setShowSearchResults(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Symbol search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (newSymbol.length >= 2) {
        performSearch(newSymbol)
      } else {
        setSearchResults([])
        setShowSearchResults(false)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [newSymbol])

  // API Functions
  const loadWatchlist = async () => {
    try {
      const response = await fetch('/historify/api/watchlist', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') setWatchlist(data.data || [])
    } catch (error) {
    }
  }

  const loadCatalog = async () => {
    try {
      const response = await fetch('/historify/api/catalog', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') setCatalog(data.data || [])
    } catch (error) {
    }
  }

  const loadIntervals = async () => {
    try {
      const response = await fetch('/historify/api/intervals', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') setIntervals(data.data)
    } catch (error) {
    }
  }

  const loadHistorifyIntervals = async () => {
    try {
      const response = await fetch('/historify/api/historify-intervals', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') {
        setHistorifyIntervals({
          storage_intervals: data.storage_intervals,
          computed_intervals: data.computed_intervals,
          all_intervals: data.all_intervals
        })
      }
    } catch (error) {
    }
  }

  const loadStats = async () => {
    try {
      const response = await fetch('/historify/api/stats', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') setStats(data.data)
    } catch (error) {
    }
  }

  const loadExchanges = async () => {
    try {
      const response = await fetch('/historify/api/exchanges', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success' && data.data?.length > 0) setExchanges(data.data)
    } catch (error) {
    }
  }

  const loadJobs = async () => {
    setJobsLoading(true)
    try {
      const response = await fetch('/historify/api/jobs?limit=50', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') setJobs(data.data || [])
    } catch (error) {
    } finally {
      setJobsLoading(false)
    }
  }

  // Scheduler API functions
  const loadSchedules = async () => {
    setSchedulesLoading(true)
    try {
      const response = await fetch('/historify/api/schedules', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') setSchedules(data.data || [])
    } catch (error) {
    } finally {
      setSchedulesLoading(false)
    }
  }

  const loadScheduleExecutions = async (scheduleId: string) => {
    try {
      const response = await fetch(`/historify/api/schedules/${scheduleId}/executions?limit=10`, { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') {
        setScheduleExecutions((prev) => ({ ...prev, [scheduleId]: data.data || [] }))
      }
    } catch (error) {
    }
  }

  const resetScheduleForm = () => {
    setScheduleName('')
    setScheduleDescription('')
    setScheduleType('daily')
    setScheduleIntervalValue(5)
    setScheduleIntervalUnit('minutes')
    setScheduleTimeOfDay('09:15')
    setScheduleDataInterval('D')
    setScheduleLookbackDays(1)
    setEditingSchedule(null)
  }

  const openScheduleDialog = (schedule?: Schedule) => {
    if (schedule) {
      setEditingSchedule(schedule)
      setScheduleName(schedule.name)
      setScheduleDescription(schedule.description || '')
      setScheduleType(schedule.schedule_type)
      setScheduleIntervalValue(schedule.interval_value || 5)
      setScheduleIntervalUnit(schedule.interval_unit || 'minutes')
      setScheduleTimeOfDay(schedule.time_of_day || '09:15')
      setScheduleDataInterval(schedule.data_interval)
      setScheduleLookbackDays(schedule.lookback_days)
    } else {
      resetScheduleForm()
    }
    setScheduleDialogOpen(true)
  }

  const handleCreateOrUpdateSchedule = async () => {
    if (!scheduleName.trim()) {
      showToast.warning('Please enter a schedule name', 'historify')
      return
    }

    setIsCreatingSchedule(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const payload: Record<string, unknown> = {
        name: scheduleName.trim(),
        description: scheduleDescription.trim() || undefined,
        schedule_type: scheduleType,
        data_interval: scheduleDataInterval,
        lookback_days: scheduleLookbackDays,
      }

      if (scheduleType === 'interval') {
        payload.interval_value = scheduleIntervalValue
        payload.interval_unit = scheduleIntervalUnit
      } else {
        payload.time_of_day = scheduleTimeOfDay
      }

      const url = editingSchedule
        ? `/historify/api/schedules/${editingSchedule.id}`
        : '/historify/api/schedules'
      const method = editingSchedule ? 'PUT' : 'POST'

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        credentials: 'include',
        body: JSON.stringify(payload),
      })
      const data = await response.json()

      if (data.status === 'success') {
        showToast.success(editingSchedule ? 'Schedule updated' : 'Schedule created', 'historify')
        setScheduleDialogOpen(false)
        resetScheduleForm()
        loadSchedules()
      } else {
        showToast.error(data.message || 'Failed to save schedule', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to save schedule', 'historify')
    } finally {
      setIsCreatingSchedule(false)
    }
  }

  const handleDeleteSchedule = async (scheduleId: string) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/historify/api/schedules/${scheduleId}`, {
        method: 'DELETE',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success('Schedule deleted', 'historify')
        loadSchedules()
      } else {
        showToast.error(data.message || 'Failed to delete schedule', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to delete schedule', 'historify')
    }
  }

  const handleToggleScheduleEnabled = async (schedule: Schedule) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const endpoint = schedule.is_enabled ? 'disable' : 'enable'
      const response = await fetch(`/historify/api/schedules/${schedule.id}/${endpoint}`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(`Schedule ${schedule.is_enabled ? 'disabled' : 'enabled'}`, 'historify')
        loadSchedules()
      } else {
        showToast.error(data.message || 'Failed to toggle schedule', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to toggle schedule', 'historify')
    }
  }

  const handlePauseResumeSchedule = async (schedule: Schedule) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const endpoint = schedule.is_paused ? 'resume' : 'pause'
      const response = await fetch(`/historify/api/schedules/${schedule.id}/${endpoint}`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(`Schedule ${schedule.is_paused ? 'resumed' : 'paused'}`, 'historify')
        loadSchedules()
      } else {
        showToast.error(data.message || 'Failed to pause/resume schedule', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to pause/resume schedule', 'historify')
    }
  }

  const handleTriggerSchedule = async (scheduleId: string) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/historify/api/schedules/${scheduleId}/trigger`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success('Schedule triggered', 'historify')
        loadSchedules()
        loadJobs()
      } else {
        showToast.error(data.message || 'Failed to trigger schedule', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to trigger schedule', 'historify')
    }
  }

  const getScheduleStatusBadge = (schedule: Schedule) => {
    if (!schedule.is_enabled) {
      return <Badge variant="secondary">Disabled</Badge>
    }
    if (schedule.is_paused) {
      return <Badge variant="outline" className="border-yellow-500 text-yellow-600">Paused</Badge>
    }
    if (schedule.status === 'running') {
      return <Badge variant="default" className="bg-blue-500">Running</Badge>
    }
    return <Badge variant="default" className="bg-green-500">Active</Badge>
  }

  const formatScheduleFrequency = (schedule: Schedule) => {
    if (schedule.schedule_type === 'interval') {
      return `Every ${schedule.interval_value} ${schedule.interval_unit}`
    }
    // Convert 24-hour to 12-hour format with AM/PM
    const [h, m] = (schedule.time_of_day || '09:15').split(':').map(Number)
    const hour12 = h === 0 ? 12 : h > 12 ? h - 12 : h
    const ampm = h >= 12 ? 'PM' : 'AM'
    return `Daily at ${hour12}:${m.toString().padStart(2, '0')} ${ampm} IST`
  }

  const performSearch = async (query: string) => {
    if (query.length < 2) return
    try {
      const params = new URLSearchParams({ q: query })
      if (newExchange) params.append('exchange', newExchange)
      const response = await fetch(`/search/api/search?${params}`, { credentials: 'include' })
      const data = await response.json()
      setSearchResults((data.results || []).slice(0, 10))
      setShowSearchResults(true)
    } catch (error) {
      setSearchResults([])
    }
  }

  // Watchlist operations
  const addToWatchlist = async () => {
    if (!newSymbol.trim()) {
      showToast.warning('Please enter a symbol', 'historify')
      return
    }
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/historify/api/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        credentials: 'include',
        body: JSON.stringify({ symbol: newSymbol.trim().toUpperCase(), exchange: newExchange }),
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(data.message, 'historify')
        setNewSymbol('')
        loadWatchlist()
        loadStats()
      } else {
        showToast.error(data.message || 'Failed to add symbol', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to add symbol', 'historify')
    }
  }

  const removeFromWatchlist = async (symbol: string, exchange: string) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/historify/api/watchlist', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        credentials: 'include',
        body: JSON.stringify({ symbol, exchange }),
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(data.message, 'historify')
        loadWatchlist()
        loadStats()
      } else {
        showToast.error(data.message || 'Failed to remove symbol', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to remove symbol', 'historify')
    }
  }

  const handleBulkAdd = async () => {
    const lines = bulkAddText.trim().split('\n')
    const symbols = lines
      .map((line) => {
        const [symbol, exchange] = line.split(',').map((s) => s.trim().toUpperCase())
        return { symbol, exchange: exchange || 'NSE' }
      })
      .filter((s) => s.symbol)

    if (symbols.length === 0) {
      showToast.warning('No valid symbols found', 'historify')
      return
    }

    setIsBulkAdding(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/historify/api/watchlist/bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        credentials: 'include',
        body: JSON.stringify({ symbols }),
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(`Added ${data.added} symbols`, 'historify')
        setBulkAddDialogOpen(false)
        setBulkAddText('')
        loadWatchlist()
        loadStats()
      } else {
        showToast.error(data.message || 'Failed to bulk add symbols', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to bulk add symbols', 'historify')
    } finally {
      setIsBulkAdding(false)
    }
  }

  // FNO Discovery functions (disabled for now)
  // const loadFnoUnderlyings = async () => {
  //   try {
  //     const response = await fetch(`/historify/api/fno/underlyings?exchange=${fnoExchange}`, { credentials: 'include' })
  //     const data = await response.json()
  //     if (data.status === 'success') {
  //       setFnoUnderlyings(data.data || [])
  //       setFnoSelectedUnderlying('')
  //       setFnoExpiries([])
  //       setFnoSelectedExpiry('')
  //       setFnoSymbols([])
  //     }
  //   } catch (error) {
  //     console.error('Error loading FNO underlyings:', error)
  //   }
  // }

  // const loadFnoExpiries = async () => {
  //   try {
  //     const params = new URLSearchParams({ underlying: fnoSelectedUnderlying, exchange: fnoExchange })
  //     const response = await fetch(`/historify/api/fno/expiries?${params}`, { credentials: 'include' })
  //     const data = await response.json()
  //     if (data.status === 'success') {
  //       setFnoExpiries(data.data || [])
  //       setFnoSelectedExpiry('')
  //     }
  //   } catch (error) {
  //     console.error('Error loading FNO expiries:', error)
  //   }
  // }

  // const loadFnoChain = async () => {
  //   if (!fnoSelectedUnderlying) {
  //     showToast.warning('Please select an underlying')
  //     return
  //   }
  //   setFnoLoading(true)
  //   try {
  //     const params = new URLSearchParams({ underlying: fnoSelectedUnderlying, exchange: fnoExchange, limit: '5000' })
  //     if (fnoSelectedExpiry) params.append('expiry', fnoSelectedExpiry)
  //     if (fnoInstrumentType && fnoInstrumentType !== '__all__') params.append('instrumenttype', fnoInstrumentType)
  //     if (fnoStrikeMin) params.append('strike_min', fnoStrikeMin)
  //     if (fnoStrikeMax) params.append('strike_max', fnoStrikeMax)

  //     const response = await fetch(`/historify/api/fno/chain?${params}`, { credentials: 'include' })
  //     const data = await response.json()
  //     if (data.status === 'success') {
  //       setFnoSymbols(data.data || [])
  //       setFnoSelectedSymbols(new Set())
  //       showToast.success(`Found ${data.count} symbols`)
  //     } else {
  //       showToast.error(data.message || 'Failed to load FNO chain')
  //     }
  //   } catch (error) {
  //     console.error('Error loading FNO chain:', error)
  //     showToast.error('Failed to load FNO chain')
  //   } finally {
  //     setFnoLoading(false)
  //   }
  // }

  // Job operations
  const createDownloadJob = async (symbols: { symbol: string; exchange: string }[], jobType: string = 'custom') => {
    if (symbols.length === 0) {
      showToast.warning('No symbols selected', 'historify')
      return
    }
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/historify/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        credentials: 'include',
        body: JSON.stringify({
          job_type: jobType,
          symbols,
          interval: selectedInterval,
          start_date: startDate,
          end_date: endDate,
          incremental: incrementalDownload,
        }),
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(`Job started: ${data.total_symbols} symbols`, 'historify')
        loadJobs()
        setActiveTab('jobs')
      } else {
        showToast.error(data.message || 'Failed to create job', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to create job', 'historify')
    }
  }

  const downloadWatchlist = async () => {
    if (watchlist.length === 0) {
      showToast.warning('Watchlist is empty', 'historify')
      return
    }
    const symbols = watchlist.map((item) => ({ symbol: item.symbol, exchange: item.exchange }))
    await createDownloadJob(symbols, 'watchlist')
  }

  const pauseJob = async (jobId: string) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/historify/api/jobs/${jobId}/pause`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success('Job paused', 'historify')
        loadJobs()
      } else {
        showToast.error(data.message || 'Failed to pause job', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to pause job', 'historify')
    }
  }

  const resumeJob = async (jobId: string) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/historify/api/jobs/${jobId}/resume`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success('Job resumed', 'historify')
        loadJobs()
      } else {
        showToast.error(data.message || 'Failed to resume job', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to resume job', 'historify')
    }
  }

  const cancelJob = async (jobId: string) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/historify/api/jobs/${jobId}/cancel`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success('Job cancellation requested', 'historify')
        loadJobs()
      } else {
        showToast.error(data.message || 'Failed to cancel job', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to cancel job', 'historify')
    }
  }

  const retryJob = async (jobId: string) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/historify/api/jobs/${jobId}/retry`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(`Retrying ${data.retry_count} failed items`, 'historify')
        loadJobs()
      } else {
        showToast.error(data.message || 'Failed to retry job', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to retry job', 'historify')
    }
  }

  const deleteJob = async (jobId: string) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/historify/api/jobs/${jobId}`, {
        method: 'DELETE',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success('Job deleted', 'historify')
        loadJobs()
        if (selectedJob?.id === jobId) {
          setSelectedJob(null)
        }
      } else {
        showToast.error(data.message || 'Failed to delete job', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to delete job', 'historify')
    }
  }

  // Delete data
  const handleDeleteData = async () => {
    if (!deleteTarget) return
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/historify/api/delete', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        credentials: 'include',
        body: JSON.stringify(deleteTarget),
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(data.message, 'historify')
        loadCatalog()
        loadStats()
      } else {
        showToast.error(data.message || 'Failed to delete data', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to delete data', 'historify')
    } finally {
      setDeleteDialogOpen(false)
      setDeleteTarget(null)
    }
  }

  // Bulk delete data
  const handleBulkDeleteData = async () => {
    if (catalogSelectedSymbols.size === 0) return
    setIsBulkDeleting(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const symbols = Array.from(catalogSelectedSymbols).map((key) => {
        const [symbol, exchange] = key.split(':')
        return { symbol, exchange }
      })
      const response = await fetch('/historify/api/delete/bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        credentials: 'include',
        body: JSON.stringify({ symbols }),
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(data.message, 'historify')
        setCatalogSelectedSymbols(new Set())
        loadCatalog()
        loadStats()
      } else {
        showToast.error(data.message || 'Failed to delete data', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to delete data', 'historify')
    } finally {
      setIsBulkDeleting(false)
      setBulkDeleteDialogOpen(false)
    }
  }

  // Bulk delete watchlist
  const handleBulkWatchlistDelete = async () => {
    if (watchlistSelectedSymbols.size === 0) return
    setIsBulkWatchlistDeleting(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const symbols = Array.from(watchlistSelectedSymbols).map((key) => {
        const [symbol, exchange] = key.split(':')
        return { symbol, exchange }
      })
      const response = await fetch('/historify/api/watchlist/bulk/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        credentials: 'include',
        body: JSON.stringify({ symbols }),
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(data.message, 'historify')
        setWatchlistSelectedSymbols(new Set())
        loadWatchlist()
      } else {
        showToast.error(data.message || 'Failed to remove from watchlist', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to remove from watchlist', 'historify')
    } finally {
      setIsBulkWatchlistDeleting(false)
      setBulkWatchlistDeleteDialogOpen(false)
    }
  }

  // CSV Upload
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      const fileName = file.name.toLowerCase()
      if (!fileName.endsWith('.csv') && !fileName.endsWith('.parquet')) {
        showToast.error('Please select a CSV or Parquet file', 'historify')
        return
      }
      setUploadFile(file)
    }
  }

  const uploadCSVData = async () => {
    if (!uploadFile) {
      showToast.warning('Please select a CSV or Parquet file', 'historify')
      return
    }
    if (!uploadSymbol.trim()) {
      showToast.warning('Please enter a symbol', 'historify')
      return
    }
    setIsUploading(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const formData = new FormData()
      formData.append('file', uploadFile)
      formData.append('symbol', uploadSymbol.trim().toUpperCase())
      formData.append('exchange', uploadExchange)
      formData.append('interval', uploadInterval)

      const response = await fetch('/historify/api/upload', {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
        body: formData,
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(`${data.message}`, 'historify')
        setUploadDialogOpen(false)
        setUploadFile(null)
        setUploadSymbol('')
        if (fileInputRef.current) fileInputRef.current.value = ''
        loadCatalog()
        loadStats()
      } else {
        showToast.error(data.message || 'Failed to upload data', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to upload CSV', 'historify')
    } finally {
      setIsUploading(false)
    }
  }

  // Export operations
  const handleBulkExport = async () => {
    setIsExporting(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const symbols = exportSymbols === 'selected'
        ? Array.from(catalogSelectedSymbols).map((key) => {
            const [symbol, exchange] = key.split(':')
            return { symbol, exchange }
          })
        : null  // null means export all symbols

      // Convert Set to array for API
      const intervalsArray = Array.from(exportIntervals)

      const response = await fetch('/historify/api/export/bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        credentials: 'include',
        body: JSON.stringify({
          format: exportFormat === 'csv' && intervalsArray.length > 1 ? 'zip' : exportFormat,  // Force ZIP if multiple intervals
          symbols,
          intervals: intervalsArray,  // Pass multiple intervals
          compression: 'zstd',
        }),
      })
      const data = await response.json()
      if (data.status === 'success') {
        showToast.success(`${data.message}`, 'historify')
        window.location.href = '/historify/api/export/bulk/download'
        setExportDialogOpen(false)
      } else {
        showToast.error(data.message || 'Failed to export data', 'historify')
      }
    } catch (error) {
      showToast.error('Failed to export data', 'historify')
    } finally {
      setIsExporting(false)
    }
  }

  // Helper functions
  const toggleCatalogSymbol = (symbol: string, exchange: string) => {
    const key = `${symbol}:${exchange}`
    setCatalogSelectedSymbols((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // FNO toggle (disabled for now)
  // const toggleFnoSymbol = (symbol: string) => {
  //   setFnoSelectedSymbols((prev) => {
  //     const next = new Set(prev)
  //     if (next.has(symbol)) next.delete(symbol)
  //     else next.add(symbol)
  //     return next
  //   })
  // }

  const getJobStatusColor = (status: string) => {
    switch (status) {
      case 'running': return 'bg-blue-500'
      case 'paused': return 'bg-yellow-500'
      case 'completed': return 'bg-green-500'
      case 'completed_with_errors': return 'bg-orange-500'
      case 'failed': return 'bg-red-500'
      case 'cancelled': return 'bg-gray-500'
      default: return 'bg-gray-400'
    }
  }

  const handleModeToggle = async () => {
    const result = await toggleAppMode()
    if (result.success) {
      const newMode = useThemeStore.getState().appMode
      showToast.success(`Switched to ${newMode === 'live' ? 'Live' : 'Analyze'} mode`, 'system')
    } else {
      showToast.error(result.message || 'Failed to toggle mode', 'system')
    }
  }

  const handleLogout = async () => {
    try {
      await authApi.logout()
      logout()
      navigate('/login')
      showToast.success('Logged out successfully', 'system')
    } catch {
      logout()
      navigate('/login')
    }
  }

  // Render
  return (
    <div className="h-full flex flex-col bg-background">
      {/* Header */}
      <div className="border-b border-border bg-card/50">
        <div className="px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-3">
          <div className="flex items-center gap-3">
            <Database className="h-6 w-6 text-primary" />
            <div>
              <h1 className="text-lg font-semibold">Historify</h1>
              <p className="text-xs text-muted-foreground hidden sm:block">Historical Data Management</p>
            </div>
          </div>

          <div className="flex-1" />

          {/* Stats Cards - Responsive */}
          <div className="flex flex-wrap gap-2">
            <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/50 rounded-lg">
              <HardDrive className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">{stats.database_size_mb.toFixed(1)} MB</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/50 rounded-lg">
              <BarChart3 className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">{stats.total_records.toLocaleString()}</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/50 rounded-lg">
              <TrendingUp className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">{stats.total_symbols}</span>
            </div>
          </div>

          {/* Right Controls */}
          <div className="flex items-center gap-2">
            {/* Broker Badge */}
            {user?.broker && (
              <Badge variant="outline" className="text-xs font-medium">
                {user.broker.toUpperCase()}
              </Badge>
            )}

            {/* Mode Badge */}
            <Badge
              variant={appMode === 'live' ? 'default' : 'secondary'}
              className={cn(
                'text-xs cursor-pointer',
                appMode === 'analyzer' && 'bg-purple-500 hover:bg-purple-600 text-white'
              )}
              onClick={handleModeToggle}
            >
              {appMode === 'live' ? <Zap className="h-3 w-3 mr-1" /> : <BarChart3 className="h-3 w-3 mr-1" />}
              <span className="hidden sm:inline">{appMode === 'live' ? 'Live Mode' : 'Analyze Mode'}</span>
              <span className="sm:hidden">{appMode === 'live' ? 'Live' : 'Analyze'}</span>
            </Badge>

            {/* Mode Toggle Button */}
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={handleModeToggle}
              disabled={isTogglingMode}
              title={`Switch to ${appMode === 'live' ? 'Analyze' : 'Live'} mode`}
            >
              {isTogglingMode ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : appMode === 'live' ? (
                <Zap className="h-4 w-4" />
              ) : (
                <BarChart3 className="h-4 w-4" />
              )}
            </Button>

            {/* Theme Toggle */}
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={toggleMode}
              disabled={appMode !== 'live'}
              title={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
            >
              {mode === 'light' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>

            {/* Charts Link - navigates with first available symbol */}
            <Link
              to={
                watchlist.length > 0
                  ? `/historify/charts/${watchlist[0].symbol}?exchange=${watchlist[0].exchange}&interval=D`
                  : groupedCatalog.length > 0
                    ? `/historify/charts/${groupedCatalog[0].symbol}?exchange=${groupedCatalog[0].exchange}&interval=D`
                    : '/historify/charts'
              }
            >
              <Button variant="outline" size="sm">
                <LineChart className="h-4 w-4 mr-1" />
                <span className="hidden sm:inline">Charts</span>
              </Button>
            </Link>

            {/* Dashboard Link */}
            <Link to="/dashboard">
              <Button variant="outline" size="sm">
                <Home className="h-4 w-4 mr-1" />
                <span className="hidden sm:inline">Dashboard</span>
              </Button>
            </Link>

            {/* Profile Menu */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 rounded-full bg-primary text-primary-foreground"
                >
                  <span className="text-sm font-medium">
                    {user?.username?.[0]?.toUpperCase() || 'O'}
                  </span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                {profileMenuItems.map((item) => (
                  <DropdownMenuItem
                    key={item.href}
                    onSelect={() => navigate(item.href)}
                    className="cursor-pointer"
                  >
                    <item.icon className="h-4 w-4 mr-2" />
                    {item.label}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuItem asChild>
                  <a
                    href="https://docs.openalgo.in"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2"
                  >
                    <BookOpen className="h-4 w-4" />
                    Docs
                  </a>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={handleLogout}
                  className="text-destructive focus:text-destructive"
                >
                  <LogOut className="h-4 w-4 mr-2" />
                  Logout
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-hidden">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="h-full flex flex-col">
          {/* Tab Navigation - Scrollable on mobile */}
          <div className="border-b border-border px-4 overflow-x-auto">
            <TabsList className="h-10 bg-transparent w-max min-w-full sm:w-auto">
              <TabsTrigger value="watchlist" className="gap-1.5 data-[state=active]:bg-muted">
                <Target className="h-4 w-4" />
                <span className="hidden sm:inline">Watchlist</span>
                <span className="sm:hidden">Watch</span>
                {watchlist.length > 0 && (
                  <Badge variant="secondary" className="ml-1 h-5 min-w-5 text-xs">{watchlist.length}</Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="scheduler" className="gap-1.5 data-[state=active]:bg-muted">
                <RefreshCw className="h-4 w-4" />
                <span className="hidden sm:inline">Scheduler</span>
                <span className="sm:hidden">Sched</span>
                {schedules.filter((s) => s.is_enabled && !s.is_paused).length > 0 && (
                  <Badge variant="default" className="ml-1 h-5 min-w-5 text-xs bg-green-500">
                    {schedules.filter((s) => s.is_enabled && !s.is_paused).length}
                  </Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="jobs" className="gap-1.5 data-[state=active]:bg-muted">
                <DownloadCloud className="h-4 w-4" />
                <span className="hidden sm:inline">Download Jobs</span>
                <span className="sm:hidden">Jobs</span>
                {jobs.filter((j) => j.status === 'running' || j.status === 'paused').length > 0 && (
                  <Badge variant="default" className="ml-1 h-5 min-w-5 text-xs bg-blue-500">
                    {jobs.filter((j) => j.status === 'running' || j.status === 'paused').length}
                  </Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="catalog" className="gap-1.5 data-[state=active]:bg-muted">
                <Database className="h-4 w-4" />
                <span className="hidden sm:inline">Export/Import</span>
                <span className="sm:hidden">Export</span>
              </TabsTrigger>
            </TabsList>
          </div>

          {/* Tab Content */}
          <div className="flex-1 overflow-hidden">
            {/* Export/Import Tab */}
            <TabsContent value="catalog" className="h-full m-0 p-4 overflow-auto">
              <div className="space-y-4">
                {/* Quick Add Symbol */}
                <Card>
                  <CardContent className="p-4">
                    <div className="flex flex-col sm:flex-row gap-3">
                      <div className="flex-1 relative" ref={searchContainerRef}>
                        <Input
                          placeholder="Quick add symbol to watchlist..."
                          value={newSymbol}
                          onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
                          className="h-9"
                        />
                        {showSearchResults && searchResults.length > 0 && (
                          <div className="absolute top-full left-0 right-0 mt-1 bg-popover border border-border rounded-md shadow-lg z-50 max-h-60 overflow-auto">
                            {searchResults.map((result) => (
                              <div
                                key={`${result.symbol}-${result.exchange}`}
                                className="px-3 py-2 hover:bg-muted cursor-pointer"
                                onClick={() => {
                                  setNewSymbol(result.symbol)
                                  setNewExchange(result.exchange)
                                  setShowSearchResults(false)
                                }}
                              >
                                <div className="font-medium">{result.symbol}</div>
                                <div className="text-xs text-muted-foreground">{result.name} - {result.exchange}</div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                      <Select value={newExchange} onValueChange={setNewExchange}>
                        <SelectTrigger className="w-full sm:w-28 h-9">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {exchanges.map((ex) => (
                            <SelectItem key={ex} value={ex}>{ex}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button onClick={addToWatchlist} className="h-9" size="sm">
                        <Plus className="h-4 w-4 mr-1" />
                        Add to Watchlist
                      </Button>
                      <Button variant="outline" onClick={() => setBulkAddDialogOpen(true)} className="h-9" size="sm">
                        <ListPlus className="h-4 w-4 mr-1" />
                        Bulk
                      </Button>
                    </div>
                  </CardContent>
                </Card>

                {/* Filters */}
                <Card>
                  <CardContent className="p-4">
                    <div className="flex flex-col sm:flex-row gap-3">
                      <div className="flex-1">
                        <Input
                          placeholder="Filter symbols..."
                          value={catalogFilter.search}
                          onChange={(e) => setCatalogFilter((prev) => ({ ...prev, search: e.target.value }))}
                          className="h-9"
                        />
                      </div>
                      <Select
                        value={catalogFilter.exchange || '__all__'}
                        onValueChange={(v) => setCatalogFilter((prev) => ({ ...prev, exchange: v }))}
                      >
                        <SelectTrigger className="w-full sm:w-32 h-9">
                          <SelectValue placeholder="Exchange" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__all__">All</SelectItem>
                          {exchanges.map((ex) => (
                            <SelectItem key={ex} value={ex}>{ex}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Select
                        value={catalogFilter.interval || '__all__'}
                        onValueChange={(v) => setCatalogFilter((prev) => ({ ...prev, interval: v }))}
                      >
                        <SelectTrigger className="w-full sm:w-32 h-9" title="Filter symbols that have this interval">
                          <SelectValue placeholder="Has Interval" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__all__">All Intervals</SelectItem>
                          {(historifyIntervals?.storage_intervals || ['1m', 'D']).map((int) => (
                            <SelectItem key={int} value={int}>Has {int}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <div className="flex gap-2">
                        {catalogSelectedSymbols.size > 0 && (
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => setBulkDeleteDialogOpen(true)}
                            className="h-9"
                          >
                            <Trash2 className="h-4 w-4 mr-1" />
                            Delete ({catalogSelectedSymbols.size})
                          </Button>
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setExportDialogOpen(true)}
                          disabled={catalog.length === 0}
                          className="h-9"
                        >
                          <FileDown className="h-4 w-4 mr-1" />
                          Export
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setUploadDialogOpen(true)} className="h-9">
                          <Upload className="h-4 w-4 mr-1" />
                          Import
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {/* Catalog Table - Grouped by Symbol */}
                <Card>
                  <ScrollArea className="h-[calc(100vh-380px)]">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-10">
                            <Checkbox
                              checked={catalogSelectedSymbols.size === filteredGroupedCatalog.length && filteredGroupedCatalog.length > 0}
                              onCheckedChange={(checked) => {
                                if (checked) {
                                  setCatalogSelectedSymbols(new Set(filteredGroupedCatalog.map((c) => `${c.symbol}:${c.exchange}`)))
                                } else {
                                  setCatalogSelectedSymbols(new Set())
                                }
                              }}
                            />
                          </TableHead>
                          <TableHead>Symbol</TableHead>
                          <TableHead className="hidden sm:table-cell">Exchange</TableHead>
                          <TableHead>Available Intervals</TableHead>
                          <TableHead className="text-right hidden sm:table-cell">Total Records</TableHead>
                          <TableHead className="hidden md:table-cell">Date Range</TableHead>
                          <TableHead className="w-20"></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filteredGroupedCatalog.length === 0 ? (
                          <TableRow>
                            <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                              No data available. Add symbols to watchlist and download data.
                            </TableCell>
                          </TableRow>
                        ) : (
                          filteredGroupedCatalog.map((item) => (
                            <TableRow key={`${item.symbol}-${item.exchange}`}>
                              <TableCell>
                                <Checkbox
                                  checked={catalogSelectedSymbols.has(`${item.symbol}:${item.exchange}`)}
                                  onCheckedChange={() => toggleCatalogSymbol(item.symbol, item.exchange)}
                                />
                              </TableCell>
                              <TableCell className="font-medium">
                                <div>
                                  {item.symbol}
                                  <span className="sm:hidden text-xs text-muted-foreground ml-1">
                                    ({item.exchange})
                                  </span>
                                </div>
                              </TableCell>
                              <TableCell className="hidden sm:table-cell">
                                <Badge variant="outline">{item.exchange}</Badge>
                              </TableCell>
                              <TableCell>
                                <div className="flex flex-wrap gap-1">
                                  {item.intervals.map((int) => (
                                    <Badge
                                      key={int.interval}
                                      variant={int.interval === '1m' ? 'default' : int.interval === 'D' ? 'secondary' : 'outline'}
                                      className="text-xs cursor-pointer hover:bg-primary/80"
                                      title={`${int.record_count.toLocaleString()} records (${int.first_date} - ${int.last_date})`}
                                      onClick={() => {
                                        // Navigate to charts with this interval
                                        window.location.href = `/historify/charts/${item.symbol}?exchange=${item.exchange}&interval=${int.interval}`
                                      }}
                                    >
                                      {int.interval}
                                      <span className="ml-1 opacity-70">{int.record_count > 1000 ? `${Math.round(int.record_count/1000)}k` : int.record_count}</span>
                                    </Badge>
                                  ))}
                                </div>
                              </TableCell>
                              <TableCell className="text-right hidden sm:table-cell">{item.total_records.toLocaleString()}</TableCell>
                              <TableCell className="hidden md:table-cell text-muted-foreground text-sm">
                                {item.earliest_date} - {item.latest_date}
                              </TableCell>
                              <TableCell>
                                <div className="flex gap-1">
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-7 w-7"
                                    asChild
                                  >
                                    <Link to={`/historify/charts/${item.symbol}?exchange=${item.exchange}&interval=${item.intervals[0]?.interval || 'D'}`}>
                                      <LineChart className="h-3.5 w-3.5" />
                                    </Link>
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-7 w-7 text-destructive hover:text-destructive"
                                    onClick={() => {
                                      setDeleteTarget({ symbol: item.symbol, exchange: item.exchange })
                                      setDeleteDialogOpen(true)
                                    }}
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </Button>
                                </div>
                              </TableCell>
                            </TableRow>
                          ))
                        )}
                      </TableBody>
                    </Table>
                  </ScrollArea>
                </Card>
              </div>
            </TabsContent>

            {/* Watchlist Tab - Two Column Layout */}
            <TabsContent value="watchlist" className="h-full m-0 p-4 overflow-auto">
              {/* Add Symbol Row */}
              <Card className="mb-4">
                <CardContent className="p-4">
                  <div className="flex flex-col sm:flex-row gap-3">
                    <div className="flex-1 relative" ref={searchContainerRef}>
                      <Input
                        placeholder="Search symbol to add..."
                        value={newSymbol}
                        onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
                        className="h-9"
                      />
                      {showSearchResults && searchResults.length > 0 && (
                        <div className="absolute top-full left-0 right-0 mt-1 bg-popover border border-border rounded-md shadow-lg z-50 max-h-60 overflow-auto">
                          {searchResults.map((result) => (
                            <div
                              key={`${result.symbol}-${result.exchange}`}
                              className="px-3 py-2 hover:bg-muted cursor-pointer"
                              onClick={() => {
                                setNewSymbol(result.symbol)
                                setNewExchange(result.exchange)
                                setShowSearchResults(false)
                              }}
                            >
                              <div className="font-medium">{result.symbol}</div>
                              <div className="text-xs text-muted-foreground">{result.name} - {result.exchange}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    <Select value={newExchange} onValueChange={setNewExchange}>
                      <SelectTrigger className="w-full sm:w-28 h-9">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {exchanges.map((ex) => (
                          <SelectItem key={ex} value={ex}>{ex}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button onClick={addToWatchlist} className="h-9">
                      <Plus className="h-4 w-4 mr-1" />
                      Add
                    </Button>
                    <Button variant="outline" onClick={() => setBulkAddDialogOpen(true)} className="h-9">
                      <ListPlus className="h-4 w-4 mr-1" />
                      Bulk
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {/* Two Column Layout */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 h-[calc(100vh-240px)]">
                {/* Left Column - Download Settings */}
                <Card className="flex flex-col">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2">
                      <Settings className="h-4 w-4" />
                      Download Settings
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="flex-1 overflow-auto">
                    <div className="space-y-4">
                      {/* Date Range Quick Buttons */}
                      <div>
                        <Label className="text-sm text-muted-foreground mb-2 block">Quick Date Range</Label>
                        <div className="flex flex-wrap gap-2">
                          {DATE_PRESETS.map((preset) => {
                            const isSelected = startDate === getDateFromPreset(preset.months)
                            return (
                              <Button
                                key={preset.label}
                                variant={isSelected ? "default" : "outline"}
                                size="sm"
                                className={cn(
                                  "h-8 min-w-[3rem]",
                                  isSelected && "ring-2 ring-primary ring-offset-2 ring-offset-background"
                                )}
                                onClick={() => {
                                  setStartDate(getDateFromPreset(preset.months))
                                  setEndDate(new Date().toISOString().split('T')[0])
                                }}
                              >
                                {preset.label}
                              </Button>
                            )
                          })}
                        </div>
                      </div>

                      {/* Custom Date Range */}
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <Label className="text-sm text-muted-foreground">From</Label>
                          <Input
                            type="date"
                            value={startDate}
                            onChange={(e) => setStartDate(e.target.value)}
                            className="h-9 mt-1"
                          />
                        </div>
                        <div>
                          <Label className="text-sm text-muted-foreground">To</Label>
                          <Input
                            type="date"
                            value={endDate}
                            onChange={(e) => setEndDate(e.target.value)}
                            className="h-9 mt-1"
                          />
                        </div>
                      </div>

                      {/* Interval Selection */}
                      <div>
                        <Label className="text-sm text-muted-foreground">Interval</Label>
                        <Select value={selectedInterval} onValueChange={setSelectedInterval}>
                          <SelectTrigger className="h-9 mt-1">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {(historifyIntervals?.storage_intervals || ['1m', 'D']).map((int) => (
                              <SelectItem key={int} value={int}>
                                {int === '1m' ? '1 Minute' : int === 'D' ? 'Daily' : int}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <p className="text-[10px] text-muted-foreground mt-1">
                          Other timeframes (5m, 15m, 30m, 1h) computed from 1m data
                        </p>
                      </div>

                      {/* Incremental Download Toggle */}
                      <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
                        <div>
                          <Label className="font-medium">Incremental Download</Label>
                          <p className="text-xs text-muted-foreground">Only download new data after last timestamp</p>
                        </div>
                        <Switch
                          checked={incrementalDownload}
                          onCheckedChange={setIncrementalDownload}
                        />
                      </div>

                      {/* Download Buttons */}
                      <div className="space-y-2 pt-2">
                        <Button
                          className="w-full h-10"
                          onClick={() => {
                            if (watchlistSelectedSymbols.size === 0) {
                              downloadWatchlist()
                            } else {
                              const selectedSymbols = watchlist
                                .filter((w) => watchlistSelectedSymbols.has(`${w.symbol}:${w.exchange}`))
                                .map((w) => ({ symbol: w.symbol, exchange: w.exchange }))
                              createDownloadJob(selectedSymbols, 'watchlist')
                            }
                          }}
                          disabled={watchlist.length === 0}
                        >
                          <DownloadCloud className="h-4 w-4 mr-2" />
                          {watchlistSelectedSymbols.size > 0
                            ? `Download Selected (${watchlistSelectedSymbols.size})`
                            : `Download All (${watchlist.length})`
                          }
                        </Button>
                        {watchlistSelectedSymbols.size > 0 && (
                          <Button
                            variant="outline"
                            className="w-full h-9"
                            onClick={() => setWatchlistSelectedSymbols(new Set())}
                          >
                            Clear Selection
                          </Button>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>

                {/* Right Column - Symbol List */}
                <Card className="flex flex-col">
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-base">
                        Symbols ({watchlist.length})
                        {watchlistSelectedSymbols.size > 0 && (
                          <Badge className="ml-2">{watchlistSelectedSymbols.size} selected</Badge>
                        )}
                      </CardTitle>
                      <div className="flex gap-2">
                        {watchlistSelectedSymbols.size > 0 && (
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => setBulkWatchlistDeleteDialogOpen(true)}
                          >
                            <Trash2 className="h-4 w-4 mr-1" />
                            Delete ({watchlistSelectedSymbols.size})
                          </Button>
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            if (watchlistSelectedSymbols.size === watchlist.length) {
                              setWatchlistSelectedSymbols(new Set())
                            } else {
                              setWatchlistSelectedSymbols(new Set(watchlist.map((w) => `${w.symbol}:${w.exchange}`)))
                            }
                          }}
                        >
                          {watchlistSelectedSymbols.size === watchlist.length ? 'Deselect All' : 'Select All'}
                        </Button>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="flex-1 p-0 overflow-hidden">
                    <ScrollArea className="h-full">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className="w-10">
                              <Checkbox
                                checked={watchlistSelectedSymbols.size === watchlist.length && watchlist.length > 0}
                                onCheckedChange={(checked) => {
                                  if (checked) {
                                    setWatchlistSelectedSymbols(new Set(watchlist.map((w) => `${w.symbol}:${w.exchange}`)))
                                  } else {
                                    setWatchlistSelectedSymbols(new Set())
                                  }
                                }}
                              />
                            </TableHead>
                            <TableHead>Symbol</TableHead>
                            <TableHead className="hidden sm:table-cell">Exchange</TableHead>
                            <TableHead className="hidden md:table-cell">Added</TableHead>
                            <TableHead className="w-20 text-right">Actions</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {watchlist.length === 0 ? (
                            <TableRow>
                              <TableCell colSpan={5} className="text-center py-12 text-muted-foreground">
                                <Target className="h-12 w-12 mx-auto mb-4 opacity-50" />
                                <p>No symbols in watchlist</p>
                                <p className="text-sm mt-1">Add symbols using the search above</p>
                              </TableCell>
                            </TableRow>
                          ) : (
                            watchlist.map((item) => (
                              <TableRow
                                key={item.id}
                                className={cn(
                                  watchlistSelectedSymbols.has(`${item.symbol}:${item.exchange}`) && "bg-muted/50"
                                )}
                              >
                                <TableCell>
                                  <Checkbox
                                    checked={watchlistSelectedSymbols.has(`${item.symbol}:${item.exchange}`)}
                                    onCheckedChange={() => {
                                      setWatchlistSelectedSymbols((prev) => {
                                        const next = new Set(prev)
                                        const key = `${item.symbol}:${item.exchange}`
                                        if (next.has(key)) next.delete(key)
                                        else next.add(key)
                                        return next
                                      })
                                    }}
                                  />
                                </TableCell>
                                <TableCell className="font-medium">
                                  {item.symbol}
                                  <span className="sm:hidden text-xs text-muted-foreground ml-1">({item.exchange})</span>
                                </TableCell>
                                <TableCell className="hidden sm:table-cell">
                                  <Badge variant="outline">{item.exchange}</Badge>
                                </TableCell>
                                <TableCell className="hidden md:table-cell text-muted-foreground text-sm">
                                  {new Date(item.added_at).toLocaleDateString()}
                                </TableCell>
                                <TableCell>
                                  <div className="flex items-center justify-end gap-1">
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="h-7 w-7"
                                      asChild
                                      title="View chart"
                                    >
                                      <Link to={`/historify/charts/${item.symbol}?exchange=${item.exchange}&interval=D`}>
                                        <LineChart className="h-4 w-4" />
                                      </Link>
                                    </Button>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="h-7 w-7 text-destructive hover:text-destructive"
                                      onClick={() => removeFromWatchlist(item.symbol, item.exchange)}
                                      title="Remove from watchlist"
                                    >
                                      <X className="h-4 w-4" />
                                    </Button>
                                  </div>
                                </TableCell>
                              </TableRow>
                            ))
                          )}
                        </TableBody>
                      </Table>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            {/* Download Jobs Tab */}
            <TabsContent value="jobs" className="h-full m-0 p-4 overflow-auto">
              <div className="space-y-4">
                {/* Jobs List */}
                <Card>
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-base">Download Jobs</CardTitle>
                      <Button variant="outline" size="sm" onClick={loadJobs} disabled={jobsLoading}>
                        <RefreshCw className={cn("h-4 w-4 mr-1", jobsLoading && "animate-spin")} />
                        Refresh
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="p-0">
                    <ScrollArea className="h-[calc(100vh-280px)]">
                      {jobs.length === 0 ? (
                        <div className="text-center py-12 text-muted-foreground">
                          <DownloadCloud className="h-12 w-12 mx-auto mb-4 opacity-50" />
                          <p>No download jobs yet</p>
                          <p className="text-sm mt-1">Start a download from the Watchlist tab</p>
                        </div>
                      ) : (
                        <div className="divide-y divide-border">
                          {jobs.map((job) => {
                            const progress = jobProgress[job.id]
                            const percent = progress?.percent || (job.total_symbols > 0 ? Math.round((job.completed_symbols / job.total_symbols) * 100) : 0)

                            return (
                              <div key={job.id} className="p-4 hover:bg-muted/50 transition-colors">
                                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2 mb-1">
                                      <div className={cn("w-2 h-2 rounded-full", getJobStatusColor(job.status))} />
                                      <span className="font-medium truncate">Job {job.id}</span>
                                      <Badge variant="outline" className="text-xs">{job.job_type}</Badge>
                                      <Badge variant={job.status === 'running' ? 'default' : job.status === 'paused' ? 'secondary' : 'outline'} className="text-xs">
                                        {job.status}
                                      </Badge>
                                    </div>
                                    <div className="text-sm text-muted-foreground">
                                      {job.interval} | {job.start_date} to {job.end_date}
                                    </div>
                                    <div className="flex items-center gap-4 mt-2 text-sm">
                                      <span className="flex items-center gap-1">
                                        <CheckCircle className="h-3.5 w-3.5 text-green-500" />
                                        {job.completed_symbols}
                                      </span>
                                      {job.failed_symbols > 0 && (
                                        <span className="flex items-center gap-1 text-red-500">
                                          <XCircle className="h-3.5 w-3.5" />
                                          {job.failed_symbols}
                                        </span>
                                      )}
                                      <span className="text-muted-foreground">/ {job.total_symbols} total</span>
                                    </div>
                                    {(job.status === 'running' || job.status === 'paused') && (
                                      <div className="mt-2">
                                        <Progress value={percent} className="h-1.5" />
                                        {progress && (
                                          <div className="text-xs text-muted-foreground mt-1">
                                            Downloading: {progress.symbol} ({percent}%)
                                          </div>
                                        )}
                                      </div>
                                    )}
                                  </div>

                                  {/* Job Actions */}
                                  <div className="flex items-center gap-2">
                                    {job.status === 'running' && (
                                      <>
                                        <Button variant="outline" size="sm" onClick={() => pauseJob(job.id)}>
                                          <Pause className="h-4 w-4" />
                                        </Button>
                                        <Button variant="outline" size="sm" className="text-destructive" onClick={() => cancelJob(job.id)}>
                                          <Square className="h-4 w-4" />
                                        </Button>
                                      </>
                                    )}
                                    {job.status === 'paused' && (
                                      <>
                                        <Button variant="outline" size="sm" onClick={() => resumeJob(job.id)}>
                                          <Play className="h-4 w-4" />
                                        </Button>
                                        <Button variant="outline" size="sm" className="text-destructive" onClick={() => cancelJob(job.id)}>
                                          <Square className="h-4 w-4" />
                                        </Button>
                                      </>
                                    )}
                                    {(job.status === 'completed_with_errors' || job.status === 'failed') && job.failed_symbols > 0 && (
                                      <Button variant="outline" size="sm" onClick={() => retryJob(job.id)}>
                                        <RefreshCw className="h-4 w-4 mr-1" />
                                        Retry
                                      </Button>
                                    )}
                                    {job.status !== 'running' && job.status !== 'paused' && (
                                      <Button variant="ghost" size="sm" className="text-destructive" onClick={() => deleteJob(job.id)}>
                                        <Trash2 className="h-4 w-4" />
                                      </Button>
                                    )}
                                  </div>
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </ScrollArea>
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            {/* Scheduler Tab */}
            <TabsContent value="scheduler" className="h-full m-0 p-4 overflow-auto">
              <div className="space-y-4">
                {/* Header with Create button */}
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-semibold">Scheduled Downloads</h2>
                    <p className="text-sm text-muted-foreground">Automate data downloads on a schedule</p>
                  </div>
                  <Button onClick={() => openScheduleDialog()}>
                    <Plus className="h-4 w-4 mr-1" />
                    Create Schedule
                  </Button>
                </div>

                {/* Schedules List */}
                <Card>
                  <CardContent className="p-0">
                    {schedulesLoading ? (
                      <div className="flex items-center justify-center py-12">
                        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                      </div>
                    ) : schedules.length === 0 ? (
                      <div className="text-center py-12 text-muted-foreground">
                        <RefreshCw className="h-12 w-12 mx-auto mb-3 opacity-50" />
                        <p>No schedules created yet</p>
                        <p className="text-sm">Create a schedule to automate data downloads</p>
                      </div>
                    ) : (
                      <div className="divide-y divide-border">
                        {schedules.map((schedule) => (
                          <div key={schedule.id} className="p-4">
                            <div className="flex items-start justify-between">
                              <div className="flex-1">
                                <div className="flex items-center gap-2 mb-1">
                                  <h3 className="font-medium">{schedule.name}</h3>
                                  {getScheduleStatusBadge(schedule)}
                                  <Badge variant="outline">{schedule.data_interval === '1m' ? '1 Min' : 'Daily'}</Badge>
                                </div>
                                <p className="text-sm text-muted-foreground">
                                  {formatScheduleFrequency(schedule)}
                                  {schedule.description && ` - ${schedule.description}`}
                                </p>
                                <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                                  {schedule.next_run_at && (
                                    <span>Next: {new Date(schedule.next_run_at).toLocaleString()}</span>
                                  )}
                                  {schedule.last_run_at && (
                                    <span>Last: {new Date(schedule.last_run_at).toLocaleString()}</span>
                                  )}
                                  <span>Runs: {schedule.total_runs} ({schedule.successful_runs} ok, {schedule.failed_runs} failed)</span>
                                </div>
                              </div>
                              <div className="flex items-center gap-1">
                                {/* Enable/Disable Toggle */}
                                <Switch
                                  checked={schedule.is_enabled}
                                  onCheckedChange={() => handleToggleScheduleEnabled(schedule)}
                                  title={schedule.is_enabled ? 'Disable schedule' : 'Enable schedule'}
                                />
                                {/* Pause/Resume */}
                                {schedule.is_enabled && (
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8"
                                    onClick={() => handlePauseResumeSchedule(schedule)}
                                    title={schedule.is_paused ? 'Resume' : 'Pause'}
                                  >
                                    {schedule.is_paused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
                                  </Button>
                                )}
                                {/* Trigger Now */}
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8"
                                  onClick={() => handleTriggerSchedule(schedule.id)}
                                  disabled={!schedule.is_enabled || schedule.status === 'running'}
                                  title="Run now"
                                >
                                  <Zap className="h-4 w-4" />
                                </Button>
                                {/* Edit */}
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8"
                                  onClick={() => openScheduleDialog(schedule)}
                                  title="Edit"
                                >
                                  <Settings className="h-4 w-4" />
                                </Button>
                                {/* View History */}
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8"
                                  onClick={() => {
                                    if (expandedSchedule === schedule.id) {
                                      setExpandedSchedule(null)
                                    } else {
                                      setExpandedSchedule(schedule.id)
                                      loadScheduleExecutions(schedule.id)
                                    }
                                  }}
                                  title="View history"
                                >
                                  {expandedSchedule === schedule.id ? <X className="h-4 w-4" /> : <BarChart3 className="h-4 w-4" />}
                                </Button>
                                {/* Delete */}
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8 text-destructive hover:text-destructive"
                                  onClick={() => handleDeleteSchedule(schedule.id)}
                                  title="Delete"
                                >
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </div>
                            </div>

                            {/* Execution History (expandable) */}
                            {expandedSchedule === schedule.id && (
                              <div className="mt-4 pt-4 border-t border-border">
                                <h4 className="text-sm font-medium mb-2">Recent Executions</h4>
                                {!scheduleExecutions[schedule.id] || scheduleExecutions[schedule.id].length === 0 ? (
                                  <p className="text-sm text-muted-foreground">No executions yet</p>
                                ) : (
                                  <Table>
                                    <TableHeader>
                                      <TableRow>
                                        <TableHead>Time</TableHead>
                                        <TableHead>Status</TableHead>
                                        <TableHead className="text-right">Symbols</TableHead>
                                        <TableHead className="text-right">Records</TableHead>
                                        <TableHead>Error</TableHead>
                                      </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                      {scheduleExecutions[schedule.id].map((exec) => (
                                        <TableRow key={exec.id}>
                                          <TableCell className="text-sm">
                                            {new Date(exec.started_at).toLocaleString()}
                                          </TableCell>
                                          <TableCell>
                                            <Badge
                                              variant={exec.status === 'completed' ? 'default' : exec.status === 'running' ? 'secondary' : 'destructive'}
                                              className={exec.status === 'completed' ? 'bg-green-500' : exec.status === 'running' ? 'bg-blue-500' : ''}
                                            >
                                              {exec.status}
                                            </Badge>
                                          </TableCell>
                                          <TableCell className="text-right text-sm">
                                            {exec.symbols_success}/{exec.symbols_processed}
                                            {exec.symbols_failed > 0 && (
                                              <span className="text-destructive ml-1">({exec.symbols_failed} failed)</span>
                                            )}
                                          </TableCell>
                                          <TableCell className="text-right text-sm">
                                            {exec.records_downloaded.toLocaleString()}
                                          </TableCell>
                                          <TableCell className="text-sm text-destructive max-w-[200px] truncate">
                                            {exec.error_message}
                                          </TableCell>
                                        </TableRow>
                                      ))}
                                    </TableBody>
                                  </Table>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            </TabsContent>
          </div>
        </Tabs>
      </div>

      {/* Schedule Dialog */}
      <Dialog open={scheduleDialogOpen} onOpenChange={(open) => {
        setScheduleDialogOpen(open)
        if (!open) resetScheduleForm()
      }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingSchedule ? 'Edit Schedule' : 'Create Schedule'}</DialogTitle>
            <DialogDescription>
              {editingSchedule ? 'Update schedule configuration' : 'Set up automated data downloads'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Name</Label>
              <Input
                value={scheduleName}
                onChange={(e) => setScheduleName(e.target.value)}
                placeholder="Daily Watchlist Update"
                className="mt-1"
              />
            </div>
            <div>
              <Label>Description (optional)</Label>
              <Input
                value={scheduleDescription}
                onChange={(e) => setScheduleDescription(e.target.value)}
                placeholder="Downloads daily data for all watchlist symbols"
                className="mt-1"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Schedule Type</Label>
                <Select value={scheduleType} onValueChange={(v) => setScheduleType(v as 'interval' | 'daily')}>
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="interval">Interval</SelectItem>
                    <SelectItem value="daily">Daily</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Data Interval</Label>
                <Select value={scheduleDataInterval} onValueChange={(v) => setScheduleDataInterval(v as '1m' | 'D')}>
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1m">1 Minute</SelectItem>
                    <SelectItem value="D">Daily</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {scheduleType === 'interval' ? (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>Every</Label>
                  <Select value={String(scheduleIntervalValue)} onValueChange={(v) => setScheduleIntervalValue(parseInt(v))}>
                    <SelectTrigger className="mt-1">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="1">1</SelectItem>
                      <SelectItem value="5">5</SelectItem>
                      <SelectItem value="15">15</SelectItem>
                      <SelectItem value="30">30</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Unit</Label>
                  <Select value={scheduleIntervalUnit} onValueChange={(v) => setScheduleIntervalUnit(v as 'minutes' | 'hours')}>
                    <SelectTrigger className="mt-1">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="minutes">Minutes</SelectItem>
                      <SelectItem value="hours">Hours</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            ) : (
              <div>
                <Label>Time of Day (IST)</Label>
                <div className="flex gap-2 mt-1">
                  <Select
                    value={(() => {
                      const [h] = scheduleTimeOfDay.split(':').map(Number)
                      const hour12 = h === 0 ? 12 : h > 12 ? h - 12 : h
                      return hour12.toString()
                    })()}
                    onValueChange={(v) => {
                      const [h, m] = scheduleTimeOfDay.split(':').map(Number)
                      const isPM = h >= 12
                      let newHour = parseInt(v)
                      if (isPM) {
                        newHour = newHour === 12 ? 12 : newHour + 12
                      } else {
                        newHour = newHour === 12 ? 0 : newHour
                      }
                      setScheduleTimeOfDay(`${newHour.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`)
                    }}
                  >
                    <SelectTrigger className="w-20">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {[12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((h) => (
                        <SelectItem key={h} value={h.toString()}>{h}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <span className="flex items-center">:</span>
                  <Select
                    value={scheduleTimeOfDay.split(':')[1] || '00'}
                    onValueChange={(v) => {
                      const [h] = scheduleTimeOfDay.split(':').map(Number)
                      setScheduleTimeOfDay(`${h.toString().padStart(2, '0')}:${v}`)
                    }}
                  >
                    <SelectTrigger className="w-20">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {['00', '15', '30', '45'].map((m) => (
                        <SelectItem key={m} value={m}>{m}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Select
                    value={parseInt(scheduleTimeOfDay.split(':')[0]) >= 12 ? 'PM' : 'AM'}
                    onValueChange={(v) => {
                      const [h, m] = scheduleTimeOfDay.split(':').map(Number)
                      const hour12 = h === 0 ? 12 : h > 12 ? h - 12 : h
                      let newHour: number
                      if (v === 'PM') {
                        newHour = hour12 === 12 ? 12 : hour12 + 12
                      } else {
                        newHour = hour12 === 12 ? 0 : hour12
                      }
                      setScheduleTimeOfDay(`${newHour.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`)
                    }}
                  >
                    <SelectTrigger className="w-20">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="AM">AM</SelectItem>
                      <SelectItem value="PM">PM</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            )}

            <div>
              <Label>Lookback Days</Label>
              <Input
                type="number"
                min="1"
                max="30"
                value={scheduleLookbackDays}
                onChange={(e) => setScheduleLookbackDays(parseInt(e.target.value) || 1)}
                className="mt-1"
              />
              <p className="text-xs text-muted-foreground mt-1">Incremental download from watchlist. Lookback used only for new symbols.</p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => {
              setScheduleDialogOpen(false)
              resetScheduleForm()
            }}>
              Cancel
            </Button>
            <Button onClick={handleCreateOrUpdateSchedule} disabled={isCreatingSchedule}>
              {isCreatingSchedule && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              {editingSchedule ? 'Update' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk Add Dialog */}
      <Dialog open={bulkAddDialogOpen} onOpenChange={setBulkAddDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Bulk Add Symbols</DialogTitle>
            <DialogDescription>Add multiple symbols at once. One per line: SYMBOL,EXCHANGE</DialogDescription>
          </DialogHeader>
          <Textarea
            placeholder="RELIANCE,NSE
INFY,NSE
NIFTY24DEC25000CE,NFO"
            value={bulkAddText}
            onChange={(e) => setBulkAddText(e.target.value)}
            rows={8}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkAddDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleBulkAdd} disabled={isBulkAdding}>
              {isBulkAdding && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              Add Symbols
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Upload Dialog */}
      <Dialog open={uploadDialogOpen} onOpenChange={setUploadDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Import Data</DialogTitle>
            <DialogDescription>Upload a CSV or Parquet file with OHLCV data</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Symbol</Label>
              <Input
                value={uploadSymbol}
                onChange={(e) => setUploadSymbol(e.target.value.toUpperCase())}
                placeholder="RELIANCE"
                className="mt-1"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Exchange</Label>
                <Select value={uploadExchange} onValueChange={setUploadExchange}>
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {exchanges.map((ex) => (
                      <SelectItem key={ex} value={ex}>{ex}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Interval</Label>
                <Select value={uploadInterval} onValueChange={setUploadInterval}>
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(historifyIntervals?.storage_intervals || ['1m', 'D']).map((int) => (
                      <SelectItem key={int} value={int}>
                        {int === '1m' ? '1 Minute' : int === 'D' ? 'Daily' : int}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground mt-1">
                  Only 1min and Daily data can be stored
                </p>
              </div>
            </div>
            <div>
              <Label>Data File</Label>
              <Input
                ref={fileInputRef}
                type="file"
                accept=".csv,.parquet"
                onChange={handleFileChange}
                className="mt-1"
              />
              {uploadFile && (
                <p className="text-sm text-muted-foreground mt-1">Selected: {uploadFile.name}</p>
              )}
              <p className="text-xs text-muted-foreground mt-2">
                Download sample: {' '}
                <a href="/historify/api/sample/csv" className="text-primary hover:underline">CSV</a>
                {' | '}
                <a href="/historify/api/sample/parquet" className="text-primary hover:underline">Parquet</a>
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setUploadDialogOpen(false)}>Cancel</Button>
            <Button onClick={uploadCSVData} disabled={isUploading}>
              {isUploading && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              Upload
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Export Dialog */}
      <Dialog open={exportDialogOpen} onOpenChange={setExportDialogOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Export Data</DialogTitle>
            <DialogDescription>Export historical data with multiple timeframes</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Export Format</Label>
                <Select value={exportFormat} onValueChange={(v: any) => setExportFormat(v)}>
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="zip">ZIP Archive (Recommended)</SelectItem>
                    <SelectItem value="csv">CSV (Single file)</SelectItem>
                    <SelectItem value="parquet">Parquet (ZSTD)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Symbols to Export</Label>
                <Select value={exportSymbols} onValueChange={(v: any) => setExportSymbols(v)}>
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All ({groupedCatalog.length} symbols)</SelectItem>
                    <SelectItem value="selected">
                      Selected ({catalogSelectedSymbols.size})
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Timeframe Selection */}
            <div>
              <Label className="mb-2 block">Select Timeframes to Export</Label>
              <p className="text-xs text-muted-foreground mb-3">
                Intraday computed from 1m data. W/M/Q/Y computed from Daily data.
              </p>
              <div className="grid grid-cols-5 sm:grid-cols-10 gap-2">
                {['1m', '5m', '15m', '30m', '1h', 'D', 'W', 'M', 'Q', 'Y'].map((int) => {
                  const isIntradayComputed = ['5m', '15m', '30m', '1h'].includes(int)
                  const isDailyComputed = ['W', 'M', 'Q', 'Y'].includes(int)
                  const isComputed = isIntradayComputed || isDailyComputed
                  const isSelected = exportIntervals.has(int)
                  return (
                    <div
                      key={int}
                      className={cn(
                        "flex flex-col items-center p-2 rounded-lg border cursor-pointer transition-colors",
                        isSelected ? "bg-primary text-primary-foreground border-primary" : "bg-muted/50 hover:bg-muted"
                      )}
                      onClick={() => {
                        setExportIntervals((prev) => {
                          const next = new Set(prev)
                          if (next.has(int)) next.delete(int)
                          else next.add(int)
                          return next
                        })
                      }}
                    >
                      <Checkbox
                        checked={isSelected}
                        className={cn("mb-1", isSelected && "border-primary-foreground")}
                        onClick={(e) => e.stopPropagation()}
                        onCheckedChange={() => {
                          setExportIntervals((prev) => {
                            const next = new Set(prev)
                            if (next.has(int)) next.delete(int)
                            else next.add(int)
                            return next
                          })
                        }}
                      />
                      <span className="font-medium text-sm">{int}</span>
                      <span className={cn("text-[10px]", isSelected ? "opacity-80" : "text-muted-foreground")}>
                        {isComputed ? 'Computed' : 'Stored'}
                      </span>
                    </div>
                  )
                })}
              </div>

              {/* Custom Interval Input */}
              <div className="mt-3 pt-3 border-t">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">Custom:</span>
                  <Input
                    type="number"
                    min="1"
                    max="999"
                    value={customExportValue}
                    onChange={(e) => setCustomExportValue(e.target.value)}
                    className="h-8 w-14 text-center"
                    placeholder="1"
                  />
                  <Select value={customExportUnit} onValueChange={(v) => setCustomExportUnit(v as 'm' | 'h' | 'W' | 'M' | 'Q' | 'Y')}>
                    <SelectTrigger className="w-20 h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="m">min</SelectItem>
                      <SelectItem value="h">hr</SelectItem>
                      <SelectItem value="W">Week</SelectItem>
                      <SelectItem value="M">Month</SelectItem>
                      <SelectItem value="Q">Qtr</SelectItem>
                      <SelectItem value="Y">Year</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8"
                    onClick={() => {
                      const val = parseInt(customExportValue) || 1
                      // For W, M, Q, Y with value 1, just use the unit
                      let customInterval: string
                      if (['W', 'M', 'Q', 'Y'].includes(customExportUnit)) {
                        customInterval = val === 1 ? customExportUnit : `${val}${customExportUnit}`
                      } else {
                        customInterval = `${customExportValue}${customExportUnit}`
                      }
                      if (val > 0) {
                        setExportIntervals((prev) => new Set([...prev, customInterval]))
                      }
                    }}
                  >
                    <Plus className="h-4 w-4 mr-1" />
                    Add
                  </Button>
                </div>
                {/* Show added custom intervals */}
                {Array.from(exportIntervals).filter(int => !['1m', '5m', '15m', '30m', '1h', 'D', 'W', 'M', 'Q', 'Y'].includes(int)).length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {Array.from(exportIntervals).filter(int => !['1m', '5m', '15m', '30m', '1h', 'D', 'W', 'M', 'Q', 'Y'].includes(int)).map(int => (
                      <Badge
                        key={int}
                        variant="secondary"
                        className="cursor-pointer hover:bg-destructive hover:text-destructive-foreground"
                        onClick={() => {
                          setExportIntervals((prev) => {
                            const next = new Set(prev)
                            next.delete(int)
                            return next
                          })
                        }}
                      >
                        {int} <X className="h-3 w-3 ml-1" />
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Symbol Selection */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <Label className="text-sm">
                  {exportSymbols === 'selected' ? 'Selected Symbols' : 'All Symbols'} ({exportSymbols === 'selected' ? catalogSelectedSymbols.size : groupedCatalog.length})
                </Label>
                {exportSymbols === 'selected' && (
                  <div className="flex gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 text-xs"
                      onClick={() => {
                        const allKeys = groupedCatalog.map(item => `${item.symbol}:${item.exchange}`)
                        setCatalogSelectedSymbols(new Set(allKeys))
                      }}
                    >
                      Select All
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 text-xs"
                      onClick={() => setCatalogSelectedSymbols(new Set())}
                    >
                      Clear
                    </Button>
                  </div>
                )}
              </div>
              <ScrollArea className="h-40 border rounded-md p-2">
                <div className="space-y-1">
                  {groupedCatalog.map((item) => {
                    const key = `${item.symbol}:${item.exchange}`
                    const isSelected = catalogSelectedSymbols.has(key)

                    if (exportSymbols === 'all') {
                      // Show all symbols (no selection UI in "all" mode)
                      return (
                        <div key={key} className="flex items-center justify-between text-sm py-1 border-b border-border/50 last:border-0">
                          <span className="font-medium">{item.symbol}</span>
                          <Badge variant="outline" className="text-xs">{item.exchange}</Badge>
                        </div>
                      )
                    } else {
                      // Show selectable list in "selected" mode
                      return (
                        <div
                          key={key}
                          className={cn(
                            "flex items-center gap-2 text-sm py-1.5 px-2 rounded cursor-pointer transition-colors border-b border-border/50 last:border-0",
                            isSelected ? "bg-primary/10" : "hover:bg-muted/50"
                          )}
                          onClick={() => {
                            setCatalogSelectedSymbols((prev) => {
                              const next = new Set(prev)
                              if (next.has(key)) next.delete(key)
                              else next.add(key)
                              return next
                            })
                          }}
                        >
                          <Checkbox
                            checked={isSelected}
                            onCheckedChange={() => {
                              setCatalogSelectedSymbols((prev) => {
                                const next = new Set(prev)
                                if (next.has(key)) next.delete(key)
                                else next.add(key)
                                return next
                              })
                            }}
                            onClick={(e) => e.stopPropagation()}
                          />
                          <span className="font-medium flex-1">{item.symbol}</span>
                          <Badge variant="outline" className="text-xs">{item.exchange}</Badge>
                        </div>
                      )
                    }
                  })}
                </div>
              </ScrollArea>
            </div>

            {/* Export Summary */}
            <div className="bg-muted/50 rounded-lg p-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Export Summary:</span>
                <span className="font-medium">
                  {exportSymbols === 'selected' ? catalogSelectedSymbols.size : groupedCatalog.length} symbols x {exportIntervals.size} timeframe{exportIntervals.size !== 1 ? 's' : ''}
                </span>
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                Files: {Array.from(exportIntervals).sort().join(', ')}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setExportDialogOpen(false)}>Cancel</Button>
            <Button
              onClick={handleBulkExport}
              disabled={isExporting || exportIntervals.size === 0 || (exportSymbols === 'selected' && catalogSelectedSymbols.size === 0)}
            >
              {isExporting && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              Export ({exportIntervals.size} timeframe{exportIntervals.size !== 1 ? 's' : ''})
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Data</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete all data for {deleteTarget?.symbol} ({deleteTarget?.exchange})?
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteData} className="bg-destructive text-destructive-foreground">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Bulk Delete Confirmation Dialog */}
      <AlertDialog open={bulkDeleteDialogOpen} onOpenChange={setBulkDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {catalogSelectedSymbols.size} Symbol(s)</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete all data for the selected symbols? This will remove all historical data for:
              <div className="mt-2 max-h-32 overflow-y-auto text-sm">
                {Array.from(catalogSelectedSymbols).slice(0, 10).map((key) => (
                  <div key={key} className="text-foreground">{key.replace(':', ' - ')}</div>
                ))}
                {catalogSelectedSymbols.size > 10 && (
                  <div className="text-muted-foreground">...and {catalogSelectedSymbols.size - 10} more</div>
                )}
              </div>
              <div className="mt-2 font-medium text-destructive">This action cannot be undone.</div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isBulkDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleBulkDeleteData}
              className="bg-destructive text-destructive-foreground"
              disabled={isBulkDeleting}
            >
              {isBulkDeleting ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Deleting...
                </>
              ) : (
                `Delete ${catalogSelectedSymbols.size} Symbol(s)`
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Bulk Watchlist Delete Confirmation Dialog */}
      <AlertDialog open={bulkWatchlistDeleteDialogOpen} onOpenChange={setBulkWatchlistDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove {watchlistSelectedSymbols.size} Symbol(s) from Watchlist</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to remove the selected symbols from your watchlist?
              <div className="mt-2 max-h-32 overflow-y-auto text-sm">
                {Array.from(watchlistSelectedSymbols).slice(0, 10).map((key) => (
                  <div key={key} className="text-foreground">{key.replace(':', ' - ')}</div>
                ))}
                {watchlistSelectedSymbols.size > 10 && (
                  <div className="text-muted-foreground">...and {watchlistSelectedSymbols.size - 10} more</div>
                )}
              </div>
              <div className="mt-2 text-muted-foreground text-sm">This will not delete any downloaded historical data.</div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isBulkWatchlistDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleBulkWatchlistDelete}
              className="bg-destructive text-destructive-foreground"
              disabled={isBulkWatchlistDeleting}
            >
              {isBulkWatchlistDeleting ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Removing...
                </>
              ) : (
                `Remove ${watchlistSelectedSymbols.size} Symbol(s)`
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

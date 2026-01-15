import {
  BarChart3,
  CheckCircle,
  Clock,
  Database,
  Download,
  DownloadCloud,
  FileDown,
  HardDrive,
  LineChart,
  ListPlus,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  Settings,
  Square,
  Target,
  Trash2,
  TrendingUp,
  Upload,
  X,
  XCircle,
  Zap,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Switch } from '@/components/ui/switch'
import { useSocket } from '@/hooks/useSocket'
import { cn } from '@/lib/utils'
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

interface IntervalData {
  seconds: string[]
  minutes: string[]
  hours: string[]
  days: string[]
  weeks: string[]
  months: string[]
}

interface FNOSymbol {
  symbol: string
  name: string
  exchange: string
  token: string
  expiry?: string
  strike?: number
  lotsize?: number
  instrumenttype?: string
  tick_size?: number
}

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
  const { appMode, toggleAppMode } = useThemeStore()

  // Core state
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([])
  const [catalog, setCatalog] = useState<CatalogItem[]>([])
  const [intervals, setIntervals] = useState<IntervalData | null>(null)
  const [historifyIntervals, setHistorifyIntervals] = useState<{
    storage_intervals: string[]
    computed_intervals: string[]
    all_intervals: string[]
  } | null>(null)
  const [exchanges, setExchanges] = useState<string[]>(['NSE', 'BSE', 'NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NSE_INDEX', 'BSE_INDEX'])
  const [stats, setStats] = useState<Stats>({ database_size_mb: 0, total_records: 0, total_symbols: 0, watchlist_count: 0 })

  // Tab state
  const [activeTab, setActiveTab] = useState<string>('catalog')

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

  // FNO Discovery state
  const [fnoExchange, setFnoExchange] = useState<string>('NFO')
  const [fnoUnderlyings, setFnoUnderlyings] = useState<string[]>([])
  const [fnoSelectedUnderlying, setFnoSelectedUnderlying] = useState<string>('')
  const [fnoExpiries, setFnoExpiries] = useState<string[]>([])
  const [fnoSelectedExpiry, setFnoSelectedExpiry] = useState<string>('')
  const [fnoInstrumentType, setFnoInstrumentType] = useState<string>('__all__')
  const [fnoStrikeMin, setFnoStrikeMin] = useState<string>('')
  const [fnoStrikeMax, setFnoStrikeMax] = useState<string>('')
  const [fnoSymbols, setFnoSymbols] = useState<FNOSymbol[]>([])
  const [fnoSelectedSymbols, setFnoSelectedSymbols] = useState<Set<string>>(new Set())
  const [fnoLoading, setFnoLoading] = useState(false)

  // Job management state
  const [jobs, setJobs] = useState<DownloadJob[]>([])
  const [selectedJob, setSelectedJob] = useState<DownloadJob | null>(null)
  const [jobProgress, setJobProgress] = useState<Record<string, JobProgress>>({})
  const [jobsLoading, setJobsLoading] = useState(false)

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

  // Export dialog state
  const [exportDialogOpen, setExportDialogOpen] = useState(false)
  const [exportFormat, setExportFormat] = useState<'csv' | 'txt' | 'zip' | 'parquet'>('csv')
  const [exportSymbols, setExportSymbols] = useState<'all' | 'selected'>('all')
  const [catalogSelectedSymbols, setCatalogSelectedSymbols] = useState<Set<string>>(new Set())
  const [isExporting, setIsExporting] = useState(false)

  // Catalog filtering
  const [catalogFilter, setCatalogFilter] = useState({ exchange: '', interval: '', search: '' })

  // Socket.IO for real-time progress
  const { socket } = useSocket()

  // Computed values
  const allIntervals = intervals
    ? [...intervals.seconds, ...intervals.minutes, ...intervals.hours, ...intervals.days, ...intervals.weeks, ...intervals.months]
    : ['D']

  const filteredCatalog = useMemo(() => {
    return catalog.filter((item) => {
      if (catalogFilter.exchange && catalogFilter.exchange !== '__all__' && item.exchange !== catalogFilter.exchange) return false
      if (catalogFilter.interval && catalogFilter.interval !== '__all__' && item.interval !== catalogFilter.interval) return false
      if (catalogFilter.search && !item.symbol.toLowerCase().includes(catalogFilter.search.toLowerCase())) return false
      return true
    })
  }, [catalog, catalogFilter])

  // Load data on mount
  useEffect(() => {
    loadWatchlist()
    loadCatalog()
    loadIntervals()
    loadHistorifyIntervals()
    loadStats()
    loadExchanges()
    loadJobs()
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
      toast.success(`Job completed: ${data.completed} success, ${data.failed} failed`)
    }

    const handleJobPaused = (data: { job_id: string }) => {
      setJobs((prevJobs) =>
        prevJobs.map((job) => (job.id === data.job_id ? { ...job, status: 'paused' } : job))
      )
    }

    socket.on('historify_progress', handleProgress)
    socket.on('historify_job_complete', handleJobComplete)
    socket.on('historify_job_paused', handleJobPaused)

    return () => {
      socket.off('historify_progress', handleProgress)
      socket.off('historify_job_complete', handleJobComplete)
      socket.off('historify_job_paused', handleJobPaused)
    }
  }, [socket])

  // FNO data loading
  useEffect(() => {
    if (fnoExchange) loadFnoUnderlyings()
  }, [fnoExchange])

  useEffect(() => {
    if (fnoSelectedUnderlying && fnoExchange) loadFnoExpiries()
  }, [fnoSelectedUnderlying, fnoExchange])

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
      console.error('Error loading watchlist:', error)
    }
  }

  const loadCatalog = async () => {
    try {
      const response = await fetch('/historify/api/catalog', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') setCatalog(data.data || [])
    } catch (error) {
      console.error('Error loading catalog:', error)
    }
  }

  const loadIntervals = async () => {
    try {
      const response = await fetch('/historify/api/intervals', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') setIntervals(data.data)
    } catch (error) {
      console.error('Error loading intervals:', error)
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
      console.error('Error loading historify intervals:', error)
    }
  }

  const loadStats = async () => {
    try {
      const response = await fetch('/historify/api/stats', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') setStats(data.data)
    } catch (error) {
      console.error('Error loading stats:', error)
    }
  }

  const loadExchanges = async () => {
    try {
      const response = await fetch('/historify/api/exchanges', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success' && data.data?.length > 0) setExchanges(data.data)
    } catch (error) {
      console.error('Error loading exchanges:', error)
    }
  }

  const loadJobs = async () => {
    setJobsLoading(true)
    try {
      const response = await fetch('/historify/api/jobs?limit=50', { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') setJobs(data.data || [])
    } catch (error) {
      console.error('Error loading jobs:', error)
    } finally {
      setJobsLoading(false)
    }
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
      console.error('Error searching symbols:', error)
      setSearchResults([])
    }
  }

  // Watchlist operations
  const addToWatchlist = async () => {
    if (!newSymbol.trim()) {
      toast.warning('Please enter a symbol')
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
        toast.success(data.message)
        setNewSymbol('')
        loadWatchlist()
        loadStats()
      } else {
        toast.error(data.message || 'Failed to add symbol')
      }
    } catch (error) {
      console.error('Error adding to watchlist:', error)
      toast.error('Failed to add symbol')
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
        toast.success(data.message)
        loadWatchlist()
        loadStats()
      } else {
        toast.error(data.message || 'Failed to remove symbol')
      }
    } catch (error) {
      console.error('Error removing from watchlist:', error)
      toast.error('Failed to remove symbol')
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
      toast.warning('No valid symbols found')
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
        toast.success(`Added ${data.added} symbols`)
        setBulkAddDialogOpen(false)
        setBulkAddText('')
        loadWatchlist()
        loadStats()
      } else {
        toast.error(data.message || 'Failed to bulk add symbols')
      }
    } catch (error) {
      console.error('Error bulk adding:', error)
      toast.error('Failed to bulk add symbols')
    } finally {
      setIsBulkAdding(false)
    }
  }

  // FNO Discovery functions
  const loadFnoUnderlyings = async () => {
    try {
      const response = await fetch(`/historify/api/fno/underlyings?exchange=${fnoExchange}`, { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') {
        setFnoUnderlyings(data.data || [])
        setFnoSelectedUnderlying('')
        setFnoExpiries([])
        setFnoSelectedExpiry('')
        setFnoSymbols([])
      }
    } catch (error) {
      console.error('Error loading FNO underlyings:', error)
    }
  }

  const loadFnoExpiries = async () => {
    try {
      const params = new URLSearchParams({ underlying: fnoSelectedUnderlying, exchange: fnoExchange })
      const response = await fetch(`/historify/api/fno/expiries?${params}`, { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') {
        setFnoExpiries(data.data || [])
        setFnoSelectedExpiry('')
      }
    } catch (error) {
      console.error('Error loading FNO expiries:', error)
    }
  }

  const loadFnoChain = async () => {
    if (!fnoSelectedUnderlying) {
      toast.warning('Please select an underlying')
      return
    }
    setFnoLoading(true)
    try {
      const params = new URLSearchParams({ underlying: fnoSelectedUnderlying, exchange: fnoExchange, limit: '5000' })
      if (fnoSelectedExpiry) params.append('expiry', fnoSelectedExpiry)
      if (fnoInstrumentType && fnoInstrumentType !== '__all__') params.append('instrumenttype', fnoInstrumentType)
      if (fnoStrikeMin) params.append('strike_min', fnoStrikeMin)
      if (fnoStrikeMax) params.append('strike_max', fnoStrikeMax)

      const response = await fetch(`/historify/api/fno/chain?${params}`, { credentials: 'include' })
      const data = await response.json()
      if (data.status === 'success') {
        setFnoSymbols(data.data || [])
        setFnoSelectedSymbols(new Set())
        toast.success(`Found ${data.count} symbols`)
      } else {
        toast.error(data.message || 'Failed to load FNO chain')
      }
    } catch (error) {
      console.error('Error loading FNO chain:', error)
      toast.error('Failed to load FNO chain')
    } finally {
      setFnoLoading(false)
    }
  }

  // Job operations
  const createDownloadJob = async (symbols: { symbol: string; exchange: string }[], jobType: string = 'custom') => {
    if (symbols.length === 0) {
      toast.warning('No symbols selected')
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
        toast.success(`Job started: ${data.total_symbols} symbols`)
        loadJobs()
        setActiveTab('jobs')
      } else {
        toast.error(data.message || 'Failed to create job')
      }
    } catch (error) {
      console.error('Error creating job:', error)
      toast.error('Failed to create job')
    }
  }

  const downloadWatchlist = async () => {
    if (watchlist.length === 0) {
      toast.warning('Watchlist is empty')
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
        toast.success('Job paused')
        loadJobs()
      } else {
        toast.error(data.message || 'Failed to pause job')
      }
    } catch (error) {
      console.error('Error pausing job:', error)
      toast.error('Failed to pause job')
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
        toast.success('Job resumed')
        loadJobs()
      } else {
        toast.error(data.message || 'Failed to resume job')
      }
    } catch (error) {
      console.error('Error resuming job:', error)
      toast.error('Failed to resume job')
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
        toast.success('Job cancellation requested')
        loadJobs()
      } else {
        toast.error(data.message || 'Failed to cancel job')
      }
    } catch (error) {
      console.error('Error cancelling job:', error)
      toast.error('Failed to cancel job')
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
        toast.success(`Retrying ${data.retry_count} failed items`)
        loadJobs()
      } else {
        toast.error(data.message || 'Failed to retry job')
      }
    } catch (error) {
      console.error('Error retrying job:', error)
      toast.error('Failed to retry job')
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
        toast.success('Job deleted')
        loadJobs()
        if (selectedJob?.id === jobId) {
          setSelectedJob(null)
        }
      } else {
        toast.error(data.message || 'Failed to delete job')
      }
    } catch (error) {
      console.error('Error deleting job:', error)
      toast.error('Failed to delete job')
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
        toast.success(data.message)
        loadCatalog()
        loadStats()
      } else {
        toast.error(data.message || 'Failed to delete data')
      }
    } catch (error) {
      console.error('Error deleting data:', error)
      toast.error('Failed to delete data')
    } finally {
      setDeleteDialogOpen(false)
      setDeleteTarget(null)
    }
  }

  // CSV Upload
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      if (!file.name.toLowerCase().endsWith('.csv')) {
        toast.error('Please select a CSV file')
        return
      }
      setUploadFile(file)
    }
  }

  const uploadCSVData = async () => {
    if (!uploadFile) {
      toast.warning('Please select a CSV file')
      return
    }
    if (!uploadSymbol.trim()) {
      toast.warning('Please enter a symbol')
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
        toast.success(`${data.message}`)
        setUploadDialogOpen(false)
        setUploadFile(null)
        setUploadSymbol('')
        if (fileInputRef.current) fileInputRef.current.value = ''
        loadCatalog()
        loadStats()
      } else {
        toast.error(data.message || 'Failed to upload data')
      }
    } catch (error) {
      console.error('Error uploading CSV:', error)
      toast.error('Failed to upload CSV')
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
        : null

      const response = await fetch('/historify/api/export/bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        credentials: 'include',
        body: JSON.stringify({
          format: exportFormat,
          symbols,
          compression: 'zstd',
        }),
      })
      const data = await response.json()
      if (data.status === 'success') {
        toast.success(`${data.message}`)
        window.location.href = '/historify/api/export/bulk/download'
        setExportDialogOpen(false)
      } else {
        toast.error(data.message || 'Failed to export data')
      }
    } catch (error) {
      console.error('Error exporting data:', error)
      toast.error('Failed to export data')
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

  const toggleFnoSymbol = (symbol: string) => {
    setFnoSelectedSymbols((prev) => {
      const next = new Set(prev)
      if (next.has(symbol)) next.delete(symbol)
      else next.add(symbol)
      return next
    })
  }

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
      toast.success(`Switched to ${newMode === 'live' ? 'Live' : 'Analyze'} mode`)
    } else {
      toast.error(result.message || 'Failed to toggle mode')
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

          {/* Mode Toggle */}
          <div className="flex items-center gap-2">
            <Badge variant={appMode === 'live' ? 'default' : 'secondary'} className="cursor-pointer" onClick={handleModeToggle}>
              {appMode === 'live' ? <Zap className="h-3 w-3 mr-1" /> : <Clock className="h-3 w-3 mr-1" />}
              {appMode === 'live' ? 'Live' : 'Analyze'}
            </Badge>
            <Link to="/historify/charts">
              <Button variant="outline" size="sm">
                <LineChart className="h-4 w-4 mr-1" />
                <span className="hidden sm:inline">Charts</span>
              </Button>
            </Link>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-hidden">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="h-full flex flex-col">
          {/* Tab Navigation - Scrollable on mobile */}
          <div className="border-b border-border px-4 overflow-x-auto">
            <TabsList className="h-10 bg-transparent w-max min-w-full sm:w-auto">
              <TabsTrigger value="catalog" className="gap-1.5 data-[state=active]:bg-muted">
                <Database className="h-4 w-4" />
                <span className="hidden sm:inline">Data Catalog</span>
                <span className="sm:hidden">Catalog</span>
              </TabsTrigger>
              <TabsTrigger value="watchlist" className="gap-1.5 data-[state=active]:bg-muted">
                <Target className="h-4 w-4" />
                <span className="hidden sm:inline">Watchlist</span>
                <span className="sm:hidden">Watch</span>
                {watchlist.length > 0 && (
                  <Badge variant="secondary" className="ml-1 h-5 min-w-5 text-xs">{watchlist.length}</Badge>
                )}
              </TabsTrigger>
              <TabsTrigger value="fno" className="gap-1.5 data-[state=active]:bg-muted">
                <Search className="h-4 w-4" />
                <span className="hidden sm:inline">FNO Discovery</span>
                <span className="sm:hidden">FNO</span>
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
            </TabsList>
          </div>

          {/* Tab Content */}
          <div className="flex-1 overflow-hidden">
            {/* Data Catalog Tab */}
            <TabsContent value="catalog" className="h-full m-0 p-4 overflow-auto">
              <div className="space-y-4">
                {/* Filters */}
                <Card>
                  <CardContent className="p-4">
                    <div className="flex flex-col sm:flex-row gap-3">
                      <div className="flex-1">
                        <Input
                          placeholder="Search symbols..."
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
                        <SelectTrigger className="w-full sm:w-24 h-9">
                          <SelectValue placeholder="Interval" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__all__">All</SelectItem>
                          {allIntervals.map((int) => (
                            <SelectItem key={int} value={int}>{int}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <div className="flex gap-2">
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

                {/* Catalog Table */}
                <Card>
                  <ScrollArea className="h-[calc(100vh-320px)]">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-10">
                            <Checkbox
                              checked={catalogSelectedSymbols.size === filteredCatalog.length && filteredCatalog.length > 0}
                              onCheckedChange={(checked) => {
                                if (checked) {
                                  setCatalogSelectedSymbols(new Set(filteredCatalog.map((c) => `${c.symbol}:${c.exchange}`)))
                                } else {
                                  setCatalogSelectedSymbols(new Set())
                                }
                              }}
                            />
                          </TableHead>
                          <TableHead>Symbol</TableHead>
                          <TableHead className="hidden sm:table-cell">Exchange</TableHead>
                          <TableHead className="hidden sm:table-cell">Interval</TableHead>
                          <TableHead className="text-right">Records</TableHead>
                          <TableHead className="hidden md:table-cell">Date Range</TableHead>
                          <TableHead className="w-20"></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filteredCatalog.length === 0 ? (
                          <TableRow>
                            <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                              No data available. Add symbols to watchlist and download data.
                            </TableCell>
                          </TableRow>
                        ) : (
                          filteredCatalog.map((item) => (
                            <TableRow key={`${item.symbol}-${item.exchange}-${item.interval}`}>
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
                              <TableCell className="hidden sm:table-cell">{item.interval}</TableCell>
                              <TableCell className="text-right">{item.record_count.toLocaleString()}</TableCell>
                              <TableCell className="hidden md:table-cell text-muted-foreground text-sm">
                                {item.first_date} - {item.last_date}
                              </TableCell>
                              <TableCell>
                                <div className="flex gap-1">
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-7 w-7"
                                    asChild
                                  >
                                    <Link to={`/historify/charts/${item.symbol}?exchange=${item.exchange}&interval=${item.interval}`}>
                                      <LineChart className="h-3.5 w-3.5" />
                                    </Link>
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-7 w-7 text-destructive hover:text-destructive"
                                    onClick={() => {
                                      setDeleteTarget({ symbol: item.symbol, exchange: item.exchange, interval: item.interval })
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

            {/* Watchlist Tab */}
            <TabsContent value="watchlist" className="h-full m-0 p-4 overflow-auto">
              <div className="space-y-4">
                {/* Add Symbol Form */}
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">Add Symbol</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-col sm:flex-row gap-3">
                      <div className="flex-1 relative" ref={searchContainerRef}>
                        <Input
                          placeholder="Search symbol..."
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

                {/* Download Settings */}
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2">
                      <Settings className="h-4 w-4" />
                      Download Settings
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-4">
                      {/* Date Range Quick Buttons */}
                      <div>
                        <Label className="text-sm text-muted-foreground mb-2 block">Quick Date Range</Label>
                        <div className="flex flex-wrap gap-2">
                          {DATE_PRESETS.map((preset) => (
                            <Button
                              key={preset.label}
                              variant="outline"
                              size="sm"
                              className={cn(
                                "h-8",
                                startDate === getDateFromPreset(preset.months) && "bg-primary text-primary-foreground"
                              )}
                              onClick={() => {
                                setStartDate(getDateFromPreset(preset.months))
                                setEndDate(new Date().toISOString().split('T')[0])
                              }}
                            >
                              {preset.label}
                            </Button>
                          ))}
                        </div>
                      </div>

                      {/* Custom Date Range */}
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
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
                      </div>

                      {/* Incremental Download Toggle */}
                      <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
                        <div>
                          <Label className="font-medium">Incremental Download</Label>
                          <p className="text-xs text-muted-foreground">Only download new data after last available timestamp</p>
                        </div>
                        <Switch
                          checked={incrementalDownload}
                          onCheckedChange={setIncrementalDownload}
                        />
                      </div>

                      {/* Download Button */}
                      <Button
                        className="w-full h-10"
                        onClick={downloadWatchlist}
                        disabled={watchlist.length === 0}
                      >
                        <DownloadCloud className="h-4 w-4 mr-2" />
                        Download All Watchlist ({watchlist.length} symbols)
                      </Button>
                    </div>
                  </CardContent>
                </Card>

                {/* Watchlist Table */}
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">Watchlist ({watchlist.length})</CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    <ScrollArea className="h-[calc(100vh-580px)]">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Symbol</TableHead>
                            <TableHead className="hidden sm:table-cell">Exchange</TableHead>
                            <TableHead className="hidden md:table-cell">Added</TableHead>
                            <TableHead className="w-10"></TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {watchlist.length === 0 ? (
                            <TableRow>
                              <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                                No symbols in watchlist. Add symbols above.
                              </TableCell>
                            </TableRow>
                          ) : (
                            watchlist.map((item) => (
                              <TableRow key={item.id}>
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
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-7 w-7 text-destructive hover:text-destructive"
                                    onClick={() => removeFromWatchlist(item.symbol, item.exchange)}
                                  >
                                    <X className="h-4 w-4" />
                                  </Button>
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

            {/* FNO Discovery Tab */}
            <TabsContent value="fno" className="h-full m-0 p-4 overflow-auto">
              <div className="space-y-4">
                {/* FNO Filters */}
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">FNO Chain Discovery</CardTitle>
                    <CardDescription>Discover option and futures chains for bulk download</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
                      <div>
                        <Label className="text-sm text-muted-foreground">Exchange</Label>
                        <Select value={fnoExchange} onValueChange={setFnoExchange}>
                          <SelectTrigger className="h-9 mt-1">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {['NFO', 'BFO', 'MCX', 'CDS'].map((ex) => (
                              <SelectItem key={ex} value={ex}>{ex}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label className="text-sm text-muted-foreground">Underlying</Label>
                        <Select value={fnoSelectedUnderlying} onValueChange={setFnoSelectedUnderlying}>
                          <SelectTrigger className="h-9 mt-1">
                            <SelectValue placeholder="Select underlying" />
                          </SelectTrigger>
                          <SelectContent>
                            {fnoUnderlyings.map((u) => (
                              <SelectItem key={u} value={u}>{u}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label className="text-sm text-muted-foreground">Expiry</Label>
                        <Select value={fnoSelectedExpiry} onValueChange={setFnoSelectedExpiry}>
                          <SelectTrigger className="h-9 mt-1">
                            <SelectValue placeholder="All expiries" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__all__">All expiries</SelectItem>
                            {fnoExpiries.map((exp) => (
                              <SelectItem key={exp} value={exp}>{exp}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label className="text-sm text-muted-foreground">Instrument</Label>
                        <Select value={fnoInstrumentType} onValueChange={setFnoInstrumentType}>
                          <SelectTrigger className="h-9 mt-1">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="__all__">All</SelectItem>
                            <SelectItem value="FUT">Futures</SelectItem>
                            <SelectItem value="CE">Call (CE)</SelectItem>
                            <SelectItem value="PE">Put (PE)</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <div className="flex flex-col sm:flex-row gap-3">
                      <div className="flex gap-2 flex-1">
                        <Input
                          type="number"
                          placeholder="Min Strike"
                          value={fnoStrikeMin}
                          onChange={(e) => setFnoStrikeMin(e.target.value)}
                          className="h-9"
                        />
                        <Input
                          type="number"
                          placeholder="Max Strike"
                          value={fnoStrikeMax}
                          onChange={(e) => setFnoStrikeMax(e.target.value)}
                          className="h-9"
                        />
                      </div>
                      <Button onClick={loadFnoChain} disabled={fnoLoading || !fnoSelectedUnderlying} className="h-9">
                        {fnoLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Search className="h-4 w-4 mr-1" />}
                        Search
                      </Button>
                    </div>
                  </CardContent>
                </Card>

                {/* FNO Results */}
                {fnoSymbols.length > 0 && (
                  <Card>
                    <CardHeader className="pb-3">
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                        <CardTitle className="text-base">
                          Found {fnoSymbols.length} symbols
                          {fnoSelectedSymbols.size > 0 && (
                            <Badge className="ml-2">{fnoSelectedSymbols.size} selected</Badge>
                          )}
                        </CardTitle>
                        <div className="flex gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setFnoSelectedSymbols(new Set(fnoSymbols.map((s) => s.symbol)))}
                          >
                            Select All
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setFnoSelectedSymbols(new Set())}
                          >
                            Clear
                          </Button>
                          <Button
                            size="sm"
                            disabled={fnoSelectedSymbols.size === 0}
                            onClick={() => {
                              const symbols = Array.from(fnoSelectedSymbols).map((symbol) => {
                                const sym = fnoSymbols.find((s) => s.symbol === symbol)
                                return { symbol, exchange: sym?.exchange || fnoExchange }
                              })
                              createDownloadJob(symbols, 'fno_chain')
                            }}
                          >
                            <Download className="h-4 w-4 mr-1" />
                            Download
                          </Button>
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="p-0">
                      <ScrollArea className="h-[calc(100vh-480px)]">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-10">
                                <Checkbox
                                  checked={fnoSelectedSymbols.size === fnoSymbols.length}
                                  onCheckedChange={(checked) => {
                                    if (checked) setFnoSelectedSymbols(new Set(fnoSymbols.map((s) => s.symbol)))
                                    else setFnoSelectedSymbols(new Set())
                                  }}
                                />
                              </TableHead>
                              <TableHead>Symbol</TableHead>
                              <TableHead className="hidden sm:table-cell">Type</TableHead>
                              <TableHead className="hidden sm:table-cell">Expiry</TableHead>
                              <TableHead className="hidden md:table-cell text-right">Strike</TableHead>
                              <TableHead className="hidden md:table-cell text-right">Lot Size</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {fnoSymbols.map((sym) => (
                              <TableRow key={sym.symbol}>
                                <TableCell>
                                  <Checkbox
                                    checked={fnoSelectedSymbols.has(sym.symbol)}
                                    onCheckedChange={() => toggleFnoSymbol(sym.symbol)}
                                  />
                                </TableCell>
                                <TableCell className="font-medium">{sym.symbol}</TableCell>
                                <TableCell className="hidden sm:table-cell">
                                  <Badge variant={sym.instrumenttype === 'FUT' ? 'default' : sym.instrumenttype === 'CE' ? 'secondary' : 'outline'}>
                                    {sym.instrumenttype}
                                  </Badge>
                                </TableCell>
                                <TableCell className="hidden sm:table-cell">{sym.expiry}</TableCell>
                                <TableCell className="hidden md:table-cell text-right">{sym.strike}</TableCell>
                                <TableCell className="hidden md:table-cell text-right">{sym.lotsize}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </ScrollArea>
                    </CardContent>
                  </Card>
                )}
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
                          <p className="text-sm mt-1">Start a download from the Watchlist or FNO Discovery tabs</p>
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
          </div>
        </Tabs>
      </div>

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
            <DialogTitle>Import CSV Data</DialogTitle>
            <DialogDescription>Upload a CSV file with OHLCV data</DialogDescription>
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
              <Label>CSV File</Label>
              <Input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                onChange={handleFileChange}
                className="mt-1"
              />
              {uploadFile && (
                <p className="text-sm text-muted-foreground mt-1">Selected: {uploadFile.name}</p>
              )}
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
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Export Data</DialogTitle>
            <DialogDescription>Export historical data to file</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Export Format</Label>
              <Select value={exportFormat} onValueChange={(v: any) => setExportFormat(v)}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="csv">CSV</SelectItem>
                  <SelectItem value="txt">TXT (Tab-separated)</SelectItem>
                  <SelectItem value="zip">ZIP Archive</SelectItem>
                  <SelectItem value="parquet">Parquet (ZSTD)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Symbols</Label>
              <Select value={exportSymbols} onValueChange={(v: any) => setExportSymbols(v)}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Data</SelectItem>
                  <SelectItem value="selected" disabled={catalogSelectedSymbols.size === 0}>
                    Selected ({catalogSelectedSymbols.size})
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setExportDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleBulkExport} disabled={isExporting}>
              {isExporting && <Loader2 className="h-4 w-4 animate-spin mr-1" />}
              Export
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
    </div>
  )
}

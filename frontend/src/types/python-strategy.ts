// Python Strategy Types

export interface PythonStrategy {
  id: string
  name: string
  file_name: string
  exchange: string
  status: 'stopped' | 'running' | 'error' | 'scheduled' | 'paused' | 'manually_stopped'
  status_message?: string
  process_id: number | null
  last_started: string | null
  last_stopped: string | null
  error_message: string | null
  is_scheduled: boolean
  manually_stopped?: boolean
  schedule_start_time: string | null
  schedule_stop_time: string | null
  schedule_days: string[]
  created_at: string
  updated_at: string
}

export interface PythonStrategyContent {
  id: string
  name: string
  file_name: string
  content: string
  line_count: number
  size_kb: number
  last_modified: string
}

export interface LogFile {
  name: string
  path: string
  size_kb: number
  last_modified: string
}

export interface LogContent {
  content: string
  lines: number
  size_kb: number
  last_updated: string
}

export interface EnvironmentVariables {
  regular: Record<string, string>
  secure: Record<string, string>
}

export interface ScheduleConfig {
  start_time: string
  stop_time: string
  days: string[]
  exchange?: string
}

// Exchanges that drive the strategy's calendar/holiday awareness in /python.
// Labels show the default daily window only; per-date overrides (e.g. partial
// holidays, Muhurat sessions) come from the market calendar DB.
export const STRATEGY_EXCHANGES = [
  { value: 'NSE', label: 'NSE — Equity (09:15-15:30)' },
  { value: 'BSE', label: 'BSE — Equity (09:15-15:30)' },
  { value: 'NFO', label: 'NFO — NSE F&O (09:15-15:30)' },
  { value: 'BFO', label: 'BFO — BSE F&O (09:15-15:30)' },
  { value: 'CDS', label: 'CDS — NSE Currency (09:00-17:00)' },
  { value: 'BCD', label: 'BCD — BSE Currency (09:00-17:00)' },
  { value: 'MCX', label: 'MCX — Commodity (09:00-23:55)' },
  { value: 'CRYPTO', label: 'CRYPTO — 24/7' },
] as const

export const CRYPTO_EXCHANGE_VALUE = 'CRYPTO'

export interface MasterContractStatus {
  ready: boolean
  message: string
  last_updated: string | null
}

export const SCHEDULE_DAYS = [
  { value: 'mon', label: 'Monday' },
  { value: 'tue', label: 'Tuesday' },
  { value: 'wed', label: 'Wednesday' },
  { value: 'thu', label: 'Thursday' },
  { value: 'fri', label: 'Friday' },
  { value: 'sat', label: 'Saturday' },
  { value: 'sun', label: 'Sunday' },
] as const

export const STATUS_COLORS: Record<string, string> = {
  running: 'bg-green-500',
  stopped: 'bg-gray-500',
  error: 'bg-red-500',
  scheduled: 'bg-blue-500',
  paused: 'bg-yellow-500',
  manually_stopped: 'bg-orange-500',
}

export const STATUS_LABELS: Record<string, string> = {
  running: 'Running',
  stopped: 'Stopped',
  error: 'Error',
  scheduled: 'Scheduled',
  paused: 'Paused',
  manually_stopped: 'Manual Stop',
}

// Admin types for Freeze Qty, Holidays, and Market Timings

export interface FreezeQty {
  id: number
  exchange: string
  symbol: string
  freeze_qty: number
}

export interface AddFreezeQtyRequest {
  exchange: string
  symbol: string
  freeze_qty: number
}

export interface UpdateFreezeQtyRequest {
  freeze_qty: number
}

export interface SpecialSessionExchange {
  exchange: string
  start_time: string // HH:MM format for UI, converted to epoch ms before sending
  end_time: string
}

export interface Holiday {
  id: number
  date: string
  day_name: string
  description: string
  holiday_type: 'TRADING_HOLIDAY' | 'SETTLEMENT_HOLIDAY' | 'SPECIAL_SESSION'
  closed_exchanges: string[]
  open_exchanges?: SpecialSessionExchange[]
}

export interface AddHolidayRequest {
  date: string
  description: string
  holiday_type: 'TRADING_HOLIDAY' | 'SETTLEMENT_HOLIDAY' | 'SPECIAL_SESSION'
  closed_exchanges: string[]
  open_exchanges?: Array<{
    exchange: string
    start_time: number // epoch milliseconds
    end_time: number
  }>
}

export interface HolidaysResponse {
  status: string
  data: Holiday[]
  current_year: number
  years: number[]
  exchanges: string[]
}

export interface MarketTiming {
  id: number | null
  exchange: string
  start_time: string
  end_time: string
  start_offset: number
  end_offset: number
}

export interface TodayTiming {
  exchange: string
  start_time: string
  end_time: string
}

export interface UpdateTimingRequest {
  start_time: string
  end_time: string
}

export interface TimingsResponse {
  status: string
  data: MarketTiming[]
  today_timings: TodayTiming[]
  today: string
  exchanges: string[]
}

export interface AdminStats {
  freeze_count: number
  holiday_count: number
}

// ============================================================================
// Diagnostics types
// ============================================================================

export interface ErrorEntry {
  ts?: string
  level?: string
  logger?: string
  module?: string
  file?: string
  message?: string
  exception?: string[] | string
  request?: { method?: string; path?: string; ip?: string }
}

export interface ErrorsListResponse {
  status: string
  data: ErrorEntry[]
  count: number
  scanned: number
  total_in_window: number
}

export interface ErrorsStats {
  status: string
  total: number
  by_level: Record<string, number>
  last_24h: number
  last_1h: number
}

export interface SystemMode {
  analyze_mode: boolean | null
  label: string
}

export interface SystemHost {
  system?: string
  release?: string
  version?: string
  machine?: string
  platform?: string
  distro?: { name?: string; id?: string; version_id?: string } | null
  in_docker?: boolean
  is_raspberry_pi?: boolean
  rpi_model?: string | null
  is_termux?: boolean
  is_android?: boolean
}

export interface SystemRuntime {
  python_version?: string
  python_implementation?: string
  eventlet_active?: boolean
  wsgi_hint?: string
  process_uptime_seconds?: number | null
}

export interface SystemHardware {
  cpu_count?: number | null
  cpu_model?: string | null
  memory_total_mb?: number | null
  memory_available_mb?: number | null
  memory_percent?: number | null
  disk_log?: { total_gb: number; free_gb: number; used_percent: number } | null
  disk_db?: { total_gb: number; free_gb: number; used_percent: number } | null
}

export interface SystemBuild {
  openalgo_version?: string | null
  openalgo_sdk_version?: string | null
  git_branch?: string | null
  git_commit?: string | null
  frontend_build_time?: string | null
}

export interface SystemConfig {
  valid_brokers: string[]
  log_level: string
  log_to_file: boolean
  log_dir: string
  websocket_host: string
  websocket_port: string
  max_symbols_per_websocket: string
  max_websocket_connections: string
  api_rate_limit: string
  flask_debug: boolean
  secrets_present: Record<string, boolean>
}

export interface SystemBrokers {
  configured_brokers: string[]
  active_broker: string | null
  user_logged_in: boolean
}

export interface SystemDatabase {
  name: string
  exists: boolean
  size_mb: number
  modified: string | null
}

export interface SystemTime {
  server_time: string
  server_tz: string | null
  ist_time: string | null
}

export interface SystemInfo {
  mode: SystemMode
  host: SystemHost
  runtime: SystemRuntime
  hardware: SystemHardware
  build: SystemBuild
  config: SystemConfig
  brokers: SystemBrokers
  databases: SystemDatabase[]
  time: SystemTime
}

export interface DiagnosticCheck {
  name: string
  ok: boolean
  ms: number | null
  detail: string
}

export interface DiagnosticsResponse {
  status: string
  ran_at: string
  checks: DiagnosticCheck[]
}

export interface ErrorGroup {
  fingerprint: string
  count: number
  level?: string
  logger?: string
  module?: string
  first_seen?: string
  last_seen?: string
  sample: ErrorEntry
}

export interface ErrorGroupsResponse {
  status: string
  groups: ErrorGroup[]
  total_entries: number
  total_groups: number
}

// ============================================================================
// Remote MCP — admin types
// ============================================================================

export interface OAuthClient {
  client_id: string
  client_name: string
  redirect_uris: string[]
  scopes_requested: string[]
  is_public: boolean
  approved: boolean
  approved_at: string | null
  revoked_at: string | null
  created_at: string | null
  last_used_at: string | null
}

export interface OAuthClientsResponse {
  status: string
  mcp_enabled: boolean
  clients: OAuthClient[]
  summary: {
    pending: number
    approved: number
    revoked: number
  }
}

export interface MCPAuditEntry {
  ts?: string
  jti?: string
  client_id?: string
  tool?: string
  scope?: string
  params_hash?: string
  duration_ms?: number
  outcome?: string
  request_ip?: string
}

export interface MCPAuditResponse {
  status: string
  mcp_enabled: boolean
  data: MCPAuditEntry[]
  count: number
  scanned?: number
  total_in_window: number
}

export interface MCPSettings {
  http_enabled: boolean
  public_url: string
  mcp_url: string
  require_approval: boolean
  write_scope_enabled: boolean
}

export interface MCPSettingsResponse {
  status: string
  settings: MCPSettings
}

export interface MCPSettingsUpdateRequest {
  http_enabled?: boolean
  public_url?: string
  require_approval?: boolean
  write_scope_enabled?: boolean
}

export interface MCPSettingsUpdateResponse {
  status: string
  message?: string
  restart_required?: boolean
  restart_command?: string
  settings_pending?: MCPSettings
}

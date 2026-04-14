// Telegram types

export interface TelegramBotStatus {
  is_running: boolean
  is_configured: boolean
  bot_username: string | null
  is_active: boolean
}

export interface TelegramConfig {
  bot_token?: string
  bot_username?: string
  broadcast_enabled: boolean
  rate_limit_per_minute: number
  is_active: boolean
}

export interface TelegramUser {
  id: number
  telegram_id: number
  telegram_username: string | null
  openalgo_username: string | null
  first_name: string | null
  last_name: string | null
  notifications_enabled: boolean
  created_at: string
  last_active: string | null
}

export interface CommandStats {
  command: string
  count: number
  last_used: string | null
}

export interface TelegramAnalytics {
  stats_7d: CommandStats[]
  stats_30d: CommandStats[]
  total_users: number
  active_users: number
  users: TelegramUser[]
}

export interface UpdateConfigRequest {
  token?: string
  broadcast_enabled?: boolean
  rate_limit_per_minute?: number
}

export interface BroadcastRequest {
  message: string
  filters?: {
    notifications_enabled?: boolean
  }
}

export interface BroadcastResponse {
  success_count: number
  fail_count: number
}

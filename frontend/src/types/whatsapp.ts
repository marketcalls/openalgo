// WhatsApp types — mirrors the JSON shapes returned by blueprints/whatsapp.py.

export interface WhatsAppBotStatus {
  is_running: boolean
  is_paired: boolean
  is_active: boolean
  own_jid: string | null
  own_phone: string | null
  bot_username: string | null
  paired_at: string | null
}

export interface WhatsAppConfig {
  is_paired: boolean
  is_active: boolean
  own_jid: string | null
  own_phone: string | null
  bot_username: string | null
  owner_user_id: number | null
  owner_username: string | null
  paired_at: string | null
  max_message_length: number
  rate_limit_per_minute: number
  broadcast_enabled: boolean
  is_running?: boolean
}

export type WhatsAppPairStatus = 'idle' | 'starting' | 'awaiting_scan' | 'paired' | 'failed'

export interface WhatsAppPairState {
  status: WhatsAppPairStatus
  qr_data_url: string | null
  pair_code: string | null
  error: string | null
  started_at: string | null
  paired_at: string | null
}

export interface WhatsAppConfigBundle {
  config: WhatsAppConfig
  pair_state: WhatsAppPairState
}

export interface WhatsAppUser {
  id: number
  whatsapp_jid: string
  phone_number: string
  openalgo_username: string
  display_name: string | null
  broker: string
  notifications_enabled: boolean
  created_at: string
  last_command_at: string | null
}

export interface WhatsAppCommandStats {
  total_commands: number
  by_command: Record<string, number>
  days: number
}

export interface WhatsAppUpdateConfigRequest {
  broadcast_enabled?: boolean
  rate_limit_per_minute?: number
  max_message_length?: number
}

export interface WhatsAppBroadcastRequest {
  message: string
  filters?: {
    broker?: string
    notifications_enabled?: boolean
  }
}

export interface WhatsAppSendToPhoneRequest {
  phone: string
  message: string
  image_path?: string | null
  document_path?: string | null
}

// Socket.IO event payloads emitted by services/whatsapp_bot_service.py.
export interface WhatsAppQrEvent {
  data_url: string | null
}

export interface WhatsAppPairCodeEvent {
  code: string
}

export interface WhatsAppPairedEvent {
  own_jid: string | null
  own_phone: string | null
}

export interface WhatsAppStatusEvent {
  is_running: boolean
  is_paired: boolean
}

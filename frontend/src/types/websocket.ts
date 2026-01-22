export type MessageDirection = 'sent' | 'received' | 'error' | 'system'

export interface WebSocketMessage {
  id: string
  direction: MessageDirection
  timestamp: number
  data: unknown
  rawData?: string
}

export interface MessageTemplate {
  key: string
  label: string
  description: string
  template: Record<string, unknown>
}

export interface LatencySample {
  timestamp: number
  latency: number
}

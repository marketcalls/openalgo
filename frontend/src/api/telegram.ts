import type {
  BroadcastRequest,
  BroadcastResponse,
  CommandStats,
  TelegramAnalytics,
  TelegramBotStatus,
  TelegramConfig,
  TelegramUser,
  UpdateConfigRequest,
} from '@/types/telegram'
import { webClient } from './client'

interface ApiResponse<T = void> {
  status: string
  message?: string
  data?: T
}

export const telegramApi = {
  // ============================================================================
  // Bot Status & Control
  // ============================================================================

  /**
   * Get bot status
   */
  getBotStatus: async (): Promise<TelegramBotStatus> => {
    const response = await webClient.get<ApiResponse<TelegramBotStatus>>('/telegram/bot/status')
    return response.data.data!
  },

  /**
   * Start the bot
   */
  startBot: async (): Promise<ApiResponse> => {
    const response = await webClient.post<ApiResponse>('/telegram/bot/start')
    return response.data
  },

  /**
   * Stop the bot
   */
  stopBot: async (): Promise<ApiResponse> => {
    const response = await webClient.post<ApiResponse>('/telegram/bot/stop')
    return response.data
  },

  // ============================================================================
  // Configuration
  // ============================================================================

  /**
   * Get bot configuration
   */
  getConfig: async (): Promise<TelegramConfig> => {
    const response = await webClient.get<ApiResponse<TelegramConfig>>('/telegram/api/config')
    return response.data.data!
  },

  /**
   * Update bot configuration
   */
  updateConfig: async (data: UpdateConfigRequest): Promise<ApiResponse> => {
    const response = await webClient.post<ApiResponse>('/telegram/config', data)
    return response.data
  },

  // ============================================================================
  // Users
  // ============================================================================

  /**
   * Get all telegram users
   */
  getUsers: async (): Promise<{ users: TelegramUser[]; stats: CommandStats[] }> => {
    const response =
      await webClient.get<ApiResponse<{ users: TelegramUser[]; stats: CommandStats[] }>>(
        '/telegram/api/users'
      )
    return response.data.data!
  },

  /**
   * Unlink a telegram user
   */
  unlinkUser: async (telegramId: number): Promise<ApiResponse> => {
    const response = await webClient.post<ApiResponse>(`/telegram/user/${telegramId}/unlink`)
    return response.data
  },

  // ============================================================================
  // Analytics
  // ============================================================================

  /**
   * Get analytics data
   */
  getAnalytics: async (): Promise<TelegramAnalytics> => {
    const response = await webClient.get<ApiResponse<TelegramAnalytics>>('/telegram/api/analytics')
    return response.data.data!
  },

  // ============================================================================
  // Messaging
  // ============================================================================

  /**
   * Send test message
   */
  sendTestMessage: async (): Promise<ApiResponse> => {
    const response = await webClient.post<ApiResponse>('/telegram/test-message')
    return response.data
  },

  /**
   * Send broadcast message
   */
  sendBroadcast: async (data: BroadcastRequest): Promise<ApiResponse<BroadcastResponse>> => {
    const response = await webClient.post<ApiResponse<BroadcastResponse>>(
      '/telegram/broadcast',
      data
    )
    return response.data
  },

  /**
   * Send message to specific user
   */
  sendMessage: async (telegramId: number, message: string): Promise<ApiResponse> => {
    const response = await webClient.post<ApiResponse>('/telegram/send-message', {
      telegram_id: telegramId,
      message,
    })
    return response.data
  },
}

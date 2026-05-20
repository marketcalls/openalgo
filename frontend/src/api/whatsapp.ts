// WhatsApp API client — talks to the session-authed blueprint at /whatsapp/...
// (Public REST namespace /api/v1/whatsapp is send-only and used by external
// scripts / SDKs, not by this frontend.)

import type {
  WhatsAppBotStatus,
  WhatsAppBroadcastRequest,
  WhatsAppCommandStats,
  WhatsAppConfigBundle,
  WhatsAppPairState,
  WhatsAppSendToPhoneRequest,
  WhatsAppUpdateConfigRequest,
  WhatsAppUser,
} from '@/types/whatsapp'
import { webClient } from './client'

interface ApiResponse<T = void> {
  status: string
  message?: string
  data?: T
}

export const whatsappApi = {
  // ----- bundled status (single call for the index page) -----

  getConfig: async (): Promise<WhatsAppConfigBundle> => {
    const r = await webClient.get<ApiResponse<WhatsAppConfigBundle>>('/whatsapp/config')
    return r.data.data!
  },

  updateConfig: async (payload: WhatsAppUpdateConfigRequest): Promise<ApiResponse> => {
    const r = await webClient.post<ApiResponse>('/whatsapp/config', payload)
    return r.data
  },

  getStatus: async (): Promise<WhatsAppBotStatus> => {
    const r = await webClient.get<ApiResponse<WhatsAppBotStatus>>('/whatsapp/bot/status')
    return r.data.data!
  },

  // ----- pairing -----

  startPair: async (phone?: string): Promise<ApiResponse<WhatsAppPairState>> => {
    const r = await webClient.post<ApiResponse<WhatsAppPairState>>('/whatsapp/pair', {
      phone: phone ?? '',
    })
    return r.data
  },

  pollPairStatus: async (): Promise<WhatsAppPairState> => {
    const r = await webClient.get<ApiResponse<WhatsAppPairState>>('/whatsapp/pair/status')
    return r.data.data!
  },

  unlinkDevice: async (): Promise<ApiResponse> => {
    const r = await webClient.post<ApiResponse>('/whatsapp/unlink')
    return r.data
  },

  // ----- bot lifecycle -----

  startBot: async (): Promise<ApiResponse> => {
    const r = await webClient.post<ApiResponse>('/whatsapp/bot/start')
    return r.data
  },

  stopBot: async (): Promise<ApiResponse> => {
    const r = await webClient.post<ApiResponse>('/whatsapp/bot/stop')
    return r.data
  },

  // ----- linked users -----

  listUsers: async (): Promise<WhatsAppUser[]> => {
    const r = await webClient.get<ApiResponse<WhatsAppUser[]>>('/whatsapp/users')
    return r.data.data ?? []
  },

  unlinkUser: async (whatsappJid: string): Promise<ApiResponse> => {
    const encoded = encodeURIComponent(whatsappJid)
    const r = await webClient.post<ApiResponse>(`/whatsapp/user/${encoded}/unlink`)
    return r.data
  },

  // ----- send -----

  broadcast: async (
    payload: WhatsAppBroadcastRequest
  ): Promise<{ queued: number; skipped: number }> => {
    const r = await webClient.post<ApiResponse<{ queued: number; skipped: number }>>(
      '/whatsapp/broadcast',
      payload
    )
    return { queued: r.data.data?.queued ?? 0, skipped: r.data.data?.skipped ?? 0 }
  },

  sendToPhone: async (payload: WhatsAppSendToPhoneRequest): Promise<ApiResponse> => {
    const r = await webClient.post<ApiResponse>('/whatsapp/send', payload)
    return r.data
  },

  testMessage: async (): Promise<ApiResponse> => {
    const r = await webClient.post<ApiResponse>('/whatsapp/test-message')
    return r.data
  },

  // ----- stats -----

  getStats: async (days = 7): Promise<WhatsAppCommandStats> => {
    const r = await webClient.get<ApiResponse<WhatsAppCommandStats>>(`/whatsapp/stats?days=${days}`)
    return r.data.data!
  },
}

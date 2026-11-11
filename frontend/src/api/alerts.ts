// Alert channels: the /alerts, /slack and /discord pages.
//
// Talks to the session-authenticated blueprint at /alerts/channels. A webhook
// URL is sent here once, when it is saved, and never comes back: a channel
// only reports whether it is set up.

import axios from 'axios'

import { webClient } from './client'

/** One group of order events the trader routes to channels. */
export interface AlertCategory {
  id: string
  label: string
  description: string
}

/** How a channel stands right now. */
export interface AlertChannelStatus {
  /** Set up enough to send at all: a bot token, a paired device, a webhook. */
  configured: boolean
  /** Would deliver an alert raised right now. */
  ready: boolean
  /** One sentence for the trader, with the next step when it is not ready. */
  detail: string
}

export type AlertChannelName = 'telegram' | 'whatsapp' | 'slack' | 'discord'

/** The channels that post to a saved webhook. Only these take one. */
export type WebhookChannelName = Extract<AlertChannelName, 'slack' | 'discord'>

export interface AlertChannel {
  name: AlertChannelName
  label: string
  /** The page where the channel is set up. */
  setup_path: string
  /** Slack and Discord post to a saved webhook. */
  uses_webhook: boolean
  enabled: boolean
  /** The event groups this channel receives. */
  categories: string[]
  status: AlertChannelStatus
}

export interface AlertChannelList {
  categories: AlertCategory[]
  channels: AlertChannel[]
}

interface Envelope<T> {
  status: string
  message?: string
  data?: T
}

/** The query key every alert page shares, so a change on one refreshes all. */
export const ALERT_CHANNELS_KEY = ['alert-channels'] as const

/**
 * The sentence to show for a failed request: the server's own when it sent
 * one, since every refusal it makes is written for the trader.
 */
export function alertsErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const message = (error.response?.data as Envelope<unknown> | undefined)?.message
    if (typeof message === 'string' && message) return message
  }
  return fallback
}

export const alertsApi = {
  list: async (): Promise<AlertChannelList> => {
    const response = await webClient.get<Envelope<AlertChannelList>>('/alerts/channels')
    return response.data.data as AlertChannelList
  },

  update: async (
    name: AlertChannelName,
    change: { enabled?: boolean; categories?: string[] }
  ): Promise<AlertChannel> => {
    const response = await webClient.post<Envelope<AlertChannel>>(
      `/alerts/channels/${name}`,
      change
    )
    return response.data.data as AlertChannel
  },

  saveWebhook: async (name: WebhookChannelName, url: string): Promise<AlertChannel> => {
    const response = await webClient.put<Envelope<AlertChannel>>(
      `/alerts/channels/${name}/webhook`,
      { url }
    )
    return response.data.data as AlertChannel
  },

  forgetWebhook: async (name: WebhookChannelName): Promise<AlertChannel> => {
    const response = await webClient.delete<Envelope<AlertChannel>>(
      `/alerts/channels/${name}/webhook`
    )
    return response.data.data as AlertChannel
  },

  /** Send a test message now. Resolves with the server's sentence. */
  sendTest: async (name: AlertChannelName): Promise<string> => {
    const response = await webClient.post<Envelope<never>>(`/alerts/channels/${name}/test`)
    return response.data.message ?? 'Test message sent.'
  },
}

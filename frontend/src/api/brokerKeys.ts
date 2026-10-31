/**
 * Broker keys saved in OpenAlgo, and the broker login that uses them.
 *
 * Two surfaces share this module. `/api/broker/keys` (session cookie, CSRF via
 * webClient) lists, saves and removes keys. The `/auth/broker-*` routes back
 * the broker login page and are called with fetch, because a 401 there has to
 * become a client-side navigation to /login rather than webClient's full-page
 * redirect.
 *
 * No key or secret ever comes back from the server: a listing carries an API
 * key's first few characters and a secret's length only.
 */

import { fetchCSRFToken, webClient } from './client'

/** One broker's keys as the server describes them; an empty string is "not set". */
export interface BrokerKeyEntry {
  broker: string
  name: string
  source: 'env' | 'saved'
  /** The first six characters and asterisks. */
  api_key: string
  api_key_set: boolean
  /** Asterisks only. */
  api_secret: string
  api_secret_set: boolean
  api_key_market: string
  api_key_market_set: boolean
  api_secret_market: string
  api_secret_market_set: boolean
  redirect_url: string | null
  /** Saved keys only: false when the broker is not in VALID_BROKERS. */
  enabled?: boolean
  /** Saved keys only: true when .env sets this broker, so these are not used. */
  overridden_by_env?: boolean
  updated_at?: string | null
}

export interface BrokerKeysData {
  brokers: BrokerKeyEntry[]
  env: BrokerKeyEntry | null
  enabled_brokers: { broker: string; name: string }[]
  live_broker: string | null
  default_redirect_urls: Record<string, string>
}

/**
 * What a save sends. Only the fields the trader typed are present: a missing
 * field keeps the saved value, including the redirect URL.
 */
export interface SaveBrokerKeysBody {
  broker: string
  api_key?: string
  api_secret?: string
  api_key_market?: string
  api_secret_market?: string
  redirect_url?: string
  clear_market_keys?: true
}

/** A broker the trader can log in to: set in .env, or with keys saved in OpenAlgo. */
export interface ConfiguredBroker {
  broker: string
  name: string
  source: 'env' | 'saved'
}

export interface BrokerConfig {
  /** The broker to preselect. */
  broker_name: string | null
  brokers: ConfiguredBroker[]
  /** The broker a device is logged in to now, if any. */
  live_broker: string | null
}

export const brokerQueryKeys = {
  all: ['broker'] as const,
  /** GET /api/broker/keys */
  keys: () => [...brokerQueryKeys.all, 'keys'] as const,
  /** GET /auth/broker-config */
  config: () => [...brokerQueryKeys.all, 'config'] as const,
}

/**
 * A refused `/auth/broker-*` request. `message` is the server's sentence when it
 * sent one, which is already written for a trader; `status` lets the caller
 * tell a signed-out session (401) from a refusal.
 */
export class BrokerAuthError extends Error {
  readonly status: number
  readonly serverMessage: string | null

  constructor(status: number, serverMessage: string | null) {
    super(serverMessage ?? `Request refused (${status})`)
    this.name = 'BrokerAuthError'
    this.status = status
    this.serverMessage = serverMessage
  }
}

function statusOf(error: unknown): number | undefined {
  if (error instanceof BrokerAuthError) return error.status
  return (error as { response?: { status?: number } })?.response?.status
}

/** Whether a request failed because the OpenAlgo session is gone. */
export function isSignedOut(error: unknown): boolean {
  return statusOf(error) === 401
}

/**
 * Retry once, as the app's default does, but never a refusal: a 4xx answers
 * the same the second time, and a 401 has to reach the login page at once.
 */
export function retryUnlessRefused(failureCount: number, error: unknown): boolean {
  const status = statusOf(error)
  if (status !== undefined && status >= 400 && status < 500) return false
  return failureCount < 1
}

/** The trader-facing sentence the server sent with a refusal, else the fallback. */
export function serverMessage(error: unknown, fallback: string): string {
  if (error instanceof BrokerAuthError) return error.serverMessage || fallback
  const data = (error as { response?: { data?: { message?: unknown } } })?.response?.data
  return typeof data?.message === 'string' && data.message ? data.message : fallback
}

// --- /api/broker/keys -------------------------------------------------------

export async function getBrokerKeys(): Promise<BrokerKeysData> {
  const response = await webClient.get<{ status: string; data: BrokerKeysData }>('/api/broker/keys')
  return response.data.data
}

/** Save one broker's keys. Resolves with the server's sentence. */
export async function saveBrokerKeys(body: SaveBrokerKeysBody): Promise<string | undefined> {
  const response = await webClient.post<{ status: string; message?: string }>(
    '/api/broker/keys',
    body
  )
  return response.data.message
}

export async function removeBrokerKeys(broker: string): Promise<string | undefined> {
  const response = await webClient.delete<{ status: string; message?: string }>(
    `/api/broker/keys/${encodeURIComponent(broker)}`
  )
  return response.data.message
}

/** Copy the .env broker's keys into OpenAlgo, the first step off .env. */
export async function importEnvBrokerKeys(): Promise<string | undefined> {
  const response = await webClient.post<{ status: string; message?: string }>(
    '/api/broker/keys/import-env'
  )
  return response.data.message
}

// --- /auth/broker-* ---------------------------------------------------------

async function brokerAuthRequest(
  url: string,
  init?: { method: 'POST'; body?: unknown }
): Promise<Record<string, unknown>> {
  const headers: Record<string, string> = {}
  if (init) {
    headers['X-CSRFToken'] = await fetchCSRFToken()
    if (init.body !== undefined) headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(url, {
    method: init?.method ?? 'GET',
    credentials: 'include',
    headers,
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  })
  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>
  if (!response.ok || data.status !== 'success') {
    const message = typeof data.message === 'string' && data.message ? data.message : null
    throw new BrokerAuthError(response.status, message)
  }
  return data
}

/** The brokers this trader can log in to. Never carries an API key. */
export async function getBrokerConfig(): Promise<BrokerConfig> {
  const data = await brokerAuthRequest('/auth/broker-config')
  return {
    broker_name: typeof data.broker_name === 'string' ? data.broker_name : null,
    brokers: Array.isArray(data.brokers) ? (data.brokers as ConfiguredBroker[]) : [],
    live_broker: typeof data.live_broker === 'string' ? data.live_broker : null,
  }
}

/**
 * Ask the server to start a login to `broker`. It checks the broker can be used
 * now, puts its keys in place and answers with the address that begins the
 * login, so no broker key reaches the page.
 */
export async function startBrokerLogin(broker: string): Promise<string> {
  const data = await brokerAuthRequest('/auth/broker/login', { method: 'POST', body: { broker } })
  if (typeof data.url !== 'string' || !data.url) throw new BrokerAuthError(200, null)
  return data.url
}

/** End the broker session another device holds. Resolves with the server's sentence. */
export async function endBrokerSession(): Promise<string | null> {
  const data = await brokerAuthRequest('/auth/broker/end-session', { method: 'POST' })
  return typeof data.message === 'string' && data.message ? data.message : null
}

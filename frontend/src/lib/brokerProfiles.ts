/**
 * Several brokers configured, one logged in at a time: the helpers the broker
 * login page, Profile and Layout share, as OpenAlgo Desktop has them.
 *
 * Keys are stored per broker on the server (in .env for the broker it names,
 * in OpenAlgo for every other one). The page never sees a key: the server
 * reports which brokers are configured and which one is active, and builds the
 * broker's sign-in address itself.
 */

import { fetchCSRFToken } from '@/api/client'

/** A broker with saved keys, from GET /api/broker/configured. */
export interface ConfiguredBroker {
  name: string
  active: boolean
}

/** Profile link that opens the Broker Configuration tab. */
export const BROKER_SETUP_PATH = '/profile?tab=broker'

/**
 * Pages a trader signed in to OpenAlgo can open before connecting a broker:
 * the broker keys are added in Profile before the first broker login.
 */
export const PRE_BROKER_PATHS = ['/profile'] as const

export function isPreBrokerPath(pathname: string): boolean {
  const p = pathname.replace(/\/+$/, '') || '/'
  return (PRE_BROKER_PATHS as readonly string[]).includes(p)
}

/**
 * The address the app is served from, for a broker redirect URL when none is
 * saved yet. A server install is reached at its own domain, so a first broker
 * saved there must not get a 127.0.0.1 address.
 */
export function defaultOrigin(): string {
  return window.location.origin || 'http://127.0.0.1:5000'
}

/** Initial Profile tab from `?tab=`, so the broker page can link to it. */
export function initialProfileTab(fallback: string): string {
  try {
    return new URLSearchParams(window.location.search).get('tab') || fallback
  } catch {
    return fallback
  }
}

/** Brokers the trader has configured, so the broker page can switch. */
export async function fetchConfiguredBrokers(): Promise<ConfiguredBroker[]> {
  try {
    const res = await fetch('/api/broker/configured', { credentials: 'include' })
    if (!res.ok) return []
    const body = await res.json()
    return Array.isArray(body?.data?.brokers) ? body.data.brokers : []
  } catch {
    return []
  }
}

async function csrfToken(): Promise<string | undefined> {
  try {
    return await fetchCSRFToken()
  } catch {
    return undefined
  }
}

/**
 * Make another configured broker the active one. Keys are stored per broker,
 * so only the active broker changes; the server ends a live session of a
 * different broker first. Returns the server's message on refusal.
 */
export async function switchActiveBroker(broker: string): Promise<string | null> {
  const csrf = await csrfToken()
  if (!csrf) return 'Could not reach OpenAlgo. Try again.'
  const form = new FormData()
  form.append('redirect_url', `${defaultOrigin()}/${broker}/callback`)
  try {
    const res = await fetch('/api/broker/credentials', {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-CSRFToken': csrf },
      body: form,
    })
    if (res.ok) return null
    const body = await res.json().catch(() => null)
    return body?.message || 'Could not switch the broker. Try again.'
  } catch {
    return 'Could not reach OpenAlgo. Try again.'
  }
}

/** The outcome of asking the server to start a broker login. */
export type BrokerLoginStart =
  | { url: string; error?: undefined }
  | { url?: undefined; error: string }

/**
 * Ask the server to start a login to `broker`. It checks the broker can be used
 * now, records the login for this browser and answers with the address that
 * begins it, so no broker key reaches the page.
 */
export async function startBrokerLogin(broker: string): Promise<BrokerLoginStart> {
  const failed = 'The broker login could not be started. Try again.'
  const csrf = await csrfToken()
  if (!csrf) return { error: 'Could not reach OpenAlgo. Try again.' }
  try {
    const res = await fetch('/auth/broker/login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify({ broker }),
    })
    const body = await res.json().catch(() => null)
    if (res.ok && body?.status === 'success' && typeof body.url === 'string' && body.url) {
      return { url: body.url }
    }
    return { error: (typeof body?.message === 'string' && body.message) || failed }
  } catch {
    return { error: failed }
  }
}

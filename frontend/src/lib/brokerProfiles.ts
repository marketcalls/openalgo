/**
 * Several brokers configured, one logged in at a time: the helpers Select
 * Broker, Broker Configuration, Profile and Layout share, as OpenAlgo Desktop
 * has them.
 *
 * Keys are stored per broker on the server (in .env for the broker it names,
 * in OpenAlgo for every other one). The page never sees a key: the server
 * lists the brokers (`GET /api/broker/list`) and builds each broker's sign-in
 * address itself.
 */

import { brokerConfigApi, csrfToken } from '@/api/broker-config'

/** The Broker Configuration page. */
export const BROKER_SETUP_PATH = '/broker/config'

/** The Broker Configuration page with one broker selected. */
export function brokerConfigPath(broker?: string): string {
  return broker ? `${BROKER_SETUP_PATH}?broker=${encodeURIComponent(broker)}` : BROKER_SETUP_PATH
}

/**
 * Pages a trader signed in to OpenAlgo can open before connecting a broker.
 * Select Broker and Broker Configuration are full pages of their own; Profile
 * shows the brokers and links to both.
 */
export const PRE_BROKER_PATHS = ['/profile'] as const

export function isPreBrokerPath(pathname: string): boolean {
  const p = pathname.replace(/\/+$/, '') || '/'
  return (PRE_BROKER_PATHS as readonly string[]).includes(p)
}

/** Initial Profile tab from `?tab=`, so another page can link to a tab. */
export function initialProfileTab(fallback: string): string {
  try {
    return new URLSearchParams(window.location.search).get('tab') || fallback
  } catch {
    return fallback
  }
}

/**
 * The broker logged in now, read again from the server rather than from what
 * the page loaded earlier (another device may have logged in since).
 */
export async function fetchLiveBroker(fallback: string | null): Promise<string | null> {
  try {
    return (await brokerConfigApi.list()).logged_in
  } catch {
    return fallback
  }
}

async function postJson(url: string, payload: unknown) {
  let csrf: string
  try {
    csrf = await csrfToken()
  } catch {
    return { ok: false as const, body: { message: 'Could not reach OpenAlgo. Try again.' } }
  }
  try {
    const res = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify(payload),
    })
    const body = await res.json().catch(() => null)
    return { ok: res.ok && body?.status === 'success', body }
  } catch {
    return { ok: false as const, body: { message: 'Could not reach OpenAlgo. Try again.' } }
  }
}

/** The outcome of asking the server to start a broker login. */
export type BrokerLoginStart =
  | { url: string; error?: undefined }
  | { url?: undefined; error: string }

/**
 * Ask the server to start a login to `broker`. It checks the broker can be
 * used now, records the login for this browser and answers with the address
 * that begins it (the broker's site, OpenAlgo's form or a one-click sign-in),
 * so no broker key reaches the page.
 */
export async function startBrokerLogin(broker: string): Promise<BrokerLoginStart> {
  const failed = 'The broker login could not be started. Try again.'
  const { ok, body } = await postJson('/auth/broker/login', { broker })
  if (ok && typeof body?.url === 'string' && body.url) return { url: body.url }
  return { error: (typeof body?.message === 'string' && body.message) || failed }
}

/**
 * Join the broker session that is logged in now, from this browser. On the
 * web a broker can be logged in from another device while this browser has
 * no broker session yet. Returns null on success, or the server's message.
 */
export async function resumeBrokerSession(): Promise<string | null> {
  const { ok, body } = await postJson('/auth/broker/resume', {})
  if (ok) return null
  return (
    (typeof body?.message === 'string' && body.message) ||
    'Could not open the broker session. Log in again.'
  )
}

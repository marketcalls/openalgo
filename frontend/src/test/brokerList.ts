/**
 * Test data for the broker pages: a `GET /api/broker/list` answer built the
 * way the server builds it (sign-in kind, keys each broker needs, masked
 * saved values).
 */
import type { BrokerEntry, BrokerKeyField, BrokerList, BrokerSignIn } from '@/api/broker-config'

const KEY: BrokerKeyField = {
  key: 'api_key',
  label: 'API Key',
  hint: 'The API key of your app.',
  secret: false,
  required: true,
  saved: null,
}
const SECRET: BrokerKeyField = {
  key: 'api_secret',
  label: 'API Secret',
  hint: 'The API secret of that app.',
  secret: true,
  required: true,
  saved: null,
}

export function brokerEntry(
  id: string,
  name: string,
  signIn: BrokerSignIn,
  over: Partial<BrokerEntry> = {}
): BrokerEntry {
  const redirect = signIn === 'redirect' ? `http://127.0.0.1:5000/${id}/callback` : null
  return {
    id,
    name,
    configured: false,
    active: false,
    sign_in: signIn,
    exchanges: ['NSE', 'BSE', 'NFO'],
    banner:
      signIn === 'redirect'
        ? `Login with ${name} takes you to ${name}'s login page. Log in there and ${name} sends you back to OpenAlgo.`
        : signIn === 'form'
          ? `Login with ${name} opens a short form in OpenAlgo.`
          : `Login with ${name} signs you in with one click using the keys you saved.`,
    fields: [{ ...KEY }, { ...SECRET }],
    redirect_url: redirect,
    redirect_url_automatic: redirect,
    redirect_url_is_default: true,
    redirect_hint: redirect
      ? 'Register this exact address as the redirect URL in your broker app.'
      : null,
    ...over,
  }
}

/** Saved values as the server masks them. */
export function saved(entry: BrokerEntry, values: Record<string, string>): BrokerEntry {
  return {
    ...entry,
    configured: true,
    fields: entry.fields.map((f) => ({ ...f, saved: values[f.key] ?? f.saved })),
  }
}

export function brokerList(brokers: BrokerEntry[]): BrokerList {
  return { logged_in: brokers.find((b) => b.active)?.id ?? null, brokers }
}

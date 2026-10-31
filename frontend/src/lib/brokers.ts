/**
 * The brokers OpenAlgo supports, shared by the broker login page and the
 * Broker Keys page.
 *
 * The server's own list (`/auth/broker-config` and `/api/broker/keys`) decides
 * which brokers a trader can use and sends each one's display name. This list
 * is the fallback for a name the server did not send, and keeps the auth type
 * each broker signs in with.
 */

export type BrokerAuthType = 'totp' | 'oauth'

export interface BrokerInfo {
  id: string
  name: string
  authType: BrokerAuthType
}

export const BROKERS: readonly BrokerInfo[] = [
  { id: 'fivepaisa', name: '5 Paisa', authType: 'totp' },
  { id: 'fivepaisaxts', name: '5 Paisa (XTS)', authType: 'totp' },
  { id: 'aliceblue', name: 'Alice Blue', authType: 'totp' },
  { id: 'angel', name: 'Angel One', authType: 'totp' },
  { id: 'arrow', name: 'Arrow', authType: 'oauth' },
  { id: 'compositedge', name: 'CompositEdge', authType: 'oauth' },
  { id: 'dhan', name: 'Dhan', authType: 'oauth' },
  { id: 'deltaexchange', name: 'Delta Exchange', authType: 'totp' },
  { id: 'indmoney', name: 'IndMoney', authType: 'totp' },
  { id: 'dhan_sandbox', name: 'Dhan (Sandbox)', authType: 'totp' },
  { id: 'definedge', name: 'Definedge', authType: 'totp' },
  { id: 'firstock', name: 'Firstock', authType: 'totp' },
  { id: 'flattrade', name: 'Flattrade', authType: 'oauth' },
  { id: 'motilal', name: 'Motilal Oswal', authType: 'totp' },
  { id: 'fyers', name: 'Fyers', authType: 'oauth' },
  { id: 'groww', name: 'Groww', authType: 'totp' },
  { id: 'hdfcsecurities', name: 'HDFC Securities', authType: 'oauth' },
  { id: 'hdfcsky', name: 'HDFC Sky', authType: 'oauth' },
  { id: 'ibulls', name: 'Ibulls', authType: 'totp' },
  { id: 'iifl', name: 'IIFL', authType: 'totp' },
  { id: 'iiflcapital', name: 'IIFL Capital', authType: 'oauth' },
  { id: 'jainamxts', name: 'JainamXts', authType: 'totp' },
  { id: 'kotak', name: 'Kotak Securities', authType: 'totp' },
  { id: 'mstock', name: 'mStock by Mirae Asset', authType: 'totp' },
  { id: 'nubra', name: 'Nubra', authType: 'totp' },
  { id: 'paytm', name: 'Paytm Money', authType: 'oauth' },
  { id: 'pocketful', name: 'Pocketful', authType: 'oauth' },
  { id: 'rmoney', name: 'RMoney', authType: 'oauth' },
  { id: 'rupeezy', name: 'Rupeezy', authType: 'oauth' },
  { id: 'sahi', name: 'Sahi', authType: 'totp' },
  { id: 'samco', name: 'Samco', authType: 'totp' },
  { id: 'shoonya', name: 'Shoonya', authType: 'totp' },
  { id: 'tradejini', name: 'Tradejini', authType: 'totp' },
  { id: 'tradesmart', name: 'TradeSmart', authType: 'oauth' },
  { id: 'upstox', name: 'Upstox', authType: 'oauth' },
  { id: 'wisdom', name: 'Wisdom Capital', authType: 'totp' },
  { id: 'zebu', name: 'Zebu', authType: 'totp' },
  { id: 'zerodha', name: 'Zerodha', authType: 'oauth' },
]

/** A broker's name as a trader knows it, falling back to the id. */
export function brokerName(id: string | null | undefined): string {
  if (!id) return ''
  return BROKERS.find((broker) => broker.id === id)?.name ?? id
}

/**
 * Brokers whose API key packs several values into one field, and the layout
 * it takes. The server refuses a key that does not match (utils/broker_keys.py
 * `_KEY_FORMATS`), so the hint is shown before the trader saves.
 */
export const BROKER_KEY_FORMATS: Readonly<Record<string, string>> = {
  fivepaisa: 'User_Key:::User_ID:::client_id',
  flattrade: 'client_id:::api_key',
  dhan: 'client_id:::api_key',
}

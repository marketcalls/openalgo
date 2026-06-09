export interface BrokerConfig {
  broker_name: string
  broker_api_key: string
  redirect_url: string
}

function generateRandomState(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  let result = ''
  for (let i = 0; i < 16; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  return result
}

function getFlattradeApiKey(fullKey: string): string {
  if (!fullKey) return ''
  const parts = fullKey.split(':::')
  return parts.length > 1 ? parts[1] : fullKey
}

export function buildBrokerLoginUrl(broker: string, config: BrokerConfig): string | null {
  const { broker_api_key, redirect_url } = config

  switch (broker) {
    case 'fivepaisa':
    case 'fivepaisaxts':
    case 'aliceblue':
    case 'angel':
    case 'mstock':
    case 'indmoney':
    case 'deltaexchange':
    case 'jainamxts':
    case 'dhan_sandbox':
    case 'definedge':
    case 'firstock':
    case 'samco':
    case 'motilal':
    case 'nubra':
    case 'groww':
    case 'ibulls':
    case 'iifl':
    case 'kotak':
    case 'rmoney':
    case 'shoonya':
    case 'tradejini':
    case 'wisdom':
    case 'zebu':
      return `/${broker}/callback`

    case 'iiflcapital':
      return '/iiflcapital/callback'

    case 'dhan':
      return '/dhan/initiate-oauth'

    case 'compositedge':
      return `https://xts.compositedge.com/interactive/thirdparty?appKey=${broker_api_key}&returnURL=${redirect_url}`

    case 'flattrade':
      return `https://auth.flattrade.in/?app_key=${getFlattradeApiKey(broker_api_key)}`

    case 'fyers':
      return `https://api-t1.fyers.in/api/v3/generate-authcode?client_id=${broker_api_key}&redirect_uri=${redirect_url}&response_type=code&state=2e9b44629ebb28226224d09db3ffb47c`

    case 'upstox':
      return `https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id=${broker_api_key}&redirect_uri=${redirect_url}`

    case 'zerodha':
      return `https://kite.trade/connect/login?api_key=${broker_api_key}`

    case 'paytm':
      return `https://login.paytmmoney.com/merchant-login?apiKey=${broker_api_key}&state={default}`

    case 'pocketful': {
      const state = generateRandomState()
      localStorage.setItem('pocketful_oauth_state', state)
      const scope = 'orders holdings'
      return `https://trade.pocketful.in/oauth2/auth?client_id=${broker_api_key}&redirect_uri=${redirect_url}&response_type=code&scope=${encodeURIComponent(scope)}&state=${encodeURIComponent(state)}`
    }

    default:
      return null
  }
}

export async function initiateBrokerReconnect(): Promise<{ ok: true } | { ok: false; message: string }> {
  const response = await fetch('/auth/broker-config', { credentials: 'include' })
  const data = await response.json()

  if (data.status !== 'success') {
    return { ok: false, message: data.message || 'Failed to load broker configuration' }
  }

  const url = buildBrokerLoginUrl(data.broker_name, data)
  if (!url) {
    return { ok: false, message: `Unknown broker: ${data.broker_name}` }
  }

  window.location.href = url
  return { ok: true }
}

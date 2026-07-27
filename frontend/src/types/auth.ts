export interface User {
  username: string
  broker?: string
  isLoggedIn: boolean
}

export interface LoginCredentials {
  username: string
  password: string
}

export interface LoginResponse {
  status: 'success' | 'error'
  message?: string
}

export interface BrokerInfo {
  name: string
  displayName: string
  authType: 'oauth' | 'totp' | 'credentials'
  enabled: boolean
  logo?: string
}

export interface SessionInfo {
  logged_in: boolean
  user?: string
  broker?: string
  analyze_mode?: boolean
}

export interface TOTPCredentials {
  totp: string
  userid?: string
  password?: string
  apikey?: string
  apisecret?: string
}

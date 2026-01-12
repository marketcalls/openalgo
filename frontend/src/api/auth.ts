import type { BrokerInfo, LoginCredentials, LoginResponse, SessionInfo } from '@/types/auth'
import { authClient } from './client'

export const authApi = {
  /**
   * Login with username and password
   */
  login: async (credentials: LoginCredentials, csrfToken?: string): Promise<LoginResponse> => {
    const formData = new FormData()
    formData.append('username', credentials.username)
    formData.append('password', credentials.password)
    if (csrfToken) {
      formData.append('csrf_token', csrfToken)
    }

    const response = await authClient.post<LoginResponse>('/auth/login', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  /**
   * Logout current user
   */
  logout: async (): Promise<void> => {
    await authClient.post('/auth/logout')
  },

  /**
   * Get current session info
   */
  getSession: async (): Promise<SessionInfo> => {
    const response = await authClient.get<SessionInfo>('/auth/session')
    return response.data
  },

  /**
   * Get list of available brokers
   */
  getBrokers: async (): Promise<BrokerInfo[]> => {
    const response = await authClient.get<{ brokers: BrokerInfo[] }>('/auth/brokers')
    return response.data.brokers
  },

  /**
   * Initiate broker OAuth flow
   */
  initiateBrokerAuth: async (
    broker: string
  ): Promise<{ redirect_url?: string; requires_totp?: boolean }> => {
    const response = await authClient.post(`/auth/broker/${broker}`)
    return response.data
  },

  /**
   * Submit TOTP for broker authentication
   */
  submitTOTP: async (
    broker: string,
    totp: string,
    additionalFields?: Record<string, string>
  ): Promise<LoginResponse> => {
    const formData = new FormData()
    formData.append('totp', totp)
    if (additionalFields) {
      Object.entries(additionalFields).forEach(([key, value]) => {
        formData.append(key, value)
      })
    }
    const response = await authClient.post<LoginResponse>(`/${broker}/auth`, formData)
    return response.data
  },

  /**
   * Get CSRF token for forms
   */
  getCSRFToken: async (): Promise<string> => {
    const response = await authClient.get<{ csrf_token: string }>('/auth/csrf-token')
    return response.data.csrf_token
  },

  /**
   * Reset password request
   */
  resetPassword: async (email: string): Promise<LoginResponse> => {
    const formData = new FormData()
    formData.append('email', email)
    const response = await authClient.post<LoginResponse>('/auth/reset-password', formData)
    return response.data
  },

  /**
   * Change password
   */
  changePassword: async (currentPassword: string, newPassword: string): Promise<LoginResponse> => {
    const formData = new FormData()
    formData.append('current_password', currentPassword)
    formData.append('new_password', newPassword)
    const response = await authClient.post<LoginResponse>('/auth/change-password', formData)
    return response.data
  },
}

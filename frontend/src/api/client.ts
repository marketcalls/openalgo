import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_URL || ''

// Helper to fetch CSRF token
export async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', {
    credentials: 'include',
  })
  const data = await response.json()
  return data.csrf_token
}

/**
 * The methods Flask-WTF protects, which is what has to carry the token.
 *
 * Mirrors WTF_CSRF_METHODS, whose default is {POST, PUT, PATCH, DELETE}; app.py
 * never narrows it. Kept as one set so the two interceptors below cannot drift
 * apart, which is how PATCH came to be missing from both.
 */
const CSRF_METHODS = new Set(['post', 'put', 'patch', 'delete'])

export const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
})

// Request interceptor
apiClient.interceptors.request.use(
  (config) => {
    // API key can be added here if needed for specific endpoints
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Handle unauthorized - redirect to login
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// Auth client for login/logout operations
export const authClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/x-www-form-urlencoded',
  },
  withCredentials: true,
})

// Endpoints that don't require CSRF token (no session yet)
const CSRF_EXEMPT_ENDPOINTS = ['/auth/login', '/auth/setup']

// Add CSRF token to auth client requests (except for initial login/setup)
authClient.interceptors.request.use(
  async (config) => {
    // Check if endpoint is exempt from CSRF (exact match or starts with path + query/fragment)
    const url = config.url || ''
    const isExempt = CSRF_EXEMPT_ENDPOINTS.some((exempt) => {
      // Exact match or match with query string/fragment
      return url === exempt || url.startsWith(`${exempt}?`) || url.startsWith(`${exempt}#`)
    })

    // PATCH included: Flask-WTF's WTF_CSRF_METHODS defaults to
    // {POST, PUT, PATCH, DELETE} and app.py never narrows it, so a PATCH sent
    // without the header is rejected with 400 before it reaches the route.
    // Omitting it here did not weaken anything, it made every PATCH in the app
    // fail outright.
    if (!isExempt && CSRF_METHODS.has(config.method ?? '')) {
      // Fail the request rather than sending it without a token. Continuing
      // meant Flask-WTF rejected it anyway, but the caller saw an opaque CSRF
      // error instead of the real cause, and a failed logout still cleared
      // local state and routed to /login while the server session survived.
      let csrfToken: string
      try {
        csrfToken = await fetchCSRFToken()
      } catch (cause) {
        throw new Error(`Could not obtain a CSRF token for ${config.method} ${url}`, { cause })
      }
      if (!csrfToken) {
        throw new Error(`Empty CSRF token returned for ${config.method} ${url}`)
      }
      config.headers['X-CSRFToken'] = csrfToken
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Web client for session-based routes (non-API endpoints) with CSRF support
// Note: Don't set default Content-Type here - let axios set it automatically based on data type
// (multipart/form-data for FormData, application/json for objects, etc.)
export const webClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
})

// Add CSRF token to web client requests
webClient.interceptors.request.use(
  async (config) => {
    const method = config.method?.toLowerCase()
    if (CSRF_METHODS.has(method ?? '')) {
      try {
        const csrfToken = await fetchCSRFToken()
        if (!csrfToken) {
          // Reject request if CSRF token is empty - security requirement
          return Promise.reject(new Error('CSRF token is required for this operation'))
        }
        config.headers['X-CSRFToken'] = csrfToken
      } catch {
        // Reject request if CSRF token fetch fails - security requirement
        return Promise.reject(
          new Error('Failed to fetch CSRF token. Please refresh the page and try again.')
        )
      }
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor for web client
webClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    if (status === 401) {
      // Unauthorized - redirect to login
      window.location.href = '/login'
    } else if (status === 403) {
      // Forbidden - user doesn't have permission for this resource
      // Create a more descriptive error for the caller to handle
      error.message = 'You do not have permission to access this resource'
    } else {
      // Surface the server's own explanation instead of axios's generic
      // "Request failed with status code 400". Flask returns the useful text
      // in the body — `message` carries the specific reason (e.g. which node
      // field a workflow is missing) while `error` is the generic headline —
      // and callers only ever read `error.message`, so without this the real
      // cause reached the server log and nothing else.
      const data = error.response?.data
      const serverMessage =
        typeof data === 'string' ? data : data?.message || data?.error || data?.detail
      if (serverMessage) {
        error.message = serverMessage
      }
    }
    return Promise.reject(error)
  }
)

export default apiClient

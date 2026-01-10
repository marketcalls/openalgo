import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_URL || ''

// Helper to fetch CSRF token
async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', {
    credentials: 'include',
  });
  const data = await response.json();
  return data.csrf_token;
}

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

// Web client for session-based routes (non-API endpoints) with CSRF support
export const webClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
})

// Add CSRF token to web client requests
webClient.interceptors.request.use(
  async (config) => {
    if (config.method === 'post' || config.method === 'put' || config.method === 'delete') {
      try {
        const csrfToken = await fetchCSRFToken();
        console.log('[webClient] CSRF token fetched:', csrfToken ? 'OK' : 'EMPTY');
        config.headers['X-CSRFToken'] = csrfToken;
      } catch (e) {
        console.error('[webClient] Failed to fetch CSRF token:', e);
      }
    }
    console.log('[webClient] Request:', config.method?.toUpperCase(), config.url);
    return config;
  },
  (error) => {
    console.error('[webClient] Request error:', error);
    return Promise.reject(error);
  }
)

// Response interceptor for web client
webClient.interceptors.response.use(
  (response) => {
    console.log('[webClient] Response:', response.status, response.config.url);
    return response;
  },
  (error) => {
    console.error('[webClient] Response error:', error.response?.status, error.response?.data, error.config?.url);
    if (error.response?.status === 401) {
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default apiClient

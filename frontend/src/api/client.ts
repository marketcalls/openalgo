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
        if (!csrfToken) {
          // Reject request if CSRF token is empty - security requirement
          return Promise.reject(new Error('CSRF token is required for this operation'));
        }
        config.headers['X-CSRFToken'] = csrfToken;
      } catch (e) {
        console.error('[webClient] Failed to fetch CSRF token:', e);
        // Reject request if CSRF token fetch fails - security requirement
        return Promise.reject(new Error('Failed to fetch CSRF token. Please refresh the page and try again.'));
      }
    }
    return config;
  },
  (error) => {
    console.error('[webClient] Request error:', error);
    return Promise.reject(error);
  }
)

// Response interceptor for web client
webClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    if (status === 401) {
      // Unauthorized - redirect to login
      window.location.href = '/login';
    } else if (status === 403) {
      // Forbidden - user doesn't have permission for this resource
      // Create a more descriptive error for the caller to handle
      error.message = 'You do not have permission to access this resource';
    }
    return Promise.reject(error);
  }
)

export default apiClient

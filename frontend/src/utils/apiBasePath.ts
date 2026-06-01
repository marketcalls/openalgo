// Prefix absolute API paths with the Vite base path so OpenAlgo works when it is
// served under a sub-path (e.g. "/portfolio/openalgo/") behind a reverse proxy.
//
// Most of the codebase calls fetch() with absolute root paths like
// "/auth/csrf-token" or "/api/v1/...". Those ignore the deployment prefix and
// hit the gateway root, which breaks login and every other API call under a
// sub-path. (axios goes through src/api/client.ts, which is already base-aware.)
//
// This installs a one-time fetch() shim that rewrites same-origin absolute API
// paths to include the base prefix. It is a no-op when served at root.
const BASE = import.meta.env.BASE_URL.replace(/\/$/, '') // "" at root, "/portfolio/openalgo" under a sub-path

// Root path prefixes that belong to the OpenAlgo backend and must carry the base.
const API_PREFIXES = [
  '/auth/',
  '/api/',
  '/admin/',
  '/flow/',
  '/python/',
  '/tools/',
  '/sandbox/',
  '/analyzer/',
  '/chartink/',
  '/download/',
  '/ws/',
  '/socket.io/',
]

function needsPrefix(path: string): boolean {
  return (
    path.startsWith('/') &&
    !path.startsWith(BASE + '/') &&
    API_PREFIXES.some((p) => path === p.slice(0, -1) || path.startsWith(p))
  )
}

export function installApiBasePath(): void {
  if (!BASE) return // served at root — nothing to rewrite
  const orig = window.fetch.bind(window)
  window.fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    if (typeof input === 'string' && needsPrefix(input)) {
      return orig(BASE + input, init)
    }
    if (input instanceof Request) {
      try {
        const u = new URL(input.url)
        if (u.origin === window.location.origin && needsPrefix(u.pathname)) {
          return orig(new Request(BASE + u.pathname + u.search + u.hash, input), init)
        }
      } catch {
        // non-absolute or unparsable URL — leave untouched
      }
    }
    return orig(input as RequestInfo, init)
  }
}

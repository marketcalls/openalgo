import { beforeEach, describe, expect, it, vi } from 'vitest'
import { authClient, webClient } from './client'

/**
 * The CSRF interceptors themselves, not a mock of them.
 *
 * Every panel and page test mocks its API module wholesale, so nothing in the
 * suite ever ran an axios instance through these interceptors. That is how the
 * watchlist shipped a rename that could not work: PATCH was missing from both
 * method lists, Flask-WTF protects it by default, and the route answered 400
 * for every user who had not disabled CSRF.
 *
 * These assert on the request config the interceptor produces, so a method
 * dropped from the list fails here rather than in production.
 *
 * Only the two session-authenticated instances are covered. `apiClient` talks
 * to /api/v1/ with an API key and carries no CSRF interceptor at all, which is
 * correct: there is no cookie-borne session for a forged request to ride.
 */

const CSRF = 'test-csrf-token'

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ json: async () => ({ csrf_token: CSRF }) }) as unknown as Response)
  )
})

/** Run a request through an instance's interceptors without sending it. */
async function headersFor(
  instance: typeof webClient,
  method: string,
  url = '/watchlist/api/lists/1'
): Promise<Record<string, unknown>> {
  const handlers = instance.interceptors.request as unknown as {
    handlers: Array<{ fulfilled: (c: unknown) => Promise<unknown> }>
  }
  let config: Record<string, unknown> = { method, url, headers: {} }
  for (const handler of handlers.handlers) {
    if (handler?.fulfilled) config = (await handler.fulfilled(config)) as Record<string, unknown>
  }
  return config.headers as Record<string, unknown>
}

describe.each([
  ['authClient', authClient],
  ['webClient', webClient],
])('%s CSRF interceptor', (_name, instance) => {
  it.each([
    'post',
    'put',
    'patch',
    'delete',
  ])('attaches the token to %s, which Flask-WTF protects', async (method) => {
    const headers = await headersFor(instance, method)
    expect(headers['X-CSRFToken']).toBe(CSRF)
  })

  it('leaves a GET alone, which needs no token', async () => {
    const headers = await headersFor(instance, 'get')
    expect(headers['X-CSRFToken']).toBeUndefined()
  })
})

describe('the method list matches what the server protects', () => {
  it('covers PATCH, the method the watchlist rename uses', async () => {
    // Named for the regression: this is the only PATCH in the frontend, and
    // without it every rename returned 400.
    const headers = await headersFor(webClient, 'patch')
    expect(headers['X-CSRFToken']).toBe(CSRF)
  })
})

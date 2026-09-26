import {
  type AxiosAdapter,
  AxiosError,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'

/** What OpenAlgo says when it refuses a request that would wait too long for the broker. */
export const BROKER_BUSY_SENTENCE =
  "OpenAlgo is pacing requests to stay within your broker's rate limit, and this one would have had to wait too long for its turn. Try again in a few seconds."

/**
 * An axios adapter that answers like the server would, then fails the
 * request the way axios's own adapters do for a status outside
 * `validateStatus`. The instance's real response interceptors still run,
 * which a mocked API module would skip.
 */
export function answer(status: number, data: unknown): AxiosAdapter {
  return async (config: InternalAxiosRequestConfig) => {
    const response: AxiosResponse = {
      data,
      status,
      statusText: '',
      headers: {},
      config,
      request: {},
    }
    if (!config.validateStatus || config.validateStatus(status)) return response
    throw new AxiosError(
      `Request failed with status code ${status}`,
      status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST,
      config,
      {},
      response
    )
  }
}

/** The axios error a request fails with through `adapter`, built by a real request. */
export async function axiosFailure(
  request: (adapter: AxiosAdapter) => Promise<unknown>,
  status: number,
  data: unknown
): Promise<unknown> {
  try {
    await request(answer(status, data))
  } catch (error) {
    return error
  }
  throw new Error('the request was expected to fail')
}

/**
 * Give jsdom's Blob the `text()` every supported browser has.
 *
 * jsdom implements Blob without it, so without this a test would exercise a
 * fallback no browser ever takes. Installed only where it is missing.
 */
export function installBlobText(): void {
  if (typeof Blob.prototype.text === 'function') return
  Object.defineProperty(Blob.prototype, 'text', {
    configurable: true,
    value(this: Blob): Promise<string> {
      return new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result ?? ''))
        reader.onerror = () => reject(reader.error)
        reader.readAsText(this)
      })
    },
  })
}

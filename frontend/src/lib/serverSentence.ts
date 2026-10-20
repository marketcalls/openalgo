/**
 * The sentence a server wrote for the trader when it refused a request.
 *
 * Two answers carry text written for a person rather than for a log: 429,
 * when OpenAlgo turned a request away because it was busy (for example while
 * it paces requests to stay inside the broker's rate limit), and 409, when
 * the request clashed with something already in progress. Both come back as
 * JSON `{status: 'error', message}`, and the message says what happened and
 * what to do next. Showing a generic "Failed to fetch" instead hides the one
 * thing the trader can act on, which is usually to wait a few seconds.
 *
 * Every other failure keeps the caller's own text. The body of a 500 or a
 * proxy error page is not written for a trader, and deciding by status is
 * reliable where deciding by the shape of the text is guesswork (see
 * `historifyError` for why that was abandoned).
 */

/** The statuses whose JSON `message` is a sentence a trader can act on. */
export const SENTENCE_STATUSES: ReadonlySet<number> = new Set([409, 429])

function messageOf(body: unknown): string | null {
  let parsed = body
  if (typeof parsed === 'string') {
    try {
      parsed = JSON.parse(parsed)
    } catch {
      return null
    }
  }
  if (!parsed || typeof parsed !== 'object') return null
  const message = (parsed as { message?: unknown }).message
  if (typeof message !== 'string') return null
  const trimmed = message.trim()
  return trimmed || null
}

/**
 * Read the sentence from a status and a response body.
 *
 * @param status - The HTTP status of the answer.
 * @param body - The body, already parsed or as JSON text.
 * @returns The trimmed `message` for a 409 or 429 that carries one, else null.
 */
export function refusalSentence(status: unknown, body: unknown): string | null {
  if (typeof status !== 'number' || !SENTENCE_STATUSES.has(status)) return null
  return messageOf(body)
}

interface ResponseLike {
  status?: unknown
  data?: unknown
}

function responseOf(error: unknown): ResponseLike | undefined {
  if (!error || typeof error !== 'object') return undefined
  const response = (error as { response?: unknown }).response
  return response && typeof response === 'object' ? (response as ResponseLike) : undefined
}

/**
 * The text a failed request should show.
 *
 * @param error - Whatever the request threw (an axios error in practice).
 * @param fallback - The caller's own text, used for every other failure.
 * @returns The server's sentence for a 409 or 429 with a JSON message,
 *   otherwise `fallback` unchanged.
 */
export function serverSentence(error: unknown, fallback: string): string {
  const response = responseOf(error)
  return refusalSentence(response?.status, response?.data) ?? fallback
}

/**
 * The sentence for a request whose body was read as a Blob (a file
 * download), where a JSON refusal arrives unparsed.
 *
 * @returns The sentence for a 409 or 429 with a JSON message, else null.
 */
export async function blobRefusalSentence(error: unknown): Promise<string | null> {
  const response = responseOf(error)
  const status = response?.status
  if (typeof status !== 'number' || !SENTENCE_STATUSES.has(status)) return null
  const data = response?.data
  if (typeof Blob !== 'undefined' && data instanceof Blob) {
    try {
      return refusalSentence(status, await data.text())
    } catch {
      return null
    }
  }
  return refusalSentence(status, data)
}

function isAbort(error: unknown): boolean {
  return (error as { name?: unknown } | null)?.name === 'AbortError'
}

/**
 * The sentence carried by a failed `fetch()` response, or null.
 *
 * Reads the body only for a 409 or 429, so any other failure is left exactly
 * as it was for the caller to report. An abort while reading is rethrown, so
 * the caller's own abort handling still runs.
 */
export async function fetchRefusalSentence(response: Response): Promise<string | null> {
  if (!SENTENCE_STATUSES.has(response.status)) return null
  let body: string
  try {
    body = await response.text()
  } catch (error) {
    if (isAbort(error)) throw error
    return null
  }
  return refusalSentence(response.status, body)
}

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient, webClient } from '@/api/client'
import { axiosFailure, BROKER_BUSY_SENTENCE as BUSY, installBlobText } from '@/test/axiosAnswer'
import {
  blobRefusalSentence,
  fetchRefusalSentence,
  refusalSentence,
  serverSentence,
} from './serverSentence'

const FALLBACK = 'Failed to fetch GEX data'
const CONFLICT = 'A mode change is already in progress. Try again in a moment.'

beforeAll(() => {
  installBlobText()
})

beforeEach(() => {
  // webClient fetches a CSRF token before every POST.
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ json: async () => ({ csrf_token: 'test-csrf' }) }) as unknown as Response)
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const gexPost = (status: number, data: unknown) =>
  axiosFailure((adapter) => webClient.post('/gex/api/gex-data', {}, { adapter }), status, data)

describe('refusalSentence', () => {
  it.each([429, 409])('reads the message of a %i', (status) => {
    expect(refusalSentence(status, { status: 'error', message: BUSY })).toBe(BUSY)
  })

  it('parses a JSON body that arrived as text', () => {
    expect(refusalSentence(429, JSON.stringify({ message: BUSY }))).toBe(BUSY)
  })

  it.each([400, 403, 404, 500, 502, 503])('ignores the message of a %i', (status) => {
    expect(refusalSentence(status, { status: 'error', message: BUSY })).toBeNull()
  })

  it.each([
    ['an HTML page', '<html><body>Too Many Requests</body></html>'],
    ['no body', undefined],
    ['a body without a message', { status: 'error' }],
    ['a blank message', { message: '   ' }],
    ['a message that is not text', { message: { symbol: ['Missing data'] } }],
  ])('ignores a 429 with %s', (_label, body) => {
    expect(refusalSentence(429, body)).toBeNull()
  })

  it('trims the sentence', () => {
    expect(refusalSentence(429, { message: `  ${BUSY}\n` })).toBe(BUSY)
  })
})

describe('serverSentence', () => {
  it('shows the server sentence for a busy refusal through webClient', async () => {
    const error = await gexPost(429, { status: 'error', message: BUSY })
    expect(serverSentence(error, FALLBACK)).toBe(BUSY)
  })

  it('shows the server sentence for a conflict through apiClient', async () => {
    const error = await axiosFailure(
      (adapter) => apiClient.post('/basketorder', {}, { adapter }),
      409,
      { status: 'error', message: CONFLICT }
    )
    expect(serverSentence(error, FALLBACK)).toBe(CONFLICT)
  })

  it('keeps the caller text for a server failure, whatever its body says', async () => {
    const error = await gexPost(500, {
      status: 'error',
      message: 'Traceback (most recent call last)',
    })
    expect(serverSentence(error, FALLBACK)).toBe(FALLBACK)
  })

  it('keeps the caller text for a validation failure', async () => {
    const error = await gexPost(400, { status: 'error', message: 'Invalid expiry format' })
    expect(serverSentence(error, FALLBACK)).toBe(FALLBACK)
  })

  it('keeps the caller text when a 429 has no JSON message', async () => {
    const error = await gexPost(429, '<!doctype html>')
    expect(serverSentence(error, FALLBACK)).toBe(FALLBACK)
  })

  it.each([
    ['a network failure', new Error('Network Error')],
    ['a plain string', 'boom'],
    ['null', null],
    ['undefined', undefined],
  ])('keeps the caller text for %s', (_label, error) => {
    expect(serverSentence(error, FALLBACK)).toBe(FALLBACK)
  })
})

describe('blobRefusalSentence', () => {
  const tearsheet = (status: number, body: Blob) =>
    axiosFailure(
      (adapter) => apiClient.post('/portfolio/tearsheet', {}, { responseType: 'blob', adapter }),
      status,
      body
    )

  it('reads the sentence out of a Blob body', async () => {
    const error = await tearsheet(
      429,
      new Blob([JSON.stringify({ status: 'error', message: BUSY })], { type: 'application/json' })
    )
    await expect(blobRefusalSentence(error)).resolves.toBe(BUSY)
  })

  it('leaves any other status alone', async () => {
    const error = await tearsheet(
      500,
      new Blob([JSON.stringify({ message: 'Tearsheet generation failed.' })])
    )
    await expect(blobRefusalSentence(error)).resolves.toBeNull()
  })

  it('returns null for a Blob that is not JSON', async () => {
    const error = await tearsheet(429, new Blob(['<html></html>']))
    await expect(blobRefusalSentence(error)).resolves.toBeNull()
  })

  it('reads an already parsed body too', async () => {
    const error = await axiosFailure(
      (adapter) => apiClient.post('/portfolio/tearsheet', {}, { adapter }),
      429,
      { status: 'error', message: BUSY }
    )
    await expect(blobRefusalSentence(error)).resolves.toBe(BUSY)
  })
})

describe('fetchRefusalSentence', () => {
  it('reads the sentence of a 429 response', async () => {
    const response = new Response(JSON.stringify({ status: 'error', message: BUSY }), {
      status: 429,
      headers: { 'Content-Type': 'application/json' },
    })
    await expect(fetchRefusalSentence(response)).resolves.toBe(BUSY)
  })

  it('does not read the body of any other failure', async () => {
    const response = new Response(JSON.stringify({ message: 'internal' }), { status: 500 })
    await expect(fetchRefusalSentence(response)).resolves.toBeNull()
    expect(response.bodyUsed).toBe(false)
  })

  it('rethrows an abort so the caller can treat it as one', async () => {
    const abort = Object.assign(new Error('The operation was aborted.'), { name: 'AbortError' })
    const response = {
      status: 429,
      text: () => Promise.reject(abort),
    } as unknown as Response
    await expect(fetchRefusalSentence(response)).rejects.toBe(abort)
  })

  it('returns null when the body cannot be read for another reason', async () => {
    const response = {
      status: 429,
      text: () => Promise.reject(new TypeError('network error')),
    } as unknown as Response
    await expect(fetchRefusalSentence(response)).resolves.toBeNull()
  })
})

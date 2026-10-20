import { waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { handleWindowError, reportClientError, sanitizeErrorReportUrl } from './errorReporter'

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

function mockSuccessfulReportFetch() {
  const fetchMock = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ csrf_token: 'csrf-token-not-real' }),
    } as Response)
    .mockResolvedValueOnce({ status: 200 } as Response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function reportedPayload(fetchMock: ReturnType<typeof mockSuccessfulReportFetch>) {
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  const request = fetchMock.mock.calls[1]?.[1]
  return JSON.parse(String(request?.body))
}

describe('client error URL sanitization', () => {
  it('redacts sensitive query values and fragments from current-page reports', async () => {
    const fakeToken = 'test-token-not-real'
    window.history.replaceState(
      null,
      '',
      `/oauth/callback?code=${fakeToken}&next=dashboard#complete`
    )
    const fetchMock = mockSuccessfulReportFetch()

    reportClientError({ message: 'Test client error report' })

    const body = await reportedPayload(fetchMock)
    const reportedUrl = new URL(body.url)

    expect(`${reportedUrl.origin}${reportedUrl.pathname}`).toBe(
      `${window.location.origin}/oauth/callback`
    )
    expect(reportedUrl.searchParams.get('code')).toBe('[redacted]')
    expect(reportedUrl.searchParams.get('next')).toBe('dashboard')
    expect(body.url).not.toContain(fakeToken)
    expect(body.url).not.toContain('#')
  })

  it('redacts sensitive values in explicit payload URLs', async () => {
    const fakeToken = 'reset-token-not-real'
    const fetchMock = mockSuccessfulReportFetch()

    reportClientError({
      message: 'Explicit URL test',
      url: `https://app.example.com/search?symbol=INFY&token=${fakeToken}&apiKey=${fakeToken}#results`,
    })

    const body = await reportedPayload(fetchMock)
    const reportedUrl = new URL(body.url)

    expect(`${reportedUrl.origin}${reportedUrl.pathname}`).toBe('https://app.example.com/search')
    expect(reportedUrl.searchParams.get('symbol')).toBe('INFY')
    expect(reportedUrl.searchParams.get('token')).toBe('[redacted]')
    expect(reportedUrl.searchParams.get('apiKey')).toBe('[redacted]')
    expect(body.url).not.toContain(fakeToken)
    expect(body.url).not.toContain('#')
  })

  it('sanitizes window error filenames before reporting them', async () => {
    const fakeToken = 'extension-token-not-real'
    const fetchMock = mockSuccessfulReportFetch()

    handleWindowError(
      new ErrorEvent('error', {
        message: 'Extension script failed',
        filename: `chrome-extension://abcdef/content.js?token=${fakeToken}#line-1`,
      })
    )

    const body = await reportedPayload(fetchMock)

    expect(body.url).toBe('chrome-extension://abcdef/content.js')
    expect(body.url).not.toContain(fakeToken)
    expect(body.url).not.toContain('#')
  })

  it('redacts absolute and relative script URLs while preserving safe context', () => {
    const fakeResetToken = 'reset-token-not-real'

    const absolute = new URL(
      sanitizeErrorReportUrl(
        `https://cdn.example.com/assets/app.js?token=${fakeResetToken}&build=123#chunk`
      )
    )
    const relative = new URL(
      sanitizeErrorReportUrl(`/assets/app.js?token=${fakeResetToken}&build=123#chunk`)
    )

    expect(`${absolute.origin}${absolute.pathname}`).toBe('https://cdn.example.com/assets/app.js')
    expect(absolute.searchParams.get('token')).toBe('[redacted]')
    expect(absolute.searchParams.get('build')).toBe('123')
    expect(`${relative.origin}${relative.pathname}`).toBe(`${window.location.origin}/assets/app.js`)
    expect(relative.searchParams.get('token')).toBe('[redacted]')
    expect(relative.searchParams.get('build')).toBe('123')
  })

  it('keeps extension URLs actionable and reduces opaque schemes safely', () => {
    expect(
      sanitizeErrorReportUrl('moz-extension://guid/inject.js?token=test-token-not-real#chunk')
    ).toBe('moz-extension://guid/inject.js')
    expect(sanitizeErrorReportUrl('data:text/html;base64,PAYLOAD')).toBe('data:')
    expect(sanitizeErrorReportUrl('blob:http://host/uuid')).toBe('blob:')
  })

  it('keeps a plain asset filename useful without throwing', () => {
    expect(sanitizeErrorReportUrl('app.js')).toBe(`${window.location.origin}/app.js`)
  })

  it('falls back safely for malformed URLs', () => {
    expect(sanitizeErrorReportUrl('http://[')).toBe('http://[')
  })
})

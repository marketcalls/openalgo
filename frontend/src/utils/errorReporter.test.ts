import { waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { reportClientError, sanitizeErrorReportUrl } from './errorReporter'

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

describe('sanitizeErrorReportUrl', () => {
  it('removes query strings and fragments from current-page reports', async () => {
    const fakeToken = 'test-token-not-real'
    window.history.replaceState(null, '', `/oauth/callback?code=${fakeToken}#complete`)
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ csrf_token: 'csrf-token-not-real' }),
      } as Response)
      .mockResolvedValueOnce({ status: 200 } as Response)
    vi.stubGlobal('fetch', fetchMock)

    reportClientError({ message: 'Test client error report' })

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))

    const request = fetchMock.mock.calls[1]?.[1]
    const body = JSON.parse(String(request?.body))

    expect(body.url).toBe(`${window.location.origin}/oauth/callback`)
    expect(body.url).not.toContain(fakeToken)
    expect(body.url).not.toContain('?')
    expect(body.url).not.toContain('#')
  })

  it('sanitizes absolute and relative script URLs', () => {
    const fakeResetToken = 'reset-token-not-real'

    expect(
      sanitizeErrorReportUrl(
        `https://cdn.example.com/assets/app.js?token=${fakeResetToken}#chunk`,
      ),
    ).toBe('https://cdn.example.com/assets/app.js')
    expect(sanitizeErrorReportUrl(`/assets/app.js?token=${fakeResetToken}#chunk`)).toBe(
      `${window.location.origin}/assets/app.js`,
    )
  })

  it('keeps a plain asset filename useful without throwing', () => {
    expect(sanitizeErrorReportUrl('app.js')).toBe(`${window.location.origin}/app.js`)
  })
})

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { answer, BROKER_BUSY_SENTENCE, installBlobText } from '@/test/axiosAnswer'
import { apiClient } from './client'
import { type BacktestRequest, downloadTearsheet } from './portfolio'

/**
 * The tearsheet is fetched as a Blob, so a refusal's JSON arrives unparsed
 * and the page only ever saw "Request failed with status code 429". These run
 * the real apiClient with an adapter that answers like the server.
 */

const REQUEST: BacktestRequest = {
  apikey: 'key',
  holdings: [{ symbol: 'INFY', exchange: 'NSE', weight: 1 }],
  start_date: '2024-01-01',
  end_date: '2024-12-31',
}

const originalAdapter = apiClient.defaults.adapter

beforeAll(() => {
  installBlobText()
})

// jsdom has no object URLs, so the download path gets stand-ins.
const urlStatics = URL as unknown as Record<string, unknown>

beforeEach(() => {
  urlStatics.createObjectURL = vi.fn(() => 'blob:x')
  urlStatics.revokeObjectURL = vi.fn()
})

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter
  delete urlStatics.createObjectURL
  delete urlStatics.revokeObjectURL
  vi.useRealTimers()
})

const jsonBlob = (body: unknown) => new Blob([JSON.stringify(body)], { type: 'application/json' })

describe('downloadTearsheet', () => {
  it('fails with the server sentence when the request is refused as busy', async () => {
    apiClient.defaults.adapter = answer(
      429,
      jsonBlob({ status: 'error', message: BROKER_BUSY_SENTENCE })
    )
    await expect(downloadTearsheet(REQUEST)).rejects.toThrow(BROKER_BUSY_SENTENCE)
  })

  it('fails with the server sentence for the rate limit message too', async () => {
    const limited = 'Rate limit exceeded. Please slow down your requests.'
    apiClient.defaults.adapter = answer(429, jsonBlob({ status: 'error', message: limited }))
    await expect(downloadTearsheet(REQUEST)).rejects.toThrow(limited)
  })

  it('rethrows any other failure untouched', async () => {
    apiClient.defaults.adapter = answer(
      500,
      jsonBlob({ status: 'error', message: 'Tearsheet generation failed.' })
    )
    await expect(downloadTearsheet(REQUEST)).rejects.toThrow('Request failed with status code 500')
  })

  it('still downloads the file when the server answers', async () => {
    vi.useFakeTimers()
    apiClient.defaults.adapter = answer(
      200,
      new Blob(['<html>report</html>'], { type: 'text/html' })
    )
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    await downloadTearsheet(REQUEST)
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
    expect(click).toHaveBeenCalledTimes(1)
    vi.runAllTimers()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:x')
    click.mockRestore()
  })
})

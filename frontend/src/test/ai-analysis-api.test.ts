// frontend/src/test/ai-analysis-api.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock axios client
vi.mock('@/api/client', () => ({
  apiClient: {
    post: vi.fn(),
    get: vi.fn(),
  },
}))

import { aiAnalysisApi } from '@/api/ai-analysis'
import { apiClient } from '@/api/client'

describe('aiAnalysisApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('analyzeSymbol sends correct payload', async () => {
    const mockResponse = {
      data: {
        status: 'success',
        data: { symbol: 'RELIANCE', signal: 'BUY', confidence: 75.0 },
      },
    }
    vi.mocked(apiClient.post).mockResolvedValue(mockResponse)

    const result = await aiAnalysisApi.analyzeSymbol('test_key', 'RELIANCE', 'NSE', '1d')

    expect(apiClient.post).toHaveBeenCalledWith('/agent/analyze', {
      apikey: 'test_key',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      interval: '1d',
    })
    expect(result.status).toBe('success')
  })

  it('scanSymbols sends correct payload', async () => {
    const mockResponse = {
      data: { status: 'success', data: [{ symbol: 'RELIANCE', signal: 'BUY' }] },
    }
    vi.mocked(apiClient.post).mockResolvedValue(mockResponse)

    const result = await aiAnalysisApi.scanSymbols('test_key', ['RELIANCE', 'SBIN'], 'NSE')

    expect(apiClient.post).toHaveBeenCalledWith('/agent/scan', {
      apikey: 'test_key',
      symbols: ['RELIANCE', 'SBIN'],
      exchange: 'NSE',
      interval: '1d',
    })
    expect(result.status).toBe('success')
  })

  it('getStatus calls correct endpoint', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { status: 'success', data: { agent: 'active' } },
    })

    const result = await aiAnalysisApi.getStatus()
    expect(apiClient.get).toHaveBeenCalledWith('/agent/status')
    expect(result.data?.agent).toBe('active')
  })
})

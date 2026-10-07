import { render, waitFor } from '@testing-library/react'
import axios from 'axios'
import type { ComponentType } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { axiosFailure, BROKER_BUSY_SENTENCE } from '@/test/axiosAnswer'

/**
 * The /tools pages that load on their own once an expiry is chosen.
 *
 * Under the gthread web server a request that would wait too long behind the
 * broker's rate limit is refused with 429 and a sentence saying so. These
 * pages used to swallow the failure and toast their own generic text, so a
 * trader saw "Failed to fetch GEX data" and nothing about waiting a few
 * seconds. Every other failure must keep that generic text.
 */

const mocks = vi.hoisted(() => {
  const listing = () => ({
    getUnderlyings: vi.fn(),
    getExpiries: vi.fn(),
  })
  return {
    toastError: vi.fn(),
    gex: { ...listing(), getGEXData: vi.fn() },
    gamma: { ...listing(), getGammaDensity: vi.fn() },
    ivSmile: { ...listing(), getIVSmileData: vi.fn() },
    oiTracker: { ...listing(), getOIData: vi.fn(), getMaxPain: vi.fn() },
    oiProfile: { ...listing(), getIntervals: vi.fn(), getProfileData: vi.fn() },
  }
})

vi.mock('@/api/gex', () => ({ gexApi: mocks.gex }))
vi.mock('@/api/gamma-density', () => ({ gammaDensityApi: mocks.gamma }))
vi.mock('@/api/iv-smile', () => ({ ivSmileApi: mocks.ivSmile }))
vi.mock('@/api/oi-tracker', () => ({ oiTrackerApi: mocks.oiTracker }))
vi.mock('@/api/oi-profile', () => ({ oiProfileApi: mocks.oiProfile }))
vi.mock('@/lib/Plot2D', () => ({ default: () => null }))
vi.mock('@/utils/toast', () => ({
  showToast: {
    error: mocks.toastError,
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    dismissAll: vi.fn(),
    dynamic: vi.fn(),
    show: vi.fn(),
  },
}))
vi.mock('@/hooks/useSupportedExchanges', () => {
  const exchanges = [{ value: 'NFO', label: 'NFO' }]
  const value = {
    toolsFnoExchanges: exchanges,
    defaultToolsFnoExchange: 'NFO',
    fnoExchanges: exchanges,
    defaultFnoExchange: 'NFO',
    defaultUnderlyings: { NFO: ['NIFTY'] },
    isCrypto: false,
  }
  return { useSupportedExchanges: () => value }
})

type ApiMock = Record<string, ReturnType<typeof vi.fn>>

interface PageCase {
  name: string
  load: () => Promise<{ default: ComponentType }>
  api: ApiMock
  dataMethod: string
  fallback: string
}

const PAGES: PageCase[] = [
  {
    name: 'GEX Dashboard',
    load: () => import('./GEXDashboard'),
    api: mocks.gex,
    dataMethod: 'getGEXData',
    fallback: 'Failed to fetch GEX data',
  },
  {
    name: 'Gamma Density',
    load: () => import('./GammaDensity'),
    api: mocks.gamma,
    dataMethod: 'getGammaDensity',
    fallback: 'Failed to fetch gamma density',
  },
  {
    name: 'IV Smile',
    load: () => import('./IVSmile'),
    api: mocks.ivSmile,
    dataMethod: 'getIVSmileData',
    fallback: 'Failed to fetch IV Smile data',
  },
  {
    name: 'OI Tracker',
    load: () => import('./OITracker'),
    api: mocks.oiTracker,
    dataMethod: 'getOIData',
    fallback: 'Failed to fetch OI data',
  },
  {
    name: 'OI Range',
    load: () => import('./OIRange'),
    api: mocks.oiTracker,
    dataMethod: 'getOIData',
    fallback: 'Failed to fetch OI data',
  },
  {
    name: 'Max Pain',
    load: () => import('./MaxPain'),
    api: mocks.oiTracker,
    dataMethod: 'getMaxPain',
    fallback: 'Failed to calculate Max Pain',
  },
  {
    name: 'OI Profile',
    load: () => import('./OIProfile'),
    api: mocks.oiProfile,
    dataMethod: 'getProfileData',
    fallback: 'Failed to fetch OI Profile data',
  },
]

/** A real axios failure with the status and body the server sent. */
const failure = (status: number, data: unknown) =>
  axiosFailure((adapter) => axios.post('/tools/api/data', {}, { adapter }), status, data)

beforeEach(() => {
  const apis = [mocks.gex, mocks.gamma, mocks.ivSmile, mocks.oiTracker, mocks.oiProfile]
  for (const api of apis as ApiMock[]) {
    for (const fn of Object.values(api)) fn.mockReset()
    api.getUnderlyings.mockResolvedValue({ status: 'success', underlyings: ['NIFTY'] })
    api.getExpiries.mockResolvedValue({ status: 'success', expiries: ['28-AUG-2026'] })
  }
  mocks.oiProfile.getIntervals.mockResolvedValue({ status: 'success', data: { intervals: ['5m'] } })
  mocks.toastError.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe.each(PAGES)('$name', ({ load, api, dataMethod, fallback }) => {
  const renderPage = async (error: unknown) => {
    api[dataMethod].mockRejectedValue(error)
    const { default: Page } = await load()
    render(<Page />)
    await waitFor(() => expect(api[dataMethod]).toHaveBeenCalled())
    await waitFor(() => expect(mocks.toastError).toHaveBeenCalled())
    return mocks.toastError.mock.calls.map((call) => call[0])
  }

  it('shows the sentence of a busy refusal', async () => {
    const shown = await renderPage(
      await failure(429, { status: 'error', message: BROKER_BUSY_SENTENCE })
    )
    expect(shown).toContain(BROKER_BUSY_SENTENCE)
    expect(shown).not.toContain(fallback)
  })

  it('shows the sentence of a conflict', async () => {
    const conflict = 'The master contract is being reloaded. Try again in a minute.'
    const shown = await renderPage(await failure(409, { status: 'error', message: conflict }))
    expect(shown).toContain(conflict)
  })

  it('keeps its own text for a server failure', async () => {
    const shown = await renderPage(
      await failure(500, { status: 'error', message: 'An unexpected error occurred' })
    )
    expect(shown).toContain(fallback)
    expect(shown).not.toContain('An unexpected error occurred')
  })

  it('keeps its own text when the network fails', async () => {
    const shown = await renderPage(new Error('Network Error'))
    expect(shown).toContain(fallback)
  })
})

import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { usePnlFilters } from './usePnlFilters'

const wrapper =
  (initial: string) =>
  ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[initial]}>{children}</MemoryRouter>
  )

describe('usePnlFilters', () => {
  it('starts with no segment and no P&L type, so nothing can be fetched', () => {
    const { result } = renderHook(() => usePnlFilters(), { wrapper: wrapper('/pnl') })
    expect(result.current.segment).toBe('')
    expect(result.current.pnlType).toBe('')
    expect(result.current.ready).toBe(false)
    expect(result.current.embedded).toBeNull()
  })

  it('is ready once both are chosen, and Fetch bumps the counter', () => {
    const { result } = renderHook(() => usePnlFilters(), { wrapper: wrapper('/pnl') })
    act(() => result.current.setSegment('equity'))
    expect(result.current.ready).toBe(false)
    act(() => result.current.setPnlType('combined'))
    expect(result.current.ready).toBe(true)
    expect(result.current.embedded?.fetchToken).toBe(0)
    act(() => result.current.fetch())
    expect(result.current.embedded?.fetchToken).toBe(1)
  })

  it('reads filters from the URL and ignores values it does not know', () => {
    const { result } = renderHook(() => usePnlFilters(), {
      wrapper: wrapper('/pnl?segment=fno&type=nonsense&start=2026-05-01&end=2026-05-31'),
    })
    expect(result.current.segment).toBe('fno')
    expect(result.current.pnlType).toBe('')
    expect(result.current.startDate).toBe('2026-05-01')
    expect(result.current.endDate).toBe('2026-05-31')
  })

  it('defaults the range to the last 30 days', () => {
    const { result } = renderHook(() => usePnlFilters(), { wrapper: wrapper('/pnl') })
    const days =
      (Date.parse(result.current.endDate) - Date.parse(result.current.startDate)) / 86400000
    expect(days).toBe(30)
  })
})

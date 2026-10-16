// frontend/src/hooks/usePnlFilters.ts
/**
 * Shared filters for the merged P&L page (fork-only, SKYSHIELD_PATCHES.md):
 * segment, P&L type and the date range live in the URL query, so a
 * refresh or a shared link opens the same view. Segment and P&L type start
 * empty on purpose: nothing is fetched until both are chosen.
 */
import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import type { Segment } from '@/types/trading'

export type PnlSegmentChoice = '' | 'all' | Segment
export type PnlTypeChoice = '' | 'realized' | 'unrealized' | 'combined'

/** The Filters dialog: narrows both tabs. Empty means no narrowing. */
export interface PnlTableFilters {
  symbol: string
  strategies: string[]
  exchanges: string[]
  products: string[]
}

export const EMPTY_TABLE_FILTERS: PnlTableFilters = {
  symbol: '',
  strategies: [],
  exchanges: [],
  products: [],
}

/** Values the tabs report back for the dialog's chips. */
export interface PnlOptions {
  strategies: string[]
  exchanges: string[]
  products: string[]
}

/** What an embedded tab gets: always complete, plus a counter that bumps on Fetch. */
export interface PnlEmbeddedFilters {
  segment: 'all' | Segment
  pnlType: 'realized' | 'unrealized' | 'combined'
  startDate: string
  endDate: string
  fetchToken: number
  tableFilters: PnlTableFilters
  onOptions: (options: Partial<PnlOptions>) => void
}

function union(a: string[], b: string[] | undefined): string[] {
  if (!b || b.every((v) => a.includes(v))) return a
  return Array.from(new Set([...a, ...b])).sort()
}

const SEGMENTS: PnlSegmentChoice[] = [
  'all',
  'equity',
  'fno',
  'currency',
  'commodity',
  'mutual_fund',
]
const TYPES: PnlTypeChoice[] = ['realized', 'unrealized', 'combined']

function isoDate(d: Date): string {
  return d.toLocaleDateString('en-CA')
}

export function usePnlFilters() {
  const [params, setParams] = useSearchParams()
  const [fetchToken, setFetchToken] = useState(0)
  const [activePreset, setActivePreset] = useState<string | null>(null)
  const [tableFilters, setTableFilters] = useState<PnlTableFilters>(EMPTY_TABLE_FILTERS)
  const [options, setOptions] = useState<PnlOptions>({
    strategies: [],
    exchanges: [],
    products: [],
  })
  const onOptions = useCallback((incoming: Partial<PnlOptions>) => {
    setOptions((prev) => {
      const next = {
        strategies: union(prev.strategies, incoming.strategies),
        exchanges: union(prev.exchanges, incoming.exchanges),
        products: union(prev.products, incoming.products),
      }
      const same =
        next.strategies === prev.strategies &&
        next.exchanges === prev.exchanges &&
        next.products === prev.products
      return same ? prev : next
    })
  }, [])

  const today = isoDate(new Date())
  const thirtyAgo = (() => {
    const d = new Date()
    d.setDate(d.getDate() - 30)
    return isoDate(d)
  })()

  const rawSegment = params.get('segment') ?? ''
  const segment = (
    SEGMENTS.includes(rawSegment as PnlSegmentChoice) ? rawSegment : ''
  ) as PnlSegmentChoice
  const rawType = params.get('type') ?? ''
  const pnlType = (TYPES.includes(rawType as PnlTypeChoice) ? rawType : '') as PnlTypeChoice
  const startDate = params.get('start') || thirtyAgo
  const endDate = params.get('end') || today

  const update = useCallback(
    (changes: Record<string, string | null>) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          for (const [key, value] of Object.entries(changes)) {
            if (value === null || value === '') next.delete(key)
            else next.set(key, value)
          }
          return next
        },
        { replace: true }
      )
    },
    [setParams]
  )

  const ready = segment !== '' && pnlType !== ''

  const embedded: PnlEmbeddedFilters | null = useMemo(
    () =>
      ready
        ? {
            segment: segment as 'all' | Segment,
            pnlType: pnlType as 'realized' | 'unrealized' | 'combined',
            startDate,
            endDate,
            fetchToken,
            tableFilters,
            onOptions,
          }
        : null,
    [ready, segment, pnlType, startDate, endDate, fetchToken, tableFilters, onOptions]
  )

  return {
    segment,
    pnlType,
    startDate,
    endDate,
    ready,
    embedded,
    activePreset,
    today,
    tableFilters,
    setTableFilters,
    options,
    setSegment: (value: PnlSegmentChoice) => update({ segment: value }),
    setPnlType: (value: PnlTypeChoice) => update({ type: value }),
    setStartDate: (value: string) => {
      setActivePreset(null)
      update({ start: value })
    },
    setEndDate: (value: string) => {
      setActivePreset(null)
      update({ end: value })
    },
    applyPreset: (start: string, end: string, key: string) => {
      setActivePreset(key)
      update({ start, end })
      setFetchToken((n) => n + 1)
    },
    fetch: () => setFetchToken((n) => n + 1),
  }
}

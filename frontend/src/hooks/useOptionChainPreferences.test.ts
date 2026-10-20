import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import type { ColumnKey } from '@/types/option-chain'
import { COLUMN_DEFINITIONS, LOCALSTORAGE_KEY, LOGICAL_COLUMNS } from '@/types/option-chain'
import { useOptionChainPreferences } from './useOptionChainPreferences'

describe('LOGICAL_COLUMNS', () => {
  it('pairs every column across both sides', () => {
    // The chain is mirrored, so a logical column that only reaches one side
    // would leave the other stuck on screen when unchecked.
    for (const col of LOGICAL_COLUMNS) {
      expect(col.keys, `${col.label} is not paired`).toHaveLength(2)
      expect(col.keys[0].startsWith('ce_')).toBe(true)
      expect(col.keys[1].startsWith('pe_')).toBe(true)
      expect(col.keys[0].slice(3)).toBe(col.keys[1].slice(3))
    }
  })

  it('covers every non-strike column exactly once', () => {
    const covered = LOGICAL_COLUMNS.flatMap((col) => col.keys).sort()
    const expected = COLUMN_DEFINITIONS.map((col) => col.key)
      .filter((key) => key !== 'strike')
      .sort()
    expect(covered).toEqual(expected)
  })

  it('exposes the five Greeks', () => {
    expect(LOGICAL_COLUMNS.filter((col) => col.isGreek).map((col) => col.label)).toEqual([
      'IV',
      'Vega',
      'Theta',
      'Gamma',
      'Delta',
    ])
  })
})

describe('useOptionChainPreferences', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  const greekPair = (label: string): ColumnKey[] =>
    LOGICAL_COLUMNS.find((col) => col.label === label)?.keys ?? []

  it('hides a Greek from both sides in one toggle', () => {
    const { result } = renderHook(() => useOptionChainPreferences())

    act(() => result.current.setViewMode('greeks'))
    const delta = greekPair('Delta')
    expect(delta.every((key) => result.current.visibleColumns.includes(key))).toBe(true)

    act(() => result.current.toggleColumn(delta))

    // Both sides must go, not just the CALL column.
    expect(delta.some((key) => result.current.visibleColumns.includes(key))).toBe(false)
  })

  it('restores both sides when toggled back on', () => {
    const { result } = renderHook(() => useOptionChainPreferences())
    act(() => result.current.setViewMode('greeks'))
    const vega = greekPair('Vega')

    act(() => result.current.toggleColumn(vega))
    act(() => result.current.toggleColumn(vega))

    expect(vega.every((key) => result.current.visibleColumns.includes(key))).toBe(true)
  })

  it('converges a pair that has drifted out of sync instead of swapping sides', () => {
    const { result } = renderHook(() => useOptionChainPreferences())
    act(() => result.current.setViewMode('greeks'))
    const theta = greekPair('Theta')

    // Hide only the CE side, mimicking preferences saved before pairing existed.
    act(() => result.current.toggleColumn(theta[0]))
    expect(result.current.visibleColumns).not.toContain(theta[0])
    expect(result.current.visibleColumns).toContain(theta[1])

    // One click on the pair should clear the remainder, not flip both.
    act(() => result.current.toggleColumn(theta))
    expect(theta.some((key) => result.current.visibleColumns.includes(key))).toBe(false)
  })

  it('never hides the strike column', () => {
    const { result } = renderHook(() => useOptionChainPreferences())

    act(() => result.current.toggleColumn('strike'))
    expect(result.current.visibleColumns).toContain('strike')

    act(() => result.current.toggleColumn(['strike']))
    expect(result.current.visibleColumns).toContain('strike')
  })

  it('keeps each mode independent', () => {
    const { result } = renderHook(() => useOptionChainPreferences())
    const oi = greekPair('OI')

    act(() => result.current.toggleColumn(oi))
    expect(oi.some((key) => result.current.visibleColumns.includes(key))).toBe(false)

    // Greeks mode has its own column set and must be untouched.
    act(() => result.current.setViewMode('greeks'))
    expect(result.current.visibleColumns).toContain('ce_delta')

    act(() => result.current.setViewMode('price'))
    expect(oi.some((key) => result.current.visibleColumns.includes(key))).toBe(false)
  })

  it('resets only the active mode', () => {
    const { result } = renderHook(() => useOptionChainPreferences())

    act(() => result.current.setViewMode('greeks'))
    act(() => result.current.toggleColumn(greekPair('Delta')))
    act(() => result.current.resetToDefaults())
    expect(result.current.visibleColumns).toContain('ce_delta')
    expect(result.current.visibleColumns).toContain('pe_delta')
  })

  it('migrates the pre-view-mode flat layout into Price mode', () => {
    // Shape written by the version before view modes existed.
    localStorage.setItem(
      LOCALSTORAGE_KEY,
      JSON.stringify({
        visibleColumns: ['ce_oi', 'ce_ltp', 'strike', 'pe_ltp', 'pe_oi'],
        columnOrder: ['ce_oi', 'ce_ltp', 'strike', 'pe_ltp', 'pe_oi'],
        strikeCount: 20,
        selectedUnderlying: 'BANKNIFTY',
        barDataSource: 'volume',
        barStyle: 'solid',
      })
    )

    const { result } = renderHook(() => useOptionChainPreferences())

    expect(result.current.viewMode).toBe('price')
    expect(result.current.strikeCount).toBe(20)
    expect(result.current.selectedUnderlying).toBe('BANKNIFTY')
    expect(result.current.barDataSource).toBe('volume')
    // The saved arrangement survives rather than resetting.
    expect(result.current.visibleColumns).toEqual(['ce_oi', 'ce_ltp', 'strike', 'pe_ltp', 'pe_oi'])
    // Columns added since are appended so they can still be enabled.
    expect(result.current.columnOrder).toContain('ce_delta')
    expect(result.current.columnOrder).toContain('pe_iv')

    // Greeks mode still gets its defaults.
    act(() => result.current.setViewMode('greeks'))
    expect(result.current.visibleColumns).toContain('ce_delta')
  })

  it('always keeps the strike column after loading stored preferences', () => {
    localStorage.setItem(
      LOCALSTORAGE_KEY,
      JSON.stringify({ visibleColumns: ['ce_ltp', 'pe_ltp'], columnOrder: ['ce_ltp', 'pe_ltp'] })
    )

    const { result } = renderHook(() => useOptionChainPreferences())
    expect(result.current.visibleColumns).toContain('strike')
  })

  it('falls back to defaults on unparseable storage', () => {
    localStorage.setItem(LOCALSTORAGE_KEY, '{not json')
    const { result } = renderHook(() => useOptionChainPreferences())
    expect(result.current.viewMode).toBe('price')
    expect(result.current.visibleColumns).toContain('strike')
  })

  it('drops column keys that no longer exist', () => {
    localStorage.setItem(
      LOCALSTORAGE_KEY,
      JSON.stringify({
        modes: {
          price: {
            visibleColumns: ['ce_ltp', 'ce_retired', 'strike'],
            columnOrder: ['ce_retired'],
          },
        },
      })
    )

    const { result } = renderHook(() => useOptionChainPreferences())
    expect(result.current.visibleColumns).not.toContain('ce_retired')
    expect(result.current.columnOrder).not.toContain('ce_retired')
  })
})

import { useCallback, useEffect, useState } from 'react'
import type { BarDataSource, BarStyle, ColumnKey, OptionChainPreferences } from '@/types/option-chain'
import {
  COLUMN_DEFINITIONS,
  DEFAULT_PREFERENCES,
  LOCALSTORAGE_KEY,
} from '@/types/option-chain'

interface UseOptionChainPreferencesReturn {
  preferences: OptionChainPreferences
  visibleColumns: ColumnKey[]
  columnOrder: ColumnKey[]
  strikeCount: number
  selectedUnderlying: string
  barDataSource: BarDataSource
  barStyle: BarStyle
  toggleColumn: (columnKey: ColumnKey) => void
  reorderColumns: (newOrder: ColumnKey[]) => void
  setStrikeCount: (count: number) => void
  setSelectedUnderlying: (underlying: string) => void
  setBarDataSource: (source: BarDataSource) => void
  setBarStyle: (style: BarStyle) => void
  resetToDefaults: () => void
  isColumnVisible: (columnKey: ColumnKey) => boolean
  getOrderedVisibleColumns: () => ColumnKey[]
}

function loadPreferences(): OptionChainPreferences {
  if (typeof window === 'undefined') {
    return DEFAULT_PREFERENCES
  }

  try {
    const stored = localStorage.getItem(LOCALSTORAGE_KEY)
    if (!stored) {
      return DEFAULT_PREFERENCES
    }

    const parsed = JSON.parse(stored) as Partial<OptionChainPreferences>

    // Validate and merge with defaults
    const validColumnKeys = new Set(COLUMN_DEFINITIONS.map(c => c.key))

    const visibleColumns = Array.isArray(parsed.visibleColumns)
      ? parsed.visibleColumns.filter(key => validColumnKeys.has(key))
      : DEFAULT_PREFERENCES.visibleColumns

    // Ensure strike column is always visible (mandatory)
    if (!visibleColumns.includes('strike')) {
      visibleColumns.push('strike')
    }

    const columnOrder = Array.isArray(parsed.columnOrder)
      ? parsed.columnOrder.filter(key => validColumnKeys.has(key))
      : DEFAULT_PREFERENCES.columnOrder

    // Ensure all valid columns are in the order (add any missing ones)
    const orderSet = new Set(columnOrder)
    DEFAULT_PREFERENCES.columnOrder.forEach(key => {
      if (!orderSet.has(key)) {
        columnOrder.push(key)
      }
    })

    return {
      visibleColumns,
      columnOrder,
      strikeCount: typeof parsed.strikeCount === 'number' && parsed.strikeCount > 0
        ? parsed.strikeCount
        : DEFAULT_PREFERENCES.strikeCount,
      selectedUnderlying: typeof parsed.selectedUnderlying === 'string' && parsed.selectedUnderlying
        ? parsed.selectedUnderlying
        : DEFAULT_PREFERENCES.selectedUnderlying,
      barDataSource: parsed.barDataSource === 'oi' || parsed.barDataSource === 'volume'
        ? parsed.barDataSource
        : DEFAULT_PREFERENCES.barDataSource,
      barStyle: parsed.barStyle === 'gradient' || parsed.barStyle === 'solid'
        ? parsed.barStyle
        : DEFAULT_PREFERENCES.barStyle,
    }
  } catch {
    return DEFAULT_PREFERENCES
  }
}

function savePreferences(preferences: OptionChainPreferences): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    localStorage.setItem(LOCALSTORAGE_KEY, JSON.stringify(preferences))
  } catch {
    // Silently fail if localStorage is unavailable
  }
}

export function useOptionChainPreferences(): UseOptionChainPreferencesReturn {
  const [preferences, setPreferences] = useState<OptionChainPreferences>(() => loadPreferences())

  // Persist changes to localStorage
  useEffect(() => {
    savePreferences(preferences)
  }, [preferences])

  const toggleColumn = useCallback((columnKey: ColumnKey) => {
    // Don't allow hiding the strike column
    if (columnKey === 'strike') {
      return
    }

    setPreferences(prev => {
      const isVisible = prev.visibleColumns.includes(columnKey)
      const newVisibleColumns = isVisible
        ? prev.visibleColumns.filter(key => key !== columnKey)
        : [...prev.visibleColumns, columnKey]

      return {
        ...prev,
        visibleColumns: newVisibleColumns,
      }
    })
  }, [])

  const reorderColumns = useCallback((newOrder: ColumnKey[]) => {
    setPreferences(prev => ({
      ...prev,
      columnOrder: newOrder,
    }))
  }, [])

  const setStrikeCount = useCallback((count: number) => {
    setPreferences(prev => ({
      ...prev,
      strikeCount: count,
    }))
  }, [])

  const setSelectedUnderlying = useCallback((underlying: string) => {
    setPreferences(prev => ({
      ...prev,
      selectedUnderlying: underlying,
    }))
  }, [])

  const setBarDataSource = useCallback((source: BarDataSource) => {
    setPreferences(prev => ({
      ...prev,
      barDataSource: source,
    }))
  }, [])

  const setBarStyle = useCallback((style: BarStyle) => {
    setPreferences(prev => ({
      ...prev,
      barStyle: style,
    }))
  }, [])

  const resetToDefaults = useCallback(() => {
    setPreferences(DEFAULT_PREFERENCES)
  }, [])

  const isColumnVisible = useCallback((columnKey: ColumnKey): boolean => {
    return preferences.visibleColumns.includes(columnKey)
  }, [preferences.visibleColumns])

  const getOrderedVisibleColumns = useCallback((): ColumnKey[] => {
    // Return columns in the specified order, filtered to only visible ones
    return preferences.columnOrder.filter(key => preferences.visibleColumns.includes(key))
  }, [preferences.columnOrder, preferences.visibleColumns])

  return {
    preferences,
    visibleColumns: preferences.visibleColumns,
    columnOrder: preferences.columnOrder,
    strikeCount: preferences.strikeCount,
    selectedUnderlying: preferences.selectedUnderlying,
    barDataSource: preferences.barDataSource,
    barStyle: preferences.barStyle,
    toggleColumn,
    reorderColumns,
    setStrikeCount,
    setSelectedUnderlying,
    setBarDataSource,
    setBarStyle,
    resetToDefaults,
    isColumnVisible,
    getOrderedVisibleColumns,
  }
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  BarDataSource,
  BarStyle,
  ColumnKey,
  ModePreferences,
  OptionChainPreferences,
  ViewMode,
} from '@/types/option-chain'
import {
  ALL_COLUMN_KEYS,
  DEFAULT_MODE_PREFERENCES,
  DEFAULT_PREFERENCES,
  LOCALSTORAGE_KEY,
} from '@/types/option-chain'

interface UseOptionChainPreferencesReturn {
  preferences: OptionChainPreferences
  viewMode: ViewMode
  /** Visible columns for the active view mode */
  visibleColumns: ColumnKey[]
  /** Column order for the active view mode */
  columnOrder: ColumnKey[]
  strikeCount: number
  selectedUnderlying: string
  barDataSource: BarDataSource
  barStyle: BarStyle
  setViewMode: (mode: ViewMode) => void
  /** Accepts a CE/PE pair so one click hides a column from both sides */
  toggleColumn: (columnKey: ColumnKey | ColumnKey[]) => void
  reorderColumns: (newOrder: ColumnKey[]) => void
  setStrikeCount: (count: number) => void
  setSelectedUnderlying: (underlying: string) => void
  setBarDataSource: (source: BarDataSource) => void
  setBarStyle: (style: BarStyle) => void
  resetToDefaults: () => void
  isColumnVisible: (columnKey: ColumnKey) => boolean
  getOrderedVisibleColumns: () => ColumnKey[]
}

const VALID_COLUMN_KEYS = new Set<ColumnKey>(ALL_COLUMN_KEYS)

/**
 * Normalize one mode's stored columns against the current column set.
 *
 * Columns are added and removed across releases, so stored preferences are
 * treated as a hint: unknown keys are dropped and missing ones are appended in
 * the default order. The page filters this list by side, so appending at the
 * end still places a newly-added column correctly within its own side.
 */
function sanitizeMode(raw: unknown, fallback: ModePreferences): ModePreferences {
  const stored = (raw ?? {}) as Partial<ModePreferences>

  const visibleColumns = Array.isArray(stored.visibleColumns)
    ? stored.visibleColumns.filter((key) => VALID_COLUMN_KEYS.has(key))
    : [...fallback.visibleColumns]

  // The strike column anchors the layout and cannot be hidden.
  if (!visibleColumns.includes('strike')) {
    visibleColumns.push('strike')
  }

  const columnOrder = Array.isArray(stored.columnOrder)
    ? stored.columnOrder.filter((key) => VALID_COLUMN_KEYS.has(key))
    : []

  const seen = new Set(columnOrder)
  for (const key of fallback.columnOrder) {
    if (!seen.has(key)) {
      columnOrder.push(key)
      seen.add(key)
    }
  }

  return {
    visibleColumns: Array.from(new Set(visibleColumns)),
    columnOrder: Array.from(new Set(columnOrder)),
  }
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

    const parsed = JSON.parse(stored) as Partial<OptionChainPreferences> & {
      // Pre-view-mode shape, where columns lived at the top level
      visibleColumns?: ColumnKey[]
      columnOrder?: ColumnKey[]
    }

    // Migrate the flat pre-view-mode layout into Price mode so an existing
    // user's arrangement survives the upgrade instead of resetting.
    const isLegacy =
      !parsed.modes && (Array.isArray(parsed.visibleColumns) || Array.isArray(parsed.columnOrder))

    const modes: Record<ViewMode, ModePreferences> = {
      price: sanitizeMode(
        isLegacy
          ? { visibleColumns: parsed.visibleColumns, columnOrder: parsed.columnOrder }
          : parsed.modes?.price,
        DEFAULT_MODE_PREFERENCES.price
      ),
      greeks: sanitizeMode(parsed.modes?.greeks, DEFAULT_MODE_PREFERENCES.greeks),
    }

    return {
      viewMode: parsed.viewMode === 'greeks' ? 'greeks' : 'price',
      modes,
      strikeCount:
        typeof parsed.strikeCount === 'number' && parsed.strikeCount > 0
          ? parsed.strikeCount
          : DEFAULT_PREFERENCES.strikeCount,
      selectedUnderlying:
        typeof parsed.selectedUnderlying === 'string' && parsed.selectedUnderlying
          ? parsed.selectedUnderlying
          : DEFAULT_PREFERENCES.selectedUnderlying,
      barDataSource:
        parsed.barDataSource === 'oi' || parsed.barDataSource === 'volume'
          ? parsed.barDataSource
          : DEFAULT_PREFERENCES.barDataSource,
      barStyle:
        parsed.barStyle === 'gradient' || parsed.barStyle === 'solid'
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

  const activeMode = preferences.modes[preferences.viewMode]

  /** Apply an update to the active mode's columns, leaving the other mode alone. */
  const updateActiveMode = useCallback((updater: (mode: ModePreferences) => ModePreferences) => {
    setPreferences((prev) => ({
      ...prev,
      modes: {
        ...prev.modes,
        [prev.viewMode]: updater(prev.modes[prev.viewMode]),
      },
    }))
  }, [])

  const setViewMode = useCallback((mode: ViewMode) => {
    setPreferences((prev) => ({ ...prev, viewMode: mode }))
  }, [])

  const toggleColumn = useCallback(
    (columnKey: ColumnKey | ColumnKey[]) => {
      // Don't allow hiding the strike column
      const keys: ColumnKey[] = (Array.isArray(columnKey) ? columnKey : [columnKey]).filter(
        (key) => key !== 'strike'
      )
      if (keys.length === 0) {
        return
      }

      updateActiveMode((mode) => {
        // Drive every key to the same target rather than flipping each on its
        // own, so a CE/PE pair that has drifted out of sync converges instead
        // of swapping which side is visible.
        const anyVisible = keys.some((key) => mode.visibleColumns.includes(key))
        const remaining = mode.visibleColumns.filter((key) => !keys.includes(key))

        return {
          ...mode,
          visibleColumns: anyVisible ? remaining : [...remaining, ...keys],
        }
      })
    },
    [updateActiveMode]
  )

  const reorderColumns = useCallback(
    (newOrder: ColumnKey[]) => {
      updateActiveMode((mode) => ({ ...mode, columnOrder: newOrder }))
    },
    [updateActiveMode]
  )

  const setStrikeCount = useCallback((count: number) => {
    setPreferences((prev) => ({
      ...prev,
      strikeCount: count,
    }))
  }, [])

  const setSelectedUnderlying = useCallback((underlying: string) => {
    setPreferences((prev) => ({
      ...prev,
      selectedUnderlying: underlying,
    }))
  }, [])

  const setBarDataSource = useCallback((source: BarDataSource) => {
    setPreferences((prev) => ({
      ...prev,
      barDataSource: source,
    }))
  }, [])

  const setBarStyle = useCallback((style: BarStyle) => {
    setPreferences((prev) => ({
      ...prev,
      barStyle: style,
    }))
  }, [])

  /**
   * Reset the active mode's columns. Scoped to columns because this is reached
   * from the column settings menu; the selected underlying, strike count and
   * bar settings are left untouched.
   */
  const resetToDefaults = useCallback(() => {
    setPreferences((prev) => {
      const defaults = DEFAULT_MODE_PREFERENCES[prev.viewMode]
      return {
        ...prev,
        modes: {
          ...prev.modes,
          [prev.viewMode]: {
            visibleColumns: [...defaults.visibleColumns],
            columnOrder: [...defaults.columnOrder],
          },
        },
      }
    })
  }, [])

  const isColumnVisible = useCallback(
    (columnKey: ColumnKey): boolean => {
      return activeMode.visibleColumns.includes(columnKey)
    },
    [activeMode.visibleColumns]
  )

  const getOrderedVisibleColumns = useCallback((): ColumnKey[] => {
    // Return columns in the specified order, filtered to only visible ones
    return activeMode.columnOrder.filter((key) => activeMode.visibleColumns.includes(key))
  }, [activeMode.columnOrder, activeMode.visibleColumns])

  return useMemo(
    () => ({
      preferences,
      viewMode: preferences.viewMode,
      visibleColumns: activeMode.visibleColumns,
      columnOrder: activeMode.columnOrder,
      strikeCount: preferences.strikeCount,
      selectedUnderlying: preferences.selectedUnderlying,
      barDataSource: preferences.barDataSource,
      barStyle: preferences.barStyle,
      setViewMode,
      toggleColumn,
      reorderColumns,
      setStrikeCount,
      setSelectedUnderlying,
      setBarDataSource,
      setBarStyle,
      resetToDefaults,
      isColumnVisible,
      getOrderedVisibleColumns,
    }),
    [
      preferences,
      activeMode,
      setViewMode,
      toggleColumn,
      reorderColumns,
      setStrikeCount,
      setSelectedUnderlying,
      setBarDataSource,
      setBarStyle,
      resetToDefaults,
      isColumnVisible,
      getOrderedVisibleColumns,
    ]
  )
}

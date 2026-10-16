// frontend/src/lib/pnlPalette.ts
/**
 * Colours for the P&L page's canvases (fork-only). A canvas cannot read CSS
 * tokens, so the values are literal. Strategies keep a colour by position in
 * the sorted name list and never cycle; Other and Untagged are neutral.
 */
export const SERIES_COLORS = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
}

export const INK = {
  light: { total: '#0b0b0b', untagged: '#8a8984', other: '#6b6a66', text: '#52514e' },
  dark: { total: '#ffffff', untagged: '#8f8e86', other: '#a9a89f', text: '#c3c2b7' },
}

export const MAX_STRATEGY_SERIES = SERIES_COLORS.light.length

export const REALIZED_COLOR = '#16a34a'
export const UNREALIZED_COLOR = '#d97706'

export function positive(isDark: boolean): string {
  return isDark ? '#22c55e' : '#16a34a'
}

export function negative(isDark: boolean): string {
  return isDark ? '#ef4444' : '#dc2626'
}

/** The colour of a strategy name given the ordered coloured names. */
export function strategyColor(name: string, coloured: string[], isDark: boolean): string {
  const ink = isDark ? INK.dark : INK.light
  if (name === 'Untagged') return ink.untagged
  const index = coloured.indexOf(name)
  if (index < 0) return ink.other
  return (isDark ? SERIES_COLORS.dark : SERIES_COLORS.light)[index] ?? ink.other
}

/** Heat colour for a day's realized P&L (matches Console's calendar). */
export function pnlHeatColor(value: number, maxAbs: number): string {
  if (value === 0) return 'rgba(148, 163, 184, 0.3)'
  const intensity = maxAbs > 0 ? Math.min(Math.abs(value) / maxAbs, 1) : 0
  const alpha = 0.15 + intensity * 0.75
  return value > 0 ? `rgba(34, 197, 94, ${alpha})` : `rgba(239, 68, 68, ${alpha})`
}

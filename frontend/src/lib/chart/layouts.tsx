/**
 * Chart grid layout presets, shared by every page that shows more than one
 * chart at once.
 *
 * Each preset is a CSS grid: `areas` names the cells and `cells` maps each pane,
 * in order, onto a named area. A pane can therefore span, which is what makes
 * the "1 + 2" preset a large chart beside two small ones rather than three
 * equal thirds.
 *
 * These began inside the trading page. They live here because a second page now
 * shows a grid of charts, and two copies of a layout table drift: the presets,
 * their labels and the order they appear in are the thing a user recognises
 * across pages, so there is one definition of them.
 */

import { cn } from '@/lib/utils'

export interface LayoutPreset {
  id: string
  label: string
  cols: string
  rows: string
  areas: string
  cells: string[]
}

export const LAYOUTS: LayoutPreset[] = [
  { id: 'single', label: 'Single', cols: '1fr', rows: '1fr', areas: '"a"', cells: ['a'] },
  {
    id: 'cols2',
    label: '2 columns',
    cols: '1fr 1fr',
    rows: '1fr',
    areas: '"a b"',
    cells: ['a', 'b'],
  },
  {
    id: 'rows2',
    label: '2 rows',
    cols: '1fr',
    rows: '1fr 1fr',
    areas: '"a" "b"',
    cells: ['a', 'b'],
  },
  {
    id: 'oneTwo',
    label: '1 + 2',
    cols: '1.4fr 1fr',
    rows: '1fr 1fr',
    areas: '"a b" "a c"',
    cells: ['a', 'b', 'c'],
  },
  {
    id: 'grid4',
    label: '2 × 2',
    cols: '1fr 1fr',
    rows: '1fr 1fr',
    areas: '"a b" "c d"',
    cells: ['a', 'b', 'c', 'd'],
  },
  {
    id: 'grid6',
    label: '3 × 2',
    cols: '1fr 1fr 1fr',
    rows: '1fr 1fr',
    areas: '"a b c" "d e f"',
    cells: ['a', 'b', 'c', 'd', 'e', 'f'],
  },
  {
    id: 'grid8',
    label: '4 × 2',
    cols: '1fr 1fr 1fr 1fr',
    rows: '1fr 1fr',
    areas: '"a b c d" "e f g h"',
    cells: ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'],
  },
]

/**
 * A preset by id, falling back to the single-pane one.
 *
 * The fallback is not decoration: a stored layout id survives a release that
 * renames or removes a preset, and one chart is always a correct answer.
 */
export function layoutById(id: string | null | undefined): LayoutPreset {
  return LAYOUTS.find((preset) => preset.id === id) ?? LAYOUTS[0]
}

/** Mini glyph previewing a preset, drawn as the actual grid it describes. */
export function LayoutIcon({ preset, className }: { preset: LayoutPreset; className?: string }) {
  return (
    <span
      className={cn('grid h-4 w-4 gap-px', className)}
      style={{
        gridTemplateColumns: preset.cols,
        gridTemplateRows: preset.rows,
        gridTemplateAreas: preset.areas,
      }}
      aria-hidden="true"
    >
      {preset.cells.map((c) => (
        <span key={c} style={{ gridArea: c }} className="rounded-[1px] bg-current" />
      ))}
    </span>
  )
}

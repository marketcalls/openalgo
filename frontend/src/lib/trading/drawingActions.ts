/**
 * What the rail, the properties bar and the right-click menu read off the
 * drawing controller, and the edits they make through it.
 *
 * Every function takes the draw tier as an argument rather than importing it:
 * the tier is fetched the first time a drawing control is used, and anything
 * imported from it here would land in the bundle every trader loads before the
 * first candle. A selection, a level ladder or an armed tool can only exist
 * once the tier is in hand, so by the time any of these runs it is.
 */
import type { Drawing, DrawingController, DrawingPatch, FibLevel } from 'openalgo-charts/draw'
import { DRAW_TOOL_METADATA } from './drawingToolMetadata'

/**
 * The draw tier's helpers these functions use, as the terminal holds them once
 * the tier has loaded. Named one by one rather than as the module, so the
 * bundler still drops the tier's exports nothing here reads.
 */
export type DrawTier = Pick<
  typeof import('openalgo-charts/draw'),
  | 'applyDrawingSettings'
  | 'boundsOf'
  | 'cloneLevels'
  | 'DEFAULT_FIB'
  | 'DRAWING_TOOL_ICONS'
  | 'drawingSettingsSchema'
  | 'formatRatio'
  | 'gannLabel'
  | 'getDrawingTool'
  | 'levelColor'
  | 'readDrawingSetting'
  | 'toolCursor'
>

/**
 * The rail's eraser, carried through the same "armed tool" state as a drawing
 * tool so every pane follows it and Escape ends it. No drawing tool is called
 * this; the terminal turns it into the tier's eraser mode.
 */
export const ERASER_TOOL = 'eraser'

/** The tool's name as the rail lists it, else its id spaced out. */
export function drawingToolName(tool: string): string {
  return (
    DRAW_TOOL_METADATA[tool]?.name ?? tool.replace(/-/g, ' ').replace(/^./, (c) => c.toUpperCase())
  )
}

/**
 * The CSS cursor for the armed tool: the tool's own glyph, haloed so it reads
 * on a light chart and a dark one. Null for no tool, and for an id the tier
 * draws no glyph for, which then keeps the chart's own pointer. Built once per
 * arm, never per pointer move.
 */
export function toolCursorValue(tier: DrawTier, tool: string | null): string | null {
  if (tool === ERASER_TOOL) return 'crosshair'
  if (!tool || !tier.DRAWING_TOOL_ICONS[tool]) return null
  try {
    return tier.toolCursor(tool)
  } catch {
    return null
  }
}

/** Counts the rail and the menus label their rows with. */
export interface DrawingCounts {
  /** What Remove all would take: every drawing the trader may delete. */
  removable: number
  /** What Select all would pick: shown, unlocked and selectable on this interval. */
  selectable: number
}

export function drawingCounts(draw: DrawingController): DrawingCounts {
  const offInterval = new Set(draw.hiddenOnInterval())
  let removable = 0
  let selectable = 0
  for (const d of draw.drawings()) {
    if (d.policy?.editable !== false) removable++
    if (
      d.visible !== false &&
      d.locked !== true &&
      d.policy?.selectable !== false &&
      !offInterval.has(d.id)
    )
      selectable++
  }
  return { removable, selectable }
}

/** The ids Select all picks, in list order. */
export function selectableIds(draw: DrawingController): string[] {
  const offInterval = new Set(draw.hiddenOnInterval())
  return draw
    .drawings()
    .filter(
      (d) =>
        d.visible !== false &&
        d.locked !== true &&
        d.policy?.selectable !== false &&
        !offInterval.has(d.id)
    )
    .map((d) => d.id)
}

/** The selection's place on screen, in chart container pixels. */
export interface DrawSelectionBox {
  left: number
  top: number
  right: number
  bottom: number
}

/** Everything the properties bar shows beyond colour, width and dash. */
export interface DrawSelectionDetails {
  /** The tool's name, or "3 drawings" for a multi-selection. */
  name: string
  /** Fill on, its colour and opacity, or null for a tool that draws no fill. */
  fill: { on: boolean; color: string; opacity: number } | null
  /** Extend left and right, or null for a tool that cannot be extended. */
  extend: { left: boolean; right: boolean } | null
  /** The tool draws a ladder of levels the trader can edit. */
  levels: boolean
  box: DrawSelectionBox | null
}

function toolDefaults(tier: DrawTier, tool: string) {
  try {
    return tier.getDrawingTool(tool).defaultStyle ?? {}
  } catch {
    // A tool the registry no longer knows; the engine's defaults apply.
    return {}
  }
}

/** Read the properties bar's view of the primary selection `d`. */
export function describeSelection(
  draw: DrawingController,
  tier: DrawTier,
  d: Drawing
): DrawSelectionDetails {
  const fields = tier.drawingSettingsSchema(d.tool).fields
  const has = (path: string) => fields.some((field) => field.path === path)
  const defaults = toolDefaults(tier, d.tool)
  const count = draw.selection().length
  const points = draw.screenPoints(d.id)
  const bounds = points && points.length > 0 ? tier.boundsOf(points) : null
  return {
    name: count > 1 ? `${count} drawings` : drawingToolName(d.tool),
    fill: has('style.fill')
      ? {
          on: d.style.fill ?? defaults.fill ?? false,
          color: d.style.fillColor ?? d.style.color ?? defaults.fillColor ?? '#4f8cff',
          opacity: d.style.fillOpacity ?? defaults.fillOpacity ?? 0.12,
        }
      : null,
    extend: has('style.extendLeft')
      ? {
          left: d.style.extendLeft ?? defaults.extendLeft ?? false,
          right: d.style.extendRight ?? defaults.extendRight ?? false,
        }
      : null,
    levels: fields.some((field) => field.kind === 'levels'),
    box: bounds ? { left: bounds.x0, top: bounds.y0, right: bounds.x1, bottom: bounds.y1 } : null,
  }
}

/**
 * Settings written by path (`style.fill`, `style.extendLeft`) to every selected
 * drawing whose tool declares them, as one undo step. A path a drawing's tool
 * does not read is left off that drawing, so turning fill on across a mixed
 * selection fills the rectangle and leaves the trend line alone.
 */
export function settingsPatches(
  draw: DrawingController,
  tier: DrawTier,
  values: Record<string, unknown>
): { id: string; patch: DrawingPatch }[] {
  const patches: { id: string; patch: DrawingPatch }[] = []
  for (const id of draw.selection()) {
    const d = draw.get(id)
    if (!d) continue
    const patch = tier.applyDrawingSettings(d, values, tier.drawingSettingsSchema(d.tool))
    if (Object.keys(patch).length > 0) patches.push({ id, patch: patch as DrawingPatch })
  }
  return patches
}

/** A ladder drawing's levels, as the levels editor shows them. */
export interface DrawLevels {
  levels: FibLevel[]
  /** What Reset restores: the tool's own ladder. */
  defaults: FibLevel[]
  /** The labels switch, or null for a tool that has none. */
  showLabels: boolean | null
  /** What a level prints when it carries no label: 61.8% for a ratio, 1x2 on a Gann fan. */
  label(ratio: number): string
  /** The conventional colour for a ratio, for a level that carries none. */
  color(ratio: number): string
}

function levelsField(tier: DrawTier, tool: string) {
  return tier.drawingSettingsSchema(tool).fields.find((field) => field.kind === 'levels') ?? null
}

/** The primary selection's levels, or null when it is not a ladder tool. */
export function levelsOf(draw: DrawingController, tier: DrawTier): DrawLevels | null {
  const id = draw.selected()
  const d = id ? draw.get(id) : undefined
  const field = d ? levelsField(tier, d.tool) : null
  if (!d || !field) return null
  const own = toolDefaults(tier, d.tool)
  const defaults = own.levels ?? tier.DEFAULT_FIB
  const current = tier.readDrawingSetting(d, field.path)
  const labelled = tier
    .drawingSettingsSchema(d.tool)
    .fields.some((f) => f.path === 'style.showLabels')
  const label =
    d.tool === 'gann-fan'
      ? tier.gannLabel
      : d.tool === 'fib-time-zone'
        ? (ratio: number) => String(ratio)
        : tier.formatRatio
  return {
    levels: tier.cloneLevels(Array.isArray(current) ? (current as FibLevel[]) : defaults),
    defaults: tier.cloneLevels(defaults),
    showLabels: labelled ? (d.style.showLabels ?? own.showLabels === true) : null,
    label,
    color: tier.levelColor,
  }
}

/** The patches that give every selected ladder drawing `levels`, as one undo step. */
export function levelsPatches(
  draw: DrawingController,
  tier: DrawTier,
  levels: readonly FibLevel[]
): { id: string; patch: DrawingPatch }[] {
  const patches: { id: string; patch: DrawingPatch }[] = []
  for (const id of draw.selection()) {
    const d = draw.get(id)
    const field = d ? levelsField(tier, d.tool) : null
    if (!d || !field) continue
    const patch = tier.applyDrawingSettings(d, { [field.path]: tier.cloneLevels(levels) })
    patches.push({ id, patch: patch as DrawingPatch })
  }
  return patches
}

/** The ladder a new level is drawn from: the conventional ratios, in order. */
const FIB_SEQUENCE = [
  0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.272,
  // biome-ignore lint/suspicious/noApproximativeNumericConstant: 1.414 is the ratio traders name, not the square root of two
  1.414,
  1.618, 2, 2.618, 3.618, 4.236,
]

/**
 * The ratio for an added level: the first conventional ratio the ladder does
 * not have, else one past its largest, so Add always adds something new.
 */
export function nextLevelRatio(levels: readonly FibLevel[]): number {
  const has = (ratio: number) => levels.some((level) => Math.abs(level.ratio - ratio) <= 1e-6)
  for (const ratio of FIB_SEQUENCE) if (!has(ratio)) return ratio
  let max = 0
  for (const level of levels) if (Number.isFinite(level.ratio)) max = Math.max(max, level.ratio)
  return max + 1
}

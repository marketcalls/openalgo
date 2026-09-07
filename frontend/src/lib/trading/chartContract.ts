/**
 * The chart agent's wire contract, on the client side.
 *
 * The mirror of `services/agent/chart_contract.py`, and deliberately one file
 * for both directions the way the backend keeps one: outbound is the context
 * the panel reports about the chart, inbound is the command vocabulary the
 * agent sends back, and a change to either has exactly one place to land on
 * each side of the wire.
 *
 * Nothing here touches a chart. It works against {@link AgentDrawingSurface},
 * which is the three methods of `DrawingController` this needs, so the whole
 * translation is testable with a plain object and the terminal supplies the
 * real controller.
 *
 * Two ops, and that is the whole vocabulary:
 *
 * - `{op: "draw", group, shapes}` replaces the named group. Replacing rather
 *   than appending is what makes asking twice redraw instead of stack.
 * - `{op: "clear", group}` removes one group, or every agent group when the
 *   group is null.
 *
 * **An unknown op is ignored, never thrown**, and so is an unknown shape kind
 * and an unusable anchor. A newer backend must not be able to break an older
 * client in the middle of a turn, and half a set of levels drawn is worse than
 * the ones this build understands drawn and the rest skipped.
 *
 * Why the id prefix is the safety property
 * ----------------------------------------
 *
 * Every shape is added under `ai:{group}:{index}`, built here from the
 * command's own group and the shape's position, never from an id the payload
 * carried. A clear then removes only ids under that prefix, and a drawing the
 * operator placed by hand carries a terminal-generated id (`d7`) that can
 * never match it. **Clearing agent markup must not remove the operator's
 * work**, and building the id locally is what makes that true whatever the
 * backend sends.
 *
 * Tone, not colour
 * ----------------
 *
 * A shape carries a semantic tone and the palette lives here, because the
 * backend has no business knowing what bullish looks like. The three colours
 * are the ones the charting library already uses for a rising and a falling
 * candle plus its neutral grey, so agent markup reads correctly against the
 * light theme and the dark one without being redrawn when the operator swaps
 * between them.
 */

import type {
  Drawing,
  DrawingInput,
  DrawingPoint,
  DrawingStyle,
  DrawingText,
} from 'openalgo-charts/draw'
import type { AgentChartCommand } from '@/lib/agent/stream'

// ---------------------------------------------------------------------------
// The namespace
// ---------------------------------------------------------------------------

/** Marks a drawing as the agent's. The terminal's own ids never start with it. */
export const AGENT_DRAWING_PREFIX = 'ai:'

/**
 * A group name this client will accept.
 *
 * Deliberately a shape rather than a list of the four groups that exist today:
 * a group the backend adds later still draws and still clears, and the ban on
 * a colon is what keeps `ai:{group}:{index}` unambiguous to split.
 */
const GROUP_TOKEN = /^[a-z0-9][a-z0-9-]{0,23}$/

/**
 * A guard against a malformed payload, not a statement of the contract.
 *
 * The backend caps a group at 24 shapes. This sits well above that so raising
 * that cap needs no client release, while still refusing to put ten thousand
 * primitives on a canvas because a payload said so.
 */
const MAX_SHAPES_PER_GROUP = 64

/** Build the id one agent shape is drawn under. */
export function agentDrawingId(group: string, index: number): string {
  return `${AGENT_DRAWING_PREFIX}${group}:${index}`
}

/** Whether a drawing belongs to the agent rather than to the operator. */
export function isAgentDrawingId(id: string): boolean {
  return id.startsWith(AGENT_DRAWING_PREFIX)
}

/**
 * The group a drawing belongs to.
 *
 * @param id - A drawing id.
 * @returns The group, or null for an operator drawing or a malformed id.
 */
export function agentGroupOf(id: string): string | null {
  if (!isAgentDrawingId(id)) return null
  const rest = id.slice(AGENT_DRAWING_PREFIX.length)
  const cut = rest.indexOf(':')
  return cut > 0 ? rest.slice(0, cut) : null
}

// ---------------------------------------------------------------------------
// Tone
// ---------------------------------------------------------------------------

/**
 * Semantic tone to canvas colour.
 *
 * The rising and falling colours are the library's own, so a drawn support
 * level is the same green as an up candle. Neutral is the mid grey that reads
 * against both the light background and the dark one.
 */
const TONE_COLOURS: Record<string, string> = {
  bullish: '#26a69a',
  bearish: '#ef5350',
  neutral: '#787b86',
}

function toneColour(tone: unknown): string {
  return TONE_COLOURS[typeof tone === 'string' ? tone : ''] ?? TONE_COLOURS.neutral
}

// ---------------------------------------------------------------------------
// Reading the payload
// ---------------------------------------------------------------------------

/** A finite number, or null. A shape built on a null is dropped, never drawn at zero. */
function num(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return value
}

function text(value: unknown, limit = 80): string {
  return typeof value === 'string' ? value.slice(0, limit) : ''
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

/** One anchor in data space, or null when either half is unusable. */
function point(value: unknown): DrawingPoint | null {
  const source = record(value)
  if (!source) return null
  const time = num(source.time)
  const price = num(source.price)
  return time === null || price === null ? null : { time, price }
}

// ---------------------------------------------------------------------------
// Inbound: shapes to drawings
// ---------------------------------------------------------------------------

/**
 * The part of `DrawingController` this module drives.
 *
 * Declared structurally so the translation can be exercised against a plain
 * object, and so nothing here can reach a method with wider consequences than
 * adding and removing a shape.
 */
export interface AgentDrawingSurface {
  /** Every drawing on the chart, in creation order. */
  drawings(): readonly { id: string }[]
  /** Add a fully specified drawing. The id we pass is the id it keeps. */
  add(drawing: DrawingInput): unknown
  /** Remove one drawing by id. */
  remove(id: string): boolean
}

/** What the terminal has to supply because the contract cannot know it. */
export interface ChartCommandOptions {
  /**
   * Where a level with no time of its own is anchored, in UTC epoch seconds.
   *
   * A full-span horizontal line is drawn across the pane whatever its anchor's
   * time is, but the anchor still has to sit somewhere the chart can map, and
   * only the terminal knows where its bars are. The last bar is the sane
   * choice: a handle at the right edge rather than one at the epoch.
   */
  anchorTime?: number
}

/**
 * A drawing ready for the controller, id included. The controller fills in
 * `zIndex` and `createdAt`, so this is its input shape rather than the stored
 * one.
 */
type AgentDrawing = DrawingInput & { id: string }

/**
 * The label a shape carries. Text lives beside the style, not in it, so a
 * label is only attached when there is one: an empty `text` on a shape reads
 * as a label of nothing rather than no label.
 */
function build(
  id: string,
  tool: string,
  points: DrawingPoint[],
  style: DrawingStyle,
  label?: DrawingText
): AgentDrawing {
  const drawing: AgentDrawing = { id, tool, points, style, paneIndex: 0 }
  if (label && label.value !== '') drawing.text = label
  return drawing
}

/**
 * Translate one shape into a drawing.
 *
 * @param shape - One entry of a draw command's `shapes`.
 * @param id - The namespaced id it will be added under.
 * @param options - What the terminal supplies about its own bars.
 * @returns The drawing, or null when the kind is unknown to this build or an
 *   anchor is unusable. Null is always a skip, never a throw.
 */
function toDrawing(
  shape: Record<string, unknown>,
  id: string,
  options: ChartCommandOptions
): AgentDrawing | null {
  const colour = toneColour(shape.tone)
  const label = text(shape.label)

  switch (shape.kind) {
    case 'level': {
      const price = num(shape.price)
      if (price === null) return null
      // A ray runs right from the bar it was found on; a level with no time of
      // its own spans the pane. Both tools draw the price on the axis, which is
      // the number that matters, so `label` rides along as the drawing's text
      // for a reader of the saved drawing rather than being drawn twice.
      const ray = shape.ray === true
      const time = num(shape.time) ?? options.anchorTime ?? 0
      return build(
        id,
        ray ? 'horizontal-ray' : 'horizontal-line',
        [{ time, price }],
        {
          color: colour,
          lineWidth: 1.5,
          lineStyle: 'dashed',
          showLabels: true,
        },
        { value: label }
      )
    }

    case 'trendline': {
      const from = point(shape.from)
      const to = point(shape.to)
      if (!from || !to) return null
      return build(
        id,
        'trend-line',
        [from, to],
        {
          color: colour,
          lineWidth: 1.5,
          extendRight: shape.extend_right !== false,
        },
        { value: label }
      )
    }

    case 'zone': {
      const from = point(shape.from)
      const to = point(shape.to)
      if (!from || !to) return null
      return build(
        id,
        'rectangle',
        [from, to],
        {
          color: colour,
          lineWidth: 1,
          fill: true,
          fillColor: colour,
          fillOpacity: 0.12,
        },
        { value: label }
      )
    }

    case 'marker': {
      const at = point(shape.at)
      if (!at) return null
      // The price label carries its own text and a leader back to the bar, so
      // one drawing names the pattern where it printed.
      return build(
        id,
        'price-label',
        [at],
        { color: colour, lineWidth: 1 },
        { value: text(shape.text) || label, fontSize: 11 }
      )
    }

    default:
      // An unknown kind is a newer backend talking to an older client. Skip it.
      return null
  }
}

/**
 * Remove agent drawings, and only agent drawings.
 *
 * @param surface - The drawing controller.
 * @param group - The group to remove, or null for every agent group.
 * @returns Whether anything was removed.
 */
function removeAgentDrawings(surface: AgentDrawingSurface, group: string | null): boolean {
  // The ids are collected before the first removal: `drawings()` hands back the
  // controller's live array, and removing while walking it skips entries.
  const doomed = surface
    .drawings()
    .map((drawing) => drawing.id)
    .filter((id) => (group === null ? isAgentDrawingId(id) : agentGroupOf(id) === group))
  for (const id of doomed) surface.remove(id)
  return doomed.length > 0
}

function groupOf(value: unknown): string | null {
  const name = typeof value === 'string' ? value.trim().toLowerCase() : ''
  return GROUP_TOKEN.test(name) ? name : null
}

/**
 * Apply one command.
 *
 * @returns Whether the drawing model changed.
 */
function applyChartCommand(
  surface: AgentDrawingSurface,
  command: AgentChartCommand,
  options: ChartCommandOptions
): boolean {
  switch (command.op) {
    case 'draw': {
      const group = groupOf(command.group)
      if (!group) return false
      const shapes = Array.isArray(command.shapes) ? command.shapes : []
      // The group is replaced, not appended to, so a second call to the same
      // tool redraws rather than stacking. An empty list is a legal way to say
      // "there was nothing to draw", which is what clears the group.
      let changed = removeAgentDrawings(surface, group)
      shapes.slice(0, MAX_SHAPES_PER_GROUP).forEach((raw, index) => {
        const shape = record(raw)
        if (!shape) return
        const drawing = toDrawing(shape, agentDrawingId(group, index), options)
        if (!drawing) return
        surface.add(drawing)
        changed = true
      })
      return changed
    }

    case 'clear': {
      // Null means every agent group. A named group that is not a group name
      // at all removes nothing, rather than falling through to removing all.
      if (command.group === null || command.group === undefined) {
        return removeAgentDrawings(surface, null)
      }
      const group = groupOf(command.group)
      return group ? removeAgentDrawings(surface, group) : false
    }

    default:
      // See the module docstring: an op this build does not know is ignored.
      return false
  }
}

/**
 * Apply a turn's chart commands in order.
 *
 * @param surface - The drawing controller to act on.
 * @param commands - The commands from one `chart_command` frame.
 * @param options - What the terminal supplies about its own bars.
 * @returns Whether anything on the chart changed.
 */
export function applyChartCommands(
  surface: AgentDrawingSurface,
  commands: readonly AgentChartCommand[],
  options: ChartCommandOptions = {}
): boolean {
  let changed = false
  for (const command of commands) {
    if (!command || typeof command.op !== 'string') continue
    if (applyChartCommand(surface, command, options)) changed = true
  }
  return changed
}

// ---------------------------------------------------------------------------
// Inbound: indicators
// ---------------------------------------------------------------------------

/** The chart's indicator tier, narrowed to what one turn can ask of it. */
export interface AgentIndicatorSurface {
  /** Every live instance, in the order the chart holds them. */
  indicators(): readonly { readonly id: string; readonly indicatorId: string }[]
  /** Add one instance of a descriptor. */
  addIndicator(indicatorId: string, settings: Record<string, unknown>): unknown
  /**
   * Take one instance off the chart, by its instance id.
   *
   * This is the chart's own removal, the same one the indicator dialog's
   * Remove uses, and not the instance's `remove()`. The latter clears the
   * series, levels and legend row an indicator created but leaves the instance
   * in `indicators()`, so the chart went blank while the toolbar still counted
   * it, and the duplicate guard below then read that ghost as "already there"
   * and silently refused to add it back. The turn answered "added" and drew
   * nothing, which is worse than refusing.
   */
  removeIndicator(instanceId: string): void
  /**
   * Whether the registry knows this descriptor.
   *
   * The chart's own registry, which includes the operator's modules from
   * `strategies/indicators/`. No list on the server can see those, so a
   * custom indicator has to be addable by a name the backend catalogue has
   * never heard of, and this is what makes that safe.
   */
  hasIndicator(indicatorId: string): boolean
}

/**
 * Add and remove the indicators one turn asked for.
 *
 * Unknown ids are skipped quietly, exactly as an unknown `op` is ignored: a
 * newer backend must not break an older client mid-turn, and throwing would
 * take the rest of the batch with it.
 *
 * @param surface - The chart's indicator tier.
 * @param commands - One turn's commands. Anything that is not an indicator op
 *   is ignored, so the caller may pass the whole batch.
 * @returns Whether the chart changed, which is what the caller persists on.
 */
export function applyIndicatorCommands(
  surface: AgentIndicatorSurface,
  commands: readonly AgentChartCommand[]
): boolean {
  let changed = false
  for (const command of commands) {
    if (!command || command.op !== 'indicator') continue
    const id = text(command.id)
    if (!id || !surface.hasIndicator(id)) continue

    if (command.action === 'remove') {
      // A copy, because removing splices the live array under the walk.
      for (const instance of [...surface.indicators()]) {
        if (instance.indicatorId !== id) continue
        surface.removeIndicator(instance.id)
        changed = true
      }
      continue
    }

    // Asking twice draws two identical lines nobody can tell apart, so a
    // repeat is a no-op rather than a second instance.
    if (surface.indicators().some((instance) => instance.indicatorId === id)) continue
    const settings =
      command.settings && typeof command.settings === 'object'
        ? (command.settings as Record<string, unknown>)
        : {}
    surface.addIndicator(id, settings)
    changed = true
  }
  return changed
}

// ---------------------------------------------------------------------------
// Outbound: the context
// ---------------------------------------------------------------------------

/** Operator drawings reported per turn. Beyond this is a canvas, not a chart. */
const MAX_DRAWINGS = 24

/** Anchors kept per drawing: two covers a line, four covers a channel. */
const MAX_DRAWING_POINTS = 4

/** One of the operator's own drawings, as the backend models it. */
export type ChartContextDrawing = {
  tool: string
  points: DrawingPoint[]
  text?: string
}

/**
 * What the panel reports about the chart, read fresh on every message.
 *
 * A type alias rather than an interface on purpose: the stream hook takes the
 * context as `Record<string, unknown>`, and only an alias carries the implicit
 * index signature that makes it assignable without a cast.
 *
 * The nine scalars are the half that reaches the prompt; the three lists reach
 * only the tools. Field names are the wire's, not the terminal's, so this
 * object is posted as it stands.
 */
export type ChartContext = {
  symbol: string
  exchange: string
  interval: string
  chart_type: string
  bars_loaded: number
  visible_bars: number
  visible_from: number | null
  visible_to: number | null
  last_price: number | null
  indicators: { id: string; name: string }[]
  drawings: ChartContextDrawing[]
  agent_groups: string[]
}

/**
 * Split a chart's drawings into the operator's and the agent's.
 *
 * The agent's own markup is excluded from `drawings` because describing it
 * back to the model as though the operator had drawn it is how an agent ends
 * up analysing its own last answer. What it gets instead is `agentGroups`,
 * which is the honest answer to "is my markup still there": the operator can
 * clear it from the drawing rail with no tool called, so the backend's memory
 * of what it drew is not evidence of what is on screen.
 *
 * @param drawings - Every drawing on the chart.
 * @returns The operator's drawings, capped, and the agent groups still present.
 */
export function describeDrawings(
  drawings: readonly Pick<Drawing, 'id' | 'tool' | 'points' | 'text'>[]
): { drawings: ChartContextDrawing[]; agentGroups: string[] } {
  const mine: ChartContextDrawing[] = []
  const groups = new Set<string>()

  for (const drawing of drawings) {
    const group = agentGroupOf(drawing.id)
    if (group !== null) {
      groups.add(group)
      continue
    }
    if (mine.length >= MAX_DRAWINGS) continue
    const entry: ChartContextDrawing = {
      tool: drawing.tool,
      points: drawing.points.slice(0, MAX_DRAWING_POINTS).map((p) => ({
        time: p.time,
        price: p.price,
      })),
    }
    const note = text(drawing.text?.value)
    if (note) entry.text = note
    mine.push(entry)
  }

  return { drawings: mine, agentGroups: [...groups] }
}

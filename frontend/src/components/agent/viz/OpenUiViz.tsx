/**
 * The general-purpose renderer: bar, line, area and pie charts, tables, metric
 * cards, callouts, tags and collapsible sections, drawn from OpenUI Lang.
 *
 * This is the one visualization tier whose numbers the **model** typed. A
 * `candles` or `plotly` frame is built by a tool from a `services/` call, so
 * its prices cannot be invented; this markup is prose in a different shape.
 * That is why the provenance rule lives in the generated prompt for this tier
 * (`lib/agent/openuiLibrary.ts`) rather than in the plumbing, and why no price
 * tool routes through here.
 *
 * Three things this component exists to get right:
 *
 * - **The whole accumulated string goes in on every frame, never the delta.**
 *   The parser diffs internally and is O(new characters), so re-feeding the
 *   whole answer is cheap and feeding a delta renders one fragment and loses
 *   the rest. `useAgentStream` accumulates it; this only forwards it.
 * - **Partial markup is the normal case, not the error case.** For most of a
 *   turn the string ends mid-statement. `isStreaming` is what tells the parser
 *   to render what has resolved and hold the rest, so a half-written block
 *   never flashes as broken output. Nothing here waits for the markup to look
 *   complete before drawing.
 * - **`--openui-*` stays inside this block.** `ThemeProvider` writes its custom
 *   properties to `body` unless it is given a selector, which would put a
 *   second design system's variables on every page in OpenAlgo. It is mounted
 *   with an explicit selector and the matching class is on the wrapper, so the
 *   variables reach these components and nothing else. Mounted here rather
 *   than once around the whole panel deliberately: the guarantee is identical,
 *   the cost is one small style element per block, and it keeps the scope in
 *   the file that needs it instead of coupling it to a page component.
 *
 * Nothing is passed for animation or palette. `isAnimationActive` already
 * defaults to false on every subset component but `PieChart`, and
 * `useChartPalette` already assigns colours from the palette's midpoint
 * outwards with wraparound. Re-implementing either would produce charts that do
 * not match OpenUI as shipped, and overriding the one exception would single
 * out a pie for treatment its own library does not give it.
 */

import { Renderer } from '@openuidev/react-lang'
import { ThemeProvider } from '@openuidev/react-ui'
import '@openuidev/react-ui/components.css'
import { Component, memo, type ReactNode } from 'react'
import { agentUiLibrary } from '@/lib/agent/openuiLibrary'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'

/**
 * The selector `--openui-*` is written to, and the class that receives it.
 *
 * They have to agree: with an explicit `cssSelector`, `ThemeProvider` injects
 * the rule but does **not** wrap its children, so the class is this
 * component's job.
 */
const OPENUI_SCOPE = 'openalgo-openui-scope'

// ---------------------------------------------------------------------------
// Failure containment
// ---------------------------------------------------------------------------

interface BoundaryProps {
  /** Clearing the caught error whenever this changes is what allows recovery. */
  resetKey: string
  children: ReactNode
}

interface BoundaryState {
  failed: boolean
  /** The `resetKey` the current state belongs to. */
  seen: string
}

/**
 * Keep a render failure inside the block that caused it.
 *
 * An exception thrown while rendering unmounts everything above it, so without
 * this a single malformed statement takes the whole conversation off the
 * screen mid-answer. The error is **not** shown: a red box in the middle of an
 * answer is worse than a missing figure, and the prose beside it still stands.
 *
 * The reset is the part that matters during a stream. Markup is incomplete for
 * most of a turn, so a failure is very often transient: the boundary clears
 * itself the moment the markup grows, and the block draws as soon as the
 * parser can read it.
 */
class OpenUiBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { failed: false, seen: '' }

  static getDerivedStateFromError(): Partial<BoundaryState> {
    return { failed: true }
  }

  static getDerivedStateFromProps(
    props: BoundaryProps,
    state: BoundaryState
  ): Partial<BoundaryState> | null {
    if (props.resetKey === state.seen) return null
    return { failed: false, seen: props.resetKey }
  }

  componentDidCatch(error: unknown) {
    console.error('[agent viz] openui', error)
  }

  render() {
    return this.state.failed ? null : this.props.children
  }
}

// ---------------------------------------------------------------------------
// The component
// ---------------------------------------------------------------------------

export interface OpenUiVizProps {
  /**
   * The **whole** OpenUI Lang markup accumulated for this block so far, not
   * the newest delta. Incomplete for most of a streaming turn, which is the
   * expected input rather than a problem to guard against.
   */
  markup: string
  /**
   * True while the turn is still writing into this block. Passed straight to
   * the renderer, which uses it to hold an unresolved tail back and to keep
   * interactive controls inert until the markup is finished.
   */
  streaming?: boolean
  /** Extra classes on the wrapper, for a host that needs to adjust margins. */
  className?: string
}

/**
 * Render one OpenUI Lang block.
 *
 * @param markup - The whole accumulated markup.
 * @param streaming - Whether the turn is still writing into it.
 * @param className - Extra classes on the wrapper.
 */
export const OpenUiViz = memo(function OpenUiViz({
  markup,
  streaming = false,
  className,
}: OpenUiVizProps) {
  const mode = useThemeStore((state) => state.mode)

  // Nothing at all until there is something to parse. An empty wrapper would
  // otherwise reserve margins in the thread before the first token lands.
  if (!markup.trim()) return null

  return (
    <ThemeProvider mode={mode} cssSelector={`.${OPENUI_SCOPE}`}>
      <div className={cn(OPENUI_SCOPE, 'my-3 min-w-0', className)}>
        <OpenUiBoundary resetKey={markup}>
          <Renderer
            response={markup}
            library={agentUiLibrary}
            isStreaming={streaming}
            // Parser complaints are for an automated correction loop, not for
            // the operator: an unknown component or a missing prop is the
            // model's mistake and it is already visible as a block that did
            // not draw. Swallowing them here is what stops the default
            // handling from surfacing them mid-answer.
            onError={() => undefined}
          />
        </OpenUiBoundary>
      </div>
    </ThemeProvider>
  )
})

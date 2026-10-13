import { useEffect, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { formatBarStamp } from '@/lib/trading/replayClock'
import type { WorkspaceReplaySnapshot } from '@/lib/trading/workspaceReplay'

/** The start bar under the pointer while one is chosen, read without a page render. */
export interface ReplayPickSource {
  subscribe(listener: () => void): () => void
  /** The hovered bar's own time, UTC seconds, or null. */
  time(): number | null
}

const NO_PICK: ReplayPickSource = { subscribe: () => () => {}, time: () => null }

interface Props {
  snapshot: WorkspaceReplaySnapshot
  ownerLabel?: string
  error?: string | null
  onScopeChange(scope: 'focused' | 'all'): void
  onPlay(speed?: number): void
  onPause(): void
  onStep(): void
  onStepBack(): void
  onSeek(index: number): void
  onStop(): void
  confirmExit?: boolean
  onCancelExit?(): void
  onConfirmExit?(): void
  /** The owner chart's start bar while one is chosen. */
  pick?: ReplayPickSource
  /** The owner chart's interval, which decides whether the clock shows a time of day. */
  interval?: string
}

export function WorkspaceReplayBar({
  snapshot,
  ownerLabel = 'the selected chart',
  error,
  onScopeChange,
  onPlay,
  onPause,
  onStep,
  onStepBack,
  onSeek,
  onStop,
  confirmExit = false,
  onCancelExit,
  onConfirmExit,
  pick = NO_PICK,
  interval = '',
}: Props) {
  const [fullscreen, setFullscreen] = useState<Element | null>(null)
  useEffect(() => {
    const update = () => setFullscreen(document.fullscreenElement)
    update()
    document.addEventListener('fullscreenchange', update)
    return () => document.removeEventListener('fullscreenchange', update)
  }, [])
  const { phase, scope, state } = snapshot
  const choosing = phase === 'picking' || phase === 'loading'
  const pickedTime = useSyncExternalStore(pick.subscribe, pick.time, pick.time)
  /**
   * Escape cancels choosing a start bar, the way it puts a drawing tool down.
   * The section says it is open while choosing, so the page's own Escape
   * leaves the side panel alone for this press.
   */
  useEffect(() => {
    if (!choosing) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      const target = event.target as HTMLElement | null
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)))
        return
      event.preventDefault()
      onStop()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [choosing, onStop])
  if (phase === 'idle' && !error) return null
  const focused = state?.members.find((member) => member.id === state.focusedId)?.state
  const clock = formatBarStamp(focused?.bar?.time ?? null, interval)
  const picked = phase === 'picking' ? formatBarStamp(pickedTime, interval) : ''
  const button = 'rounded border border-border px-2 py-1 text-xs hover:bg-accent'
  const content = (
    <section
      className="absolute bottom-3 left-1/2 z-30 w-max max-w-[calc(100%_-_1.5rem)] -translate-x-1/2 rounded-lg border border-border bg-popover p-2 shadow-lg"
      aria-label="Workspace replay"
      data-trading-dialog-open={choosing ? 'true' : undefined}
    >
      {error && (
        <p role="alert" className="mb-1 text-xs text-destructive">
          {error}
        </p>
      )}
      {phase !== 'idle' && (
        <div className="flex flex-wrap items-center justify-center gap-2 text-xs">
          <span className="max-w-full break-words font-medium">Replay: {ownerLabel}</span>
          <select
            aria-label="Replay scope"
            disabled={phase === 'loading'}
            value={scope}
            className="rounded border bg-background px-2 py-1"
            onChange={(event) => onScopeChange(event.target.value as 'focused' | 'all')}
          >
            <option value="focused">Selected chart</option>
            <option value="all">All charts</option>
          </select>
          {(phase === 'picking' || phase === 'loading') && (
            <output>
              {phase === 'loading' ? 'Loading replay history' : `Select a bar on ${ownerLabel}`}
            </output>
          )}
          {picked && (
            <span className="tabular-nums text-muted-foreground" data-replay-picked>
              Start: {picked}
            </span>
          )}
          {phase === 'active' && state && (
            <>
              <button
                type="button"
                className={button}
                aria-label="Previous observation"
                disabled={state.index < 0}
                onClick={onStepBack}
              >
                Prev
              </button>
              <button
                type="button"
                className={button}
                disabled={state.total === 0}
                onClick={() => (state.playing ? onPause() : onPlay())}
              >
                {state.playing ? 'Pause' : 'Play'}
              </button>
              <button
                type="button"
                className={button}
                aria-label="Next observation"
                disabled={state.index >= state.total - 1}
                onClick={onStep}
              >
                Next
              </button>
              <input
                type="range"
                aria-label="Replay position"
                min={-1}
                max={Math.max(-1, state.total - 1)}
                value={state.index}
                disabled={state.total === 0}
                onChange={(event) => onSeek(Number(event.target.value))}
                className="w-28 accent-primary sm:w-40"
              />
              <span className="tabular-nums text-muted-foreground">
                {state.index + 1} / {state.total}
              </span>
              {/* Only while a bar forms over several steps, so a whole-bar
                  replay does not carry a permanent 1/1. */}
              {focused && focused.subSteps > 1 && (
                <span
                  className="tabular-nums text-primary"
                  title="Step of the forming bar"
                  data-replay-substep
                >
                  {focused.subIndex + 1}/{focused.subSteps}
                </span>
              )}
              {/* A simulated step's prices were never traded; a trader testing
                  a stop against them has to know. */}
              {focused?.simulated && (
                <span
                  className="rounded border border-amber-500/50 px-1 text-amber-600 dark:text-amber-400"
                  title="No finer bars for this candle: it forms along a path through its own open, high, low and close, and closes on the real candle"
                >
                  Simulated
                </span>
              )}
              {clock && (
                <span className="tabular-nums font-medium" data-replay-clock>
                  {clock}
                </span>
              )}
              <select
                aria-label="Replay speed"
                value={state.speed}
                onChange={(event) => onPlay(Number(event.target.value))}
                className="rounded border bg-background px-1 py-1"
              >
                {[0.5, 1, 2, 4, 10].map((speed) => (
                  <option key={speed} value={speed}>
                    {speed}x
                  </option>
                ))}
              </select>
            </>
          )}
          <button
            type="button"
            className={button}
            aria-label={phase === 'active' ? 'Stop replay' : 'Cancel replay'}
            onClick={onStop}
          >
            {phase === 'active' ? 'Exit' : 'Cancel'}
          </button>
        </div>
      )}
      <Dialog
        open={confirmExit && phase === 'active'}
        onOpenChange={(open) => {
          if (!open) onCancelExit?.()
        }}
      >
        <DialogContent
          container={fullscreen instanceof HTMLElement ? fullscreen : null}
          className="sm:max-w-sm"
        >
          <DialogTitle>Leave replay?</DialogTitle>
          <DialogDescription>
            The charts return to their live sessions and the playhead is lost.
          </DialogDescription>
          <div className="flex justify-end gap-2">
            <button type="button" className={button} onClick={onCancelExit}>
              Stay
            </button>
            <button type="button" className={button} onClick={onConfirmExit}>
              Leave
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  )
  return fullscreen ? createPortal(content, fullscreen) : content
}

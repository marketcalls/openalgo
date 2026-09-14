/**
 * The replay transport.
 *
 * A strip under the chart rather than a floating panel, because it is modal:
 * while it is on screen the prices above it are not the latest ones, and that
 * has to be impossible to miss.
 */

import { ChevronLeft, ChevronRight, Pause, Play, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { type ChartReplay, REPLAY_SPEEDS } from './useChartReplay'

export function ChartReplayBar({ replay, className }: { replay: ChartReplay; className?: string }) {
  if (replay.mode === 'off') return null

  if (replay.mode === 'picking') {
    return (
      <div
        className={cn(
          'flex h-9 shrink-0 items-center gap-2 border-t bg-card/80 px-3 text-xs',
          className
        )}
      >
        <span className="font-medium text-primary">Pick a starting bar</span>
        <span className="text-muted-foreground">
          Click a candle to begin there. Everything after it is hidden until you step forward.
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto h-7 px-2 text-xs"
          onClick={replay.exit}
        >
          Cancel
        </Button>
      </div>
    )
  }

  const state = replay.state
  const total = state?.total ?? 0
  const index = state?.index ?? 0
  const playing = state?.playing === true

  return (
    <div
      className={cn(
        'flex h-9 shrink-0 items-center gap-2 border-t bg-card/80 px-3 text-xs',
        className
      )}
    >
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        title="Previous bar"
        onClick={replay.stepBack}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        title={playing ? 'Pause' : 'Play'}
        onClick={playing ? replay.pause : replay.play}
      >
        {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        title="Next bar"
        onClick={replay.step}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>

      <input
        type="range"
        min={0}
        max={Math.max(0, total - 1)}
        value={index}
        onChange={(e) => replay.seek(Number(e.target.value))}
        className="mx-1 h-1 min-w-24 flex-1 accent-primary"
        aria-label="Replay position"
      />

      <span className="shrink-0 tabular-nums text-muted-foreground">
        {total > 0 ? `${index + 1} / ${total}` : ''}
      </span>

      <select
        value={replay.speed}
        onChange={(e) => replay.setSpeed(Number(e.target.value))}
        className="h-7 shrink-0 rounded-md border bg-background px-1 text-xs"
        aria-label="Replay speed"
      >
        {REPLAY_SPEEDS.map((value) => (
          <option key={value} value={value}>
            {value}x
          </option>
        ))}
      </select>

      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        title="Exit replay"
        onClick={replay.exit}
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  )
}

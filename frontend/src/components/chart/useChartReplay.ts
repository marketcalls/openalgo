/**
 * Bar replay for a read-only chart.
 *
 * Replay walks the loaded bars forward from a point you choose, so a session
 * can be read the way it happened rather than with its outcome already on
 * screen. It needs no live feed and places no orders, which is what makes it
 * belong on a historical-data page at all.
 *
 * You pick the starting bar yourself and everything after it is shaded while
 * you do, because choosing a start with the next twenty bars visible is
 * choosing with hindsight.
 *
 * The engine owns the mechanics through `ReplayController`; this hook owns the
 * lifecycle a host needs: arming the pick, resolving a click to a bar, and
 * tearing both down so a chart is never left holding a controller or a
 * primitive it no longer uses.
 */

import { ReplayController, ReplayShade, type ReplayState } from 'openalgo-charts'
import type { Widget } from 'openalgo-charts/widget'
import { useCallback, useEffect, useRef, useState } from 'react'

export type ReplayMode = 'off' | 'picking' | 'active'

/** Playback speeds offered, as a multiple of one bar per tick. */
export const REPLAY_SPEEDS = [0.5, 1, 2, 5, 10] as const

export interface ChartReplay {
  mode: ReplayMode
  state: ReplayState | null
  /** Bar the pointer is over while picking, for the hint text. */
  pickIndex: number | null
  speed: number
  /** Arm the pick. The next click on the chart chooses the starting bar. */
  arm(): void
  /** Leave replay, or cancel the pick, restoring the full series. */
  exit(): void
  play(): void
  pause(): void
  step(): void
  stepBack(): void
  seek(index: number): void
  setSpeed(speed: number): void
}

export function useChartReplay(widget: Widget | null): ChartReplay {
  const [mode, setMode] = useState<ReplayMode>('off')
  const [state, setState] = useState<ReplayState | null>(null)
  const [pickIndex, setPickIndex] = useState<number | null>(null)
  const [speed, setSpeedState] = useState(1)

  const controller = useRef<ReplayController | null>(null)
  const shade = useRef<ReplayShade | null>(null)
  const hovered = useRef<number | null>(null)
  /**
   * Read by the crosshair listener.
   *
   * `subscribeCrosshairMove` returns nothing to unsubscribe with, so the
   * listener is registered once for the chart's life and asks this whether it
   * is wanted, rather than being added and removed around the pick.
   */
  const picking = useRef(false)

  /** Drop the controller and the shading, leaving the chart as it was. */
  const teardown = useCallback(() => {
    picking.current = false
    hovered.current = null
    try {
      controller.current?.stop()
    } catch {
      // A chart torn down first leaves nothing to stop.
    }
    controller.current = null
    try {
      shade.current?.setOptions({ index: null })
    } catch {
      // Same.
    }
    setPickIndex(null)
    setState(null)
  }, [])

  /**
   * One shade primitive and one crosshair listener for the life of the chart.
   *
   * `index: null` draws nothing, which is how the shade is kept across
   * entering and leaving the mode rather than attached and detached each time.
   */
  useEffect(() => {
    if (!widget) return
    const primitive = new ReplayShade({ index: null })
    shade.current = primitive
    widget.chart.addPrimitive(primitive)
    widget.chart.subscribeCrosshairMove((event) => {
      if (!picking.current) return
      hovered.current = event.index
      setPickIndex(event.index)
      shade.current?.setOptions({ index: event.index })
    })
    return () => {
      try {
        widget.chart.removePrimitive?.(primitive)
      } catch {
        // The chart may already be gone; the primitive goes with it.
      }
      shade.current = null
    }
  }, [widget])

  useEffect(() => () => teardown(), [teardown])

  /** Replay is about one loaded series, so a new one ends it. */
  useEffect(() => {
    if (!widget) return
    const stop = () => {
      setMode('off')
      teardown()
    }
    const off = [widget.on('symbol', stop), widget.on('interval', stop)]
    return () => {
      for (const unsubscribe of off) unsubscribe()
    }
  }, [widget, teardown])

  const begin = useCallback(
    (startIndex: number) => {
      if (!widget) return
      picking.current = false
      // `bars` is left to default to the primary series' own data, so replay
      // always walks exactly what is drawn.
      controller.current = new ReplayController(widget.chart, {
        series: widget.series,
        startIndex,
        speed,
        onFrame: (next) => setState(next),
      })
      setState(controller.current.state())
      setMode('active')
      shade.current?.setOptions({ index: null })
      setPickIndex(null)
    },
    [widget, speed]
  )

  /** A click without a drag commits the pick; a drag is a pan, not a choice. */
  useEffect(() => {
    if (!widget || mode !== 'picking') return
    picking.current = true

    let pressedAt: { x: number; y: number } | null = null
    const down = (event: PointerEvent) => {
      pressedAt = { x: event.clientX, y: event.clientY }
    }
    const up = (event: PointerEvent) => {
      const from = pressedAt
      pressedAt = null
      if (!from) return
      if (Math.abs(event.clientX - from.x) > 3 || Math.abs(event.clientY - from.y) > 3) return
      const index = hovered.current
      // Index 0 would replay a single bar, which is not a session.
      if (index === null || index < 1) return
      begin(index)
    }

    const root = widget.root
    root.addEventListener('pointerdown', down)
    root.addEventListener('pointerup', up)
    return () => {
      picking.current = false
      root.removeEventListener('pointerdown', down)
      root.removeEventListener('pointerup', up)
    }
  }, [widget, mode, begin])

  const arm = useCallback(() => {
    if (!widget) return
    setPickIndex(null)
    setMode('picking')
  }, [widget])

  const exit = useCallback(() => {
    setMode('off')
    teardown()
  }, [teardown])

  /** Pull the controller's state after a transport call that does not tick. */
  const sync = useCallback(() => setState(controller.current?.state() ?? null), [])

  const play = useCallback(() => {
    controller.current?.play({ speed })
    sync()
  }, [speed, sync])

  const pause = useCallback(() => {
    controller.current?.pause()
    sync()
  }, [sync])

  const step = useCallback(() => {
    controller.current?.step()
    sync()
  }, [sync])

  const stepBack = useCallback(() => {
    controller.current?.stepBack()
    sync()
  }, [sync])

  const seek = useCallback(
    (index: number) => {
      controller.current?.seek(index)
      sync()
    },
    [sync]
  )

  const setSpeed = useCallback(
    (next: number) => {
      setSpeedState(next)
      const current = controller.current
      if (current?.state().playing) current.play({ speed: next })
      sync()
    },
    [sync]
  )

  return {
    mode,
    state,
    pickIndex,
    speed,
    arm,
    exit,
    play,
    pause,
    step,
    stepBack,
    seek,
    setSpeed,
  }
}

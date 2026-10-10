/**
 * The terminal's hover label: a control's name, its keyboard shortcut and one
 * line on what it does.
 *
 * Why not `title`: the browser's box waits about a second, cannot be styled,
 * cannot hold a shortcut beside the name, and on a row of bare glyphs the
 * second it costs is the whole problem. Why one component: the toolbar and both
 * rails say the same kinds of thing, and two label styles side by side read as
 * two products.
 *
 * It wraps one control and adds pointer and focus handlers to it, so the
 * control keeps its own element, ref and accessible name. A `title` already on
 * the control is dropped, or the browser would draw its own box over this one a
 * second later, so a control named only by its title needs an `aria-label`. The label is
 * portalled, so it is never clipped by a scrolling toolbar or rail, and it goes
 * into the full-screen chart when one is open so it still shows there.
 *
 * It shows after a short rest, at once when moving along a row of controls,
 * on keyboard focus, and never on a touch. Pressing the control hides it: once
 * somebody has decided, a label left over the menu they opened reads as part
 * of the menu.
 */
import {
  Children,
  cloneElement,
  type FocusEvent,
  type PointerEvent,
  type ReactElement,
  type ReactNode,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from 'react'
import { createPortal } from 'react-dom'
import { placeTip, type TipSide } from '@/lib/trading/tipPlacement'

export interface TipSpec {
  title: string
  /** The keyboard shortcut, shown after the name. */
  chord?: string
  /** One muted line on what the control does. */
  sub?: string
}

/** How long the pointer rests on a control before its label shows. */
const DWELL_MS = 350
/** Moving on from one label to the next within this shows the next at once. */
const WARM_MS = 500
let lastShown = 0

interface Props {
  tip: TipSpec | null
  side?: TipSide
  /** Hold the label back, for instance while the control's own menu is open. */
  disabled?: boolean
  children: ReactElement
}

type Handlers = {
  onPointerEnter?: (event: PointerEvent<HTMLElement>) => void
  onPointerLeave?: (event: PointerEvent<HTMLElement>) => void
  onPointerDown?: (event: PointerEvent<HTMLElement>) => void
  onFocus?: (event: FocusEvent<HTMLElement>) => void
  onBlur?: (event: FocusEvent<HTMLElement>) => void
  title?: unknown
  'aria-describedby'?: string
}

function focusVisible(target: Element): boolean {
  try {
    return target.matches(':focus-visible')
  } catch {
    return true
  }
}

export function Tip({ tip, side = 'bottom', disabled = false, children }: Props) {
  const id = useId()
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pressed = useRef(false)

  const clear = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }
  const hide = () => {
    clear()
    setAnchor((current) => {
      if (current) lastShown = Date.now()
      return null
    })
  }
  const show = (target: HTMLElement) => {
    if (!tip || disabled) return
    clear()
    const warm = Date.now() - lastShown < WARM_MS
    if (warm) setAnchor(target)
    else timer.current = setTimeout(() => setAnchor(target), DWELL_MS)
  }

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    []
  )
  const withheld = disabled || tip === null
  useEffect(() => {
    if (!withheld) return
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    setAnchor(null)
  }, [withheld])
  // Escape puts a label away, as it does any other surface; a scroll moves the
  // control out from under it.
  useEffect(() => {
    if (!anchor) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAnchor(null)
    }
    const onScroll = () => setAnchor(null)
    window.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onScroll, true)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [anchor])

  const child = Children.only(children) as ReactElement<Handlers>
  const own = child.props
  const control = cloneElement(child, {
    title: undefined,
    'aria-describedby': anchor ? id : own['aria-describedby'],
    onPointerEnter: (event: PointerEvent<HTMLElement>) => {
      own.onPointerEnter?.(event)
      pressed.current = false
      if (event.pointerType !== 'touch') show(event.currentTarget)
    },
    onPointerLeave: (event: PointerEvent<HTMLElement>) => {
      own.onPointerLeave?.(event)
      pressed.current = false
      hide()
    },
    onPointerDown: (event: PointerEvent<HTMLElement>) => {
      own.onPointerDown?.(event)
      pressed.current = true
      hide()
    },
    onFocus: (event: FocusEvent<HTMLElement>) => {
      own.onFocus?.(event)
      if (!pressed.current && focusVisible(event.target)) show(event.currentTarget)
    },
    onBlur: (event: FocusEvent<HTMLElement>) => {
      own.onBlur?.(event)
      hide()
    },
  })

  return (
    <>
      {control}
      {anchor && tip && !disabled && (
        <TipLabel id={id} anchor={anchor} side={side}>
          <span className="font-medium">{tip.title}</span>
          {tip.chord && (
            <span className="ml-2 font-mono text-[11px] text-muted-foreground">{tip.chord}</span>
          )}
          {tip.sub && (
            <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">
              {tip.sub}
            </span>
          )}
        </TipLabel>
      )}
    </>
  )
}

function TipLabel({
  id,
  anchor,
  side,
  children,
}: {
  id: string
  anchor: HTMLElement
  side: TipSide
  children: ReactNode
}) {
  const label = useRef<HTMLDivElement>(null)
  const [at, setAt] = useState<{ left: number; top: number } | null>(null)
  useLayoutEffect(() => {
    const node = label.current
    if (!node) return
    const box = anchor.getBoundingClientRect()
    const place = placeTip(
      { left: box.left, top: box.top, width: box.width, height: box.height },
      { width: node.offsetWidth, height: node.offsetHeight },
      { width: window.innerWidth, height: window.innerHeight },
      side
    )
    setAt({ left: place.left, top: place.top })
  }, [anchor, side])
  const host = (typeof document !== 'undefined' && document.fullscreenElement) || document.body
  return createPortal(
    <div
      ref={label}
      id={id}
      role="tooltip"
      className="pointer-events-none fixed z-[100] max-w-[260px] rounded-md border bg-popover px-2 py-1 text-[12px] leading-snug text-popover-foreground shadow-md"
      style={{ left: at?.left ?? 0, top: at?.top ?? 0, visibility: at ? 'visible' : 'hidden' }}
    >
      {children}
    </div>,
    host
  )
}

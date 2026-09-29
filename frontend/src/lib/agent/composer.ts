/**
 * Putting a sentence into the composer, from anywhere in the thread.
 *
 * This exists for one reason, and the reason is a safety rule rather than a
 * convenience: **a control that starts an order must not be wired to an order
 * tool.** Every order this product places pauses at a human approval gate, and
 * a button that reached the tool directly would be the one path around it. So
 * the Buy and Sell controls on an instrument card do not place anything. They
 * write a plain-language request into the message box and stop, leaving the
 * operator to read it, edit it, and press send. From there it is an ordinary
 * turn: the model decides, the risk guard runs inside the tool body, and the
 * approval gate is where it has always been.
 *
 * A channel rather than a prop, for two reasons:
 *
 * - The control sits four levels below the page that owns the composer
 *   (`AgentChat` to `Message` to `VizBlock` to the card). Threading a callback
 *   through `VizBlock` would put a prop about ordering on the switch that
 *   chooses renderers, and the contract there is that adding a renderer is one
 *   `kind` and one branch.
 * - **A surface that cannot order must show no order controls at all.** The
 *   chart panel mounts the same thread and the same box, and is offered no
 *   order tools whatever, so a Buy there would write a sentence the surface
 *   can only refuse. A composer therefore registers whether its surface can
 *   carry an order, `useComposerPrefill` reports that, and the card leaves the
 *   buttons out instead of rendering two that quietly do nothing.
 *
 * Nothing here sends. The channel carries a string to a textarea; that is its
 * whole capability, and it is deliberately incapable of more.
 */

import { useSyncExternalStore } from 'react'

/** A mounted composer, waiting to be handed text. */
type Target = (text: string) => void

const targets = new Set<Target>()
/**
 * The subset of {@link targets} whose surface can actually run an order.
 *
 * The chart panel mounts a composer too, and it is offered no order tools at
 * all, so "a box exists" stopped being the same question as "pressing Buy
 * leads anywhere". Keeping the two sets apart is what lets one boolean answer
 * the question the card is really asking.
 */
const ordering = new Set<Target>()
const watchers = new Set<() => void>()

function announce() {
  for (const watcher of watchers) watcher()
}

/**
 * Register a composer as the destination for prefilled text.
 *
 * @param target - Called with the request. It owns what happens to text the
 *   operator has already typed; nothing here assumes the box is empty.
 * @param canOrder - Whether a turn sent from this composer can reach an order
 *   tool. False on a surface built without them, such as the chart panel: the
 *   text would arrive, the operator would send it, and the answer would be
 *   that this panel cannot trade.
 * @returns The unsubscribe, for the effect that registered it.
 */
export function subscribeComposerPrefill(target: Target, canOrder = true): () => void {
  targets.add(target)
  if (canOrder) ordering.add(target)
  announce()
  return () => {
    targets.delete(target)
    ordering.delete(target)
    announce()
  }
}

/**
 * Write a request into the composer.
 *
 * @param text - The plain-language request, e.g. `Buy 1 share of RELIANCE on
 *   NSE at market.` It is placed in the box and nothing else happens: no send,
 *   no tool call, no order.
 * @returns Whether a composer was there to receive it.
 */
export function prefillComposer(text: string): boolean {
  // The newest registration wins. Only one composer is ever mounted on a
  // surface, so this only decides an overlap during a remount.
  const target = [...targets].pop()
  if (!target) return false
  target(text)
  return true
}

function subscribeWatcher(watcher: () => void): () => void {
  watchers.add(watcher)
  return () => {
    watchers.delete(watcher)
  }
}

function hasOrderingTarget(): boolean {
  return ordering.size > 0
}

function hasNoTarget(): boolean {
  return false
}

/**
 * Whether a composer is mounted whose surface can carry an order request.
 *
 * @returns True once such a composer has registered. A card asks this before it
 *   offers a Buy or a Sell, so a read-only surface renders neither rather than
 *   two controls that write a sentence nothing can act on.
 */
export function useComposerPrefill(): boolean {
  return useSyncExternalStore(subscribeWatcher, hasOrderingTarget, hasNoTarget)
}

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
 * - **A surface with no composer must show no controls at all.** The chart
 *   panel and any future read-only host mount the thread without one, and
 *   `useComposerPrefill` reports that as a boolean, so the card leaves the
 *   buttons out instead of rendering two that quietly do nothing.
 *
 * Nothing here sends. The channel carries a string to a textarea; that is its
 * whole capability, and it is deliberately incapable of more.
 */

import { useSyncExternalStore } from 'react'

/** A mounted composer, waiting to be handed text. */
type Target = (text: string) => void

const targets = new Set<Target>()
const watchers = new Set<() => void>()

function announce() {
  for (const watcher of watchers) watcher()
}

/**
 * Register a composer as the destination for prefilled text.
 *
 * @param target - Called with the request. It owns what happens to text the
 *   operator has already typed; nothing here assumes the box is empty.
 * @returns The unsubscribe, for the effect that registered it.
 */
export function subscribeComposerPrefill(target: Target): () => void {
  targets.add(target)
  announce()
  return () => {
    targets.delete(target)
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

function hasTarget(): boolean {
  return targets.size > 0
}

function hasNoTarget(): boolean {
  return false
}

/**
 * Whether a composer is mounted and can receive a prefill.
 *
 * @returns True once a composer has registered. A card asks this before it
 *   offers a control that would otherwise do nothing.
 */
export function useComposerPrefill(): boolean {
  return useSyncExternalStore(subscribeWatcher, hasTarget, hasNoTarget)
}

/**
 * Where an agent thread scrolls to when a new turn starts.
 *
 * **On a new question, not on a new token.** Following the tail of a streaming
 * answer drags the text the operator is reading out from under them, and a long
 * answer makes that unusable. So the newest question is pinned near the top of
 * the viewport when it is asked, and the answer fills the space below it as it
 * arrives while the reader's eye stays still.
 *
 * The surface has to leave room for that: a thread whose last answer is one
 * line cannot scroll its question to the top unless there is something under it,
 * which is what the trailing spacer in each thread is for.
 *
 * Lifted out of the chat page so the chart panel behaves identically. It is the
 * same question in both places, and a narrow panel needs the answer more, not
 * less, because there is less of the answer on screen at once.
 */

import { type RefObject, useEffect, useMemo } from 'react'
import type { AgentMessage } from './useAgentStream'

/**
 * How far the newest question sits from the top of the thread, in pixels.
 * Enough that it does not touch the header, small enough that the answer below
 * it gets the viewport.
 */
const PIN_OFFSET_PX = 8

/**
 * Scroll the newest question to the top of its thread as it is asked.
 *
 * @param thread - The scrolling element. It must be positioned, so that every
 *   message's `offsetTop` is already relative to it however many unpositioned
 *   wrappers sit in between.
 * @param messages - The conversation. Only the newest question's identity is
 *   read, so a hundred token flushes into the answer below it move nothing.
 */
export function usePinNewestQuestion(
  thread: RefObject<HTMLElement | null>,
  messages: readonly AgentMessage[]
): void {
  const newestQuestionId = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].role === 'user') return messages[index].id
    }
    return null
  }, [messages])

  useEffect(() => {
    if (!newestQuestionId) return
    const element = thread.current
    if (!element) return
    const question = element.querySelector<HTMLElement>(`[data-message-id="${newestQuestionId}"]`)
    if (!question) return
    const top = Math.max(question.offsetTop - PIN_OFFSET_PX, 0)
    // Not every environment gives an element a scrollTo: jsdom does not, and
    // this runs in a passive effect, where a missing method takes the whole
    // tree down rather than losing an animation. Assigning scrollTop lands in
    // the same place without the easing.
    if (typeof element.scrollTo === 'function') element.scrollTo({ top, behavior: 'smooth' })
    else element.scrollTop = top
  }, [newestQuestionId, thread])
}

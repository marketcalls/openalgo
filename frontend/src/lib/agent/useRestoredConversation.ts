/**
 * Reopen the conversation a surface had open before the page was refreshed.
 *
 * The open thread lives only in `useAgentStream`'s state, so without this a
 * reload dropped the operator onto an empty new chat mid-session. The id is
 * kept in session storage, not local: a refresh reopens the thread, while a new
 * tab or tomorrow's session still starts on a fresh chat.
 *
 * Each surface passes its own key, so the `/agent` page and the chart panel on
 * `/trading` each reopen their own thread.
 */

import { useEffect, useRef } from 'react'
import { getConversation } from '@/api/agent'
import { hydrateMessages } from './hydrate'
import type { AgentMessage } from './useAgentStream'

/**
 * Read the remembered conversation id, if any.
 *
 * Storage can throw outright in a browser configured to block site data, so
 * every access is guarded: forgetting the thread is better than a page that
 * will not render.
 */
function readStored(key: string): number | null {
  try {
    const id = Number(window.sessionStorage.getItem(key))
    return Number.isInteger(id) && id > 0 ? id : null
  } catch {
    return null
  }
}

/** Remember `id` under `key`, or forget it when `id` is null. */
function writeStored(key: string, id: number | null): void {
  try {
    if (id === null) window.sessionStorage.removeItem(key)
    else window.sessionStorage.setItem(key, String(id))
  } catch {
    // Not remembered. A refresh will open a new chat, as it did before.
  }
}

export interface RestoredConversationOptions {
  /** Session-storage key, one per surface, namespaced like every oa- key. */
  storageKey: string
  /** The conversation now open, straight from `useAgentStream`. */
  conversationId: number | null | undefined
  /** The thread now shown, straight from `useAgentStream`. */
  messages: readonly AgentMessage[]
  /** `useAgentStream`'s `setConversation`. */
  setConversation: (id: number | null, next?: AgentMessage[]) => void
}

/**
 * Remember the open conversation and reopen it once on mount.
 *
 * @param options - The surface's key and its `useAgentStream` state.
 */
export function useRestoredConversation({
  storageKey,
  conversationId,
  messages,
  setConversation,
}: RestoredConversationOptions): void {
  const conversationIdRef = useRef<number | null>(null)
  conversationIdRef.current = conversationId ?? null
  const messageCountRef = useRef(0)
  messageCountRef.current = messages.length

  // Read once, before the first render's null id can overwrite it.
  const restoringRef = useRef<number | null | undefined>(undefined)
  if (restoringRef.current === undefined) restoringRef.current = readStored(storageKey)

  useEffect(() => {
    // Hold the stored id while it is still being reopened, or the empty first
    // render would erase the very thread it is about to restore.
    if (conversationId == null && restoringRef.current != null) return
    writeStored(storageKey, conversationId ?? null)
  }, [conversationId, storageKey])

  useEffect(() => {
    const id = restoringRef.current
    if (id == null) return
    let cancelled = false
    getConversation(id)
      .then((detail) => {
        // The operator may have started typing, or opened another thread,
        // while this was loading; their choice wins.
        if (cancelled || conversationIdRef.current !== null || messageCountRef.current > 0) return
        setConversation(id, hydrateMessages(detail.messages))
      })
      .catch(() => {
        // Deleted, or no longer this user's: forget it and stay on a new chat.
        if (!cancelled) writeStored(storageKey, null)
      })
      .finally(() => {
        if (!cancelled) restoringRef.current = null
      })
    return () => {
      cancelled = true
    }
  }, [setConversation, storageKey])
}

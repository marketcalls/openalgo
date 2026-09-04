/**
 * The conversation thread list beside the agent chat.
 *
 * Five decisions here are load bearing, and the obvious implementation of each
 * one is wrong:
 *
 * - **New chat creates nothing.** It resets the local thread and stops. The
 *   stream route opens a conversation when a request names none, so the first
 *   message of a new thread is a single round trip and the row appears with a
 *   title already on it. Pre-creating one here would litter this list with
 *   empty threads every time somebody clicked New chat and changed their mind.
 * - **Leaving a thread abandons the fetch that was opening it.** Every open is
 *   guarded by a token, and New chat and a successful delete both bump it, so a
 *   detail request that resolves after the operator moved on is dropped instead
 *   of replacing the empty thread they just started with the conversation they
 *   just left, or with one that no longer exists.
 * - **Opening a conversation hands its messages up already hydrated.** The
 *   sidebar fetches the detail and converts it with `hydrateMessages`, so the
 *   caller does one thing with the result: `setConversation(id, messages)`.
 *   Usage lives in each row's notices sidecar, so a thread reloaded any other
 *   way loses its token and cost badges and the header total under-reports.
 * - **The list is not the page.** A failed load renders an error inside this
 *   column with a retry, never as a page-level failure: the chat is what the
 *   operator came for and it works perfectly well with no history beside it.
 * - **Nothing that would disturb a running turn is enabled while one runs.**
 *   Switching thread mid-answer discards the answer, so opening, deleting and
 *   New chat are all disabled until the turn ends.
 *
 * The collapsed state is remembered per browser under an `oa-` key, and a
 * viewport too narrow to hold both the list and a readable answer starts
 * collapsed when there is no stored preference.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  Loader2,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  type AgentSurface,
  agentErrorMessage,
  agentQueryKeys,
  type Conversation,
  deleteConversation,
  getConversation,
  type ListConversationsParams,
  listConversations,
} from '@/api/agent'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { hydrateMessages } from '@/lib/agent/hydrate'
import type { AgentMessage } from '@/lib/agent/useAgentStream'
import { cn } from '@/lib/utils'

/** Where the collapsed preference is remembered, namespaced like every oa- key. */
const COLLAPSED_KEY = 'oa-agent-sidebar-collapsed'

/** Below this the list and a readable answer cannot share the viewport. */
const NARROW_VIEWPORT = '(max-width: 767px)'

/** How many placeholder rows the first load shows. */
const SKELETON_ROWS = 5

const MINUTE = 60
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
const WEEK = 7 * DAY

/**
 * Read the remembered collapsed state.
 *
 * Storage can throw outright in a browser configured to block site data, so
 * every access is guarded: a sidebar that will not render because localStorage
 * is off is a worse failure than one that forgets its width.
 *
 * @returns True to start collapsed.
 */
function readCollapsed(): boolean {
  try {
    const stored = window.localStorage.getItem(COLLAPSED_KEY)
    if (stored === '1') return true
    if (stored === '0') return false
  } catch {
    // No stored preference is readable. Fall through to the viewport default.
  }
  try {
    return window.matchMedia(NARROW_VIEWPORT).matches
  } catch {
    return false
  }
}

/**
 * How long ago something happened, in the shortest honest form.
 *
 * @param iso - An explicit-offset UTC timestamp, as every agent route emits.
 * @returns A short relative label, or an empty string for an unreadable value.
 */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return ''
  // Negative when the server clock is a little ahead, which reads as just now.
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < MINUTE) return 'just now'
  if (seconds < HOUR) return `${Math.round(seconds / MINUTE)}m ago`
  if (seconds < DAY) return `${Math.round(seconds / HOUR)}h ago`
  if (seconds < WEEK) return `${Math.round(seconds / DAY)}d ago`
  return new Date(then).toLocaleDateString()
}

/**
 * What to call a conversation in the list.
 *
 * The stream route titles a new conversation from its first message, so a row
 * with no title is one whose first turn never finished writing.
 */
function titleOf(conversation: Conversation): string {
  const title = conversation.title?.trim()
  return title || 'Untitled conversation'
}

/** The full timestamp, for the hover the short label cannot carry. */
function fullStamp(iso: string | null | undefined): string {
  if (!iso) return ''
  const stamp = new Date(iso)
  return Number.isFinite(stamp.getTime()) ? stamp.toLocaleString() : ''
}

export interface ConversationSidebarProps {
  /** The conversation on screen, or null for a thread not yet written to. */
  activeId: number | null
  /** Which surface's conversations to list. Chat by default. */
  surface?: AgentSurface
  /** True while a turn is streaming. Every disturbing action is disabled. */
  busy?: boolean
  /** Clear the thread and start fresh. Must not create a conversation row. */
  onNewChat: () => void
  /** Load a stored conversation, with its messages already hydrated. */
  onSelect: (id: number, messages: AgentMessage[]) => void
  className?: string
}

/**
 * The list of past conversations, newest first.
 *
 * @param props - See {@link ConversationSidebarProps}.
 */
export function ConversationSidebar({
  activeId,
  surface = 'chat',
  busy = false,
  onNewChat,
  onSelect,
  className,
}: ConversationSidebarProps) {
  const queryClient = useQueryClient()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [openingId, setOpeningId] = useState<number | null>(null)
  const [openError, setOpenError] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null)

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0')
    } catch {
      // Remembering the preference is a convenience, not a requirement.
    }
  }, [collapsed])

  const params = useMemo<ListConversationsParams>(() => ({ surface }), [surface])
  const listKey = useMemo(() => agentQueryKeys.conversations(params), [params])

  const {
    data,
    isPending: isLoadingList,
    isFetching,
    isError: listFailed,
    error: listError,
    refetch,
  } = useQuery({
    queryKey: listKey,
    queryFn: () => listConversations(params),
    // The server orders by updated_at descending, so the list arrives newest
    // first and re-sorting here would only be a second opinion about the same
    // column.
    staleTime: 15_000,
  })

  const conversations = data ?? []

  // A finished turn is what renames a new conversation and bumps every row's
  // updated_at, so the list is refreshed on the edge rather than on a timer.
  const wasBusy = useRef(busy)
  useEffect(() => {
    if (wasBusy.current && !busy) {
      void queryClient.invalidateQueries({ queryKey: listKey })
    }
    wasBusy.current = busy
  }, [busy, listKey, queryClient])

  // A click while an earlier fetch is still in flight wins, so the thread never
  // ends up showing the conversation the operator moved on from.
  const openToken = useRef(0)

  const handleOpen = useCallback(
    async (id: number) => {
      if (busy || id === activeId) return
      const token = openToken.current + 1
      openToken.current = token
      setOpeningId(id)
      setOpenError(null)
      try {
        const detail = await getConversation(id)
        if (openToken.current !== token) return
        onSelect(id, hydrateMessages(detail.messages))
      } catch (cause) {
        if (openToken.current !== token) return
        setOpenError(agentErrorMessage(cause, 'Could not open that conversation'))
      } finally {
        if (openToken.current === token) setOpeningId(null)
      }
    },
    [activeId, busy, onSelect]
  )

  // Abandon whatever open is in flight. The fetch checks this token before it
  // hands its messages up, so a conversation the operator has moved on from
  // can no longer arrive late and replace the thread they are looking at.
  const abandonOpen = useCallback(() => {
    openToken.current += 1
    setOpeningId(null)
  }, [])

  // Every route back to an empty thread goes through here, so New chat and a
  // delete of the open conversation cannot differ in what they forget.
  const startFresh = useCallback(() => {
    abandonOpen()
    setOpenError(null)
    onNewChat()
  }, [abandonOpen, onNewChat])

  const remove = useMutation({
    mutationFn: (id: number) => deleteConversation(id),
    onSuccess: (_ack, id) => {
      setPendingDelete(null)
      setDeleteError(null)
      void queryClient.invalidateQueries({ queryKey: listKey })
      // A row deleted while it was opening must not still land: that fetch is
      // carrying the messages of a conversation that no longer exists.
      if (openingId === id) abandonOpen()
      // The thread on screen is the one that just stopped existing, so it goes
      // back to the empty state rather than to a conversation id that 404s on
      // the next message.
      if (id === activeId) startFresh()
    },
    onError: (cause) => {
      setDeleteError(agentErrorMessage(cause, 'Could not delete that conversation'))
    },
  })

  if (collapsed) {
    return (
      <div
        className={cn(
          'flex w-12 shrink-0 flex-col items-center gap-1 border-r border-border py-2.5',
          className
        )}
      >
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={() => setCollapsed(false)}
          aria-label="Show conversations"
          title="Show conversations"
        >
          <PanelLeftOpen className="h-4 w-4" aria-hidden />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={startFresh}
          disabled={busy}
          aria-label="New chat"
          title="New chat"
        >
          <Plus className="h-4 w-4" aria-hidden />
        </Button>
      </div>
    )
  }

  return (
    <aside
      className={cn('flex w-64 shrink-0 flex-col border-r border-border', className)}
      aria-label="Conversations"
    >
      <div className="flex shrink-0 items-center gap-1 px-2 py-2.5">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="min-w-0 flex-1 justify-start"
          onClick={startFresh}
          disabled={busy}
        >
          <Plus className="h-4 w-4" aria-hidden />
          New chat
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={() => setCollapsed(true)}
          aria-label="Hide conversations"
          title="Hide conversations"
        >
          <PanelLeftClose className="h-4 w-4" aria-hidden />
        </Button>
      </div>

      <div className="flex shrink-0 items-center gap-2 px-3 pb-1.5">
        <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          Conversations
        </span>
        {isFetching && !isLoadingList && (
          <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" aria-hidden />
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {isLoadingList ? (
          <div className="space-y-1.5 px-0.5 pt-1">
            {Array.from({ length: SKELETON_ROWS }, (_, index) => (
              <Skeleton key={`row-${index}`} className="h-9 w-full" />
            ))}
          </div>
        ) : listFailed ? (
          // Inline, and only here: the chat below works without this list, so a
          // failed history load must not take the page down with it.
          <div className="space-y-2 rounded-lg border border-destructive/40 bg-destructive/5 p-2.5">
            <p className="flex items-start gap-1.5 text-xs leading-relaxed text-destructive">
              <AlertCircle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
              <span>{agentErrorMessage(listError, 'Could not load your conversations')}</span>
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 w-full text-xs"
              onClick={() => void refetch()}
            >
              Try again
            </Button>
          </div>
        ) : conversations.length === 0 ? (
          <div className="flex flex-col items-center gap-1.5 px-3 py-8 text-center">
            <MessageSquare className="h-6 w-6 text-muted-foreground/50" aria-hidden />
            <p className="text-xs font-medium">No conversations yet</p>
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              Ask the agent something and the thread is saved here.
            </p>
          </div>
        ) : (
          <ul className="space-y-0.5">
            {conversations.map((conversation) => {
              const isActive = conversation.id === activeId
              const isOpening = openingId === conversation.id
              const label = titleOf(conversation)
              return (
                <li
                  key={conversation.id}
                  className={cn(
                    'group relative flex items-center rounded-lg transition-colors',
                    isActive ? 'bg-muted' : 'hover:bg-muted/60'
                  )}
                >
                  {isActive && (
                    <span
                      className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-primary"
                      aria-hidden
                    />
                  )}
                  <button
                    type="button"
                    onClick={() => void handleOpen(conversation.id)}
                    disabled={busy}
                    aria-current={isActive ? 'true' : undefined}
                    title={`${label}\n${fullStamp(conversation.updated_at)}`}
                    className="flex min-w-0 flex-1 flex-col items-start gap-0.5 rounded-lg py-1.5 pr-9 pl-2.5 text-left disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <span
                      className={cn(
                        'w-full truncate text-sm leading-tight',
                        isActive ? 'font-medium text-foreground' : 'text-foreground/90'
                      )}
                    >
                      {label}
                    </span>
                    <span className="text-[11px] leading-none text-muted-foreground">
                      {formatRelative(conversation.updated_at)}
                    </span>
                  </button>
                  <div className="absolute right-1 flex items-center">
                    {isOpening ? (
                      <Loader2
                        className="h-3.5 w-3.5 animate-spin text-muted-foreground"
                        aria-hidden
                      />
                    ) : (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        // Hidden until the row is hovered, but never unreachable
                        // from the keyboard: focus brings it back.
                        className="size-7 text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive focus-visible:opacity-100"
                        onClick={() => {
                          setDeleteError(null)
                          setPendingDelete(conversation)
                        }}
                        disabled={busy}
                        aria-label={`Delete ${label}`}
                        title="Delete this conversation"
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      </Button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {(openError || deleteError) && (
        <p className="shrink-0 border-t border-border px-3 py-2 text-[11px] leading-relaxed text-destructive">
          {openError ?? deleteError}
        </p>
      )}

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete ? `"${titleOf(pendingDelete)}" and every message in it go. ` : null}
              This cannot be undone. Audit rows are kept: they are a trade record and they outlive
              the conversation the trade was typed into.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError && (
            // Inside the dialog, not only under it. This is a modal with a
            // full-screen overlay, so the sidebar's own error line is covered
            // while it is open and a refused delete would read as the Delete
            // button having done nothing at all.
            <p className="flex items-start gap-1.5 text-sm leading-relaxed text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>{deleteError}</span>
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={remove.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(event) => {
                // The dialog closes itself on action; the row is only gone once
                // the server says so, so the close is driven by the mutation.
                event.preventDefault()
                if (pendingDelete) remove.mutate(pendingDelete.id)
              }}
              disabled={remove.isPending}
            >
              {remove.isPending ? 'Deleting' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </aside>
  )
}

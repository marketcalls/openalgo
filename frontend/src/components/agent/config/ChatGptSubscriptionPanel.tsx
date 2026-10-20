/**
 * Connect a ChatGPT Plus or Pro plan, so the agent can run on it.
 *
 * LiteLLM exposes the subscription as its own provider, `chatgpt`, separate
 * from `openai`. The same ten models, a different bill:
 *
 * ```
 * openai/gpt-5.4     an API key you paste  -> OpenAI API credits
 * chatgpt/gpt-5.4    an OAuth sign-in      -> your Plus or Pro plan
 * ```
 *
 * So there is no key field on this panel, and there never can be: the
 * credential is a refresh token issued by a device-code sign-in. The operator
 * presses Connect, reads a short code, types it at OpenAI's own page, and this
 * panel notices when it is approved. What they see afterwards is what an API
 * key row shows them, a fingerprint. **A token is never rendered here**, not
 * masked and not partial, and no type in this file has a field for one.
 *
 * Four states, and each one has a different next action:
 *
 * | state | what the operator sees |
 * | --- | --- |
 * | disconnected | what a plan buys them, and one Connect |
 * | connecting | the code, the link, the deadline, and Cancel |
 * | connected | the fingerprint, the account, the expiry, and Disconnect |
 * | failed or expired | what went wrong, and one retry |
 *
 * Three things about it are not obvious:
 *
 * - **The deadline is shown because it is real.** A device code is accepted for
 *   about fifteen minutes and then stops working. A panel that showed the code
 *   without the clock would leave an operator retyping a dead code and
 *   concluding the feature is broken.
 * - **The poll runs only while a sign-in is pending.** `start_login` answers in
 *   milliseconds and the wait happens on a real OS thread server side, so this
 *   screen polls a cheap status route rather than holding a request open for a
 *   quarter of an hour. It stops the moment the state is anything but pending.
 * - **Disconnect leaves the registered models alone.** A `chatgpt/` row is
 *   operator intent; this call only revokes the credential behind it. Deleting
 *   the row on their behalf would throw away a configuration they may want back
 *   the moment they sign in again, so the confirmation says so instead.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ExternalLink, Loader2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  agentErrorMessage,
  agentQueryKeys,
  cancelChatGptLogin,
  type ChatGptLogin,
  type ChatGptStatus,
  getChatGptStatus,
  removeChatGptSession,
  startChatGptLogin,
} from '@/api/agent'
import { Alert, AlertDescription } from '@/components/ui/alert'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

/** How often the status route is re-read while a sign-in is waiting. */
const POLL_MS = 2000

/** How often the deadline on screen is recomputed while one is showing. */
const TICK_MS = 1000

/** How long the copy control shows its confirmation, in milliseconds. */
const COPIED_MS = 1500

/**
 * Every state this panel can be in, and it is in exactly one of them.
 *
 * Derived rather than stored, so the screen cannot disagree with the server:
 * there is one source of truth, `GET /agent/api/chatgpt/status`, and this is a
 * pure reading of it. Exported because the state machine is the part worth
 * pinning in a test, separately from how any of it is drawn.
 */
export type ChatGptPanelState =
  | 'loading'
  | 'unavailable'
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'failed'
  | 'expired'

export interface ChatGptPanelInput {
  status: ChatGptStatus | undefined
  isError: boolean
}

/**
 * Which state the panel is in.
 *
 * The order of the tests is the whole design:
 *
 * 1. **A pending sign-in wins over everything**, including an existing
 *    authorisation. An operator moving this instance to a different ChatGPT
 *    account is still connected to the old one while they do it, and the code
 *    on screen is the only thing they can act on.
 * 2. **Then authorisation**, because a plan that works is the answer to the
 *    question the panel exists to ask, whatever a previous sign-in ended as.
 * 3. **Then the terminal failure states**, which are the only remaining reason
 *    to say more than "not connected".
 *
 * @param input - The status query's data and whether it failed outright.
 * @returns The single state to render.
 */
export function chatGptPanelState({ status, isError }: ChatGptPanelInput): ChatGptPanelState {
  if (!status) return isError ? 'unavailable' : 'loading'
  if (status.login.state === 'pending') return 'connecting'
  if (status.authorised) return 'connected'
  if (status.login.state === 'failed') return 'failed'
  if (status.login.state === 'expired') return 'expired'
  return 'disconnected'
}

/**
 * How long a pending device code has left, in whole seconds.
 *
 * @param login - The login snapshot.
 * @param now - Milliseconds since the epoch, passed in so the caller owns the
 *   clock and a test does not have to fake a global one.
 * @returns Seconds remaining, floored at zero, or null when the snapshot names
 *   no deadline. Null renders as nothing rather than as "expires in 0:00",
 *   which would be a countdown to a moment nobody promised.
 */
export function secondsRemaining(login: ChatGptLogin, now: number): number | null {
  if (typeof login.expires_at !== 'number' || !Number.isFinite(login.expires_at)) return null
  return Math.max(0, Math.round((login.expires_at * 1000 - now) / 1000))
}

/**
 * A countdown as minutes and seconds.
 *
 * @param seconds - Whole seconds remaining.
 * @returns `m:ss`.
 */
function formatCountdown(seconds: number): string {
  const whole = Math.floor(seconds)
  const minutes = Math.floor(whole / 60)
  return `${minutes}:${String(whole % 60).padStart(2, '0')}`
}

/**
 * A unix timestamp as something an operator can read.
 *
 * @param unixSeconds - Seconds since the epoch, or null.
 * @returns A local date and time, or an empty string when there is none.
 */
function formatMoment(unixSeconds: number | null): string {
  if (typeof unixSeconds !== 'number' || !Number.isFinite(unixSeconds)) return ''
  const at = new Date(unixSeconds * 1000)
  return Number.isFinite(at.getTime()) ? at.toLocaleString() : ''
}

/**
 * Put text on the clipboard, with a fallback for an insecure origin.
 *
 * `navigator.clipboard` is undefined on plain http, which a self-hosted
 * OpenAlgo reached over a LAN address is, so the textarea path is not legacy
 * support: it is the path most installs actually take. The same helper the
 * message actions use, kept local because the eight characters it moves here
 * are a device code and nothing else in this file should reach a clipboard.
 *
 * @param text - What to copy.
 * @returns Whether it landed.
 */
async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Fall through. A permissions policy can reject it even on https.
    }
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    document.body.removeChild(area)
  }
}

export function ChatGptSubscriptionPanel() {
  const queryClient = useQueryClient()
  const [actionError, setActionError] = useState<string | null>(null)
  const [confirmingDisconnect, setConfirmingDisconnect] = useState(false)
  const [copied, setCopied] = useState(false)
  const [now, setNow] = useState(() => Date.now())

  const query = useQuery({
    queryKey: agentQueryKeys.chatgpt(),
    queryFn: getChatGptStatus,
    // A 404 while the route is still being written is a permanent answer, not a
    // flaky one, so retrying it four times only delays the message.
    retry: false,
    staleTime: 15_000,
    // Only while a code is outstanding. Everything else here changes because
    // the operator pressed something, which refreshes the cache itself.
    refetchInterval: (entry) => (entry.state.data?.login.state === 'pending' ? POLL_MS : false),
    // **In the background too, and that is the whole point.** The panel tells
    // the operator to open OpenAI's page in another tab, so this one is hidden
    // for the entire wait, and a poll that pauses on a hidden tab is a poll
    // that never runs during the only period it is needed. Found in a browser:
    // with this left at its default the code sat there approved and the panel
    // went on counting down until the tab was focused again.
    refetchIntervalInBackground: true,
  })

  const status = query.data
  const state = chatGptPanelState({ status, isError: query.isError })
  const connecting = state === 'connecting'
  // Stable across renders, unlike the query object it came off, so the callback
  // below is not rebuilt on every tick of the countdown.
  const { refetch } = query

  // The clock ticks only while there is a deadline on screen. An interval that
  // ran on a connected panel would re-render it once a second forever for
  // nothing.
  useEffect(() => {
    if (!connecting) return
    const timer = window.setInterval(() => setNow(Date.now()), TICK_MS)
    return () => window.clearInterval(timer)
  }, [connecting])

  // The confirmation is a moment, not a state. Left latched the button reads
  // "Copied" for the rest of the sign-in, so a second copy after a failed paste
  // gives no feedback at all.
  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), COPIED_MS)
    return () => window.clearTimeout(timer)
  }, [copied])

  /** Write a fresh login snapshot into the cached status, keeping the rest. */
  const applyLogin = useCallback(
    (login: ChatGptLogin): void => {
      queryClient.setQueryData<ChatGptStatus>(agentQueryKeys.chatgpt(), (previous) =>
        previous ? { ...previous, login } : previous
      )
      // The snapshot says what the sign-in is doing; only the status route says
      // whether the plan is authorised, so a terminal state is confirmed rather
      // than assumed.
      if (login.state !== 'pending') void refetch()
    },
    [queryClient, refetch]
  )

  const connect = useMutation({
    mutationFn: (force: boolean) => startChatGptLogin(force),
    onMutate: () => {
      setActionError(null)
      setCopied(false)
      setNow(Date.now())
    },
    onSuccess: applyLogin,
    onError: (error) => {
      setActionError(agentErrorMessage(error, 'The sign-in could not be started.'))
    },
  })

  const cancel = useMutation({
    mutationFn: () => cancelChatGptLogin(),
    onSuccess: (result) => {
      setActionError(null)
      applyLogin(result.data)
    },
    onError: (error) => {
      setActionError(agentErrorMessage(error, 'The sign-in could not be cancelled.'))
    },
  })

  const disconnect = useMutation({
    mutationFn: () => removeChatGptSession(),
    onSuccess: () => {
      setActionError(null)
      void queryClient.invalidateQueries({ queryKey: agentQueryKeys.chatgpt() })
      // A plan model that can no longer run changes what the picker should say
      // about the rows that depend on it.
      void queryClient.invalidateQueries({ queryKey: agentQueryKeys.models() })
      void queryClient.invalidateQueries({ queryKey: agentQueryKeys.status() })
    },
    onError: (error) => {
      setActionError(agentErrorMessage(error, 'The plan could not be disconnected.'))
    },
  })

  const login = status?.login
  const remaining = login ? secondsRemaining(login, now) : null
  const busy = connect.isPending || cancel.isPending || disconnect.isPending

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          ChatGPT subscription
          {state === 'connected' ? <Badge variant="secondary">Connected</Badge> : null}
        </CardTitle>
        <CardDescription>
          A ChatGPT Plus or Pro plan is a second billing path, not a second key. A model registered
          under <span className="font-mono">chatgpt/</span> runs on your plan; the same model under{' '}
          <span className="font-mono">openai/</span> spends API credits. Sign in once here and the{' '}
          <span className="font-mono">chatgpt/</span> models become available in the catalog below.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {state === 'loading' ? (
          <div className="space-y-2" aria-busy="true">
            <span className="sr-only">Checking whether a ChatGPT plan is connected</span>
            <Skeleton className="h-4 w-64" />
            <Skeleton className="h-9 w-40" />
          </div>
        ) : null}

        {state === 'unavailable' ? (
          <Alert variant="warning">
            <AlertCircle className="h-4 w-4" aria-hidden />
            <AlertDescription className="space-y-2">
              <p>
                This server cannot answer for a ChatGPT plan yet.{' '}
                {agentErrorMessage(query.error, 'The status request failed.')}
              </p>
              <p>
                The subscription needs a LiteLLM new enough to carry its ChatGPT provider.
                Everything else on this page still works, and a model with an API key is unaffected.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  void refetch()
                }}
              >
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        {state === 'disconnected' ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              No plan is connected, so the <span className="font-mono">chatgpt/</span> models cannot
              run. Connecting opens OpenAI's own sign-in page and stores nothing but the credential
              it hands back, encrypted in this instance's database.
            </p>
            <Button type="button" disabled={busy} onClick={() => connect.mutate(false)}>
              {connect.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              Connect ChatGPT plan
            </Button>
          </div>
        ) : null}

        {state === 'failed' || state === 'expired' ? (
          <div className="space-y-3">
            <Alert variant={state === 'expired' ? 'warning' : 'destructive'}>
              <AlertCircle className="h-4 w-4" aria-hidden />
              <AlertDescription>
                {state === 'expired'
                  ? 'The code was not entered in time, so it stopped being accepted. Nothing is broken: start again and a new code is issued.'
                  : login?.message?.trim() || 'The sign-in did not complete.'}
              </AlertDescription>
            </Alert>
            <Button type="button" disabled={busy} onClick={() => connect.mutate(false)}>
              {connect.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              Try connecting again
            </Button>
          </div>
        ) : null}

        {connecting && login ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-border bg-muted/40 p-4">
              <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                Your code
              </p>
              <p className="mt-2 font-mono text-3xl leading-tight font-semibold break-all select-all">
                {login.user_code || 'waiting'}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={!login.user_code}
                  onClick={() => {
                    void copyText(login.user_code).then((ok) => setCopied(ok))
                  }}
                >
                  {copied ? 'Copied' : 'Copy code'}
                </Button>
                {login.verification_url ? (
                  <Button asChild size="sm">
                    <a href={login.verification_url} target="_blank" rel="noreferrer noopener">
                      Open the sign-in page
                      <ExternalLink className="h-4 w-4" aria-hidden />
                    </a>
                  </Button>
                ) : null}
                {remaining === null ? null : (
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {remaining > 0
                      ? `Expires in ${formatCountdown(remaining)}`
                      : 'This code has expired. Cancel and start again.'}
                  </span>
                )}
              </div>
            </div>

            <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
              <li>Open the sign-in page. It opens in a new tab, on OpenAI's own site.</li>
              <li>Sign in with the account your ChatGPT plan belongs to.</li>
              <li>Enter the code above when it asks for one.</li>
              <li>Come back here. This panel notices on its own within a couple of seconds.</li>
            </ol>

            <p className="text-xs text-muted-foreground">
              A code is good for about fifteen minutes. Nobody but you should ever be asked for it:
              if anything else asks you to enter this code, cancel instead.
            </p>

            <Button type="button" variant="outline" disabled={busy} onClick={() => cancel.mutate()}>
              {cancel.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              Cancel sign-in
            </Button>
          </div>
        ) : null}

        {state === 'connected' && status ? (
          <div className="space-y-4">
            <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
              <div className="min-w-0">
                <dt className="text-xs text-muted-foreground">Credential</dt>
                <dd className="truncate font-mono text-xs" title={status.fingerprint}>
                  {status.fingerprint}
                </dd>
              </div>
              {status.account_id ? (
                <div className="min-w-0">
                  <dt className="text-xs text-muted-foreground">Account</dt>
                  <dd className="truncate font-mono text-xs" title={status.account_id}>
                    {status.account_id}
                  </dd>
                </div>
              ) : null}
              {status.expiry === null ? null : (
                <div className="min-w-0">
                  <dt className="text-xs text-muted-foreground">Access token expires</dt>
                  <dd className="text-xs">
                    {formatMoment(status.expiry)}. It is refreshed on its own.
                  </dd>
                </div>
              )}
              <div className="min-w-0">
                <dt className="text-xs text-muted-foreground">Stored</dt>
                {/* The path is its own element with `break-all`, and that is not
                    cosmetic: a Windows path is one unbroken token, so left in
                    the sentence it sets the column's min-content width and the
                    whole grid overhangs the card on a narrow screen. Measured
                    at a 310px card: the row ran 59px past its own border. */}
                <dd className="text-xs">
                  {status.stored_in_database
                    ? 'Encrypted in this instance database, and cached for LiteLLM in '
                    : 'On disk only, in '}
                  <span className="font-mono break-all">{status.token_dir}</span>
                </dd>
              </div>
            </dl>

            <p className="text-sm text-muted-foreground">
              Turns on a <span className="font-mono">chatgpt/</span> model are covered by this plan
              and carry no per-token price. The same model under{' '}
              <span className="font-mono">openai/</span> still bills your API credits.
            </p>

            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => connect.mutate(true)}
              >
                {connect.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                Sign in again
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={busy}
                onClick={() => setConfirmingDisconnect(true)}
              >
                Disconnect
              </Button>
            </div>
          </div>
        ) : null}

        {actionError ? (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" aria-hidden />
            <AlertDescription>{actionError}</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>

      <AlertDialog
        open={confirmingDisconnect}
        onOpenChange={(open) => !open && setConfirmingDisconnect(false)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Disconnect the ChatGPT plan</AlertDialogTitle>
            <AlertDialogDescription>
              The stored credential is deleted and cannot be read back, so reconnecting means
              signing in again. Any model you registered under chatgpt/ stays in the registry and
              stops working until then, which is why they are not removed for you.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it connected</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setConfirmingDisconnect(false)
                disconnect.mutate()
              }}
            >
              Disconnect
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

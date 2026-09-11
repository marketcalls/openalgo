/**
 * Voice configuration.
 *
 * The spoken surface is a third surface on the existing agent, so almost
 * nothing here is about intelligence: the speech model hears and speaks, and
 * every answer it reads out was produced by the same agent, the same toolkits
 * and the same risk guard a typed turn goes through. What this screen sets is
 * the credential, the delivery, and the two questions that have consequences.
 *
 * Three things this panel has to make obvious, because none is guessable and
 * each one is a way an operator ends up surprised:
 *
 * - **The name and the approval word are different values on purpose.** The
 *   name is what a trader says all day and carries no authority. The approval
 *   word does one thing, and the server refuses a word that also appears in the
 *   name so the two cannot be collapsed back into one by configuration. That
 *   rule is stated next to the fields and checked here as the operator types,
 *   because meeting it for the first time as a 400 teaches nothing.
 * - **Voice trading is subordinate, not parallel.** `voice_trading_enabled` is
 *   an `and`, never an `or`: with the agent's own trading switch off, turning
 *   this on changes nothing at all. The panel renders it as a nested control
 *   and says so when the master is off, rather than showing a switch that
 *   appears to work and does not.
 * - **What spoken approval actually means.** Anyone within earshot who says the
 *   word while a window is open places the staged order. That is written in
 *   plain words rather than softened, and without an alarming icon, because the
 *   operator is the one who decides whether their room is a room where that is
 *   acceptable.
 *
 * Two rules from the module contract are enforced here rather than assumed, the
 * same way WebSearchPanel enforces them: **a key value is never rendered**, not
 * masked and not partial, so the field starts empty even when a key is stored;
 * and **the server owns validation**, so an unusable name, word or window is
 * refused with the server's own message rather than corrected locally.
 *
 * The two switches apply on toggle and the typed fields wait for Save. That
 * split is deliberate: a switch has no intermediate state worth staging, and
 * the trading switch in particular is the one control an operator may want to
 * flip in a hurry, while a half-typed approval word saved on every keystroke
 * would be a different approval word on every keystroke.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Loader2 } from 'lucide-react'
import { useId, useState } from 'react'
import {
  agentErrorMessage,
  agentQueryKeys,
  clearVoiceKey,
  getVoiceConfig,
  setVoiceKey,
  testVoice,
  updateVoiceConfig,
  type VoiceConfig,
  type VoiceConfigResponse,
  type VoiceConfigUpdate,
  type VoiceTestResult,
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

/** The bounds `voice_confirm_window_seconds` is stored under, as input hints. */
const MIN_CONFIRM_WINDOW = 5
const MAX_CONFIRM_WINDOW = 300

/** What the approval word and the name are allowed to be, as input hints. */
const MAX_NAME_CHARS = 40
const MIN_PHRASE_CHARS = 3
const MAX_PHRASE_CHARS = 20

/** The typed half of the configuration, held as text while it is edited. */
interface Draft {
  model: string
  speaker: string
  agentName: string
  orderPhrase: string
  confirmWindow: string
}

function toDraft(config: VoiceConfig): Draft {
  return {
    model: config.voice_model,
    speaker: config.voice_speaker,
    agentName: config.voice_agent_name,
    orderPhrase: config.voice_order_phrase,
    confirmWindow: String(config.voice_confirm_window_seconds),
  }
}

function sameDraft(a: Draft, b: Draft): boolean {
  return (
    a.model === b.model &&
    a.speaker === b.speaker &&
    a.agentName === b.agentName &&
    a.orderPhrase === b.orderPhrase &&
    a.confirmWindow === b.confirmWindow
  )
}

/**
 * A whole number, or null when the text is not one.
 *
 * The only local validation on the window, and for the same reason WebSearch
 * has it: the payload is typed as a number, so a value that is not one cannot
 * travel to the server to collect the server's own message. The range itself is
 * the server's to refuse.
 */
function parseWhole(raw: string): number | null {
  const text = raw.trim()
  if (!/^\d+$/.test(text)) return null
  const value = Number(text)
  return Number.isSafeInteger(value) ? value : null
}

/**
 * Whether the approval word is also one of the words in the name.
 *
 * This is the one relationship the server enforces across two fields, so it is
 * the one worth checking locally: the operator typing a name is the moment the
 * conflict is created, and a rejected save several fields later reads as the
 * form being broken rather than as these two values disagreeing. Everything
 * that is not a letter is a separator here exactly as the matcher treats it, so
 * "Milo" in "Hey Milo" is caught and "Milos" is not.
 */
function wordAppearsInName(phrase: string, name: string): boolean {
  const word = phrase.trim().toLowerCase()
  if (!word) return false
  return name
    .toLowerCase()
    .split(/[^a-z]+/)
    .filter(Boolean)
    .includes(word)
}

/**
 * A naive UTC timestamp rendered in the reader's own timezone.
 *
 * The server sends `2026-09-02T10:11:12` with no offset, which `Date` reads as
 * local time, so a key used an hour ago would otherwise be reported five and a
 * half hours in the future.
 */
function formatUtc(value: string | null): string {
  if (!value) return 'never'
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`
  const parsed = new Date(normalized)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

/** A test outcome, whether the vendor answered it or the request itself failed. */
interface TestOutcome {
  ok: boolean
  message: string
  latencyMs: number
  model: string
}

export function VoicePanel() {
  const queryClient = useQueryClient()
  const fieldId = useId()

  const query = useQuery({
    queryKey: agentQueryKeys.voice(),
    queryFn: getVoiceConfig,
    staleTime: 30_000,
  })

  const config = query.data?.data ?? null
  const defaults = query.data?.defaults ?? null

  // Null means "whatever the server last said". Clearing it after a save is
  // what re-derives the form from the refreshed response, so no effect has to
  // watch the query and no stale draft can survive a successful write.
  const [draft, setDraft] = useState<Draft | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [keyDraft, setKeyDraft] = useState('')
  const [test, setTest] = useState<TestOutcome | null>(null)
  const [clearingKey, setClearingKey] = useState(false)

  const form = draft ?? (config ? toDraft(config) : null)
  const dirty = form !== null && config !== null && !sameDraft(form, toDraft(config))
  const conflict = form !== null && wordAppearsInName(form.orderPhrase, form.agentName)

  /**
   * Every mutation answers with the whole refreshed configuration, so the cache
   * is written from the response rather than invalidated. One round trip, and
   * no window in which the screen shows the value that was just replaced.
   */
  const applyConfig = (next: VoiceConfig): void => {
    queryClient.setQueryData<VoiceConfigResponse>(agentQueryKeys.voice(), (prev) =>
      prev ? { ...prev, data: next } : prev
    )
  }

  // A switch, applied on toggle. Kept separate from the form save so a toggle
  // never discards what somebody is part way through typing.
  const saveSwitch = useMutation({
    mutationFn: (values: VoiceConfigUpdate) => updateVoiceConfig(values),
    onSuccess: (next) => {
      applyConfig(next)
      setFormError(null)
    },
    onError: (error) => {
      setFormError(agentErrorMessage(error, 'Could not change the voice setting.'))
    },
  })

  const saveSettings = useMutation({
    mutationFn: (values: VoiceConfigUpdate) => updateVoiceConfig(values),
    onSuccess: (next) => {
      applyConfig(next)
      setDraft(null)
      setFormError(null)
      showToast.success('Voice settings saved')
    },
    onError: (error) => {
      setFormError(agentErrorMessage(error, 'Could not save the voice settings.'))
    },
  })

  const saveKey = useMutation({
    mutationFn: (apiKey: string) => setVoiceKey(apiKey),
    onSuccess: (next) => {
      applyConfig(next)
      // Cleared on the way out, not held for a retry: the field is write only
      // and a key sitting in component state is a key on the screen.
      setKeyDraft('')
      setTest(null)
      showToast.success('Key saved')
    },
    onError: (error) => {
      showToast.error(agentErrorMessage(error, 'Could not save the key.'))
    },
  })

  const removeKey = useMutation({
    mutationFn: () => clearVoiceKey(),
    onSuccess: (next) => {
      applyConfig(next)
      setTest(null)
      showToast.success('Key removed')
    },
    onError: (error) => {
      showToast.error(agentErrorMessage(error, 'Could not remove the key.'))
    },
  })

  const runTest = useMutation({
    mutationFn: () => testVoice(),
    onSuccess: (result: VoiceTestResult) => {
      // A passing test updates the key's last use, so the refreshed config it
      // hands back is what the fingerprint line should be reading from.
      if (result.data) applyConfig(result.data)
      setTest({
        ok: result.ok,
        message: result.message,
        latencyMs: result.latency_ms,
        model: result.model,
      })
    },
    onError: (error) => {
      setTest({
        ok: false,
        message: agentErrorMessage(error, 'The test could not be run.'),
        latencyMs: 0,
        model: '',
      })
    },
  })

  const submit = (): void => {
    if (!form || !config) return
    setFormError(null)

    const window = parseWhole(form.confirmWindow)
    if (window === null) {
      setFormError('The confirmation window must be a whole number of seconds.')
      return
    }

    // Only what moved, except for the two spoken values, which travel together
    // whenever either of them has: the server validates them as a pair and
    // re-writes the word when the name changes, so sending one alone would have
    // it validated against a value the operator is no longer looking at.
    const values: VoiceConfigUpdate = {}
    if (form.model.trim() !== config.voice_model) values.voice_model = form.model.trim()
    if (form.speaker !== config.voice_speaker) values.voice_speaker = form.speaker
    const nameMoved = form.agentName.trim() !== config.voice_agent_name
    const phraseMoved = form.orderPhrase.trim() !== config.voice_order_phrase
    if (nameMoved || phraseMoved) {
      values.voice_agent_name = form.agentName.trim()
      values.voice_order_phrase = form.orderPhrase.trim()
    }
    if (window !== config.voice_confirm_window_seconds) {
      values.voice_confirm_window_seconds = window
    }

    if (Object.keys(values).length === 0) {
      setDraft(null)
      return
    }
    saveSettings.mutate(values)
  }

  const switchesBusy = saveSwitch.isPending

  return (
    <Card>
      <CardHeader>
        <CardTitle>Voice</CardTitle>
        <CardDescription>
          A spoken surface on the same agent. The speech model hears and speaks and decides nothing:
          every answer it reads out is produced by the model you configured above, through the same
          tools and the same limits a typed question goes through, and the full answer lands on
          screen as an ordinary message. Audio goes from your browser straight to OpenAI; the only
          thing this server does is mint the session with the key below.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {query.isLoading ? <VoiceSkeleton /> : null}

        {query.isError ? (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" aria-hidden />
            <AlertDescription className="flex flex-wrap items-center gap-3">
              <span>
                {agentErrorMessage(query.error, 'The voice configuration could not be loaded.')}
              </span>
              <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
                Retry
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        {config && form ? (
          <>
            <div className="rounded-lg border border-border">
              <div className="flex items-start gap-3 p-4">
                <Switch
                  id={`${fieldId}-enabled`}
                  checked={config.voice_enabled}
                  disabled={switchesBusy}
                  onCheckedChange={(next) => saveSwitch.mutate({ voice_enabled: next })}
                  aria-describedby={`${fieldId}-enabled-help`}
                />
                <div className="min-w-0 flex-1">
                  <Label htmlFor={`${fieldId}-enabled`} className="text-sm font-medium">
                    Let the agent listen and speak
                  </Label>
                  <p id={`${fieldId}-enabled-help`} className="mt-1 text-sm text-muted-foreground">
                    {config.voice_enabled
                      ? 'The microphone is offered in the chat composer. Nothing is heard until you press it.'
                      : 'The microphone is not offered anywhere, so the voice surface cannot be started.'}
                  </p>
                  {config.voice_enabled && !config.key.has_value ? (
                    <p className="mt-2 text-sm text-muted-foreground">
                      No OpenAI key is stored yet, so a session cannot be minted. Add one below.
                    </p>
                  ) : null}
                </div>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor={`${fieldId}-model`}>Speech model</Label>
                <Input
                  id={`${fieldId}-model`}
                  value={form.model}
                  spellCheck={false}
                  autoComplete="off"
                  onChange={(event) => setDraft({ ...form, model: event.target.value })}
                />
                <p className="text-xs text-muted-foreground">
                  {defaults
                    ? `The model that hears and speaks. Default ${defaults.voice_model}.`
                    : 'The model that hears and speaks.'}
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor={`${fieldId}-speaker`}>Voice</Label>
                <Select
                  value={form.speaker}
                  onValueChange={(next) => setDraft({ ...form, speaker: next })}
                >
                  <SelectTrigger id={`${fieldId}-speaker`} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {config.speakers.map((speaker) => (
                      <SelectItem key={speaker} value={speaker}>
                        {speaker}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Which OpenAI voice speaks the answers. The list is advisory; your account decides
                  which of them it will actually serve.
                </p>
              </div>
            </div>

            <Separator />

            <div className="space-y-4">
              <div className="space-y-1">
                <h3 className="text-sm font-semibold">What the agent is called, and what trades</h3>
                <p className="text-xs text-muted-foreground">
                  These are two different words on purpose. The name is what you say to get the
                  agent's attention and it carries no authority at all. The approval word does one
                  thing: it approves an order that has already been staged and read back to you. A
                  word said all day must not also be the word that places a trade, so the approval
                  word may not appear anywhere in the name and the server refuses a pair that breaks
                  that.
                </p>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor={`${fieldId}-name`}>What you call the agent</Label>
                  <Input
                    id={`${fieldId}-name`}
                    value={form.agentName}
                    maxLength={MAX_NAME_CHARS}
                    spellCheck={false}
                    autoComplete="off"
                    onChange={(event) => setDraft({ ...form, agentName: event.target.value })}
                  />
                  <p className="text-xs text-muted-foreground">
                    {`Letters and spaces, up to ${MAX_NAME_CHARS} characters.`}
                    {defaults ? ` Leave it empty to restore ${defaults.voice_agent_name}.` : ''}
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor={`${fieldId}-phrase`}>Word that approves an order</Label>
                  <Input
                    id={`${fieldId}-phrase`}
                    value={form.orderPhrase}
                    maxLength={MAX_PHRASE_CHARS}
                    spellCheck={false}
                    autoComplete="off"
                    onChange={(event) => setDraft({ ...form, orderPhrase: event.target.value })}
                  />
                  <p className="text-xs text-muted-foreground">
                    {`One word, ${MIN_PHRASE_CHARS} to ${MAX_PHRASE_CHARS} letters, no spaces, digits or punctuation.`}
                    {defaults ? ` Leave it empty to restore ${defaults.voice_order_phrase}.` : ''}
                  </p>
                </div>
              </div>

              {conflict ? (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" aria-hidden />
                  <AlertDescription>
                    {`"${form.orderPhrase.trim()}" appears in the name, so it cannot also be the approval word. Change one of them before saving.`}
                  </AlertDescription>
                </Alert>
              ) : null}
            </div>

            <Separator />

            <div className="space-y-4">
              <div className="space-y-1">
                <h3 className="text-sm font-semibold">Placing orders by voice</h3>
                <p className="text-xs text-muted-foreground">
                  Ships off. With it off the voice surface is read only: the agent answers questions
                  and draws charts, and the tools that place, modify or cancel an order are never
                  offered to it, so it declines rather than asking you to approve anything.
                </p>
              </div>

              {/* Nested rather than beside the other controls, because this
                  setting is an `and` with the agent's trading switch and never
                  an `or`. Rendering it as a peer would show a switch that looks
                  like it decides something on an instance where it decides
                  nothing. */}
              <div className="rounded-lg border border-border border-l-4 border-l-muted-foreground/40">
                <div className="flex items-start gap-3 p-4">
                  <Switch
                    id={`${fieldId}-voice-trading`}
                    checked={config.voice_trading_enabled}
                    disabled={switchesBusy}
                    onCheckedChange={(next) => saveSwitch.mutate({ voice_trading_enabled: next })}
                    aria-describedby={`${fieldId}-voice-trading-help`}
                  />
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Label htmlFor={`${fieldId}-voice-trading`} className="text-sm font-medium">
                        Let a spoken request reach the order tools
                      </Label>
                      <Badge variant={config.trading_effective ? 'secondary' : 'outline'}>
                        {config.trading_effective ? 'Reachable' : 'Not reachable'}
                      </Badge>
                    </div>
                    <p
                      id={`${fieldId}-voice-trading-help`}
                      className="text-sm text-muted-foreground"
                    >
                      Subject to the Trading switch in the section above. This one can only take
                      capability away from the voice surface, never add it.
                    </p>

                    {config.trading_enabled_master ? null : (
                      <p className="rounded-md bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                        The agent's Trading switch is currently off, so turning this on has no
                        effect. Order tools stay withheld on every surface, spoken or typed, until
                        that switch is on.
                      </p>
                    )}
                  </div>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor={`${fieldId}-window`}>Approval window, seconds</Label>
                  <Input
                    id={`${fieldId}-window`}
                    type="number"
                    min={MIN_CONFIRM_WINDOW}
                    max={MAX_CONFIRM_WINDOW}
                    step={1}
                    value={form.confirmWindow}
                    onChange={(event) => setDraft({ ...form, confirmWindow: event.target.value })}
                  />
                  <p className="text-xs text-muted-foreground">
                    {`${MIN_CONFIRM_WINDOW} to ${MAX_CONFIRM_WINDOW}.`}
                    {defaults ? ` Default ${defaults.voice_confirm_window_seconds}.` : ''} It opens
                    only after an order has been staged and read back, allows one attempt, and
                    closes on the first thing said either way.
                  </p>
                </div>
              </div>

              {/* Stated whether or not the switch is on. An operator deciding
                  whether to turn it on is exactly the reader this paragraph is
                  for, and they read it before the switch, not after. */}
              <div className="rounded-md border px-3 py-2 text-sm text-muted-foreground">
                <p>
                  What spoken approval means: while that window is open, anyone within earshot who
                  says <span className="font-mono">{config.voice_order_phrase}</span> can place the
                  staged order. The agent cannot tell one voice from another. The word has to be
                  said on its own, with nothing but a bare "yes" or "confirm" around it, and the
                  window is short and single use, which narrows that surface without removing it.
                </p>
                <p className="mt-2">
                  The on-screen confirmation card never goes away, so tapping still works and is the
                  only way to approve once the window has closed. If your room is not one where that
                  trade-off is acceptable, leave this off and tap.
                </p>
              </div>
            </div>

            {formError ? (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" aria-hidden />
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            ) : null}

            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={submit} disabled={!dirty || conflict || saveSettings.isPending}>
                {saveSettings.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                Save settings
              </Button>
              <Button
                variant="ghost"
                disabled={!dirty || saveSettings.isPending}
                onClick={() => {
                  setDraft(null)
                  setFormError(null)
                }}
              >
                Discard changes
              </Button>
              {dirty ? (
                <span className="text-xs text-muted-foreground">
                  Unsaved. The text above still describes what the agent does now.
                </span>
              ) : null}
            </div>

            <Separator />

            <div className="space-y-3">
              <div className="space-y-1">
                <h3 className="text-sm font-semibold">OpenAI key</h3>
                <p className="text-xs text-muted-foreground">
                  Used only to mint the speech session, and stored encrypted in this instance's own
                  database rather than in a configuration file. It is separate from any OpenAI model
                  key above on purpose: the intelligence can run on Claude, or on a local model,
                  while OpenAI supplies the ears and the mouth. The key is write only. It is never
                  sent back to this screen, so the field starts empty even when one is stored.
                </p>
              </div>

              <div className="space-y-2 rounded-lg border p-4">
                <Label htmlFor={`${fieldId}-key`} className="text-xs">
                  API key
                </Label>
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    id={`${fieldId}-key`}
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    className="max-w-md flex-1"
                    placeholder={
                      config.key.has_value
                        ? 'Leave empty to keep the stored key'
                        : 'Paste the OpenAI key'
                    }
                    value={keyDraft}
                    onChange={(event) => setKeyDraft(event.target.value)}
                  />
                  <Button
                    size="sm"
                    disabled={keyDraft.trim() === '' || saveKey.isPending}
                    onClick={() => saveKey.mutate(keyDraft)}
                  >
                    {saveKey.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                    ) : null}
                    Save key
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!config.key.has_value || runTest.isPending}
                    onClick={() => runTest.mutate()}
                  >
                    {runTest.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                    ) : null}
                    Test
                  </Button>
                  {config.key.has_value ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={removeKey.isPending}
                      onClick={() => setClearingKey(true)}
                    >
                      Remove key
                    </Button>
                  ) : null}
                </div>
                <p className="text-xs text-muted-foreground">
                  {config.key.has_value ? (
                    <>
                      Stored key <span className="font-mono">{config.key.fingerprint}</span>. Last
                      used {formatUtc(config.key.last_used_at)}. Test mints one session and throws
                      it away; no audio is involved.
                    </>
                  ) : (
                    <>No key stored. Paste one and save it, then test it.</>
                  )}
                </p>

                {test ? <TestResult test={test} /> : null}
              </div>
            </div>
          </>
        ) : null}
      </CardContent>

      <AlertDialog open={clearingKey} onOpenChange={(open) => !open && setClearingKey(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove the OpenAI voice key</AlertDialogTitle>
            <AlertDialogDescription>
              The stored key cannot be read back, so removing it means pasting it again from
              wherever you keep it. The voice surface stops working until a key is stored again; the
              settings themselves are left alone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                removeKey.mutate()
                setClearingKey(false)
              }}
            >
              Remove key
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

function TestResult({ test }: { test: TestOutcome }) {
  return (
    <div
      className={cn(
        'rounded-md border px-3 py-2 text-xs',
        test.ok
          ? 'border-emerald-500/50 bg-emerald-50 text-emerald-900 dark:border-emerald-600/60 dark:bg-emerald-950/40 dark:text-emerald-200'
          : 'border-destructive/50 bg-destructive/5 text-destructive'
      )}
    >
      <p>{test.message}</p>
      <p className="mt-1 tabular-nums opacity-80">
        {test.latencyMs} ms{test.model ? `, ${test.model}` : ''}
      </p>
    </div>
  )
}

function VoiceSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-20 w-full" />
      <div className="grid gap-4 sm:grid-cols-2">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-28 w-full" />
    </div>
  )
}

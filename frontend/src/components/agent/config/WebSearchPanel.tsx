/**
 * Web search configuration.
 *
 * Three providers, one selection, and a key per paid provider. The behaviour
 * this screen has to make obvious is the routing, because it is not guessable
 * from a provider list and an operator who guesses wrong reads a working setup
 * as broken:
 *
 * - DuckDuckGo needs no key and answers link searches out of the box.
 * - Tavily replaces it for link searches once its key is stored, and silently
 *   falls back to DuckDuckGo when the key is missing or the call fails.
 * - Perplexity is a different kind of result, a synthesised answer with
 *   citations, so it answers a different tool. Selecting it leaves link
 *   searches on DuckDuckGo rather than switching them off.
 *
 * Two rules from the module contract are enforced here rather than assumed:
 *
 * - **A key value is never rendered.** The response carries no key at all, only
 *   a presence flag and a display-safe fingerprint, and the input starts empty
 *   even when a key is stored. Blank on save means keep, exactly as it does for
 *   a model key, which is why Save is disabled while the field is empty rather
 *   than sending a blank the server would have to interpret.
 * - **The server owns validation.** An out-of-range cap is refused, not
 *   clamped, and its message is the one shown. Only the "is this a whole
 *   number" check is local, because a non-numeric value cannot be sent at all
 *   through a typed payload.
 *
 * The saved configuration, not the unsaved form, is what the routing sentence
 * and the usage meter describe. Reporting what the agent will do once someone
 * presses Save would be a lie for as long as the form sits dirty.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Globe, Loader2 } from 'lucide-react'
import { useId, useState } from 'react'
import {
  agentErrorMessage,
  agentQueryKeys,
  clearWebSearchKey,
  getWebSearchConfig,
  setWebSearchKey,
  testWebSearchProvider,
  updateWebSearchConfig,
  type WebSearchConfig,
  type WebSearchConfigResponse,
  type WebSearchConfigUpdate,
  type WebSearchProvider,
  type WebSearchProviderId,
  type WebSearchTestResult,
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
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

/** The bounds the settings module enforces, mirrored only as input hints. */
const MAX_CALLS_PER_TURN = 50
const MAX_DAILY_CAP = 10000
const MAX_PERPLEXITY_MODEL_CHARS = 120

/** Above this a passing DuckDuckGo test deserves an explanation, not alarm. */
const SLOW_TEST_MS = 5000

/** The editable half of the configuration, held as text while it is typed. */
interface Draft {
  provider: WebSearchProviderId
  perplexityModel: string
  maxCallsPerTurn: string
  dailyCap: string
}

function toDraft(config: WebSearchConfig): Draft {
  return {
    provider: config.provider,
    perplexityModel: config.perplexity_model,
    maxCallsPerTurn: String(config.max_calls_per_turn),
    dailyCap: String(config.daily_cap),
  }
}

function sameDraft(a: Draft, b: Draft): boolean {
  return (
    a.provider === b.provider &&
    a.perplexityModel === b.perplexityModel &&
    a.maxCallsPerTurn === b.maxCallsPerTurn &&
    a.dailyCap === b.dailyCap
  )
}

/**
 * A whole number, or null when the text is not one.
 *
 * Deliberately strict: the payload is typed as a number, so a value that is not
 * one cannot travel to the server to collect the server's own message. This is
 * the only validation that lives on this side.
 */
function parseWhole(raw: string): number | null {
  const text = raw.trim()
  if (!/^\d+$/.test(text)) return null
  const value = Number(text)
  return Number.isSafeInteger(value) ? value : null
}

/**
 * A naive UTC timestamp rendered in the reader's own timezone.
 *
 * The server sends `2026-09-02T10:11:12` with no offset, which `Date` reads as
 * local time. Appending the marker is what stops a key last used an hour ago
 * from being reported five and a half hours in the future.
 */
function formatUtc(value: string | null): string {
  if (!value) return 'never'
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`
  const parsed = new Date(normalized)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

/** What each provider gives back, said in the operator's words. */
function resultKindLabel(provider: WebSearchProvider): string {
  return provider.result_kind === 'links' ? 'Links' : 'Cited answer'
}

/**
 * What the saved configuration actually does, and whether that needs a warning.
 *
 * Every branch names the provider that ends up answering, because the fallback
 * is silent at run time and an operator who cannot see it here will never see
 * it at all.
 */
function routingState(config: WebSearchConfig): { text: string; warn: boolean } {
  const selected = config.providers.find((entry) => entry.id === config.provider)
  const ready = selected?.ready ?? false

  if (config.provider === 'duckduckgo') {
    return {
      text: 'Link searches run on DuckDuckGo, which needs no key and works out of the box.',
      warn: false,
    }
  }

  if (config.provider === 'tavily') {
    return ready
      ? { text: 'Link searches run on Tavily.', warn: false }
      : {
          text:
            'Tavily is selected but no Tavily key is stored, so link searches fall back to ' +
            'DuckDuckGo.',
          warn: true,
        }
  }

  return ready
    ? {
        text:
          'Perplexity answers questions with citations through the web_research tool. Link ' +
          'searches still run on DuckDuckGo.',
        warn: false,
      }
    : {
        text:
          'Perplexity is selected but no Perplexity key is stored, so web_research cannot run. ' +
          'Link searches run on DuckDuckGo either way.',
        warn: true,
      }
}

/** A test outcome, whether the route answered it or the request itself failed. */
interface TestOutcome {
  ok: boolean
  message: string
  latencyMs: number
  resultCount: number
}

export function WebSearchPanel() {
  const queryClient = useQueryClient()
  const fieldId = useId()

  const query = useQuery({
    queryKey: agentQueryKeys.websearch(),
    queryFn: getWebSearchConfig,
    staleTime: 30_000,
  })

  const config = query.data?.data ?? null
  const defaults = query.data?.defaults ?? null

  // Null means "whatever the server last said". Clearing it after a save is
  // what re-derives the form from the refreshed response, so no effect has to
  // watch the query and no stale draft can survive a successful write.
  const [draft, setDraft] = useState<Draft | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [keyDrafts, setKeyDrafts] = useState<Record<string, string>>({})
  const [tests, setTests] = useState<Record<string, TestOutcome>>({})
  const [clearing, setClearing] = useState<WebSearchProvider | null>(null)

  const form = draft ?? (config ? toDraft(config) : null)
  const dirty = form !== null && config !== null && !sameDraft(form, toDraft(config))

  /**
   * Every mutation answers with the whole refreshed configuration, so the cache
   * is written from the response rather than invalidated. One round trip, and
   * no window in which the screen shows the value that was just replaced.
   */
  const applyConfig = (next: WebSearchConfig): void => {
    queryClient.setQueryData<WebSearchConfigResponse>(agentQueryKeys.websearch(), (prev) =>
      prev ? { ...prev, data: next } : prev
    )
  }

  const saveSettings = useMutation({
    mutationFn: (values: WebSearchConfigUpdate) => updateWebSearchConfig(values),
    onSuccess: (next) => {
      applyConfig(next)
      setDraft(null)
      setFormError(null)
      showToast.success('Web search settings saved')
    },
    onError: (error) => {
      setFormError(agentErrorMessage(error, 'Could not save the web search settings.'))
    },
  })

  const saveKey = useMutation({
    mutationFn: (variables: { provider: WebSearchProviderId; apiKey: string }) =>
      setWebSearchKey(variables.provider, variables.apiKey),
    onSuccess: (next, variables) => {
      applyConfig(next)
      // Cleared on the way out, not held for a retry: the field is write only
      // and a key sitting in component state is a key on the screen.
      setKeyDrafts((prev) => ({ ...prev, [variables.provider]: '' }))
      showToast.success('Key saved')
    },
    onError: (error) => {
      showToast.error(agentErrorMessage(error, 'Could not save the key.'))
    },
  })

  const clearKey = useMutation({
    mutationFn: (provider: WebSearchProviderId) => clearWebSearchKey(provider),
    onSuccess: (next, provider) => {
      applyConfig(next)
      setTests((prev) => {
        const rest = { ...prev }
        delete rest[provider]
        return rest
      })
      showToast.success('Key removed')
    },
    onError: (error) => {
      showToast.error(agentErrorMessage(error, 'Could not remove the key.'))
    },
  })

  const testProvider = useMutation({
    mutationFn: (variables: { provider: WebSearchProviderId; apiKey?: string }) =>
      testWebSearchProvider(variables.provider, variables.apiKey),
    onSuccess: (result: WebSearchTestResult) => {
      applyConfig(result.data)
      setTests((prev) => ({
        ...prev,
        [result.provider]: {
          ok: result.ok,
          message: result.message,
          latencyMs: result.latency_ms,
          resultCount: result.result_count,
        },
      }))
    },
    onError: (error, variables) => {
      setTests((prev) => ({
        ...prev,
        [variables.provider]: {
          ok: false,
          message: agentErrorMessage(error, 'The test could not be run.'),
          latencyMs: 0,
          resultCount: 0,
        },
      }))
    },
  })

  const submit = (): void => {
    if (!form || !config) return
    setFormError(null)

    const calls = parseWhole(form.maxCallsPerTurn)
    if (calls === null) {
      setFormError('Searches per turn must be a whole number.')
      return
    }
    const cap = parseWhole(form.dailyCap)
    if (cap === null) {
      setFormError('Daily cap must be a whole number.')
      return
    }

    // Only what moved. Sending an unchanged field is harmless but it makes a
    // rejected write ambiguous about which field the server refused.
    const values: WebSearchConfigUpdate = {}
    if (form.provider !== config.provider) values.provider = form.provider
    if (form.perplexityModel.trim() !== config.perplexity_model) {
      values.perplexity_model = form.perplexityModel.trim()
    }
    if (calls !== config.max_calls_per_turn) values.max_calls_per_turn = calls
    if (cap !== config.daily_cap) values.daily_cap = cap

    if (Object.keys(values).length === 0) {
      setDraft(null)
      return
    }
    saveSettings.mutate(values)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Globe className="h-4 w-4 text-muted-foreground" aria-hidden />
          Web search
        </CardTitle>
        <CardDescription>
          DuckDuckGo needs no key and answers link searches out of the box; Tavily replaces it for
          link searches once its key is stored; Perplexity answers questions with citations through
          a separate tool, so choosing it leaves link searches on DuckDuckGo. Keys are stored
          encrypted in your own database and never in a configuration file.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {query.isLoading ? <WebSearchSkeleton /> : null}

        {query.isError ? (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" aria-hidden />
            <AlertDescription className="flex flex-wrap items-center gap-3">
              <span>
                {agentErrorMessage(
                  query.error,
                  'The web search configuration could not be loaded.'
                )}
              </span>
              <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
                Retry
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        {config && form && defaults ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor={`${fieldId}-provider`}>Search provider</Label>
                <Select
                  value={form.provider}
                  onValueChange={(next) =>
                    setDraft({ ...form, provider: next as WebSearchProviderId })
                  }
                >
                  <SelectTrigger id={`${fieldId}-provider`} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {config.providers.map((provider) => (
                      <SelectItem key={provider.id} value={provider.id}>
                        {provider.label}
                        {provider.needs_key && !provider.has_api_key ? ' (no key stored)' : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Reverts to {labelOf(config, defaults.provider)}.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor={`${fieldId}-perplexity-model`}>Perplexity model</Label>
                <Input
                  id={`${fieldId}-perplexity-model`}
                  value={form.perplexityModel}
                  maxLength={MAX_PERPLEXITY_MODEL_CHARS}
                  spellCheck={false}
                  autoComplete="off"
                  onChange={(event) => setDraft({ ...form, perplexityModel: event.target.value })}
                />
                <p className="text-xs text-muted-foreground">
                  {`The model web_research runs. Leave it empty to restore ${defaults.perplexity_model}.`}
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor={`${fieldId}-calls`}>Searches per turn</Label>
                <Input
                  id={`${fieldId}-calls`}
                  type="number"
                  min={0}
                  max={MAX_CALLS_PER_TURN}
                  step={1}
                  value={form.maxCallsPerTurn}
                  onChange={(event) => setDraft({ ...form, maxCallsPerTurn: event.target.value })}
                />
                <p className="text-xs text-muted-foreground">
                  0 to {MAX_CALLS_PER_TURN}. Default {defaults.max_calls_per_turn}.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor={`${fieldId}-cap`}>Daily cap</Label>
                <Input
                  id={`${fieldId}-cap`}
                  type="number"
                  min={0}
                  max={MAX_DAILY_CAP}
                  step={1}
                  value={form.dailyCap}
                  onChange={(event) => setDraft({ ...form, dailyCap: event.target.value })}
                />
                <p className="text-xs text-muted-foreground">
                  0 to {MAX_DAILY_CAP}. Default {defaults.daily_cap}. A per-turn budget alone is
                  bypassed by sending another message, so this one is counted in the database.
                </p>
              </div>
            </div>

            <RoutingNotice config={config} />

            <UsageMeter config={config} />

            {formError ? (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" aria-hidden />
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            ) : null}

            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={submit} disabled={!dirty || saveSettings.isPending}>
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
                  Unsaved. The description above still reports what the agent does now.
                </span>
              ) : null}
            </div>

            <Separator />

            <div className="space-y-3">
              <div className="space-y-1">
                <h3 className="text-sm font-semibold">Provider keys</h3>
                <p className="text-xs text-muted-foreground">
                  A key is write only. It is never sent back to this screen, so the field starts
                  empty even when one is stored and leaving it empty keeps the stored key.
                </p>
              </div>

              {config.providers.map((provider) => (
                <ProviderRow
                  key={provider.id}
                  provider={provider}
                  selected={provider.id === config.provider}
                  keyDraft={keyDrafts[provider.id] ?? ''}
                  onKeyDraftChange={(value) =>
                    setKeyDrafts((prev) => ({ ...prev, [provider.id]: value }))
                  }
                  test={tests[provider.id]}
                  savingKey={saveKey.isPending && saveKey.variables?.provider === provider.id}
                  clearingKey={clearKey.isPending && clearKey.variables === provider.id}
                  testing={
                    testProvider.isPending && testProvider.variables?.provider === provider.id
                  }
                  onSaveKey={() =>
                    saveKey.mutate({
                      provider: provider.id,
                      apiKey: keyDrafts[provider.id] ?? '',
                    })
                  }
                  onClearKey={() => setClearing(provider)}
                  onTest={() => {
                    const typed = (keyDrafts[provider.id] ?? '').trim()
                    testProvider.mutate({
                      provider: provider.id,
                      apiKey: typed === '' ? undefined : typed,
                    })
                  }}
                />
              ))}
            </div>
          </>
        ) : null}
      </CardContent>

      <AlertDialog open={clearing !== null} onOpenChange={(open) => !open && setClearing(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove the {clearing?.label} key</AlertDialogTitle>
            <AlertDialogDescription>
              The stored key cannot be read back, so removing it means pasting it again from
              wherever you keep it. {clearing?.id === 'tavily' ? 'Link searches fall back to ' : ''}
              {clearing?.id === 'tavily'
                ? 'DuckDuckGo until a key is stored again.'
                : 'The web_research tool cannot run until a key is stored again.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (clearing) clearKey.mutate(clearing.id)
                setClearing(null)
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

/** The display name of a provider id, falling back to the id itself. */
function labelOf(config: WebSearchConfig, id: WebSearchProviderId): string {
  return config.providers.find((provider) => provider.id === id)?.label ?? id
}

function RoutingNotice({ config }: { config: WebSearchConfig }) {
  const state = routingState(config)
  return (
    <div
      className={cn(
        'rounded-md border px-3 py-2 text-sm',
        state.warn
          ? 'border-amber-500 bg-amber-50 text-amber-900 dark:border-amber-600 dark:bg-amber-950/50 dark:text-amber-200'
          : 'bg-muted/40 text-muted-foreground'
      )}
    >
      {state.text}
    </div>
  )
}

/**
 * How much of today's budget is left.
 *
 * Measured as remaining rather than used, because the Progress primitive turns
 * green as it fills: a bar that goes green when the budget is nearly exhausted
 * would read as healthy at exactly the wrong moment.
 */
function UsageMeter({ config }: { config: WebSearchConfig }) {
  const { usage, daily_cap: cap } = config

  if (cap === 0) {
    return (
      <div className="rounded-md border border-amber-500 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-600 dark:bg-amber-950/50 dark:text-amber-200">
        The daily cap is 0, so the agent will not search the web at all.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium">Searches left today</span>
        <span className="tabular-nums text-muted-foreground">
          {usage.remaining} of {cap}
        </span>
      </div>
      <Progress value={usage.remaining} max={cap} className="h-2" />
      <p className="text-xs text-muted-foreground">
        {usage.count} used on {usage.date}, counted on the IST date and reset by the date itself
        rather than by a scheduled job.
      </p>
    </div>
  )
}

interface ProviderRowProps {
  provider: WebSearchProvider
  selected: boolean
  keyDraft: string
  onKeyDraftChange: (value: string) => void
  test: TestOutcome | undefined
  savingKey: boolean
  clearingKey: boolean
  testing: boolean
  onSaveKey: () => void
  onClearKey: () => void
  onTest: () => void
}

function ProviderRow({
  provider,
  selected,
  keyDraft,
  onKeyDraftChange,
  test,
  savingKey,
  clearingKey,
  testing,
  onSaveKey,
  onClearKey,
  onTest,
}: ProviderRowProps) {
  const inputId = useId()
  const hasDraft = keyDraft.trim() !== ''

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{provider.label}</span>
            {selected ? <Badge variant="secondary">Selected</Badge> : null}
            <Badge variant="outline">{resultKindLabel(provider)}</Badge>
            <Badge variant="outline" className="font-mono text-[11px]">
              {provider.tool}
            </Badge>
          </div>
          <p className="max-w-2xl text-xs text-muted-foreground">{provider.description}</p>
        </div>
        <Badge variant={provider.ready ? 'secondary' : 'outline'}>
          {provider.ready ? 'Ready' : 'Needs a key'}
        </Badge>
      </div>

      {provider.needs_key ? (
        <div className="space-y-2">
          <Label htmlFor={inputId} className="text-xs">
            API key
          </Label>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              id={inputId}
              type="password"
              autoComplete="off"
              spellCheck={false}
              className="max-w-md flex-1"
              placeholder={
                provider.has_api_key
                  ? 'Leave empty to keep the stored key'
                  : `Paste the ${provider.label} key`
              }
              value={keyDraft}
              onChange={(event) => onKeyDraftChange(event.target.value)}
            />
            <Button size="sm" disabled={!hasDraft || savingKey} onClick={onSaveKey}>
              {savingKey ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              Save key
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={testing || (!provider.has_api_key && !hasDraft)}
              onClick={onTest}
            >
              {testing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              Test
            </Button>
            {provider.has_api_key ? (
              <Button size="sm" variant="ghost" disabled={clearingKey} onClick={onClearKey}>
                Remove key
              </Button>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground">
            {provider.has_api_key ? (
              <>
                Stored key <span className="font-mono">{provider.api_key_fingerprint}</span>. Last
                used {formatUtc(provider.api_key_last_used_at)}.
              </>
            ) : (
              <>
                No key stored.{' '}
                {hasDraft
                  ? 'Test checks the key typed above without saving it.'
                  : 'Paste one to save or to test it before saving.'}
              </>
            )}
          </p>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" disabled={testing} onClick={onTest}>
            {testing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
            Test
          </Button>
          <span className="text-xs text-muted-foreground">
            No key needed, so this provider works with nothing configured.
          </span>
        </div>
      )}

      {test ? <TestResult provider={provider} test={test} /> : null}
    </div>
  )
}

function TestResult({ provider, test }: { provider: WebSearchProvider; test: TestOutcome }) {
  const slowKeyless = test.ok && !provider.needs_key && test.latencyMs >= SLOW_TEST_MS

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
        {test.latencyMs} ms
        {test.ok ? `, ${test.resultCount} result${test.resultCount === 1 ? '' : 's'}` : ''}
      </p>
      {slowKeyless ? (
        <p className="mt-1 opacity-80">
          {provider.label} aggregates several engines, so one slow engine decides the time. A slow
          pass is still a pass.
        </p>
      ) : null}
    </div>
  )
}

function WebSearchSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
      <Skeleton className="h-10 w-full" />
      <div className="space-y-3">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    </div>
  )
}

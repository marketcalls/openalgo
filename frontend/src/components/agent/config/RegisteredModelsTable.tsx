/**
 * The models the operator has already added, with everything needed to run one.
 *
 * This is the second half of the model configuration screen. The catalog panel
 * above it answers "what could I add"; this table answers "what did I add, and
 * does it work", which is a different question and needs different columns: the
 * id actually sent to LiteLLM, the fingerprint of the key that will authenticate
 * it, and the outcome of the last credential test.
 *
 * Five decisions here are load bearing, and the obvious implementation of each
 * one is wrong:
 *
 * - **A blank key field means keep the stored key, never clear it.** The input
 *   starts empty even when a key is configured, because a secret is never sent
 *   back to the client, so blank is the state of every edit that was not about
 *   the key. Reading it as "clear" would silently unconfigure the provider on an
 *   unrelated edit such as renaming a model. `api_key` is therefore omitted from
 *   the payload entirely unless the operator typed something.
 * - **No clear-key action is offered, because there is no route for one.**
 *   `PATCH /agent/api/models/<id>` treats a blank `api_key` as "no change" and
 *   the module ships nothing else, so a Clear button here could only fake it by
 *   writing a junk value. Removing the model removes its per-model override.
 * - **A key edit says where the key goes.** The default scope is `provider`,
 *   which is what lets one pasted OpenAI key serve every GPT model, and that
 *   also means a key typed while editing one model rotates the credential for
 *   every model of that kind. The scope selector appears the moment a key is
 *   typed, and it starts on whichever scope this model is already answered by.
 * - **The default is a radio, and one click moves it.** The server enforces that
 *   exactly one row holds it and refuses an untested or disabled model with a
 *   409, so a row that cannot hold it has its radio disabled with the reason in
 *   its tooltip rather than offered and then rejected. The row that already
 *   holds it stays enabled, because a disabled radio is drawn desaturated and
 *   the current default has to read as selected.
 * - **A failed action is shown against the row that failed.** A test failure, a
 *   refused promotion and a refused delete all open that row's detail area and
 *   render the server's own sentence: "invalid API key" and "model not found"
 *   need different fixes, and a generic failure message helps nobody.
 *
 * Deleting a model can change whether the agent is configured at all, since the
 * deleted row may have been the default or the only one, so every mutation here
 * invalidates the status query and the setup gate re-evaluates itself.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ChevronDown, ChevronRight, Cpu, Loader2, Pencil, Trash2 } from 'lucide-react'
import { Fragment, useState } from 'react'
import {
  type AgentModel,
  type ApiKeyScope,
  agentErrorMessage,
  agentQueryKeys,
  type ChatGptStatus,
  deleteModel,
  getChatGptStatus,
  listModels,
  type ModelTestResult,
  type ProviderKind,
  type ReasoningEffort,
  setDefaultModel,
  testModel,
  type UpdateModelPayload,
  updateModel,
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { isSubscriptionModel, SUBSCRIPTION_BADGE } from '@/lib/agent/subscription'

/** How many columns a detail row has to span. */
const COLUMN_COUNT = 8

/** How many placeholder rows the first load shows. */
const SKELETON_ROWS = 3

/** Brand names for the five kinds `ag_provider_model.provider_kind` accepts. */
const PROVIDER_LABELS: Record<ProviderKind, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  ollama: 'Ollama',
  openai_compatible: 'OpenAI compatible',
  litellm: 'LiteLLM',
}

/** The kinds whose model reaches an operator-supplied endpoint. */
const NEEDS_BASE_URL: ProviderKind[] = ['ollama', 'openai_compatible']

/** The kinds that authenticate with a key. A local Ollama needs none. */
const NEEDS_KEY: ProviderKind[] = ['openai', 'anthropic', 'openai_compatible', 'litellm']

const REASONING_EFFORTS: ReasoningEffort[] = ['off', 'low', 'medium', 'high']

const MINUTE = 60
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/**
 * How long ago something happened, in the shortest honest form.
 *
 * A local copy rather than an import from the chat sidebar, which owns its own:
 * a configuration screen should not pull a conversation list into its chunk to
 * borrow twelve lines of arithmetic.
 *
 * @param iso - An explicit-offset UTC timestamp, as every agent route emits.
 * @returns A short relative label, or an empty string for an unreadable value.
 */
function relativeTime(iso: string | null): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return ''
  // Negative when the server clock is a little ahead, which reads as just now.
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < MINUTE) return 'just now'
  if (seconds < HOUR) return `${Math.round(seconds / MINUTE)}m ago`
  if (seconds < DAY) return `${Math.round(seconds / HOUR)}h ago`
  return `${Math.round(seconds / DAY)}d ago`
}

/** The full timestamp, for the hover the short label cannot carry. */
function fullStamp(iso: string | null): string {
  if (!iso) return ''
  const stamp = new Date(iso)
  return Number.isFinite(stamp.getTime()) ? stamp.toLocaleString() : ''
}

/** The brand name for a provider kind, falling back to the stored value. */
function providerLabel(kind: ProviderKind): string {
  return PROVIDER_LABELS[kind] ?? kind
}

/** Which secret answers for this model, in words rather than as a row name. */
function keySourceLabel(model: AgentModel): string {
  const source = model.api_key_source ?? ''
  if (source.startsWith('model:')) return 'this model only'
  if (source.startsWith('provider:')) {
    return `shared by every ${providerLabel(model.provider_kind)} model`
  }
  return source
}

/**
 * Which key answers for a plan model, which is none of them.
 *
 * A `chatgpt/` row authenticates with an OAuth refresh token from the
 * subscription panel, not with anything in `ag_secret` under `provider:` or
 * `model:`, so `has_api_key` is false and `api_key_fingerprint` is null on the
 * row itself. Leaving the Key cell reading "No key stored" would be true and
 * useless: it would look identical to a misconfigured OpenAI row, on the exact
 * table whose job is telling two identically named GPT-5.4 rows apart.
 *
 * The fingerprint therefore comes from where the credential actually is.
 *
 * @param status - The subscription status, or undefined while it is loading or
 *   if the route is not available on this server.
 * @returns The fingerprint to show, or null when no plan is connected.
 */
function subscriptionFingerprint(status: ChatGptStatus | undefined): string | null {
  if (!status?.authorised) return null
  return status.fingerprint || null
}

/** Why the default radio is or is not available, said in the tooltip. */
function defaultReason(model: AgentModel): string {
  if (model.is_default) return 'This is the default model'
  if (!model.enabled) return 'Enable this model before making it the default'
  if (model.last_test_ok !== true) return 'Test this model before making it the default'
  return `Make ${model.display_name} the default model`
}

/**
 * The registered model registry, with its own edit and remove dialogs.
 *
 * Takes no props: it reads the registry itself so the page above can place it
 * under whatever heading it likes without threading data through.
 */
export function RegisteredModelsTable() {
  const queryClient = useQueryClient()

  // The outcome of a test run in this session, keyed by model id. The row
  // itself only records whether the last test passed and when; latency lives
  // for the length of the visit, which is when it is useful.
  const [results, setResults] = useState<Record<number, ModelTestResult | undefined>>({})
  // A refused action, against the row that refused it. Cleared by writing an
  // empty string rather than by deleting the entry, so the shape never changes.
  const [rowErrors, setRowErrors] = useState<Record<number, string>>({})
  const [openDetails, setOpenDetails] = useState<Record<number, boolean>>({})
  const [editing, setEditing] = useState<AgentModel | null>(null)
  // Bumped on every open so the dialog remounts and its fields, the key field
  // above all, start from the row being edited rather than from the last one.
  const [editKey, setEditKey] = useState(0)
  const [removing, setRemoving] = useState<AgentModel | null>(null)

  const {
    data,
    isPending,
    isError,
    error: listError,
    refetch,
  } = useQuery({
    queryKey: agentQueryKeys.models(),
    queryFn: listModels,
    staleTime: 15_000,
  })

  const models = data ?? []

  // Read only when a plan row is actually on screen. The route is new, an older
  // server answers 404, and a table full of OpenAI models has no reason to ask.
  const hasPlanModel = models.some((model) => isSubscriptionModel(model.model_name))
  const subscription = useQuery({
    queryKey: agentQueryKeys.chatgpt(),
    queryFn: getChatGptStatus,
    enabled: hasPlanModel,
    retry: false,
    staleTime: 30_000,
  })
  const planFingerprint = subscriptionFingerprint(subscription.data)

  const noteError = (id: number, message: string): void => {
    setRowErrors((prev) => ({ ...prev, [id]: message }))
    setOpenDetails((prev) => ({ ...prev, [id]: true }))
  }

  const clearError = (id: number): void => {
    setRowErrors((prev) => ({ ...prev, [id]: '' }))
  }

  // Both, every time. The model list is what this table renders, and the status
  // flags are what the setup gate reads: deleting the default or the last model
  // changes whether /agent is usable at all, and so does disabling one.
  const refreshRegistry = (): void => {
    void queryClient.invalidateQueries({ queryKey: agentQueryKeys.models() })
    void queryClient.invalidateQueries({ queryKey: agentQueryKeys.status() })
  }

  const test = useMutation({
    mutationFn: (id: number) => testModel(id),
    onSuccess: (result, id) => {
      setResults((prev) => ({ ...prev, [id]: result }))
      clearError(id)
      // A failure is worth reading immediately; a pass says everything it needs
      // to in the cell, so it does not push the table around.
      if (!result.ok) setOpenDetails((prev) => ({ ...prev, [id]: true }))
      refreshRegistry()
    },
    onError: (cause, id) => {
      noteError(id, agentErrorMessage(cause, 'Could not reach the test route'))
    },
  })

  const patch = useMutation({
    mutationFn: (input: { id: number; payload: UpdateModelPayload }) =>
      updateModel(input.id, input.payload),
    onSuccess: (_model, input) => {
      clearError(input.id)
      refreshRegistry()
    },
    onError: (cause, input) => {
      noteError(input.id, agentErrorMessage(cause, 'Could not update that model'))
    },
  })

  const promote = useMutation({
    mutationFn: (id: number) => setDefaultModel(id),
    onSuccess: (_model, id) => {
      clearError(id)
      refreshRegistry()
    },
    onError: (cause, id) => {
      noteError(id, agentErrorMessage(cause, 'Could not make that model the default'))
    },
  })

  const remove = useMutation({
    mutationFn: (id: number) => deleteModel(id),
    onSuccess: (_ack, id) => {
      setRemoving(null)
      clearError(id)
      refreshRegistry()
    },
    onError: (cause, id) => {
      noteError(id, agentErrorMessage(cause, 'Could not delete that model'))
    },
  })

  if (isPending) {
    return (
      <div className="space-y-2" aria-busy="true">
        <span className="sr-only">Loading configured models</span>
        {Array.from({ length: SKELETON_ROWS }, (_, index) => (
          <Skeleton key={`model-row-${index}`} className="h-12 w-full" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="space-y-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4">
        <p className="flex items-start gap-2 text-sm leading-relaxed text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>{agentErrorMessage(listError, 'Could not load your configured models')}</span>
        </p>
        <Button type="button" variant="outline" size="sm" onClick={() => void refetch()}>
          Try again
        </Button>
      </div>
    )
  }

  if (models.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border">
        <EmptyState
          icon={Cpu}
          title="No models configured yet"
          description="Pick a provider from the catalog above, paste its key once, and tick the models you want. Everything you add appears here."
        />
      </div>
    )
  }

  return (
    <>
      <div className="rounded-lg border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Model</TableHead>
              <TableHead>Provider</TableHead>
              <TableHead>Key</TableHead>
              <TableHead>Capabilities</TableHead>
              <TableHead>Last test</TableHead>
              <TableHead className="text-center">Enabled</TableHead>
              <TableHead className="text-center">Default</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {models.map((model) => {
              const fresh = results[model.id]
              const rowError = rowErrors[model.id]
              const testing = test.isPending && test.variables === model.id
              const promoting = promote.isPending && promote.variables === model.id
              const toggling = patch.isPending && patch.variables?.id === model.id
              const detailOpen = Boolean(openDetails[model.id])
              const storedError = model.last_test_error?.trim() ?? ''
              const hasDetail = Boolean(rowError) || Boolean(fresh) || Boolean(storedError)
              const canPromote = model.enabled && model.last_test_ok === true
              const onPlan = isSubscriptionModel(model.model_name)
              const needsKey = !onPlan && NEEDS_KEY.includes(model.provider_kind)

              return (
                <Fragment key={model.id}>
                  <TableRow className={detailOpen ? 'border-b-0' : undefined}>
                    <TableCell className="max-w-[18rem]">
                      <div className="truncate font-medium" title={model.display_name}>
                        {model.display_name}
                      </div>
                      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                        <div
                          className="truncate font-mono text-xs text-muted-foreground"
                          title={model.model_name}
                        >
                          {model.model_name}
                        </div>
                        {/* The whole reason this badge exists: eight of the ten
                            chatgpt/ models share a bare name with an openai/
                            one, so two rows can both read GPT-5.4 and bill to
                            different places. The prefix is right there in the
                            id, but an operator scanning a column does not read
                            it as a billing path until something says so. */}
                        {onPlan ? (
                          <Badge
                            variant="secondary"
                            className="shrink-0 font-normal"
                            title="Turns on this model are covered by your ChatGPT Plus or Pro plan, not billed per token against API credits."
                          >
                            {SUBSCRIPTION_BADGE}
                          </Badge>
                        ) : null}
                      </div>
                    </TableCell>

                    <TableCell className="text-sm text-muted-foreground">
                      {providerLabel(model.provider_kind)}
                    </TableCell>

                    <TableCell className="max-w-[14rem]">
                      {onPlan ? (
                        // A plan row has no key of its own, so its credential is
                        // described from where the credential is: the OAuth
                        // session in the subscription panel above.
                        planFingerprint ? (
                          <>
                            <div
                              className="truncate font-mono text-xs text-muted-foreground"
                              title={planFingerprint}
                            >
                              {planFingerprint}
                            </div>
                            <div className="truncate text-[11px] text-muted-foreground/80">
                              your ChatGPT plan sign-in
                            </div>
                          </>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            No plan connected yet
                          </span>
                        )
                      ) : model.has_api_key ? (
                        <>
                          <div
                            className="truncate font-mono text-xs text-muted-foreground"
                            title={model.api_key_fingerprint ?? ''}
                          >
                            {model.api_key_fingerprint}
                          </div>
                          <div className="truncate text-[11px] text-muted-foreground/80">
                            {keySourceLabel(model)}
                          </div>
                        </>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          {needsKey ? 'No key stored' : 'No key needed'}
                        </span>
                      )}
                    </TableCell>

                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {model.supports_reasoning && (
                          <Badge variant="secondary" className="font-normal">
                            Reasoning {model.default_reasoning_effort}
                          </Badge>
                        )}
                        {model.supports_vision && (
                          <Badge variant="secondary" className="font-normal">
                            Vision
                          </Badge>
                        )}
                        {model.tools_unreliable && (
                          <Badge
                            variant="outline"
                            className="border-amber-500/50 font-normal text-amber-700 dark:text-amber-400"
                          >
                            Tools unreliable
                          </Badge>
                        )}
                        {!model.supports_reasoning &&
                          !model.supports_vision &&
                          !model.tools_unreliable && (
                            <span className="text-xs text-muted-foreground">Text and tools</span>
                          )}
                      </div>
                    </TableCell>

                    <TableCell className="max-w-[16rem]">
                      <div className="flex items-center gap-2">
                        {model.last_test_ok === true ? (
                          <Badge
                            variant="outline"
                            className="border-emerald-500/50 font-normal text-emerald-700 dark:text-emerald-400"
                          >
                            Passed
                          </Badge>
                        ) : model.last_test_ok === false ? (
                          <Badge variant="destructive" className="font-normal">
                            Failed
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="font-normal text-muted-foreground">
                            Not tested
                          </Badge>
                        )}
                        <span
                          className="text-xs text-muted-foreground"
                          title={fullStamp(model.last_tested_at)}
                        >
                          {relativeTime(model.last_tested_at)}
                        </span>
                      </div>
                      {fresh?.ok && (
                        <div className="mt-0.5 text-xs text-muted-foreground tabular-nums">
                          {fresh.latency_ms} ms
                        </div>
                      )}
                      {hasDetail && (
                        <button
                          type="button"
                          onClick={() =>
                            setOpenDetails((prev) => ({ ...prev, [model.id]: !detailOpen }))
                          }
                          aria-expanded={detailOpen}
                          className="mt-0.5 inline-flex items-center gap-0.5 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                        >
                          {detailOpen ? (
                            <ChevronDown className="h-3 w-3" aria-hidden />
                          ) : (
                            <ChevronRight className="h-3 w-3" aria-hidden />
                          )}
                          {detailOpen ? 'Hide details' : 'Details'}
                        </button>
                      )}
                    </TableCell>

                    <TableCell className="text-center">
                      <Switch
                        checked={model.enabled}
                        disabled={toggling}
                        aria-label={`Enable ${model.display_name}`}
                        onCheckedChange={(next) =>
                          patch.mutate({ id: model.id, payload: { enabled: next } })
                        }
                      />
                    </TableCell>

                    <TableCell className="text-center">
                      {promoting ? (
                        <Loader2
                          className="mx-auto h-4 w-4 animate-spin text-muted-foreground"
                          aria-hidden
                        />
                      ) : (
                        // The row that already holds the default is left
                        // enabled. A checked radio fires no change event when
                        // it is clicked again, so nothing can happen, and a
                        // disabled one is drawn desaturated by the browser
                        // whatever the accent colour says: the current default
                        // then reads as unselected, which is the one thing
                        // this column exists to say.
                        <input
                          type="radio"
                          name="agent-default-model"
                          className="h-4 w-4 accent-primary disabled:cursor-not-allowed disabled:opacity-50"
                          checked={model.is_default}
                          disabled={!model.is_default && (!canPromote || promote.isPending)}
                          aria-label={defaultReason(model)}
                          title={defaultReason(model)}
                          onChange={() => promote.mutate(model.id)}
                        />
                      )}
                    </TableCell>

                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={testing}
                          onClick={() => test.mutate(model.id)}
                          title={`Send one capped completion to ${providerLabel(model.provider_kind)}`}
                        >
                          {testing ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                          ) : null}
                          {testing ? 'Testing' : 'Test'}
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Edit ${model.display_name}`}
                          title="Edit this model"
                          onClick={() => {
                            setEditing(model)
                            setEditKey((value) => value + 1)
                          }}
                        >
                          <Pencil className="h-4 w-4" aria-hidden />
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          className="text-muted-foreground hover:text-destructive"
                          aria-label={`Remove ${model.display_name}`}
                          title="Remove this model"
                          onClick={() => {
                            clearError(model.id)
                            setRemoving(model)
                          }}
                        >
                          <Trash2 className="h-4 w-4" aria-hidden />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>

                  {detailOpen && hasDetail && (
                    <TableRow className="bg-muted/40 hover:bg-muted/40">
                      <TableCell colSpan={COLUMN_COUNT} className="whitespace-normal py-3">
                        <div className="space-y-2 text-xs leading-relaxed">
                          {rowError && (
                            <p className="flex items-start gap-1.5 text-destructive">
                              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                              <span>{rowError}</span>
                            </p>
                          )}
                          {fresh && (
                            <div>
                              <p className="font-medium">
                                {fresh.ok
                                  ? `The provider answered in ${fresh.latency_ms} ms`
                                  : `The test failed after ${fresh.latency_ms} ms`}
                              </p>
                              <p className="mt-0.5 break-words whitespace-pre-wrap text-muted-foreground">
                                {fresh.message}
                              </p>
                            </div>
                          )}
                          {!fresh && storedError && (
                            <div>
                              <p className="font-medium">
                                The last test failed
                                {model.last_tested_at
                                  ? ` ${relativeTime(model.last_tested_at)}`
                                  : ''}
                              </p>
                              <p className="mt-0.5 break-words whitespace-pre-wrap text-muted-foreground">
                                {storedError}
                              </p>
                            </div>
                          )}
                          {model.base_url && (
                            <p className="text-muted-foreground">
                              Endpoint <span className="font-mono">{model.base_url}</span>
                            </p>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              )
            })}
          </TableBody>
        </Table>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
        Exactly one model is the default, and it is what a request that names no model resolves to.
        A model has to be enabled and to have passed a test before it can hold it. Keys are stored
        encrypted and are never shown again: the fingerprint is enough to tell two keys apart.
      </p>

      {editing && (
        <EditModelDialog
          key={editKey}
          model={editing}
          open={editing !== null}
          onOpenChange={(open) => {
            if (!open) setEditing(null)
          }}
          onSaved={(id) => {
            // A saved base URL invalidates the recorded test result server side,
            // so a latency measured against the old endpoint must not linger.
            setResults((prev) => ({ ...prev, [id]: undefined }))
            clearError(id)
          }}
        />
      )}

      <AlertDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove this model?</AlertDialogTitle>
            <AlertDialogDescription>
              {removing
                ? `"${removing.display_name}" is removed from the registry and from every picker. `
                : null}
              Its per-model key override goes with it. A key shared with the rest of the provider
              stays, because other models still answer to it.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {removing && models.length === 1 ? (
            <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm leading-relaxed text-amber-800 dark:text-amber-300">
              This is the only model you have configured. Removing it leaves the agent unconfigured,
              and /agent goes back to the setup screen until another one is added and tested.
            </p>
          ) : removing?.is_default ? (
            <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm leading-relaxed text-amber-800 dark:text-amber-300">
              This is the default model. The server hands the default to another enabled model that
              has passed a test, and the agent is unconfigured until it has one.
            </p>
          ) : null}
          {removing && rowErrors[removing.id] && (
            // Inside the dialog, not only behind it. This is a modal with a
            // full-screen overlay, so the row's own detail area is covered while
            // it is open and a refused delete would read as a button that did
            // nothing at all.
            <p className="flex items-start gap-1.5 text-sm leading-relaxed text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>{rowErrors[removing.id]}</span>
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={remove.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(event) => {
                // The dialog closes itself on action; the row is only gone once
                // the server says so, so the close is driven by the mutation.
                event.preventDefault()
                if (removing) remove.mutate(removing.id)
              }}
              disabled={remove.isPending}
            >
              {remove.isPending ? 'Removing' : 'Remove'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

interface EditModelDialogProps {
  model: AgentModel
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Told after a successful save, so the table can drop a stale test result. */
  onSaved: (id: number) => void
}

/**
 * Edit one registered model.
 *
 * The provider and the model id are read only, because the server refuses to
 * change either: a different model is a different row, not an edit. Everything
 * else is editable, and the payload carries only what actually changed, so a
 * save is never a blind overwrite of fields the operator did not touch.
 *
 * The API key field is the subtle part. It starts empty even when a key is
 * configured, because no endpoint in this module ever returns a secret, and it
 * is omitted from the payload entirely when left blank. See the module comment.
 */
function EditModelDialog({ model, open, onOpenChange, onSaved }: EditModelDialogProps) {
  const queryClient = useQueryClient()

  const [displayName, setDisplayName] = useState(model.display_name)
  const [baseUrl, setBaseUrl] = useState(model.base_url ?? '')
  // Write only, and it always starts blank. Never seeded from the row, which
  // does not carry a key, and never left in state after the dialog closes.
  const [apiKey, setApiKey] = useState('')
  const [keyScope, setKeyScope] = useState<ApiKeyScope>(
    model.api_key_source?.startsWith('model:') ? 'model' : 'provider'
  )
  const [enabled, setEnabled] = useState(model.enabled)
  const [supportsReasoning, setSupportsReasoning] = useState(model.supports_reasoning)
  const [effort, setEffort] = useState<ReasoningEffort>(model.default_reasoning_effort)
  const [supportsVision, setSupportsVision] = useState(model.supports_vision)
  const [toolsUnreliable, setToolsUnreliable] = useState(model.tools_unreliable)
  const [error, setError] = useState<string | null>(null)

  const needsBaseUrl = NEEDS_BASE_URL.includes(model.provider_kind)
  // A plan model is registered as `litellm`, which normally does want a key.
  // This one cannot have one: it runs on the OAuth session from the
  // subscription panel, so a key field here would take a value that is never
  // read and quietly overwrite the shared LiteLLM key for every other row.
  const onPlan = isSubscriptionModel(model.model_name)
  const needsKey = !onPlan && NEEDS_KEY.includes(model.provider_kind)
  const typedKey = apiKey.trim()

  /**
   * What actually changed, and nothing else.
   *
   * A plain function rather than a memo: it is cheap, and it keeps the key out
   * of a dependency array. `api_key` is present only when the operator typed
   * one, which is what makes a blank field mean "keep the stored key".
   */
  const buildPayload = (): UpdateModelPayload => {
    const payload: UpdateModelPayload = {}
    const name = displayName.trim()
    if (name && name !== model.display_name) payload.display_name = name
    if (needsBaseUrl && baseUrl.trim() !== (model.base_url ?? '')) {
      payload.base_url = baseUrl.trim()
    }
    if (enabled !== model.enabled) payload.enabled = enabled
    if (supportsReasoning !== model.supports_reasoning) {
      payload.supports_reasoning = supportsReasoning
    }
    if (effort !== model.default_reasoning_effort) payload.default_reasoning_effort = effort
    if (supportsVision !== model.supports_vision) payload.supports_vision = supportsVision
    if (toolsUnreliable !== model.tools_unreliable) payload.tools_unreliable = toolsUnreliable
    if (typedKey) {
      payload.api_key = typedKey
      payload.api_key_scope = keyScope
    }
    return payload
  }

  // The server refuses an empty body with a 400 rather than answering 200 to a
  // request that changed nothing, so Save is unavailable until something has.
  const hasChanges = Object.keys(buildPayload()).length > 0

  const save = useMutation({
    mutationFn: () => updateModel(model.id, buildPayload()),
    onSuccess: () => {
      // The plaintext lives no longer than the request it was needed for.
      setApiKey('')
      void queryClient.invalidateQueries({ queryKey: agentQueryKeys.models() })
      void queryClient.invalidateQueries({ queryKey: agentQueryKeys.status() })
      onSaved(model.id)
      onOpenChange(false)
    },
    onError: (cause) => {
      setError(agentErrorMessage(cause, 'Could not save that model'))
    },
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setApiKey('')
        onOpenChange(next)
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit model</DialogTitle>
          <DialogDescription>
            The provider and the model id cannot change. Register the other model instead.
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            setError(null)
            if (!hasChanges) return
            save.mutate()
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="edit-model-provider">Provider</Label>
              <Input id="edit-model-provider" disabled value={providerLabel(model.provider_kind)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-model-id">Model id</Label>
              <Input id="edit-model-id" disabled className="font-mono" value={model.model_name} />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="edit-model-display">Display name</Label>
            <Input
              id="edit-model-display"
              required
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </div>

          {needsBaseUrl && (
            <div className="space-y-1.5">
              <Label htmlFor="edit-model-base-url">Base URL</Label>
              <Input
                id="edit-model-base-url"
                type="url"
                required
                placeholder="http://127.0.0.1:11434"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
              />
              <p className="text-xs leading-relaxed text-muted-foreground">
                The server connects to this address. Changing it clears the test result and the
                default status: the credentials were tested against the old endpoint and say nothing
                about this one.
              </p>
            </div>
          )}

          {needsKey && (
            <div className="space-y-1.5">
              <Label htmlFor="edit-model-key">API key</Label>
              <Input
                id="edit-model-key"
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder="Leave blank to keep the stored key"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
              />
              <p className="text-xs leading-relaxed text-muted-foreground">
                {model.has_api_key
                  ? `Stored key ${model.api_key_fingerprint}, ${keySourceLabel(model)}. Leave this blank and it is kept exactly as it is.`
                  : 'No key is stored for this model yet, so it cannot be tested until one is.'}
              </p>
            </div>
          )}

          {onPlan && (
            <p className="text-xs leading-relaxed text-muted-foreground">
              This model runs on your ChatGPT plan, so it has no API key. Its credential is the
              sign-in in the ChatGPT subscription panel, and disconnecting there stops this model
              rather than anything typed here.
            </p>
          )}

          {needsKey && typedKey !== '' && (
            <div className="space-y-1.5 rounded-md border border-border p-3">
              <Label htmlFor="edit-model-key-scope">Store this key for</Label>
              <Select value={keyScope} onValueChange={(next) => setKeyScope(next as ApiKeyScope)}>
                <SelectTrigger id="edit-model-key-scope" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="provider">
                    Every {providerLabel(model.provider_kind)} model
                  </SelectItem>
                  <SelectItem value="model">This model only</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs leading-relaxed text-muted-foreground">
                One key normally serves every model of a provider, so saving at that scope replaces
                the credential the other {providerLabel(model.provider_kind)} models use as well.
                Choose this model only for a second account with the same provider.
              </p>
            </div>
          )}

          <div className="space-y-2">
            <ToggleRow
              id="edit-model-enabled"
              label="Enabled"
              hint="A disabled model is offered nowhere and cannot be the default."
              checked={enabled}
              onCheckedChange={setEnabled}
            />
            <ToggleRow
              id="edit-model-reasoning"
              label="Supports reasoning"
              hint="Lets a turn ask for a thinking effort."
              checked={supportsReasoning}
              onCheckedChange={setSupportsReasoning}
            />
            {supportsReasoning && (
              <div className="space-y-1.5 pl-1">
                <Label htmlFor="edit-model-effort">Default reasoning effort</Label>
                <Select value={effort} onValueChange={(next) => setEffort(next as ReasoningEffort)}>
                  <SelectTrigger id="edit-model-effort" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {REASONING_EFFORTS.map((value) => (
                      <SelectItem key={value} value={value} className="capitalize">
                        {value}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <ToggleRow
              id="edit-model-vision"
              label="Supports vision"
              hint="Lets a turn attach an image."
              checked={supportsVision}
              onCheckedChange={setSupportsVision}
            />
            <ToggleRow
              id="edit-model-tools"
              label="Unreliable at tool calling"
              hint="This agent is entirely tool driven, so mark a model that cannot be trusted with a function call."
              checked={toolsUnreliable}
              onCheckedChange={setToolsUnreliable}
            />
          </div>

          {error && (
            <p role="alert" className="flex items-start gap-1.5 text-sm text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>{error}</span>
            </p>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={save.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending || !hasChanges}>
              {save.isPending ? 'Saving' : 'Save changes'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

interface ToggleRowProps {
  id: string
  label: string
  hint: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}

/** One labelled switch, with the sentence that says what turning it on means. */
function ToggleRow({ id, label, hint, checked, onCheckedChange }: ToggleRowProps) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-md border p-3">
      <div className="min-w-0 space-y-0.5">
        <Label htmlFor={id} className="cursor-pointer">
          {label}
        </Label>
        <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  )
}

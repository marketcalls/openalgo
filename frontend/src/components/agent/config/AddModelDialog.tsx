/**
 * Register one model, and offer to test it before the operator walks away.
 *
 * Opened from the provider catalog with the provider kind and the model name
 * already filled in, and openable with neither so a model the catalog has never
 * heard of can still be added by hand. The catalog is advisory; the registry is
 * operator intent.
 *
 * Three rules shape this form:
 *
 *   * **The form refuses what the server would refuse.** `base_url` is required
 *     for `ollama` and `openai_compatible` and is never sent for anything else,
 *     and the same scheme, credential and metadata-address checks the route
 *     applies run here first. The server is not the right place for an operator
 *     to discover a typo.
 *   * **A key is write only and short lived.** It is typed into local state,
 *     sent once, and cleared the moment the row comes back. Nothing reads it
 *     again, nothing logs it, and the response carries only a fingerprint.
 *   * **A test is offered immediately.** A mistyped key should be discovered
 *     here, on the screen where it was pasted, rather than at the first chat
 *     message. The test is the cheapest real call the provider allows and its
 *     failure message is the provider's own, because "invalid API key" and
 *     "model not found" need different fixes.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useState } from 'react'
import {
  type AgentModel,
  type ApiKeyScope,
  agentErrorMessage,
  agentQueryKeys,
  type CreateModelPayload,
  createModel,
  listModels,
  type ModelTestResult,
  type ProviderKind,
  testModel,
} from '@/api/agent'
import { Alert, AlertDescription } from '@/components/ui/alert'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  isSubscriptionModel,
  SUBSCRIPTION_BADGE,
  suggestSubscriptionDisplayName,
} from '@/lib/agent/subscription'
import { cn } from '@/lib/utils'

/**
 * What each provider kind needs, mirroring `services/agent/providers.py`.
 *
 * The five kinds are a closed vocabulary on the server, so this list is
 * complete by construction rather than by maintenance: a sixth kind would be a
 * schema change, not a silent addition.
 */
interface ProviderKindSpec {
  value: ProviderKind
  label: string
  needsKey: boolean
  needsBaseUrl: boolean
  /** One line under the model name field, describing what to type there. */
  modelHint: string
}

const PROVIDER_KIND_SPECS: ProviderKindSpec[] = [
  {
    value: 'openai',
    label: 'OpenAI',
    needsKey: true,
    needsBaseUrl: false,
    modelHint: 'The model name on its own, for example gpt-4o.',
  },
  {
    value: 'anthropic',
    label: 'Anthropic',
    needsKey: true,
    needsBaseUrl: false,
    modelHint: 'The model name on its own, for example claude-sonnet-4-20250514.',
  },
  {
    value: 'ollama',
    label: 'Ollama, on your own machine',
    needsKey: false,
    needsBaseUrl: true,
    modelHint: 'The tag as Ollama lists it, for example llama3.1:8b.',
  },
  {
    value: 'openai_compatible',
    label: 'OpenAI-compatible endpoint',
    needsKey: true,
    needsBaseUrl: true,
    modelHint: 'The model name the endpoint serves, for example Qwen2.5-72B-Instruct.',
  },
  {
    value: 'litellm',
    label: 'Any other provider, through LiteLLM',
    needsKey: true,
    needsBaseUrl: false,
    modelHint: 'Include the provider prefix, for example groq/llama-3.3-70b-versatile.',
  },
]

const KIND_BY_VALUE = new Map(PROVIDER_KIND_SPECS.map((spec) => [spec.value as string, spec]))

/** The cloud metadata addresses the route refuses, refused here as well. */
const BLOCKED_BASE_URL_HOSTS = new Set([
  '169.254.169.254',
  'fd00:ec2::254',
  'metadata.google.internal',
  'metadata',
])

/**
 * Resolve the prefilled provider kind onto the closed vocabulary.
 *
 * @param value - The caller's suggestion, which is a plain string because the
 *   catalog serves it as one.
 * @returns The matching kind, or OpenAI when nothing was suggested.
 */
function resolveKind(value: string | undefined): ProviderKind {
  const spec = KIND_BY_VALUE.get((value ?? '').trim())
  return spec ? spec.value : 'openai'
}

/**
 * Suggest a display name from a model name.
 *
 * A suggestion only. It stays editable, and an empty one is allowed because the
 * server falls back to the model name itself.
 *
 * **A `chatgpt/` model gets its billing path in the name.** Eight of the ten
 * plan models share a bare name with an `openai` model, so the default
 * suggestion for `chatgpt/gpt-5.4` and for `openai/gpt-5.4` would otherwise be
 * the same two words, and an operator who accepted both defaults would end up
 * with two rows called GPT-5.4 that bill to different places. That is the exact
 * confusion this whole feature exists to prevent, and it is cheapest to prevent
 * at the moment the name is chosen.
 *
 * @param modelName - The model name, possibly carrying a provider prefix.
 * @returns A title-cased last path segment, or an empty string.
 */
function suggestDisplayName(modelName: string): string {
  if (isSubscriptionModel(modelName)) return suggestSubscriptionDisplayName(modelName)
  const last = modelName.split('/').pop() ?? modelName
  if (!last.trim()) return ''
  return last
    .split(/[-_]/)
    .map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word))
    .join(' ')
}

/**
 * Check an operator-supplied endpoint the way the route checks it.
 *
 * The server will make requests to this address, so this is an accident guard
 * rather than a defence against the operator, who already has server access. A
 * private or loopback host is allowed on purpose: a local Ollama is the entire
 * point of that provider kind.
 *
 * @param value - The typed base URL.
 * @returns A message describing the first problem, or null when it is usable.
 */
function baseUrlProblem(value: string): string | null {
  const url = value.trim()
  if (!url) return 'A base URL is required for this provider'
  if (!/^https?:\/\//i.test(url)) return 'The base URL must start with http:// or https://'

  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return 'The base URL could not be parsed'
  }
  if (parsed.username || parsed.password) {
    return 'The base URL must not carry a username or password'
  }
  const host = parsed.hostname
    .trim()
    .replace(/^\[|\]$/g, '')
    .toLowerCase()
    .replace(/\.$/, '')
  if (!host) return 'The base URL must name a host'
  if (BLOCKED_BASE_URL_HOSTS.has(host)) {
    return 'That address is the cloud metadata endpoint and cannot be used'
  }
  return null
}

export interface AddModelDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** The provider kind to start on, from the catalog card the operator opened. */
  providerKind?: string
  /** The model name to start on, stored exactly as typed. */
  modelName?: string
}

export function AddModelDialog({
  open,
  onOpenChange,
  providerKind,
  modelName,
}: AddModelDialogProps) {
  const queryClient = useQueryClient()
  // The page mounts this dialog more than once: the catalog panel owns one and
  // the page header owns another. Generated ids keep every label bound to its
  // own field rather than to whichever instance rendered first.
  const fieldId = useId()

  const [kind, setKind] = useState<ProviderKind>(() => resolveKind(providerKind))
  const [modelId, setModelId] = useState(modelName ?? '')
  const [displayName, setDisplayName] = useState(() => suggestDisplayName(modelName ?? ''))
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [scope, setScope] = useState<ApiKeyScope>('provider')
  const [formError, setFormError] = useState<string | null>(null)
  const [created, setCreated] = useState<AgentModel | null>(null)
  const [testResult, setTestResult] = useState<ModelTestResult | null>(null)

  // Every open starts clean, whoever opened it and whatever it was opened on
  // last time. A key must never survive a close, and a model name left over
  // from the previous provider would be registered against this one.
  useEffect(() => {
    if (!open) return
    setKind(resolveKind(providerKind))
    setModelId(modelName ?? '')
    setDisplayName(suggestDisplayName(modelName ?? ''))
    setBaseUrl('')
    setApiKey('')
    setScope('provider')
    setFormError(null)
    setCreated(null)
    setTestResult(null)
  }, [open, providerKind, modelName])

  // The registry answers one question this form needs: whether a shared key is
  // already stored for this provider kind, which is what makes leaving the key
  // field blank the right thing to do for the second model of a provider.
  const registered = useQuery({
    queryKey: agentQueryKeys.models(),
    queryFn: listModels,
    staleTime: 30_000,
    enabled: open,
  })

  const baseSpec = KIND_BY_VALUE.get(kind) ?? PROVIDER_KIND_SPECS[0]
  // A ChatGPT plan model is stored as `litellm`, whose spec wants a key, and it
  // is the one `litellm` model that cannot have one: it authenticates with the
  // OAuth session from the subscription panel. Offering the field would take a
  // value that is never read for this model and, at provider scope, silently
  // replace the shared LiteLLM key every other row of that kind runs on.
  //
  // Decided from the model name rather than the kind, because the name is what
  // carries the prefix and the operator types it here.
  const onPlan = isSubscriptionModel(modelId)
  const spec: ProviderKindSpec = onPlan ? { ...baseSpec, needsKey: false } : baseSpec
  const providerSecret = `provider:${kind}`
  const hasStoredProviderKey = (registered.data ?? []).some(
    (model) => model.has_api_key && model.api_key_source === providerSecret
  )

  const invalidate = (): void => {
    // models() is the list key and model(id) sits under it, so one call covers
    // both. status() moves too: a first model changes the setup gate.
    void queryClient.invalidateQueries({ queryKey: agentQueryKeys.models() })
    void queryClient.invalidateQueries({ queryKey: agentQueryKeys.status() })
  }

  const createMutation = useMutation({
    mutationFn: (payload: CreateModelPayload) => createModel(payload),
    onSettled: invalidate,
  })

  const testMutation = useMutation({
    mutationFn: (id: number) => testModel(id),
    onSettled: invalidate,
  })

  const validate = (): string | null => {
    if (!modelId.trim()) return 'A model name is required'
    if (spec.needsBaseUrl) {
      const problem = baseUrlProblem(baseUrl)
      if (problem) return problem
    }
    if (spec.needsKey && !apiKey.trim() && !hasStoredProviderKey) {
      return `${spec.label} needs an API key before this model can run. Paste one below.`
    }
    return null
  }

  const submit = async (): Promise<void> => {
    const problem = validate()
    if (problem) {
      setFormError(problem)
      return
    }
    setFormError(null)

    const payload: CreateModelPayload = {
      provider_kind: kind,
      model_name: modelId.trim(),
    }
    if (displayName.trim()) payload.display_name = displayName.trim()
    // Sent for the two kinds that need one, and for nothing else.
    if (spec.needsBaseUrl) payload.base_url = baseUrl.trim()
    if (apiKey.trim()) {
      payload.api_key = apiKey.trim()
      payload.api_key_scope = scope
    }

    try {
      const model = await createMutation.mutateAsync(payload)
      // The plaintext leaves component state as soon as it is stored. What
      // comes back describes the key with a fingerprint and nothing else.
      setApiKey('')
      setCreated(model)
    } catch (error) {
      setFormError(agentErrorMessage(error, 'The model could not be registered'))
    }
  }

  const runTest = async (): Promise<void> => {
    if (!created) return
    setTestResult(null)
    try {
      setTestResult(await testMutation.mutateAsync(created.id))
    } catch (error) {
      setTestResult({
        ok: false,
        message: agentErrorMessage(error, 'The test could not be run'),
        latency_ms: 0,
      })
    }
  }

  const addAnother = (): void => {
    setCreated(null)
    setTestResult(null)
    setModelId('')
    setDisplayName('')
    setApiKey('')
    setFormError(null)
    testMutation.reset()
    createMutation.reset()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{created ? 'Model registered' : 'Add a model'}</DialogTitle>
          <DialogDescription>
            {created
              ? 'Test it now so a mistyped key is found here rather than at the first message.'
              : 'The key is encrypted in your own OpenAlgo database and is never written to a configuration file.'}
          </DialogDescription>
        </DialogHeader>

        {created ? (
          <div className="space-y-4">
            <div className="rounded-lg border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{created.display_name}</span>
                <Badge variant="secondary">{created.provider_kind}</Badge>
                {isSubscriptionModel(created.model_name) ? (
                  <Badge variant="secondary">{SUBSCRIPTION_BADGE}</Badge>
                ) : null}
              </div>
              <p className="mt-1 font-mono text-xs text-muted-foreground">{created.model_name}</p>
              <p className="mt-2 text-xs text-muted-foreground">
                {isSubscriptionModel(created.model_name)
                  ? 'It runs on your ChatGPT plan sign-in, so there is no key to store.'
                  : created.has_api_key
                    ? `Key stored, shown only as ${created.api_key_fingerprint ?? 'a fingerprint'}.`
                    : 'No key is stored for this model yet.'}
              </p>
            </div>

            {testResult ? (
              <Alert
                variant={testResult.ok ? 'default' : 'destructive'}
                className={cn(
                  testResult.ok &&
                    'border-emerald-500 bg-emerald-50 text-emerald-900 dark:border-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-200'
                )}
              >
                <AlertDescription>
                  {testResult.ok
                    ? `Test passed in ${Math.round(testResult.latency_ms)} ms. ${testResult.message}.`
                    : testResult.message}
                </AlertDescription>
              </Alert>
            ) : null}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={addAnother}>
                Add another model
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={testMutation.isPending}
                onClick={() => {
                  void runTest()
                }}
              >
                {testMutation.isPending ? 'Testing' : 'Test now'}
              </Button>
              <Button type="button" onClick={() => onOpenChange(false)}>
                Done
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              void submit()
            }}
          >
            <div className="space-y-2">
              <Label htmlFor={`${fieldId}-kind`}>Provider kind</Label>
              <Select
                value={kind}
                onValueChange={(next) => {
                  setKind(next as ProviderKind)
                  setFormError(null)
                }}
              >
                <SelectTrigger id={`${fieldId}-kind`} className="w-full">
                  <SelectValue placeholder="Choose a provider kind" />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDER_KIND_SPECS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor={`${fieldId}-name`}>Model name</Label>
              <Input
                id={`${fieldId}-name`}
                value={modelId}
                autoComplete="off"
                spellCheck={false}
                aria-describedby={`${fieldId}-name-hint`}
                placeholder="Model name as the provider publishes it"
                onChange={(event) => {
                  const next = event.target.value
                  setModelId(next)
                  // A suggestion, and only while the operator has not written
                  // their own: retyping the model must not overwrite a name
                  // they chose.
                  if (!displayName || displayName === suggestDisplayName(modelId)) {
                    setDisplayName(suggestDisplayName(next))
                  }
                }}
              />
              <p id={`${fieldId}-name-hint`} className="text-xs text-muted-foreground">
                {spec.modelHint}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor={`${fieldId}-display`}>Display name</Label>
              <Input
                id={`${fieldId}-display`}
                value={displayName}
                autoComplete="off"
                aria-describedby={`${fieldId}-display-hint`}
                placeholder={modelId || 'Shown in the model picker'}
                onChange={(event) => setDisplayName(event.target.value)}
              />
              <p id={`${fieldId}-display-hint`} className="text-xs text-muted-foreground">
                What the chat picker shows. Left blank, the model name is used.
              </p>
            </div>

            {spec.needsBaseUrl ? (
              <div className="space-y-2">
                <Label htmlFor={`${fieldId}-base-url`}>Base URL</Label>
                <Input
                  id={`${fieldId}-base-url`}
                  type="url"
                  value={baseUrl}
                  autoComplete="off"
                  spellCheck={false}
                  aria-describedby={`${fieldId}-base-url-hint`}
                  placeholder="http://127.0.0.1:11434"
                  onChange={(event) => setBaseUrl(event.target.value)}
                />
                <p id={`${fieldId}-base-url-hint`} className="text-xs text-muted-foreground">
                  This server will connect to that address. A private or loopback address is fine,
                  which is what makes a local model possible.
                </p>
              </div>
            ) : null}

            {spec.needsKey ? (
              <>
                <div className="space-y-2">
                  <Label htmlFor={`${fieldId}-key`}>API key</Label>
                  <Input
                    id={`${fieldId}-key`}
                    type="password"
                    value={apiKey}
                    autoComplete="off"
                    spellCheck={false}
                    aria-describedby={`${fieldId}-key-hint`}
                    placeholder={
                      hasStoredProviderKey
                        ? 'Leave blank to reuse the stored key'
                        : 'Pasted once, stored encrypted, never shown again'
                    }
                    onChange={(event) => {
                      setApiKey(event.target.value)
                      setFormError(null)
                    }}
                  />
                  <p id={`${fieldId}-key-hint`} className="text-xs text-muted-foreground">
                    {hasStoredProviderKey
                      ? `A key is already stored for ${spec.label}. Leave this blank to reuse it.`
                      : 'Stored encrypted in your own database. It is never returned by any endpoint, not even masked.'}
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor={`${fieldId}-scope`}>Key applies to</Label>
                  <Select value={scope} onValueChange={(next) => setScope(next as ApiKeyScope)}>
                    <SelectTrigger id={`${fieldId}-scope`} className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="provider">Every model of this provider</SelectItem>
                      <SelectItem value="model">This model only</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    {scope === 'provider'
                      ? 'One paste serves every model of this provider, so adding a second one needs no key at all.'
                      : 'An override for a second account with the same provider. It wins over the shared key.'}
                  </p>
                  {scope === 'provider' && hasStoredProviderKey && apiKey.trim() ? (
                    <p className="text-xs text-muted-foreground">
                      Saving this replaces the stored key for every model of this provider.
                    </p>
                  ) : null}
                </div>
              </>
            ) : onPlan ? (
              // Not the same sentence as a local model. A ChatGPT plan model
              // takes no key but every token still reaches OpenAI, so saying
              // "nothing leaves this machine" here would be false.
              <p className="text-xs text-muted-foreground">
                This model runs on your ChatGPT Plus or Pro plan, so it takes no API key. Connect
                the plan in the ChatGPT subscription panel on this page; turns on it are covered by
                the plan rather than billed against API credits.
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                This provider takes no API key, and nothing leaves this machine to reach it.
              </p>
            )}

            {formError ? (
              <Alert variant="destructive">
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            ) : null}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? 'Adding' : 'Add model'}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

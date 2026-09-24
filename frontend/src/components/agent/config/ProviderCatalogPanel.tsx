/**
 * Browse the provider catalog and register models from it.
 *
 * The catalog is read from LiteLLM's own in-package data at request time, so
 * there is no catalog table, no generated frontend constant and nothing to keep
 * in sync: bumping `litellm` is the entire maintenance story, and a provider a
 * future release adds appears here on its own. Nothing in this file hardcodes a
 * model, a price or a context window.
 *
 * Two shaping facts:
 *
 *   * **Around 94 chat providers is too many for a flat list.** The grid is
 *     searchable and the providers a trader actually reaches for lead it. The
 *     rest keep the server's own display-name order behind them, so nothing is
 *     hidden, it is only ranked.
 *   * **`supports_function_calling` is load-bearing, not decoration.** This
 *     agent is entirely tool-driven, so a model that cannot call a function
 *     cannot drive it. A model known not to support it is greyed with the
 *     reason rather than quietly listed, a model nobody has priced says so
 *     rather than claiming zero, and the list can be filtered down to models
 *     that do support it.
 *
 * What the operator already has is read from the registry, never from a second
 * source of truth: a provider shows how many of its models are registered and
 * whether a key is stored, both derived from `GET /agent/api/models`.
 */

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Plus, RefreshCw, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  type AgentModel,
  agentErrorMessage,
  agentQueryKeys,
  type CatalogModel,
  type CatalogProvider,
  listCatalogModels,
  listModels,
  listProviders,
} from '@/api/agent'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { CHATGPT_PROVIDER_ID, isSubscriptionModel } from '@/lib/agent/subscription'
import { cn } from '@/lib/utils'
import { AddModelDialog } from './AddModelDialog'
import { ProviderIcon } from './providerIcon'

/**
 * The providers a trader reaches for, in the order they are offered.
 *
 * A ranking, not a filter: an id absent from the catalog simply does not
 * appear, and everything not named here follows in the server's own
 * display-name order. Ollama is high on the list on purpose, because it is the
 * one provider that sends nothing off this machine.
 */
const PINNED_PROVIDER_IDS = [
  'openai',
  'anthropic',
  'gemini',
  'xai',
  'groq',
  'deepseek',
  'mistral',
  'openrouter',
  'ollama',
  'together_ai',
  'perplexity',
  'fireworks_ai',
  'cerebras',
  'azure',
  'bedrock',
  'vertex_ai',
  'lm_studio',
  'vllm',
]

const PINNED_RANK = new Map(PINNED_PROVIDER_IDS.map((id, index) => [id, index]))

/** How many model rows are rendered before the operator asks for more. */
const MODEL_PAGE_SIZE = 40

/**
 * How many provider cards are rendered before the operator asks for more.
 *
 * LiteLLM lists 93 chat providers, which is six full screens of cards at four
 * to a row, and web search sits under this panel on the settings page. Drawn in
 * full it puts that section three viewports below the fold. Nothing is hidden:
 * the search box filters the whole list, and the count line always names it.
 */
const PROVIDER_PAGE_SIZE = 24

/**
 * The registered models that belong to a catalog provider.
 *
 * Deliberately a heuristic, and used for nothing but a count on a card. A
 * `litellm` model carries its provider prefix in the stored name, so those
 * match exactly; every other kind matches on the kind alone, which means the
 * several catalog providers that map onto `openai_compatible` each claim the
 * same rows. That is honest for a badge and is not a security decision.
 *
 * @param provider - The catalog provider.
 * @param models - Every registered model.
 * @returns The registered models that plausibly belong to this provider.
 */
function registeredForProvider(provider: CatalogProvider, models: AgentModel[]): AgentModel[] {
  return models.filter((model) => {
    if (model.provider_kind !== provider.provider_kind) return false
    if (provider.provider_kind === 'litellm') return model.model_name.startsWith(`${provider.id}/`)
    return true
  })
}

/**
 * Whether a shared key is stored for this provider's kind.
 *
 * The signal is the registry, which describes every key by source and
 * fingerprint and never by value. The shared secret is keyed by provider kind,
 * so this answers for the kind rather than for the catalog id, which is exactly
 * what the key itself does.
 *
 * @param provider - The catalog provider.
 * @param models - Every registered model.
 * @returns True when some registered model of this kind uses the shared key.
 */
function hasProviderKey(provider: CatalogProvider, models: AgentModel[]): boolean {
  const source = `provider:${provider.provider_kind}`
  return models.some((model) => model.has_api_key && model.api_key_source === source)
}

/**
 * The name a model is stored under once registered.
 *
 * A `litellm` model is passed to LiteLLM verbatim and therefore carries its own
 * provider prefix; every other kind applies the prefix itself and stores the
 * bare name.
 *
 * @param provider - The catalog provider the model was listed under.
 * @param model - The catalog model.
 * @returns The value that belongs in `ag_provider_model.model_name`.
 */
function storedModelName(provider: CatalogProvider, model: CatalogModel): string {
  return provider.provider_kind === 'litellm' ? model.qualified_id : model.id
}

/**
 * Render a context window.
 *
 * @param tokens - The window in tokens, or null when the catalog has no entry.
 * @returns A short label, or null when there is nothing to say.
 */
function formatTokenWindow(tokens: number | null): string | null {
  if (tokens === null || !Number.isFinite(tokens) || tokens <= 0) return null
  if (tokens >= 1_000_000) {
    const millions = tokens / 1_000_000
    return `${Number.isInteger(millions) ? millions : millions.toFixed(1)}M context`
  }
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}k context`
  return `${tokens} context`
}

/**
 * Render one side of a price.
 *
 * @param value - USD per million tokens, or null when unpriced.
 * @returns A dollar string, or null when the catalog has no price.
 */
function formatPricePerMillion(value: number | null): string | null {
  if (value === null || !Number.isFinite(value)) return null
  if (value === 0) return 'free'
  if (value >= 1) return `$${value.toFixed(2)}`
  return `$${value.toFixed(3)}`
}

/**
 * Render both sides of a price.
 *
 * A missing price reads as unknown, never as zero: the catalog not knowing a
 * price and a model being free are different facts and only one of them is
 * safe to assume.
 *
 * A ChatGPT plan model is the third case, and it is the one this whole section
 * is here to make visible. LiteLLM prices `gpt-5.4` and deliberately prices
 * nothing under `chatgpt/`, because a plan turn has no per-token price at all.
 * Reporting that as "price unknown" would put a `chatgpt/gpt-5.4` row and an
 * obscure unpriced model in the same category when they are nothing alike.
 *
 * @param model - The catalog model.
 * @returns A price label for the row.
 */
function priceLabel(model: CatalogModel): string {
  if (isSubscriptionModel(model.qualified_id) || isSubscriptionModel(model.id)) {
    return 'covered by your ChatGPT plan'
  }
  const input = formatPricePerMillion(model.input_price_per_million)
  const output = formatPricePerMillion(model.output_price_per_million)
  if (input === null && output === null) return 'price unknown'
  return `${input ?? 'unknown'} in / ${output ?? 'unknown'} out per 1M`
}

/** What the operator asked to register, in the form the dialog takes. */
interface AddTarget {
  providerKind: string
  modelName?: string
}

export function ProviderCatalogPanel() {
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [addTarget, setAddTarget] = useState<AddTarget | null>(null)
  const [visibleProviders, setVisibleProviders] = useState(PROVIDER_PAGE_SIZE)

  const providers = useQuery({
    queryKey: agentQueryKeys.providers(),
    queryFn: listProviders,
    // LiteLLM's data is a package constant, so this cannot go stale within a
    // session. It is refetched when the page is reopened, which is when a
    // package bump would have taken effect.
    staleTime: 10 * 60_000,
  })

  const registered = useQuery({
    queryKey: agentQueryKeys.models(),
    queryFn: listModels,
    staleTime: 30_000,
  })

  const catalog = providers.data?.data ?? []
  const registeredModels = registered.data ?? []
  const catalogAvailable = providers.data?.available !== false

  const ranked = useMemo(() => {
    const term = query.trim().toLowerCase()
    const matched = term
      ? catalog.filter(
          (provider) =>
            provider.display_name.toLowerCase().includes(term) ||
            provider.id.toLowerCase().includes(term)
        )
      : catalog
    // A stable sort over the server's own display-name order, so the pinned
    // providers lead and everything else keeps the order it arrived in.
    return [...matched].sort(
      (left, right) =>
        (PINNED_RANK.get(left.id) ?? PINNED_RANK.size) -
        (PINNED_RANK.get(right.id) ?? PINNED_RANK.size)
    )
  }, [catalog, query])

  // A narrowed search must show its matches from the top, not from wherever the
  // previous "show more" had scrolled the page to.
  const shownProviders = ranked.slice(0, visibleProviders)

  const selected = catalog.find((provider) => provider.id === selectedId) ?? null

  return (
    <section aria-labelledby="agent-provider-catalog-heading" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="agent-provider-catalog-heading" className="text-base font-semibold">
            Providers
          </h2>
          <p className="text-sm text-muted-foreground">
            Read from LiteLLM itself, so upgrading the package brings new providers and models with
            it. Pick a provider to see its models, their context window, their price and whether
            they can call tools.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setAddTarget({ providerKind: 'openai' })}
          >
            <Plus aria-hidden="true" />
            Add a model by hand
          </Button>
        </div>
      </div>

      {providers.isError ? (
        <Alert variant="destructive">
          <AlertTitle>The provider catalog could not be loaded</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            <span>{agentErrorMessage(providers.error, 'The request failed')}</span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void providers.refetch()
              }}
            >
              <RefreshCw aria-hidden="true" />
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {!providers.isPending && !providers.isError && !catalogAvailable ? (
        <Alert variant="warning">
          <AlertTitle>LiteLLM is not installed on this server</AlertTitle>
          <AlertDescription>
            The catalog is advisory, so the agent still runs a model you name yourself. Use Add a
            model by hand above, and install litellm to get the browsable list back.
          </AlertDescription>
        </Alert>
      ) : null}

      {providers.isPending ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((slot) => (
            <Skeleton key={slot} className="h-[104px] w-full" />
          ))}
        </div>
      ) : null}

      {!providers.isPending && catalogAvailable && selected === null ? (
        <>
          <div className="max-w-sm space-y-2">
            <Label htmlFor="agent-provider-search" className="sr-only">
              Search providers
            </Label>
            <Input
              id="agent-provider-search"
              type="search"
              value={query}
              autoComplete="off"
              placeholder="Search providers"
              onChange={(event) => {
                setQuery(event.target.value)
                setVisibleProviders(PROVIDER_PAGE_SIZE)
              }}
            />
          </div>

          {ranked.length === 0 ? (
            <EmptyState
              icon={Search}
              title="No provider matches that search"
              description="Try a shorter term, or add a model by hand if the provider is not listed."
            />
          ) : (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {shownProviders.map((provider) => {
                  const owned = registeredForProvider(provider, registeredModels)
                  const keyed = hasProviderKey(provider, registeredModels)
                  return (
                    <button
                      key={provider.id}
                      type="button"
                      onClick={() => setSelectedId(provider.id)}
                      className="flex w-full flex-col items-start gap-2 rounded-lg border bg-card p-3 text-left transition-colors hover:bg-accent/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
                    >
                      <div className="flex w-full items-start justify-between gap-2">
                        <ProviderIcon provider={provider.icon || provider.id} />
                        {owned.length > 0 ? (
                          <Badge variant="secondary">{owned.length} added</Badge>
                        ) : null}
                      </div>
                      <span className="text-sm font-medium">{provider.display_name}</span>
                      <div className="flex flex-wrap gap-1">
                        <Badge variant="outline" className="font-normal">
                          {provider.model_count} models
                        </Badge>
                        {keyed ? (
                          <Badge variant="outline" className="font-normal">
                            key stored
                          </Badge>
                        ) : null}
                        {provider.id === CHATGPT_PROVIDER_ID ? (
                          <Badge variant="outline" className="font-normal">
                            runs on your plan
                          </Badge>
                        ) : !provider.needs_key ? (
                          <Badge variant="outline" className="font-normal">
                            no key needed
                          </Badge>
                        ) : null}
                        {provider.needs_base_url ? (
                          <Badge variant="outline" className="font-normal">
                            needs a URL
                          </Badge>
                        ) : null}
                      </div>
                    </button>
                  )
                })}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-xs text-muted-foreground">
                  Showing {shownProviders.length} of {ranked.length} chat providers
                  {ranked.length === catalog.length
                    ? '.'
                    : ` matching that search, out of ${catalog.length}.`}
                </p>
                {visibleProviders < ranked.length ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setVisibleProviders((count) => count + PROVIDER_PAGE_SIZE)}
                  >
                    Show more providers
                  </Button>
                ) : null}
              </div>
            </>
          )}
        </>
      ) : null}

      {selected !== null ? (
        <ProviderDetail
          key={selected.id}
          provider={selected}
          registered={registeredModels}
          onBack={() => setSelectedId(null)}
          onAdd={(modelName) => setAddTarget({ providerKind: selected.provider_kind, modelName })}
        />
      ) : null}

      <AddModelDialog
        open={addTarget !== null}
        onOpenChange={(open) => {
          if (!open) setAddTarget(null)
        }}
        providerKind={addTarget?.providerKind}
        modelName={addTarget?.modelName}
      />
    </section>
  )
}

interface ProviderDetailProps {
  provider: CatalogProvider
  registered: AgentModel[]
  onBack: () => void
  onAdd: (modelName?: string) => void
}

/**
 * One provider's models.
 *
 * Mounted with the provider id as its key, so switching providers starts with a
 * clean filter and a clean page count rather than carrying the previous
 * provider's search into a different list.
 */
function ProviderDetail({ provider, registered, onBack, onAdd }: ProviderDetailProps) {
  const [search, setSearch] = useState('')
  const [toolsOnly, setToolsOnly] = useState(false)
  const [visible, setVisible] = useState(MODEL_PAGE_SIZE)

  const models = useQuery({
    queryKey: agentQueryKeys.catalogModels(provider.id, true),
    queryFn: () => listCatalogModels(provider.id, true),
    staleTime: 10 * 60_000,
  })

  const all = models.data?.data ?? []

  const owned = useMemo(
    () =>
      new Set(
        registered
          .filter((model) => model.provider_kind === provider.provider_kind)
          .map((model) => model.model_name)
      ),
    [registered, provider.provider_kind]
  )

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    return all.filter((model) => {
      if (toolsOnly && model.supports_function_calling !== true) return false
      if (term && !model.id.toLowerCase().includes(term)) return false
      return true
    })
  }, [all, search, toolsOnly])

  const shown = filtered.slice(0, visible)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft aria-hidden="true" />
          All providers
        </Button>
        <ProviderIcon provider={provider.icon || provider.id} />
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{provider.display_name}</h3>
          <p className="text-xs text-muted-foreground">
            <span className="font-mono">{provider.id}</span>
            {provider.id === CHATGPT_PROVIDER_ID
              ? ', signed in with your ChatGPT plan rather than an API key'
              : provider.needs_key
                ? ', needs an API key'
                : ', needs no API key'}
            {provider.needs_base_url ? ', needs a base URL' : ''}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ml-auto"
          onClick={() => onAdd(undefined)}
        >
          <Plus aria-hidden="true" />
          Model not listed
        </Button>
      </div>

      {provider.id === CHATGPT_PROVIDER_ID ? (
        <Alert>
          <AlertTitle>These bill to your plan, not to API credits</AlertTitle>
          <AlertDescription>
            Most of these models also exist under OpenAI with the same name and a per-token price.
            The two are told apart by the prefix, so a model added from here is stored as{' '}
            <span className="font-mono">chatgpt/</span> and the suggested display name says so.
            Connect the plan in the ChatGPT subscription panel above before adding one; without a
            sign-in these models cannot run.
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="flex flex-wrap items-center gap-4">
        <div className="min-w-[16rem] flex-1 space-y-2">
          <Label htmlFor="agent-model-search" className="sr-only">
            Search models from this provider
          </Label>
          <Input
            id="agent-model-search"
            type="search"
            value={search}
            autoComplete="off"
            placeholder="Search models"
            onChange={(event) => {
              setSearch(event.target.value)
              setVisible(MODEL_PAGE_SIZE)
            }}
          />
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            id="agent-model-tools-only"
            checked={toolsOnly}
            onCheckedChange={(checked) => {
              setToolsOnly(checked === true)
              setVisible(MODEL_PAGE_SIZE)
            }}
          />
          <Label htmlFor="agent-model-tools-only" className="text-sm font-normal">
            Only models that can call tools
          </Label>
        </div>
      </div>

      {models.isError ? (
        <Alert variant="destructive">
          <AlertTitle>This provider models could not be loaded</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            <span>{agentErrorMessage(models.error, 'The request failed')}</span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void models.refetch()
              }}
            >
              <RefreshCw aria-hidden="true" />
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {models.isPending ? (
        <div className="space-y-2">
          {[0, 1, 2, 3, 4].map((slot) => (
            <Skeleton key={slot} className="h-14 w-full" />
          ))}
        </div>
      ) : null}

      {!models.isPending && !models.isError && filtered.length === 0 ? (
        <EmptyState
          icon={Search}
          title={all.length === 0 ? 'No models are listed for this provider' : 'No model matches'}
          description={
            all.length === 0
              ? 'The catalog is advisory. Use Model not listed to register one by name.'
              : 'Clear the search or the tool-calling filter, or register a model by name.'
          }
        />
      ) : null}

      {shown.length > 0 ? (
        <>
          <ul className="divide-y rounded-lg border">
            {shown.map((model) => {
              const stored = storedModelName(provider, model)
              const already = owned.has(stored)
              const noTools = model.supports_function_calling === false
              const context = formatTokenWindow(model.max_input_tokens)
              return (
                <li
                  key={model.id}
                  className={cn(
                    'flex flex-wrap items-center justify-between gap-3 px-3 py-2',
                    noTools && 'opacity-60'
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-sm">{model.id}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      {context ? <span>{context}</span> : null}
                      <span>{priceLabel(model)}</span>
                      {model.supports_function_calling === true ? (
                        <Badge variant="secondary" className="font-normal">
                          tool calling
                        </Badge>
                      ) : null}
                      {model.supports_function_calling === false ? (
                        <Badge variant="outline" className="font-normal">
                          cannot call tools, so it cannot drive this agent
                        </Badge>
                      ) : null}
                      {model.supports_function_calling === null ? (
                        <Badge variant="outline" className="font-normal">
                          tool support unknown
                        </Badge>
                      ) : null}
                      {model.supports_vision === true ? (
                        <Badge variant="outline" className="font-normal">
                          vision
                        </Badge>
                      ) : null}
                    </div>
                  </div>
                  {already ? (
                    <Badge variant="secondary">Added</Badge>
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      aria-label={`Add ${model.id}`}
                      onClick={() => onAdd(stored)}
                    >
                      <Plus aria-hidden="true" />
                      Add
                    </Button>
                  )}
                </li>
              )
            })}
          </ul>
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs text-muted-foreground">
              Showing {shown.length} of {filtered.length} models.
            </p>
            {visible < filtered.length ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setVisible((count) => count + MODEL_PAGE_SIZE)}
              >
                Show more models
              </Button>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  )
}

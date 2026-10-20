/**
 * The model and reasoning control for a conversation.
 *
 * One trigger, reading `GPT-5.6 Luna  High`, because it is one decision: which
 * model, and how hard it thinks about the next message.
 *
 * **Reasoning is the primary menu and the model is a submenu**, which is the
 * inverse of what it first looks like it should be. The model is chosen once
 * and then rarely; effort changes constantly, because it belongs to the
 * question rather than to the model. "What is the LTP of INFY" wants none of
 * it and "which of these three structures carries less risk" wants all of it,
 * asked of the same model minutes apart. Putting effort one click away and the
 * model two matches how often each is touched.
 *
 * **`Default` sends no override at all.** It leaves the model row's own effort
 * in force rather than transmitting a value meaning off, so a model registered
 * as `high` keeps thinking hard until the operator says otherwise on a
 * specific turn.
 *
 * It offers every **enabled** model, which is the same set the backend will
 * accept: a disabled or missing model is a typed error from the stream route
 * rather than a silent fall-through, so offering one here would only produce a
 * failed turn. A change applies to the **next** turn; nothing about a running
 * turn moves, because the model was resolved before the first stream byte.
 *
 * The configured default is marked rather than assumed: leaving the picker
 * alone sends no `model_id` and the server resolves its own default, so the
 * label has to say which row that is.
 */

import { useQuery } from '@tanstack/react-query'
import { ChevronDown, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { type AgentModel, agentQueryKeys, listModels, type ReasoningEffort } from '@/api/agent'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { isSubscriptionModel, SUBSCRIPTION_BADGE } from '@/lib/agent/subscription'
import { cn } from '@/lib/utils'

/** Effort levels offered per turn, in the order shown. */
const EFFORTS: Array<{ value: ReasoningEffort; label: string; hint: string }> = [
  { value: 'off', label: 'Default', hint: "the model's own" },
  { value: 'low', label: 'Low', hint: 'fastest' },
  { value: 'medium', label: 'Medium', hint: 'balanced' },
  { value: 'high', label: 'High', hint: 'deepest' },
]

/** Above this many models the submenu grows a search box. */
const SEARCH_THRESHOLD = 6

function effortLabel(effort: ReasoningEffort): string {
  return EFFORTS.find((item) => item.value === effort)?.label ?? 'Default'
}

export interface ModelPickerProps {
  /** The chosen model, or null to run on the configured default. */
  value: number | null
  onChange: (modelId: number | null) => void
  /**
   * Reasoning effort for the NEXT message. `off` sends no override, leaving
   * the model row's own default in force.
   */
  effort?: ReasoningEffort
  onEffortChange?: (effort: ReasoningEffort) => void
  disabled?: boolean
  className?: string
}

function Placeholder({ text, className }: { text: string; className?: string }) {
  return (
    <div
      className={cn(
        'flex h-8 items-center rounded-md border border-input px-3 text-xs text-muted-foreground',
        className
      )}
    >
      {text}
    </div>
  )
}

export function ModelPicker({
  value,
  onChange,
  effort = 'off',
  onEffortChange,
  disabled = false,
  className,
}: ModelPickerProps) {
  const [query, setQuery] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: agentQueryKeys.models(),
    queryFn: listModels,
    staleTime: 60_000,
  })

  const models: AgentModel[] = useMemo(() => (data ?? []).filter((model) => model.enabled), [data])
  const defaultModel = models.find((model) => model.is_default) ?? null
  // Null means "whatever the server calls default", so the trigger shows that
  // row rather than an empty box the operator has to interpret.
  const selectedId = value ?? defaultModel?.id ?? null
  const selected = models.find((model) => model.id === selectedId) ?? defaultModel

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return models
    return models.filter((model) =>
      `${model.display_name} ${model.model_name} ${model.provider_kind}`
        .toLowerCase()
        .includes(needle)
    )
  }, [models, query])

  if (isLoading) return <Placeholder text="Loading models" className={className} />
  if (models.length === 0) return <Placeholder text="No enabled model" className={className} />

  const selectedLabel = selected?.display_name || selected?.model_name || 'Select a model'
  const selectedOnPlan = isSubscriptionModel(selected?.model_name)
  const showSearch = models.length > SEARCH_THRESHOLD
  // Not every model thinks. GPT-4 and GPT-4o take no reasoning effort, and the
  // backend refuses to send one for them whatever is asked, so offering the
  // menu would be a control that silently does nothing. The row's flag is
  // resolved against LiteLLM's own table on the server, so this is the same
  // answer the run will act on rather than a second opinion.
  const canReason = selected?.supports_reasoning ?? false
  const showEffort = Boolean(onEffortChange) && canReason

  const modelList = (
    <>
      {showSearch && (
        <div className="flex items-center gap-2 border-b border-border px-2 py-1.5">
          <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search all models"
            aria-label="Search models"
            className="h-7 border-none px-0 text-xs shadow-none focus-visible:ring-0"
            // The menu treats typing as type-ahead navigation and would steal
            // these keys, so the field has to claim them while it has focus.
            onKeyDown={(event) => event.stopPropagation()}
          />
        </div>
      )}
      <DropdownMenuRadioGroup
        value={selectedId === null ? '' : String(selectedId)}
        onValueChange={(next) => {
          const parsed = Number(next)
          onChange(Number.isFinite(parsed) ? parsed : null)
        }}
      >
        {filtered.map((model) => (
          <DropdownMenuRadioItem key={model.id} value={String(model.id)} className="text-xs">
            <span className="flex min-w-0 flex-1 items-center gap-2">
              <span className="truncate">{model.display_name || model.model_name}</span>
              {/* Two rows here can carry the same display name and bill to
                  different places, because eight of the ten chatgpt/ models
                  share a bare name with an openai/ one. A turn should never be
                  ambiguous about which billing path it took, and this is the
                  moment the operator chooses it. */}
              {isSubscriptionModel(model.model_name) && (
                <span
                  className="shrink-0 rounded bg-muted px-1 py-px text-[10px] text-muted-foreground"
                  title="Runs on your ChatGPT Plus or Pro plan, not on API credits."
                >
                  {SUBSCRIPTION_BADGE}
                </span>
              )}
              {model.is_default && (
                <span className="shrink-0 rounded bg-muted px-1 py-px text-[10px] text-muted-foreground">
                  default
                </span>
              )}
              {/* Each row carries its own configured effort, so switching model
                  does not silently change how hard the next answer thinks. */}
              <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                {effortLabel(model.default_reasoning_effort)}
              </span>
            </span>
          </DropdownMenuRadioItem>
        ))}
        {filtered.length === 0 && (
          <p className="px-2 py-3 text-center text-xs text-muted-foreground">
            No model matches that.
          </p>
        )}
      </DropdownMenuRadioGroup>
    </>
  )

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={cn('h-8 w-auto gap-1.5 px-2.5 text-xs font-normal', className)}
          aria-label={
            selectedOnPlan
              ? `Model ${selectedLabel}, on your ChatGPT plan, reasoning ${effortLabel(effort)}. Change either.`
              : `Model ${selectedLabel}, reasoning ${effortLabel(effort)}. Change either.`
          }
          title={
            selectedOnPlan
              ? 'The next turn runs on your ChatGPT Plus or Pro plan rather than on API credits.'
              : undefined
          }
        >
          <span className="max-w-[12rem] truncate">{selectedLabel}</span>
          {/* On the trigger, not only in the menu. This is the last thing shown
              before a question is sent, and it is the only place the billing
              path of the turn about to run is visible. */}
          {selectedOnPlan && <span className="shrink-0 text-muted-foreground">on plan</span>}
          {showEffort && (
            <span className="shrink-0 text-muted-foreground">{effortLabel(effort)}</span>
          )}
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden />
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="min-w-[13rem]">
        {showEffort ? (
          <>
            <DropdownMenuLabel className="text-[11px] tracking-wide text-muted-foreground uppercase">
              Reasoning effort
            </DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={effort}
              onValueChange={(next) => onEffortChange?.(next as ReasoningEffort)}
            >
              {EFFORTS.map((item) => (
                <DropdownMenuRadioItem key={item.value} value={item.value} className="text-xs">
                  <span className="flex min-w-0 flex-1 items-center gap-2">
                    <span className="truncate">{item.label}</span>
                    <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                      {item.hint}
                    </span>
                  </span>
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>

            <DropdownMenuSeparator />

            {/* The model sits behind one more click than effort, deliberately.
                See the module docstring: it is chosen far less often. */}
            <DropdownMenuSub>
              <DropdownMenuSubTrigger className="text-xs">
                <span className="flex min-w-0 flex-1 items-center gap-2">
                  <span>Model</span>
                  <span className="ml-auto max-w-[8rem] shrink-0 truncate text-muted-foreground">
                    {selectedLabel}
                  </span>
                </span>
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent className="min-w-[15rem] p-0">
                {modelList}
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          </>
        ) : (
          <>
            <DropdownMenuLabel className="text-[11px] tracking-wide text-muted-foreground uppercase">
              Model
            </DropdownMenuLabel>
            {modelList}
            {Boolean(onEffortChange) && !canReason && (
              <>
                <DropdownMenuSeparator />
                <p className="px-2 py-1.5 text-[11px] text-muted-foreground">
                  {selectedLabel} does not take a reasoning effort. Pick a reasoning model to
                  control how hard it thinks.
                </p>
              </>
            )}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

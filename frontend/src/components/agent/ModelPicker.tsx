/**
 * The model picker for a conversation.
 *
 * It offers every **enabled** model in the registry, which is the same set the
 * backend will accept: a disabled or missing model is a typed error from the
 * stream route rather than a silent fall-through to the default, so offering
 * one here would only produce a failed turn.
 *
 * A change applies to the **next** turn. Nothing about a running turn moves,
 * because the model was resolved before the first stream byte was written.
 *
 * The configured default is marked rather than assumed: leaving the picker
 * alone sends no `model_id` at all and the server resolves its own default, so
 * the label has to say which row that is.
 */

import { useQuery } from '@tanstack/react-query'
import { type AgentModel, agentQueryKeys, listModels } from '@/api/agent'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

export interface ModelPickerProps {
  /** The chosen model, or null to run on the configured default. */
  value: number | null
  onChange: (modelId: number | null) => void
  disabled?: boolean
  className?: string
}

export function ModelPicker({ value, onChange, disabled = false, className }: ModelPickerProps) {
  const { data, isLoading } = useQuery({
    queryKey: agentQueryKeys.models(),
    queryFn: listModels,
    staleTime: 60_000,
  })

  const models: AgentModel[] = (data ?? []).filter((model) => model.enabled)
  const defaultModel = models.find((model) => model.is_default) ?? null
  // Null means "whatever the server calls default", so the trigger shows that
  // row rather than an empty box the operator has to interpret.
  const selectedId = value ?? defaultModel?.id ?? null

  if (isLoading) {
    return (
      <div
        className={cn(
          'flex h-8 items-center rounded-md border border-input px-3 text-xs text-muted-foreground',
          className
        )}
      >
        Loading models
      </div>
    )
  }

  if (models.length === 0) {
    return (
      <div
        className={cn(
          'flex h-8 items-center rounded-md border border-input px-3 text-xs text-muted-foreground',
          className
        )}
      >
        No enabled model
      </div>
    )
  }

  return (
    <Select
      value={selectedId === null ? undefined : String(selectedId)}
      onValueChange={(next) => {
        const parsed = Number(next)
        onChange(Number.isFinite(parsed) ? parsed : null)
      }}
      disabled={disabled}
    >
      <SelectTrigger size="sm" className={cn('h-8 w-auto min-w-[10rem] gap-2 text-xs', className)}>
        <SelectValue placeholder="Select a model" />
      </SelectTrigger>
      <SelectContent position="popper" align="end">
        {models.map((model) => (
          <SelectItem key={model.id} value={String(model.id)} className="text-xs">
            <span className="flex items-center gap-2">
              <span className="truncate">{model.display_name || model.model_name}</span>
              {model.is_default && (
                <span className="shrink-0 text-[10px] text-muted-foreground">default</span>
              )}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

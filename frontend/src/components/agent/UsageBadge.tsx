/**
 * Per-turn and per-conversation token usage.
 *
 * Quiet by design: it sits under an answer the operator is reading, so it is
 * small, muted and never competes with the prose above it.
 *
 * The one rule that is not cosmetic: **`cost_usd` null renders as a dash, never
 * as zero.** The backend computes cost locally from LiteLLM's price table and
 * reports null for a model that table has no entry for. Showing tokens and
 * admitting the price is unknown beats inventing a number, and a rendered $0.00
 * is exactly the invented number that would make an expensive turn look free.
 * The dash carries a title saying why.
 *
 * The conversation total follows from that: turns with a known price are summed
 * and a total that had at least one unpriced turn says so, rather than quietly
 * under-reporting.
 */

import type { AgentUsage } from '@/lib/agent/useAgentStream'
import { cn } from '@/lib/utils'

/** What a model with no published price renders as, in place of a number. */
const UNKNOWN_COST = '-'

const UNKNOWN_COST_TITLE =
  'This model has no published price in the catalog, so the cost is unknown. It is not zero.'

const tokenFormatter = new Intl.NumberFormat('en-US')

/**
 * Render a token count with thousands separators.
 *
 * @param value - A token count, which may be missing on a partial usage frame.
 * @returns The formatted count, or '0' when there is no number to show.
 */
export function formatTokens(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '0'
  return tokenFormatter.format(Math.round(value))
}

/**
 * Render a cost in dollars, or the unknown marker.
 *
 * Small costs keep four decimals because a turn frequently costs less than a
 * cent and rounding it to two would print $0.00 for money that was really
 * spent, which is the same lie as reporting an unknown price as zero.
 *
 * @param cost - Dollars, or null when the model has no published price.
 * @returns A dollar string, or a dash for an unknown price.
 */
export function formatCost(cost: number | null | undefined): string {
  if (typeof cost !== 'number' || !Number.isFinite(cost)) return UNKNOWN_COST
  if (cost === 0) return '$0.00'
  if (cost >= 1) return `$${cost.toFixed(2)}`
  return `$${cost.toFixed(4)}`
}

/** A conversation's running total, with the honesty of its cost recorded. */
export interface UsageTotals {
  /** How many turns contributed usage at all. */
  turns: number
  inputTokens: number
  outputTokens: number
  totalTokens: number
  /** Summed over the turns that had a price. Null when none of them did. */
  costUsd: number | null
  /** True when at least one turn ran on a model with no published price. */
  hasUnpricedTurn: boolean
}

const EMPTY_TOTALS: UsageTotals = {
  turns: 0,
  inputTokens: 0,
  outputTokens: 0,
  totalTokens: 0,
  costUsd: null,
  hasUnpricedTurn: false,
}

/**
 * Add up every turn's usage in a conversation.
 *
 * @param usages - One entry per message, most of them null for a user turn.
 * @returns The running total, with `hasUnpricedTurn` set when a turn's cost was
 *   unknown, so the caller can say the total is partial rather than exact.
 */
export function sumUsage(usages: readonly (AgentUsage | null | undefined)[]): UsageTotals {
  const totals: UsageTotals = { ...EMPTY_TOTALS }
  for (const usage of usages) {
    if (!usage) continue
    totals.turns += 1
    totals.inputTokens += usage.input_tokens ?? 0
    totals.outputTokens += usage.output_tokens ?? 0
    totals.totalTokens += usage.total_tokens ?? 0
    if (typeof usage.cost_usd === 'number' && Number.isFinite(usage.cost_usd)) {
      totals.costUsd = (totals.costUsd ?? 0) + usage.cost_usd
    } else {
      totals.hasUnpricedTurn = true
    }
  }
  return totals
}

/**
 * Everything about a turn worth putting in a hover, rather than on the line.
 *
 * The line stays short enough to ignore; the title is where the model id, the
 * cache hits, the reasoning tokens and the time to first token live.
 */
function usageTitle(usage: AgentUsage): string {
  const parts: string[] = []
  if (usage.model) parts.push(`Model: ${usage.model}`)
  parts.push(`Input: ${formatTokens(usage.input_tokens)} tokens`)
  parts.push(`Output: ${formatTokens(usage.output_tokens)} tokens`)
  parts.push(`Total: ${formatTokens(usage.total_tokens)} tokens`)
  if (usage.cached_tokens > 0) parts.push(`Cached: ${formatTokens(usage.cached_tokens)} tokens`)
  if (usage.reasoning_tokens > 0) {
    parts.push(`Reasoning: ${formatTokens(usage.reasoning_tokens)} tokens`)
  }
  if (typeof usage.ttft_ms === 'number' && Number.isFinite(usage.ttft_ms)) {
    parts.push(`First token: ${Math.round(usage.ttft_ms)} ms`)
  }
  parts.push(
    typeof usage.cost_usd === 'number' && Number.isFinite(usage.cost_usd)
      ? `Cost: ${formatCost(usage.cost_usd)}`
      : `Cost: unknown. ${UNKNOWN_COST_TITLE}`
  )
  return parts.join('\n')
}

export interface UsageBadgeProps {
  usage: AgentUsage | null | undefined
  className?: string
}

/**
 * One turn's tokens and cost, shown under the answer it belongs to.
 */
export function UsageBadge({ usage, className }: UsageBadgeProps) {
  if (!usage) return null

  const priced = typeof usage.cost_usd === 'number' && Number.isFinite(usage.cost_usd)

  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] leading-none text-muted-foreground',
        className
      )}
      title={usageTitle(usage)}
    >
      <span>{formatTokens(usage.input_tokens)} in</span>
      <span aria-hidden>&middot;</span>
      <span>{formatTokens(usage.output_tokens)} out</span>
      {usage.cached_tokens > 0 && (
        <>
          <span aria-hidden>&middot;</span>
          <span>{formatTokens(usage.cached_tokens)} cached</span>
        </>
      )}
      {usage.reasoning_tokens > 0 && (
        <>
          <span aria-hidden>&middot;</span>
          <span>{formatTokens(usage.reasoning_tokens)} reasoning</span>
        </>
      )}
      <span aria-hidden>&middot;</span>
      {priced ? (
        <span className="tabular-nums">{formatCost(usage.cost_usd)}</span>
      ) : (
        // Never $0.00: the price is not known, and a zero would read as free.
        <span className="tabular-nums" title={UNKNOWN_COST_TITLE}>
          {UNKNOWN_COST}
        </span>
      )}
    </div>
  )
}

export interface ConversationUsageBadgeProps {
  totals: UsageTotals
  className?: string
}

/**
 * The conversation's running total, for the header.
 *
 * A total built from at least one unpriced turn is marked with a trailing plus
 * and explains itself on hover, because the number is a floor rather than the
 * amount actually spent.
 */
export function ConversationUsageBadge({ totals, className }: ConversationUsageBadgeProps) {
  if (totals.turns === 0) return null

  const partial = totals.hasUnpricedTurn
  const costLabel = totals.costUsd === null ? UNKNOWN_COST : formatCost(totals.costUsd)
  const title = partial
    ? `${totals.turns} turn${totals.turns === 1 ? '' : 's'}. ${UNKNOWN_COST_TITLE} The total covers only the turns that had one.`
    : `${totals.turns} turn${totals.turns === 1 ? '' : 's'}, ${formatTokens(totals.totalTokens)} tokens.`

  return (
    <div
      className={cn(
        'flex items-center gap-2 text-[11px] leading-none text-muted-foreground',
        className
      )}
      title={title}
    >
      <span>{formatTokens(totals.totalTokens)} tokens</span>
      <span aria-hidden>&middot;</span>
      <span className="tabular-nums">
        {costLabel}
        {partial && totals.costUsd !== null ? '+' : ''}
      </span>
    </div>
  )
}

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
 * **A subscription turn is the one case where null does not mean unknown, and
 * the dash would be wrong too.** A turn on a ChatGPT Plus or Pro plan has no
 * per-token price to publish: it is covered by a fee that was paid whether or
 * not the turn happened. `litellm.model_cost` prices `gpt-5.4` and deliberately
 * returns nothing for `chatgpt/gpt-5.4` for exactly that reason. Three
 * statements, three renderings, and no two of them may share one:
 *
 * | situation | rendered | means |
 * | --- | --- | --- |
 * | a price is known | `$0.0123` | that much was spent |
 * | no price is published | `-` | unknown, and not zero |
 * | the turn ran on a plan | `included in your ChatGPT plan` | already paid for |
 *
 * The conversation total follows from that: turns with a known price are summed,
 * a total that had at least one unpriced turn says so rather than quietly
 * under-reporting, and plan turns are counted separately because they belong to
 * neither side of that sum.
 */

import type { AgentUsage } from '@/lib/agent/useAgentStream'
import { cn } from '@/lib/utils'

/** What a model with no published price renders as, in place of a number. */
const UNKNOWN_COST = '-'

const UNKNOWN_COST_TITLE =
  'This model has no published price in the catalog, so the cost is unknown. It is not zero.'

/** What a plan turn reads as. Not a price, because it is not one. */
const SUBSCRIPTION_COST = 'included in your ChatGPT plan'

const SUBSCRIPTION_COST_TITLE =
  'This turn ran on your ChatGPT Plus or Pro plan, which has no per-token price. It is covered by the plan, not free and not unknown.'

/**
 * Whether a turn was billed to a subscription rather than per token.
 *
 * @param usage - The turn's usage, possibly from a row stored before the field
 *   existed.
 * @returns True only when the turn says so. Unknown is read as metered, because
 *   claiming a turn was covered by a plan when nobody said so is the reading
 *   that costs somebody money.
 */
export function isSubscriptionTurn(usage: AgentUsage | null | undefined): boolean {
  return usage?.billing === 'subscription'
}

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
  /** How many turns came out of a ChatGPT plan rather than out of credits. */
  subscriptionTurns: number
}

const EMPTY_TOTALS: UsageTotals = {
  turns: 0,
  inputTokens: 0,
  outputTokens: 0,
  totalTokens: 0,
  costUsd: null,
  hasUnpricedTurn: false,
  subscriptionTurns: 0,
}

/**
 * Add up every turn's usage in a conversation.
 *
 * A plan turn contributes its tokens and nothing to the money, and it does
 * **not** set `hasUnpricedTurn`: the total is not missing that turn's price,
 * because there was never a price to miss. Counting it as unpriced would mark
 * an exact total as a floor for no reason.
 *
 * @param usages - One entry per message, most of them null for a user turn.
 * @returns The running total, with `hasUnpricedTurn` set when a turn's cost was
 *   genuinely unknown, so the caller can say the total is partial rather than
 *   exact, and `subscriptionTurns` counting the ones a plan covered.
 */
export function sumUsage(usages: readonly (AgentUsage | null | undefined)[]): UsageTotals {
  const totals: UsageTotals = { ...EMPTY_TOTALS }
  for (const usage of usages) {
    if (!usage) continue
    totals.turns += 1
    totals.inputTokens += usage.input_tokens ?? 0
    totals.outputTokens += usage.output_tokens ?? 0
    totals.totalTokens += usage.total_tokens ?? 0
    if (isSubscriptionTurn(usage)) {
      totals.subscriptionTurns += 1
    } else if (typeof usage.cost_usd === 'number' && Number.isFinite(usage.cost_usd)) {
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
  if (isSubscriptionTurn(usage)) {
    parts.push(`Billing: ChatGPT plan. ${SUBSCRIPTION_COST_TITLE}`)
  } else if (typeof usage.cost_usd === 'number' && Number.isFinite(usage.cost_usd)) {
    parts.push(`Cost: ${formatCost(usage.cost_usd)}`)
  } else {
    parts.push(`Cost: unknown. ${UNKNOWN_COST_TITLE}`)
  }
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

  const onPlan = isSubscriptionTurn(usage)
  const priced = !onPlan && typeof usage.cost_usd === 'number' && Number.isFinite(usage.cost_usd)

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
      {onPlan ? (
        // Neither a number nor the unknown dash. The dash means "nobody
        // published a price"; this turn has no price to publish, which is a
        // different and more useful thing to say.
        <span title={SUBSCRIPTION_COST_TITLE}>{SUBSCRIPTION_COST}</span>
      ) : priced ? (
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
 *
 * A conversation held entirely on a ChatGPT plan has no total to show, so it
 * says so in words instead of showing a dash. A mixed conversation shows the
 * money its metered turns cost and names the plan turns in the hover, because
 * the number on the line is then the complete answer to "what did this spend"
 * even though it is not the complete answer to "what did this use".
 */
export function ConversationUsageBadge({ totals, className }: ConversationUsageBadgeProps) {
  if (totals.turns === 0) return null

  const allOnPlan = totals.subscriptionTurns === totals.turns
  const partial = totals.hasUnpricedTurn
  const costLabel = totals.costUsd === null ? UNKNOWN_COST : formatCost(totals.costUsd)
  const turnCount = `${totals.turns} turn${totals.turns === 1 ? '' : 's'}`
  const planNote =
    totals.subscriptionTurns > 0 && !allOnPlan
      ? ` ${totals.subscriptionTurns} of them ran on your ChatGPT plan and cost nothing extra.`
      : ''

  let title: string
  if (allOnPlan) {
    title = `${turnCount}, ${formatTokens(totals.totalTokens)} tokens. ${SUBSCRIPTION_COST_TITLE}`
  } else if (partial) {
    title = `${turnCount}. ${UNKNOWN_COST_TITLE} The total covers only the turns that had one.${planNote}`
  } else {
    title = `${turnCount}, ${formatTokens(totals.totalTokens)} tokens.${planNote}`
  }

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
      {allOnPlan ? (
        <span>{SUBSCRIPTION_COST}</span>
      ) : (
        <span className="tabular-nums">
          {costLabel}
          {partial && totals.costUsd !== null ? '+' : ''}
        </span>
      )}
    </div>
  )
}

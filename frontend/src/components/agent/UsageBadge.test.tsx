/**
 * Three statements about the price of a turn, and no two may share a rendering.
 *
 * | situation | rendered | means |
 * | --- | --- | --- |
 * | a price is known | `$0.0123` | that much was spent |
 * | no price is published | `-` | unknown, and not zero |
 * | the turn ran on a plan | `included in your ChatGPT plan` | already paid for |
 *
 * The failure this file exists to catch is the middle rendering leaking onto
 * the bottom row. `litellm.model_cost` prices `gpt-5.4` and returns nothing for
 * `chatgpt/gpt-5.4`, deliberately, because a plan turn has no per-token price
 * at all. Read naively that is indistinguishable from a model nobody priced, so
 * a plan turn renders a dash meaning "unknown" for a cost that is perfectly
 * well known, or worse a $0.00 that says the turn was free. Neither is true.
 */

import { describe, expect, it } from 'vitest'
import type { AgentUsage } from '@/lib/agent/useAgentStream'
import { render, screen } from '@/test/test-utils'
import { ConversationUsageBadge, sumUsage, UsageBadge } from './UsageBadge'

function usage(overrides: Partial<AgentUsage> = {}): AgentUsage {
  return {
    input_tokens: 1024,
    output_tokens: 180,
    total_tokens: 1204,
    cached_tokens: 0,
    reasoning_tokens: 0,
    cost_usd: 0.0123,
    model: 'gpt-5.4',
    ttft_ms: 410,
    ...overrides,
  }
}

describe('UsageBadge', () => {
  it('renders a known price as money', () => {
    render(<UsageBadge usage={usage()} />)

    expect(screen.getByText('$0.0123')).toBeInTheDocument()
    expect(screen.queryByText(/ChatGPT plan/)).not.toBeInTheDocument()
  })

  it('renders an unpublished price as unknown, never as zero', () => {
    render(<UsageBadge usage={usage({ cost_usd: null })} />)

    expect(screen.getByText('-')).toBeInTheDocument()
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument()
  })

  it('says a plan turn is covered, and shows neither a dash nor a zero', () => {
    render(
      <UsageBadge
        usage={usage({ cost_usd: null, billing: 'subscription', model: 'chatgpt/gpt-5.4' })}
      />
    )

    expect(screen.getByText('included in your ChatGPT plan')).toBeInTheDocument()
    expect(screen.queryByText('-')).not.toBeInTheDocument()
    expect(screen.queryByText('$0.00')).not.toBeInTheDocument()
    // The tokens are still reported: what the turn used is a separate fact from
    // what it cost.
    expect(screen.getByText('1,024 in')).toBeInTheDocument()
    expect(screen.getByText('180 out')).toBeInTheDocument()
  })

  // A cost arriving alongside a subscription turn is a server-side mistake, and
  // rendering it would tell the operator a plan turn charged them money.
  it('trusts the billing path over a stray cost on a plan turn', () => {
    render(<UsageBadge usage={usage({ cost_usd: 0.0123, billing: 'subscription' })} />)

    expect(screen.getByText('included in your ChatGPT plan')).toBeInTheDocument()
    expect(screen.queryByText('$0.0123')).not.toBeInTheDocument()
  })

  it('reads an unknown billing value as metered rather than as a plan', () => {
    render(<UsageBadge usage={usage({ billing: 'free' as unknown as 'metered' })} />)

    expect(screen.getByText('$0.0123')).toBeInTheDocument()
    expect(screen.queryByText(/ChatGPT plan/)).not.toBeInTheDocument()
  })
})

describe('sumUsage', () => {
  it('keeps a plan turn out of the money and out of the unpriced count', () => {
    const totals = sumUsage([usage(), usage({ cost_usd: null, billing: 'subscription' })])

    expect(totals.turns).toBe(2)
    expect(totals.totalTokens).toBe(2408)
    expect(totals.costUsd).toBeCloseTo(0.0123)
    expect(totals.subscriptionTurns).toBe(1)
    // The total is exact: the plan turn never had a price to be missing from it.
    expect(totals.hasUnpricedTurn).toBe(false)
  })

  it('still marks a genuinely unpriced turn as unknown', () => {
    const totals = sumUsage([usage(), usage({ cost_usd: null })])

    expect(totals.hasUnpricedTurn).toBe(true)
    expect(totals.subscriptionTurns).toBe(0)
  })
})

describe('ConversationUsageBadge', () => {
  it('says a conversation held entirely on a plan cost nothing extra', () => {
    const totals = sumUsage([usage({ cost_usd: null, billing: 'subscription' })])
    render(<ConversationUsageBadge totals={totals} />)

    expect(screen.getByText('included in your ChatGPT plan')).toBeInTheDocument()
    expect(screen.queryByText('-')).not.toBeInTheDocument()
  })

  it('shows the money a mixed conversation spent, exactly rather than as a floor', () => {
    const totals = sumUsage([usage(), usage({ cost_usd: null, billing: 'subscription' })])
    render(<ConversationUsageBadge totals={totals} />)

    expect(screen.getByText('$0.0123')).toBeInTheDocument()
    expect(screen.queryByText('$0.0123+')).not.toBeInTheDocument()
  })
})

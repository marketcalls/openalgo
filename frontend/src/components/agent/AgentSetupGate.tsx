/**
 * The "configure the agent first" state, for any surface that hosts a chat.
 *
 * Every agent surface needs this and for the same reason: until a model is
 * registered and its key has passed a test, there is nothing to talk to, and a
 * composer that accepts a question and then fails is worse than one that
 * explains itself. `/agent` grew its own copy first; this is that behaviour
 * lifted so the chart panel and anything after it share one answer rather than
 * three that drift.
 *
 * **An unreachable status reads as "not configured", never as an error.** That
 * is the honest interpretation: a status call that cannot be answered is not
 * evidence of a working agent behind it. The failure mode that matters is
 * showing a working chat when there is none, not the reverse.
 *
 * `compact` exists because a rail panel is roughly a third the width of the
 * page. The same words at page scale wrap into a wall in a narrow column, so
 * the compact form drops to the two sentences that actually decide what the
 * operator does next.
 */

import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Bot } from 'lucide-react'
import { Link } from 'react-router'
import { agentQueryKeys, getStatus } from '@/api/agent'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export interface AgentStatusGate {
  /** True once a model is registered, enabled and has passed a test. */
  configured: boolean
  /** True while the answer is unknown. Render nothing rather than guessing. */
  loading: boolean
}

/**
 * Whether the agent is usable on this instance.
 *
 * Shared across surfaces through one query key, so opening the chart panel
 * after the chat costs no second request and both agree about the answer.
 */
export function useAgentConfigured(): AgentStatusGate {
  const { data, isLoading } = useQuery({
    queryKey: agentQueryKeys.status(),
    queryFn: async () => {
      try {
        return await getStatus()
      } catch {
        // See the module docstring: unanswerable is treated as unconfigured.
        return { configured: false, default_model_id: null, model_count: 0 }
      }
    },
    staleTime: 30_000,
  })
  return { configured: Boolean(data?.configured), loading: isLoading }
}

export interface AgentSetupGateProps {
  /** Narrow form, for a rail panel rather than a page. */
  compact?: boolean
  className?: string
}

export function AgentSetupGate({ compact = false, className }: AgentSetupGateProps) {
  return (
    <div
      className={cn(
        'flex h-full flex-col items-center justify-center gap-3 text-center',
        compact ? 'px-4 py-6' : 'mx-auto max-w-xl px-6 py-10 gap-4',
        className
      )}
    >
      <div className="rounded-xl border bg-muted/40 p-3">
        <Bot className={cn('text-muted-foreground', compact ? 'h-6 w-6' : 'h-8 w-8')} aria-hidden />
      </div>
      <h2 className={cn('font-semibold tracking-tight', compact ? 'text-base' : 'text-2xl')}>
        Set up your agent
      </h2>
      <p className={cn('leading-relaxed text-muted-foreground', compact ? 'text-xs' : 'text-sm')}>
        {compact
          ? 'Add a model and its API key before the agent can answer. Keys are stored encrypted in your own database.'
          : 'Choose a model provider and add its API key to start using the agent. Keys are stored encrypted in your own database and are never written to a configuration file. A local provider is supported if you would rather nothing left this machine.'}
      </p>
      {/* The whole first-run path. A fresh install lands here, so it has to
          lead somewhere rather than describe a screen the operator cannot
          reach. */}
      <Button asChild size={compact ? 'sm' : 'default'}>
        <Link to="/agent/config">
          Configure the agent
          <ArrowRight className={compact ? 'h-3.5 w-3.5' : 'h-4 w-4'} aria-hidden />
        </Link>
      </Button>
    </div>
  )
}

/**
 * The /agent surface.
 *
 * The page is gated on configuration: until a model is configured and its
 * credentials have been tested, there is nothing useful to chat with, so the
 * setup view is what renders. `GET /agent/api/status` is the single cheap call
 * that decides which of the two the operator sees.
 *
 * An unreachable status is read as "not configured" rather than as an error.
 * That is the honest reading: a status call that cannot be answered is not
 * evidence that a working agent is sitting behind it.
 */

import { useQuery } from '@tanstack/react-query'
import { Bot } from 'lucide-react'
import { webClient } from '@/api/client'
import AgentChat from './AgentChat'

interface AgentStatus {
  configured: boolean
  default_model_id: number | null
  model_count: number
}

const UNCONFIGURED: AgentStatus = {
  configured: false,
  default_model_id: null,
  model_count: 0,
}

async function fetchAgentStatus(): Promise<AgentStatus> {
  try {
    const response = await webClient.get<AgentStatus>('/agent/api/status')
    return response.data
  } catch {
    // Treated as unconfigured, never surfaced as a page-level error. See the
    // module docstring: an unanswerable status is not proof of a working agent.
    return UNCONFIGURED
  }
}

export default function AgentIndex() {
  const { data, isLoading } = useQuery({
    queryKey: ['agent', 'status'],
    queryFn: fetchAgentStatus,
    staleTime: 30_000,
  })

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <span className="text-sm text-muted-foreground">Checking agent configuration</span>
      </div>
    )
  }

  if (!data?.configured) {
    return (
      <div className="mx-auto flex min-h-[60vh] max-w-xl flex-col items-center justify-center gap-4 px-6 text-center">
        <div className="rounded-xl border bg-muted/40 p-4">
          <Bot className="h-8 w-8 text-muted-foreground" aria-hidden />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">Set up your agent</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Choose a model provider and add its API key to start using the agent. Keys are
          stored encrypted in your own database and are never written to a configuration
          file. A local provider is supported if you would rather nothing left this machine.
        </p>
        <p className="text-xs text-muted-foreground">
          Provider setup is not available yet on this build.
        </p>
      </div>
    )
  }

  return <AgentChat />
}

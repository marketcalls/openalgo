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
 *
 * The route lives under `FullWidthLayout`, which renders no navigation of its
 * own, so this page renders `Navbar` itself exactly as /trading does. The
 * layout gives it an `h-screen` flex column with `overflow-hidden`, so
 * everything below the nav is one `flex-1 min-h-0` region: the height comes
 * from the viewport rather than from a `calc()` that has to guess how tall the
 * chrome above it is.
 */

import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Bot } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { webClient } from '@/api/client'
import { Navbar } from '@/components/layout/Navbar'
import { Button } from '@/components/ui/button'
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

/**
 * The nav plus the one region everything else fills.
 *
 * `min-h-0` is load-bearing: a flex item's default `min-height: auto` refuses
 * to shrink below its content, so without it a long thread grows this region
 * past the viewport and the composer walks off the bottom of the screen
 * instead of staying pinned.
 */
function AgentShell({ children }: { children: ReactNode }) {
  return (
    <>
      {/* Full-bleed page: the nav spans the viewport rather than Layout's
          centred container. See NavbarProps.fluid. */}
      <Navbar fluid />
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
    </>
  )
}

export default function AgentIndex() {
  const { data, isLoading } = useQuery({
    queryKey: ['agent', 'status'],
    queryFn: fetchAgentStatus,
    staleTime: 30_000,
  })

  if (isLoading) {
    return (
      <AgentShell>
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <span className="text-sm text-muted-foreground">Checking agent configuration</span>
        </div>
      </AgentShell>
    )
  }

  if (!data?.configured) {
    return (
      <AgentShell>
        {/* Scrolls on a short viewport rather than clipping, which the
            layout's overflow-hidden would otherwise do. */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex min-h-full max-w-xl flex-col items-center justify-center gap-4 px-6 py-10 text-center">
            <div className="rounded-xl border bg-muted/40 p-4">
              <Bot className="h-8 w-8 text-muted-foreground" aria-hidden />
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">Set up your agent</h1>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Choose a model provider and add its API key to start using the agent. Keys are stored
              encrypted in your own database and are never written to a configuration file. A local
              provider is supported if you would rather nothing left this machine.
            </p>
            {/* The whole first-run path. A fresh install lands on this gate,
                so it has to lead somewhere rather than describe a screen the
                operator cannot reach. */}
            <Button asChild>
              <Link to="/agent/config">
                Configure the agent
                <ArrowRight className="h-4 w-4" aria-hidden />
              </Link>
            </Button>
          </div>
        </div>
      </AgentShell>
    )
  }

  return (
    <AgentShell>
      <AgentChat />
    </AgentShell>
  )
}

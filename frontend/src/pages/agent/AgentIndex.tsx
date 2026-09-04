/**
 * The /agent surface.
 *
 * The page is gated on configuration: until a model is configured and its
 * credentials have been tested, there is nothing useful to chat with, so the
 * setup view is what renders.
 *
 * **The gate is `components/agent/AgentSetupGate`, not a copy of it.** This
 * page had the first version, the chart panel needed the same behaviour, and
 * two copies of "what does an unconfigured agent say" is two answers that drift
 * the first time either is edited. `useAgentConfigured` is the one status query
 * and `AgentSetupGate` is the one thing it renders, so both surfaces agree, and
 * they share a query key so opening the second costs no second request.
 *
 * An unreachable status is read as "not configured" rather than as an error,
 * which is decided inside that hook. That is the honest reading: a status call
 * that cannot be answered is not evidence that a working agent is sitting
 * behind it.
 *
 * The route lives under `FullWidthLayout`, which renders no navigation of its
 * own, so this page renders `Navbar` itself exactly as /trading does. The
 * layout gives it an `h-screen` flex column with `overflow-hidden`, so
 * everything below the nav is one `flex-1 min-h-0` region: the height comes
 * from the viewport rather than from a `calc()` that has to guess how tall the
 * chrome above it is.
 */

import type { ReactNode } from 'react'
import { AgentSetupGate, useAgentConfigured } from '@/components/agent/AgentSetupGate'
import { Navbar } from '@/components/layout/Navbar'
import AgentChat from './AgentChat'

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
  const { configured, loading } = useAgentConfigured()

  if (loading) {
    return (
      <AgentShell>
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <span className="text-sm text-muted-foreground">Checking agent configuration</span>
        </div>
      </AgentShell>
    )
  }

  if (!configured) {
    return (
      <AgentShell>
        {/* Scrolls on a short viewport rather than clipping, which the
            layout's overflow-hidden would otherwise do. */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <AgentSetupGate />
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

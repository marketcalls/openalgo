/**
 * The /agent/config surface.
 *
 * Everything an operator sets for the agent lives here: the models already
 * registered, the provider catalog they are added from, and web search. None of
 * it is read from `.env`; it is all rows in this instance's own database, which
 * is why there is a screen for it at all.
 *
 * The order is deliberate, and it is ranked by what brought someone here. A
 * returning operator came to change a model that is already there, so the
 * registry is first. The two things they came to connect, a ChatGPT plan and
 * the trading switch, come next. The provider catalog follows, because it is
 * the only section that is browsed rather than read and it draws two dozen
 * cards before it stops. Web search is last: it works with nothing configured,
 * so it is the one section that is never the reason someone opened this page.
 *
 * That ranking is not a preference. The catalog grid is a screen and a half
 * tall, and anything placed under it is effectively unfindable, which is how
 * the trading switch came to be buried once already.
 *
 * The route sits under `FullWidthLayout`, which renders no navigation of its
 * own, so this page renders `Navbar` itself exactly as /agent and /trading do.
 * The layout gives it an `h-screen` flex column with `overflow-hidden`, so the
 * header bar is a `shrink-0` row and everything below it is one
 * `flex-1 min-h-0` scroll region. `min-h-0` is load-bearing: a flex item's
 * default `min-height: auto` refuses to shrink below its content, so without it
 * a long registry grows the region past the viewport and the page scrolls in
 * two places at once.
 *
 * Full width is for the chrome, not for the content. The header spans the
 * viewport; the sections share one capped, centred column, because a settings
 * form stretched across 2000px is unreadable.
 *
 * Each section owns its own queries and its own failure. A section whose data
 * cannot be loaded says so in place, and the boundary around it catches a
 * render error so one broken panel cannot take the other two down with it.
 */

import { ArrowLeft, Plus } from 'lucide-react'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { Link } from 'react-router'
import { AddModelDialog } from '@/components/agent/config/AddModelDialog'
import { ChatGptSubscriptionPanel } from '@/components/agent/config/ChatGptSubscriptionPanel'
import { ProviderCatalogPanel } from '@/components/agent/config/ProviderCatalogPanel'
import { RegisteredModelsTable } from '@/components/agent/config/RegisteredModelsTable'
import { TradingPanel } from '@/components/agent/config/TradingPanel'
import { WebSearchPanel } from '@/components/agent/config/WebSearchPanel'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Navbar } from '@/components/layout/Navbar'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

/**
 * One section, isolated from the other two.
 *
 * The boundary is per section rather than per page on purpose: the registry,
 * the catalog and web search are independent, and a panel that throws should
 * cost the operator that panel and nothing else.
 */
function Section({ name, children }: { name: string; children: ReactNode }) {
  return (
    <ErrorBoundary
      fallback={
        <Alert variant="destructive">
          <AlertDescription>
            {name} could not be shown. The error has been logged; reload the page to try again. The
            rest of this page still works.
          </AlertDescription>
        </Alert>
      }
    >
      {children}
    </ErrorBoundary>
  )
}

export default function AgentConfig() {
  // The escape hatch: the catalog covers the models LiteLLM knows about, and
  // this covers the one it does not. Opened with no provider and no model name,
  // so the dialog starts blank.
  const [addOpen, setAddOpen] = useState(false)

  return (
    <>
      {/* Full-bleed page: the nav spans the viewport rather than Layout's
          centred container. See NavbarProps.fluid. */}
      <Navbar fluid />
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <Button asChild variant="ghost" size="sm">
              <Link to="/agent">
                <ArrowLeft className="h-4 w-4" aria-hidden />
                Back to chat
              </Link>
            </Button>
            <div className="space-y-0.5">
              <h1 className="text-base font-semibold leading-none">Agent configuration</h1>
              <p className="text-xs text-muted-foreground">
                Models, keys and web search, stored encrypted in this instance's own database.
              </p>
            </div>
          </div>
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            Add model
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6">
            <Section name="The registered models">
              {/* The table renders no heading of its own so the page can place
                  it, which means the page has to. Without this the first thing
                  on the screen is an unlabelled table while the two sections
                  under it are titled. */}
              <section aria-labelledby="agent-models-heading" className="space-y-4">
                <div>
                  <h2 id="agent-models-heading" className="text-base font-semibold">
                    Models
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    Every model the agent may run. Exactly one is the default, and the chat picker
                    offers every enabled row.
                  </p>
                </div>
                <RegisteredModelsTable />
              </section>
            </Section>
            {/* Above the provider grid, not below it. The grid draws 24 cards
                before it offers to show more, so anything under it starts a
                screen and a half down: the trading switch was buried exactly
                that way once. This panel is the answer to a question an
                operator arrives with ("where is my ChatGPT plan"), so it sits
                where they land. */}
            <Section name="The ChatGPT subscription">
              <ChatGptSubscriptionPanel />
            </Section>
            <Section name="Trading">
              <TradingPanel />
            </Section>
            <Section name="The provider catalog">
              <ProviderCatalogPanel />
            </Section>
            <Section name="Web search">
              <WebSearchPanel />
            </Section>
          </div>
        </div>
      </div>

      <AddModelDialog open={addOpen} onOpenChange={setAddOpen} />
    </>
  )
}

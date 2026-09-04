/**
 * The agent's trading switch.
 *
 * Order tools are withheld unless this is on. That is why an operator can ask
 * the agent to place an order and get a polite refusal rather than an approval
 * prompt: with the switch off the tools are never offered, so there is nothing
 * to approve. Until this panel existed the switch could only be changed by
 * writing the database row by hand, which is a setting nobody would find.
 *
 * **The mode is shown next to the switch on purpose.** Two independent things
 * decide where an approved order lands: this switch decides whether the agent
 * may propose one at all, and the platform's analyzer mode decides whether it
 * reaches the broker or the sandbox. An operator reading only this panel could
 * reasonably assume orders are simulated; on a live instance they are not. So
 * the live case is stated in the panel rather than left to be inferred from a
 * badge in the navigation bar.
 *
 * Turning this on does not place anything. Every order tool still pauses for
 * explicit approval, and the risk guard still runs inside the tool body after
 * that approval. This is the outermost of those gates, not a replacement for
 * them.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { agentErrorMessage, agentQueryKeys, getSettings, updateSettings } from '@/api/agent'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'

interface AnalyzerStatus {
  analyze_mode?: boolean
}

export function TradingPanel() {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  const settings = useQuery({
    queryKey: agentQueryKeys.settings(),
    queryFn: getSettings,
  })

  // The platform-wide analyzer toggle, read from the same endpoint the
  // navigation badge uses. It is not an agent setting and is deliberately not
  // editable here: changing where every order in the whole platform lands
  // should not be a side effect of configuring the agent.
  const analyzer = useQuery({
    queryKey: ['analyzer', 'status'],
    queryFn: async (): Promise<AnalyzerStatus> => {
      const response = await fetch('/settings/analyze-mode', {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      })
      if (!response.ok) return {}
      return (await response.json()) as AnalyzerStatus
    },
    staleTime: 30_000,
  })

  const save = useMutation({
    mutationFn: (enabled: boolean) => updateSettings({ trading_enabled: enabled }),
    onSuccess: (data) => {
      setError(null)
      queryClient.setQueryData(agentQueryKeys.settings(), (previous: unknown) =>
        previous && typeof previous === 'object'
          ? { ...(previous as Record<string, unknown>), data }
          : previous
      )
      // The chat reads this to decide whether to ask for order tools, so it has
      // to see the change without a reload.
      void queryClient.invalidateQueries({ queryKey: agentQueryKeys.settings() })
      void queryClient.invalidateQueries({ queryKey: agentQueryKeys.status() })
    },
    onError: (cause) => setError(agentErrorMessage(cause, 'Could not change the trading setting')),
  })

  const enabled = settings.data?.data.trading_enabled ?? false
  const live = analyzer.data?.analyze_mode === false
  const busy = settings.isLoading || save.isPending

  return (
    <section aria-labelledby="agent-trading-heading" className="space-y-4">
      <div>
        <h2 id="agent-trading-heading" className="text-base font-semibold">
          Trading
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Whether the agent may propose orders at all. Every order it proposes still stops for your
          approval before anything is sent.
        </p>
      </div>

      <div className="rounded-lg border border-border">
        <div className="flex items-start gap-3 p-4">
          <Switch
            id="agent-trading-enabled"
            checked={enabled}
            disabled={busy}
            onCheckedChange={(next) => save.mutate(next)}
            aria-describedby="agent-trading-help"
          />
          <div className="min-w-0 flex-1">
            <Label htmlFor="agent-trading-enabled" className="text-sm font-medium">
              Allow the agent to place, modify and cancel orders
            </Label>
            <p id="agent-trading-help" className="mt-1 text-sm text-muted-foreground">
              {enabled
                ? 'Order tools are available. Each call pauses for your approval, and the risk limits still apply after it.'
                : 'Order tools are withheld, so the agent will decline to trade rather than ask you to approve anything.'}
            </p>
          </div>
        </div>

        {/* Only shown when it changes the consequence. On an analyzer instance
            the sandbox note is reassurance nobody needs; on a live one this is
            the single most important sentence on the page. */}
        {enabled && live && (
          // Padding on a wrapper, not margin on the Alert. The Alert base style
          // is `w-full`, so `w-full` plus a horizontal margin resolves to the
          // parent's full width PLUS that margin, and the box overhangs its
          // container by exactly the margin on each side.
          <div className="px-4 pb-4">
            <Alert variant="destructive">
              <AlertDescription>
                This instance is in live mode, so an order you approve is sent to your broker with
                real money. Switch the platform to analyzer mode first if you want approved orders
                to reach the sandbox instead.
              </AlertDescription>
            </Alert>
          </div>
        )}

        {enabled && analyzer.data?.analyze_mode === true && (
          <p className="px-4 pb-4 text-sm text-muted-foreground">
            The platform is in analyzer mode, so an approved order reaches the sandbox rather than
            your broker.
          </p>
        )}
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </section>
  )
}

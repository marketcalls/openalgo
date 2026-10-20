// pages/strategy/Edit.tsx
// Loads a strategy, then hands it to the wizard to edit in place.

import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router'
import { getStrategy, strategyQueryKeys } from '@/api/strategy_module'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import StrategyWizard from './Wizard'

export default function StrategyEdit() {
  // Named to match the route, which declares :strategyId. Destructuring
  // `id` from it yields undefined, so every visit to /strategy/<n> failed
  // its own validity check and rendered "Invalid strategy id".
  const { strategyId } = useParams<{ strategyId: string }>()
  const navigate = useNavigate()
  const numId = Number(strategyId)

  const {
    data: strategy,
    isLoading,
    error,
  } = useQuery({
    queryKey: strategyQueryKeys.strategy(numId),
    queryFn: () => getStrategy(numId),
    enabled: Number.isFinite(numId) && numId > 0,
  })

  if (isLoading) {
    return <div className="py-12 text-center text-sm text-muted-foreground">Loading strategy…</div>
  }

  if (error || !strategy) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6 text-center">
          <p className="text-sm text-destructive">Failed to load strategy.</p>
          <Button variant="outline" onClick={() => navigate('/strategy')}>
            Back to list
          </Button>
        </CardContent>
      </Card>
    )
  }

  // The server answers a PATCH on a running strategy with a 409. Saying so here
  // is a clearer explanation than letting the user fill in a form and then be
  // told the whole thing was refused.
  if (strategy.status === 'running') {
    return (
      <Card>
        <CardContent className="space-y-3 p-6 text-center">
          <p className="text-sm">
            This strategy is currently <span className="font-mono">{strategy.status}</span>. Stop it
            before editing.
          </p>
          <Button variant="outline" onClick={() => navigate(`/strategy/${strategy.id}`)}>
            Back to detail
          </Button>
        </CardContent>
      </Card>
    )
  }

  return <StrategyWizard editing={strategy} />
}

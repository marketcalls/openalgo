// frontend/src/components/ai-analysis/VotingBreakdown.tsx
import type { ConfluenceVote } from '@/types/strategy-analysis'

interface VotingBreakdownProps {
  votes: ConfluenceVote[]
}

const MODULE_LABELS: Record<string, string> = {
  signal: 'Signal',
  smc: 'Smart Money',
  fibonacci: 'Fibonacci',
  harmonic: 'Harmonic',
  elliott: 'Elliott Wave',
  hedge_momentum: 'Momentum',
  candlestick_patterns: 'Patterns',
  mean_reversion: 'Mean Rev',
  support_resistance: 'S/R Levels',
}

export function VotingBreakdown({ votes }: VotingBreakdownProps) {
  if (!votes || votes.length === 0) {
    return (
      <div className="flex items-center justify-center py-4 text-sm text-muted-foreground">
        No voting data available
      </div>
    )
  }

  return (
    <div className="space-y-1">
      {votes.map((vote, idx) => {
        let icon: string
        let iconColor: string

        if (vote.vote > 0) {
          icon = '\u25B2' // ▲
          iconColor = 'text-green-500'
        } else if (vote.vote < 0) {
          icon = '\u25BC' // ▼
          iconColor = 'text-red-500'
        } else {
          icon = '\u2014' // —
          iconColor = 'text-gray-400'
        }

        const label = MODULE_LABELS[vote.module] ?? vote.module

        return (
          <div
            key={`${vote.module}-${idx}`}
            className="flex items-start gap-2 rounded-sm px-2 py-1.5 transition-colors hover:bg-muted/50"
          >
            <span className={`mt-0.5 text-xs ${iconColor}`}>{icon}</span>

            <div className="flex-1 min-w-0">
              <span className="text-sm font-medium">{label}</span>
              {vote.detail && (
                <p className="truncate text-xs text-muted-foreground">
                  {vote.detail}
                </p>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

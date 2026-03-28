import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Loader2, Brain, TrendingUp, TrendingDown, Minus, AlertCircle } from 'lucide-react'
import { useRLSignal } from '@/hooks/useStrategyAnalysis'
import { useApiKey } from '@/hooks/useAIAnalysis'
import { apiClient } from '@/api/client'

interface Props {
  symbol: string
  exchange: string
}

const SIGNAL_CONFIG = {
  BUY: {
    color: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
    icon: TrendingUp,
    label: 'BUY',
  },
  SELL: {
    color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
    icon: TrendingDown,
    label: 'SELL',
  },
  HOLD: {
    color: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
    icon: Minus,
    label: 'HOLD',
  },
}

export function RLAgentTab({ symbol, exchange }: Props) {
  const apikey = useApiKey()
  const [training, setTraining] = useState(false)
  const [trainError, setTrainError] = useState<string | null>(null)
  const [algo, setAlgo] = useState<'ppo' | 'a2c' | 'dqn'>('ppo')
  const { data, isLoading, refetch } = useRLSignal(symbol, exchange, algo)

  const handleTrain = async () => {
    if (!apikey) return
    setTraining(true)
    setTrainError(null)
    try {
      await apiClient.post('/api/v1/agent/rl-train', {
        apikey,
        symbol,
        exchange,
        algo,
        timesteps: 20000,
      })
      refetch()
    } catch {
      setTrainError('Training failed — check logs for details.')
    } finally {
      setTraining(false)
    }
  }

  const signal = data?.signal ?? 'HOLD'
  const cfg = SIGNAL_CONFIG[signal] ?? SIGNAL_CONFIG.HOLD
  const SignalIcon = cfg.icon

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-purple-500" />
          <h3 className="font-semibold text-lg">RL Trading Agent</h3>
          <Badge variant="outline" className="text-xs">
            FinRL / SB3
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="text-xs border rounded px-2 py-1 bg-background"
            value={algo}
            onChange={(e) => setAlgo(e.target.value as typeof algo)}
          >
            <option value="ppo">PPO</option>
            <option value="a2c">A2C</option>
            <option value="dqn">DQN</option>
          </select>
          <Button size="sm" variant="outline" onClick={handleTrain} disabled={training || !symbol}>
            {training ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin mr-1" />
                Training…
              </>
            ) : (
              'Train'
            )}
          </Button>
          <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isLoading || !symbol}>
            {isLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Refresh'}
          </Button>
        </div>
      </div>

      {trainError && (
        <p className="text-sm text-red-500 flex items-center gap-1">
          <AlertCircle className="h-4 w-4" /> {trainError}
        </p>
      )}

      {/* Signal Card */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">
            Current Signal — {symbol || 'no symbol selected'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!symbol ? (
            <p className="text-sm text-muted-foreground">Enter a symbol above to get an RL signal.</p>
          ) : isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" /> Loading signal…
            </div>
          ) : data?.status === 'no_model' ? (
            <div className="flex items-start gap-3 p-3 bg-muted/50 rounded-lg">
              <AlertCircle className="h-5 w-5 text-yellow-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium">No model trained yet</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Click <strong>Train</strong> to train a {algo.toUpperCase()} agent on {symbol}'s
                  historical data (~2 min for 20k steps).
                </p>
              </div>
            </div>
          ) : data?.status === 'error' ? (
            <p className="text-sm text-red-500">{data.message ?? 'Error fetching signal'}</p>
          ) : data?.status === 'success' ? (
            <div className="flex items-center gap-4">
              <div className={`flex items-center gap-2 px-4 py-2 rounded-lg text-lg font-bold ${cfg.color}`}>
                <SignalIcon className="h-6 w-6" />
                {cfg.label}
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">
                  Confidence:{' '}
                  <span className="font-mono font-semibold">
                    {((data.confidence ?? 0) * 100).toFixed(0)}%
                  </span>
                </p>
                <p className="text-xs text-muted-foreground">
                  Model: <span className="font-mono">{data.algo?.toUpperCase()}</span>
                </p>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* Info Panel */}
      <Card>
        <CardContent className="pt-4">
          <p className="text-xs text-muted-foreground leading-relaxed">
            <strong>How it works:</strong> The RL agent is trained on {symbol || 'your symbol'}'s OHLCV
            history using Stable-Baselines3 ({algo.toUpperCase()}). It learns when to BUY, SELL, or HOLD
            by maximising portfolio value. Training takes ~2 minutes for 20,000 steps. Re-train
            periodically as market conditions change.
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            <strong>Actions:</strong> 0 = HOLD · 1 = BUY (full position) · 2 = SELL (close position)
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

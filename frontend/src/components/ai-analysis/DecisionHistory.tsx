import { useQuery } from '@tanstack/react-query'

import { aiAnalysisApi } from '@/api/ai-analysis'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useApiKey } from '@/hooks/useAIAnalysis'
import type { AIDecisionRecord } from '@/types/ai-analysis'

import { SignalBadge } from './SignalBadge'

interface DecisionHistoryProps {
  symbol?: string
  limit?: number
}

export function DecisionHistory({ symbol, limit = 10 }: DecisionHistoryProps) {
  const apiKey = useApiKey()

  const { data: decisions } = useQuery<AIDecisionRecord[]>({
    queryKey: ['ai-decisions', symbol, limit],
    queryFn: async () => {
      if (!apiKey) return []
      const response = await aiAnalysisApi.getDecisionHistory(apiKey, symbol, limit)
      if (response.status === 'error') {
        throw new Error(response.message || 'Failed to fetch AI history')
      }
      return response.data ?? []
    },
    enabled: !!apiKey,
    staleTime: 30_000,
  })

  if (!decisions || decisions.length === 0) {
    return <p className="py-2 text-center text-xs text-muted-foreground">No history yet</p>
  }

  return (
    <div className="max-h-48 overflow-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs">Time</TableHead>
            <TableHead className="text-xs">Symbol</TableHead>
            <TableHead className="text-xs">Signal</TableHead>
            <TableHead className="text-right text-xs">Conf.</TableHead>
            <TableHead className="text-xs">Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {decisions.map((decision) => (
            <TableRow key={decision.id}>
              <TableCell className="font-mono text-xs">
                {new Date(decision.timestamp).toLocaleTimeString()}
              </TableCell>
              <TableCell className="text-xs">{decision.symbol}</TableCell>
              <TableCell>
                <SignalBadge signal={decision.signal} size="sm" />
              </TableCell>
              <TableCell className="text-right text-xs">
                {decision.confidence.toFixed(0)}%
              </TableCell>
              <TableCell className="text-xs">{decision.action_taken ?? '-'}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

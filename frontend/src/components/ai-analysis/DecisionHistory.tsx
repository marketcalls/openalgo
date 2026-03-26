// frontend/src/components/ai-analysis/DecisionHistory.tsx
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { SignalBadge } from './SignalBadge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { SignalType } from '@/types/ai-analysis'

interface DecisionRecord {
  id: number
  timestamp: string
  symbol: string
  exchange: string
  signal: SignalType
  confidence: number
  score: number
  regime: string
  action_taken: string | null
  order_id: string | null
}

interface DecisionHistoryProps {
  symbol?: string
  limit?: number
}

export function DecisionHistory({ symbol, limit = 10 }: DecisionHistoryProps) {
  const apiKey = useAuthStore((s) => s.apiKey)

  const { data: decisions } = useQuery<DecisionRecord[]>({
    queryKey: ['ai-decisions', symbol, limit],
    queryFn: async () => {
      const params: Record<string, string> = { apikey: apiKey ?? '', limit: String(limit) }
      if (symbol) params.symbol = symbol
      try {
        const response = await apiClient.post('/agent/history', params)
        return response.data?.data ?? []
      } catch (err: unknown) {
        // Handle 404 gracefully -- endpoint may not exist yet
        if (err && typeof err === 'object' && 'response' in err) {
          const axiosErr = err as { response?: { status?: number } }
          if (axiosErr.response?.status === 404) {
            return []
          }
        }
        throw err
      }
    },
    enabled: !!apiKey,
    staleTime: 30_000,
  })

  if (!decisions || decisions.length === 0) {
    return <p className="text-xs text-muted-foreground text-center py-2">No history yet</p>
  }

  return (
    <div className="max-h-48 overflow-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs">Time</TableHead>
            <TableHead className="text-xs">Symbol</TableHead>
            <TableHead className="text-xs">Signal</TableHead>
            <TableHead className="text-xs text-right">Conf.</TableHead>
            <TableHead className="text-xs">Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {decisions.map((d) => (
            <TableRow key={d.id}>
              <TableCell className="text-xs font-mono">{new Date(d.timestamp).toLocaleTimeString()}</TableCell>
              <TableCell className="text-xs">{d.symbol}</TableCell>
              <TableCell><SignalBadge signal={d.signal} size="sm" /></TableCell>
              <TableCell className="text-xs text-right">{d.confidence.toFixed(0)}%</TableCell>
              <TableCell className="text-xs">{d.action_taken ?? '—'}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

import { Badge } from '@/components/ui/badge'
import { SIGNAL_CONFIG, type ScanResult } from '@/types/ai-analysis'

interface EnhancedScannerProps {
  results: ScanResult[]
  onSelectSymbol?: (symbol: string) => void
}

function formatPrice(val: number | undefined): string {
  if (!val || val === 0) return '—'
  return val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function EnhancedScanner({ results, onSelectSymbol }: EnhancedScannerProps) {
  if (!results || results.length === 0) {
    return <p className="text-sm text-muted-foreground">No scan results</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="text-left py-2 px-2">Symbol</th>
            <th className="text-center py-2 px-1">Signal</th>
            <th className="text-right py-2 px-1">Score</th>
            <th className="text-right py-2 px-1">Entry</th>
            <th className="text-right py-2 px-1">SL</th>
            <th className="text-right py-2 px-1">Target</th>
            <th className="text-right py-2 px-1">R:R</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r) => {
            const signalCfg = r.signal ? SIGNAL_CONFIG[r.signal] : null
            const ts = r.trade_setup
            return (
              <tr
                key={r.symbol}
                className="border-b hover:bg-muted/50 cursor-pointer transition-colors"
                onClick={() => onSelectSymbol?.(r.symbol)}
              >
                <td className="py-2 px-2 font-medium">{r.symbol}</td>
                <td className="py-2 px-1 text-center">
                  {signalCfg ? (
                    <Badge className={`${signalCfg.bgColor} ${signalCfg.color} text-xs`}>
                      {signalCfg.label}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
                <td className="py-2 px-1 text-right font-mono">
                  {r.score ? r.score.toFixed(1) : '—'}
                </td>
                <td className="py-2 px-1 text-right font-mono text-blue-600">
                  {formatPrice(ts?.entry)}
                </td>
                <td className="py-2 px-1 text-right font-mono text-red-600">
                  {formatPrice(ts?.stop_loss)}
                </td>
                <td className="py-2 px-1 text-right font-mono text-green-600">
                  {formatPrice(ts?.target_1)}
                </td>
                <td className="py-2 px-1 text-right font-mono">
                  {ts?.risk_reward_1 ? `1:${ts.risk_reward_1.toFixed(1)}` : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

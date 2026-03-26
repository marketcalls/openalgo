// frontend/src/components/ai-analysis/IndicatorTable.tsx
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { IndicatorValues } from '@/types/ai-analysis'

interface IndicatorTableProps {
  indicators: IndicatorValues
}

const INDICATOR_LABELS: Record<string, string> = {
  rsi_14: 'RSI (14)', rsi_7: 'RSI (7)',
  macd: 'MACD', macd_signal: 'MACD Signal', macd_hist: 'MACD Histogram',
  ema_9: 'EMA (9)', ema_21: 'EMA (21)', sma_50: 'SMA (50)', sma_200: 'SMA (200)',
  adx_14: 'ADX (14)', bb_high: 'BB Upper', bb_low: 'BB Lower', bb_pband: 'BB %B',
  supertrend: 'Supertrend', supertrend_dir: 'ST Direction',
  atr_14: 'ATR (14)', stoch_k: 'Stoch %K', stoch_d: 'Stoch %D',
  obv: 'OBV', vwap: 'VWAP',
}

export function IndicatorTable({ indicators }: IndicatorTableProps) {
  const entries = Object.entries(indicators).filter(([, v]) => v !== undefined && v !== null)

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Indicator</TableHead>
          <TableHead className="text-right">Value</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map(([key, value]) => (
          <TableRow key={key}>
            <TableCell>{INDICATOR_LABELS[key] ?? key}</TableCell>
            <TableCell className="text-right font-mono">{Number(value).toFixed(2)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { DailyPnLEntry } from '@/types/strategy-dashboard'

interface EquityCurveChartProps {
  data: DailyPnLEntry[]
}

const currencyFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: Array<{ value: number; dataKey: string }>
  label?: string
}) {
  if (!active || !payload?.length) return null

  return (
    <div className="bg-popover border rounded-lg shadow-lg p-3 text-sm">
      <p className="text-muted-foreground mb-1">{label}</p>
      {payload.map((item) => (
        <p key={item.dataKey} className="font-mono tabular-nums">
          <span className="text-muted-foreground">
            {item.dataKey === 'cumulative_pnl' ? 'P&L: ' : 'DD: '}
          </span>
          <span
            className={
              item.value >= 0 ? 'text-green-600' : 'text-red-600'
            }
          >
            {currencyFormat.format(item.value)}
          </span>
        </p>
      ))}
    </div>
  )
}

export function EquityCurveChart({ data }: EquityCurveChartProps) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[250px] text-muted-foreground text-sm">
        No data available
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={250}>
      <ComposedChart data={data}>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="hsl(var(--border))"
        />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 11 }}
          stroke="hsl(var(--muted-foreground))"
        />
        <YAxis
          tick={{ fontSize: 11 }}
          stroke="hsl(var(--muted-foreground))"
          tickFormatter={(v: number) => currencyFormat.format(v)}
        />
        <Tooltip content={<CustomTooltip />} />
        <Area
          dataKey="drawdown"
          fill="hsl(0 84% 60%)"
          fillOpacity={0.15}
          stroke="hsl(0 84% 60%)"
          strokeWidth={1}
        />
        <Line
          dataKey="cumulative_pnl"
          stroke="hsl(142 71% 45%)"
          strokeWidth={2}
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { DailyPnL } from '@/types/strategy-dashboard'

interface EquityCurveChartProps {
  data: DailyPnL[]
}

export function EquityCurveChart({ data }: EquityCurveChartProps) {
  if (data.length === 0) {
    return (
      <div className="h-[250px] flex items-center justify-center text-sm text-muted-foreground">
        No P&L data to display
      </div>
    )
  }

  const chartData = data.map((d) => ({
    date: d.date,
    pnl: d.cumulative_pnl,
    daily: d.total_pnl,
  }))

  const lastPnl = chartData[chartData.length - 1]?.pnl || 0
  const color = lastPnl >= 0 ? '#16a34a' : '#dc2626'

  return (
    <ResponsiveContainer width="100%" height={250}>
      <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 0 }}>
        <defs>
          <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.3} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 10 }}
          tickFormatter={(v: string) => {
            const parts = v.split('-')
            return `${parts[2]}/${parts[1]}`
          }}
        />
        <YAxis tick={{ fontSize: 10 }} />
        <Tooltip
          contentStyle={{
            fontSize: 12,
            borderRadius: 8,
          }}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          formatter={(value: any, name: any) => [
            typeof value === 'number' ? value.toFixed(2) : String(value ?? '0.00'),
            name === 'pnl' ? 'Cumulative' : 'Daily',
          ]}
          labelFormatter={(label) => `Date: ${String(label)}`}
        />
        <Area
          type="monotone"
          dataKey="pnl"
          stroke={color}
          fill="url(#pnlGradient)"
          strokeWidth={2}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

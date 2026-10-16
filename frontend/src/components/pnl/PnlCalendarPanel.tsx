// frontend/src/components/pnl/PnlCalendarPanel.tsx
/**
 * The calendar heat map of the P&L page (fork-only): one square per day,
 * coloured by that day's realized P&L for the current selection. Collapsible.
 */
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import { CalendarHeatmap, type CalendarHeatmapDay } from '@/components/reports/CalendarHeatmap'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { PnlModel } from '@/lib/pnlModel'
import { pnlHeatColor } from '@/lib/pnlPalette'

interface Props {
  model: PnlModel
  startDate: string
  endDate: string
  formatCurrency: (value: number) => string
}

export function PnlCalendarPanel({ model, startDate, endDate, formatCurrency }: Props) {
  const [open, setOpen] = useState(true)
  const days: CalendarHeatmapDay[] = useMemo(
    () =>
      model.realizedSeries.dates.map((date, i) => ({
        date,
        value: model.realizedSeries.total[i],
        tooltip: `${date}: ${formatCurrency(model.realizedSeries.total[i])}`,
      })),
    [model.realizedSeries, formatCurrency]
  )

  return (
    <Card>
      <CardHeader className="pb-3">
        <button
          type="button"
          className="flex items-start gap-2 text-left"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
        >
          {open ? (
            <ChevronDown className="mt-1 h-4 w-4" />
          ) : (
            <ChevronRight className="mt-1 h-4 w-4" />
          )}
          <span>
            <CardTitle className="text-base">Calendar</CardTitle>
            <CardDescription>Realized P&L by day, for the selection</CardDescription>
          </span>
        </button>
      </CardHeader>
      {open && (
        <CardContent>
          <CalendarHeatmap
            days={days}
            startDate={startDate}
            endDate={endDate}
            colorFor={pnlHeatColor}
          />
        </CardContent>
      )}
    </Card>
  )
}

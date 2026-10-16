// frontend/src/components/reports/PnlFilterBar.tsx
/**
 * One filter bar for the merged P&L page (fork-only): Segment, P&L type, date
 * range with presets, and Fetch. Segment and P&L type have no default.
 */
import { RefreshCw } from 'lucide-react'
import { DateRangePresets } from '@/components/reports/DateRangePresets'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { usePnlFilters } from '@/hooks/usePnlFilters'

type Filters = ReturnType<typeof usePnlFilters>

export function PnlFilterBar({ filters }: { filters: Filters }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex flex-col sm:flex-row sm:items-end gap-4">
          <div className="flex-1 space-y-1">
            <Label htmlFor="pnl-segment">Segment</Label>
            <Select
              value={filters.segment}
              onValueChange={(v) => filters.setSegment(v as typeof filters.segment)}
            >
              <SelectTrigger id="pnl-segment">
                <SelectValue placeholder="Select segment" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                <SelectItem value="equity">Equity</SelectItem>
                <SelectItem value="fno">Futures & Options</SelectItem>
                <SelectItem value="currency">Currency</SelectItem>
                <SelectItem value="commodity">Commodity</SelectItem>
                <SelectItem value="mutual_fund">Mutual Funds</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex-1 space-y-1">
            <Label htmlFor="pnl-type">P&L</Label>
            <Select
              value={filters.pnlType}
              onValueChange={(v) => filters.setPnlType(v as typeof filters.pnlType)}
            >
              <SelectTrigger id="pnl-type">
                <SelectValue placeholder="Select P&L type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="realized">Realized</SelectItem>
                <SelectItem value="unrealized">Unrealized</SelectItem>
                <SelectItem value="combined">Combined</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex-1 space-y-1">
            <Label htmlFor="pnl-start-date">Start date</Label>
            <Input
              id="pnl-start-date"
              type="date"
              value={filters.startDate}
              max={filters.endDate}
              onChange={(e) => filters.setStartDate(e.target.value)}
            />
          </div>
          <div className="flex-1 space-y-1">
            <Label htmlFor="pnl-end-date">End date</Label>
            <Input
              id="pnl-end-date"
              type="date"
              value={filters.endDate}
              min={filters.startDate}
              max={filters.today}
              onChange={(e) => filters.setEndDate(e.target.value)}
            />
          </div>
          <Button
            onClick={filters.fetch}
            disabled={!filters.ready}
            aria-label="Fetch the P&L report"
            title={filters.ready ? undefined : 'Choose a segment and a P&L type first'}
          >
            <RefreshCw className="h-4 w-4 mr-2" />
            Fetch
          </Button>
        </div>
        <div className="flex flex-col sm:flex-row gap-4 mt-4">
          <div className="hidden sm:block flex-[2]" />
          <div className="flex-[2]">
            <DateRangePresets
              activeKey={filters.activePreset}
              onSelect={(start, end, key) => {
                if (filters.ready) filters.applyPreset(start, end, key)
                else {
                  filters.setStartDate(start)
                  filters.setEndDate(end)
                }
              }}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

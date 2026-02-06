import { Loader2, Play, X } from 'lucide-react'
import { useState } from 'react'
import { showToast } from '@/utils/toast'
import { strategyDashboardApi } from '@/api/strategy-dashboard'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PositionTable } from '../PositionTable'
import type { StrategySymbolMapping } from '@/types/strategy'
import type { DashboardStrategy } from '@/types/strategy-dashboard'

interface LivePositionsSectionProps {
  strategy: DashboardStrategy
  mappings: StrategySymbolMapping[]
  flashMap: Map<number, 'profit' | 'loss'>
  onRefresh: () => void
}

export function LivePositionsSection({
  strategy,
  mappings,
  flashMap,
  onRefresh,
}: LivePositionsSectionProps) {
  const [closingAll, setClosingAll] = useState(false)
  // Manual entry state
  const [entryOpen, setEntryOpen] = useState(false)
  const [entryMappingId, setEntryMappingId] = useState('')
  const [entryAction, setEntryAction] = useState<'BUY' | 'SELL'>('BUY')
  const [entryQuantity, setEntryQuantity] = useState('')
  const [submittingEntry, setSubmittingEntry] = useState(false)

  const activePositions = strategy.positions.filter(
    (p) => p.position_state === 'active' || p.position_state === 'pending_entry'
  )

  const handleClosePosition = async (positionId: number) => {
    try {
      const res = await strategyDashboardApi.closePosition(strategy.id, positionId)
      if (res.status === 'success') {
        showToast.success('Position close order placed', 'positions')
      } else {
        showToast.error(res.message || 'Failed to close position', 'positions')
      }
    } catch {
      showToast.error('Failed to close position', 'positions')
    }
  }

  const handleCloseAll = async () => {
    setClosingAll(true)
    try {
      const res = await strategyDashboardApi.closeAllPositions(strategy.id)
      if (res.status === 'success') {
        showToast.success('Close all orders placed', 'positions')
        onRefresh()
      } else {
        showToast.error(res.message || 'Failed to close all', 'positions')
      }
    } catch {
      showToast.error('Failed to close all positions', 'positions')
    } finally {
      setClosingAll(false)
    }
  }

  const handleManualEntry = async () => {
    if (!entryMappingId || !entryQuantity || Number(entryQuantity) < 1) {
      showToast.error('Please select a symbol and enter valid quantity', 'strategy')
      return
    }
    setSubmittingEntry(true)
    try {
      const res = await strategyDashboardApi.manualEntry(strategy.id, {
        mapping_id: Number(entryMappingId),
        action: entryAction,
        quantity: Number(entryQuantity),
      })
      if (res.status === 'success') {
        showToast.success('Manual entry order placed', 'strategy')
        setEntryOpen(false)
        setEntryMappingId('')
        setEntryQuantity('')
        onRefresh()
      } else {
        showToast.error(res.message || 'Failed to place order', 'strategy')
      }
    } catch {
      showToast.error('Failed to place manual entry', 'strategy')
    } finally {
      setSubmittingEntry(false)
    }
  }

  // When a mapping is selected, pre-fill quantity
  const handleMappingSelect = (mappingId: string) => {
    setEntryMappingId(mappingId)
    const mapping = mappings.find((m) => m.id === Number(mappingId))
    if (mapping) {
      setEntryQuantity(mapping.quantity.toString())
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3 flex flex-row items-center justify-between">
        <div>
          <CardTitle className="text-sm">
            Live Positions
            {activePositions.length > 0 && (
              <Badge variant="secondary" className="ml-2 text-xs">
                {activePositions.length}
              </Badge>
            )}
          </CardTitle>
          <CardDescription className="text-xs">
            Open positions tracked by risk engine
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {/* Manual Entry */}
          <Dialog open={entryOpen} onOpenChange={setEntryOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" disabled={mappings.length === 0}>
                <Play className="h-3.5 w-3.5 mr-1" />
                Manual Entry
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>Manual Entry</DialogTitle>
                <DialogDescription>
                  Place a manual entry order for {strategy.name}
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label>Symbol</Label>
                  <Select value={entryMappingId} onValueChange={handleMappingSelect}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select symbol..." />
                    </SelectTrigger>
                    <SelectContent>
                      {mappings.map((m) => (
                        <SelectItem key={m.id} value={m.id.toString()}>
                          {m.symbol} ({m.exchange}) — {m.product_type}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Action</Label>
                  <Tabs
                    value={entryAction}
                    onValueChange={(v) => setEntryAction(v as 'BUY' | 'SELL')}
                  >
                    <TabsList className="grid w-full grid-cols-2">
                      <TabsTrigger value="BUY">BUY</TabsTrigger>
                      <TabsTrigger value="SELL">SELL</TabsTrigger>
                    </TabsList>
                  </Tabs>
                </div>
                <div className="space-y-2">
                  <Label>Quantity</Label>
                  <Input
                    type="number"
                    min="1"
                    value={entryQuantity}
                    onChange={(e) => setEntryQuantity(e.target.value)}
                    placeholder="Enter quantity"
                    className="font-mono"
                  />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setEntryOpen(false)}>
                  Cancel
                </Button>
                <Button onClick={handleManualEntry} disabled={submittingEntry}>
                  {submittingEntry && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
                  Place Order
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          {/* Close All */}
          {activePositions.length > 0 && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" size="sm" disabled={closingAll}>
                  {closingAll ? (
                    <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  ) : (
                    <X className="h-4 w-4 mr-1" />
                  )}
                  Close All
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Close All Positions</AlertDialogTitle>
                  <AlertDialogDescription>
                    Close all {activePositions.length} position(s) for &quot;{strategy.name}&quot;
                    at MARKET? This will place immediate exit orders.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={handleCloseAll}
                    className="bg-red-600 hover:bg-red-700"
                  >
                    Close All
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <PositionTable
          positions={strategy.positions}
          flashMap={flashMap}
          riskMonitoring={strategy.risk_monitoring}
          onClosePosition={handleClosePosition}
        />
      </CardContent>
    </Card>
  )
}

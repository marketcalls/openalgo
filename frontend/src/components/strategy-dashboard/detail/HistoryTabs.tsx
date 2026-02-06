import { useRef, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { OrdersPanel } from '../OrdersPanel'
import { TradesPanel } from '../TradesPanel'
import { PnlPanel } from '../PnlPanel'

interface HistoryTabsProps {
  strategyId: number
  strategyName: string
}

export function HistoryTabs({ strategyId, strategyName }: HistoryTabsProps) {
  const [activeTab, setActiveTab] = useState('orders')
  const loadedTabs = useRef(new Set<string>(['orders']))

  const handleTabChange = (tab: string) => {
    loadedTabs.current.add(tab)
    setActiveTab(tab)
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <Tabs value={activeTab} onValueChange={handleTabChange}>
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="orders">Orders</TabsTrigger>
            <TabsTrigger value="trades">Trades</TabsTrigger>
            <TabsTrigger value="pnl">P&L Analytics</TabsTrigger>
          </TabsList>

          <TabsContent value="orders" className="mt-4">
            {loadedTabs.current.has('orders') && (
              <OrdersPanel strategyId={strategyId} strategyName={strategyName} />
            )}
          </TabsContent>

          <TabsContent value="trades" className="mt-4">
            {loadedTabs.current.has('trades') && (
              <TradesPanel strategyId={strategyId} strategyName={strategyName} />
            )}
          </TabsContent>

          <TabsContent value="pnl" className="mt-4">
            {loadedTabs.current.has('pnl') && (
              <PnlPanel strategyId={strategyId} strategyName={strategyName} />
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}

import { ChevronDown, ChevronRight, Download, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { showToast } from '@/utils/toast'
import { tradingApi } from '@/api/trading'
import type { Trade } from '@/types/trading'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useLivePrice, type PriceableItem } from '@/hooks/useLivePrice'
import { usePageVisibility } from '@/hooks/usePageVisibility'
import { useAuthStore } from '@/stores/authStore'

// Extended trade interface for P&L computation
interface TradeLeg extends PriceableItem {
    symbol: string
    exchange: string
    buyQty: number
    sellQty: number
    netQty: number
    avgBuyPrice: number
    avgSellPrice: number
    ltp: number
    realizedPnl: number
    unrealizedPnl: number
    product: string
    quantity: number
    average_price: number
}

interface StrategyGroup {
    name: string
    legs: TradeLeg[]
    totalRealizedPnl: number
    totalUnrealizedPnl: number
    totalPnl: number
}

// Format number as currency
function formatCurrency(value: number): string {
    const absValue = Math.abs(value)
    const formatted = new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(absValue)
    return value < 0 ? `-${formatted}` : formatted
}

// Format number with sign
function formatWithSign(value: number): string {
    if (value > 0) return `+${formatCurrency(value)}`
    return formatCurrency(value)
}

export default function IntradayPnl() {
    const { apiKey } = useAuthStore()
    const [trades, setTrades] = useState<Trade[]>([])
    const [isLoading, setIsLoading] = useState(true)
    const [isRefreshing, setIsRefreshing] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [collapsedStrategies, setCollapsedStrategies] = useState<Set<string>>(new Set())

    // Page visibility for refresh on return
    const { wasHidden, timeSinceHidden } = usePageVisibility()

    // Fetch tradebook data
    const fetchTrades = useCallback(
        async (showRefreshing = false) => {
            if (!apiKey) return

            if (showRefreshing) setIsRefreshing(true)
            else setIsLoading(true)

            try {
                const response = await tradingApi.getTrades(apiKey)
                if (response.status === 'success' && response.data) {
                    // Filter only intraday (MIS) trades
                    const intradayTrades = response.data.filter((t) => t.product === 'MIS')
                    setTrades(intradayTrades)
                    setError(null)
                } else {
                    setError(response.message || 'Failed to fetch trades')
                }
            } catch (err) {
                setError('Failed to fetch tradebook')
                console.error('Tradebook fetch error:', err)
            } finally {
                setIsLoading(false)
                setIsRefreshing(false)
            }
        },
        [apiKey]
    )

    // Initial fetch
    useEffect(() => {
        fetchTrades()
    }, [fetchTrades])

    // Refresh on visibility return after 30s
    useEffect(() => {
        if (wasHidden && timeSinceHidden > 30000) {
            fetchTrades(true)
        }
    }, [wasHidden, timeSinceHidden, fetchTrades])

    // Group trades by strategy and symbol
    const strategyLegs = useMemo((): TradeLeg[] => {
        const legMap = new Map<string, TradeLeg>()

        trades.forEach((trade) => {
            const strategy = trade.strategy || 'Untagged'
            const key = `${strategy}:${trade.symbol}:${trade.exchange}`

            const existing = legMap.get(key)
            if (existing) {
                if (trade.action === 'BUY') {
                    const totalBuyValue = existing.avgBuyPrice * existing.buyQty + trade.average_price * trade.quantity
                    existing.buyQty += trade.quantity
                    existing.avgBuyPrice = existing.buyQty > 0 ? totalBuyValue / existing.buyQty : 0
                } else {
                    const totalSellValue = existing.avgSellPrice * existing.sellQty + trade.average_price * trade.quantity
                    existing.sellQty += trade.quantity
                    existing.avgSellPrice = existing.sellQty > 0 ? totalSellValue / existing.sellQty : 0
                }
                existing.netQty = existing.buyQty - existing.sellQty
                existing.quantity = Math.abs(existing.netQty)
                existing.average_price = existing.netQty > 0 ? existing.avgBuyPrice : existing.avgSellPrice
            } else {
                const isBuy = trade.action === 'BUY'
                legMap.set(key, {
                    symbol: trade.symbol,
                    exchange: trade.exchange,
                    buyQty: isBuy ? trade.quantity : 0,
                    sellQty: isBuy ? 0 : trade.quantity,
                    netQty: isBuy ? trade.quantity : -trade.quantity,
                    avgBuyPrice: isBuy ? trade.average_price : 0,
                    avgSellPrice: isBuy ? 0 : trade.average_price,
                    ltp: 0,
                    realizedPnl: 0,
                    unrealizedPnl: 0,
                    product: trade.product,
                    quantity: trade.quantity,
                    average_price: trade.average_price,
                })
            }
        })

        return Array.from(legMap.values())
    }, [trades])

    // Use live price hook for real-time LTP
    const { data: legsWithLtp, isLive } = useLivePrice(strategyLegs, {
        enabled: strategyLegs.length > 0,
        useMultiQuotesFallback: true,
        pauseWhenHidden: true,
    })

    // Group by strategy and calculate P&L
    const strategies = useMemo((): StrategyGroup[] => {
        const strategyMap = new Map<string, StrategyGroup>()

        // Map legs back to original trades to get strategy name
        const legToStrategy = new Map<string, string>()
        trades.forEach((trade) => {
            const strategy = trade.strategy || 'Untagged'
            const key = `${trade.symbol}:${trade.exchange}`
            legToStrategy.set(key, strategy)
        })

        legsWithLtp.forEach((leg) => {
            // Find strategy from original trades
            const legKey = `${leg.symbol}:${leg.exchange}`
            const strategyName = legToStrategy.get(legKey) || 'Untagged'

            // Calculate P&L for this leg
            const closedQty = Math.min(leg.buyQty, leg.sellQty)
            const openQty = leg.netQty
            const ltp = leg.ltp || 0

            // Realized P&L: closed trades
            let realizedPnl = 0
            if (closedQty > 0 && leg.avgBuyPrice > 0 && leg.avgSellPrice > 0) {
                realizedPnl = (leg.avgSellPrice - leg.avgBuyPrice) * closedQty
            }

            // Unrealized P&L: open positions
            let unrealizedPnl = 0
            if (openQty !== 0 && ltp > 0) {
                const avgPrice = openQty > 0 ? leg.avgBuyPrice : leg.avgSellPrice
                if (openQty > 0) {
                    // Long position
                    unrealizedPnl = (ltp - avgPrice) * openQty
                } else {
                    // Short position
                    unrealizedPnl = (avgPrice - ltp) * Math.abs(openQty)
                }
            }

            const legWithPnl: TradeLeg = {
                ...leg,
                ltp,
                realizedPnl,
                unrealizedPnl,
            }

            const existing = strategyMap.get(strategyName)
            if (existing) {
                existing.legs.push(legWithPnl)
                existing.totalRealizedPnl += realizedPnl
                existing.totalUnrealizedPnl += unrealizedPnl
                existing.totalPnl = existing.totalRealizedPnl + existing.totalUnrealizedPnl
            } else {
                strategyMap.set(strategyName, {
                    name: strategyName,
                    legs: [legWithPnl],
                    totalRealizedPnl: realizedPnl,
                    totalUnrealizedPnl: unrealizedPnl,
                    totalPnl: realizedPnl + unrealizedPnl,
                })
            }
        })

        // Sort strategies by name
        return Array.from(strategyMap.values()).sort((a, b) => a.name.localeCompare(b.name))
    }, [legsWithLtp, trades])

    // Calculate totals
    const totals = useMemo(() => {
        return strategies.reduce(
            (acc, strategy) => ({
                realizedPnl: acc.realizedPnl + strategy.totalRealizedPnl,
                unrealizedPnl: acc.unrealizedPnl + strategy.totalUnrealizedPnl,
                totalPnl: acc.totalPnl + strategy.totalPnl,
            }),
            { realizedPnl: 0, unrealizedPnl: 0, totalPnl: 0 }
        )
    }, [strategies])

    // Toggle strategy collapse
    const toggleStrategy = (name: string) => {
        setCollapsedStrategies((prev) => {
            const next = new Set(prev)
            if (next.has(name)) {
                next.delete(name)
            } else {
                next.add(name)
            }
            return next
        })
    }

    // Export to CSV
    const exportCsv = () => {
        const headers = [
            'Strategy',
            'Symbol',
            'Exchange',
            'Buy Qty',
            'Sell Qty',
            'Net Qty',
            'Avg Buy Price',
            'Avg Sell Price',
            'LTP',
            'Realized P&L',
            'Unrealized P&L',
            'Total P&L',
        ]

        const rows = strategies.flatMap((strategy) =>
            strategy.legs.map((leg) => [
                strategy.name,
                leg.symbol,
                leg.exchange,
                leg.buyQty,
                leg.sellQty,
                leg.netQty,
                leg.avgBuyPrice.toFixed(2),
                leg.avgSellPrice.toFixed(2),
                leg.ltp.toFixed(2),
                leg.realizedPnl.toFixed(2),
                leg.unrealizedPnl.toFixed(2),
                (leg.realizedPnl + leg.unrealizedPnl).toFixed(2),
            ])
        )

        const csv = [headers.join(','), ...rows.map((row) => row.join(','))].join('\n')
        const blob = new Blob([csv], { type: 'text/csv' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `intraday_pnl_${new Date().toISOString().split('T')[0]}.csv`
        a.click()
        URL.revokeObjectURL(url)
        showToast.success('CSV exported successfully', 'system')
    }

    // Loading skeleton
    if (isLoading) {
        return (
            <div className="container mx-auto py-6 space-y-6">
                <div className="flex justify-between items-center">
                    <Skeleton className="h-8 w-48" />
                    <Skeleton className="h-10 w-32" />
                </div>
                <div className="grid gap-4 md:grid-cols-3">
                    {[1, 2, 3].map((i) => (
                        <Skeleton key={i} className="h-24" />
                    ))}
                </div>
                <Skeleton className="h-64" />
            </div>
        )
    }

    return (
        <div className="container mx-auto py-6 space-y-6">
            {/* Header */}
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">Intraday P&L</h1>
                    <p className="text-muted-foreground">
                        Today's strategy-wise P&L from tradebook
                        {isLive && (
                            <span className="ml-2 inline-flex items-center gap-1 text-green-600">
                                <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                                Live
                            </span>
                        )}
                    </p>
                </div>
                <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => fetchTrades(true)} disabled={isRefreshing}>
                        <RefreshCw className={cn('h-4 w-4 mr-2', isRefreshing && 'animate-spin')} />
                        Refresh
                    </Button>
                    <Button variant="outline" size="sm" onClick={exportCsv} disabled={strategies.length === 0}>
                        <Download className="h-4 w-4 mr-2" />
                        Export CSV
                    </Button>
                </div>
            </div>

            {/* Error state */}
            {error && (
                <Card className="border-destructive">
                    <CardContent className="pt-6">
                        <p className="text-destructive">{error}</p>
                    </CardContent>
                </Card>
            )}

            {/* KPI Cards */}
            <div className="grid gap-4 md:grid-cols-3">
                <Card>
                    <CardHeader className="pb-2">
                        <CardDescription>Realized P&L</CardDescription>
                        <CardTitle
                            className={cn(
                                'text-2xl',
                                totals.realizedPnl >= 0 ? 'text-green-600' : 'text-red-600'
                            )}
                        >
                            {formatWithSign(totals.realizedPnl)}
                        </CardTitle>
                    </CardHeader>
                </Card>
                <Card>
                    <CardHeader className="pb-2">
                        <CardDescription>Unrealized P&L</CardDescription>
                        <CardTitle
                            className={cn(
                                'text-2xl',
                                totals.unrealizedPnl >= 0 ? 'text-green-600' : 'text-red-600'
                            )}
                        >
                            {formatWithSign(totals.unrealizedPnl)}
                        </CardTitle>
                    </CardHeader>
                </Card>
                <Card>
                    <CardHeader className="pb-2">
                        <CardDescription>Total P&L</CardDescription>
                        <CardTitle
                            className={cn(
                                'text-2xl',
                                totals.totalPnl >= 0 ? 'text-green-600' : 'text-red-600'
                            )}
                        >
                            {formatWithSign(totals.totalPnl)}
                        </CardTitle>
                    </CardHeader>
                </Card>
            </div>

            {/* No trades message */}
            {strategies.length === 0 && !error && (
                <Card>
                    <CardContent className="py-12 text-center">
                        <p className="text-muted-foreground">No intraday trades found for today</p>
                    </CardContent>
                </Card>
            )}

            {/* Strategy Cards */}
            <div className="space-y-4">
                {strategies.map((strategy) => {
                    const isCollapsed = collapsedStrategies.has(strategy.name)
                    return (
                        <Card key={strategy.name}>
                            <CardHeader
                                className="cursor-pointer flex flex-row items-center justify-between py-4"
                                onClick={() => toggleStrategy(strategy.name)}
                            >
                                <div className="flex items-center gap-2">
                                    {isCollapsed ? (
                                        <ChevronRight className="h-5 w-5 text-muted-foreground" />
                                    ) : (
                                        <ChevronDown className="h-5 w-5 text-muted-foreground" />
                                    )}
                                    <CardTitle className="text-lg">{strategy.name}</CardTitle>
                                    <span className="text-sm text-muted-foreground">({strategy.legs.length} legs)</span>
                                </div>
                                <div className="flex items-center gap-4">
                                    <div className="text-right">
                                        <div className="text-sm text-muted-foreground">Realized</div>
                                        <div
                                            className={cn(
                                                'font-medium',
                                                strategy.totalRealizedPnl >= 0 ? 'text-green-600' : 'text-red-600'
                                            )}
                                        >
                                            {formatWithSign(strategy.totalRealizedPnl)}
                                        </div>
                                    </div>
                                    <div className="text-right">
                                        <div className="text-sm text-muted-foreground">Unrealized</div>
                                        <div
                                            className={cn(
                                                'font-medium',
                                                strategy.totalUnrealizedPnl >= 0 ? 'text-green-600' : 'text-red-600'
                                            )}
                                        >
                                            {formatWithSign(strategy.totalUnrealizedPnl)}
                                        </div>
                                    </div>
                                    <div className="text-right min-w-[100px]">
                                        <div className="text-sm text-muted-foreground">Total</div>
                                        <div className="flex items-center gap-1">
                                            {strategy.totalPnl >= 0 ? (
                                                <TrendingUp className="h-4 w-4 text-green-600" />
                                            ) : (
                                                <TrendingDown className="h-4 w-4 text-red-600" />
                                            )}
                                            <span
                                                className={cn(
                                                    'font-bold',
                                                    strategy.totalPnl >= 0 ? 'text-green-600' : 'text-red-600'
                                                )}
                                            >
                                                {formatWithSign(strategy.totalPnl)}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                            </CardHeader>

                            {/* Leg details table */}
                            {!isCollapsed && (
                                <CardContent className="pt-0">
                                    <div className="overflow-x-auto">
                                        <table className="w-full text-sm">
                                            <thead>
                                                <tr className="border-b">
                                                    <th className="text-left py-2 font-medium">Symbol</th>
                                                    <th className="text-right py-2 font-medium">Buy Qty</th>
                                                    <th className="text-right py-2 font-medium">Sell Qty</th>
                                                    <th className="text-right py-2 font-medium">Net Qty</th>
                                                    <th className="text-right py-2 font-medium">Avg Buy</th>
                                                    <th className="text-right py-2 font-medium">Avg Sell</th>
                                                    <th className="text-right py-2 font-medium">LTP</th>
                                                    <th className="text-right py-2 font-medium">Realized</th>
                                                    <th className="text-right py-2 font-medium">Unrealized</th>
                                                    <th className="text-right py-2 font-medium">P&L</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {strategy.legs.map((leg, idx) => {
                                                    const totalLegPnl = leg.realizedPnl + leg.unrealizedPnl
                                                    return (
                                                        <tr key={idx} className="border-b last:border-0 hover:bg-muted/50">
                                                            <td className="py-2">
                                                                <div className="font-medium">{leg.symbol}</div>
                                                                <div className="text-xs text-muted-foreground">{leg.exchange}</div>
                                                            </td>
                                                            <td className="text-right py-2 text-green-600">{leg.buyQty || '-'}</td>
                                                            <td className="text-right py-2 text-red-600">{leg.sellQty || '-'}</td>
                                                            <td
                                                                className={cn(
                                                                    'text-right py-2 font-medium',
                                                                    leg.netQty > 0 ? 'text-green-600' : leg.netQty < 0 ? 'text-red-600' : ''
                                                                )}
                                                            >
                                                                {leg.netQty > 0 ? '+' : ''}
                                                                {leg.netQty}
                                                            </td>
                                                            <td className="text-right py-2">
                                                                {leg.avgBuyPrice > 0 ? `₹${leg.avgBuyPrice.toFixed(2)}` : '-'}
                                                            </td>
                                                            <td className="text-right py-2">
                                                                {leg.avgSellPrice > 0 ? `₹${leg.avgSellPrice.toFixed(2)}` : '-'}
                                                            </td>
                                                            <td className="text-right py-2 font-medium">
                                                                {leg.ltp > 0 ? `₹${leg.ltp.toFixed(2)}` : '-'}
                                                            </td>
                                                            <td
                                                                className={cn(
                                                                    'text-right py-2',
                                                                    leg.realizedPnl >= 0 ? 'text-green-600' : 'text-red-600'
                                                                )}
                                                            >
                                                                {formatWithSign(leg.realizedPnl)}
                                                            </td>
                                                            <td
                                                                className={cn(
                                                                    'text-right py-2',
                                                                    leg.unrealizedPnl >= 0 ? 'text-green-600' : 'text-red-600'
                                                                )}
                                                            >
                                                                {formatWithSign(leg.unrealizedPnl)}
                                                            </td>
                                                            <td
                                                                className={cn(
                                                                    'text-right py-2 font-bold',
                                                                    totalLegPnl >= 0 ? 'text-green-600' : 'text-red-600'
                                                                )}
                                                            >
                                                                {formatWithSign(totalLegPnl)}
                                                            </td>
                                                        </tr>
                                                    )
                                                })}
                                            </tbody>
                                        </table>
                                    </div>
                                </CardContent>
                            )}
                        </Card>
                    )
                })}
            </div>

            {/* Bottom Total Bar */}
            {strategies.length > 0 && (
                <Card className="bg-muted/50">
                    <CardContent className="py-4">
                        <div className="flex justify-between items-center">
                            <span className="font-medium">
                                Grand Total ({strategies.length} strategies, {strategies.reduce((acc, s) => acc + s.legs.length, 0)}{' '}
                                legs)
                            </span>
                            <div className="flex items-center gap-4">
                                <div className="text-right">
                                    <span className="text-sm text-muted-foreground mr-2">Realized:</span>
                                    <span
                                        className={cn('font-medium', totals.realizedPnl >= 0 ? 'text-green-600' : 'text-red-600')}
                                    >
                                        {formatWithSign(totals.realizedPnl)}
                                    </span>
                                </div>
                                <div className="text-right">
                                    <span className="text-sm text-muted-foreground mr-2">Unrealized:</span>
                                    <span
                                        className={cn('font-medium', totals.unrealizedPnl >= 0 ? 'text-green-600' : 'text-red-600')}
                                    >
                                        {formatWithSign(totals.unrealizedPnl)}
                                    </span>
                                </div>
                                <div className="text-right">
                                    <span className="text-sm text-muted-foreground mr-2">Total:</span>
                                    <span className={cn('font-bold text-lg', totals.totalPnl >= 0 ? 'text-green-600' : 'text-red-600')}>
                                        {formatWithSign(totals.totalPnl)}
                                    </span>
                                </div>
                            </div>
                        </div>
                    </CardContent>
                </Card>
            )}
        </div>
    )
}

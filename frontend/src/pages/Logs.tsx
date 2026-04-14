import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Download,
  FileText,
  RefreshCw,
  Search,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { webClient } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { JsonEditor } from '@/components/ui/json-editor'

interface LogEntry {
  id: number
  api_type: string
  request_data: Record<string, unknown>
  response_data: Record<string, unknown>
  strategy: string
  created_at: string
}

interface LogsResponse {
  logs: LogEntry[]
  total_pages: number
  current_page: number
}

export default function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [totalPages, setTotalPages] = useState(1)
  const [currentPage, setCurrentPage] = useState(1)
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)

  // Filters
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [searchQuery, setSearchQuery] = useState('')

  // Expanded log entries
  const [expandedLogs, setExpandedLogs] = useState<Set<number>>(new Set())

  const fetchLogs = useCallback(
    async (page: number = 1) => {
      try {
        const params = new URLSearchParams()
        params.append('page', page.toString())
        if (startDate) params.append('start_date', startDate)
        if (endDate) params.append('end_date', endDate)
        if (searchQuery) params.append('search', searchQuery)

        const response = await webClient.get<LogsResponse>(`/logs/?${params.toString()}`, {
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
          },
        })

        setLogs(Array.isArray(response.data.logs) ? response.data.logs : [])
        setTotalPages(response.data.total_pages || 1)
        setCurrentPage(response.data.current_page || 1)
      } catch (error) {
        showToast.error('Failed to load logs', 'monitoring')
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [startDate, endDate, searchQuery]
  )

  useEffect(() => {
    fetchLogs()
  }, [fetchLogs])

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!isLoading) {
        setCurrentPage(1)
        fetchLogs(1)
      }
    }, 300)

    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchLogs, isLoading])

  const handleRefresh = async () => {
    setIsRefreshing(true)
    await fetchLogs(currentPage)
    showToast.success('Logs refreshed', 'monitoring')
  }

  const handleExport = () => {
    const params = new URLSearchParams()
    if (startDate) params.append('start_date', startDate)
    if (endDate) params.append('end_date', endDate)
    if (searchQuery) params.append('search', searchQuery)

    window.open(`/logs/export?${params.toString()}`, '_blank')
  }

  const handleDateChange = () => {
    setCurrentPage(1)
    fetchLogs(1)
  }

  const toggleExpanded = (logId: number) => {
    setExpandedLogs((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(logId)) {
        newSet.delete(logId)
      } else {
        newSet.add(logId)
      }
      return newSet
    })
  }

  const getApiTypeBadgeColor = (apiType: string) => {
    switch (apiType) {
      case 'placeorder':
        return 'bg-blue-500 hover:bg-blue-600'
      case 'placesmartorder':
        return 'bg-purple-500 hover:bg-purple-600'
      case 'modifyorder':
        return 'bg-yellow-500 hover:bg-yellow-600'
      case 'cancelorder':
        return 'bg-red-500 hover:bg-red-600'
      case 'closeposition':
        return 'bg-green-500 hover:bg-green-600'
      default:
        return 'bg-gray-500 hover:bg-gray-600'
    }
  }

  const renderPagination = () => {
    if (totalPages <= 1) return null

    const pages: (number | string)[] = []
    const maxVisiblePages = 5

    if (totalPages <= maxVisiblePages) {
      for (let i = 1; i <= totalPages; i++) {
        pages.push(i)
      }
    } else {
      pages.push(1)
      if (currentPage > 3) {
        pages.push('...')
      }
      for (
        let i = Math.max(2, currentPage - 1);
        i <= Math.min(totalPages - 1, currentPage + 1);
        i++
      ) {
        if (!pages.includes(i)) {
          pages.push(i)
        }
      }
      if (currentPage < totalPages - 2) {
        pages.push('...')
      }
      if (!pages.includes(totalPages)) {
        pages.push(totalPages)
      }
    }

    return (
      <div className="flex items-center justify-center gap-1 mt-6">
        <Button
          variant="outline"
          size="icon"
          onClick={() => fetchLogs(currentPage - 1)}
          disabled={currentPage <= 1}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        {pages.map((page, index) => (
          <Button
            key={index}
            variant={page === currentPage ? 'default' : 'outline'}
            size="sm"
            onClick={() => typeof page === 'number' && fetchLogs(page)}
            disabled={typeof page !== 'number'}
          >
            {page}
          </Button>
        ))}
        <Button
          variant="outline"
          size="icon"
          onClick={() => fetchLogs(currentPage + 1)}
          disabled={currentPage >= totalPages}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Link to="/logs" className="text-muted-foreground hover:text-foreground">
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <FileText className="h-6 w-6" />
              Live Trading Logs
            </h1>
          </div>
          <p className="text-muted-foreground">View and search your real-time API trading logs</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleRefresh} disabled={isRefreshing}>
            <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button onClick={handleExport}>
            <Download className="h-4 w-4 mr-2" />
            Export to CSV
          </Button>
        </div>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Start Date</label>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                onBlur={handleDateChange}
                className="date-input-styled"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">End Date</label>
              <Input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                onBlur={handleDateChange}
                className="date-input-styled"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Search</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-primary" />
                <Input
                  type="text"
                  placeholder="Search logs..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-10"
                />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Logs */}
      <div className="space-y-4">
        {logs.length === 0 ? (
          <Card>
            <CardContent className="py-16 text-center text-muted-foreground">
              <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>No logs found for the selected date range</p>
            </CardContent>
          </Card>
        ) : (
          logs.map((log) => {
            const requestData = log.request_data || {}
            const isExpanded = expandedLogs.has(log.id)

            return (
              <Card key={log.id} className="hover:shadow-md transition-shadow">
                <CardContent className="p-6">
                  {/* Header Badges */}
                  <div className="flex flex-wrap gap-2 mb-4">
                    <Badge className={getApiTypeBadgeColor(log.api_type)}>{log.api_type}</Badge>
                    <Badge variant="outline" className="gap-1">
                      <Zap className="h-3 w-3" />
                      {log.strategy}
                    </Badge>
                    {requestData.action ? (
                      <Badge
                        variant={String(requestData.action) === 'BUY' ? 'default' : 'destructive'}
                        className={`gap-1 ${
                          String(requestData.action) === 'BUY'
                            ? 'bg-green-500 hover:bg-green-600'
                            : 'bg-red-500 hover:bg-red-600'
                        }`}
                      >
                        {String(requestData.action) === 'BUY' ? (
                          <ArrowUp className="h-3 w-3" />
                        ) : (
                          <ArrowDown className="h-3 w-3" />
                        )}
                        {String(requestData.action)}
                      </Badge>
                    ) : null}
                    {requestData.exchange ? (
                      <Badge variant="secondary">{String(requestData.exchange)}</Badge>
                    ) : null}
                    <Badge variant="outline" className="text-muted-foreground">
                      {log.created_at}
                    </Badge>
                  </div>

                  {/* Order Details */}
                  {requestData.symbol ||
                  requestData.quantity ||
                  requestData.price ||
                  requestData.product ? (
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
                      {requestData.symbol ? (
                        <div className="bg-muted rounded-lg p-3">
                          <p className="text-xs text-muted-foreground uppercase">Symbol</p>
                          <p className="font-semibold">{String(requestData.symbol)}</p>
                        </div>
                      ) : null}
                      {requestData.quantity ? (
                        <div className="bg-muted rounded-lg p-3">
                          <p className="text-xs text-muted-foreground uppercase">Quantity</p>
                          <p className="font-semibold">{String(requestData.quantity)}</p>
                        </div>
                      ) : null}
                      {requestData.price && String(requestData.price) !== '0' ? (
                        <div className="bg-muted rounded-lg p-3">
                          <p className="text-xs text-muted-foreground uppercase">Price</p>
                          <p className="font-semibold">{String(requestData.price)}</p>
                        </div>
                      ) : null}
                      {requestData.product ? (
                        <div className="bg-muted rounded-lg p-3">
                          <p className="text-xs text-muted-foreground uppercase">Product</p>
                          <p className="font-semibold">{String(requestData.product)}</p>
                        </div>
                      ) : null}
                      {requestData.pricetype ? (
                        <div className="bg-muted rounded-lg p-3">
                          <p className="text-xs text-muted-foreground uppercase">Price Type</p>
                          <p className="font-semibold">{String(requestData.pricetype)}</p>
                        </div>
                      ) : null}
                      {requestData.orderid ? (
                        <div className="bg-muted rounded-lg p-3">
                          <p className="text-xs text-muted-foreground uppercase">Order ID</p>
                          <p className="font-semibold text-sm truncate">
                            {String(requestData.orderid)}
                          </p>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  {/* Collapsible Request/Response */}
                  <Collapsible open={isExpanded} onOpenChange={() => toggleExpanded(log.id)}>
                    <CollapsibleTrigger asChild>
                      <Button
                        variant="ghost"
                        className="w-full justify-between bg-muted hover:bg-muted/80"
                      >
                        View Request/Response Data
                        {isExpanded ? (
                          <ChevronUp className="h-4 w-4" />
                        ) : (
                          <ChevronDown className="h-4 w-4" />
                        )}
                      </Button>
                    </CollapsibleTrigger>
                    <CollapsibleContent className="mt-4 space-y-4">
                      {(() => {
                        const requestJson = JSON.stringify(requestData, null, 2)
                        const responseJson = JSON.stringify(log.response_data, null, 2)
                        const requestLines = requestJson.split('\n').length
                        const responseLines = responseJson.split('\n').length
                        // Allow up to 70vh height, minimum 120px
                        const maxHeight = typeof window !== 'undefined' ? window.innerHeight * 0.7 : 600
                        const requestHeight = Math.min(Math.max(requestLines * 20 + 24, 120), maxHeight)
                        const responseHeight = Math.min(Math.max(responseLines * 20 + 24, 120), maxHeight)

                        return (
                          <>
                            <div className="bg-muted rounded-lg p-4">
                              <h4 className="text-sm font-medium mb-2">Request Data</h4>
                              <div className="rounded-lg border bg-card/50" style={{ height: requestHeight }}>
                                <JsonEditor
                                  value={requestJson}
                                  readOnly={true}
                                  lineWrapping={false}
                                />
                              </div>
                            </div>
                            <div className="bg-muted rounded-lg p-4">
                              <h4 className="text-sm font-medium mb-2">Response Data</h4>
                              <div className="rounded-lg border bg-card/50" style={{ height: responseHeight }}>
                                <JsonEditor
                                  value={responseJson}
                                  readOnly={true}
                                  lineWrapping={false}
                                />
                              </div>
                            </div>
                          </>
                        )
                      })()}
                    </CollapsibleContent>
                  </Collapsible>
                </CardContent>
              </Card>
            )
          })
        )}
      </div>

      {/* Pagination */}
      {renderPagination()}
    </div>
  )
}

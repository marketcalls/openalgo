import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle,
  Download,
  Eye,
  Filter,
  Users,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { JsonEditor } from '@/components/ui/json-editor'

interface ApiRequest {
  timestamp: string
  api_type: string
  source: string
  symbol?: string
  quantity?: number
  position_size?: number
  orderid?: string
  exchange?: string
  action?: string
  request_data: Record<string, unknown>
  response_data?: Record<string, unknown>
  analysis: {
    issues?: boolean | string[]
    error?: string
    error_type?: string
    warnings?: string[]
  }
}

interface Stats {
  total_requests: number
  issues: {
    total: number
  }
  symbols: string[]
  sources: string[]
}

interface AnalyzerData {
  requests: ApiRequest[]
  stats: Stats
}

const EXCHANGE_COLORS: Record<string, string> = {
  NSE: 'bg-cyan-500/10 text-cyan-600 border-cyan-500/30',
  NFO: 'bg-purple-500/10 text-purple-600 border-purple-500/30',
  CDS: 'bg-blue-500/10 text-blue-600 border-blue-500/30',
  BSE: 'bg-gray-500/10 text-gray-600 border-gray-500/30',
  BFO: 'bg-yellow-500/10 text-yellow-600 border-yellow-500/30',
  BCD: 'bg-red-500/10 text-red-600 border-red-500/30',
  MCX: 'bg-primary/10 text-primary border-primary/30',
  NCDEX: 'bg-green-500/10 text-green-600 border-green-500/30',
}

export default function Analyzer() {
  const [data, setData] = useState<AnalyzerData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [selectedRequest, setSelectedRequest] = useState<ApiRequest | null>(null)
  const [showDetailsDialog, setShowDetailsDialog] = useState(false)

  useEffect(() => {
    fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchData = async (start?: string, end?: string) => {
    setIsLoading(true)
    try {
      const params = new URLSearchParams()
      if (start) params.append('start_date', start)
      if (end) params.append('end_date', end)

      const url = params.toString() ? `/analyzer/api/data?${params}` : '/analyzer/api/data'

      const response = await fetch(url, {
        credentials: 'include',
      })

      if (response.ok) {
        const result = await response.json()
        if (result.status === 'success') {
          setData(result.data)
        }
      }
    } catch (error) {
    } finally {
      setIsLoading(false)
    }
  }

  const handleFilter = (e: React.FormEvent) => {
    e.preventDefault()
    fetchData(startDate, endDate)
  }

  const handleExport = () => {
    const params = new URLSearchParams()
    if (startDate) params.append('start_date', startDate)
    if (endDate) params.append('end_date', endDate)

    const url = params.toString() ? `/analyzer/export?${params}` : '/analyzer/export'
    window.location.href = url
  }

  const viewDetails = (request: ApiRequest) => {
    setSelectedRequest(request)
    setShowDetailsDialog(true)
  }

  const getRequestDetails = (request: ApiRequest): string => {
    if (request.api_type === 'cancelorder') {
      return `OrderID: ${request.orderid}`
    }

    let details = request.symbol || ''
    if (request.quantity) {
      details += ` (${request.quantity})`
    }
    if (request.api_type === 'placesmartorder' && request.position_size) {
      details += ` [Size: ${request.position_size}]`
    }
    return details
  }

  // Clean request data for display (remove apikey)
  const cleanRequestData = (data: Record<string, unknown>): Record<string, unknown> => {
    const cleaned = { ...data }
    delete cleaned.apikey
    return cleaned
  }

  if (isLoading) {
    return (
      <div className="container mx-auto py-8 px-4 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  const stats = data?.stats || { total_requests: 0, issues: { total: 0 }, symbols: [], sources: [] }
  const requests = data?.requests || []

  return (
    <div className="container mx-auto py-6 px-4">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold">Sandbox Request Monitor</h1>
        <p className="text-muted-foreground mt-1">
          Review and validate your sandbox API requests before going live
        </p>
      </div>

      {/* Date Filter */}
      <Card className="mb-6">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Filter className="h-4 w-4" />
            Filters
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleFilter} className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
            <div className="space-y-2">
              <Label htmlFor="start_date" className="text-sm font-medium">Start Date</Label>
              <Input
                id="start_date"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="date-input-styled"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="end_date" className="text-sm font-medium">End Date</Label>
              <Input
                id="end_date"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="date-input-styled"
              />
            </div>
            <div className="flex gap-2 pt-6">
              <Button type="submit">
                <Filter className="h-4 w-4 mr-2" />
                Filter
              </Button>
              <Button type="button" variant="secondary" onClick={handleExport}>
                <Download className="h-4 w-4 mr-2" />
                Export CSV
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Total Requests
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-primary">{stats.total_requests}</div>
            <Badge className="mt-1">Last 24 hours</Badge>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              Issues Found
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-yellow-500">{stats.issues.total}</div>
            <Badge variant="secondary" className="mt-1">
              Needs Attention
            </Badge>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              Unique Symbols
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{stats.symbols.length}</div>
            <Badge variant="outline" className="mt-1">
              Tracked
            </Badge>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Users className="h-4 w-4" />
              Active Sources
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{stats.sources.length}</div>
            <Badge variant="outline" className="mt-1">
              Connected
            </Badge>
          </CardContent>
        </Card>
      </div>

      {/* Requests Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Timestamp</TableHead>
                  <TableHead>API Type</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Details</TableHead>
                  <TableHead>Exchange</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>View</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {requests.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                      No requests found
                    </TableCell>
                  </TableRow>
                ) : (
                  requests.map((request, index) => (
                    <TableRow key={index} className="hover:bg-muted/50">
                      <TableCell className="text-sm">{request.timestamp}</TableCell>
                      <TableCell>
                        <Badge variant="default">{request.api_type}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="truncate max-w-[120px]">
                          {request.source}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-medium">{getRequestDetails(request)}</TableCell>
                      <TableCell>
                        {request.exchange && (
                          <Badge
                            className={EXCHANGE_COLORS[request.exchange] || ''}
                            variant="outline"
                          >
                            {request.exchange}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {request.action && (
                          <Badge variant={request.action === 'BUY' ? 'default' : 'destructive'}>
                            {request.action}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {request.analysis.issues ? (
                          <Badge
                            variant="secondary"
                            className="bg-yellow-500/10 text-yellow-600 border-yellow-500/30"
                          >
                            <AlertTriangle className="h-3 w-3 mr-1" />
                            Error
                          </Badge>
                        ) : (
                          <Badge
                            variant="secondary"
                            className="bg-green-500/10 text-green-600 border-green-500/30"
                          >
                            <CheckCircle className="h-3 w-3 mr-1" />
                            Success
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <Button size="sm" onClick={() => viewDetails(request)}>
                          <Eye className="h-4 w-4 mr-1" />
                          View
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Request Details Dialog */}
      <Dialog open={showDetailsDialog} onOpenChange={setShowDetailsDialog}>
        <DialogContent className="max-w-[98vw] w-[98vw] sm:max-w-[98vw] p-4">
          <DialogHeader>
            <DialogTitle>Request Details</DialogTitle>
          </DialogHeader>
          {selectedRequest && (() => {
            const requestJson = JSON.stringify(cleanRequestData(selectedRequest.request_data), null, 2)
            const responseJson = JSON.stringify(
              selectedRequest.response_data || selectedRequest.analysis,
              null,
              2
            )
            const requestLines = requestJson.split('\n').length
            const responseLines = responseJson.split('\n').length
            const maxLines = Math.max(requestLines, responseLines)
            // Allow up to 70vh height
            const height = Math.min(Math.max(maxLines * 20 + 24, 200), window.innerHeight * 0.7)

            return (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 max-h-[85vh] overflow-y-auto">
                <div className="min-w-0 overflow-hidden">
                  <h4 className="font-semibold mb-2">Request Data</h4>
                  <div className="rounded-lg border bg-card/50 overflow-auto" style={{ height }}>
                    <JsonEditor value={requestJson} readOnly={true} lineWrapping={false} />
                  </div>
                </div>
                <div className="min-w-0 overflow-hidden">
                  <h4 className="font-semibold mb-2">Response Data</h4>
                  <div className="rounded-lg border bg-card/50 overflow-auto" style={{ height }}>
                    <JsonEditor value={responseJson} readOnly={true} lineWrapping={false} />
                  </div>
                </div>
              </div>
            )
          })()}
        </DialogContent>
      </Dialog>
    </div>
  )
}

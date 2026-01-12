import {
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  Download,
  Eye,
  EyeOff,
  Home,
  Key,
  Menu,
  Plus,
  RefreshCw,
  Search,
  Send,
  Terminal,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'

interface Endpoint {
  name: string
  path: string
  method: 'GET' | 'POST'
  body?: Record<string, unknown>
  params?: Record<string, unknown>
}

interface EndpointsByCategory {
  [category: string]: Endpoint[]
}

interface OpenTab {
  id: string
  endpoint: Endpoint
  requestBody: string
  modified: boolean
}

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', {
    credentials: 'include',
  })
  const data = await response.json()
  return data.csrf_token
}

function syntaxHighlight(json: string): string {
  if (json.length > 100 * 1024) {
    return escapeHtml(json)
  }

  json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return json.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
    (match) => {
      let cls = 'text-orange-400' // number
      if (/^"/.test(match)) {
        if (/:$/.test(match))
          cls = 'text-sky-400' // key
        else cls = 'text-emerald-400' // string
      } else if (/true|false/.test(match))
        cls = 'text-purple-400' // boolean
      else if (/null/.test(match)) cls = 'text-red-400' // null
      return `<span class="${cls}">${match}</span>`
    }
  )
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function isValidApiUrl(url: string): { valid: boolean; error?: string } {
  if (url.startsWith('/api/') || url.startsWith('/playground/')) {
    return { valid: true }
  }

  try {
    const parsed = new URL(url, window.location.origin)

    if (parsed.origin !== window.location.origin) {
      return { valid: false, error: 'Only same-origin requests are allowed' }
    }

    if (!parsed.pathname.startsWith('/api/') && !parsed.pathname.startsWith('/playground/')) {
      return { valid: false, error: 'Only /api/ and /playground/ endpoints are allowed' }
    }

    return { valid: true }
  } catch {
    return { valid: false, error: 'Invalid URL format' }
  }
}

export default function Playground() {
  const [apiKey, setApiKey] = useState('')
  const [showApiKey, setShowApiKey] = useState(false)
  const [endpoints, setEndpoints] = useState<EndpointsByCategory>({})
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')

  // Tabs state
  const [openTabs, setOpenTabs] = useState<OpenTab[]>([])
  const [activeTabId, setActiveTabId] = useState<string | null>(null)

  // Request state
  const [method, setMethod] = useState<'GET' | 'POST'>('POST')
  const [url, setUrl] = useState('')
  const [requestBody, setRequestBody] = useState('')

  // Response state
  const [isLoading, setIsLoading] = useState(false)
  const [responseStatus, setResponseStatus] = useState<number | null>(null)
  const [responseTime, setResponseTime] = useState<number | null>(null)
  const [responseSize, setResponseSize] = useState<number | null>(null)
  const [responseData, setResponseData] = useState<string | null>(null)
  const [responseHeaders, setResponseHeaders] = useState<Record<string, string>>({})

  // Mobile sidebar
  const [isSidebarOpen, setIsSidebarOpen] = useState(true)

  const requestBodyRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    loadApiKey()
    loadEndpoints()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadApiKey = async () => {
    try {
      const response = await fetch('/playground/api-key', {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        setApiKey(data.api_key || '')
      }
    } catch (error) {
      console.error('Error loading API key:', error)
    }
  }

  const loadEndpoints = async () => {
    try {
      const response = await fetch('/playground/endpoints', {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        setEndpoints(data)
      }
    } catch (error) {
      console.error('Error loading endpoints:', error)
      toast.error('Failed to load endpoints')
    }
  }

  const getDefaultBody = useCallback(
    (endpoint: Endpoint): string => {
      let body: Record<string, unknown> = {}
      if (endpoint.method === 'GET' && endpoint.params) {
        body = { ...endpoint.params }
      } else if (endpoint.body) {
        body = { ...endpoint.body }
      }

      if (apiKey && !body.apikey) {
        body.apikey = apiKey
      }

      return JSON.stringify(body, null, 2)
    },
    [apiKey]
  )

  const selectEndpoint = (endpoint: Endpoint) => {
    // Check if tab already exists
    const existingTab = openTabs.find((t) => t.endpoint.path === endpoint.path)

    if (existingTab) {
      setActiveTabId(existingTab.id)
      setMethod(existingTab.endpoint.method)
      setUrl(existingTab.endpoint.path)
      setRequestBody(existingTab.requestBody)
    } else {
      // Create new tab
      const newTab: OpenTab = {
        id: `${endpoint.path}-${Date.now()}`,
        endpoint,
        requestBody: getDefaultBody(endpoint),
        modified: false,
      }

      setOpenTabs((prev) => [...prev, newTab])
      setActiveTabId(newTab.id)
      setMethod(endpoint.method)
      setUrl(endpoint.path)
      setRequestBody(newTab.requestBody)
    }

    // Clear response when switching
    setResponseData(null)
    setResponseStatus(null)
    setResponseTime(null)
    setResponseSize(null)
  }

  const closeTab = (tabId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const tabIndex = openTabs.findIndex((t) => t.id === tabId)
    const newTabs = openTabs.filter((t) => t.id !== tabId)
    setOpenTabs(newTabs)

    if (activeTabId === tabId) {
      // Select adjacent tab or clear
      if (newTabs.length > 0) {
        const newIndex = Math.min(tabIndex, newTabs.length - 1)
        const newActiveTab = newTabs[newIndex]
        setActiveTabId(newActiveTab.id)
        setMethod(newActiveTab.endpoint.method)
        setUrl(newActiveTab.endpoint.path)
        setRequestBody(newActiveTab.requestBody)
      } else {
        setActiveTabId(null)
        setMethod('POST')
        setUrl('')
        setRequestBody('')
      }
    }
  }

  const switchTab = (tab: OpenTab) => {
    setActiveTabId(tab.id)
    setMethod(tab.endpoint.method)
    setUrl(tab.endpoint.path)
    setRequestBody(tab.requestBody)
    setResponseData(null)
    setResponseStatus(null)
  }

  const updateCurrentTabBody = (newBody: string) => {
    setRequestBody(newBody)
    if (activeTabId) {
      setOpenTabs((prev) =>
        prev.map((t) =>
          t.id === activeTabId
            ? { ...t, requestBody: newBody, modified: newBody !== getDefaultBody(t.endpoint) }
            : t
        )
      )
    }
  }

  const toggleCategory = (category: string) => {
    setCollapsedCategories((prev) => {
      const next = new Set(prev)
      if (next.has(category)) {
        next.delete(category)
      } else {
        next.add(category)
      }
      return next
    })
  }

  const prettifyBody = () => {
    try {
      const parsed = JSON.parse(requestBody)
      const prettified = JSON.stringify(parsed, null, 2)
      updateCurrentTabBody(prettified)
      toast.success('JSON prettified')
    } catch {
      toast.error('Invalid JSON - cannot prettify')
    }
  }

  const sendRequest = async () => {
    if (!url) {
      toast.warning('Please select an endpoint')
      return
    }

    const validation = isValidApiUrl(url)
    if (!validation.valid) {
      toast.error(validation.error)
      return
    }

    setIsLoading(true)
    setResponseData(null)
    setResponseStatus(null)
    setResponseTime(null)
    setResponseSize(null)
    setResponseHeaders({})

    const startTime = Date.now()

    try {
      const options: RequestInit = {
        method,
        credentials: 'include',
        headers: {
          Accept: 'application/json',
        },
      }

      let fetchUrl = url

      if (method === 'GET') {
        if (requestBody.trim()) {
          try {
            const params = JSON.parse(requestBody)
            const urlObj = new URL(url, window.location.origin)
            Object.entries(params).forEach(([key, value]) => {
              if (value !== null && value !== undefined && value !== '') {
                urlObj.searchParams.append(key, String(value))
              }
            })
            fetchUrl = urlObj.toString()
          } catch {
            toast.error('Invalid JSON for query parameters')
            setIsLoading(false)
            return
          }
        }
      } else {
        const csrfToken = await fetchCSRFToken()
        ;(options.headers as Record<string, string>)['Content-Type'] = 'application/json'
        ;(options.headers as Record<string, string>)['X-CSRFToken'] = csrfToken
        if (requestBody.trim()) {
          options.body = requestBody
        }
      }

      const response = await fetch(fetchUrl, options)
      const elapsed = Date.now() - startTime

      // Capture headers
      const headers: Record<string, string> = {}
      response.headers.forEach((value, key) => {
        headers[key] = value
      })
      setResponseHeaders(headers)

      let data
      const contentType = response.headers.get('content-type')
      if (contentType?.includes('application/json')) {
        data = await response.json()
      } else {
        data = { text: await response.text(), contentType }
      }

      const responseText = JSON.stringify(data, null, 2)
      setResponseStatus(response.status)
      setResponseTime(elapsed)
      setResponseSize(new Blob([responseText]).size)
      setResponseData(responseText)
    } catch (error) {
      const elapsed = Date.now() - startTime
      setResponseStatus(0)
      setResponseTime(elapsed)
      setResponseData(
        JSON.stringify({ error: error instanceof Error ? error.message : 'Unknown error' }, null, 2)
      )
    } finally {
      setIsLoading(false)
    }
  }

  const copyResponse = () => {
    if (responseData) {
      navigator.clipboard.writeText(responseData)
      toast.success('Response copied!')
    }
  }

  const copyApiKey = () => {
    if (apiKey) {
      navigator.clipboard.writeText(apiKey)
      toast.success('API key copied!')
    }
  }

  const copyCurl = () => {
    if (!url) return

    let curlUrl = url

    if (method === 'GET' && requestBody.trim()) {
      try {
        const params = JSON.parse(requestBody)
        const urlObj = new URL(url, window.location.origin)
        Object.entries(params).forEach(([key, value]) => {
          if (value !== null && value !== undefined && value !== '') {
            urlObj.searchParams.append(key, String(value))
          }
        })
        curlUrl = urlObj.toString()
      } catch {
        toast.error('Invalid JSON for query parameters')
        return
      }
    }

    const absoluteUrl = new URL(curlUrl, window.location.origin).href
    let curl = `curl -X ${method} "${absoluteUrl}"`
    curl += ' \\\n  -H "Accept: application/json"'

    if (method !== 'GET' && requestBody.trim()) {
      curl += ' \\\n  -H "Content-Type: application/json"'
      curl += ` \\\n  -d '${requestBody.replace(/'/g, "'\\''")}'`
    }

    navigator.clipboard.writeText(curl)
    toast.success('Copied as cURL')
  }

  // Filter endpoints by search
  const filteredEndpoints = Object.entries(endpoints).reduce((acc, [category, eps]) => {
    if (!searchQuery) {
      acc[category] = eps
    } else {
      const filtered = eps.filter(
        (ep) =>
          ep.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          ep.path.toLowerCase().includes(searchQuery.toLowerCase())
      )
      if (filtered.length) acc[category] = filtered
    }
    return acc
  }, {} as EndpointsByCategory)

  const getStatusColor = (status: number | null) => {
    if (!status) return 'text-zinc-500'
    if (status >= 200 && status < 300) return 'text-emerald-400'
    if (status >= 400) return 'text-red-400'
    return 'text-yellow-400'
  }

  const getStatusBg = (status: number | null) => {
    if (!status) return 'bg-zinc-500/10'
    if (status >= 200 && status < 300) return 'bg-emerald-500/10'
    if (status >= 400) return 'bg-red-500/10'
    return 'bg-yellow-500/10'
  }

  const formatSize = (bytes: number) => {
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)}KB`
    return `${bytes}B`
  }

  const activeTab = openTabs.find((t) => t.id === activeTabId)

  return (
    <div className="h-full flex flex-col bg-zinc-950 text-zinc-100">
      {/* Top Header Bar */}
      <div className="h-12 border-b border-zinc-800 flex items-center px-2 bg-zinc-900/50">
        {/* Left: Logo and Menu */}
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
          >
            <Menu className="h-4 w-4" />
          </Button>
          <div className="flex items-center gap-2 px-2">
            <img
              src="/static/favicon/android-chrome-192x192.png"
              alt="OpenAlgo"
              className="w-6 h-6"
            />
            <span className="font-semibold text-sm">openalgo</span>
          </div>
        </div>

        {/* Center: Tabs */}
        <div className="flex-1 flex items-center gap-1 px-4 overflow-x-auto">
          {openTabs.map((tab) => (
            <div
              key={tab.id}
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-md text-xs cursor-pointer group',
                'hover:bg-zinc-800',
                tab.id === activeTabId ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-400'
              )}
              onClick={() => switchTab(tab)}
            >
              <Badge
                variant="outline"
                className={cn(
                  'text-[9px] px-1 py-0 h-4 border-0 font-semibold',
                  tab.endpoint.method === 'GET'
                    ? 'bg-sky-500/20 text-sky-400'
                    : 'bg-emerald-500/20 text-emerald-400'
                )}
              >
                {tab.endpoint.method}
              </Badge>
              <span className="truncate max-w-[100px]">{tab.endpoint.name}</span>
              {tab.modified && <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />}
              <button
                className="opacity-0 group-hover:opacity-100 hover:text-zinc-100 p-0.5 -mr-1"
                onClick={(e) => closeTab(tab.id, e)}
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-zinc-500 hover:text-zinc-100 hover:bg-zinc-800"
            onClick={() => {
              // Select first available endpoint
              const firstCat = Object.keys(endpoints)[0]
              if (firstCat && endpoints[firstCat]?.[0]) {
                selectEndpoint(endpoints[firstCat][0])
              }
            }}
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2 px-2">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
            asChild
          >
            <Link to="/dashboard">
              <Home className="h-3.5 w-3.5 mr-1.5" />
              Dashboard
            </Link>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
            asChild
          >
            <Link to="/apikey">
              <Key className="h-3.5 w-3.5 mr-1.5" />
              API Keys
            </Link>
          </Button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        <div
          className={cn(
            'w-56 border-r border-zinc-800 bg-zinc-900/30 flex flex-col overflow-hidden',
            'transition-all duration-200',
            isSidebarOpen ? 'translate-x-0' : '-translate-x-full absolute h-full z-50'
          )}
        >
          {/* Search */}
          <div className="p-2 border-b border-zinc-800 shrink-0">
            <div className="relative">
              <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-500" />
              <Input
                placeholder="search"
                className="h-7 pl-8 text-xs bg-zinc-800/50 border-zinc-700 text-zinc-100 placeholder:text-zinc-500"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
          </div>

          {/* Endpoints List */}
          <div className="flex-1 overflow-y-auto min-h-0">
            <div className="p-2">
              {Object.entries(filteredEndpoints).map(([category, eps]) => (
                <div key={category} className="mb-2">
                  <button
                    className="flex items-center gap-1.5 w-full px-2 py-1 rounded text-[11px] font-medium uppercase tracking-wider text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50"
                    onClick={() => toggleCategory(category)}
                  >
                    {collapsedCategories.has(category) ? (
                      <ChevronRight className="h-3 w-3" />
                    ) : (
                      <ChevronDown className="h-3 w-3" />
                    )}
                    {category}
                  </button>

                  {!collapsedCategories.has(category) && (
                    <div className="mt-0.5 space-y-0.5">
                      {eps.map((endpoint, idx) => (
                        <button
                          key={idx}
                          className={cn(
                            'w-full flex items-center gap-2 px-2 py-1 rounded text-left text-xs hover:bg-zinc-800/50',
                            activeTab?.endpoint.path === endpoint.path &&
                              'bg-zinc-800 text-zinc-100'
                          )}
                          onClick={() => selectEndpoint(endpoint)}
                        >
                          <Badge
                            variant="outline"
                            className={cn(
                              'text-[9px] px-1 py-0 h-4 border-0 font-semibold shrink-0',
                              endpoint.method === 'GET'
                                ? 'bg-sky-500/20 text-sky-400'
                                : 'bg-emerald-500/20 text-emerald-400'
                            )}
                          >
                            {endpoint.method}
                          </Badge>
                          <span className="truncate text-zinc-300">{endpoint.name}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* API Key Section */}
          <div className="p-2 border-t border-zinc-800 shrink-0">
            <div className="flex items-center gap-2 px-2 py-1.5 rounded bg-zinc-800/50">
              <Key className="h-3 w-3 text-zinc-500" />
              <Input
                type={showApiKey ? 'text' : 'password'}
                value={apiKey}
                readOnly
                className="flex-1 h-5 text-[10px] font-mono bg-transparent border-none p-0 text-zinc-400"
                placeholder="No API key"
              />
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5 text-zinc-500 hover:text-zinc-300"
                onClick={() => setShowApiKey(!showApiKey)}
              >
                {showApiKey ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5 text-zinc-500 hover:text-zinc-300"
                onClick={copyApiKey}
              >
                <Copy className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </div>

        {/* Main Panels */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {activeTab ? (
            <>
              {/* URL Bar */}
              <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800 bg-zinc-900/30">
                <Badge
                  variant="outline"
                  className={cn(
                    'text-xs px-2 py-0.5 border-0 font-semibold',
                    method === 'GET'
                      ? 'bg-sky-500/20 text-sky-400'
                      : 'bg-emerald-500/20 text-emerald-400'
                  )}
                >
                  {method}
                </Badge>
                <div className="flex-1 flex items-center gap-1 px-3 py-1.5 rounded bg-zinc-800/50 font-mono text-sm">
                  <span className="text-zinc-500">http://127.0.0.1:5000</span>
                  <span className="text-zinc-100">{url}</span>
                </div>
                <Button
                  size="sm"
                  className="h-8 px-4 bg-emerald-600 hover:bg-emerald-700 text-white"
                  onClick={sendRequest}
                  disabled={isLoading}
                >
                  {isLoading ? (
                    <RefreshCw className="h-4 w-4 animate-spin" />
                  ) : (
                    <>
                      <Send className="h-3.5 w-3.5 mr-1.5" />
                      Send
                    </>
                  )}
                </Button>
              </div>

              {/* Request/Response Panels */}
              <div className="flex-1 flex overflow-hidden">
                {/* Request Panel */}
                <div className="flex-1 flex flex-col border-r border-zinc-800 min-w-0">
                  {/* Request Tabs */}
                  <Tabs defaultValue="body" className="flex-1 flex flex-col min-h-0">
                    <div className="flex items-center justify-between px-4 py-1.5 border-b border-zinc-800 bg-zinc-900/30">
                      <TabsList className="h-7 bg-transparent p-0 gap-2">
                        <TabsTrigger
                          value="body"
                          className="h-6 px-2 text-xs data-[state=active]:bg-zinc-800 data-[state=active]:text-zinc-100 text-zinc-500"
                        >
                          Body
                        </TabsTrigger>
                        <TabsTrigger
                          value="headers"
                          className="h-6 px-2 text-xs data-[state=active]:bg-zinc-800 data-[state=active]:text-zinc-100 text-zinc-500"
                        >
                          Headers
                        </TabsTrigger>
                      </TabsList>
                      <div className="flex items-center gap-1">
                        <span className="text-[10px] text-zinc-500 mr-2">JSON</span>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 text-[10px] text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
                          onClick={prettifyBody}
                        >
                          Prettify
                        </Button>
                      </div>
                    </div>

                    <TabsContent value="body" className="flex-1 m-0 overflow-hidden">
                      <div className="h-full flex bg-zinc-950">
                        {/* Line Numbers */}
                        <div className="w-10 bg-zinc-900/50 text-zinc-600 text-xs font-mono py-3 px-2 text-right select-none overflow-hidden border-r border-zinc-800">
                          {requestBody.split('\n').map((_, i) => (
                            <div key={i} className="leading-5">
                              {i + 1}
                            </div>
                          ))}
                        </div>
                        {/* Editor */}
                        <textarea
                          ref={requestBodyRef}
                          className="flex-1 p-3 font-mono text-xs bg-transparent border-none outline-none resize-none text-zinc-100 leading-5"
                          placeholder='{"apikey": ""}'
                          value={requestBody}
                          onChange={(e) => updateCurrentTabBody(e.target.value)}
                          spellCheck={false}
                        />
                      </div>
                    </TabsContent>

                    <TabsContent
                      value="headers"
                      className="flex-1 m-0 p-4 overflow-auto bg-zinc-950"
                    >
                      <div className="text-xs font-mono space-y-2">
                        <div className="flex gap-2">
                          <span className="text-zinc-500">Content-Type:</span>
                          <span className="text-zinc-300">application/json</span>
                        </div>
                        <div className="flex gap-2">
                          <span className="text-zinc-500">Accept:</span>
                          <span className="text-zinc-300">application/json</span>
                        </div>
                      </div>
                    </TabsContent>
                  </Tabs>
                </div>

                {/* Response Panel */}
                <div className="flex-1 flex flex-col min-w-0">
                  {/* Response Header */}
                  <Tabs defaultValue="response" className="flex-1 flex flex-col min-h-0">
                    <div className="flex items-center justify-between px-4 py-1.5 border-b border-zinc-800 bg-zinc-900/30">
                      <TabsList className="h-7 bg-transparent p-0 gap-2">
                        <TabsTrigger
                          value="response"
                          className="h-6 px-2 text-xs data-[state=active]:bg-zinc-800 data-[state=active]:text-zinc-100 text-zinc-500"
                        >
                          Response
                        </TabsTrigger>
                        <TabsTrigger
                          value="headers"
                          className="h-6 px-2 text-xs data-[state=active]:bg-zinc-800 data-[state=active]:text-zinc-100 text-zinc-500"
                        >
                          Headers
                        </TabsTrigger>
                      </TabsList>
                      <div className="flex items-center gap-3 text-xs font-mono">
                        {responseStatus !== null && (
                          <span
                            className={cn(
                              'px-2 py-0.5 rounded',
                              getStatusBg(responseStatus),
                              getStatusColor(responseStatus)
                            )}
                          >
                            {responseStatus}{' '}
                            {responseStatus >= 200 && responseStatus < 300 ? 'OK' : 'Error'}
                          </span>
                        )}
                        {responseTime !== null && (
                          <span className="text-zinc-500 flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {responseTime}ms
                          </span>
                        )}
                        {responseSize !== null && (
                          <span className="text-zinc-500 flex items-center gap-1">
                            <Download className="h-3 w-3" />
                            {formatSize(responseSize)}
                          </span>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 text-[10px] text-zinc-500 hover:text-zinc-100 hover:bg-zinc-800"
                          onClick={copyCurl}
                        >
                          <Terminal className="h-3 w-3 mr-1" />
                          cURL
                        </Button>
                        {responseData && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 text-zinc-500 hover:text-zinc-100"
                            onClick={copyResponse}
                          >
                            <Copy className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                    </div>

                    <TabsContent value="response" className="flex-1 m-0 overflow-hidden">
                      <div className="h-full flex bg-zinc-950">
                        {responseData ? (
                          <>
                            {/* Line Numbers */}
                            <div className="w-10 bg-zinc-900/50 text-zinc-600 text-xs font-mono py-3 px-2 text-right select-none overflow-hidden border-r border-zinc-800">
                              {responseData.split('\n').map((_, i) => (
                                <div key={i} className="leading-5">
                                  {i + 1}
                                </div>
                              ))}
                            </div>
                            {/* Response Content */}
                            <ScrollArea className="flex-1 p-3">
                              <pre
                                className="text-xs font-mono whitespace-pre-wrap break-words leading-5"
                                dangerouslySetInnerHTML={{ __html: syntaxHighlight(responseData) }}
                              />
                            </ScrollArea>
                          </>
                        ) : (
                          <div className="flex-1 flex flex-col items-center justify-center text-center">
                            {isLoading ? (
                              <RefreshCw className="h-8 w-8 text-zinc-700 animate-spin" />
                            ) : (
                              <>
                                <Send className="h-10 w-10 text-zinc-800 mb-3" />
                                <p className="text-zinc-600 text-sm">No response yet</p>
                                <p className="text-zinc-700 text-xs mt-1">
                                  Click Send to make a request
                                </p>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    </TabsContent>

                    <TabsContent
                      value="headers"
                      className="flex-1 m-0 p-4 overflow-auto bg-zinc-950"
                    >
                      {Object.keys(responseHeaders).length > 0 ? (
                        <div className="text-xs font-mono space-y-2">
                          {Object.entries(responseHeaders).map(([key, value]) => (
                            <div key={key} className="flex gap-2">
                              <span className="text-zinc-500">{key}:</span>
                              <span className="text-zinc-300 break-all">{value}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-xs text-zinc-600">No headers to display</div>
                      )}
                    </TabsContent>
                  </Tabs>
                </div>
              </div>
            </>
          ) : (
            /* Empty State */
            <div className="flex-1 flex flex-col items-center justify-center text-center bg-zinc-950">
              <img
                src="/static/favicon/android-chrome-192x192.png"
                alt="OpenAlgo"
                className="w-16 h-16 mb-4"
              />
              <h2 className="text-lg font-semibold text-zinc-300 mb-2">API Playground</h2>
              <p className="text-zinc-500 text-sm mb-4">
                Select an endpoint from the sidebar to get started
              </p>
              {!apiKey && (
                <Button
                  variant="outline"
                  size="sm"
                  className="border-zinc-700 text-zinc-300"
                  asChild
                >
                  <Link to="/apikey">
                    <Key className="h-4 w-4 mr-2" />
                    Generate API Key
                  </Link>
                </Button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

import { useState, useEffect, useCallback, useRef } from 'react';
import { Wifi, WifiOff, X, Play, Square, Trash2, Activity, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', {
    credentials: 'include',
  });
  const data = await response.json();
  return data.csrf_token;
}

interface SearchResult {
  symbol: string;
  name: string;
  exchange: string;
  token: string;
}

interface MarketData {
  ltp?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  average_price?: number;
  last_trade_quantity?: number;
  total_buy_quantity?: number;
  total_sell_quantity?: number;
  timestamp?: string;
  depth?: {
    buy: Array<{ price: number; quantity: number; orders?: number }>;
    sell: Array<{ price: number; quantity: number; orders?: number }>;
  };
}

interface SymbolData {
  symbol: string;
  exchange: string;
  data: MarketData;
  subscriptions: Set<string>;
}

interface LogEntry {
  timestamp: string;
  message: string;
  type: 'info' | 'success' | 'error' | 'data';
}

const EXCHANGES = ['NSE', 'NFO', 'BSE', 'BFO', 'CDS', 'MCX'];

function formatPrice(price: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(price);
}

function formatVolume(volume: number): string {
  return new Intl.NumberFormat('en-IN').format(volume);
}

function formatTimestamp(timestamp?: string): string {
  if (!timestamp) return '-';
  const date = new Date(timestamp);
  return date.toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour12: true,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export default function WebSocketTest() {
  // Connection state
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);

  // Symbol management
  const [activeSymbols, setActiveSymbols] = useState<Map<string, SymbolData>>(new Map());
  const [searchQuery, setSearchQuery] = useState('');
  const [searchExchange, setSearchExchange] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [showSearchResults, setShowSearchResults] = useState(false);
  const [isSearching, setIsSearching] = useState(false);

  // Logs
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const logContainerRef = useRef<HTMLDivElement>(null);

  // Refs for tracking
  const searchInputRef = useRef<HTMLDivElement>(null);

  // Add log entry
  const logEvent = useCallback((message: string, type: LogEntry['type'] = 'info') => {
    const timestamp = new Date().toLocaleTimeString('en-IN');
    setLogs((prev) => [...prev.slice(-99), { timestamp, message, type }]);
  }, []);

  // Get CSRF token
  const getCsrfToken = async () => {
    return await fetchCSRFToken();
  };

  // Connect to WebSocket
  const connectWebSocket = async () => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      logEvent('Already connected to WebSocket', 'info');
      return;
    }

    setIsConnecting(true);
    logEvent('Attempting to connect to WebSocket server...', 'info');

    try {
      // Get WebSocket config
      const csrfToken = await getCsrfToken();
      const configResponse = await fetch('/api/websocket/config', {
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      });
      const configData = await configResponse.json();

      if (configData.status !== 'success') {
        throw new Error('Failed to get WebSocket configuration');
      }

      const wsUrl = configData.websocket_url;
      logEvent(`Connecting to ${wsUrl}...`, 'info');

      const socket = new WebSocket(wsUrl);

      socket.onopen = async () => {
        logEvent('Connected to WebSocket server', 'success');
        setIsConnected(true);
        setIsConnecting(false);

        // Authenticate
        try {
          const authCsrfToken = await getCsrfToken();
          const apiKeyResponse = await fetch('/api/websocket/apikey', {
            headers: { 'X-CSRFToken': authCsrfToken },
            credentials: 'include',
          });
          const apiKeyData = await apiKeyResponse.json();

          if (apiKeyData.status === 'success' && apiKeyData.api_key) {
            socket.send(JSON.stringify({ action: 'authenticate', api_key: apiKeyData.api_key }));
            logEvent('Sent authentication request', 'info');
          } else {
            logEvent('Failed to get API key. Go to /apikey to generate one.', 'error');
          }
        } catch (error) {
          logEvent(`Error getting API key: ${error}`, 'error');
        }
      };

      socket.onclose = (event) => {
        setIsConnected(false);
        setIsConnecting(false);
        if (event.wasClean) {
          logEvent('WebSocket connection closed cleanly', 'info');
        } else {
          logEvent(`WebSocket connection lost. Code: ${event.code}`, 'error');
        }
      };

      socket.onerror = () => {
        logEvent('WebSocket error occurred', 'error');
        setIsConnecting(false);
      };

      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          handleWebSocketMessage(data);
        } catch (e) {
          logEvent(`Error parsing WebSocket message: ${e}`, 'error');
        }
      };

      socketRef.current = socket;
    } catch (error) {
      logEvent(`Error connecting: ${error}`, 'error');
      setIsConnecting(false);
    }
  };

  // Handle WebSocket messages
  const handleWebSocketMessage = useCallback((data: Record<string, unknown>) => {
    const type = (data.type || data.status) as string;

    switch (type) {
      case 'auth':
        if (data.status === 'success') {
          logEvent('WebSocket authentication successful', 'success');
        } else {
          logEvent(`Authentication failed: ${data.message}`, 'error');
        }
        break;

      case 'market_data': {
        const symbol = (data.symbol as string).toLowerCase();
        const exchange = data.exchange as string;
        const mode = data.mode as number;
        const marketData = (data.data || {}) as MarketData;

        setActiveSymbols((prev) => {
          const key = `${exchange}:${symbol.toUpperCase()}`;
          const existing = prev.get(key);
          if (!existing) return prev;

          const updated = new Map(prev);
          const newData = { ...existing.data };

          if (mode === 1 || mode === 2) {
            if (marketData.ltp !== undefined) newData.ltp = marketData.ltp;
            if (marketData.open !== undefined) newData.open = marketData.open;
            if (marketData.high !== undefined) newData.high = marketData.high;
            if (marketData.low !== undefined) newData.low = marketData.low;
            if (marketData.close !== undefined) newData.close = marketData.close;
            if (marketData.volume !== undefined) newData.volume = marketData.volume;
            if (marketData.average_price !== undefined) newData.average_price = marketData.average_price;
            if (marketData.last_trade_quantity !== undefined) newData.last_trade_quantity = marketData.last_trade_quantity;
            if (marketData.total_buy_quantity !== undefined) newData.total_buy_quantity = marketData.total_buy_quantity;
            if (marketData.total_sell_quantity !== undefined) newData.total_sell_quantity = marketData.total_sell_quantity;
            if (marketData.timestamp !== undefined) newData.timestamp = marketData.timestamp;
          }

          if (mode === 3 && marketData.depth) {
            newData.depth = marketData.depth;
          }

          updated.set(key, { ...existing, data: newData });
          return updated;
        });
        break;
      }

      case 'subscribe':
        if (data.status === 'success') {
          logEvent('Subscription successful', 'success');
        } else {
          logEvent(`Subscription error: ${data.message}`, 'error');
        }
        break;

      case 'unsubscribe':
        logEvent('Unsubscription processed', 'info');
        break;

      case 'error':
        logEvent(`WebSocket error: ${data.message}`, 'error');
        break;

      default:
        logEvent(`Unknown message type: ${type}`, 'info');
    }
  }, [logEvent]);

  // Subscribe to a symbol
  const subscribe = (symbol: string, exchange: string, mode: string) => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      logEvent('Please connect to WebSocket first', 'error');
      return;
    }

    const message = {
      action: 'subscribe',
      symbols: [{ symbol, exchange }],
      mode,
    };

    socketRef.current.send(JSON.stringify(message));
    logEvent(`Subscribing to ${exchange}:${symbol} (${mode})`, 'info');

    // Update subscriptions
    setActiveSymbols((prev) => {
      const key = `${exchange}:${symbol}`;
      const existing = prev.get(key);
      if (!existing) return prev;

      const updated = new Map(prev);
      const newSubs = new Set(existing.subscriptions);
      newSubs.add(mode);
      updated.set(key, { ...existing, subscriptions: newSubs });
      return updated;
    });
  };

  // Unsubscribe from a symbol
  const unsubscribe = (symbol: string, exchange: string, mode: string) => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      return;
    }

    const modeMap: Record<string, number> = { LTP: 1, Quote: 2, Depth: 3 };
    const message = {
      action: 'unsubscribe',
      symbols: [{ symbol, exchange, mode: modeMap[mode] }],
      mode,
    };

    socketRef.current.send(JSON.stringify(message));
    logEvent(`Unsubscribing from ${exchange}:${symbol} (${mode})`, 'info');

    // Update subscriptions
    setActiveSymbols((prev) => {
      const key = `${exchange}:${symbol}`;
      const existing = prev.get(key);
      if (!existing) return prev;

      const updated = new Map(prev);
      const newSubs = new Set(existing.subscriptions);
      newSubs.delete(mode);
      updated.set(key, { ...existing, subscriptions: newSubs });
      return updated;
    });
  };

  // Subscribe all symbols to a mode
  const subscribeAllMode = (mode: string) => {
    let delay = 0;
    activeSymbols.forEach((_, key) => {
      const [exchange, symbol] = key.split(':');
      setTimeout(() => subscribe(symbol, exchange, mode), delay);
      delay += 200;
    });
  };

  // Unsubscribe all
  const unsubscribeAll = () => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      return;
    }

    socketRef.current.send(JSON.stringify({ action: 'unsubscribe_all' }));
    logEvent('Unsubscribed from all symbols', 'info');

    setActiveSymbols((prev) => {
      const updated = new Map(prev);
      updated.forEach((value, key) => {
        updated.set(key, { ...value, subscriptions: new Set() });
      });
      return updated;
    });
  };

  // Search for symbols
  const performSearch = useCallback(async (query: string, exchange: string) => {
    if (query.length < 2) {
      setSearchResults([]);
      setShowSearchResults(false);
      return;
    }

    setIsSearching(true);
    try {
      const params = new URLSearchParams({ q: query });
      if (exchange) params.append('exchange', exchange);

      const response = await fetch(`/search/api/search?${params}`, {
        credentials: 'include',
      });
      const data = await response.json();
      setSearchResults((data.results || []).slice(0, 10));
      setShowSearchResults(true);
    } catch (error) {
      console.error('Search error:', error);
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  }, []);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchQuery.length >= 2) {
        performSearch(searchQuery, searchExchange);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, searchExchange, performSearch]);

  // Add symbol
  const addSymbol = (symbol: string, exchange: string) => {
    const key = `${exchange}:${symbol}`;
    if (activeSymbols.has(key)) {
      toast.error('Symbol already added');
      return;
    }

    setActiveSymbols((prev) => {
      const updated = new Map(prev);
      updated.set(key, {
        symbol,
        exchange,
        data: {},
        subscriptions: new Set(),
      });
      return updated;
    });

    setSearchQuery('');
    setShowSearchResults(false);
    logEvent(`Added symbol: ${key}`, 'success');
  };

  // Remove symbol
  const removeSymbol = (symbol: string, exchange: string) => {
    const key = `${exchange}:${symbol}`;
    const existing = activeSymbols.get(key);

    // Unsubscribe first
    if (existing) {
      existing.subscriptions.forEach((mode) => {
        unsubscribe(symbol, exchange, mode);
      });
    }

    setActiveSymbols((prev) => {
      const updated = new Map(prev);
      updated.delete(key);
      return updated;
    });

    logEvent(`Removed symbol: ${key}`, 'info');
  };

  // Clear logs
  const clearLogs = () => {
    setLogs([]);
  };

  // Click outside handler for search
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchInputRef.current && !searchInputRef.current.contains(e.target as Node)) {
        setShowSearchResults(false);
      }
    };
    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, []);

  // Scroll log to bottom
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  // Load saved symbols on mount
  useEffect(() => {
    const saved = localStorage.getItem('websocket_active_symbols');
    if (saved) {
      try {
        const symbols = JSON.parse(saved);
        const newMap = new Map<string, SymbolData>();
        symbols.forEach((key: string) => {
          const [exchange, symbol] = key.split(':');
          newMap.set(key, { symbol, exchange, data: {}, subscriptions: new Set() });
        });
        setActiveSymbols(newMap);
      } catch (e) {
        console.error('Error loading saved symbols:', e);
      }
    }
  }, []);

  // Save symbols to localStorage
  useEffect(() => {
    const keys = Array.from(activeSymbols.keys());
    localStorage.setItem('websocket_active_symbols', JSON.stringify(keys));
  }, [activeSymbols]);

  return (
    <div className="container mx-auto py-6 px-4 space-y-6">
      {/* Header */}
      <Card>
        <CardHeader>
          <CardTitle className="text-3xl">WebSocket Market Data Test</CardTitle>
          <p className="text-muted-foreground">Real-time testing for multiple symbols with dynamic symbol management</p>
        </CardHeader>
      </Card>

      {/* Connection Status */}
      <Card>
        <CardHeader>
          <CardTitle>Connection Status</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">WebSocket:</span>
              {isConnected ? (
                <>
                  <Wifi className="h-4 w-4 text-green-500" />
                  <span className="font-semibold text-green-500">Connected</span>
                </>
              ) : isConnecting ? (
                <>
                  <Activity className="h-4 w-4 text-yellow-500 animate-pulse" />
                  <span className="font-semibold text-yellow-500">Connecting...</span>
                </>
              ) : (
                <>
                  <WifiOff className="h-4 w-4 text-red-500" />
                  <span className="font-semibold text-red-500">Disconnected</span>
                </>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Active Symbols:</span>
              <Badge>{activeSymbols.size}</Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Symbol Management */}
      <Card>
        <CardHeader>
          <CardTitle>Symbol Management</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Search */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Add Symbol</Label>
              <div className="relative" ref={searchInputRef}>
                <Input
                  type="text"
                  placeholder="Search for symbol..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onFocus={() => searchQuery.length >= 2 && setShowSearchResults(true)}
                />
                {isSearching && (
                  <div className="absolute right-3 top-1/2 -translate-y-1/2">
                    <RefreshCw className="h-4 w-4 animate-spin" />
                  </div>
                )}

                {showSearchResults && searchResults.length > 0 && (
                  <div className="absolute z-50 w-full mt-1 bg-background border rounded-lg shadow-lg max-h-64 overflow-y-auto">
                    {searchResults.map((result, index) => (
                      <div
                        key={index}
                        className="p-3 border-b last:border-b-0 hover:bg-muted cursor-pointer"
                        onClick={() => addSymbol(result.symbol, result.exchange)}
                      >
                        <div className="flex justify-between items-center">
                          <div>
                            <div className="font-medium">{result.symbol}</div>
                            <div className="text-xs text-muted-foreground">{result.name}</div>
                          </div>
                          <Badge>{result.exchange}</Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="space-y-2">
              <Label>Exchange Filter</Label>
              <Select value={searchExchange} onValueChange={setSearchExchange}>
                <SelectTrigger>
                  <SelectValue placeholder="All Exchanges" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="_all">All Exchanges</SelectItem>
                  {EXCHANGES.map((ex) => (
                    <SelectItem key={ex} value={ex}>{ex}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Active Symbols */}
          <div>
            <Label>Active Symbols ({activeSymbols.size})</Label>
            <div className="flex flex-wrap gap-2 mt-2">
              {Array.from(activeSymbols.entries()).map(([key, data]) => (
                <Badge key={key} variant="secondary" className="gap-1 py-1 px-2">
                  {key}
                  <button onClick={() => removeSymbol(data.symbol, data.exchange)}>
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
              {activeSymbols.size === 0 && (
                <span className="text-muted-foreground text-sm">No symbols added</span>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Control Panel */}
      <Card>
        <CardHeader>
          <CardTitle>Control Panel</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            <Button onClick={connectWebSocket} disabled={isConnected || isConnecting}>
              <Play className="h-4 w-4 mr-2" />
              Connect WebSocket
            </Button>
            <Button onClick={() => subscribeAllMode('LTP')} variant="outline" disabled={!isConnected}>
              Subscribe All LTP
            </Button>
            <Button onClick={() => subscribeAllMode('Quote')} variant="outline" disabled={!isConnected}>
              Subscribe All Quote
            </Button>
            <Button onClick={() => subscribeAllMode('Depth')} variant="outline" disabled={!isConnected}>
              Subscribe All Depth
            </Button>
            <Button onClick={unsubscribeAll} variant="destructive" disabled={!isConnected}>
              <Square className="h-4 w-4 mr-2" />
              Unsubscribe All
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Market Data Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {Array.from(activeSymbols.entries()).map(([key, symbolData]) => (
          <Card key={key}>
            <CardHeader>
              <div className="flex justify-between items-center">
                <CardTitle>{key}</CardTitle>
                <div className="flex gap-1">
                  <Button size="sm" variant="outline" onClick={() => subscribe(symbolData.symbol, symbolData.exchange, 'LTP')}>
                    LTP
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => subscribe(symbolData.symbol, symbolData.exchange, 'Quote')}>
                    Quote
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => subscribe(symbolData.symbol, symbolData.exchange, 'Depth')}>
                    Depth
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* LTP */}
              <div className="p-4 bg-muted rounded-lg">
                <h4 className="font-semibold text-sm mb-2">Last Traded Price</h4>
                <div className="text-2xl font-bold font-mono">
                  {symbolData.data.ltp !== undefined ? formatPrice(symbolData.data.ltp) : '-'}
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  {formatTimestamp(symbolData.data.timestamp)}
                </div>
              </div>

              {/* Quote Data */}
              <div className="p-4 bg-muted rounded-lg">
                <h4 className="font-semibold text-sm mb-2">Quote</h4>
                <div className="grid grid-cols-3 gap-2 text-sm">
                  <div><span className="text-muted-foreground">Open:</span> <span className="font-mono">{symbolData.data.open !== undefined ? formatPrice(symbolData.data.open) : '-'}</span></div>
                  <div><span className="text-muted-foreground">High:</span> <span className="font-mono">{symbolData.data.high !== undefined ? formatPrice(symbolData.data.high) : '-'}</span></div>
                  <div><span className="text-muted-foreground">Low:</span> <span className="font-mono">{symbolData.data.low !== undefined ? formatPrice(symbolData.data.low) : '-'}</span></div>
                  <div><span className="text-muted-foreground">Close:</span> <span className="font-mono">{symbolData.data.close !== undefined ? formatPrice(symbolData.data.close) : '-'}</span></div>
                  <div><span className="text-muted-foreground">Volume:</span> <span className="font-mono">{symbolData.data.volume !== undefined ? formatVolume(symbolData.data.volume) : '-'}</span></div>
                </div>
              </div>

              {/* Depth */}
              {symbolData.data.depth && (
                <div className="p-4 bg-muted rounded-lg">
                  <h4 className="font-semibold text-sm mb-2">Market Depth</h4>
                  <div className="grid grid-cols-2 gap-4 text-xs">
                    <div>
                      <div className="font-semibold text-green-500 mb-1">BUY</div>
                      {symbolData.data.depth.buy.slice(0, 5).map((level, i) => (
                        <div key={i} className="flex justify-between">
                          <span>{formatPrice(level.price)}</span>
                          <span className="text-green-500">{level.quantity}</span>
                        </div>
                      ))}
                    </div>
                    <div>
                      <div className="font-semibold text-red-500 mb-1">SELL</div>
                      {symbolData.data.depth.sell.slice(0, 5).map((level, i) => (
                        <div key={i} className="flex justify-between">
                          <span>{formatPrice(level.price)}</span>
                          <span className="text-red-500">{level.quantity}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Event Log */}
      <Card>
        <CardHeader>
          <div className="flex justify-between items-center">
            <CardTitle>Event Log</CardTitle>
            <Button variant="ghost" size="sm" onClick={clearLogs}>
              <Trash2 className="h-4 w-4 mr-1" />
              Clear
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div
            ref={logContainerRef}
            className="h-64 overflow-y-auto bg-muted rounded-lg p-4 font-mono text-xs space-y-1"
          >
            {logs.length === 0 ? (
              <div className="text-muted-foreground">Waiting for events...</div>
            ) : (
              logs.map((log, index) => (
                <div
                  key={index}
                  className={cn(
                    log.type === 'success' && 'text-green-500',
                    log.type === 'error' && 'text-red-500',
                    log.type === 'data' && 'text-yellow-500',
                    log.type === 'info' && 'text-blue-500'
                  )}
                >
                  [{log.timestamp}] {log.message}
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

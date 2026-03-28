# OpenAlgo Frontend AI UI + CCGL Orchestration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build React 19 components for AI signal display, multi-symbol scan, and decision history inside OpenAlgo's frontend, then define CCGL/Triad Workbench workflows to orchestrate the full backend + frontend build across Claude, Codex, and Gemini.

**Architecture:** New `ai-analysis` feature module following OpenAlgo's existing patterns: types in `types/`, API client in `api/`, custom hook in `hooks/`, shadcn/ui components in `components/ai-analysis/`, page in `pages/`, and route in the router. CCGL orchestration uses custom workflow definitions dispatched via Triad Workbench.

**Tech Stack:** React 19, TypeScript, Vite 7, TanStack Query, Zustand, shadcn/ui (Radix + Tailwind), Lucide icons, Vitest + Testing Library, Biome linter

**Prerequisite:** Backend plan completed first (`2026-03-26-vayu-openalgo-ai-integration.md` — Tasks 1-9 providing `/api/v1/agent/analyze`, `/scan`, `/status` endpoints).

---

## Part A: Frontend AI Components

### File Structure

```
D:\openalgo\frontend\src\
├── types/
│   └── ai-analysis.ts                    # NEW: TypeScript types
├── api/
│   └── ai-analysis.ts                    # NEW: API client module
├── hooks/
│   └── useAIAnalysis.ts                  # NEW: TanStack Query hook
├── components/
│   └── ai-analysis/                      # NEW: Feature components
│       ├── index.ts                      # Barrel exports
│       ├── SignalBadge.tsx               # Signal type badge (BUY/SELL/HOLD)
│       ├── ConfidenceGauge.tsx           # Circular confidence meter
│       ├── SubScoresChart.tsx            # Horizontal bar chart of 6 sub-signals
│       ├── IndicatorTable.tsx            # Key indicator values table
│       └── ScanResultsTable.tsx          # Multi-symbol scan results
├── pages/
│   └── AIAnalyzer.tsx                    # NEW: AI Analysis page
└── test/
    ├── ai-analysis.test.tsx             # NEW: Component tests
    └── ai-analysis-api.test.ts          # NEW: API + hook tests
```

### Modified Files

```
D:\openalgo\frontend\src\
├── app/routes.tsx                        # Add /ai-analyzer route
└── components/layout/Navbar.tsx          # Add AI Analyzer nav link
```

---

### Task 1: TypeScript Types

**Files:**
- Create: `frontend/src/types/ai-analysis.ts`

- [ ] **Step 1: Create type definitions**

```typescript
// frontend/src/types/ai-analysis.ts

/** Signal types from VAYU engine */
export type SignalType = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL'

/** Market regime classification */
export type MarketRegime = 'TRENDING_UP' | 'TRENDING_DOWN' | 'RANGING' | 'VOLATILE'

/** Sub-signal scores from the weighted engine */
export interface SubScores {
  supertrend?: number
  rsi?: number
  macd?: number
  ema_cross?: number
  bollinger?: number
  adx_strength?: number
}

/** Latest indicator values */
export interface IndicatorValues {
  rsi_14?: number
  rsi_7?: number
  macd?: number
  macd_signal?: number
  macd_hist?: number
  ema_9?: number
  ema_21?: number
  sma_50?: number
  sma_200?: number
  adx_14?: number
  bb_high?: number
  bb_low?: number
  bb_pband?: number
  supertrend?: number
  supertrend_dir?: number
  atr_14?: number
  stoch_k?: number
  stoch_d?: number
  obv?: number
  vwap?: number
}

/** Full analysis result from /api/v1/agent/analyze */
export interface AIAnalysisResult {
  symbol: string
  exchange: string
  interval: string
  signal: SignalType
  confidence: number
  score: number
  regime: MarketRegime
  sub_scores: SubScores
  indicators: IndicatorValues
  data_points: number
}

/** Scan result for one symbol from /api/v1/agent/scan */
export interface ScanResult {
  symbol: string
  signal: SignalType | null
  confidence: number
  score: number
  regime: MarketRegime | null
  error: string | null
}

/** AI agent status from /api/v1/agent/status */
export interface AIAgentStatus {
  agent: string
  version: string
  engine: string
  indicators: number
  signals: number
}

/** API response wrapper (matches OpenAlgo pattern) */
export interface AIAnalysisResponse {
  status: 'success' | 'error'
  message?: string
  data?: AIAnalysisResult
}

export interface AIScanResponse {
  status: 'success' | 'error'
  message?: string
  data?: ScanResult[]
}

export interface AIStatusResponse {
  status: 'success' | 'error'
  data?: AIAgentStatus
}

/** Signal display config */
export const SIGNAL_CONFIG: Record<SignalType, { label: string; color: string; bgColor: string }> = {
  STRONG_BUY: { label: 'Strong Buy', color: 'text-green-700', bgColor: 'bg-green-100' },
  BUY: { label: 'Buy', color: 'text-green-600', bgColor: 'bg-green-50' },
  HOLD: { label: 'Hold', color: 'text-yellow-600', bgColor: 'bg-yellow-50' },
  SELL: { label: 'Sell', color: 'text-red-600', bgColor: 'bg-red-50' },
  STRONG_SELL: { label: 'Strong Sell', color: 'text-red-700', bgColor: 'bg-red-100' },
}

export const REGIME_CONFIG: Record<MarketRegime, { label: string; icon: string }> = {
  TRENDING_UP: { label: 'Trending Up', icon: 'TrendingUp' },
  TRENDING_DOWN: { label: 'Trending Down', icon: 'TrendingDown' },
  RANGING: { label: 'Ranging', icon: 'Minus' },
  VOLATILE: { label: 'Volatile', icon: 'Zap' },
}
```

- [ ] **Step 2: Commit**

```bash
cd D:\openalgo\frontend
git add src/types/ai-analysis.ts
git commit -m "feat(ai-ui): add TypeScript types for AI analysis"
```

---

### Task 2: API Client Module

**Files:**
- Create: `frontend/src/api/ai-analysis.ts`
- Test: `frontend/src/test/ai-analysis-api.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// frontend/src/test/ai-analysis-api.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock axios client
vi.mock('@/api/client', () => ({
  apiClient: {
    post: vi.fn(),
    get: vi.fn(),
  },
}))

import { aiAnalysisApi } from '@/api/ai-analysis'
import { apiClient } from '@/api/client'

describe('aiAnalysisApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('analyzeSymbol sends correct payload', async () => {
    const mockResponse = {
      data: {
        status: 'success',
        data: { symbol: 'RELIANCE', signal: 'BUY', confidence: 75.0 },
      },
    }
    vi.mocked(apiClient.post).mockResolvedValue(mockResponse)

    const result = await aiAnalysisApi.analyzeSymbol('test_key', 'RELIANCE', 'NSE', '1d')

    expect(apiClient.post).toHaveBeenCalledWith('/agent/analyze', {
      apikey: 'test_key',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      interval: '1d',
    })
    expect(result.status).toBe('success')
  })

  it('scanSymbols sends correct payload', async () => {
    const mockResponse = {
      data: { status: 'success', data: [{ symbol: 'RELIANCE', signal: 'BUY' }] },
    }
    vi.mocked(apiClient.post).mockResolvedValue(mockResponse)

    const result = await aiAnalysisApi.scanSymbols('test_key', ['RELIANCE', 'SBIN'], 'NSE')

    expect(apiClient.post).toHaveBeenCalledWith('/agent/scan', {
      apikey: 'test_key',
      symbols: ['RELIANCE', 'SBIN'],
      exchange: 'NSE',
      interval: '1d',
    })
    expect(result.status).toBe('success')
  })

  it('getStatus calls correct endpoint', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { status: 'success', data: { agent: 'active' } },
    })

    const result = await aiAnalysisApi.getStatus()
    expect(apiClient.get).toHaveBeenCalledWith('/agent/status')
    expect(result.data?.agent).toBe('active')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\openalgo\frontend && npm test -- --run src/test/ai-analysis-api.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement API client**

```typescript
// frontend/src/api/ai-analysis.ts
import { apiClient } from './client'
import type {
  AIAnalysisResponse,
  AIScanResponse,
  AIStatusResponse,
} from '@/types/ai-analysis'

export const aiAnalysisApi = {
  /** Run AI technical analysis on a single symbol */
  analyzeSymbol: async (
    apiKey: string,
    symbol: string,
    exchange: string = 'NSE',
    interval: string = '1d',
  ): Promise<AIAnalysisResponse> => {
    const response = await apiClient.post<AIAnalysisResponse>('/agent/analyze', {
      apikey: apiKey,
      symbol,
      exchange,
      interval,
    })
    return response.data
  },

  /** Scan multiple symbols and return signals */
  scanSymbols: async (
    apiKey: string,
    symbols: string[],
    exchange: string = 'NSE',
    interval: string = '1d',
  ): Promise<AIScanResponse> => {
    const response = await apiClient.post<AIScanResponse>('/agent/scan', {
      apikey: apiKey,
      symbols,
      exchange,
      interval,
    })
    return response.data
  },

  /** Check AI agent status */
  getStatus: async (): Promise<AIStatusResponse> => {
    const response = await apiClient.get<AIStatusResponse>('/agent/status')
    return response.data
  },
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\openalgo\frontend && npm test -- --run src/test/ai-analysis-api.test.ts`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
cd D:\openalgo\frontend
git add src/api/ai-analysis.ts src/test/ai-analysis-api.test.ts
git commit -m "feat(ai-ui): add API client for AI analysis endpoints"
```

---

### Task 3: TanStack Query Hook

**Files:**
- Create: `frontend/src/hooks/useAIAnalysis.ts`

- [ ] **Step 1: Implement hook**

```typescript
// frontend/src/hooks/useAIAnalysis.ts
import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@/stores/authStore'
import { aiAnalysisApi } from '@/api/ai-analysis'
import type { AIAnalysisResult, ScanResult, AIAgentStatus } from '@/types/ai-analysis'

/** Fetch AI analysis for a single symbol */
export function useAIAnalysis(
  symbol: string,
  exchange: string = 'NSE',
  interval: string = '1d',
  enabled: boolean = true,
) {
  const apiKey = useAuthStore((s) => s.apiKey)

  return useQuery<AIAnalysisResult | null>({
    queryKey: ['ai-analysis', symbol, exchange, interval],
    queryFn: async () => {
      if (!apiKey) return null
      const response = await aiAnalysisApi.analyzeSymbol(apiKey, symbol, exchange, interval)
      if (response.status === 'error') throw new Error(response.message || 'Analysis failed')
      return response.data ?? null
    },
    enabled: enabled && !!apiKey && !!symbol,
    staleTime: 60_000, // 1 minute (matches existing pattern)
    refetchOnWindowFocus: true,
  })
}

/** Scan multiple symbols */
export function useAIScan(
  symbols: string[],
  exchange: string = 'NSE',
  interval: string = '1d',
  enabled: boolean = true,
) {
  const apiKey = useAuthStore((s) => s.apiKey)

  return useQuery<ScanResult[]>({
    queryKey: ['ai-scan', symbols, exchange, interval],
    queryFn: async () => {
      if (!apiKey) return []
      const response = await aiAnalysisApi.scanSymbols(apiKey, symbols, exchange, interval)
      if (response.status === 'error') throw new Error(response.message || 'Scan failed')
      return response.data ?? []
    },
    enabled: enabled && !!apiKey && symbols.length > 0,
    staleTime: 60_000,
  })
}

/** Check AI agent status */
export function useAIStatus() {
  return useQuery<AIAgentStatus | null>({
    queryKey: ['ai-status'],
    queryFn: async () => {
      const response = await aiAnalysisApi.getStatus()
      return response.data ?? null
    },
    staleTime: 300_000, // 5 minutes
  })
}
```

- [ ] **Step 2: Commit**

```bash
cd D:\openalgo\frontend
git add src/hooks/useAIAnalysis.ts
git commit -m "feat(ai-ui): add TanStack Query hooks for AI analysis"
```

---

### Task 4: UI Components

**Files:**
- Create: `frontend/src/components/ai-analysis/SignalBadge.tsx`
- Create: `frontend/src/components/ai-analysis/ConfidenceGauge.tsx`
- Create: `frontend/src/components/ai-analysis/SubScoresChart.tsx`
- Create: `frontend/src/components/ai-analysis/IndicatorTable.tsx`
- Create: `frontend/src/components/ai-analysis/ScanResultsTable.tsx`
- Create: `frontend/src/components/ai-analysis/index.ts`
- Test: `frontend/src/test/ai-analysis.test.tsx`

- [ ] **Step 1: Write failing component tests**

```typescript
// frontend/src/test/ai-analysis.test.tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@/test/test-utils'
import { SignalBadge } from '@/components/ai-analysis/SignalBadge'
import { ConfidenceGauge } from '@/components/ai-analysis/ConfidenceGauge'
import { SubScoresChart } from '@/components/ai-analysis/SubScoresChart'
import { IndicatorTable } from '@/components/ai-analysis/IndicatorTable'
import { ScanResultsTable } from '@/components/ai-analysis/ScanResultsTable'

describe('SignalBadge', () => {
  it('renders BUY signal', () => {
    render(<SignalBadge signal="BUY" />)
    expect(screen.getByText('Buy')).toBeInTheDocument()
  })

  it('renders STRONG_SELL signal', () => {
    render(<SignalBadge signal="STRONG_SELL" />)
    expect(screen.getByText('Strong Sell')).toBeInTheDocument()
  })

  it('renders HOLD signal', () => {
    render(<SignalBadge signal="HOLD" />)
    expect(screen.getByText('Hold')).toBeInTheDocument()
  })
})

describe('ConfidenceGauge', () => {
  it('renders confidence value', () => {
    render(<ConfidenceGauge confidence={75.5} />)
    expect(screen.getByText('75.5%')).toBeInTheDocument()
  })

  it('renders zero confidence', () => {
    render(<ConfidenceGauge confidence={0} />)
    expect(screen.getByText('0%')).toBeInTheDocument()
  })
})

describe('SubScoresChart', () => {
  it('renders all sub-scores', () => {
    render(<SubScoresChart scores={{ rsi: 0.3, macd: -0.5, supertrend: 0.8 }} />)
    expect(screen.getByText('RSI')).toBeInTheDocument()
    expect(screen.getByText('MACD')).toBeInTheDocument()
    expect(screen.getByText('Supertrend')).toBeInTheDocument()
  })

  it('renders empty state', () => {
    render(<SubScoresChart scores={{}} />)
    expect(screen.getByText(/no signals/i)).toBeInTheDocument()
  })
})

describe('IndicatorTable', () => {
  it('renders indicator values', () => {
    render(<IndicatorTable indicators={{ rsi_14: 42.5, macd: 1.23 }} />)
    expect(screen.getByText('RSI (14)')).toBeInTheDocument()
    expect(screen.getByText('42.5')).toBeInTheDocument()
  })
})

describe('ScanResultsTable', () => {
  it('renders scan results', () => {
    render(
      <ScanResultsTable
        results={[
          { symbol: 'RELIANCE', signal: 'BUY', confidence: 75, score: 0.35, regime: 'TRENDING_UP', error: null },
          { symbol: 'SBIN', signal: 'SELL', confidence: 60, score: -0.28, regime: 'TRENDING_DOWN', error: null },
        ]}
      />,
    )
    expect(screen.getByText('RELIANCE')).toBeInTheDocument()
    expect(screen.getByText('SBIN')).toBeInTheDocument()
  })

  it('renders empty state', () => {
    render(<ScanResultsTable results={[]} />)
    expect(screen.getByText(/no results/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\openalgo\frontend && npm test -- --run src/test/ai-analysis.test.tsx`
Expected: FAIL (modules not found)

- [ ] **Step 3: Implement SignalBadge**

```tsx
// frontend/src/components/ai-analysis/SignalBadge.tsx
import { Badge } from '@/components/ui/badge'
import { SIGNAL_CONFIG } from '@/types/ai-analysis'
import type { SignalType } from '@/types/ai-analysis'

interface SignalBadgeProps {
  signal: SignalType
  size?: 'sm' | 'md' | 'lg'
}

export function SignalBadge({ signal, size = 'md' }: SignalBadgeProps) {
  const config = SIGNAL_CONFIG[signal]
  const sizeClass = size === 'lg' ? 'text-lg px-4 py-2' : size === 'sm' ? 'text-xs px-2 py-0.5' : 'text-sm px-3 py-1'

  return (
    <Badge className={`${config.bgColor} ${config.color} ${sizeClass} font-semibold`}>
      {config.label}
    </Badge>
  )
}
```

- [ ] **Step 4: Implement ConfidenceGauge**

```tsx
// frontend/src/components/ai-analysis/ConfidenceGauge.tsx
interface ConfidenceGaugeProps {
  confidence: number // 0-100
}

export function ConfidenceGauge({ confidence }: ConfidenceGaugeProps) {
  const radius = 40
  const circumference = 2 * Math.PI * radius
  const progress = (confidence / 100) * circumference
  const color = confidence > 70 ? '#16a34a' : confidence > 40 ? '#ca8a04' : '#dc2626'

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="100" height="100" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r={radius} fill="none" stroke="#e5e7eb" strokeWidth="8" />
        <circle
          cx="50" cy="50" r={radius} fill="none"
          stroke={color} strokeWidth="8" strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference - progress}
          transform="rotate(-90 50 50)"
        />
        <text x="50" y="55" textAnchor="middle" className="text-lg font-bold fill-current">
          {confidence}%
        </text>
      </svg>
      <span className="text-xs text-muted-foreground">Confidence</span>
    </div>
  )
}
```

- [ ] **Step 5: Implement SubScoresChart**

```tsx
// frontend/src/components/ai-analysis/SubScoresChart.tsx
import type { SubScores } from '@/types/ai-analysis'

interface SubScoresChartProps {
  scores: SubScores
}

const LABELS: Record<string, string> = {
  supertrend: 'Supertrend',
  rsi: 'RSI',
  macd: 'MACD',
  ema_cross: 'EMA Cross',
  bollinger: 'Bollinger',
  adx_strength: 'ADX',
}

export function SubScoresChart({ scores }: SubScoresChartProps) {
  const entries = Object.entries(scores).filter(([, v]) => v !== undefined)

  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">No signals available</p>
  }

  return (
    <div className="space-y-2">
      {entries.map(([key, value]) => {
        const pct = ((value + 1) / 2) * 100 // -1..+1 → 0..100
        const color = value > 0 ? 'bg-green-500' : value < 0 ? 'bg-red-500' : 'bg-gray-400'
        return (
          <div key={key} className="flex items-center gap-2">
            <span className="w-24 text-sm text-right">{LABELS[key] ?? key}</span>
            <div className="flex-1 h-4 bg-muted rounded-full overflow-hidden relative">
              <div className="absolute left-1/2 top-0 bottom-0 w-px bg-border" />
              <div
                className={`absolute top-0 bottom-0 ${color} rounded-full`}
                style={{
                  left: value > 0 ? '50%' : `${pct}%`,
                  width: `${Math.abs(value) * 50}%`,
                }}
              />
            </div>
            <span className="w-12 text-sm text-right font-mono">{value.toFixed(2)}</span>
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 6: Implement IndicatorTable**

```tsx
// frontend/src/components/ai-analysis/IndicatorTable.tsx
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { IndicatorValues } from '@/types/ai-analysis'

interface IndicatorTableProps {
  indicators: IndicatorValues
}

const INDICATOR_LABELS: Record<string, string> = {
  rsi_14: 'RSI (14)', rsi_7: 'RSI (7)',
  macd: 'MACD', macd_signal: 'MACD Signal', macd_hist: 'MACD Histogram',
  ema_9: 'EMA (9)', ema_21: 'EMA (21)', sma_50: 'SMA (50)', sma_200: 'SMA (200)',
  adx_14: 'ADX (14)', bb_high: 'BB Upper', bb_low: 'BB Lower', bb_pband: 'BB %B',
  supertrend: 'Supertrend', supertrend_dir: 'ST Direction',
  atr_14: 'ATR (14)', stoch_k: 'Stoch %K', stoch_d: 'Stoch %D',
  obv: 'OBV', vwap: 'VWAP',
}

export function IndicatorTable({ indicators }: IndicatorTableProps) {
  const entries = Object.entries(indicators).filter(([, v]) => v !== undefined && v !== null)

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Indicator</TableHead>
          <TableHead className="text-right">Value</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map(([key, value]) => (
          <TableRow key={key}>
            <TableCell>{INDICATOR_LABELS[key] ?? key}</TableCell>
            <TableCell className="text-right font-mono">{Number(value).toFixed(2)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
```

- [ ] **Step 7: Implement ScanResultsTable**

```tsx
// frontend/src/components/ai-analysis/ScanResultsTable.tsx
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { SignalBadge } from './SignalBadge'
import type { ScanResult } from '@/types/ai-analysis'

interface ScanResultsTableProps {
  results: ScanResult[]
}

export function ScanResultsTable({ results }: ScanResultsTableProps) {
  if (results.length === 0) {
    return <p className="text-sm text-muted-foreground py-8 text-center">No results yet</p>
  }

  const sorted = [...results].sort((a, b) => b.score - a.score)

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Symbol</TableHead>
          <TableHead>Signal</TableHead>
          <TableHead className="text-right">Confidence</TableHead>
          <TableHead className="text-right">Score</TableHead>
          <TableHead>Regime</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((r) => (
          <TableRow key={r.symbol}>
            <TableCell className="font-medium">{r.symbol}</TableCell>
            <TableCell>
              {r.signal ? <SignalBadge signal={r.signal} size="sm" /> : <span className="text-muted-foreground">—</span>}
            </TableCell>
            <TableCell className="text-right">{r.confidence.toFixed(1)}%</TableCell>
            <TableCell className="text-right font-mono">{r.score.toFixed(4)}</TableCell>
            <TableCell>{r.regime ?? '—'}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
```

- [ ] **Step 8: Create barrel export**

```typescript
// frontend/src/components/ai-analysis/index.ts
export { SignalBadge } from './SignalBadge'
export { ConfidenceGauge } from './ConfidenceGauge'
export { SubScoresChart } from './SubScoresChart'
export { IndicatorTable } from './IndicatorTable'
export { ScanResultsTable } from './ScanResultsTable'
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd D:\openalgo\frontend && npm test -- --run src/test/ai-analysis.test.tsx`
Expected: all 10 tests PASS

- [ ] **Step 10: Commit**

```bash
cd D:\openalgo\frontend
git add src/components/ai-analysis/ src/test/ai-analysis.test.tsx
git commit -m "feat(ai-ui): add AI analysis display components (signal, gauge, scores, table, scan)"
```

---

### Task 5: AI Analyzer Page

**Files:**
- Create: `frontend/src/pages/AIAnalyzer.tsx`
- Modify: Router config to add `/ai-analyzer` route
- Modify: Navbar to add link

- [ ] **Step 1: Implement page**

```tsx
// frontend/src/pages/AIAnalyzer.tsx
import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, Search, TrendingUp } from 'lucide-react'
import {
  SignalBadge,
  ConfidenceGauge,
  SubScoresChart,
  IndicatorTable,
  ScanResultsTable,
} from '@/components/ai-analysis'
import { useAIAnalysis, useAIScan, useAIStatus } from '@/hooks/useAIAnalysis'
import { REGIME_CONFIG } from '@/types/ai-analysis'
import { showToast } from '@/utils/toast'

const NIFTY50 = [
  'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'HINDUNILVR', 'SBIN',
  'BHARTIARTL', 'ITC', 'KOTAKBANK', 'LT', 'AXISBANK', 'BAJFINANCE',
  'ASIANPAINT', 'MARUTI', 'TITAN', 'SUNPHARMA', 'WIPRO', 'HCLTECH', 'ULTRACEMCO',
]

export function AIAnalyzer() {
  const [symbol, setSymbol] = useState('RELIANCE')
  const [exchange, setExchange] = useState('NSE')
  const [interval, setInterval] = useState('1d')
  const [scanSymbols, setScanSymbols] = useState('')
  const [runScan, setRunScan] = useState(false)

  const { data: analysis, isLoading, error, refetch } = useAIAnalysis(symbol, exchange, interval, !!symbol)
  const { data: statusData } = useAIStatus()

  const symbolList = runScan
    ? (scanSymbols.trim() ? scanSymbols.split(',').map((s) => s.trim()) : NIFTY50)
    : []
  const { data: scanResults, isLoading: scanLoading } = useAIScan(symbolList, exchange, interval, runScan)

  const handleAnalyze = () => {
    if (!symbol.trim()) {
      showToast.error('Enter a symbol')
      return
    }
    refetch()
  }

  const handleScan = () => {
    setRunScan(true)
  }

  return (
    <div className="container mx-auto p-4 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-6 w-6" />
          <h1 className="text-2xl font-bold">AI Analysis</h1>
          {statusData && (
            <span className="text-xs text-muted-foreground">
              Engine: {statusData.engine} | {statusData.indicators} indicators | {statusData.signals} signals
            </span>
          )}
        </div>
      </div>

      {/* Controls */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex gap-2 items-end flex-wrap">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Symbol</label>
              <Input
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                placeholder="RELIANCE"
                className="w-40"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Exchange</label>
              <Select value={exchange} onValueChange={setExchange}>
                <SelectTrigger className="w-24"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="NSE">NSE</SelectItem>
                  <SelectItem value="BSE">BSE</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Interval</label>
              <Select value={interval} onValueChange={setInterval}>
                <SelectTrigger className="w-24"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="1d">Daily</SelectItem>
                  <SelectItem value="1h">1 Hour</SelectItem>
                  <SelectItem value="15m">15 Min</SelectItem>
                  <SelectItem value="5m">5 Min</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button onClick={handleAnalyze} disabled={isLoading}>
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Search className="h-4 w-4 mr-1" />}
              Analyze
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Analysis Result */}
      {error && <p className="text-destructive text-sm">{String(error)}</p>}

      {analysis && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Signal + Confidence */}
          <Card>
            <CardHeader><CardTitle className="text-sm">Signal</CardTitle></CardHeader>
            <CardContent className="flex flex-col items-center gap-4">
              <SignalBadge signal={analysis.signal} size="lg" />
              <ConfidenceGauge confidence={analysis.confidence} />
              <div className="text-center">
                <p className="text-xs text-muted-foreground">
                  Score: <span className="font-mono">{analysis.score.toFixed(4)}</span>
                </p>
                <p className="text-xs text-muted-foreground">
                  Regime: {REGIME_CONFIG[analysis.regime]?.label ?? analysis.regime}
                </p>
                <p className="text-xs text-muted-foreground">
                  Data points: {analysis.data_points}
                </p>
              </div>
            </CardContent>
          </Card>

          {/* Sub-Scores */}
          <Card>
            <CardHeader><CardTitle className="text-sm">Signal Components</CardTitle></CardHeader>
            <CardContent>
              <SubScoresChart scores={analysis.sub_scores} />
            </CardContent>
          </Card>

          {/* Indicators */}
          <Card>
            <CardHeader><CardTitle className="text-sm">Indicators</CardTitle></CardHeader>
            <CardContent className="max-h-80 overflow-auto">
              <IndicatorTable indicators={analysis.indicators} />
            </CardContent>
          </Card>
        </div>
      )}

      {/* Scan Section */}
      <Card>
        <CardHeader><CardTitle className="text-sm">Multi-Symbol Scan</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2 items-end">
            <div className="flex-1 space-y-1">
              <label className="text-xs text-muted-foreground">
                Symbols (comma-separated, leave empty for NIFTY 50)
              </label>
              <Input
                value={scanSymbols}
                onChange={(e) => setScanSymbols(e.target.value.toUpperCase())}
                placeholder="RELIANCE, TCS, INFY, SBIN, ..."
              />
            </div>
            <Button onClick={handleScan} disabled={scanLoading}>
              {scanLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              Scan {scanSymbols.trim() ? '' : 'NIFTY 50'}
            </Button>
          </div>
          {scanResults && <ScanResultsTable results={scanResults} />}
        </CardContent>
      </Card>
    </div>
  )
}
```

- [ ] **Step 2: Add route**

Find the router configuration (likely in `frontend/src/app/routes.tsx` or `App.tsx`) and add:

```tsx
import { AIAnalyzer } from '@/pages/AIAnalyzer'

// In route definitions:
{ path: '/ai-analyzer', element: <AIAnalyzer /> }
```

- [ ] **Step 3: Add nav link**

In `frontend/src/components/layout/Navbar.tsx`, add the AI Analyzer link alongside existing nav items:

```tsx
{ label: 'AI Analysis', path: '/ai-analyzer', icon: TrendingUp }
```

- [ ] **Step 4: Build and verify**

Run: `cd D:\openalgo\frontend && npm run build`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 5: Commit**

```bash
cd D:\openalgo\frontend
git add src/pages/AIAnalyzer.tsx
git add -p  # Stage only the route and nav link changes
git commit -m "feat(ai-ui): add AI Analyzer page with signal display, indicators, and scanner"
```

---

## Part B: CCGL Orchestration

### Task 6: Custom Workflow Definitions for Triad Workbench

**Files:**
- Create: `D:\ccgl room\OPENALGO_AI_WORKFLOWS.md`

This defines how Triad Workbench orchestrates the backend + frontend build.

- [ ] **Step 1: Create workflow definitions**

```markdown
# OpenAlgo AI Integration — CCGL Workflow Definitions

## Workflow 1: Backend AI Package (10 tasks)

**Workflow ID:** `openalgo-ai-backend`
**Mode:** chain
**Steps:**

1. **Claude (coder)**: Implement Tasks 1-3 (symbol mapper, indicators, signals)
   - Brief: "Implement ai/ package with symbol_mapper.py, indicators.py, signals.py following TDD.
     Plan: D:\openalgo\docs\superpowers\plans\2026-03-26-vayu-openalgo-ai-integration.md Tasks 1-3"
   - Approval gate: YES

2. **Codex (reviewer)**: Review Tasks 1-3 implementation
   - Brief: "Review ai/ package code quality, test coverage, edge cases.
     Check: _safe() wrappers, signal weight sums, symbol format handling."
   - Approval gate: YES

3. **Claude (coder)**: Implement Tasks 4-6 (data bridge, events, service)
   - Brief: "Implement data_bridge.py, ai_events.py, ai_db.py, ai_analysis_service.py.
     Use raw SQLAlchemy (NOT Flask-SQLAlchemy). Follow get_history() real signature."
   - Approval gate: YES

4. **Codex (reviewer)**: Review Tasks 4-6
   - Brief: "Verify: DB pattern matches auth_db.py, get_history call signature correct,
     event bus integration follows existing subscriber pattern."

5. **Claude (coder)**: Implement Tasks 7-9 (REST API, MCP, wiring)
   - Brief: "Add restx_api/ai_agent.py namespace, extend MCP server,
     wire subscribers and DB init into app.py."

6. **Codex (reviewer)**: Final review + run full test suite
   - Brief: "Run: cd D:\openalgo && uv run pytest test/ -v
     Verify all tests pass including new test_ai_*.py files."


## Workflow 2: Frontend AI UI (5 tasks)

**Workflow ID:** `openalgo-ai-frontend`
**Mode:** chain
**Steps:**

1. **Gemini (architect)**: Review UI design
   - Brief: "Review AI Analyzer page design in plan. Propose improvements for
     signal display, confidence gauge, scan table. Consider mobile responsiveness."
   - Approval gate: YES

2. **Claude (coder)**: Implement types, API, hooks, components
   - Brief: "Implement frontend Tasks 1-4 from plan:
     D:\openalgo\docs\superpowers\plans\2026-03-26-frontend-ai-ccgl-orchestration.md"
   - Approval gate: YES

3. **Codex (reviewer)**: Review frontend code
   - Brief: "Review TypeScript types, API client, hooks, and components.
     Check: shadcn/ui usage, TanStack Query patterns, Biome lint compliance."

4. **Claude (coder)**: Implement page + routing
   - Brief: "Create AIAnalyzer.tsx page, add route, add nav link. Run npm run build."

5. **Codex (reviewer)**: Final review + test
   - Brief: "Run: cd D:\openalgo\frontend && npm test -- --run && npm run build
     Verify all tests pass and build succeeds."


## Workflow 3: End-to-End Integration Test

**Workflow ID:** `openalgo-ai-e2e`
**Mode:** chain
**Steps:**

1. **Claude (coder)**: Start app, test endpoints
   - Brief: "Start OpenAlgo (uv run app.py), test /api/v1/agent/status,
     /api/v1/agent/analyze, /api/v1/agent/scan. Verify React page loads."

2. **Gemini (architect)**: Architecture review
   - Brief: "Review full integration: data flow from broker → history service →
     AI indicators → signal engine → REST API → React UI. Identify gaps."

3. **Codex (reviewer)**: Security + performance review
   - Brief: "Check: API key handling, rate limiting, error responses, no SQL injection,
     no XSS in React components, reasonable response times."
```

- [ ] **Step 2: Create custom workflow JSON for Triad Workbench**

These can be loaded via Triad Workbench's custom workflow builder UI or saved directly to SQLite.

```json
[
  {
    "id": "openalgo-ai-backend",
    "label": "OpenAlgo AI Backend",
    "description": "Build AI analysis package (indicators, signals, API, MCP)",
    "mode": "chain",
    "steps": [
      { "agentId": "claude", "role": "coder", "label": "Implement core AI package (Tasks 1-3)", "approvalGate": true },
      { "agentId": "codex", "role": "reviewer", "label": "Review core package", "approvalGate": true },
      { "agentId": "claude", "role": "coder", "label": "Implement services (Tasks 4-6)", "approvalGate": true },
      { "agentId": "codex", "role": "reviewer", "label": "Review services", "approvalGate": false },
      { "agentId": "claude", "role": "coder", "label": "Implement API + wiring (Tasks 7-9)", "approvalGate": false },
      { "agentId": "codex", "role": "reviewer", "label": "Final test suite", "approvalGate": true }
    ]
  },
  {
    "id": "openalgo-ai-frontend",
    "label": "OpenAlgo AI Frontend",
    "description": "Build React AI analysis UI components",
    "mode": "chain",
    "steps": [
      { "agentId": "gemini", "role": "architect", "label": "UI design review", "approvalGate": true },
      { "agentId": "claude", "role": "coder", "label": "Implement types + components", "approvalGate": true },
      { "agentId": "codex", "role": "reviewer", "label": "Code review", "approvalGate": false },
      { "agentId": "claude", "role": "coder", "label": "Implement page + routing", "approvalGate": false },
      { "agentId": "codex", "role": "reviewer", "label": "Final test + build", "approvalGate": true }
    ]
  },
  {
    "id": "openalgo-ai-e2e",
    "label": "OpenAlgo AI E2E",
    "description": "End-to-end integration test",
    "mode": "chain",
    "steps": [
      { "agentId": "claude", "role": "coder", "label": "Integration smoke test", "approvalGate": true },
      { "agentId": "gemini", "role": "architect", "label": "Architecture review", "approvalGate": false },
      { "agentId": "codex", "role": "reviewer", "label": "Security + perf review", "approvalGate": true }
    ]
  }
]
```

- [ ] **Step 3: Commit workflow definitions**

```bash
cd "D:\ccgl room"
git add OPENALGO_AI_WORKFLOWS.md
git commit -m "feat: add CCGL workflow definitions for OpenAlgo AI integration"
```

---

## Execution Order

```
1. Open Triad Workbench → Select D:\openalgo as project
2. Import custom workflow: openalgo-ai-backend
3. Start workflow with brief: "Build AI analysis package following plan at
   docs/superpowers/plans/2026-03-26-vayu-openalgo-ai-integration.md"
4. Review at each approval gate
5. After backend complete: Import openalgo-ai-frontend workflow
6. Start frontend workflow
7. After frontend complete: Run openalgo-ai-e2e workflow
8. Final: npm run build in frontend, uv run pytest in backend
```

---

## Summary

| Part | Tasks | Tests | New Files | Modified |
|------|-------|-------|-----------|----------|
| A: Frontend | 5 | ~13 | 10 | 2 |
| B: CCGL | 1 | — | 1 | — |
| **Total** | **6** | **~13** | **11** | **2** |

### Full Integration Map

```
Broker API ──→ OpenAlgo history_service ──→ ai/data_bridge.py
                                                ↓
                                        ai/indicators.py (20+ indicators)
                                                ↓
                                        ai/signals.py (6 weighted sub-signals)
                                                ↓
                                    services/ai_analysis_service.py
                                         ↓              ↓
                              restx_api/ai_agent.py    events/ai_events.py
                                    ↓                       ↓
                            /api/v1/agent/*          database/ai_db.py
                                    ↓
                        frontend/src/api/ai-analysis.ts
                                    ↓
                        frontend/src/hooks/useAIAnalysis.ts
                                    ↓
                  frontend/src/components/ai-analysis/*.tsx
                                    ↓
                      frontend/src/pages/AIAnalyzer.tsx
                                    ↓
                            User sees: Signal, Confidence,
                            Sub-Scores, Indicators, Scanner
```

# Trading Decision Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the AI Analyzer page into a single-screen trading command center where users see AI signals, live price, advanced patterns, CPR levels, and can execute paper/live trades — all in one view. Add LLM router for AI-powered commentary, and design extensible interfaces for future deep learning models and new agents.

**Architecture:** Enhance the existing `AIAnalyzer.tsx` page with 4 new panels (Advanced Signals, Live Price, Trade Actions, LLM Commentary). Add a backend LLM router service that talks to Ollama (primary) or Gemini (fallback). Add a model/agent registry for future extensibility. All new components reuse existing OpenAlgo primitives (`PlaceOrderDialog`, `useLiveQuote`, `tradingApi`).

**Tech Stack:** React 19, TypeScript, shadcn/ui, TanStack Query, lightweight-charts v5, Zustand, Flask, Ollama API, Google Gemini API (free tier)

---

## File Structure

### New Files — Frontend

```
D:\openalgo\frontend\src\
├── components\ai-analysis\
│   ├── AdvancedSignalsPanel.tsx       # SMC, candlestick, harmonic, divergence alerts
│   ├── LivePriceHeader.tsx            # Real-time LTP + change + bid/ask
│   ├── TradeActionPanel.tsx           # Paper/Live trade buttons wired to PlaceOrderDialog
│   ├── LevelsPanel.tsx                # CPR pivot + Fibonacci levels
│   ├── MLConfidenceBar.tsx            # Buy vs Sell ML confidence horizontal bar
│   ├── LLMCommentary.tsx              # AI-generated market commentary
│   └── DecisionHistory.tsx            # Recent AI decisions from DB
├── types\
│   └── llm.ts                         # LLM request/response types
├── api\
│   └── llm.ts                         # LLM API client
└── hooks\
    └── useLLMCommentary.ts            # Hook for LLM commentary
```

### New Files — Backend

```
D:\openalgo\
├── ai\
│   ├── llm_router.py                  # LLM router: Ollama → Gemini fallback
│   └── model_registry.py              # Agent/model/DL registry for extensibility
├── services\
│   └── llm_service.py                 # Service layer for LLM operations
├── restx_api\
│   └── llm_api.py                     # /api/v1/llm/* endpoints
└── test\
    ├── test_ai_llm_router.py          # LLM router tests
    └── test_ai_model_registry.py      # Registry tests
```

### Modified Files

```
D:\openalgo\frontend\src\
├── pages\AIAnalyzer.tsx               # Restructure into tabbed dashboard layout
├── components\ai-analysis\index.ts    # Add new component exports
├── types\ai-analysis.ts              # Add AdvancedSignals type (already in API response)

D:\openalgo\
├── restx_api\__init__.py             # Register llm_api namespace
```

---

## Task 1: Advanced Signals Type + Panel

**Files:**
- Modify: `frontend/src/types/ai-analysis.ts`
- Create: `frontend/src/components/ai-analysis/AdvancedSignalsPanel.tsx`
- Test: `frontend/src/test/advanced-signals-panel.test.tsx`

- [ ] **Step 1: Add AdvancedSignals type**

Add to `frontend/src/types/ai-analysis.ts`:

```typescript
/** Advanced signals from SMC, candlestick, harmonic, etc. */
export interface AdvancedSignals {
  smc: Record<string, boolean>
  candlestick: string[]
  cpr: Record<string, number>
  fibonacci: { long: number; short: number }
  harmonic: { bullish: number; bearish: number }
  divergence: { rsi_bullish: number; rsi_bearish: number }
  volume: { exhaustion: number; vwap_bb_confluence: number }
  ml_confidence: { buy: number; sell: number }
}
```

Also add `advanced?: AdvancedSignals` to `AIAnalysisResult` interface.

- [ ] **Step 2: Write failing test**

```typescript
// frontend/src/test/advanced-signals-panel.test.tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AdvancedSignalsPanel } from '@/components/ai-analysis/AdvancedSignalsPanel'

const mockAdvanced = {
  smc: { smc_fvg_bullish: true, smc_bos_bearish: true },
  candlestick: ['doji', 'engulfing_bull', 'hammer'],
  cpr: { pivot: 2450.5, r1: 2465.0, s1: 2435.0 },
  fibonacci: { long: 1, short: 0 },
  harmonic: { bullish: 1, bearish: 0 },
  divergence: { rsi_bullish: 0, rsi_bearish: 1 },
  volume: { exhaustion: 1, vwap_bb_confluence: 0 },
  ml_confidence: { buy: 72.5, sell: 28.3 },
}

describe('AdvancedSignalsPanel', () => {
  it('renders SMC alerts', () => {
    render(<AdvancedSignalsPanel signals={mockAdvanced} />)
    expect(screen.getByText(/FVG Bullish/i)).toBeInTheDocument()
    expect(screen.getByText(/BOS Bearish/i)).toBeInTheDocument()
  })

  it('renders candlestick patterns', () => {
    render(<AdvancedSignalsPanel signals={mockAdvanced} />)
    expect(screen.getByText(/doji/i)).toBeInTheDocument()
    expect(screen.getByText(/hammer/i)).toBeInTheDocument()
  })

  it('renders harmonic detection', () => {
    render(<AdvancedSignalsPanel signals={mockAdvanced} />)
    expect(screen.getByText(/Harmonic/i)).toBeInTheDocument()
  })

  it('renders empty state', () => {
    const empty = {
      smc: {}, candlestick: [], cpr: {},
      fibonacci: { long: 0, short: 0 }, harmonic: { bullish: 0, bearish: 0 },
      divergence: { rsi_bullish: 0, rsi_bearish: 0 },
      volume: { exhaustion: 0, vwap_bb_confluence: 0 },
      ml_confidence: { buy: 0, sell: 0 },
    }
    render(<AdvancedSignalsPanel signals={empty} />)
    expect(screen.getByText(/no patterns/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd D:\openalgo\frontend && npm test -- --run src/test/advanced-signals-panel.test.tsx`

- [ ] **Step 4: Implement AdvancedSignalsPanel**

```tsx
// frontend/src/components/ai-analysis/AdvancedSignalsPanel.tsx
import { Badge } from '@/components/ui/badge'
import type { AdvancedSignals } from '@/types/ai-analysis'
import { AlertTriangle, TrendingUp, TrendingDown, Activity, Zap } from 'lucide-react'

interface AdvancedSignalsPanelProps {
  signals: AdvancedSignals
}

const SMC_LABELS: Record<string, { label: string; type: 'bullish' | 'bearish' }> = {
  smc_bos_bullish: { label: 'BOS Bullish', type: 'bullish' },
  smc_bos_bearish: { label: 'BOS Bearish', type: 'bearish' },
  smc_choch_bullish: { label: 'CHoCH Bullish', type: 'bullish' },
  smc_choch_bearish: { label: 'CHoCH Bearish', type: 'bearish' },
  smc_fvg_bullish: { label: 'FVG Bullish', type: 'bullish' },
  smc_fvg_bearish: { label: 'FVG Bearish', type: 'bearish' },
  smc_ob_bullish: { label: 'Order Block Bullish', type: 'bullish' },
  smc_ob_bearish: { label: 'Order Block Bearish', type: 'bearish' },
}

export function AdvancedSignalsPanel({ signals }: AdvancedSignalsPanelProps) {
  const smcAlerts = Object.entries(signals.smc).filter(([, v]) => v)
  const hasPatterns = smcAlerts.length > 0 || signals.candlestick.length > 0 ||
    signals.harmonic.bullish > 0 || signals.harmonic.bearish > 0 ||
    signals.divergence.rsi_bullish > 0 || signals.divergence.rsi_bearish > 0 ||
    signals.volume.exhaustion > 0 || signals.volume.vwap_bb_confluence > 0

  if (!hasPatterns) {
    return <p className="text-sm text-muted-foreground py-4 text-center">No patterns detected</p>
  }

  return (
    <div className="space-y-3">
      {/* SMC Alerts */}
      {smcAlerts.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1">
            <Zap className="h-3 w-3" /> Smart Money
          </p>
          <div className="flex flex-wrap gap-1">
            {smcAlerts.map(([key]) => {
              const info = SMC_LABELS[key]
              return (
                <Badge key={key} className={info?.type === 'bullish' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}>
                  {info?.label ?? key}
                </Badge>
              )
            })}
          </div>
        </div>
      )}

      {/* Candlestick Patterns */}
      {signals.candlestick.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1">
            <Activity className="h-3 w-3" /> Candlestick
          </p>
          <div className="flex flex-wrap gap-1">
            {signals.candlestick.map((p) => (
              <Badge key={p} variant="outline" className="text-xs capitalize">
                {p.replace(/_/g, ' ')}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Harmonic */}
      {(signals.harmonic.bullish > 0 || signals.harmonic.bearish > 0) && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Harmonic:</span>
          {signals.harmonic.bullish > 0 && <Badge className="bg-green-100 text-green-700">Bullish Pattern</Badge>}
          {signals.harmonic.bearish > 0 && <Badge className="bg-red-100 text-red-700">Bearish Pattern</Badge>}
        </div>
      )}

      {/* Divergence */}
      {(signals.divergence.rsi_bullish > 0 || signals.divergence.rsi_bearish > 0) && (
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-3 w-3 text-yellow-500" />
          <span className="text-xs text-muted-foreground">RSI Divergence:</span>
          {signals.divergence.rsi_bullish > 0 && <Badge className="bg-green-50 text-green-600">Bullish</Badge>}
          {signals.divergence.rsi_bearish > 0 && <Badge className="bg-red-50 text-red-600">Bearish</Badge>}
        </div>
      )}

      {/* Volume */}
      {(signals.volume.exhaustion > 0 || signals.volume.vwap_bb_confluence > 0) && (
        <div className="flex items-center gap-2 flex-wrap">
          {signals.volume.exhaustion > 0 && <Badge variant="outline">Volume Exhaustion</Badge>}
          {signals.volume.vwap_bb_confluence > 0 && <Badge variant="outline">VWAP+BB Confluence</Badge>}
        </div>
      )}

      {/* Fibonacci */}
      {(signals.fibonacci.long > 0 || signals.fibonacci.short > 0) && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Fibonacci:</span>
          {signals.fibonacci.long > 0 && (
            <Badge className="bg-green-50 text-green-600">
              <TrendingUp className="h-3 w-3 mr-1" /> Support Level
            </Badge>
          )}
          {signals.fibonacci.short > 0 && (
            <Badge className="bg-red-50 text-red-600">
              <TrendingDown className="h-3 w-3 mr-1" /> Resistance Level
            </Badge>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd D:\openalgo\frontend && npm test -- --run src/test/advanced-signals-panel.test.tsx`

- [ ] **Step 6: Commit**

```bash
cd D:\openalgo\frontend
git add src/types/ai-analysis.ts src/components/ai-analysis/AdvancedSignalsPanel.tsx src/test/advanced-signals-panel.test.tsx
git commit -m "feat(ai-ui): add AdvancedSignalsPanel for SMC, candlestick, harmonic patterns"
```

---

## Task 2: Live Price Header + ML Confidence Bar + Levels Panel

**Files:**
- Create: `frontend/src/components/ai-analysis/LivePriceHeader.tsx`
- Create: `frontend/src/components/ai-analysis/MLConfidenceBar.tsx`
- Create: `frontend/src/components/ai-analysis/LevelsPanel.tsx`

- [ ] **Step 1: Implement LivePriceHeader**

```tsx
// frontend/src/components/ai-analysis/LivePriceHeader.tsx
import { useLiveQuote } from '@/hooks/useLiveQuote'
import { TrendingUp, TrendingDown, Minus, Wifi, WifiOff } from 'lucide-react'

interface LivePriceHeaderProps {
  symbol: string
  exchange: string
}

export function LivePriceHeader({ symbol, exchange }: LivePriceHeaderProps) {
  const { data, isLive, isLoading } = useLiveQuote(symbol, exchange)

  if (isLoading || !data) {
    return <div className="animate-pulse h-8 w-48 bg-muted rounded" />
  }

  const change = data.change ?? 0
  const changePct = data.changePercent ?? 0
  const isUp = change > 0
  const isDown = change < 0

  return (
    <div className="flex items-center gap-3">
      <span className="text-2xl font-bold font-mono">{data.ltp?.toFixed(2) ?? '—'}</span>
      <span className={`text-sm font-medium flex items-center gap-1 ${isUp ? 'text-green-600' : isDown ? 'text-red-600' : 'text-muted-foreground'}`}>
        {isUp ? <TrendingUp className="h-4 w-4" /> : isDown ? <TrendingDown className="h-4 w-4" /> : <Minus className="h-4 w-4" />}
        {change > 0 ? '+' : ''}{change.toFixed(2)} ({changePct > 0 ? '+' : ''}{changePct.toFixed(2)}%)
      </span>
      <span className="text-xs text-muted-foreground">
        Bid: {data.bidPrice?.toFixed(2) ?? '—'} | Ask: {data.askPrice?.toFixed(2) ?? '—'}
      </span>
      {isLive ? <Wifi className="h-3 w-3 text-green-500" /> : <WifiOff className="h-3 w-3 text-muted-foreground" />}
    </div>
  )
}
```

- [ ] **Step 2: Implement MLConfidenceBar**

```tsx
// frontend/src/components/ai-analysis/MLConfidenceBar.tsx
interface MLConfidenceBarProps {
  buyConfidence: number  // 0-100
  sellConfidence: number // 0-100
}

export function MLConfidenceBar({ buyConfidence, sellConfidence }: MLConfidenceBarProps) {
  const total = buyConfidence + sellConfidence
  const buyPct = total > 0 ? (buyConfidence / total) * 100 : 50

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>Buy: {buyConfidence.toFixed(1)}%</span>
        <span>ML Confidence</span>
        <span>Sell: {sellConfidence.toFixed(1)}%</span>
      </div>
      <div className="h-3 rounded-full overflow-hidden flex bg-muted">
        <div className="bg-green-500 transition-all" style={{ width: `${buyPct}%` }} />
        <div className="bg-red-500 transition-all" style={{ width: `${100 - buyPct}%` }} />
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Implement LevelsPanel**

```tsx
// frontend/src/components/ai-analysis/LevelsPanel.tsx
interface LevelsPanelProps {
  cpr: Record<string, number>
  currentPrice?: number
}

const LEVEL_ORDER = ['r3', 'r2', 'r1', 'tc', 'pivot', 'bc', 's1', 's2', 's3']
const LEVEL_LABELS: Record<string, string> = {
  pivot: 'Pivot', bc: 'BC', tc: 'TC',
  r1: 'R1', r2: 'R2', r3: 'R3',
  s1: 'S1', s2: 'S2', s3: 'S3',
}

export function LevelsPanel({ cpr, currentPrice }: LevelsPanelProps) {
  const levels = LEVEL_ORDER
    .filter((k) => cpr[k] !== undefined)
    .map((k) => ({ key: k, label: LEVEL_LABELS[k] ?? k, value: cpr[k] }))

  if (levels.length === 0) {
    return <p className="text-xs text-muted-foreground">No levels available</p>
  }

  return (
    <div className="space-y-0.5">
      {levels.map(({ key, label, value }) => {
        const isResistance = key.startsWith('r') || key === 'tc'
        const isSupport = key.startsWith('s') || key === 'bc'
        const isPivot = key === 'pivot'
        const isNearPrice = currentPrice && Math.abs(value - currentPrice) / currentPrice < 0.005

        return (
          <div
            key={key}
            className={`flex justify-between text-xs px-2 py-0.5 rounded ${
              isNearPrice ? 'bg-yellow-50 font-bold' :
              isPivot ? 'bg-blue-50' :
              isResistance ? 'text-red-600' :
              isSupport ? 'text-green-600' : ''
            }`}
          >
            <span>{label}</span>
            <span className="font-mono">{value.toFixed(2)}</span>
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 4: Update barrel export**

Add to `frontend/src/components/ai-analysis/index.ts`:
```typescript
export { AdvancedSignalsPanel } from './AdvancedSignalsPanel'
export { LivePriceHeader } from './LivePriceHeader'
export { MLConfidenceBar } from './MLConfidenceBar'
export { LevelsPanel } from './LevelsPanel'
```

- [ ] **Step 5: Commit**

```bash
cd D:\openalgo\frontend
git add src/components/ai-analysis/
git commit -m "feat(ai-ui): add LivePriceHeader, MLConfidenceBar, LevelsPanel components"
```

---

## Task 3: Trade Action Panel + Decision History

**Files:**
- Create: `frontend/src/components/ai-analysis/TradeActionPanel.tsx`
- Create: `frontend/src/components/ai-analysis/DecisionHistory.tsx`

- [ ] **Step 1: Implement TradeActionPanel**

```tsx
// frontend/src/components/ai-analysis/TradeActionPanel.tsx
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { PlaceOrderDialog } from '@/components/trading/PlaceOrderDialog'
import { showToast } from '@/utils/toast'
import type { SignalType } from '@/types/ai-analysis'
import { ShoppingCart, AlertCircle } from 'lucide-react'

interface TradeActionPanelProps {
  symbol: string
  exchange: string
  signal: SignalType
  confidence: number
}

export function TradeActionPanel({ symbol, exchange, signal, confidence }: TradeActionPanelProps) {
  const [orderDialogOpen, setOrderDialogOpen] = useState(false)

  const suggestedAction = signal === 'STRONG_BUY' || signal === 'BUY' ? 'BUY' as const
    : signal === 'STRONG_SELL' || signal === 'SELL' ? 'SELL' as const
    : undefined

  const isHold = signal === 'HOLD'
  const isStrong = signal === 'STRONG_BUY' || signal === 'STRONG_SELL'

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Button
          className="flex-1 bg-green-600 hover:bg-green-700 text-white"
          onClick={() => { setOrderDialogOpen(true) }}
          disabled={isHold}
        >
          <ShoppingCart className="h-4 w-4 mr-1" />
          {suggestedAction === 'BUY' ? (isStrong ? 'Strong Buy' : 'Buy') : 'Buy'}
        </Button>
        <Button
          className="flex-1 bg-red-600 hover:bg-red-700 text-white"
          onClick={() => { setOrderDialogOpen(true) }}
          disabled={isHold}
        >
          {suggestedAction === 'SELL' ? (isStrong ? 'Strong Sell' : 'Sell') : 'Sell'}
        </Button>
      </div>

      {isHold && (
        <div className="flex items-center gap-2 text-xs text-yellow-600 bg-yellow-50 p-2 rounded">
          <AlertCircle className="h-3 w-3" />
          Signal is HOLD — no trade recommended (confidence: {confidence.toFixed(1)}%)
        </div>
      )}

      {confidence < 50 && !isHold && (
        <p className="text-xs text-muted-foreground">
          Low confidence ({confidence.toFixed(1)}%) — consider smaller position size
        </p>
      )}

      <PlaceOrderDialog
        open={orderDialogOpen}
        onOpenChange={setOrderDialogOpen}
        symbol={symbol}
        exchange={exchange}
        action={suggestedAction}
        strategy="AIAnalyzer"
        onSuccess={(orderId) => {
          showToast.success(`Order placed: ${orderId}`)
          setOrderDialogOpen(false)
        }}
        onError={(err) => showToast.error(err)}
      />
    </div>
  )
}
```

- [ ] **Step 2: Implement DecisionHistory**

```tsx
// frontend/src/components/ai-analysis/DecisionHistory.tsx
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { SignalBadge } from './SignalBadge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { SignalType } from '@/types/ai-analysis'

interface DecisionRecord {
  id: number
  timestamp: string
  symbol: string
  exchange: string
  signal: SignalType
  confidence: number
  score: number
  regime: string
  action_taken: string | null
  order_id: string | null
}

interface DecisionHistoryProps {
  symbol?: string
  limit?: number
}

export function DecisionHistory({ symbol, limit = 10 }: DecisionHistoryProps) {
  const apiKey = useAuthStore((s) => s.apiKey)

  const { data: decisions } = useQuery<DecisionRecord[]>({
    queryKey: ['ai-decisions', symbol, limit],
    queryFn: async () => {
      const params: Record<string, string> = { apikey: apiKey ?? '', limit: String(limit) }
      if (symbol) params.symbol = symbol
      const response = await apiClient.post('/agent/history', params)
      return response.data?.data ?? []
    },
    enabled: !!apiKey,
    staleTime: 30_000,
  })

  if (!decisions || decisions.length === 0) {
    return <p className="text-xs text-muted-foreground text-center py-2">No history yet</p>
  }

  return (
    <div className="max-h-48 overflow-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs">Time</TableHead>
            <TableHead className="text-xs">Symbol</TableHead>
            <TableHead className="text-xs">Signal</TableHead>
            <TableHead className="text-xs text-right">Conf.</TableHead>
            <TableHead className="text-xs">Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {decisions.map((d) => (
            <TableRow key={d.id}>
              <TableCell className="text-xs font-mono">{new Date(d.timestamp).toLocaleTimeString()}</TableCell>
              <TableCell className="text-xs">{d.symbol}</TableCell>
              <TableCell><SignalBadge signal={d.signal} size="sm" /></TableCell>
              <TableCell className="text-xs text-right">{d.confidence.toFixed(0)}%</TableCell>
              <TableCell className="text-xs">{d.action_taken ?? '—'}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
```

- [ ] **Step 3: Update barrel export**

Add to `frontend/src/components/ai-analysis/index.ts`:
```typescript
export { TradeActionPanel } from './TradeActionPanel'
export { DecisionHistory } from './DecisionHistory'
```

- [ ] **Step 4: Commit**

```bash
cd D:\openalgo\frontend
git add src/components/ai-analysis/
git commit -m "feat(ai-ui): add TradeActionPanel with PlaceOrderDialog + DecisionHistory"
```

---

## Task 4: Backend — LLM Router + Model Registry

**Files:**
- Create: `ai/llm_router.py`
- Create: `ai/model_registry.py`
- Test: `test/test_ai_llm_router.py`
- Test: `test/test_ai_model_registry.py`

- [ ] **Step 1: Write failing registry tests**

```python
# test/test_ai_model_registry.py
import pytest
from ai.model_registry import ModelRegistry, ModelInfo, ModelType


def test_register_and_get():
    reg = ModelRegistry()
    reg.register(ModelInfo(id="ollama-qwen", name="Qwen 3.5 9B", type=ModelType.LLM, provider="ollama", endpoint="http://localhost:11434"))
    model = reg.get("ollama-qwen")
    assert model is not None
    assert model.name == "Qwen 3.5 9B"


def test_list_by_type():
    reg = ModelRegistry()
    reg.register(ModelInfo(id="ollama-qwen", name="Qwen", type=ModelType.LLM, provider="ollama"))
    reg.register(ModelInfo(id="custom-lstm", name="LSTM Predictor", type=ModelType.DEEP_LEARNING, provider="local"))
    reg.register(ModelInfo(id="gemini-flash", name="Gemini Flash", type=ModelType.LLM, provider="gemini"))
    llms = reg.list_by_type(ModelType.LLM)
    assert len(llms) == 2
    dls = reg.list_by_type(ModelType.DEEP_LEARNING)
    assert len(dls) == 1


def test_list_by_provider():
    reg = ModelRegistry()
    reg.register(ModelInfo(id="ollama-qwen", name="Qwen", type=ModelType.LLM, provider="ollama"))
    reg.register(ModelInfo(id="ollama-llama", name="Llama", type=ModelType.LLM, provider="ollama"))
    assert len(reg.list_by_provider("ollama")) == 2


def test_remove():
    reg = ModelRegistry()
    reg.register(ModelInfo(id="test", name="Test", type=ModelType.LLM, provider="test"))
    reg.remove("test")
    assert reg.get("test") is None


def test_get_default_chain():
    reg = ModelRegistry()
    reg.register(ModelInfo(id="ollama-qwen", name="Qwen", type=ModelType.LLM, provider="ollama", priority=1))
    reg.register(ModelInfo(id="gemini-flash", name="Gemini", type=ModelType.LLM, provider="gemini", priority=2))
    chain = reg.get_fallback_chain(ModelType.LLM)
    assert chain[0].id == "ollama-qwen"
    assert chain[1].id == "gemini-flash"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:\openalgo && uv run pytest test/test_ai_model_registry.py -v`

- [ ] **Step 3: Implement model_registry.py**

```python
# ai/model_registry.py
"""Extensible registry for LLM models, deep learning models, and agents.

Supports: Ollama (local), Gemini (free), OpenAI, Anthropic, vLLM, custom PyTorch/TF models.
New models added via register() — no code changes needed.
"""

from dataclasses import dataclass, field
from enum import Enum
from utils.logging import get_logger

logger = get_logger(__name__)


class ModelType(str, Enum):
    LLM = "llm"
    DEEP_LEARNING = "deep_learning"
    AGENT = "agent"
    EMBEDDING = "embedding"


@dataclass
class ModelInfo:
    id: str
    name: str
    type: ModelType
    provider: str  # "ollama", "gemini", "openai", "anthropic", "vllm", "local", "custom"
    endpoint: str = ""
    api_key: str = ""
    model_name: str = ""  # e.g., "qwen3.5:9b", "gemini-2.0-flash"
    priority: int = 100  # Lower = higher priority in fallback chain
    enabled: bool = True
    capabilities: list[str] = field(default_factory=list)  # ["chat", "analysis", "vision"]
    metadata: dict = field(default_factory=dict)


class ModelRegistry:
    """Central registry for all models and agents. Thread-safe."""

    def __init__(self):
        self._models: dict[str, ModelInfo] = {}

    def register(self, model: ModelInfo) -> None:
        self._models[model.id] = model
        logger.info(f"Registered model: {model.id} ({model.provider}/{model.type.value})")

    def remove(self, model_id: str) -> None:
        self._models.pop(model_id, None)

    def get(self, model_id: str) -> ModelInfo | None:
        return self._models.get(model_id)

    def list_all(self) -> list[ModelInfo]:
        return list(self._models.values())

    def list_by_type(self, model_type: ModelType) -> list[ModelInfo]:
        return [m for m in self._models.values() if m.type == model_type and m.enabled]

    def list_by_provider(self, provider: str) -> list[ModelInfo]:
        return [m for m in self._models.values() if m.provider == provider and m.enabled]

    def get_fallback_chain(self, model_type: ModelType) -> list[ModelInfo]:
        """Get models sorted by priority (lowest first) for fallback."""
        return sorted(self.list_by_type(model_type), key=lambda m: m.priority)


# Global registry with defaults
_registry = ModelRegistry()


def get_registry() -> ModelRegistry:
    return _registry


def init_default_models():
    """Register default models. Called at app startup."""
    _registry.register(ModelInfo(
        id="ollama-qwen", name="Qwen 3.5 9B", type=ModelType.LLM,
        provider="ollama", endpoint="http://localhost:11434",
        model_name="qwen3.5:9b", priority=1,
        capabilities=["chat", "analysis"],
    ))
    _registry.register(ModelInfo(
        id="gemini-flash", name="Gemini 2.0 Flash", type=ModelType.LLM,
        provider="gemini", endpoint="https://generativelanguage.googleapis.com",
        model_name="gemini-2.0-flash", priority=2,
        capabilities=["chat", "analysis"],
    ))
    # Placeholder for future deep learning models
    _registry.register(ModelInfo(
        id="dl-placeholder", name="Custom DL Model (Future)", type=ModelType.DEEP_LEARNING,
        provider="local", enabled=False, priority=10,
        capabilities=["prediction"],
        metadata={"note": "Placeholder for PyTorch/TF fine-tuned models"},
    ))
```

- [ ] **Step 4: Run registry tests**

Run: `cd D:\openalgo && uv run pytest test/test_ai_model_registry.py -v`

- [ ] **Step 5: Write failing LLM router tests**

```python
# test/test_ai_llm_router.py
import pytest
from unittest.mock import patch, MagicMock
from ai.llm_router import LLMRouter, LLMResponse


def test_router_returns_response():
    router = LLMRouter()
    with patch.object(router, '_call_ollama', return_value=LLMResponse(
        success=True, text="RELIANCE looks bullish", provider="ollama", model="qwen3.5:9b"
    )):
        result = router.generate("Analyze RELIANCE signal: BUY with 75% confidence")
        assert result.success is True
        assert "bullish" in result.text.lower()
        assert result.provider == "ollama"


def test_router_falls_back_to_gemini():
    router = LLMRouter()
    with patch.object(router, '_call_ollama', return_value=LLMResponse(
        success=False, text="", provider="ollama", error="Connection refused"
    )):
        with patch.object(router, '_call_gemini', return_value=LLMResponse(
            success=True, text="Analysis complete", provider="gemini", model="gemini-2.0-flash"
        )):
            result = router.generate("Analyze RELIANCE")
            assert result.success is True
            assert result.provider == "gemini"


def test_router_all_fail():
    router = LLMRouter()
    with patch.object(router, '_call_ollama', return_value=LLMResponse(success=False, text="", provider="ollama", error="down")):
        with patch.object(router, '_call_gemini', return_value=LLMResponse(success=False, text="", provider="gemini", error="quota")):
            result = router.generate("test")
            assert result.success is False
            assert result.error is not None
```

- [ ] **Step 6: Implement llm_router.py**

```python
# ai/llm_router.py
"""LLM Router with Ollama → Gemini fallback chain.

Extensible: add new providers by registering models in model_registry
and adding a _call_{provider} method.
"""

import json
import os
from dataclasses import dataclass

import requests
from ai.model_registry import ModelType, get_registry
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResponse:
    success: bool
    text: str
    provider: str
    model: str = ""
    error: str | None = None


class LLMRouter:
    """Routes LLM requests through a fallback chain: Ollama → Gemini → error."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def generate(self, prompt: str, system: str = "") -> LLMResponse:
        """Send prompt to first available LLM in the fallback chain."""
        registry = get_registry()
        chain = registry.get_fallback_chain(ModelType.LLM)

        for model_info in chain:
            caller = getattr(self, f"_call_{model_info.provider}", None)
            if caller is None:
                logger.debug(f"No caller for provider: {model_info.provider}")
                continue

            result = caller(prompt, system, model_info)
            if result.success:
                return result
            logger.warning(f"LLM {model_info.id} failed: {result.error}")

        return LLMResponse(success=False, text="", provider="none", error="All LLM providers failed")

    def _call_ollama(self, prompt: str, system: str, model_info) -> LLMResponse:
        """Call Ollama local API."""
        try:
            payload = {
                "model": model_info.model_name or "qwen3.5:9b",
                "prompt": prompt,
                "stream": False,
            }
            if system:
                payload["system"] = system

            resp = requests.post(
                f"{model_info.endpoint}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                return LLMResponse(
                    success=True, text=data.get("response", ""),
                    provider="ollama", model=model_info.model_name,
                )
            return LLMResponse(success=False, text="", provider="ollama", error=f"HTTP {resp.status_code}")
        except Exception as e:
            return LLMResponse(success=False, text="", provider="ollama", error=str(e))

    def _call_gemini(self, prompt: str, system: str, model_info) -> LLMResponse:
        """Call Google Gemini API (free tier)."""
        try:
            api_key = model_info.api_key or os.getenv("GEMINI_API_KEY", "")
            if not api_key:
                return LLMResponse(success=False, text="", provider="gemini", error="No GEMINI_API_KEY")

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_info.model_name}:generateContent?key={api_key}"
            parts = []
            if system:
                parts.append({"text": system + "\n\n"})
            parts.append({"text": prompt})

            resp = requests.post(url, json={
                "contents": [{"parts": parts}]
            }, timeout=self.timeout)

            if resp.status_code == 200:
                data = resp.json()
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                return LLMResponse(success=True, text=text, provider="gemini", model=model_info.model_name)
            return LLMResponse(success=False, text="", provider="gemini", error=f"HTTP {resp.status_code}")
        except Exception as e:
            return LLMResponse(success=False, text="", provider="gemini", error=str(e))
```

- [ ] **Step 7: Run all LLM tests**

Run: `cd D:\openalgo && uv run pytest test/test_ai_llm_router.py test/test_ai_model_registry.py -v`

- [ ] **Step 8: Commit**

```bash
cd D:\openalgo
git add ai/llm_router.py ai/model_registry.py test/test_ai_llm_router.py test/test_ai_model_registry.py
git commit -m "feat(ai): add LLM router (Ollama→Gemini fallback) + extensible model registry"
```

---

## Task 5: Backend — LLM Commentary API

**Files:**
- Create: `services/llm_service.py`
- Create: `restx_api/llm_api.py`
- Modify: `restx_api/__init__.py`

- [ ] **Step 1: Implement LLM service**

```python
# services/llm_service.py
"""LLM service for generating AI commentary on market analysis."""

from ai.llm_router import LLMRouter, LLMResponse
from utils.logging import get_logger

logger = get_logger(__name__)

_router = LLMRouter(timeout=30)

ANALYSIS_SYSTEM_PROMPT = """You are a concise Indian stock market analyst. Given technical analysis data,
provide a 2-3 sentence trading commentary. Include: key signal, risk level, and suggested action.
Be direct. Use plain English. Mention specific indicator values that matter."""


def generate_commentary(analysis_data: dict) -> LLMResponse:
    """Generate AI commentary for a stock analysis result."""
    symbol = analysis_data.get("symbol", "?")
    signal = analysis_data.get("signal", "HOLD")
    confidence = analysis_data.get("confidence", 0)
    score = analysis_data.get("score", 0)
    regime = analysis_data.get("regime", "RANGING")
    scores = analysis_data.get("sub_scores", {})
    indicators = analysis_data.get("indicators", {})

    prompt = f"""Symbol: {symbol}
Signal: {signal} (confidence: {confidence}%, score: {score})
Market Regime: {regime}
Sub-signals: {scores}
Key indicators: RSI={indicators.get('rsi_14', '?')}, MACD={indicators.get('macd', '?')}, ADX={indicators.get('adx_14', '?')}

Provide a brief trading commentary."""

    return _router.generate(prompt, system=ANALYSIS_SYSTEM_PROMPT)
```

- [ ] **Step 2: Implement LLM API endpoint**

```python
# restx_api/llm_api.py
"""LLM API endpoints for AI commentary."""

from flask_restx import Namespace, Resource
from limiter import limiter
from services.llm_service import generate_commentary
from utils.logging import get_logger

api = Namespace("llm", description="LLM AI Commentary Endpoints")
logger = get_logger(__name__)


@api.route("/commentary")
class CommentaryResource(Resource):
    @limiter.limit("5 per second")
    def post(self):
        """Generate AI commentary for analysis data."""
        from flask import request
        data = request.get_json(force=True)

        api_key = data.get("apikey", "")
        if not api_key:
            return {"status": "error", "message": "apikey required"}, 400

        analysis = data.get("analysis", {})
        if not analysis:
            return {"status": "error", "message": "analysis data required"}, 400

        result = generate_commentary(analysis)

        if not result.success:
            return {"status": "error", "message": result.error or "LLM unavailable"}

        return {
            "status": "success",
            "data": {
                "commentary": result.text,
                "provider": result.provider,
                "model": result.model,
            },
        }


@api.route("/models")
class ModelsResource(Resource):
    def get(self):
        """List available LLM models."""
        from ai.model_registry import ModelType, get_registry
        registry = get_registry()
        models = [
            {"id": m.id, "name": m.name, "provider": m.provider, "type": m.type.value, "enabled": m.enabled}
            for m in registry.list_all()
        ]
        return {"status": "success", "data": models}
```

- [ ] **Step 3: Register namespace**

Add to `restx_api/__init__.py`:
```python
from .llm_api import api as llm_api_ns
api.add_namespace(llm_api_ns, path="/llm")
```

- [ ] **Step 4: Commit**

```bash
cd D:\openalgo
git add services/llm_service.py restx_api/llm_api.py restx_api/__init__.py
git commit -m "feat(ai): add LLM commentary API with Ollama/Gemini support"
```

---

## Task 6: Frontend — LLM Commentary + Restructured Dashboard

**Files:**
- Create: `frontend/src/types/llm.ts`
- Create: `frontend/src/api/llm.ts`
- Create: `frontend/src/components/ai-analysis/LLMCommentary.tsx`
- Modify: `frontend/src/pages/AIAnalyzer.tsx` — Full restructure

- [ ] **Step 1: Create LLM types + API**

```typescript
// frontend/src/types/llm.ts
export interface LLMCommentaryResponse {
  status: 'success' | 'error'
  message?: string
  data?: {
    commentary: string
    provider: string
    model: string
  }
}

export interface LLMModel {
  id: string
  name: string
  provider: string
  type: string
  enabled: boolean
}
```

```typescript
// frontend/src/api/llm.ts
import { apiClient } from './client'
import type { LLMCommentaryResponse } from '@/types/llm'

export const llmApi = {
  getCommentary: async (apiKey: string, analysis: Record<string, unknown>): Promise<LLMCommentaryResponse> => {
    const response = await apiClient.post<LLMCommentaryResponse>('/llm/commentary', {
      apikey: apiKey,
      analysis,
    })
    return response.data
  },

  getModels: async () => {
    const response = await apiClient.get('/llm/models')
    return response.data
  },
}
```

- [ ] **Step 2: Create LLMCommentary component**

```tsx
// frontend/src/components/ai-analysis/LLMCommentary.tsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/stores/authStore'
import { llmApi } from '@/api/llm'
import { Bot, Loader2, RefreshCw } from 'lucide-react'
import type { AIAnalysisResult } from '@/types/ai-analysis'

interface LLMCommentaryProps {
  analysis: AIAnalysisResult | null
}

export function LLMCommentary({ analysis }: LLMCommentaryProps) {
  const apiKey = useAuthStore((s) => s.apiKey)
  const [enabled, setEnabled] = useState(false)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['llm-commentary', analysis?.symbol, analysis?.signal],
    queryFn: async () => {
      if (!apiKey || !analysis) return null
      const response = await llmApi.getCommentary(apiKey, analysis as unknown as Record<string, unknown>)
      return response.data ?? null
    },
    enabled: enabled && !!apiKey && !!analysis,
    staleTime: 120_000,
  })

  if (!analysis) return null

  if (!enabled) {
    return (
      <Button variant="outline" size="sm" onClick={() => setEnabled(true)}>
        <Bot className="h-4 w-4 mr-1" /> Get AI Commentary
      </Button>
    )
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Generating commentary...
      </div>
    )
  }

  if (!data) {
    return <p className="text-xs text-muted-foreground">LLM unavailable — check Ollama or set GEMINI_API_KEY</p>
  }

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <Bot className="h-4 w-4 mt-0.5 text-blue-500 shrink-0" />
        <p className="text-sm">{data.commentary}</p>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">via {data.provider}/{data.model}</span>
        <Button variant="ghost" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-3 w-3" />
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Restructure AIAnalyzer.tsx — Full Dashboard**

Replace `frontend/src/pages/AIAnalyzer.tsx` with the new layout:

```tsx
// frontend/src/pages/AIAnalyzer.tsx
import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Loader2, Search, TrendingUp, BarChart3, History, Scan } from 'lucide-react'
import {
  SignalBadge, ConfidenceGauge, SubScoresChart, IndicatorTable, ScanResultsTable,
  AdvancedSignalsPanel, LivePriceHeader, MLConfidenceBar, LevelsPanel,
  TradeActionPanel, DecisionHistory, LLMCommentary,
} from '@/components/ai-analysis'
import { useAIAnalysis, useAIScan, useAIStatus } from '@/hooks/useAIAnalysis'
import { REGIME_CONFIG } from '@/types/ai-analysis'
import { showToast } from '@/utils/toast'

const NIFTY50 = [
  'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'HINDUNILVR', 'SBIN',
  'BHARTIARTL', 'ITC', 'KOTAKBANK', 'LT', 'AXISBANK', 'BAJFINANCE',
  'ASIANPAINT', 'MARUTI', 'TITAN', 'SUNPHARMA', 'WIPRO', 'HCLTECH', 'ULTRACEMCO',
]

export default function AIAnalyzer() {
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
    if (!symbol.trim()) { showToast.error('Enter a symbol'); return }
    refetch()
  }

  return (
    <div className="container mx-auto p-4 space-y-4">
      {/* Header + Controls */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-5 w-5" />
          <h1 className="text-xl font-bold">AI Trading Intelligence</h1>
          {statusData && (
            <span className="text-xs text-muted-foreground hidden md:inline">
              {statusData.engine} | {statusData.indicators} indicators
            </span>
          )}
        </div>
        <div className="flex gap-2 items-end flex-wrap">
          <Input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="RELIANCE" className="w-32" />
          <Select value={exchange} onValueChange={setExchange}>
            <SelectTrigger className="w-20"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="NSE">NSE</SelectItem>
              <SelectItem value="BSE">BSE</SelectItem>
            </SelectContent>
          </Select>
          <Select value={interval} onValueChange={setInterval}>
            <SelectTrigger className="w-20"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="1d">Daily</SelectItem>
              <SelectItem value="1h">1H</SelectItem>
              <SelectItem value="15m">15m</SelectItem>
              <SelectItem value="5m">5m</SelectItem>
            </SelectContent>
          </Select>
          <Button onClick={handleAnalyze} disabled={isLoading} size="sm">
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {error && <p className="text-destructive text-sm">{String(error)}</p>}

      {/* Live Price */}
      {symbol && <LivePriceHeader symbol={symbol} exchange={exchange} />}

      <Tabs defaultValue="analysis" className="w-full">
        <TabsList>
          <TabsTrigger value="analysis"><BarChart3 className="h-4 w-4 mr-1" /> Analysis</TabsTrigger>
          <TabsTrigger value="scanner"><Scan className="h-4 w-4 mr-1" /> Scanner</TabsTrigger>
          <TabsTrigger value="history"><History className="h-4 w-4 mr-1" /> History</TabsTrigger>
        </TabsList>

        {/* ═══ ANALYSIS TAB ═══ */}
        <TabsContent value="analysis" className="space-y-4">
          {analysis && (
            <>
              {/* Row 1: Signal + Trade Action + ML Confidence */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                {/* Signal Card */}
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Signal</CardTitle></CardHeader>
                  <CardContent className="flex flex-col items-center gap-3">
                    <SignalBadge signal={analysis.signal} size="lg" />
                    <ConfidenceGauge confidence={analysis.confidence} />
                    <p className="text-xs text-muted-foreground">
                      {REGIME_CONFIG[analysis.regime]?.label ?? analysis.regime} | {analysis.data_points} bars
                    </p>
                  </CardContent>
                </Card>

                {/* Trade Actions */}
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Trade</CardTitle></CardHeader>
                  <CardContent>
                    <TradeActionPanel
                      symbol={symbol} exchange={exchange}
                      signal={analysis.signal} confidence={analysis.confidence}
                    />
                    <div className="mt-3">
                      <MLConfidenceBar
                        buyConfidence={analysis.advanced?.ml_confidence?.buy ?? 0}
                        sellConfidence={analysis.advanced?.ml_confidence?.sell ?? 0}
                      />
                    </div>
                  </CardContent>
                </Card>

                {/* Sub-Scores */}
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Signal Breakdown</CardTitle></CardHeader>
                  <CardContent>
                    <SubScoresChart scores={analysis.sub_scores} />
                  </CardContent>
                </Card>

                {/* CPR Levels */}
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Pivot Levels</CardTitle></CardHeader>
                  <CardContent>
                    <LevelsPanel cpr={analysis.advanced?.cpr ?? {}} />
                  </CardContent>
                </Card>
              </div>

              {/* Row 2: Advanced Signals + Indicators + LLM */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Pattern Alerts</CardTitle></CardHeader>
                  <CardContent>
                    {analysis.advanced ? (
                      <AdvancedSignalsPanel signals={analysis.advanced} />
                    ) : (
                      <p className="text-xs text-muted-foreground">No advanced data</p>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">Indicators</CardTitle></CardHeader>
                  <CardContent className="max-h-64 overflow-auto">
                    <IndicatorTable indicators={analysis.indicators} />
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-sm">AI Commentary</CardTitle></CardHeader>
                  <CardContent>
                    <LLMCommentary analysis={analysis} />
                  </CardContent>
                </Card>
              </div>
            </>
          )}

          {!analysis && !isLoading && (
            <div className="text-center py-12 text-muted-foreground">
              Enter a symbol and click Analyze to get AI trading intelligence
            </div>
          )}
        </TabsContent>

        {/* ═══ SCANNER TAB ═══ */}
        <TabsContent value="scanner" className="space-y-4">
          <Card>
            <CardContent className="pt-4 space-y-4">
              <div className="flex gap-2 items-end">
                <div className="flex-1">
                  <Input value={scanSymbols} onChange={(e) => setScanSymbols(e.target.value.toUpperCase())}
                    placeholder="RELIANCE, TCS, INFY... (empty = NIFTY 50)" />
                </div>
                <Button onClick={() => setRunScan(true)} disabled={scanLoading}>
                  {scanLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Scan className="h-4 w-4 mr-1" />}
                  Scan
                </Button>
              </div>
              {scanResults && <ScanResultsTable results={scanResults} />}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ═══ HISTORY TAB ═══ */}
        <TabsContent value="history">
          <Card>
            <CardContent className="pt-4">
              <DecisionHistory symbol={symbol} limit={20} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
```

- [ ] **Step 4: Update barrel export with all new components**

```typescript
// frontend/src/components/ai-analysis/index.ts
export { SignalBadge } from './SignalBadge'
export { ConfidenceGauge } from './ConfidenceGauge'
export { SubScoresChart } from './SubScoresChart'
export { IndicatorTable } from './IndicatorTable'
export { ScanResultsTable } from './ScanResultsTable'
export { AdvancedSignalsPanel } from './AdvancedSignalsPanel'
export { LivePriceHeader } from './LivePriceHeader'
export { MLConfidenceBar } from './MLConfidenceBar'
export { LevelsPanel } from './LevelsPanel'
export { TradeActionPanel } from './TradeActionPanel'
export { DecisionHistory } from './DecisionHistory'
export { LLMCommentary } from './LLMCommentary'
```

- [ ] **Step 5: Build**

Run: `cd D:\openalgo\frontend && npm run build`

- [ ] **Step 6: Commit**

```bash
cd D:\openalgo\frontend
git add src/
git commit -m "feat(ai-ui): complete trading decision dashboard — live price, patterns, trade, LLM commentary, history"

cd D:\openalgo
git add ai/ services/ restx_api/ test/
git commit -m "feat(ai): LLM router + model registry + commentary API"
```

---

## Summary

| Task | Files | Tests | Description |
|------|-------|-------|-------------|
| 1 | 2 new, 1 mod | 4 | AdvancedSignalsPanel (SMC, candlestick, harmonic, divergence) |
| 2 | 3 new | — | LivePriceHeader, MLConfidenceBar, LevelsPanel |
| 3 | 2 new | — | TradeActionPanel (PlaceOrderDialog), DecisionHistory |
| 4 | 2 new | 8 | LLM Router (Ollama→Gemini) + Model Registry |
| 5 | 2 new, 1 mod | — | LLM Commentary API endpoint |
| 6 | 3 new, 1 mod | — | LLM frontend + restructured dashboard |
| **Total** | **14 new, 3 mod** | **~12** | — |

### Dashboard Layout

```
┌─ AI Trading Intelligence ─── [RELIANCE] [NSE] [1d] [🔍] ──────────┐
│ ₹2,456.80 +12.50 (+0.51%) Bid:2456 Ask:2457 📶                   │
├── [Analysis] [Scanner] [History] ──────────────────────────────────┤
│                                                                     │
│ ┌─Signal──┐ ┌─Trade─────┐ ┌─Breakdown──┐ ┌─Pivot Levels─┐        │
│ │ ██BUY██ │ │ [BUY]     │ │ ST   ████  │ │ R3  2490.81  │        │
│ │  ╭───╮  │ │ [SELL]    │ │ RSI  ███   │ │ R2  2480.20  │        │
│ │  │75%│  │ │           │ │ MACD ██    │ │ R1  2465.80  │        │
│ │  ╰───╯  │ │ ML: ██░░  │ │ EMA  ████  │ │ TC  2455.29  │        │
│ │TREND UP │ │ Buy:72%   │ │ BB   ██    │ │ *P  2450.19* │        │
│ └─────────┘ └───────────┘ │ ADX  █     │ │ BC  2445.08  │        │
│                            └────────────┘ │ S1  2435.79  │        │
│                                           └──────────────┘        │
│ ┌─Pattern Alerts─────┐ ┌─Indicators──┐ ┌─AI Commentary──────────┐│
│ │ ⚡ Smart Money      │ │ RSI(14) 42.5│ │ 🤖 RELIANCE shows a   ││
│ │   FVG Bullish      │ │ MACD    1.23│ │ bullish setup with     ││
│ │   BOS Bearish      │ │ ADX    28.4 │ │ RSI oversold + FVG.   ││
│ │ 🕯 Candlestick     │ │ EMA9  2452  │ │ Consider buying near   ││
│ │   doji, hammer     │ │ BB%B  0.23  │ │ CPR support at 2445.  ││
│ │ ⚠ RSI Divergence   │ │ ATR   18.5  │ │ via ollama/qwen3.5:9b ││
│ │   Bearish          │ │ VWAP 2448   │ │ [🔄 Refresh]          ││
│ └────────────────────┘ └─────────────┘ └────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

### Extensibility Architecture

```
Model Registry (ai/model_registry.py)
├── LLM: ollama-qwen (priority 1, local)
├── LLM: gemini-flash (priority 2, free)
├── LLM: [future] openai-gpt4 (priority 3)
├── LLM: [future] anthropic-claude (priority 4)
├── DL:  [future] custom-lstm (local PyTorch)
├── DL:  [future] fine-tuned-transformer
└── Agent: [future] new-agent-connector

LLM Router (ai/llm_router.py)
├── _call_ollama()  ← Add new provider by adding _call_{provider}()
├── _call_gemini()
├── [future] _call_openai()
├── [future] _call_anthropic()
└── [future] _call_vllm()
```

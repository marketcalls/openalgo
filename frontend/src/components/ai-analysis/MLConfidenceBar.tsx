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

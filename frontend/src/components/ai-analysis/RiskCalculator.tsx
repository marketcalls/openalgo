import { useState, useMemo, useEffect } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface RiskCalculatorProps {
  entry: number
  stopLoss: number
  onQtyChange?: (qty: number) => void
}

function formatINR(value: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 0,
  }).format(value)
}

export function RiskCalculator({ entry, stopLoss, onQtyChange }: RiskCalculatorProps) {
  const [balance, setBalance] = useState(100000)
  const [riskPercent, setRiskPercent] = useState(1)

  const calc = useMemo(() => {
    const maxRisk = (balance * riskPercent) / 100
    const slDistance = Math.abs(entry - stopLoss)
    const qty = slDistance > 0 ? Math.max(Math.floor(maxRisk / slDistance), 1) : 0
    const positionValue = qty * entry
    const actualRisk = qty * slDistance

    return { maxRisk, slDistance, qty, positionValue, actualRisk }
  }, [balance, riskPercent, entry, stopLoss])

  useEffect(() => {
    if (onQtyChange && calc.qty > 0) {
      onQtyChange(calc.qty)
    }
  }, [calc.qty, onQtyChange])

  if (!entry || !stopLoss || entry === 0) {
    return <p className="text-xs text-muted-foreground">No trade setup available</p>
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <Label className="text-xs">Account Balance</Label>
          <Input
            type="number"
            value={balance}
            onChange={(e) => setBalance(Number(e.target.value))}
            className="h-8 text-sm"
          />
        </div>
        <div>
          <Label className="text-xs">Risk %</Label>
          <Input
            type="number"
            value={riskPercent}
            onChange={(e) => setRiskPercent(Number(e.target.value))}
            className="h-8 text-sm"
            min={0.1}
            max={5}
            step={0.1}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="bg-muted/50 p-2 rounded">
          <div className="text-xs text-muted-foreground">Max Risk</div>
          <div className="font-semibold">{formatINR(calc.maxRisk)}</div>
        </div>
        <div className="bg-muted/50 p-2 rounded">
          <div className="text-xs text-muted-foreground">SL Distance</div>
          <div className="font-semibold">{formatINR(calc.slDistance)}</div>
        </div>
        <div className="bg-muted/50 p-2 rounded">
          <div className="text-xs text-muted-foreground">Qty (Suggested)</div>
          <div className="font-semibold text-blue-600">{calc.qty} shares</div>
        </div>
        <div className="bg-muted/50 p-2 rounded">
          <div className="text-xs text-muted-foreground">Position Value</div>
          <div className="font-semibold">{formatINR(calc.positionValue)}</div>
        </div>
      </div>

      <div className="text-xs text-muted-foreground">
        Actual risk: {formatINR(calc.actualRisk)} (
        {((calc.actualRisk / balance) * 100).toFixed(2)}% of account)
      </div>
    </div>
  )
}

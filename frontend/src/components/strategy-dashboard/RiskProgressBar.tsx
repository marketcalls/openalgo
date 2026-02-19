import { Progress } from '@/components/ui/progress'

interface RiskProgressBarProps {
  label: string
  currentPrice: number
  entryPrice: number
  triggerPrice: number
  action: 'BUY' | 'SELL'
  type: 'sl' | 'tgt' | 'tsl'
}

export function RiskProgressBar({
  label,
  currentPrice,
  entryPrice,
  triggerPrice,
  action,
  type,
}: RiskProgressBarProps) {
  // Calculate distance from entry to trigger and from current to trigger
  const totalRange = Math.abs(triggerPrice - entryPrice)
  const consumed =
    action === 'BUY'
      ? type === 'sl' || type === 'tsl'
        ? entryPrice - currentPrice // SL: how much price dropped
        : currentPrice - entryPrice // TGT: how much price rose
      : type === 'sl' || type === 'tsl'
        ? currentPrice - entryPrice // Short SL: how much price rose
        : entryPrice - currentPrice // Short TGT: how much price dropped

  const progress = totalRange > 0 ? Math.max(0, Math.min(100, (consumed / totalRange) * 100)) : 0

  // Color based on progress and type
  let color = ''
  if (type === 'sl' || type === 'tsl') {
    // SL/TSL: green (safe) → amber (warning) → red (danger)
    if (progress < 50) color = '[&>div]:bg-green-500'
    else if (progress < 80) color = '[&>div]:bg-amber-500'
    else color = '[&>div]:bg-red-500'
  } else {
    // TGT: red (far) → amber → green (close to target)
    if (progress < 50) color = '[&>div]:bg-red-300'
    else if (progress < 80) color = '[&>div]:bg-amber-500'
    else color = '[&>div]:bg-green-500'
  }

  const distPts = Math.abs(currentPrice - triggerPrice).toFixed(2)
  const distPct = entryPrice > 0 ? ((Math.abs(currentPrice - triggerPrice) / entryPrice) * 100).toFixed(1) : '0.0'

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground">
          {distPts} pts ({distPct}%)
        </span>
      </div>
      <Progress value={progress} className={`h-2 ${color}`} />
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>Entry: {entryPrice.toFixed(2)}</span>
        <span>Trigger: {triggerPrice.toFixed(2)}</span>
      </div>
    </div>
  )
}

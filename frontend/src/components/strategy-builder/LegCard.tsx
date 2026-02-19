import { TrashIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { BuilderLeg, StrikeType } from '@/types/strategy-builder'

interface LegCardProps {
  leg: BuilderLeg
  index: number
  onChange: (leg: BuilderLeg) => void
  onRemove: () => void
  frozen?: boolean
}

const STRIKE_TYPES: { value: StrikeType; label: string }[] = [
  { value: 'ATM', label: 'ATM' },
  { value: 'ITM', label: 'ITM' },
  { value: 'OTM', label: 'OTM' },
  { value: 'specific', label: 'Specific Strike' },
  { value: 'premium_near', label: 'Premium Near' },
]

function getOffsets(strikeType: StrikeType): string[] {
  switch (strikeType) {
    case 'ATM':
      return ['ATM']
    case 'ITM':
      return Array.from({ length: 20 }, (_, i) => `ITM${i + 1}`)
    case 'OTM':
      return Array.from({ length: 20 }, (_, i) => `OTM${i + 1}`)
    default:
      return ['ATM']
  }
}

export function LegCard({ leg, index, onChange, onRemove, frozen }: LegCardProps) {
  const update = <K extends keyof BuilderLeg>(key: K, value: BuilderLeg[K]) =>
    onChange({ ...leg, [key]: value })

  const offsets = getOffsets(leg.strike_type)
  const showOffset = leg.strike_type === 'ITM' || leg.strike_type === 'OTM'

  const handleStrikeTypeChange = (v: string) => {
    const st = v as StrikeType
    let offset = leg.offset
    if (st === 'ATM') offset = 'ATM'
    else if (st === 'ITM') offset = 'ITM1'
    else if (st === 'OTM') offset = 'OTM1'
    else offset = 'ATM'
    onChange({ ...leg, strike_type: st, offset })
  }

  return (
    <Card className={frozen ? 'relative overflow-hidden opacity-75 pointer-events-none' : ''}>
      {frozen && <FrozenLegOverlay />}
      <CardContent className="p-3">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium">
            Leg {index + 1}
            <span className={`ml-2 ${leg.action === 'BUY' ? 'text-green-600' : 'text-red-600'}`}>
              {leg.action} {leg.option_type || 'FUT'}
              {leg.offset !== 'ATM' ? ` ${leg.offset}` : ' ATM'}
            </span>
          </span>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onRemove} disabled={frozen}>
            <TrashIcon className="h-3.5 w-3.5 text-muted-foreground" />
          </Button>
        </div>
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
          <div className="space-y-1">
            <Label className="text-[10px]">Action</Label>
            <Select value={leg.action} onValueChange={(v) => update('action', v as 'BUY' | 'SELL')}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="BUY">BUY</SelectItem>
                <SelectItem value="SELL">SELL</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label className="text-[10px]">Type</Label>
            <Select
              value={leg.option_type || 'FUT'}
              onValueChange={(v) => update('option_type', v === 'FUT' ? null : (v as 'CE' | 'PE'))}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="CE">CE</SelectItem>
                <SelectItem value="PE">PE</SelectItem>
                <SelectItem value="FUT">Future</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label className="text-[10px]">Strike Type</Label>
            <Select value={leg.strike_type} onValueChange={handleStrikeTypeChange}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STRIKE_TYPES.map((st) => (
                  <SelectItem key={st.value} value={st.value}>
                    {st.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {showOffset && (
            <div className="space-y-1">
              <Label className="text-[10px]">Offset</Label>
              <Select value={leg.offset} onValueChange={(v) => update('offset', v)}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {offsets.map((o) => (
                    <SelectItem key={o} value={o}>
                      {o}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="space-y-1">
            <Label className="text-[10px]">Lots</Label>
            <Input
              type="number"
              min={1}
              className="h-8 text-xs"
              value={leg.quantity_lots}
              onChange={(e) => update('quantity_lots', Math.max(1, Number(e.target.value)))}
            />
          </div>

          <div className="space-y-1">
            <Label className="text-[10px]">Expiry</Label>
            <Select
              value={leg.expiry_type}
              onValueChange={(v) => update('expiry_type', v as BuilderLeg['expiry_type'])}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="current_week">Curr Week</SelectItem>
                <SelectItem value="next_week">Next Week</SelectItem>
                <SelectItem value="current_month">Curr Month</SelectItem>
                <SelectItem value="next_month">Next Month</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label className="text-[10px]">Product</Label>
            <Select
              value={leg.product_type}
              onValueChange={(v) => update('product_type', v as 'MIS' | 'NRML')}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="MIS">MIS</SelectItem>
                <SelectItem value="NRML">NRML</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label className="text-[10px]">Order</Label>
            <Select
              value={leg.order_type}
              onValueChange={(v) => update('order_type', v as 'MARKET' | 'LIMIT')}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="MARKET">Market</SelectItem>
                <SelectItem value="LIMIT">Limit</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function FrozenLegOverlay() {
  return (
    <div
      className="absolute inset-0 z-10"
      style={{
        background: `repeating-linear-gradient(
          -45deg,
          transparent,
          transparent 6px,
          rgba(128, 128, 128, 0.08) 6px,
          rgba(128, 128, 128, 0.08) 12px
        )`,
      }}
    />
  )
}

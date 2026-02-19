import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import type { BuilderBasics } from '@/types/strategy-builder'

interface BasicsStepProps {
  basics: BuilderBasics
  onChange: (basics: BuilderBasics) => void
  onNext: () => void
}

const UNDERLYINGS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX']

export function BasicsStep({ basics, onChange, onNext }: BasicsStepProps) {
  const update = <K extends keyof BuilderBasics>(key: K, value: BuilderBasics[K]) =>
    onChange({ ...basics, [key]: value })

  const isValid = basics.name.trim().length > 0

  return (
    <div className="max-w-lg mx-auto space-y-5">
      <div className="space-y-1.5">
        <Label>Strategy Name</Label>
        <Input
          placeholder="e.g., NIFTY Short Straddle"
          value={basics.name}
          onChange={(e) => update('name', e.target.value)}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label>Exchange</Label>
          <Select value={basics.exchange} onValueChange={(v) => update('exchange', v as 'NFO' | 'BFO')}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="NFO">NFO</SelectItem>
              <SelectItem value="BFO">BFO</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label>Underlying</Label>
          <Select value={basics.underlying} onValueChange={(v) => update('underlying', v)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {UNDERLYINGS.map((u) => (
                <SelectItem key={u} value={u}>
                  {u}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label>Expiry</Label>
          <Select value={basics.expiry_type} onValueChange={(v) => update('expiry_type', v as BuilderBasics['expiry_type'])}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="current_week">Current Week</SelectItem>
              <SelectItem value="next_week">Next Week</SelectItem>
              <SelectItem value="current_month">Current Month</SelectItem>
              <SelectItem value="next_month">Next Month</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label>Product Type</Label>
          <Select value={basics.product_type} onValueChange={(v) => update('product_type', v as 'MIS' | 'NRML')}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="MIS">MIS (Intraday)</SelectItem>
              <SelectItem value="NRML">NRML (Positional)</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label>Trading Mode</Label>
          <Select value={basics.trading_mode} onValueChange={(v) => update('trading_mode', v as BuilderBasics['trading_mode'])}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="BOTH">Both</SelectItem>
              <SelectItem value="LONG">Long Only</SelectItem>
              <SelectItem value="SHORT">Short Only</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-3 pt-6">
          <Switch
            checked={basics.is_intraday}
            onCheckedChange={(v) => update('is_intraday', v)}
          />
          <Label className="text-sm">{basics.is_intraday ? 'Intraday' : 'Positional'}</Label>
        </div>
      </div>

      <div className="pt-4 flex justify-end">
        <Button onClick={onNext} disabled={!isValid}>
          Next: Add Legs
        </Button>
      </div>
    </div>
  )
}

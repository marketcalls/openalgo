import { useState, useEffect } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import { webClient } from '@/api/client'
import type { BuilderBasics, BuilderExchange } from '@/types/strategy-builder'

interface BasicsStepProps {
  basics: BuilderBasics
  onChange: (basics: BuilderBasics) => void
  onNext: () => void
}

const EXCHANGES: { value: BuilderExchange; label: string }[] = [
  { value: 'NFO', label: 'NFO' },
  { value: 'BFO', label: 'BFO' },
  { value: 'CDS', label: 'CDS' },
  { value: 'BCD', label: 'BCD' },
  { value: 'MCX', label: 'MCX' },
]

const DEFAULT_UNDERLYINGS: Record<string, string[]> = {
  NFO: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'],
  BFO: ['SENSEX', 'BANKEX', 'SENSEX50'],
  CDS: ['USDINR', 'EURINR', 'GBPINR', 'JPYINR'],
  BCD: ['USDINR', 'EURINR'],
  MCX: ['CRUDEOIL', 'GOLD', 'SILVER', 'NATURALGAS'],
}

export function BasicsStep({ basics, onChange, onNext }: BasicsStepProps) {
  const [underlyings, setUnderlyings] = useState<string[]>(
    DEFAULT_UNDERLYINGS[basics.exchange] || []
  )
  const [loading, setLoading] = useState(false)

  const update = <K extends keyof BuilderBasics>(key: K, value: BuilderBasics[K]) =>
    onChange({ ...basics, [key]: value })

  // Fetch underlyings dynamically when exchange changes
  useEffect(() => {
    let cancelled = false
    const fetchUnderlyings = async () => {
      setLoading(true)
      try {
        const res = await webClient.get<{ status: string; underlyings: string[] }>(
          `/search/api/underlyings?exchange=${basics.exchange}`
        )
        if (!cancelled && res.data.underlyings?.length > 0) {
          setUnderlyings(res.data.underlyings)
        } else if (!cancelled) {
          setUnderlyings(DEFAULT_UNDERLYINGS[basics.exchange] || [])
        }
      } catch {
        if (!cancelled) {
          setUnderlyings(DEFAULT_UNDERLYINGS[basics.exchange] || [])
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchUnderlyings()
    return () => { cancelled = true }
  }, [basics.exchange])

  // Reset underlying when exchange changes
  const handleExchangeChange = (v: string) => {
    const exchange = v as BuilderExchange
    const defaults = DEFAULT_UNDERLYINGS[exchange] || []
    onChange({ ...basics, exchange, underlying: defaults[0] || '' })
  }

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
          <Select value={basics.exchange} onValueChange={handleExchangeChange}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {EXCHANGES.map((ex) => (
                <SelectItem key={ex.value} value={ex.value}>
                  {ex.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label>Underlying</Label>
          <Select
            value={basics.underlying}
            onValueChange={(v) => update('underlying', v)}
            disabled={loading}
          >
            <SelectTrigger>
              <SelectValue placeholder={loading ? 'Loading...' : 'Select'} />
            </SelectTrigger>
            <SelectContent>
              {underlyings.map((u) => (
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

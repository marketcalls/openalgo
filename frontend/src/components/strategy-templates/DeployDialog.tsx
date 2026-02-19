import { useState, useEffect } from 'react'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { templatesApi, type StrategyTemplate } from '@/api/strategy-templates'
import { webClient } from '@/api/client'
import { showToast } from '@/utils/toast'
import type { BuilderExchange } from '@/types/strategy-builder'

interface DeployDialogProps {
  open: boolean
  onClose: () => void
  template: StrategyTemplate | null
  onDeployed: () => void
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

export function DeployDialog({ open, onClose, template, onDeployed }: DeployDialogProps) {
  const [name, setName] = useState('')
  const [exchange, setExchange] = useState<BuilderExchange>('NFO')
  const [underlying, setUnderlying] = useState('NIFTY')
  const [underlyings, setUnderlyings] = useState<string[]>(DEFAULT_UNDERLYINGS.NFO)
  const [expiryType, setExpiryType] = useState<string>('current_week')
  const [lots, setLots] = useState(1)
  const [slType, setSlType] = useState<string>('')
  const [slValue, setSlValue] = useState<number | null>(null)
  const [tgtType, setTgtType] = useState<string>('')
  const [tgtValue, setTgtValue] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  // Reset when template changes
  const handleOpen = (isOpen: boolean) => {
    if (!isOpen) {
      onClose()
    } else if (template) {
      setName(`${template.name} - ${underlying}`)
    }
  }

  // Fetch underlyings on exchange change
  useEffect(() => {
    let cancelled = false
    const fetchUnderlyings = async () => {
      try {
        const res = await webClient.get<{ status: string; underlyings: string[] }>(
          `/search/api/underlyings?exchange=${exchange}`
        )
        if (!cancelled && res.data.underlyings?.length > 0) {
          setUnderlyings(res.data.underlyings)
        } else if (!cancelled) {
          setUnderlyings(DEFAULT_UNDERLYINGS[exchange] || [])
        }
      } catch {
        if (!cancelled) setUnderlyings(DEFAULT_UNDERLYINGS[exchange] || [])
      }
    }
    fetchUnderlyings()
    return () => { cancelled = true }
  }, [exchange])

  const handleExchangeChange = (v: string) => {
    const ex = v as BuilderExchange
    setExchange(ex)
    const defaults = DEFAULT_UNDERLYINGS[ex] || []
    setUnderlying(defaults[0] || '')
  }

  const handleDeploy = async () => {
    if (!template || !name.trim()) return
    setSaving(true)
    try {
      await templatesApi.deployTemplate(template.id, {
        name,
        exchange,
        underlying,
        expiry_type: expiryType,
        product_type: 'MIS',
        lots,
        default_stoploss_type: slType || null,
        default_stoploss_value: slValue,
        default_target_type: tgtType || null,
        default_target_value: tgtValue,
      })
      showToast.success('Strategy deployed')
      onDeployed()
      onClose()
    } catch {
      showToast.error('Failed to deploy template')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpen}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle>Deploy {template?.name}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label>Strategy Name</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., NIFTY Short Straddle"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Exchange</Label>
              <Select value={exchange} onValueChange={handleExchangeChange}>
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
              <Select value={underlying} onValueChange={setUnderlying}>
                <SelectTrigger>
                  <SelectValue />
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
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Expiry Type</Label>
              <Select value={expiryType} onValueChange={setExpiryType}>
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
              <Label>Lots per Leg</Label>
              <Input
                type="number"
                min={1}
                value={lots}
                onChange={(e) => setLots(Math.max(1, Number(e.target.value)))}
              />
            </div>
          </div>

          {/* Risk Parameters */}
          <div className="border-t pt-3 space-y-3">
            <Label className="text-xs text-muted-foreground">Risk Parameters (optional)</Label>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Stop Loss</Label>
                <div className="flex gap-1.5">
                  <Select value={slType} onValueChange={setSlType}>
                    <SelectTrigger className="h-8 text-xs w-[90px]">
                      <SelectValue placeholder="Off" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="">Off</SelectItem>
                      <SelectItem value="percentage">%</SelectItem>
                      <SelectItem value="points">Pts</SelectItem>
                    </SelectContent>
                  </Select>
                  <Input
                    type="number"
                    step="0.01"
                    className="h-8 text-xs"
                    value={slValue ?? ''}
                    disabled={!slType}
                    onChange={(e) => setSlValue(e.target.value ? Number(e.target.value) : null)}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Target</Label>
                <div className="flex gap-1.5">
                  <Select value={tgtType} onValueChange={setTgtType}>
                    <SelectTrigger className="h-8 text-xs w-[90px]">
                      <SelectValue placeholder="Off" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="">Off</SelectItem>
                      <SelectItem value="percentage">%</SelectItem>
                      <SelectItem value="points">Pts</SelectItem>
                    </SelectContent>
                  </Select>
                  <Input
                    type="number"
                    step="0.01"
                    className="h-8 text-xs"
                    value={tgtValue ?? ''}
                    disabled={!tgtType}
                    onChange={(e) => setTgtValue(e.target.value ? Number(e.target.value) : null)}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleDeploy} disabled={saving || !name.trim()}>
            {saving ? 'Deploying...' : 'Deploy'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

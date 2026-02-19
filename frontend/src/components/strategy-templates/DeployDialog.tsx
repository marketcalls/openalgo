import { useState } from 'react'
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
import { builderApi } from '@/api/strategy-builder'
import { showToast } from '@/utils/toast'
import type { PresetDefinition } from '@/types/strategy-builder'
import { DEFAULT_RISK_CONFIG } from '@/types/strategy-builder'

interface DeployDialogProps {
  open: boolean
  onClose: () => void
  template: PresetDefinition | null
  onDeployed: () => void
}

const UNDERLYINGS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX']

export function DeployDialog({ open, onClose, template, onDeployed }: DeployDialogProps) {
  const [name, setName] = useState('')
  const [exchange, setExchange] = useState<'NFO' | 'BFO'>('NFO')
  const [underlying, setUnderlying] = useState('NIFTY')
  const [lots, setLots] = useState(1)
  const [saving, setSaving] = useState(false)

  // Reset when template changes
  const handleOpen = (isOpen: boolean) => {
    if (!isOpen) {
      onClose()
    } else if (template) {
      setName(`${template.name} - ${underlying}`)
    }
  }

  const handleDeploy = async () => {
    if (!template || !name.trim()) return
    setSaving(true)
    try {
      const legs = template.legs.map((leg) => ({
        ...leg,
        quantity_lots: lots,
      }))

      const result = await builderApi.saveStrategy({
        basics: {
          name,
          exchange,
          underlying,
          expiry_type: 'current_week',
          product_type: 'MIS',
          is_intraday: true,
          trading_mode: 'BOTH',
        },
        legs,
        riskConfig: { ...DEFAULT_RISK_CONFIG },
        preset: template.id,
      })

      if (result.status === 'success') {
        showToast.success('Strategy deployed')
        onDeployed()
        onClose()
      } else {
        showToast.error(result.message || 'Failed to deploy')
      }
    } catch {
      showToast.error('Failed to deploy template')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpen}>
      <DialogContent className="sm:max-w-[400px]">
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
              <Select value={exchange} onValueChange={(v) => setExchange(v as 'NFO' | 'BFO')}>
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
              <Select value={underlying} onValueChange={setUnderlying}>
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

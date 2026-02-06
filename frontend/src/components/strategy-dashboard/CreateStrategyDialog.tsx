import { Info, Zap } from 'lucide-react'
import { useState } from 'react'
import { showToast } from '@/utils/toast'
import { strategyApi } from '@/api/strategy'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { PLATFORMS, TRADING_MODES } from '@/types/strategy'

interface CreateStrategyDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (strategyId: number) => void
}

export function CreateStrategyDialog({ open, onOpenChange, onCreated }: CreateStrategyDialogProps) {
  const [loading, setLoading] = useState(false)
  const [formData, setFormData] = useState({
    name: '',
    platform: '',
    strategy_type: 'intraday',
    trading_mode: 'LONG',
    start_time: '09:15',
    end_time: '15:00',
    squareoff_time: '15:15',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})

  const resetForm = () => {
    setFormData({
      name: '',
      platform: '',
      strategy_type: 'intraday',
      trading_mode: 'LONG',
      start_time: '09:15',
      end_time: '15:00',
      squareoff_time: '15:15',
    })
    setErrors({})
  }

  const validateForm = () => {
    const newErrors: Record<string, string> = {}

    if (!formData.name.trim()) {
      newErrors.name = 'Strategy name is required'
    } else if (formData.name.length < 3 || formData.name.length > 50) {
      newErrors.name = 'Name must be between 3 and 50 characters'
    } else if (!/^[a-zA-Z0-9\s\-_]+$/.test(formData.name)) {
      newErrors.name = 'Name can only contain letters, numbers, spaces, hyphens, and underscores'
    }

    if (!formData.platform) {
      newErrors.platform = 'Please select a platform'
    }

    if (formData.strategy_type === 'intraday') {
      const { start_time, end_time, squareoff_time } = formData
      if (!start_time || !end_time || !squareoff_time) {
        newErrors.time = 'All time fields are required for intraday strategies'
      } else if (start_time >= end_time) {
        newErrors.time = 'Start time must be before end time'
      } else if (end_time >= squareoff_time) {
        newErrors.time = 'End time must be before square off time'
      }
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validateForm()) {
      showToast.error('Please fix the form errors', 'strategy')
      return
    }

    try {
      setLoading(true)
      const response = await strategyApi.createStrategy({
        name: formData.name,
        platform: formData.platform,
        strategy_type: formData.strategy_type as 'intraday' | 'positional',
        trading_mode: formData.trading_mode as 'LONG' | 'SHORT' | 'BOTH',
        ...(formData.strategy_type === 'intraday' && {
          start_time: formData.start_time,
          end_time: formData.end_time,
          squareoff_time: formData.squareoff_time,
        }),
      })

      if (response.status === 'success' && response.data?.strategy_id) {
        showToast.success('Strategy created successfully', 'strategy')
        resetForm()
        onOpenChange(false)
        onCreated(response.data.strategy_id)
      } else {
        showToast.error(response.message || 'Failed to create strategy', 'strategy')
      }
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to create strategy'
      showToast.error(errorMessage, 'strategy')
    } finally {
      setLoading(false)
    }
  }

  const finalName =
    formData.platform && formData.name
      ? `${formData.platform}_${formData.name.toLowerCase().replace(/\s+/g, '_')}`
      : ''

  return (
    <Dialog open={open} onOpenChange={(isOpen) => {
      if (!isOpen) resetForm()
      onOpenChange(isOpen)
    }}>
      <DialogContent className="sm:max-w-[500px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Zap className="h-5 w-5" />
            Create New Strategy
          </DialogTitle>
          <DialogDescription>
            Set up a new webhook strategy to receive trading alerts
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Strategy Name */}
          <div className="space-y-1.5">
            <Label htmlFor="dialog-name">Strategy Name</Label>
            <Input
              id="dialog-name"
              placeholder="My Trading Strategy"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className={errors.name ? 'border-red-500' : ''}
            />
            {errors.name && <p className="text-xs text-red-500">{errors.name}</p>}
            <p className="text-xs text-muted-foreground">
              3-50 chars. Letters, numbers, spaces, hyphens, underscores.
            </p>
          </div>

          {/* Platform */}
          <div className="space-y-1.5">
            <Label>Platform</Label>
            <Select
              value={formData.platform}
              onValueChange={(value) => setFormData({ ...formData, platform: value })}
            >
              <SelectTrigger className={errors.platform ? 'border-red-500' : ''}>
                <SelectValue placeholder="Select platform" />
              </SelectTrigger>
              <SelectContent>
                {PLATFORMS.map((platform) => (
                  <SelectItem key={platform.value} value={platform.value}>
                    {platform.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {errors.platform && <p className="text-xs text-red-500">{errors.platform}</p>}
          </div>

          {/* Final Name Preview */}
          {finalName && (
            <Alert>
              <Info className="h-4 w-4" />
              <AlertDescription className="text-xs">
                Final name: <code className="bg-muted px-1 rounded font-mono">{finalName}</code>
              </AlertDescription>
            </Alert>
          )}

          {/* Strategy Type */}
          <div className="space-y-1.5">
            <Label>Strategy Type</Label>
            <Select
              value={formData.strategy_type}
              onValueChange={(value) => setFormData({ ...formData, strategy_type: value })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="intraday">Intraday</SelectItem>
                <SelectItem value="positional">Positional</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Trading Mode */}
          <div className="space-y-1.5">
            <Label>Trading Mode</Label>
            <Select
              value={formData.trading_mode}
              onValueChange={(value) => setFormData({ ...formData, trading_mode: value })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TRADING_MODES.map((mode) => (
                  <SelectItem key={mode.value} value={mode.value}>
                    {mode.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {TRADING_MODES.find((m) => m.value === formData.trading_mode)?.description}
            </p>
          </div>

          {/* Intraday Time Settings */}
          {formData.strategy_type === 'intraday' && (
            <div className="space-y-3 p-3 border rounded-lg bg-muted/50">
              <h4 className="text-sm font-medium">Trading Hours</h4>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Start</Label>
                  <Input
                    type="time"
                    value={formData.start_time}
                    onChange={(e) => setFormData({ ...formData, start_time: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">End</Label>
                  <Input
                    type="time"
                    value={formData.end_time}
                    onChange={(e) => setFormData({ ...formData, end_time: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Square Off</Label>
                  <Input
                    type="time"
                    value={formData.squareoff_time}
                    onChange={(e) => setFormData({ ...formData, squareoff_time: e.target.value })}
                  />
                </div>
              </div>
              {errors.time && <p className="text-xs text-red-500">{errors.time}</p>}
            </div>
          )}

          {/* Submit */}
          <div className="flex gap-3 pt-2">
            <Button
              type="button"
              variant="outline"
              className="flex-1"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" className="flex-1" disabled={loading}>
              {loading ? 'Creating...' : 'Create Strategy'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

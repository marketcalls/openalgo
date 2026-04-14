import { ArrowLeft, Info, Zap } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { strategyApi } from '@/api/strategy'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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

export default function NewStrategy() {
  const navigate = useNavigate()
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

  const validateForm = () => {
    const newErrors: Record<string, string> = {}

    // Name validation
    if (!formData.name.trim()) {
      newErrors.name = 'Strategy name is required'
    } else if (formData.name.length < 3 || formData.name.length > 50) {
      newErrors.name = 'Name must be between 3 and 50 characters'
    } else if (!/^[a-zA-Z0-9\s\-_]+$/.test(formData.name)) {
      newErrors.name = 'Name can only contain letters, numbers, spaces, hyphens, and underscores'
    }

    // Platform validation
    if (!formData.platform) {
      newErrors.platform = 'Please select a platform'
    }

    // Time validation for intraday
    if (formData.strategy_type === 'intraday') {
      const start = formData.start_time
      const end = formData.end_time
      const squareoff = formData.squareoff_time

      if (!start || !end || !squareoff) {
        newErrors.time = 'All time fields are required for intraday strategies'
      } else if (start >= end) {
        newErrors.time = 'Start time must be before end time'
      } else if (end >= squareoff) {
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

      if (response.status === 'success') {
        showToast.success('Strategy created successfully', 'strategy')
        navigate(`/strategy/${response.data?.strategy_id}`)
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
    <div className="container mx-auto py-6 max-w-2xl space-y-6">
      {/* Back Button */}
      <Button variant="ghost" asChild>
        <Link to="/strategy">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Strategies
        </Link>
      </Button>

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Create New Strategy</h1>
        <p className="text-muted-foreground">
          Set up a new webhook strategy to receive trading alerts
        </p>
      </div>

      {/* Form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-5 w-5" />
            Strategy Details
          </CardTitle>
          <CardDescription>Configure your webhook strategy settings</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Strategy Name */}
            <div className="space-y-2">
              <Label htmlFor="name">Strategy Name</Label>
              <Input
                id="name"
                placeholder="My Trading Strategy"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className={errors.name ? 'border-red-500' : ''}
              />
              {errors.name && <p className="text-sm text-red-500">{errors.name}</p>}
              <p className="text-xs text-muted-foreground">
                3-50 characters. Letters, numbers, spaces, hyphens, and underscores only.
              </p>
            </div>

            {/* Platform */}
            <div className="space-y-2">
              <Label htmlFor="platform">Platform</Label>
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
              {errors.platform && <p className="text-sm text-red-500">{errors.platform}</p>}
            </div>

            {/* Final Name Preview */}
            {finalName && (
              <Alert>
                <Info className="h-4 w-4" />
                <AlertDescription>
                  Final strategy name:{' '}
                  <code className="bg-muted px-1 rounded font-mono">{finalName}</code>
                </AlertDescription>
              </Alert>
            )}

            {/* Strategy Type */}
            <div className="space-y-2">
              <Label htmlFor="strategy_type">Strategy Type</Label>
              <Select
                value={formData.strategy_type}
                onValueChange={(value) => setFormData({ ...formData, strategy_type: value })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="intraday">Intraday</SelectItem>
                  <SelectItem value="positional">Positional</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Intraday strategies have trading hours and auto square-off.
              </p>
            </div>

            {/* Trading Mode */}
            <div className="space-y-2">
              <Label htmlFor="trading_mode">Trading Mode</Label>
              <Select
                value={formData.trading_mode}
                onValueChange={(value) => setFormData({ ...formData, trading_mode: value })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select mode" />
                </SelectTrigger>
                <SelectContent>
                  {TRADING_MODES.map((mode) => (
                    <SelectItem key={mode.value} value={mode.value}>
                      <div className="flex flex-col">
                        <span>{mode.label}</span>
                      </div>
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
              <div className="space-y-4 p-4 border rounded-lg bg-muted/50">
                <h4 className="font-medium">Trading Hours</h4>

                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="start_time">Start Time</Label>
                    <Input
                      id="start_time"
                      type="time"
                      value={formData.start_time}
                      onChange={(e) => setFormData({ ...formData, start_time: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="end_time">End Time</Label>
                    <Input
                      id="end_time"
                      type="time"
                      value={formData.end_time}
                      onChange={(e) => setFormData({ ...formData, end_time: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="squareoff_time">Square Off</Label>
                    <Input
                      id="squareoff_time"
                      type="time"
                      value={formData.squareoff_time}
                      onChange={(e) => setFormData({ ...formData, squareoff_time: e.target.value })}
                    />
                  </div>
                </div>

                {errors.time && <p className="text-sm text-red-500">{errors.time}</p>}
                <p className="text-xs text-muted-foreground">
                  Orders will only be placed during trading hours. Positions will be squared off at
                  the specified time.
                </p>
              </div>
            )}

            {/* Submit */}
            <div className="flex gap-3 pt-4">
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                onClick={() => navigate('/strategy')}
              >
                Cancel
              </Button>
              <Button type="submit" className="flex-1" disabled={loading}>
                {loading ? 'Creating...' : 'Create Strategy'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

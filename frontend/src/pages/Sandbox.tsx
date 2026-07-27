import { BarChart3, RotateCcw, Save, Settings } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
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

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', {
    credentials: 'include',
  })
  const data = await response.json()
  return data.csrf_token
}

interface ConfigItem {
  value: string
  description: string
}

interface ConfigCategory {
  title: string
  configs: Record<string, ConfigItem>
}

type Configs = Record<string, ConfigCategory>

const DAYS_OF_WEEK = [
  'Never',
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
]

const CAPITAL_OPTIONS = [
  { value: '100000', label: '1,00,000 (1 Lakh)' },
  { value: '500000', label: '5,00,000 (5 Lakhs)' },
  { value: '1000000', label: '10,00,000 (10 Lakhs)' },
  { value: '2500000', label: '25,00,000 (25 Lakhs)' },
  { value: '5000000', label: '50,00,000 (50 Lakhs)' },
  { value: '10000000', label: '1,00,00,000 (1 Crore)' },
]

function formatConfigLabel(key: string): string {
  return key
    .split('_')
    .map((word) => {
      const upper = word.toUpperCase()
      if (['NSE', 'BSE', 'CDS', 'BCD', 'MCX', 'NCDEX', 'MIS', 'CNC', 'NRML'].includes(upper)) {
        return upper
      }
      return word.charAt(0).toUpperCase() + word.slice(1)
    })
    .join(' ')
}

export default function Sandbox() {
  const [configs, setConfigs] = useState<Configs>({})
  const [modifiedConfigs, setModifiedConfigs] = useState<Set<string>>(new Set())
  const [isLoading, setIsLoading] = useState(true)
  const [isResetting, setIsResetting] = useState(false)
  const [showResetDialog, setShowResetDialog] = useState(false)

  // Fetch configs on mount
  useEffect(() => {
    fetchConfigs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchConfigs = async () => {
    try {
      const response = await fetch('/sandbox/api/configs', {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        if (data.status === 'success') {
          setConfigs(data.configs)
        }
      }
    } catch (error) {
      showToast.error('Failed to load configuration', 'analyzer')
    } finally {
      setIsLoading(false)
    }
  }

  const updateConfig = (configKey: string, value: string) => {
    // Update local state
    setConfigs((prev) => {
      const updated = { ...prev }
      for (const categoryKey in updated) {
        if (updated[categoryKey].configs[configKey]) {
          updated[categoryKey].configs[configKey] = {
            ...updated[categoryKey].configs[configKey],
            value,
          }
          break
        }
      }
      return updated
    })
    setModifiedConfigs((prev) => new Set(prev).add(configKey))
  }

  const saveConfig = async (configKey: string) => {
    // Find the value
    let value = ''
    for (const categoryKey in configs) {
      if (configs[categoryKey].configs[configKey]) {
        value = configs[categoryKey].configs[configKey].value
        break
      }
    }

    try {
      const csrfToken = await fetchCSRFToken()

      const response = await fetch('/sandbox/update', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({
          config_key: configKey,
          config_value: value,
        }),
      })

      const data = await response.json()

      if (data.status === 'success') {
        showToast.success(data.message, 'analyzer')
        setModifiedConfigs((prev) => {
          const updated = new Set(prev)
          updated.delete(configKey)
          return updated
        })
      } else {
        showToast.error(data.message, 'analyzer')
      }
    } catch (error) {
      showToast.error('Failed to save configuration', 'analyzer')
    }
  }

  const resetConfiguration = async () => {
    setIsResetting(true)
    try {
      const csrfToken = await fetchCSRFToken()

      const response = await fetch('/sandbox/reset', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
      })

      const data = await response.json()

      if (data.status === 'success') {
        showToast.success(data.message, 'analyzer')
        setShowResetDialog(false)
        // Reload configs
        setTimeout(() => {
          fetchConfigs()
        }, 1000)
      } else {
        showToast.error(data.message, 'analyzer')
      }
    } catch (error) {
      showToast.error('Failed to reset configuration', 'analyzer')
    } finally {
      setIsResetting(false)
    }
  }

  const renderConfigInput = (configKey: string, configData: ConfigItem) => {
    const isModified = modifiedConfigs.has(configKey)

    // Reset Day selector
    if (configKey === 'reset_day') {
      return (
        <div className="flex gap-2">
          <Select
            value={configData.value}
            onValueChange={(value) => updateConfig(configKey, value)}
          >
            <SelectTrigger className="flex-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DAYS_OF_WEEK.map((day) => (
                <SelectItem key={day} value={day}>
                  {day}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant={isModified ? 'default' : 'secondary'}
            onClick={() => saveConfig(configKey)}
          >
            <Save className="h-4 w-4 mr-1" />
            Set
          </Button>
        </div>
      )
    }

    // Time inputs
    if (configKey === 'reset_time' || configKey.endsWith('_square_off_time')) {
      return (
        <div className="flex gap-2">
          <Input
            type="time"
            value={configData.value || ''}
            onChange={(e) => updateConfig(configKey, e.target.value)}
            className="flex-1"
          />
          <Button
            size="sm"
            variant={isModified ? 'default' : 'secondary'}
            onClick={() => saveConfig(configKey)}
          >
            <Save className="h-4 w-4 mr-1" />
            Set
          </Button>
        </div>
      )
    }

    // Leverage inputs
    if (configKey.endsWith('_leverage')) {
      return (
        <div className="flex gap-2">
          <Input
            type="number"
            value={configData.value || ''}
            onChange={(e) => updateConfig(configKey, e.target.value)}
            min="1"
            max="50"
            step="0.1"
            className="flex-1"
          />
          <Button
            size="sm"
            variant={isModified ? 'default' : 'secondary'}
            onClick={() => saveConfig(configKey)}
          >
            <Save className="h-4 w-4 mr-1" />
            Set
          </Button>
        </div>
      )
    }

    // Starting capital selector
    if (configKey === 'starting_capital') {
      const currentValue = parseFloat(configData.value || '10000000').toFixed(0)
      return (
        <div className="flex gap-2">
          <Select value={currentValue} onValueChange={(value) => updateConfig(configKey, value)}>
            <SelectTrigger className="flex-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CAPITAL_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant={isModified ? 'default' : 'secondary'}
            onClick={() => saveConfig(configKey)}
          >
            <Save className="h-4 w-4 mr-1" />
            Set
          </Button>
        </div>
      )
    }

    // Order check interval / MTM update interval
    if (configKey === 'order_check_interval' || configKey === 'mtm_update_interval') {
      return (
        <div className="flex gap-2">
          <Input
            type="number"
            value={configData.value || ''}
            onChange={(e) => updateConfig(configKey, e.target.value)}
            min={configKey === 'mtm_update_interval' ? 0 : 1}
            max={configKey === 'mtm_update_interval' ? 60 : 30}
            step="1"
            className="flex-1"
          />
          <Button
            size="sm"
            variant={isModified ? 'default' : 'secondary'}
            onClick={() => saveConfig(configKey)}
          >
            <Save className="h-4 w-4 mr-1" />
            Set
          </Button>
        </div>
      )
    }

    // Default text input
    return (
      <div className="flex gap-2">
        <Input
          type="text"
          value={configData.value || ''}
          onChange={(e) => updateConfig(configKey, e.target.value)}
          className="flex-1"
        />
        <Button
          size="sm"
          variant={isModified ? 'default' : 'secondary'}
          onClick={() => saveConfig(configKey)}
        >
          <Save className="h-4 w-4 mr-1" />
          Set
        </Button>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="container mx-auto py-8 px-4 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return (
    <div className="container mx-auto py-6 px-4">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Settings className="h-8 w-8" />
            Sandbox Configuration
          </h1>
          <p className="text-muted-foreground mt-1">Configure sandbox environment settings</p>
        </div>
        <div className="flex gap-3">
          <Button asChild>
            <Link to="/sandbox/mypnl">
              <BarChart3 className="h-4 w-4 mr-2" />
              My P&L
            </Link>
          </Button>
          <Button variant="destructive" onClick={() => setShowResetDialog(true)}>
            <RotateCcw className="h-4 w-4 mr-2" />
            Reset to Defaults
          </Button>
        </div>
      </div>

      {/* Configuration Sections */}
      <div className="space-y-6">
        {Object.entries(configs).map(([categoryKey, category]) => (
          <Card key={categoryKey}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Settings className="h-5 w-5 text-primary" />
                {category.title}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {Object.entries(category.configs).map(([configKey, configData]) => (
                  <div key={configKey} className="space-y-2">
                    <Label htmlFor={configKey} className="font-semibold">
                      {formatConfigLabel(configKey)}
                    </Label>
                    {renderConfigInput(configKey, configData)}
                    <p className="text-xs text-muted-foreground">{configData.description}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Reset Confirmation Dialog */}
      <Dialog open={showResetDialog} onOpenChange={setShowResetDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <RotateCcw className="h-5 w-5" />
              Reset ALL Sandbox Data
            </DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-4 pt-4">
                <Alert variant="destructive">
                  <AlertDescription>This action cannot be undone!</AlertDescription>
                </Alert>

                <div className="space-y-2">
                  <p className="font-semibold">This action will:</p>
                  <ul className="list-disc list-inside space-y-1 ml-4 text-sm">
                    <li>Delete all orders, trades, positions, and holdings</li>
                    <li>Reset funds to starting capital (1.00 Crore)</li>
                    <li>Reset all configuration values to defaults</li>
                    <li>Clear all historical data</li>
                  </ul>
                </div>

                <p className="text-muted-foreground">
                  Are you absolutely sure you want to reset everything?
                </p>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setShowResetDialog(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={resetConfiguration} disabled={isResetting}>
              {isResetting ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current mr-2"></div>
                  Resetting...
                </>
              ) : (
                'Yes, Reset Everything'
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

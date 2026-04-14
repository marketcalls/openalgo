import { Gauge, Loader2, RefreshCw, Save } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { webClient } from '@/api/client'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { showToast } from '@/utils/toast'

const LEVERAGE_OPTIONS = [
  { value: '0', label: 'Default (Broker Setting)' },
  { value: '1', label: '1x' },
  { value: '2', label: '2x' },
  { value: '3', label: '3x' },
  { value: '5', label: '5x' },
  { value: '10', label: '10x' },
  { value: '20', label: '20x' },
  { value: '50', label: '50x' },
]

export default function Leverage() {
  const [currentLeverage, setCurrentLeverage] = useState('0')
  const [selectedLeverage, setSelectedLeverage] = useState('0')
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [fetchError, setFetchError] = useState(false)

  const fetchCurrent = useCallback(async () => {
    setIsLoading(true)
    setFetchError(false)
    try {
      const res = await webClient.get('/leverage/api/current')
      if (res.data.status === 'success') {
        const lev = String(Math.floor(res.data.leverage || 0))
        setCurrentLeverage(lev)
        setSelectedLeverage(lev)
      }
    } catch {
      setFetchError(true)
      showToast.error('Failed to fetch leverage setting')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchCurrent()
  }, [fetchCurrent])

  const handleSave = async () => {
    setIsSaving(true)
    try {
      const res = await webClient.post('/leverage/api/update', {
        leverage: Number(selectedLeverage),
      })
      if (res.data.status === 'success') {
        showToast.success(res.data.message)
        setCurrentLeverage(selectedLeverage)
      } else {
        showToast.error(res.data.message || 'Failed to save')
      }
    } catch {
      showToast.error('Failed to save leverage')
    } finally {
      setIsSaving(false)
    }
  }

  const isModified = selectedLeverage !== currentLeverage

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="container mx-auto py-6 space-y-6 max-w-2xl">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <Gauge className="h-6 w-6 text-primary" />
            <div>
              <CardTitle>Leverage Configuration</CardTitle>
              <CardDescription>
                Set leverage for crypto futures. This leverage is applied before every order
                via the Delta Exchange leverage API.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="leverage">Default Leverage</Label>
              <div className="flex gap-2">
                <Select value={selectedLeverage} onValueChange={setSelectedLeverage} disabled={fetchError}>
                  <SelectTrigger className="w-[250px]" id="leverage">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LEVERAGE_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {fetchError ? (
                <Button size="sm" variant="destructive" onClick={fetchCurrent}>
                  <RefreshCw className="h-4 w-4 mr-1" />
                  Retry
                </Button>
                ) : (
                <Button
                  size="sm"
                  variant={isModified ? 'default' : 'secondary'}
                  onClick={handleSave}
                  disabled={isSaving}
                >
                  {isSaving ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-1" />
                  ) : (
                    <Save className="h-4 w-4 mr-1" />
                  )}
                  Set
                </Button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Default uses the leverage already set on your Delta Exchange account. Other
                values will set leverage before every order.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

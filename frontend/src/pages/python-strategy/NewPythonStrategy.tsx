import { ArrowLeft, Clock, FileCode, FolderOpen, Info, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { pythonStrategyApi } from '@/api/python-strategy'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useStrategyExchanges } from '@/hooks/useStrategyExchanges'
import { CRYPTO_EXCHANGE_VALUE, SCHEDULE_DAYS } from '@/types/python-strategy'
import { showToast } from '@/utils/toast'

const EXAMPLE_STRATEGY = `"""
Example OpenAlgo Strategy
This is a minimal example showing how to use the OpenAlgo Python SDK.
"""

import os
import time
from openalgo import api

API_KEY = os.getenv('OPENALGO_API_KEY')

client = api(
    api_key=API_KEY,
    host_url="http://127.0.0.1:5000"
)

def main():
    print("Strategy started")
    funds = client.funds()
    print(f"Available funds: {funds}")
    while True:
        time.sleep(60)

if __name__ == "__main__":
    main()
`

const SUPPORTED_EXTENSIONS = ['.py', '.sh', '.bat', '.cmd'] as const

export default function NewPythonStrategy() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [mode, setMode] = useState<'upload' | 'path'>('upload')
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [strategyPath, setStrategyPath] = useState('')
  const [workingDir, setWorkingDir] = useState('')
  const [loading, setLoading] = useState(false)
  const [showExample, setShowExample] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const [exchange, setExchange] = useState<string>('NSE')
  const [startTime, setStartTime] = useState('09:00')
  const [stopTime, setStopTime] = useState('16:00')
  const [selectedDays, setSelectedDays] = useState<string[]>(['mon', 'tue', 'wed', 'thu', 'fri'])

  const { exchanges, getWindow } = useStrategyExchanges()
  const isCrypto = exchange === CRYPTO_EXCHANGE_VALUE

  const handleExchangeChange = (value: string) => {
    setExchange(value)
    const session = getWindow(value)
    if (session) {
      setStartTime(session.start)
      setStopTime(session.stop)
    }
    setSelectedDays(
      value === CRYPTO_EXCHANGE_VALUE
        ? ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        : ['mon', 'tue', 'wed', 'thu', 'fri']
    )
  }

  const handleDayToggle = (day: string) => {
    setSelectedDays((prev) => (prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day]))
  }

  const validateForm = () => {
    const newErrors: Record<string, string> = {}

    if (!name.trim()) {
      newErrors.name = 'Strategy name is required'
    } else if (name.length < 3 || name.length > 50) {
      newErrors.name = 'Name must be between 3 and 50 characters'
    } else if (!/^[a-zA-Z0-9\s\-_]+$/.test(name)) {
      newErrors.name = 'Name can only contain letters, numbers, spaces, hyphens, and underscores'
    }

    if (mode === 'upload') {
      if (!file) {
        newErrors.file = 'Please select a strategy file'
      } else if (!SUPPORTED_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext))) {
        newErrors.file = `File must be one of: ${SUPPORTED_EXTENSIONS.join(', ')}`
      }
    } else if (!strategyPath.trim()) {
      newErrors.strategyPath = 'Strategy path is required'
    }

    if (!startTime) newErrors.startTime = 'Start time is required'
    if (!stopTime) newErrors.stopTime = 'Stop time is required'
    if (selectedDays.length === 0) newErrors.days = 'Select at least one day'

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (!selectedFile) return

    if (!SUPPORTED_EXTENSIONS.some((ext) => selectedFile.name.toLowerCase().endsWith(ext))) {
      showToast.error(
        `Please select a supported file (${SUPPORTED_EXTENSIONS.join(', ')})`,
        'pythonStrategy'
      )
      return
    }

    const maxSizeBytes = 1024 * 1024
    if (selectedFile.size > maxSizeBytes) {
      showToast.error('File size must be less than 1MB', 'pythonStrategy')
      return
    }

    setFile(selectedFile)
    if (!name) {
      const baseName = selectedFile.name.replace(/\.(py|sh|bat|cmd)$/i, '').replace(/_/g, ' ')
      setName(baseName.charAt(0).toUpperCase() + baseName.slice(1))
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validateForm()) {
      showToast.error('Please fix the form errors', 'pythonStrategy')
      return
    }

    try {
      setLoading(true)
      const response =
        mode === 'upload'
          ? await pythonStrategyApi.uploadStrategy(name, file!, {
              start_time: startTime,
              stop_time: stopTime,
              days: selectedDays,
              exchange,
            })
          : await pythonStrategyApi.addStrategyFromPath(name, strategyPath.trim(), {
              start_time: startTime,
              stop_time: stopTime,
              days: selectedDays,
              exchange,
              working_dir: workingDir.trim() || undefined,
            })

      if (response.status === 'success') {
        showToast.success(
          mode === 'upload'
            ? 'Strategy uploaded with schedule'
            : 'Strategy path added with schedule',
          'pythonStrategy'
        )
        navigate('/python')
      } else {
        showToast.error(response.message || 'Failed to add strategy', 'pythonStrategy')
      }
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to add strategy'
      showToast.error(errorMessage, 'pythonStrategy')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="container mx-auto py-6 max-w-2xl space-y-6">
      <Button variant="ghost" asChild>
        <Link to="/python">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Python Strategies
        </Link>
      </Button>

      <div>
        <h1 className="text-2xl font-bold tracking-tight">Add Strategy</h1>
        <p className="text-muted-foreground">
          Upload a script or point to a strategy file path from an existing folder.
        </p>
      </div>

      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription>
          Supported types: <code className="bg-muted px-1 rounded">.py</code>,{' '}
          <code className="bg-muted px-1 rounded">.sh</code>,{' '}
          <code className="bg-muted px-1 rounded">.bat/.cmd</code>.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5" />
            Add Strategy
          </CardTitle>
          <CardDescription>Set source, schedule, and exchange settings</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-6">
            <Tabs value={mode} onValueChange={(v) => setMode(v as 'upload' | 'path')}>
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="upload">Upload File</TabsTrigger>
                <TabsTrigger value="path">Run From Folder Path</TabsTrigger>
              </TabsList>
              <TabsContent value="upload" className="space-y-2">
                <Label htmlFor="file">Strategy Script</Label>
                <div
                  className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer hover:border-primary transition-colors ${
                    errors.file ? 'border-red-500' : ''
                  }`}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    id="file"
                    type="file"
                    accept={SUPPORTED_EXTENSIONS.join(',')}
                    className="hidden"
                    onChange={handleFileChange}
                  />
                  {file ? (
                    <div className="flex items-center justify-center gap-2">
                      <FileCode className="h-8 w-8 text-green-500" />
                      <div className="text-left">
                        <p className="font-medium">{file.name}</p>
                        <p className="text-sm text-muted-foreground">
                          {(file.size / 1024).toFixed(2)} KB
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div>
                      <Upload className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
                      <p className="text-sm text-muted-foreground">
                        Click to select a strategy file ({SUPPORTED_EXTENSIONS.join(', ')})
                      </p>
                      <p className="text-xs text-muted-foreground mt-1">Maximum file size: 1MB</p>
                    </div>
                  )}
                </div>
                {errors.file && <p className="text-sm text-red-500">{errors.file}</p>}
              </TabsContent>
              <TabsContent value="path" className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="strategyPath">Strategy File Path</Label>
                  <div className="relative">
                    <FolderOpen className="h-4 w-4 absolute left-3 top-3 text-muted-foreground" />
                    <Input
                      id="strategyPath"
                      className={`pl-9 ${errors.strategyPath ? 'border-red-500' : ''}`}
                      placeholder="/absolute/path/to/strategy.py"
                      value={strategyPath}
                      onChange={(e) => setStrategyPath(e.target.value)}
                    />
                  </div>
                  {errors.strategyPath && (
                    <p className="text-sm text-red-500">{errors.strategyPath}</p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="workingDir">Working Directory (optional)</Label>
                  <Input
                    id="workingDir"
                    placeholder="/absolute/path/to/folder"
                    value={workingDir}
                    onChange={(e) => setWorkingDir(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Leave empty to use the script&apos;s parent folder.
                  </p>
                </div>
              </TabsContent>
            </Tabs>

            <div className="space-y-2">
              <Label htmlFor="name">Strategy Name</Label>
              <Input
                id="name"
                placeholder="My Trading Strategy"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={errors.name ? 'border-red-500' : ''}
              />
              {errors.name && <p className="text-sm text-red-500">{errors.name}</p>}
            </div>

            <div className="space-y-2 border-t pt-6">
              <Label htmlFor="exchange">Exchange</Label>
              <select
                id="exchange"
                value={exchange}
                onChange={(e) => handleExchangeChange(e.target.value)}
                className="w-full px-3 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-primary"
              >
                {exchanges.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">
                Exchange selection drives holiday and session-aware scheduling.
              </p>
            </div>

            <div className="space-y-4 border-t pt-6">
              <div className="flex items-center gap-2">
                <Clock className="h-5 w-5 text-muted-foreground" />
                <h3 className="font-medium">Schedule</h3>
              </div>
              <p className="text-sm text-muted-foreground">
                {isCrypto
                  ? 'CRYPTO runs 24/7. The schedule below limits when this script is allowed to run.'
                  : 'Configure when this strategy should run. All times are in IST.'}
              </p>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="startTime">Start Time (IST)</Label>
                  <Input
                    id="startTime"
                    type="time"
                    value={startTime}
                    onChange={(e) => setStartTime(e.target.value)}
                    className={errors.startTime ? 'border-red-500' : ''}
                  />
                  {errors.startTime && <p className="text-sm text-red-500">{errors.startTime}</p>}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="stopTime">Stop Time (IST)</Label>
                  <Input
                    id="stopTime"
                    type="time"
                    value={stopTime}
                    onChange={(e) => setStopTime(e.target.value)}
                    className={errors.stopTime ? 'border-red-500' : ''}
                  />
                  {errors.stopTime && <p className="text-sm text-red-500">{errors.stopTime}</p>}
                </div>
              </div>
              <div className="space-y-2">
                <Label>Schedule Days</Label>
                <div className="flex flex-wrap gap-2">
                  {SCHEDULE_DAYS.map((day) => (
                    <button
                      type="button"
                      key={day.value}
                      className={`flex items-center gap-2 px-3 py-2 border rounded-lg cursor-pointer transition-colors ${
                        selectedDays.includes(day.value)
                          ? 'bg-primary text-primary-foreground border-primary'
                          : 'hover:bg-muted'
                      }`}
                      onClick={() => handleDayToggle(day.value)}
                    >
                      <span className="text-sm">{day.label}</span>
                    </button>
                  ))}
                </div>
                {errors.days && <p className="text-sm text-red-500">{errors.days}</p>}
              </div>
            </div>

            <div className="flex gap-3 pt-4">
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                onClick={() => navigate('/python')}
              >
                Cancel
              </Button>
              <Button type="submit" className="flex-1" disabled={loading}>
                {loading
                  ? 'Saving...'
                  : mode === 'upload'
                    ? 'Upload Strategy'
                    : 'Add Strategy Path'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Collapsible open={showExample} onOpenChange={setShowExample}>
        <Card>
          <CardHeader>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" className="w-full justify-between p-0">
                <CardTitle className="text-lg flex items-center gap-2">
                  <FileCode className="h-5 w-5" />
                  Example Python Strategy Template
                </CardTitle>
                <span className="text-muted-foreground">{showExample ? 'Hide' : 'Show'}</span>
              </Button>
            </CollapsibleTrigger>
          </CardHeader>
          <CollapsibleContent>
            <CardContent>
              <pre className="p-4 bg-muted rounded-lg overflow-x-auto text-xs font-mono">
                {EXAMPLE_STRATEGY}
              </pre>
              <Button
                variant="outline"
                size="sm"
                className="mt-4"
                onClick={() => {
                  navigator.clipboard.writeText(EXAMPLE_STRATEGY)
                  showToast.success('Copied to clipboard', 'clipboard')
                }}
              >
                Copy Template
              </Button>
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>
    </div>
  )
}

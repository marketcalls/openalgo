import { ArrowLeft, Clock, FileCode, Info, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { pythonStrategyApi } from '@/api/python-strategy'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SCHEDULE_DAYS } from '@/types/python-strategy'

const EXAMPLE_STRATEGY = `"""
Example OpenAlgo Strategy
This is a minimal example showing how to use the OpenAlgo Python SDK.
"""

import os
import time
from openalgo import api

# Get API key from environment variable
API_KEY = os.getenv('OPENALGO_API_KEY')

# Initialize the API client
client = api(
    api_key=API_KEY,
    host_url="http://127.0.0.1:5000"
)

def main():
    """Main strategy logic"""
    print("Strategy started")

    # Example: Get account funds
    funds = client.funds()
    print(f"Available funds: {funds}")

    # Your trading logic here
    while True:
        # Check market conditions
        # Place orders based on your strategy
        # ...

        time.sleep(60)  # Check every minute

if __name__ == "__main__":
    main()
`

export default function NewPythonStrategy() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [showExample, setShowExample] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Schedule fields with defaults (Mon-Fri, 9:00 AM - 4:00 PM IST)
  const [startTime, setStartTime] = useState('09:00')
  const [stopTime, setStopTime] = useState('16:00')
  const [selectedDays, setSelectedDays] = useState<string[]>(['mon', 'tue', 'wed', 'thu', 'fri'])

  const handleDayToggle = (day: string) => {
    setSelectedDays((prev) =>
      prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day]
    )
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

    if (!file) {
      newErrors.file = 'Please select a Python file'
    } else if (!file.name.endsWith('.py')) {
      newErrors.file = 'File must be a Python file (.py)'
    }

    // Schedule validation
    if (!startTime) {
      newErrors.startTime = 'Start time is required'
    }
    if (!stopTime) {
      newErrors.stopTime = 'Stop time is required'
    }
    if (selectedDays.length === 0) {
      newErrors.days = 'Select at least one day'
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      // Validate file extension
      if (!selectedFile.name.endsWith('.py')) {
        showToast.error('Please select a Python file (.py)', 'pythonStrategy')
        return
      }
      // Validate file size (max 1MB for Python scripts)
      const maxSizeBytes = 1024 * 1024 // 1MB
      if (selectedFile.size > maxSizeBytes) {
        showToast.error('File size must be less than 1MB', 'pythonStrategy')
        return
      }
      setFile(selectedFile)
      // Auto-fill name from file name if empty
      if (!name) {
        const baseName = selectedFile.name.replace('.py', '').replace(/_/g, ' ')
        setName(baseName.charAt(0).toUpperCase() + baseName.slice(1))
      }
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
      // Upload strategy with schedule (schedule is mandatory)
      const response = await pythonStrategyApi.uploadStrategy(name, file!, {
        start_time: startTime,
        stop_time: stopTime,
        days: selectedDays,
      })

      if (response.status === 'success') {
        showToast.success('Strategy uploaded with schedule', 'pythonStrategy')
        navigate('/python')
      } else {
        showToast.error(response.message || 'Failed to upload strategy', 'pythonStrategy')
      }
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to upload strategy'
      showToast.error(errorMessage, 'pythonStrategy')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="container mx-auto py-6 max-w-2xl space-y-6">
      {/* Back Button */}
      <Button variant="ghost" asChild>
        <Link to="/python">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Python Strategies
        </Link>
      </Button>

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Add Python Strategy</h1>
        <p className="text-muted-foreground">
          Upload a Python script to run as an automated trading strategy
        </p>
      </div>

      {/* Requirements Info */}
      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription>
          Your Python script should use the <code className="bg-muted px-1 rounded">openalgo</code>{' '}
          SDK. Install it with: <code className="bg-muted px-1 rounded">pip install openalgo</code>
        </AlertDescription>
      </Alert>

      {/* Form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5" />
            Upload Strategy
          </CardTitle>
          <CardDescription>Select your Python script file and give it a name</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Strategy Name */}
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
              <p className="text-xs text-muted-foreground">A descriptive name for your strategy</p>
            </div>

            {/* File Upload */}
            <div className="space-y-2">
              <Label htmlFor="file">Python Script</Label>
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
                  accept=".py"
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
                      Click to select a Python file (.py)
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">Maximum file size: 1MB</p>
                  </div>
                )}
              </div>
              {errors.file && <p className="text-sm text-red-500">{errors.file}</p>}
            </div>

            {/* Schedule Section */}
            <div className="space-y-4 border-t pt-6">
              <div className="flex items-center gap-2">
                <Clock className="h-5 w-5 text-muted-foreground" />
                <h3 className="font-medium">Schedule</h3>
              </div>
              <p className="text-sm text-muted-foreground">
                Configure when this strategy should run. All times are in IST.
              </p>

              {/* Time Inputs */}
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

              {/* Day Selection */}
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
                      <div className={`h-4 w-4 rounded border flex items-center justify-center ${
                        selectedDays.includes(day.value)
                          ? 'bg-primary-foreground border-primary-foreground'
                          : 'border-current'
                      }`}>
                        {selectedDays.includes(day.value) && (
                          <svg className="h-3 w-3 text-primary" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        )}
                      </div>
                      <span className="text-sm">{day.label}</span>
                    </button>
                  ))}
                </div>
                {errors.days && <p className="text-sm text-red-500">{errors.days}</p>}
                <p className="text-xs text-muted-foreground">
                  Select the days when this strategy should run. Weekends can be enabled for special trading sessions.
                </p>
              </div>
            </div>

            {/* Submit */}
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
                {loading ? 'Uploading...' : 'Upload Strategy'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Example Strategy */}
      <Collapsible open={showExample} onOpenChange={setShowExample}>
        <Card>
          <CardHeader>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" className="w-full justify-between p-0">
                <CardTitle className="text-lg flex items-center gap-2">
                  <FileCode className="h-5 w-5" />
                  Example Strategy Template
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

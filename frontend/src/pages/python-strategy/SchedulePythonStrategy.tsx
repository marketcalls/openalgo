import { ArrowLeft, Calendar, Clock } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { pythonStrategyApi } from '@/api/python-strategy'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import type { PythonStrategy } from '@/types/python-strategy'
import { SCHEDULE_DAYS } from '@/types/python-strategy'

export default function SchedulePythonStrategy() {
  const { strategyId } = useParams<{ strategyId: string }>()
  const navigate = useNavigate()
  const [strategy, setStrategy] = useState<PythonStrategy | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [startTime, setStartTime] = useState('09:15')
  const [stopTime, setStopTime] = useState('15:30')
  const [selectedDays, setSelectedDays] = useState<string[]>(['mon', 'tue', 'wed', 'thu', 'fri'])

  useEffect(() => {
    const fetchStrategy = async () => {
      if (!strategyId) return
      try {
        setLoading(true)
        const data = await pythonStrategyApi.getStrategy(strategyId)
        setStrategy(data)
        // Pre-fill with existing schedule (schedule is always enabled)
        if (data.schedule_start_time) setStartTime(data.schedule_start_time)
        if (data.schedule_stop_time) setStopTime(data.schedule_stop_time)
        if (data.schedule_days?.length) setSelectedDays(data.schedule_days)
      } catch (error) {
        console.error('Failed to fetch strategy:', error)
        toast.error('Failed to load strategy')
        navigate('/python')
      } finally {
        setLoading(false)
      }
    }
    fetchStrategy()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategyId])

  const handleDayToggle = (day: string) => {
    setSelectedDays((prev) =>
      prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day]
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!strategyId) return
    if (selectedDays.length === 0) {
      toast.error('Please select at least one day')
      return
    }
    if (!startTime) {
      toast.error('Start time is required')
      return
    }
    if (!stopTime) {
      toast.error('Stop time is required')
      return
    }

    try {
      setSaving(true)
      const response = await pythonStrategyApi.scheduleStrategy(strategyId, {
        start_time: startTime,
        stop_time: stopTime,
        days: selectedDays,
      })

      if (response.status === 'success') {
        toast.success('Schedule saved successfully')
        navigate('/python')
      } else {
        toast.error(response.message || 'Failed to save schedule')
      }
    } catch (error) {
      console.error('Failed to schedule:', error)
      toast.error('Failed to save schedule')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="container mx-auto py-6 max-w-2xl space-y-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-12" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  if (!strategy) {
    return null
  }

  if (strategy.status === 'running') {
    return (
      <div className="container mx-auto py-6 max-w-2xl space-y-6">
        <Button variant="ghost" asChild>
          <Link to="/python">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Python Strategies
          </Link>
        </Button>
        <Card>
          <CardContent className="pt-6">
            <p className="text-muted-foreground">
              Cannot modify schedule while strategy is running. Please stop the strategy first.
            </p>
          </CardContent>
        </Card>
      </div>
    )
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
        <h1 className="text-2xl font-bold tracking-tight">Edit Schedule</h1>
        <p className="text-muted-foreground">{strategy.name}</p>
      </div>

      {/* Form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Calendar className="h-5 w-5" />
            Schedule Settings
          </CardTitle>
          <CardDescription>
            Set when the strategy should automatically start and stop (IST)
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Time Inputs */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="start_time" className="flex items-center gap-2">
                  <Clock className="h-4 w-4" />
                  Start Time (IST)
                </Label>
                <Input
                  id="start_time"
                  type="time"
                  value={startTime}
                  onChange={(e) => setStartTime(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="stop_time" className="flex items-center gap-2">
                  <Clock className="h-4 w-4" />
                  Stop Time (IST)
                </Label>
                <Input
                  id="stop_time"
                  type="time"
                  value={stopTime}
                  onChange={(e) => setStopTime(e.target.value)}
                  required
                />
              </div>
            </div>

            {/* Days Selection */}
            <div className="space-y-3">
              <Label>Days to Run</Label>
              <div className="flex flex-wrap gap-2">
                {SCHEDULE_DAYS.map((day) => (
                  <div
                    key={day.value}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-colors ${
                      selectedDays.includes(day.value)
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'bg-background hover:bg-muted'
                    }`}
                    onClick={() => handleDayToggle(day.value)}
                  >
                    <Checkbox
                      checked={selectedDays.includes(day.value)}
                      onCheckedChange={() => handleDayToggle(day.value)}
                      className="pointer-events-none"
                    />
                    <span className="text-sm font-medium">{day.label}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Quick Select */}
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setSelectedDays(['mon', 'tue', 'wed', 'thu', 'fri'])}
              >
                Weekdays
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setSelectedDays(['sat', 'sun'])}
              >
                Weekend
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setSelectedDays(['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'])}
              >
                Every Day
              </Button>
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
              <Button type="submit" className="flex-1" disabled={saving}>
                {saving ? 'Saving...' : 'Save Schedule'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

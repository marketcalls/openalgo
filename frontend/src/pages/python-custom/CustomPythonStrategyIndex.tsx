import { ArrowRight, FileCode, FileCode2, FileText, Play, Plus, RefreshCw, Square } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { pythonStrategyApi } from '@/api/python-strategy'
import { pythonStrategyCustomApi } from '@/api/python-strategy-custom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { PythonStrategy } from '@/types/python-strategy'
import { STATUS_LABELS } from '@/types/python-strategy'
import { showToast } from '@/utils/toast'

export default function CustomPythonStrategyIndex() {
  const navigate = useNavigate()
  const [strategies, setStrategies] = useState<PythonStrategy[]>([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const fetchStrategies = async (silent = false) => {
    try {
      if (!silent) setLoading(true)
      const data = await pythonStrategyApi.getStrategies()
      setStrategies(data)
    } catch {
      if (!silent) showToast.error('Failed to load strategies', 'pythonStrategy')
    } finally {
      if (!silent) setLoading(false)
    }
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: fetch once on mount for this page
  useEffect(() => {
    fetchStrategies()
  }, [])

  const handleStart = async (strategy: PythonStrategy) => {
    try {
      setActionLoading(strategy.id)
      const response = await pythonStrategyApi.startStrategy(strategy.id)
      if (response.status === 'success') {
        showToast.success(response.message || `Strategy ${strategy.name} started`, 'pythonStrategy')
      } else {
        showToast.error(response.message || 'Failed to start strategy', 'pythonStrategy')
      }
      await fetchStrategies(true)
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { message?: string } } }
      showToast.error(
        axiosError.response?.data?.message || 'Failed to start strategy',
        'pythonStrategy'
      )
    } finally {
      setActionLoading(null)
    }
  }

  const handleForceStart = async (strategy: PythonStrategy) => {
    try {
      setActionLoading(`force-${strategy.id}`)
      const response = await pythonStrategyCustomApi.forceStartStrategy(strategy.id)
      if (response.status === 'success') {
        showToast.success(`Force started ${strategy.name}`, 'pythonStrategy')
      } else {
        showToast.error(response.message || 'Failed to force start strategy', 'pythonStrategy')
      }
      await fetchStrategies(true)
    } catch {
      showToast.error('Failed to force start strategy', 'pythonStrategy')
    } finally {
      setActionLoading(null)
    }
  }

  const handleStop = async (strategy: PythonStrategy) => {
    try {
      setActionLoading(`stop-${strategy.id}`)
      const response = await pythonStrategyApi.stopStrategy(strategy.id)
      if (response.status === 'success') {
        showToast.success(response.message || `Strategy ${strategy.name} stopped`, 'pythonStrategy')
      } else {
        showToast.error(response.message || 'Failed to stop strategy', 'pythonStrategy')
      }
      await fetchStrategies(true)
    } catch {
      showToast.error('Failed to stop strategy', 'pythonStrategy')
    } finally {
      setActionLoading(null)
    }
  }

  return (
    <div className="container mx-auto py-6 max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Python Strategies Custom</h1>
        <p className="text-muted-foreground">
          Additive custom module that keeps your custom entry points isolated for easier upstream
          merges.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Plus className="h-5 w-5" />
              Add Strategy
            </CardTitle>
            <CardDescription>
              Upload a script or register a folder path (.py, .sh, .bat, .cmd).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild>
              <Link to="/python-custom/new">
                Open custom add screen
                <ArrowRight className="h-4 w-4 ml-2" />
              </Link>
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileCode2 className="h-5 w-5" />
              Full Strategy Console
            </CardTitle>
            <CardDescription>
              Open the existing strategy dashboard for run, stop, logs, edit, and schedule
              operations.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" asChild>
              <Link to="/python">
                Open full python strategies
                <ArrowRight className="h-4 w-4 ml-2" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>Custom Strategy Control</CardTitle>
            <CardDescription>
              Start, force start, and stop strategies directly from this custom module.
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => fetchStrategies()}>
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading strategies...</p>
          ) : strategies.length === 0 ? (
            <p className="text-sm text-muted-foreground">No strategies found.</p>
          ) : (
            strategies.map((strategy) => (
              <div
                key={strategy.id}
                className="border rounded-lg p-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <p className="font-medium truncate">{strategy.name}</p>
                  <p className="text-xs text-muted-foreground truncate">{strategy.file_name}</p>
                  <div className="mt-1 flex gap-2 items-center">
                    <Badge variant="outline">
                      {STATUS_LABELS[strategy.status] || strategy.status}
                    </Badge>
                    {strategy.is_scheduled && <Badge variant="secondary">Scheduled</Badge>}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {strategy.status !== 'running' && (
                    <>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={actionLoading === strategy.id}
                        onClick={() => handleStart(strategy)}
                      >
                        <Play className="h-4 w-4 mr-1" />
                        Start
                      </Button>
                      <Button
                        size="sm"
                        disabled={actionLoading === `force-${strategy.id}`}
                        onClick={() => handleForceStart(strategy)}
                      >
                        Force Start
                      </Button>
                    </>
                  )}
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={actionLoading === `stop-${strategy.id}`}
                    onClick={() => handleStop(strategy)}
                  >
                    <Square className="h-4 w-4 mr-1" />
                    Stop
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => navigate(`/python/${strategy.id}/logs`)}
                  >
                    <FileText className="h-4 w-4 mr-1" />
                    Logs
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => navigate(`/python/${strategy.id}/edit`)}
                  >
                    <FileCode className="h-4 w-4 mr-1" />
                    Source
                  </Button>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  )
}

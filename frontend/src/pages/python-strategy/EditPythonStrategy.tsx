import {
  AlertTriangle,
  ArrowLeft,
  Download,
  FileCode,
  Maximize2,
  Minimize2,
  RotateCcw,
  Save,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { pythonStrategyApi } from '@/api/python-strategy'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { PythonEditor } from '@/components/ui/python-editor'
import { Skeleton } from '@/components/ui/skeleton'
import type { PythonStrategy, PythonStrategyContent } from '@/types/python-strategy'

export default function EditPythonStrategy() {
  const { strategyId } = useParams<{ strategyId: string }>()
  const navigate = useNavigate()
  const [strategy, setStrategy] = useState<PythonStrategy | null>(null)
  const [content, setContent] = useState<PythonStrategyContent | null>(null)
  const [code, setCode] = useState('')
  const [originalCode, setOriginalCode] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)

  const hasChanges = code !== originalCode
  const isRunning = strategy?.status === 'running'

  // Ref to always have access to the latest code value in event handlers
  const codeRef = useRef(code)
  useEffect(() => {
    codeRef.current = code
  }, [code])

  const fetchData = async () => {
    if (!strategyId) return
    try {
      setLoading(true)
      const [strategyData, contentData] = await Promise.all([
        pythonStrategyApi.getStrategy(strategyId),
        pythonStrategyApi.getStrategyContent(strategyId),
      ])
      setStrategy(strategyData)
      setContent(contentData)
      setCode(contentData.content || '')
      setOriginalCode(contentData.content || '')
    } catch (error) {
      showToast.error('Failed to load strategy', 'pythonStrategy')
      navigate('/python')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSave = useCallback(async () => {
    // Use ref to get the latest code value (important for keyboard shortcuts)
    const currentCode = codeRef.current
    const currentHasChanges = currentCode !== originalCode

    if (!strategyId || !currentHasChanges || isRunning) return

    try {
      setSaving(true)
      const response = await pythonStrategyApi.saveStrategy(strategyId, currentCode)

      if (response.status === 'success') {
        setOriginalCode(currentCode)
        showToast.success('Strategy saved', 'pythonStrategy')
      } else {
        showToast.error(response.message || 'Failed to save strategy', 'pythonStrategy')
      }
    } catch (error) {
      showToast.error('Failed to save strategy', 'pythonStrategy')
    } finally {
      setSaving(false)
    }
  }, [strategyId, originalCode, isRunning])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        // handleSave uses codeRef internally to get the latest code
        handleSave()
      }
      if (e.key === 'F11') {
        e.preventDefault()
        setIsFullscreen((prev) => !prev)
      }
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleSave, isFullscreen])

  const handleReset = () => {
    setCode(originalCode)
    showToast.info('Changes discarded', 'pythonStrategy')
  }

  const handleExport = async (version: 'saved' | 'current') => {
    if (!strategyId || !strategy) return

    try {
      const blob = await pythonStrategyApi.exportStrategy(strategyId, version)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = strategy.file_name || `${strategy.name}.py`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      showToast.success('Strategy exported', 'pythonStrategy')
    } catch (error) {
      showToast.error('Failed to export strategy', 'pythonStrategy')
    }
  }

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-12" />
        <Skeleton className="h-[600px]" />
      </div>
    )
  }

  if (!strategy || !content) {
    return null
  }

  const editorContent = (
    <div className={`relative ${isFullscreen ? 'fixed inset-0 z-50 bg-background p-4' : ''}`}>
      {isFullscreen && (
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">{strategy.name}</h2>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setIsFullscreen(false)}>
              <Minimize2 className="h-4 w-4" />
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!hasChanges || saving || isRunning}
              className={hasChanges && !isRunning ? 'animate-pulse' : ''}
            >
              <Save className="h-4 w-4 mr-2" />
              {saving ? 'Saving...' : 'Save'}
            </Button>
          </div>
        </div>
      )}

      <div className={`rounded-lg border overflow-hidden ${isRunning ? 'opacity-75' : ''}`}>
        <PythonEditor
          value={code}
          onChange={isRunning ? undefined : setCode}
          readOnly={isRunning}
          height={isFullscreen ? 'calc(100vh - 140px)' : '600px'}
          placeholder="# Your Python strategy code here..."
        />
      </div>

      {/* Line count footer */}
      <div className="flex items-center justify-between mt-2 text-xs text-muted-foreground">
        <span>
          Lines: {code.split('\n').length} • Size: {(new Blob([code]).size / 1024).toFixed(2)} KB
        </span>
        <span>
          {hasChanges ? (
            <Badge variant="outline" className="text-yellow-500 border-yellow-500">
              Unsaved Changes
            </Badge>
          ) : (
            <Badge variant="outline" className="text-green-500 border-green-500">
              Saved
            </Badge>
          )}
        </span>
      </div>
    </div>
  )

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Back Button */}
      <Button variant="ghost" asChild>
        <Link to="/python">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Python Strategies
        </Link>
      </Button>

      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-3">
            {isRunning ? 'View' : 'Edit'} Strategy
            {isRunning && <Badge className="bg-green-500">Running</Badge>}
          </h1>
          <p className="text-muted-foreground flex items-center gap-2">
            <FileCode className="h-4 w-4" />
            {strategy.name} • {content.file_name}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setIsFullscreen(true)}>
            <Maximize2 className="h-4 w-4" />
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <Download className="h-4 w-4 mr-2" />
                Export
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onClick={() => handleExport('saved')}>
                Saved Version
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => handleExport('current')}>
                Current Content
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button variant="outline" size="sm" onClick={handleReset} disabled={!hasChanges}>
            <RotateCcw className="h-4 w-4 mr-2" />
            Reset
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={!hasChanges || saving || isRunning}
            className={hasChanges && !isRunning ? 'animate-pulse' : ''}
          >
            <Save className="h-4 w-4 mr-2" />
            {saving ? 'Saving...' : 'Save'}
          </Button>
        </div>
      </div>

      {/* Running Warning */}
      {isRunning && (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            This strategy is currently running. The editor is in read-only mode. Stop the strategy
            to make changes.
          </AlertDescription>
        </Alert>
      )}

      {/* File Info */}
      <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
        <span>File: {content.file_name}</span>
        {content.line_count && (
          <>
            <span>•</span>
            <span>{content.line_count} lines</span>
          </>
        )}
        {content.size_kb != null && (
          <>
            <span>•</span>
            <span>{content.size_kb.toFixed(2)} KB</span>
          </>
        )}
        {content.last_modified && (
          <>
            <span>•</span>
            <span>Last modified: {new Date(content.last_modified).toLocaleString()}</span>
          </>
        )}
      </div>

      {/* Editor */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            <span>Code Editor</span>
            <span className="font-normal text-xs text-muted-foreground">
              Ctrl+S to save • F11 for fullscreen • Tab to indent
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>{editorContent}</CardContent>
      </Card>

      {/* Keyboard Shortcuts */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Keyboard Shortcuts</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <kbd className="px-2 py-1 bg-muted rounded">Ctrl+S</kbd> Save
            </div>
            <div>
              <kbd className="px-2 py-1 bg-muted rounded">Tab</kbd> Indent
            </div>
            <div>
              <kbd className="px-2 py-1 bg-muted rounded">Shift+Tab</kbd> Unindent
            </div>
            <div>
              <kbd className="px-2 py-1 bg-muted rounded">F11</kbd> Fullscreen
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

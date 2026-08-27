// pages/flow/FlowEditor.tsx
// Flow visual workflow editor page

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Background,
  Controls,
  type Edge,
  MiniMap,
  type Node,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { showToast } from '@/utils/toast'
import '@xyflow/react/dist/style.css'
import {
  ArrowLeft,
  BarChart3,
  BookOpen,
  Download,
  FileJson,
  Home,
  Keyboard,
  Loader2,
  LogOut,
  Moon,
  MoreVertical,
  Pause,
  Play,
  Save,
  Sun,
  Terminal,
  Zap,
} from 'lucide-react'
import { authApi } from '@/api/auth'
import {
  activateWorkflow,
  deactivateWorkflow,
  executeWorkflow,
  exportWorkflow,
  flowQueryKeys,
  getWorkflow,
  replaceWorkflow,
  updateWorkflow,
} from '@/api/flow'
import { LogoutConfirmDialog } from '@/components/auth/LogoutConfirmDialog'
import { edgeTypes } from '@/components/flow/edges'
// Import Flow components
import { nodeTypes } from '@/components/flow/nodes'
import {
  ConfigPanel,
  ExecutionLogPanel,
  type LogEntry,
  NodePalette,
} from '@/components/flow/panels'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useProfileMenuItems } from '@/hooks/useProfileMenuItems'
import { DEFAULT_NODE_DATA } from '@/lib/flow/constants'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useFlowWorkflowStore } from '@/stores/flowWorkflowStore'
import { useThemeStore } from '@/stores/themeStore'

let nodeId = 0

/**
 * Fill in the output-variable name the config panel displays for a node that
 * was saved without one.
 *
 * The panel renders the name as its input's fallback, so the box looks filled
 * while the stored value is an empty string - the executor then stores nothing
 * and every downstream {{name.path}} resolves to its own literal text. New
 * nodes now carry the name in DEFAULT_NODE_DATA; this repairs the ones already
 * saved, so what the panel shows is what the next save will persist.
 */
function withDefaultOutputVariables(nodes: Node[]): { nodes: Node[]; repaired: boolean } {
  let repaired = false
  const next = nodes.map((node) => {
    const defaults = DEFAULT_NODE_DATA[node.type as keyof typeof DEFAULT_NODE_DATA] as
      | { outputVariable?: string }
      | undefined
    const fallback = defaults?.outputVariable
    const current = (node.data as { outputVariable?: string } | undefined)?.outputVariable
    if (!fallback || (typeof current === 'string' && current.trim())) {
      return node
    }
    repaired = true
    return { ...node, data: { ...node.data, outputVariable: fallback } }
  })
  return { nodes: next, repaired }
}
const getNodeId = () => `node_${nodeId++}`

function FlowEditorContent() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const reactFlowWrapper = useRef<HTMLDivElement>(null)
  const { screenToFlowPosition } = useReactFlow()

  const {
    name,
    nodes,
    edges,
    selectedNodeId,
    selectedEdgeId,
    isModified,
    setWorkflow,
    setName,
    onNodesChange,
    onEdgesChange,
    onConnect,
    addNode,
    selectNode,
    selectEdge,
    deleteSelected,
    markSaved,
    resetWorkflow,
  } = useFlowWorkflowStore()

  const [isActive, setIsActive] = useState(false)
  const [showLogoutDialog, setShowLogoutDialog] = useState(false)
  const [showLogPanel, setShowLogPanel] = useState(false)
  const [executionLogs, setExecutionLogs] = useState<LogEntry[]>([])
  const [executionStatus, setExecutionStatus] = useState<'idle' | 'running' | 'success' | 'error'>(
    'idle'
  )

  // Theme and auth stores
  const { mode, appMode, toggleMode, toggleAppMode, isTogglingMode } = useThemeStore()
  const { user, logout } = useAuthStore()
  // Filtered by broker capabilities (hides crypto-only Leverage on Indian brokers, issue #1480)
  const profileMenuItems = useProfileMenuItems()

  const handleLogout = async () => {
    try {
      await authApi.logout()
      logout()
      navigate('/login')
    } catch (_error) {
      showToast.error('Logout failed', 'system')
    }
  }

  const handleModeToggle = async () => {
    await toggleAppMode()
  }

  const {
    isLoading,
    isError,
    error: loadError,
    refetch,
    data: workflow,
  } = useQuery({
    queryKey: flowQueryKeys.workflow(Number(id)),
    queryFn: () => getWorkflow(Number(id)),
    enabled: !!id,
  })

  // Activate and Deactivate invalidate this query, and the refetch returns a new
  // object identity, which re-ran this effect and called setWorkflow - silently
  // replacing the canvas with the last saved graph and clearing isModified. Ten
  // minutes of unsaved edits vanished a moment after clicking Activate, with no
  // warning and no undo. Hydrate only when the loaded workflow is not the one
  // already open; keep is_active in its own effect so status still updates.
  const hydratedIdRef = useRef<number | null>(null)

  useEffect(() => {
    setIsActive(Boolean(workflow?.is_active))
  }, [workflow?.is_active])

  useEffect(() => {
    if (workflow && hydratedIdRef.current !== workflow.id) {
      hydratedIdRef.current = workflow.id
      // Ensure nodes and edges are arrays
      const workflowNodes = workflow.nodes || []
      const workflowEdges = workflow.edges || []

      // Convert all edges to insertable type
      const convertedEdges = workflowEdges.map((edge: Edge) => ({
        ...edge,
        type: 'insertable',
        animated: true,
      }))
      const { nodes: hydratedNodes, repaired } = withDefaultOutputVariables(workflowNodes as Node[])
      setWorkflow({
        id: workflow.id,
        name: workflow.name,
        description: workflow.description || '',
        nodes: hydratedNodes,
        edges: convertedEdges,
      })
      if (repaired) {
        // setWorkflow marks the canvas clean, so a repair made here would live
        // only in memory: Run Now saves nothing, the backend executes the
        // stored graph with the blank names, and the run fails on a variable
        // the panel shows as filled. Flagging it dirty is also honest -- the
        // canvas really does differ from what is stored.
        useFlowWorkflowStore.setState({ isModified: true })
      }
      // Set node ID counter
      const maxId = Math.max(
        0,
        ...workflowNodes.map((n) => {
          const match = n.id.match(/node_(\d+)/)
          return match ? parseInt(match[1], 10) : 0
        })
      )
      nodeId = maxId + 1
    }
  }, [workflow, setWorkflow])

  useEffect(() => {
    return () => {
      resetWorkflow()
    }
  }, [resetWorkflow])

  const saveMutation = useMutation({
    mutationFn: () => {
      // Captured with the payload, so onSuccess can tell whether the canvas
      // moved on while the request was in flight.
      const revision = useFlowWorkflowStore.getState().revision()
      const state = useFlowWorkflowStore.getState()
      return updateWorkflow(Number(id), {
        name: state.name,
        nodes: state.nodes,
        edges: state.edges,
      }).then((saved) => ({ ...saved, revision }))
    },
    onSuccess: (saved) => {
      markSaved(saved.revision)
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflows() })
      // The server re-arms a changed trigger during the save. It only reports
      // needs_reactivate when that failed, in which case it has stood the
      // workflow down rather than leave it running a stale registration.
      if (saved?.needs_reactivate) {
        showToast.warning(
          'Saved, but the new trigger could not be registered, so the workflow was deactivated. Activate it again once the trigger is valid.',
          'flow'
        )
      } else {
        showToast.success('Workflow saved', 'flow')
      }
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  // Run Now and Activate send only the workflow id, so the backend acts on the
  // last SAVED graph. With the buttons enabled while the canvas was dirty, a
  // user who changed a quantity and hit Run Now watched a successful run of the
  // previous graph and had no way to tell. Saving first makes the graph that
  // runs the graph on screen; awaiting it also closes the race where a pending
  // Ctrl+S PUT and the execute POST were in flight together.
  const saveIfDirty = useCallback(async () => {
    // Loops because an edit made during the PUT leaves the workflow dirty: the
    // save that just finished does not contain it, so executing now would run
    // the previous revision. Bounded, because a canvas being edited continuously
    // would otherwise never converge -- and failing loudly is far better than
    // silently trading a graph the user is no longer looking at.
    for (let attempt = 0; attempt < 3; attempt++) {
      if (!useFlowWorkflowStore.getState().isModified) {
        return
      }
      await saveMutation.mutateAsync()
    }
    if (useFlowWorkflowStore.getState().isModified) {
      throw new Error(
        'The canvas kept changing while it was being saved. Stop editing, save, then try again.'
      )
    }
  }, [saveMutation])

  const activateMutation = useMutation({
    mutationFn: async () => {
      await saveIfDirty()
      return activateWorkflow(Number(id))
    },
    onSuccess: () => {
      setIsActive(true)
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflow(Number(id)) })
      showToast.success('Workflow activated', 'flow')
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  const deactivateMutation = useMutation({
    mutationFn: async () => {
      await saveIfDirty()
      return deactivateWorkflow(Number(id))
    },
    onSuccess: () => {
      setIsActive(false)
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflow(Number(id)) })
      showToast.success('Workflow deactivated', 'flow')
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  const executeMutation = useMutation({
    mutationFn: async () => {
      await saveIfDirty()
      setExecutionStatus('running')
      setExecutionLogs([])
      setShowLogPanel(true)
      return executeWorkflow(Number(id))
    },
    onSuccess: (data) => {
      setExecutionStatus(data.status === 'success' ? 'success' : 'error')
      if (data.logs) {
        setExecutionLogs(data.logs as LogEntry[])
      }
      if (data.status === 'success') {
        showToast.success(data.message || 'Execution completed', 'flow')
      } else {
        showToast.error(data.message || 'Execution failed', 'flow')
      }
    },
    onError: (error: Error) => {
      setExecutionStatus('error')
      setExecutionLogs([{ time: new Date().toISOString(), message: error.message, level: 'error' }])
      showToast.error(error.message, 'flow')
    },
  })

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Don't trigger shortcuts when typing in inputs
      const target = event.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return
      }

      // Delete/Backspace - delete selected node or edge
      // selectedEdgeId was never consulted, and selectEdge clears selectedNodeId,
      // so after clicking an edge this guard was always false. With
      // deleteKeyCode={null} on the canvas there was no other way to remove one.
      if (event.key === 'Delete' || event.key === 'Backspace') {
        if (selectedNodeId || selectedEdgeId) {
          event.preventDefault()
          deleteSelected()
        }
      }

      // Ctrl/Cmd + S - Save
      if ((event.ctrlKey || event.metaKey) && event.key === 's') {
        event.preventDefault()
        if (isModified && !saveMutation.isPending) {
          saveMutation.mutate()
        }
      }

      // Escape - Deselect
      if (event.key === 'Escape') {
        selectNode(null)
        selectEdge(null)
      }

      // ? - Open keyboard shortcuts
      if (event.key === '?' || (event.shiftKey && event.key === '/')) {
        navigate('/flow/shortcuts')
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [
    selectedNodeId,
    selectedEdgeId,
    deleteSelected,
    selectNode,
    selectEdge,
    isModified,
    saveMutation,
    navigate,
  ])

  const handleDragStart = useCallback((event: React.DragEvent, nodeType: string) => {
    event.dataTransfer.setData('application/reactflow', nodeType)
    event.dataTransfer.effectAllowed = 'move'
  }, [])

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()

      const type = event.dataTransfer.getData('application/reactflow')
      if (!type || !reactFlowWrapper.current) return

      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      })

      // Get default data for the node type from constants
      const defaultData = DEFAULT_NODE_DATA[type as keyof typeof DEFAULT_NODE_DATA] || {}

      const newNode: Node = {
        id: getNodeId(),
        type,
        position,
        data: { ...defaultData },
      }

      addNode(newNode)
    },
    [screenToFlowPosition, addNode]
  )

  // Same placement logic as a drop, but at the middle of the visible canvas,
  // for adding a node without a pointer.
  const handleAddNode = useCallback(
    (type: string) => {
      const bounds = reactFlowWrapper.current?.getBoundingClientRect()
      const position = screenToFlowPosition({
        x: bounds ? bounds.x + bounds.width / 2 : window.innerWidth / 2,
        y: bounds ? bounds.y + bounds.height / 2 : window.innerHeight / 2,
      })
      const defaultData = DEFAULT_NODE_DATA[type as keyof typeof DEFAULT_NODE_DATA] || {}
      const newNode: Node = { id: getNodeId(), type, position, data: { ...defaultData } }
      addNode(newNode)
      selectNode(newNode.id)
    },
    [screenToFlowPosition, addNode, selectNode]
  )

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      selectNode(node.id)
    },
    [selectNode]
  )

  const handlePaneClick = useCallback(() => {
    selectNode(null)
  }, [selectNode])

  const handleEdgeClick = useCallback(
    (_: React.MouseEvent, edge: Edge) => {
      selectEdge(edge.id)
    },
    [selectEdge]
  )

  // Replace-from-JSON: the editor could export a workflow but had no way to
  // bring an edited file back into the same workflow. Importing created a copy
  // with a new webhook URL, so iterating on a strategy as JSON meant deleting
  // the old one every time.
  const [showReplaceDialog, setShowReplaceDialog] = useState(false)
  const [replaceJson, setReplaceJson] = useState('')
  const [replaceError, setReplaceError] = useState<string | null>(null)
  const [replaceBusy, setReplaceBusy] = useState(false)

  const handleReplaceFromJson = useCallback(async () => {
    setReplaceError(null)
    let parsed: unknown
    try {
      parsed = JSON.parse(replaceJson)
    } catch {
      setReplaceError('That is not valid JSON.')
      return
    }
    const graph = parsed as { nodes?: unknown; edges?: unknown }
    if (!graph || typeof graph !== 'object' || !Array.isArray(graph.nodes)) {
      setReplaceError('Workflow JSON needs a nodes array.')
      return
    }

    setReplaceBusy(true)
    try {
      const result = await replaceWorkflow(Number(id), parsed as never)
      // Reload the canvas from the database rather than trusting the payload,
      // so what is shown is what was actually stored.
      await queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflow(Number(id)) })
      setShowReplaceDialog(false)
      setReplaceJson('')
      const notes = result.migrations?.length
        ? ` ${result.migrations.length} legacy field(s) upgraded.`
        : ''
      if (result.needs_reactivate) {
        showToast.warning(
          `Workflow replaced.${notes} The trigger changed - deactivate and reactivate it.`,
          'flow'
        )
      } else {
        showToast.success(`Workflow replaced.${notes}`, 'flow')
      }
    } catch (error) {
      const detail =
        (error as { response?: { data?: { message?: string } } })?.response?.data?.message ??
        (error instanceof Error ? error.message : 'Replace failed')
      setReplaceError(detail)
    } finally {
      setReplaceBusy(false)
    }
  }, [id, replaceJson, queryClient])

  const handleExport = useCallback(async () => {
    try {
      const exportData = await exportWorkflow(Number(id))
      const blob = new Blob([JSON.stringify(exportData, null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${exportData.name.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      showToast.success('Workflow exported', 'flow')
    } catch (error) {
      showToast.error(error instanceof Error ? error.message : 'Export failed', 'flow')
    }
  }, [id])

  // Handle invalid ID - redirect to flow list
  if (!id || id === 'undefined' || Number.isNaN(Number(id))) {
    return (
      <div className="flex h-screen flex-col bg-background text-foreground">
        <div className="h-12 border-b border-border flex items-center px-2 bg-card/50">
          <div className="flex items-center gap-2 px-2">
            <img src="/images/android-chrome-192x192.png" alt="OpenAlgo" className="w-6 h-6" />
            <span className="font-semibold text-sm">openalgo</span>
          </div>
          <div className="flex-1" />
        </div>
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <p className="text-muted-foreground">Invalid workflow ID</p>
          <Button onClick={() => navigate('/flow')}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Workflows
          </Button>
        </div>
      </div>
    )
  }

  // A failed load left isLoading false and workflow undefined, so the editor
  // rendered a blank canvas indistinguishable from a new workflow. Dropping two
  // nodes on it and saving PUT those two nodes over the real graph, and reset
  // the name to the store default. Never render the canvas without its data.
  if (isError) {
    return (
      <div className="flex h-screen flex-col bg-background text-foreground">
        <div className="h-12 border-b border-border flex items-center px-2 bg-card/50">
          <div className="flex items-center gap-2 px-2">
            <img src="/images/android-chrome-192x192.png" alt="OpenAlgo" className="w-6 h-6" />
            <span className="font-semibold text-sm">openalgo</span>
          </div>
          <div className="flex-1" />
        </div>
        <div className="flex-1 flex items-center justify-center">
          <div className="max-w-md text-center space-y-4 px-6">
            <h2 className="text-lg font-semibold">Could not load this workflow</h2>
            <p className="text-sm text-muted-foreground">
              {loadError instanceof Error ? loadError.message : 'The workflow could not be loaded.'}
            </p>
            <p className="text-sm text-muted-foreground">
              Editing is disabled so the stored workflow is not overwritten.
            </p>
            <div className="flex items-center justify-center gap-2">
              <Button size="sm" onClick={() => refetch()}>
                Retry
              </Button>
              <Button variant="outline" size="sm" onClick={() => navigate('/flow')}>
                Back to workflows
              </Button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex h-screen flex-col bg-background text-foreground">
        {/* Top Header Bar */}
        <div className="h-12 border-b border-border flex items-center px-2 bg-card/50">
          <div className="flex items-center gap-2 px-2">
            <img src="/images/android-chrome-192x192.png" alt="OpenAlgo" className="w-6 h-6" />
            <span className="font-semibold text-sm">openalgo</span>
          </div>
          <div className="flex-1" />
        </div>
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      {/* Top Header Bar */}
      <div className="h-12 border-b border-border flex items-center px-2 bg-card/50">
        {/* Left: Logo */}
        <div className="flex items-center gap-2 px-2">
          <img src="/images/android-chrome-192x192.png" alt="OpenAlgo" className="w-6 h-6" />
          <span className="font-semibold text-sm">openalgo</span>
        </div>

        {/* Center: Workflow Name */}
        <div className="flex-1 flex items-center justify-center">
          <span className="text-sm font-medium text-muted-foreground">Flow Editor</span>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2 px-2">
          {/* Mode Badge */}
          <Badge
            variant={appMode === 'live' ? 'default' : 'secondary'}
            className={cn(
              'text-xs',
              appMode === 'analyzer' && 'bg-purple-500 hover:bg-purple-600 text-white'
            )}
          >
            <span className="hidden sm:inline">
              {appMode === 'live' ? 'Live Mode' : 'Analyze Mode'}
            </span>
            <span className="sm:hidden">{appMode === 'live' ? 'Live' : 'Analyze'}</span>
          </Badge>

          {/* Mode Toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={handleModeToggle}
            disabled={isTogglingMode}
            title={`Switch to ${appMode === 'live' ? 'Analyze' : 'Live'} mode`}
            aria-label={`Switch to ${appMode === 'live' ? 'Analyze' : 'Live'} mode`}
          >
            {isTogglingMode ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            ) : appMode === 'live' ? (
              <Zap className="h-4 w-4" />
            ) : (
              <BarChart3 className="h-4 w-4" />
            )}
          </Button>

          {/* Theme Toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={toggleMode}
            disabled={appMode !== 'live'}
            title={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
            aria-label={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
          >
            {mode === 'light' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>

          <Button variant="ghost" size="sm" className="h-7 text-xs" asChild>
            <Link to="/dashboard">
              <Home className="h-3.5 w-3.5 mr-1.5" />
              Dashboard
            </Link>
          </Button>

          {/* Profile Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-full bg-primary text-primary-foreground"
                aria-label="Open profile menu"
              >
                <span className="text-sm font-medium">
                  {user?.username?.[0]?.toUpperCase() || 'O'}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {profileMenuItems.map((item) => (
                <DropdownMenuItem
                  key={item.href}
                  onSelect={() => navigate(item.href)}
                  className="cursor-pointer"
                >
                  <item.icon className="h-4 w-4 mr-2" />
                  {item.label}
                </DropdownMenuItem>
              ))}
              <DropdownMenuItem asChild>
                <a
                  href="https://docs.openalgo.in"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2"
                >
                  <BookOpen className="h-4 w-4" />
                  Docs
                </a>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => setShowLogoutDialog(true)}
                className="text-destructive focus:text-destructive"
              >
                <LogOut className="h-4 w-4 mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <Dialog open={showReplaceDialog} onOpenChange={setShowReplaceDialog}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Replace from JSON</DialogTitle>
            <DialogDescription>
              Replaces this workflow's nodes and edges in place. The workflow id, webhook URL and
              active state are kept, so nothing pointing at this workflow breaks. Export first if
              you want a copy of the current version.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <input
              type="file"
              accept="application/json,.json"
              className="text-xs"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (!file) return
                file.text().then((text) => {
                  setReplaceJson(text)
                  setReplaceError(null)
                })
              }}
            />
            <Textarea
              className="h-64 font-mono text-xs"
              placeholder='{ "name": "...", "nodes": [...], "edges": [...] }'
              value={replaceJson}
              onChange={(e) => {
                setReplaceJson(e.target.value)
                setReplaceError(null)
              }}
            />
            {replaceError && <p className="text-xs text-destructive">{replaceError}</p>}
            <p className="text-[10px] text-muted-foreground">
              Validated the same way as Import: a graph that could not run is rejected with the
              reason, rather than saved to fail later.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowReplaceDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleReplaceFromJson} disabled={replaceBusy || !replaceJson.trim()}>
              {replaceBusy ? 'Replacing...' : 'Replace'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <LogoutConfirmDialog
        open={showLogoutDialog}
        onOpenChange={setShowLogoutDialog}
        onConfirm={handleLogout}
      />

      {/* Workflow Toolbar */}
      <div className="flex items-center justify-between border-b border-border bg-card px-4 py-2">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => navigate('/flow')}
            aria-label="Back to flows list"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="h-8 w-64 border-transparent bg-transparent px-2 font-medium hover:border-border focus:border-border"
          />
          {isModified && <span className="text-xs text-muted-foreground">Unsaved</span>}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !isModified}
          >
            {saveMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            Save
          </Button>
          {isActive ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => deactivateMutation.mutate()}
              disabled={deactivateMutation.isPending || saveMutation.isPending}
            >
              {deactivateMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Pause className="mr-2 h-4 w-4" />
              )}
              Deactivate
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={() => activateMutation.mutate()}
              disabled={activateMutation.isPending || saveMutation.isPending}
            >
              {activateMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Play className="mr-2 h-4 w-4" />
              )}
              Activate
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Workflow actions">
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={() => executeMutation.mutate()}
                disabled={executeMutation.isPending || saveMutation.isPending}
              >
                Run Now
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setShowLogPanel(!showLogPanel)}>
                <Terminal className="mr-2 h-4 w-4" />
                {showLogPanel ? 'Hide Logs' : 'Show Logs'}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={handleExport}>
                <Download className="mr-2 h-4 w-4" />
                Export Workflow
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setShowReplaceDialog(true)}>
                <FileJson className="mr-2 h-4 w-4" />
                Replace from JSON
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link to="/flow/shortcuts">
                  <Keyboard className="mr-2 h-4 w-4" />
                  Keyboard Shortcuts
                </Link>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Node Palette - Left Sidebar */}
        <div className="w-56 flex-shrink-0">
          <NodePalette onDragStart={handleDragStart} onAdd={handleAddNode} />
        </div>

        {/* Canvas */}
        <div ref={reactFlowWrapper} className="flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={handleNodeClick}
            onEdgeClick={handleEdgeClick}
            onPaneClick={handlePaneClick}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ maxZoom: 1 }}
            snapToGrid
            snapGrid={[16, 16]}
            deleteKeyCode={null}
            defaultEdgeOptions={{
              type: 'insertable',
              animated: true,
            }}
            connectionLineStyle={{ stroke: 'hsl(var(--primary))', strokeWidth: 2 }}
            connectionRadius={30}
            connectOnClick={true}
          >
            <Background gap={16} size={1} />
            <Controls />
            <MiniMap nodeStrokeWidth={3} pannable zoomable />
            <Panel position="bottom-center" className="mb-4">
              <div
                className={cn(
                  'flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm',
                  isActive && 'border-green-500/30 bg-green-500/5'
                )}
              >
                <div
                  className={cn(
                    'h-2 w-2 rounded-full',
                    isActive ? 'bg-green-500' : 'bg-muted-foreground'
                  )}
                />
                <span className="text-muted-foreground">
                  {isActive ? 'Workflow active' : 'Workflow inactive'}
                </span>
              </div>
            </Panel>
          </ReactFlow>
        </div>

        {/* Config Panel - Right Sidebar (when node selected) */}
        {selectedNodeId && <ConfigPanel />}

        {/* Execution Log Panel - Right Sidebar (when shown) */}
        {showLogPanel && !selectedNodeId && (
          <ExecutionLogPanel
            logs={executionLogs}
            status={executionStatus}
            onClose={() => setShowLogPanel(false)}
          />
        )}
      </div>
    </div>
  )
}

export default function FlowEditor() {
  return (
    <ReactFlowProvider>
      <FlowEditorContent />
    </ReactFlowProvider>
  )
}

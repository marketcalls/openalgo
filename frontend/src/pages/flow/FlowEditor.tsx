// pages/flow/FlowEditor.tsx
// Flow visual workflow editor page

import { useCallback, useRef, useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { showToast } from '@/utils/toast'
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  Panel,
  useReactFlow,
  type Node,
  type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  ArrowLeft,
  BarChart3,
  BookOpen,
  Download,
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
  getWorkflow,
  updateWorkflow,
  activateWorkflow,
  deactivateWorkflow,
  executeWorkflow,
  exportWorkflow,
  flowQueryKeys,
} from '@/api/flow'
import { useFlowWorkflowStore } from '@/stores/flowWorkflowStore'
import { DEFAULT_NODE_DATA } from '@/lib/flow/constants'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { profileMenuItems } from '@/config/navigation'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'

// Import Flow components
import { nodeTypes } from '@/components/flow/nodes'
import { edgeTypes } from '@/components/flow/edges'
import { NodePalette, ConfigPanel, ExecutionLogPanel, type LogEntry } from '@/components/flow/panels'

let nodeId = 0
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
  const [showLogPanel, setShowLogPanel] = useState(false)
  const [executionLogs, setExecutionLogs] = useState<LogEntry[]>([])
  const [executionStatus, setExecutionStatus] = useState<'idle' | 'running' | 'success' | 'error'>('idle')

  // Theme and auth stores
  const { mode, appMode, toggleMode, toggleAppMode, isTogglingMode } = useThemeStore()
  const { user, logout } = useAuthStore()

  const handleLogout = async () => {
    try {
      await authApi.logout()
      logout()
      navigate('/login')
    } catch (error) {
      showToast.error('Logout failed', 'system')
    }
  }

  const handleModeToggle = async () => {
    await toggleAppMode()
  }

  const { isLoading, data: workflow } = useQuery({
    queryKey: flowQueryKeys.workflow(Number(id)),
    queryFn: () => getWorkflow(Number(id)),
    enabled: !!id,
  })

  useEffect(() => {
    if (workflow) {
      // Ensure nodes and edges are arrays
      const workflowNodes = workflow.nodes || []
      const workflowEdges = workflow.edges || []

      // Convert all edges to insertable type
      const convertedEdges = workflowEdges.map((edge: Edge) => ({
        ...edge,
        type: 'insertable',
        animated: true,
      }))
      setWorkflow({
        id: workflow.id,
        name: workflow.name,
        description: workflow.description || '',
        nodes: workflowNodes as Node[],
        edges: convertedEdges,
      })
      setIsActive(workflow.is_active)
      // Set node ID counter
      const maxId = Math.max(
        0,
        ...workflowNodes.map((n) => {
          const match = n.id.match(/node_(\d+)/)
          return match ? parseInt(match[1]) : 0
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
    mutationFn: () =>
      updateWorkflow(Number(id), {
        name,
        nodes,
        edges,
      }),
    onSuccess: () => {
      markSaved()
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflows() })
      showToast.success('Workflow saved', 'flow')
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  const activateMutation = useMutation({
    mutationFn: () => activateWorkflow(Number(id)),
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
    mutationFn: () => deactivateWorkflow(Number(id)),
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
    mutationFn: () => {
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
      if (event.key === 'Delete' || event.key === 'Backspace') {
        if (selectedNodeId) {
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
      }

      // ? - Open keyboard shortcuts
      if (event.key === '?' || (event.shiftKey && event.key === '/')) {
        navigate('/flow/shortcuts')
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedNodeId, deleteSelected, selectNode, isModified, saveMutation, navigate])

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
  if (!id || id === 'undefined' || isNaN(Number(id))) {
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
                onClick={handleLogout}
                className="text-destructive focus:text-destructive"
              >
                <LogOut className="h-4 w-4 mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Workflow Toolbar */}
      <div className="flex items-center justify-between border-b border-border bg-card px-4 py-2">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => navigate('/flow')}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="h-8 w-64 border-transparent bg-transparent px-2 font-medium hover:border-border focus:border-border"
          />
          {isModified && (
            <span className="text-xs text-muted-foreground">Unsaved</span>
          )}
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
              disabled={deactivateMutation.isPending}
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
              disabled={activateMutation.isPending}
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
              <Button variant="ghost" size="icon">
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={() => executeMutation.mutate()}
                disabled={executeMutation.isPending}
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
          <NodePalette onDragStart={handleDragStart} />
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
            <MiniMap
              nodeStrokeWidth={3}
              pannable
              zoomable
            />
            <Panel position="bottom-center" className="mb-4">
              <div
                className={cn(
                  'flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm',
                  isActive && 'border-green-500/30 bg-green-500/5'
                )}
              >
                <div className={cn('h-2 w-2 rounded-full', isActive ? 'bg-green-500' : 'bg-muted-foreground')} />
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

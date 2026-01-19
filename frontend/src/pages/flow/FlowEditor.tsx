// pages/flow/FlowEditor.tsx
// Flow visual workflow editor page

import { useCallback, useRef, useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
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
  Save,
  Play,
  Pause,
  Loader2,
  MoreVertical,
  Terminal,
  Download,
} from 'lucide-react'
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
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

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

  const { isLoading, data: workflow } = useQuery({
    queryKey: flowQueryKeys.workflow(Number(id)),
    queryFn: () => getWorkflow(Number(id)),
    enabled: !!id,
  })

  useEffect(() => {
    if (workflow) {
      // Convert all edges to insertable type
      const convertedEdges = workflow.edges.map((edge: Edge) => ({
        ...edge,
        type: 'insertable',
        animated: true,
      }))
      setWorkflow({
        id: workflow.id,
        name: workflow.name,
        description: workflow.description || '',
        nodes: workflow.nodes as Node[],
        edges: convertedEdges,
      })
      setIsActive(workflow.is_active)
      // Set node ID counter
      const maxId = Math.max(
        0,
        ...workflow.nodes.map((n) => {
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
      toast.success('Workflow saved')
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const activateMutation = useMutation({
    mutationFn: () => activateWorkflow(Number(id)),
    onSuccess: () => {
      setIsActive(true)
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflow(Number(id)) })
      toast.success('Workflow activated')
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const deactivateMutation = useMutation({
    mutationFn: () => deactivateWorkflow(Number(id)),
    onSuccess: () => {
      setIsActive(false)
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflow(Number(id)) })
      toast.success('Workflow deactivated')
    },
    onError: (error: Error) => {
      toast.error(error.message)
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
        toast.success(data.message || 'Execution completed')
      } else {
        toast.error(data.message || 'Execution failed')
      }
    },
    onError: (error: Error) => {
      setExecutionStatus('error')
      setExecutionLogs([{ time: new Date().toISOString(), message: error.message, level: 'error' }])
      toast.error(error.message)
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
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedNodeId, deleteSelected, selectNode, isModified, saveMutation])

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
      toast.success('Workflow exported')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Export failed')
    }
  }, [id])

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col">
      {/* Toolbar */}
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

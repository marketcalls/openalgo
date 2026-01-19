// components/flow/panels/ConfigPanel.tsx
// Right sidebar for configuring selected nodes
// This is a shell version - full node configs will be added in Phase 6

import { X, Trash2, Settings2, Info } from 'lucide-react'
import { useFlowWorkflowStore } from '@/stores/flowWorkflowStore'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { NODE_DEFINITIONS } from '@/lib/flow/constants'

// Get node display info from definitions
function getNodeInfo(nodeType: string) {
  for (const category of Object.values(NODE_DEFINITIONS)) {
    const node = category.find(n => n.type === nodeType)
    if (node) return node
  }
  return null
}

export function ConfigPanel() {
  const { nodes, selectedNodeId, updateNodeData, deleteNode, selectNode } = useFlowWorkflowStore()

  const selectedNode = nodes.find((n) => n.id === selectedNodeId)

  if (!selectedNode) {
    return (
      <div className="w-72 border-l border-border bg-card flex flex-col h-full">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Settings2 className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium">Configure</span>
          </div>
        </div>
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="text-center text-muted-foreground">
            <Settings2 className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p className="text-sm">Select a node to configure</p>
            <p className="text-xs mt-1">Click on a node in the canvas</p>
          </div>
        </div>
      </div>
    )
  }

  const nodeInfo = getNodeInfo(selectedNode.type || '')
  const nodeData = selectedNode.data as Record<string, unknown>

  const handleClose = () => {
    selectNode(null)
  }

  const handleDelete = () => {
    deleteNode(selectedNode.id)
  }

  const handleLabelChange = (value: string) => {
    updateNodeData(selectedNode.id, { label: value })
  }

  return (
    <div className="w-72 border-l border-border bg-card flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Settings2 className="h-4 w-4" />
          <span className="font-medium text-sm truncate">
            {nodeInfo?.label || selectedNode.type}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-destructive hover:text-destructive"
            onClick={handleDelete}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={handleClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-4">
          {/* Node Type Info */}
          {nodeInfo && (
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <div className="flex items-start gap-2">
                <Info className="h-4 w-4 text-muted-foreground mt-0.5" />
                <div>
                  <p className="text-xs font-medium">{nodeInfo.label}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {nodeInfo.description}
                  </p>
                </div>
              </div>
            </div>
          )}

          <Separator />

          {/* Basic Configuration */}
          <div className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="node-label" className="text-xs">
                Node Label
              </Label>
              <Input
                id="node-label"
                placeholder="Enter label..."
                value={(nodeData.label as string) || ''}
                onChange={(e) => handleLabelChange(e.target.value)}
                className="h-8 text-sm"
              />
            </div>
          </div>

          <Separator />

          {/* Placeholder for node-specific configuration */}
          <div className="rounded-lg border border-dashed border-amber-500/50 bg-amber-500/5 p-4">
            <div className="flex items-start gap-2">
              <Info className="h-4 w-4 text-amber-500 mt-0.5" />
              <div>
                <p className="text-xs font-medium text-amber-500">
                  Configuration Pending
                </p>
                <p className="text-xs text-amber-500/80 mt-1">
                  Full configuration for <strong>{nodeInfo?.label || selectedNode.type}</strong> nodes
                  will be available after Phase 6 implementation.
                </p>
              </div>
            </div>
          </div>

          {/* Node ID (debug info) */}
          <div className="space-y-2">
            <Label className="text-xs text-muted-foreground">Node ID</Label>
            <code className="block text-xs bg-muted px-2 py-1 rounded font-mono">
              {selectedNode.id}
            </code>
          </div>

          {/* Current Data (debug info) */}
          <div className="space-y-2">
            <Label className="text-xs text-muted-foreground">Current Data</Label>
            <pre className="text-xs bg-muted px-2 py-2 rounded font-mono overflow-x-auto max-h-40">
              {JSON.stringify(nodeData, null, 2)}
            </pre>
          </div>
        </div>
      </ScrollArea>
    </div>
  )
}

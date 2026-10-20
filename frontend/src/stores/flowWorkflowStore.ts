// stores/flowWorkflowStore.ts
// Zustand store for Flow workflow editor state

import type { Edge, Node, OnConnect, OnEdgesChange, OnNodesChange } from '@xyflow/react'
import { addEdge, applyEdgeChanges, applyNodeChanges } from '@xyflow/react'
import { create } from 'zustand'

interface WorkflowState {
  // Workflow data
  id: number | null
  name: string
  description: string
  nodes: Node[]
  edges: Edge[]

  // Selection state
  selectedNodeId: string | null
  selectedEdgeId: string | null

  // Edit tracking
  isModified: boolean

  // Actions - Workflow
  setWorkflow: (workflow: {
    id: number | null
    name: string
    description: string
    nodes: Node[]
    edges: Edge[]
  }) => void
  setName: (name: string) => void
  setDescription: (description: string) => void
  resetWorkflow: () => void
  /**
   * A cheap identity for the current graph, captured when a save is issued and
   * handed back to markSaved when it resolves.
   */
  revision: () => string
  markSaved: (revision?: string) => void

  // Actions - Nodes
  setNodes: (nodes: Node[]) => void
  onNodesChange: OnNodesChange
  addNode: (node: Node) => void
  updateNodeData: (nodeId: string, data: Record<string, unknown>) => void
  deleteNode: (nodeId: string) => void

  // Actions - Edges
  setEdges: (edges: Edge[]) => void
  onEdgesChange: OnEdgesChange
  onConnect: OnConnect
  deleteEdge: (edgeId: string) => void

  // Actions - Selection
  selectNode: (nodeId: string | null) => void
  selectEdge: (edgeId: string | null) => void
  deleteSelected: () => void
}

const initialState = {
  id: null,
  name: 'Untitled Workflow',
  description: '',
  nodes: [],
  edges: [],
  selectedNodeId: null,
  selectedEdgeId: null,
  isModified: false,
}

/**
 * Whether a batch of ReactFlow changes represents an actual edit.
 *
 * ReactFlow emits `dimensions` changes when it first measures a node, and
 * `select` changes when one is merely clicked. Counting those as edits marked a
 * freshly opened or imported graph dirty before the user touched anything --
 * which matters now that Run Now and Activate save the canvas first, since it
 * turned a read-only glance into a write.
 */
function isRealEdit(changes: Array<{ type: string }>): boolean {
  return changes.some((change) => change.type !== 'dimensions' && change.type !== 'select')
}

export const useFlowWorkflowStore = create<WorkflowState>((set, get) => ({
  ...initialState,

  // =============================================================================
  // Workflow Actions
  // =============================================================================

  setWorkflow: (workflow) =>
    set({
      id: workflow.id,
      name: workflow.name,
      description: workflow.description,
      nodes: workflow.nodes,
      edges: workflow.edges,
      isModified: false,
      selectedNodeId: null,
      selectedEdgeId: null,
    }),

  setName: (name) => set({ name, isModified: true }),

  setDescription: (description) => set({ description, isModified: true }),

  resetWorkflow: () => set(initialState),

  revision: () => {
    const { name, nodes, edges } = get()
    return JSON.stringify([name, nodes, edges])
  },

  markSaved: (revision) => {
    // Only clear the dirty flag when the graph still matches what was actually
    // sent. The save PUTs the graph as it stood when it was issued; edits made
    // while that request is in flight are not in it, and clearing the flag
    // unconditionally left the canvas showing B, the server holding A, and the
    // editor insisting there was nothing unsaved -- so Run Now and Activate
    // then ran A.
    if (revision !== undefined && revision !== get().revision()) {
      return
    }
    set({ isModified: false })
  },

  // =============================================================================
  // Node Actions
  // =============================================================================

  setNodes: (nodes) => set({ nodes, isModified: true }),

  onNodesChange: (changes) => {
    set({
      nodes: applyNodeChanges(changes, get().nodes),
      isModified: get().isModified || isRealEdit(changes),
    })
  },

  addNode: (node) =>
    set((state) => ({
      nodes: [...state.nodes, node],
      isModified: true,
    })),

  updateNodeData: (nodeId, data) =>
    set((state) => ({
      nodes: state.nodes.map((node) =>
        node.id === nodeId ? { ...node, data: { ...node.data, ...data } } : node
      ),
      isModified: true,
    })),

  deleteNode: (nodeId) =>
    set((state) => ({
      nodes: state.nodes.filter((node) => node.id !== nodeId),
      edges: state.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId),
      selectedNodeId: state.selectedNodeId === nodeId ? null : state.selectedNodeId,
      isModified: true,
    })),

  // =============================================================================
  // Edge Actions
  // =============================================================================

  setEdges: (edges) => set({ edges, isModified: true }),

  onEdgesChange: (changes) => {
    set({
      edges: applyEdgeChanges(changes, get().edges),
      isModified: get().isModified || isRealEdit(changes),
    })
  },

  onConnect: (connection) => {
    set({
      edges: addEdge(
        {
          ...connection,
          id: `edge-${Date.now()}`,
          type: 'insertable',
          animated: true,
        },
        get().edges
      ),
      isModified: true,
    })
  },

  deleteEdge: (edgeId) =>
    set((state) => ({
      edges: state.edges.filter((edge) => edge.id !== edgeId),
      selectedEdgeId: state.selectedEdgeId === edgeId ? null : state.selectedEdgeId,
      isModified: true,
    })),

  // =============================================================================
  // Selection Actions
  // =============================================================================

  selectNode: (nodeId) => set({ selectedNodeId: nodeId, selectedEdgeId: null }),

  selectEdge: (edgeId) => set({ selectedEdgeId: edgeId, selectedNodeId: null }),

  deleteSelected: () =>
    set((state) => {
      const { selectedNodeId, selectedEdgeId, nodes, edges } = state

      if (selectedNodeId) {
        return {
          nodes: nodes.filter((node) => node.id !== selectedNodeId),
          edges: edges.filter(
            (edge) => edge.source !== selectedNodeId && edge.target !== selectedNodeId
          ),
          selectedNodeId: null,
          isModified: true,
        }
      }

      if (selectedEdgeId) {
        return {
          edges: edges.filter((edge) => edge.id !== selectedEdgeId),
          selectedEdgeId: null,
          isModified: true,
        }
      }

      return state
    }),
}))

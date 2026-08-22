import type { Node } from '@xyflow/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useFlowWorkflowStore } from './flowWorkflowStore'

/**
 * A save PUTs the graph as it stood when the request was issued. Edits made
 * while it is in flight are not in that payload, so clearing the dirty flag on
 * success left the canvas showing B, the server holding A, and the editor
 * insisting nothing was unsaved -- Run Now and Activate then executed A.
 */

const node = (id: string, quantity: number): Node => ({
  id,
  type: 'placeOrder',
  position: { x: 0, y: 0 },
  data: { symbol: 'SBIN', exchange: 'NSE', action: 'BUY', quantity },
})

describe('save race', () => {
  beforeEach(() => {
    useFlowWorkflowStore.getState().resetWorkflow()
  })

  it('stays dirty when the canvas changes while the save is in flight', () => {
    const store = useFlowWorkflowStore.getState()
    store.setWorkflow({ id: 1, name: 'wf', nodes: [node('n1', 1)], edges: [] })

    // The save is issued: this is the graph the server will receive.
    const revision = useFlowWorkflowStore.getState().revision()

    // The user edits while the request is still open.
    useFlowWorkflowStore.getState().updateNodeData('n1', { quantity: 500 })
    expect(useFlowWorkflowStore.getState().isModified).toBe(true)

    // The PUT resolves, carrying the revision it actually sent.
    useFlowWorkflowStore.getState().markSaved(revision)

    expect(useFlowWorkflowStore.getState().isModified).toBe(true)
    const saved = useFlowWorkflowStore.getState().nodes[0].data as { quantity: number }
    expect(saved.quantity).toBe(500)
  })

  it('clears the dirty flag when nothing changed while the save was in flight', () => {
    const store = useFlowWorkflowStore.getState()
    store.setWorkflow({ id: 1, name: 'wf', nodes: [node('n1', 1)], edges: [] })
    useFlowWorkflowStore.getState().updateNodeData('n1', { quantity: 5 })

    const revision = useFlowWorkflowStore.getState().revision()
    useFlowWorkflowStore.getState().markSaved(revision)

    expect(useFlowWorkflowStore.getState().isModified).toBe(false)
  })

  it('treats a rename during the save as an unsaved change', () => {
    const store = useFlowWorkflowStore.getState()
    store.setWorkflow({ id: 1, name: 'wf', nodes: [node('n1', 1)], edges: [] })

    const revision = useFlowWorkflowStore.getState().revision()
    useFlowWorkflowStore.getState().setName('renamed mid-flight')
    useFlowWorkflowStore.getState().markSaved(revision)

    expect(useFlowWorkflowStore.getState().isModified).toBe(true)
  })

  it('still supports an unconditional markSaved for callers with no revision', () => {
    const store = useFlowWorkflowStore.getState()
    store.setWorkflow({ id: 1, name: 'wf', nodes: [node('n1', 1)], edges: [] })
    useFlowWorkflowStore.getState().updateNodeData('n1', { quantity: 9 })

    useFlowWorkflowStore.getState().markSaved()

    expect(useFlowWorkflowStore.getState().isModified).toBe(false)
  })

  it('gives an unchanged graph a stable revision', () => {
    const store = useFlowWorkflowStore.getState()
    store.setWorkflow({ id: 1, name: 'wf', nodes: [node('n1', 1)], edges: [] })

    const before = useFlowWorkflowStore.getState().revision()
    expect(useFlowWorkflowStore.getState().revision()).toBe(before)

    useFlowWorkflowStore.getState().updateNodeData('n1', { quantity: 2 })
    expect(useFlowWorkflowStore.getState().revision()).not.toBe(before)
  })
})

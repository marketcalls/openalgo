// pages/flow/FlowIndex.tsx
// Flow workflow list page

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Copy,
  Eye,
  EyeOff,
  Loader2,
  MoreVertical,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
  Webhook,
  XCircle,
} from 'lucide-react'
import {
  listWorkflows,
  createWorkflow,
  deleteWorkflow,
  activateWorkflow,
  deactivateWorkflow,
  getWebhookInfo,
  enableWebhook,
  disableWebhook,
  regenerateWebhook,
  updateWebhookAuthType,
  importWorkflow,
  flowQueryKeys,
  type WorkflowListItem,
  type WorkflowExportData,
} from '@/api/flow'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'

function StatusIcon({ status }: { status: string | null }) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 className="h-4 w-4 text-green-500" />
    case 'failed':
      return <XCircle className="h-4 w-4 text-red-500" />
    case 'running':
      return <Loader2 className="h-4 w-4 animate-spin text-primary" />
    case 'pending':
      return <Clock className="h-4 w-4 text-muted-foreground" />
    default:
      return <AlertCircle className="h-4 w-4 text-muted-foreground" />
  }
}

function WorkflowCard({ workflow }: { workflow: WorkflowListItem }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [isWebhookOpen, setIsWebhookOpen] = useState(false)
  const [showSecret, setShowSecret] = useState(false)

  const activateMutation = useMutation({
    mutationFn: () => activateWorkflow(workflow.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflows() })
      showToast.success('Workflow activated', 'flow')
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  const deactivateMutation = useMutation({
    mutationFn: () => deactivateWorkflow(workflow.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflows() })
      showToast.success('Workflow deactivated', 'flow')
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteWorkflow(workflow.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflows() })
      showToast.success('Workflow deleted', 'flow')
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  // Webhook queries and mutations
  const webhookQuery = useQuery({
    queryKey: flowQueryKeys.webhook(workflow.id),
    queryFn: () => getWebhookInfo(workflow.id),
    enabled: isWebhookOpen,
  })

  const enableWebhookMutation = useMutation({
    mutationFn: () => enableWebhook(workflow.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.webhook(workflow.id) })
      showToast.success('Webhook enabled', 'flow')
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  const disableWebhookMutation = useMutation({
    mutationFn: () => disableWebhook(workflow.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.webhook(workflow.id) })
      showToast.success('Webhook disabled', 'flow')
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  const regenerateWebhookMutation = useMutation({
    mutationFn: () => regenerateWebhook(workflow.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.webhook(workflow.id) })
      showToast.success('Webhook URL and secret regenerated', 'flow')
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  const updateAuthTypeMutation = useMutation({
    mutationFn: (authType: 'payload' | 'url') => updateWebhookAuthType(workflow.id, authType),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.webhook(workflow.id) })
      showToast.success('Authentication type updated', 'flow')
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text)
    showToast.success(`${label} copied to clipboard`, 'clipboard')
  }

  return (
    <>
      <Card
        className={cn(
          'group cursor-pointer transition-all duration-200 hover:border-primary/50',
          workflow.is_active && 'border-green-500/30'
        )}
        onClick={() => navigate(`/flow/editor/${workflow.id}`)}
      >
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div
                className={cn(
                  'h-2 w-2 rounded-full',
                  workflow.is_active ? 'bg-green-500' : 'bg-muted-foreground'
                )}
              />
              <CardTitle className="text-base">{workflow.name}</CardTitle>
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                <Button variant="ghost" size="icon" className="h-8 w-8">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onClick={(e) => {
                    e.stopPropagation()
                    navigate(`/flow/editor/${workflow.id}`)
                  }}
                >
                  Edit
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={(e) => {
                    e.stopPropagation()
                    setIsWebhookOpen(true)
                  }}
                >
                  <Webhook className="mr-2 h-4 w-4" />
                  Webhook
                </DropdownMenuItem>
                {workflow.is_active ? (
                  <DropdownMenuItem
                    onClick={(e) => {
                      e.stopPropagation()
                      deactivateMutation.mutate()
                    }}
                  >
                    <Pause className="mr-2 h-4 w-4" />
                    Deactivate
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem
                    onClick={(e) => {
                      e.stopPropagation()
                      activateMutation.mutate()
                    }}
                  >
                    <Play className="mr-2 h-4 w-4" />
                    Activate
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive"
                  onClick={(e) => {
                    e.stopPropagation()
                    deleteMutation.mutate()
                  }}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          {workflow.description && (
            <CardDescription className="line-clamp-2">
              {workflow.description}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2 text-muted-foreground">
              <StatusIcon status={workflow.last_execution_status} />
              <span>
                {workflow.last_execution_status
                  ? `Last: ${workflow.last_execution_status}`
                  : 'No executions'}
              </span>
            </div>
            <span className="text-xs text-muted-foreground">
              {new Date(workflow.updated_at).toLocaleDateString()}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Webhook Settings Dialog */}
      <Dialog open={isWebhookOpen} onOpenChange={setIsWebhookOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Webhook className="h-5 w-5" />
              Webhook Settings
            </DialogTitle>
            <DialogDescription>
              Configure webhook for "{workflow.name}"
            </DialogDescription>
          </DialogHeader>

          {webhookQuery.isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          ) : webhookQuery.data ? (
            <div className="space-y-6 py-4 overflow-y-auto flex-1">
              {/* Enable/Disable Toggle */}
              <div className="flex items-center justify-between rounded-lg border p-4">
                <div>
                  <Label className="text-base">Enable Webhook</Label>
                  <p className="text-sm text-muted-foreground">
                    Allow external systems to trigger this workflow
                  </p>
                </div>
                <Switch
                  checked={webhookQuery.data.webhook_enabled}
                  onCheckedChange={(checked) => {
                    if (checked) {
                      enableWebhookMutation.mutate()
                    } else {
                      disableWebhookMutation.mutate()
                    }
                  }}
                  disabled={enableWebhookMutation.isPending || disableWebhookMutation.isPending}
                />
              </div>

              {/* Authentication Type */}
              <div className="space-y-3">
                <Label>Authentication Method</Label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    className={cn(
                      'rounded-lg border p-4 text-left transition-all',
                      webhookQuery.data.webhook_auth_type === 'payload'
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:border-primary/50'
                    )}
                    onClick={() => updateAuthTypeMutation.mutate('payload')}
                    disabled={updateAuthTypeMutation.isPending}
                  >
                    <div className="font-medium">Secret in Payload</div>
                    <p className="text-xs text-muted-foreground mt-1">
                      For TradingView, custom scripts
                    </p>
                  </button>
                  <button
                    type="button"
                    className={cn(
                      'rounded-lg border p-4 text-left transition-all',
                      webhookQuery.data.webhook_auth_type === 'url'
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:border-primary/50'
                    )}
                    onClick={() => updateAuthTypeMutation.mutate('url')}
                    disabled={updateAuthTypeMutation.isPending}
                  >
                    <div className="font-medium">Secret in URL</div>
                    <p className="text-xs text-muted-foreground mt-1">
                      For Chartink, fixed-format services
                    </p>
                  </button>
                </div>
              </div>

              {/* Webhook URL */}
              <div className="space-y-2">
                <Label>Webhook URL</Label>
                <div className="flex gap-2">
                  <Input
                    readOnly
                    value={webhookQuery.data.webhook_url}
                    className="font-mono text-sm"
                  />
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => copyToClipboard(webhookQuery.data.webhook_url, 'URL')}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              {/* Webhook URL with Symbol */}
              <div className="space-y-2">
                <Label>Webhook URL (with symbol)</Label>
                <div className="flex gap-2">
                  <Input
                    readOnly
                    value={webhookQuery.data.webhook_url_with_symbol}
                    className="font-mono text-sm"
                  />
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => copyToClipboard(webhookQuery.data.webhook_url_with_symbol, 'URL')}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Replace {'{symbol}'} with actual symbol like RELIANCE, INFY, etc.
                </p>
              </div>

              {/* Webhook Secret */}
              <div className="space-y-2">
                <Label>Webhook Secret</Label>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <Input
                      readOnly
                      type={showSecret ? 'text' : 'password'}
                      value={webhookQuery.data.webhook_secret}
                      className="font-mono text-sm pr-10"
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="absolute right-0 top-0 h-full"
                      onClick={() => setShowSecret(!showSecret)}
                    >
                      {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </Button>
                  </div>
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => copyToClipboard(webhookQuery.data.webhook_secret, 'Secret')}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  {webhookQuery.data.webhook_auth_type === 'url'
                    ? 'Append this secret to URL as ?secret=...'
                    : 'Include this secret in your webhook payload as "secret" field'}
                </p>
              </div>

              {/* URL with Secret (for URL auth type) */}
              {webhookQuery.data.webhook_auth_type === 'url' && webhookQuery.data.webhook_url_with_secret && (
                <div className="space-y-2">
                  <Label>Webhook URL (with secret)</Label>
                  <div className="flex gap-2">
                    <Input
                      readOnly
                      value={showSecret ? webhookQuery.data.webhook_url_with_secret : webhookQuery.data.webhook_url + '?secret=........'}
                      className="font-mono text-sm"
                    />
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => copyToClipboard(webhookQuery.data.webhook_url_with_secret!, 'URL with secret')}
                    >
                      <Copy className="h-4 w-4" />
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Use this URL for Chartink and other services with fixed payloads
                  </p>
                </div>
              )}

              {/* Example Usage */}
              <div className="space-y-2">
                <Label>Example Usage</Label>
                <div className="rounded-lg bg-muted p-4">
                  {webhookQuery.data.webhook_auth_type === 'url' ? (
                    <>
                      <p className="text-xs text-muted-foreground mb-2">For Chartink (secret in URL):</p>
                      <pre className="text-xs font-mono overflow-x-auto">
{`POST ${webhookQuery.data.webhook_url}?secret=${showSecret ? webhookQuery.data.webhook_secret : '........'}

Chartink payload (sent as-is):
{
  "stocks": "RELIANCE,INFY,TCS",
  "trigger_prices": "2500.50,1800.25,3500.00",
  "triggered_at": "9:30 am",
  "scan_name": "My Scanner",
  "alert_name": "Buy Alert"
}`}
                      </pre>
                    </>
                  ) : (
                    <>
                      <p className="text-xs text-muted-foreground mb-2">For TradingView (secret in payload):</p>
                      <pre className="text-xs font-mono overflow-x-auto">
{`POST ${webhookQuery.data.webhook_url}

{
  "secret": "${showSecret ? webhookQuery.data.webhook_secret : '................'}",
  "symbol": "RELIANCE",
  "action": "BUY",
  "quantity": 10,
  "price": 2500.50
}`}
                      </pre>
                    </>
                  )}
                </div>
              </div>

              {/* Regenerate Button */}
              <div className="flex justify-end pt-2">
                <Button
                  variant="outline"
                  onClick={() => regenerateWebhookMutation.mutate()}
                  disabled={regenerateWebhookMutation.isPending}
                >
                  {regenerateWebhookMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="mr-2 h-4 w-4" />
                  )}
                  Regenerate URL & Secret
                </Button>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  )
}

export default function FlowIndex() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [isImportOpen, setIsImportOpen] = useState(false)
  const [newWorkflowName, setNewWorkflowName] = useState('')
  const [importJson, setImportJson] = useState('')
  const [importError, setImportError] = useState<string | null>(null)

  const { data: workflows, isLoading } = useQuery({
    queryKey: flowQueryKeys.workflows(),
    queryFn: listWorkflows,
  })

  const createMutation = useMutation({
    mutationFn: createWorkflow,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflows() })
      setIsCreateOpen(false)
      setNewWorkflowName('')
      navigate(`/flow/editor/${data.id}`)
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  const importMutation = useMutation({
    mutationFn: importWorkflow,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: flowQueryKeys.workflows() })
      setIsImportOpen(false)
      setImportJson('')
      setImportError(null)
      showToast.success(`Workflow "${data.name}" imported`, 'flow')
      navigate(`/flow/editor/${data.id}`)
    },
    onError: (error: Error) => {
      showToast.error(error.message, 'flow')
    },
  })

  const handleCreate = () => {
    if (!newWorkflowName.trim()) return
    createMutation.mutate({ name: newWorkflowName.trim() })
  }

  const handleImport = () => {
    setImportError(null)
    try {
      const parsed = JSON.parse(importJson) as WorkflowExportData
      // Validate basic structure
      if (!parsed.name || !Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges)) {
        setImportError('Invalid workflow format. Must have name, nodes, and edges.')
        return
      }
      importMutation.mutate(parsed)
    } catch {
      setImportError('Invalid JSON format. Please check the workflow data.')
    }
  }

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      const content = e.target?.result as string
      setImportJson(content)
      setImportError(null)
    }
    reader.onerror = () => {
      setImportError('Failed to read file')
    }
    reader.readAsText(file)
  }

  if (isLoading) {
    return (
      <div className="flex h-[calc(100vh-3.5rem)] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Flow Editor</h1>
          <p className="text-muted-foreground">
            Create and manage your trading automations
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => setIsImportOpen(true)}>
            <Upload className="mr-2 h-4 w-4" />
            Import
          </Button>
          <Button onClick={() => setIsCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            New Workflow
          </Button>
        </div>
      </div>

      {workflows && workflows.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {workflows.map((workflow) => (
            <WorkflowCard key={workflow.id} workflow={workflow} />
          ))}
        </div>
      ) : (
        <Card className="flex flex-col items-center justify-center py-16">
          <div className="mb-4 rounded-full bg-muted p-4">
            <Plus className="h-8 w-8 text-muted-foreground" />
          </div>
          <h3 className="mb-2 text-lg font-medium">No workflows yet</h3>
          <p className="mb-6 text-center text-sm text-muted-foreground">
            Create your first workflow to automate your trading
          </p>
          <Button onClick={() => setIsCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Create Workflow
          </Button>
        </Card>
      )}

      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New Workflow</DialogTitle>
            <DialogDescription>
              Give your workflow a name to get started
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="name">Workflow Name</Label>
              <Input
                id="name"
                placeholder="e.g., Morning Order Automation"
                value={newWorkflowName}
                onChange={(e) => setNewWorkflowName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreate}
              disabled={!newWorkflowName.trim() || createMutation.isPending}
            >
              {createMutation.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={isImportOpen} onOpenChange={(open) => {
        setIsImportOpen(open)
        if (!open) {
          setImportJson('')
          setImportError(null)
        }
      }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Import Workflow</DialogTitle>
            <DialogDescription>
              Import a workflow from a JSON file or paste the JSON data
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="file">Upload File</Label>
              <Input
                id="file"
                type="file"
                accept=".json"
                onChange={handleFileUpload}
                className="cursor-pointer"
              />
            </div>
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-background px-2 text-muted-foreground">
                  or paste JSON
                </span>
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="json">Workflow JSON</Label>
              <Textarea
                id="json"
                placeholder='{"name": "My Workflow", "nodes": [...], "edges": [...]}'
                value={importJson}
                onChange={(e) => {
                  setImportJson(e.target.value)
                  setImportError(null)
                }}
                className="h-40 font-mono text-sm"
              />
              {importError && (
                <p className="text-sm text-destructive">{importError}</p>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsImportOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleImport}
              disabled={!importJson.trim() || importMutation.isPending}
            >
              {importMutation.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Import
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

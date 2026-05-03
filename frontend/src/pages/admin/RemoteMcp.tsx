import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Globe,
  Loader2,
  Power,
  RefreshCw,
  Save,
  ShieldAlert,
} from 'lucide-react'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminApi } from '@/api/admin'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { MCPAuditEntry, MCPSettings, OAuthClient } from '@/types/admin'
import { showToast } from '@/utils/toast'

const RESTART_PENDING_KEY = 'mcp_restart_pending_settings'

function settingsEqual(a: MCPSettings, b: MCPSettings): boolean {
  return (
    a.http_enabled === b.http_enabled &&
    a.public_url === b.public_url &&
    a.require_approval === b.require_approval &&
    a.write_scope_enabled === b.write_scope_enabled
  )
}

const SCOPE_FILTERS = [
  { value: '__all', label: 'All scopes' },
  { value: 'read:market', label: 'read:market' },
  { value: 'read:account', label: 'read:account' },
  { value: 'write:orders', label: 'write:orders' },
]

const OUTCOME_FILTERS = [
  { value: '__all', label: 'All outcomes' },
  { value: 'success', label: 'success' },
  { value: 'error', label: 'error' },
  { value: 'bad_arguments', label: 'bad_arguments' },
]

function ClientCard({
  client,
  busy,
  onApprove,
  onRevoke,
}: {
  client: OAuthClient
  busy: boolean
  onApprove: () => void
  onRevoke: () => void
}) {
  const status = client.revoked_at ? 'revoked' : client.approved ? 'approved' : 'pending'
  const badgeVariant: 'default' | 'secondary' | 'destructive' = client.revoked_at
    ? 'destructive'
    : client.approved
      ? 'default'
      : 'secondary'

  return (
    <div className="border rounded-md p-4 space-y-2">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="font-semibold">{client.client_name}</div>
          <div className="text-xs font-mono text-muted-foreground break-all">
            {client.client_id}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Badge variant={badgeVariant}>{status}</Badge>
          {client.is_public ? <Badge variant="outline">public client</Badge> : null}
        </div>
      </div>

      <div className="text-xs grid grid-cols-1 md:grid-cols-2 gap-1 text-muted-foreground">
        <div>
          <span className="font-medium text-foreground">Scopes requested: </span>
          {client.scopes_requested.length > 0 ? client.scopes_requested.join(', ') : '—'}
        </div>
        <div>
          <span className="font-medium text-foreground">Created: </span>
          {client.created_at ? new Date(client.created_at).toLocaleString() : '—'}
        </div>
        {client.approved_at ? (
          <div>
            <span className="font-medium text-foreground">Approved: </span>
            {new Date(client.approved_at).toLocaleString()}
          </div>
        ) : null}
        {client.revoked_at ? (
          <div>
            <span className="font-medium text-foreground">Revoked: </span>
            {new Date(client.revoked_at).toLocaleString()}
          </div>
        ) : null}
        {client.last_used_at ? (
          <div>
            <span className="font-medium text-foreground">Last used: </span>
            {new Date(client.last_used_at).toLocaleString()}
          </div>
        ) : null}
      </div>

      <div className="text-xs">
        <span className="font-medium">Redirect URIs: </span>
        <span className="font-mono break-all text-muted-foreground">
          {client.redirect_uris.join(', ')}
        </span>
      </div>

      {!client.revoked_at ? (
        <div className="flex gap-2 pt-2">
          {!client.approved ? (
            <Button size="sm" onClick={onApprove} disabled={busy}>
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
              )}
              Approve
            </Button>
          ) : null}
          <Button size="sm" variant="outline" onClick={onRevoke} disabled={busy}>
            <Ban className="h-3.5 w-3.5 mr-1" />
            Revoke
          </Button>
        </div>
      ) : null}
    </div>
  )
}

export default function RemoteMcp() {
  const [loading, setLoading] = useState(true)
  const [mcpEnabled, setMcpEnabled] = useState(false)
  const [clients, setClients] = useState<OAuthClient[]>([])
  const [summary, setSummary] = useState({ pending: 0, approved: 0, revoked: 0 })
  const [audit, setAudit] = useState<MCPAuditEntry[]>([])
  const [auditTotal, setAuditTotal] = useState(0)
  const [auditTool, setAuditTool] = useState('')
  const [auditScope, setAuditScope] = useState('__all')
  const [auditOutcome, setAuditOutcome] = useState('__all')
  const [busyClient, setBusyClient] = useState<string | null>(null)
  const [revokeTarget, setRevokeTarget] = useState<OAuthClient | null>(null)
  const [killSwitchOpen, setKillSwitchOpen] = useState(false)
  const [killSwitchBusy, setKillSwitchBusy] = useState(false)
  const [expandedAudit, setExpandedAudit] = useState<number | null>(null)

  // Settings card state — runtime values, the user's pending edits, and a
  // "restart required" tracker that survives page reloads. We persist the
  // settings the user last saved in localStorage; on every load we compare
  // them with the runtime values returned by GET /admin/api/mcp/settings.
  // If they match the runtime, the service was restarted and changes took
  // effect — clear the banner.
  const [settings, setSettings] = useState<MCPSettings | null>(null)
  const [pending, setPendingSettings] = useState<MCPSettings | null>(null)
  const [savingSettings, setSavingSettings] = useState(false)
  const [restartPending, setRestartPending] = useState<MCPSettings | null>(null)

  const loadAll = async () => {
    setLoading(true)
    try {
      const [clientsRes, auditRes, settingsRes] = await Promise.all([
        adminApi.getOAuthClients(),
        adminApi.getMCPAudit({ limit: 100 }),
        adminApi.getMCPSettings(),
      ])
      setMcpEnabled(clientsRes.mcp_enabled)
      setClients(clientsRes.clients)
      setSummary(clientsRes.summary)
      setAudit(auditRes.data)
      setAuditTotal(auditRes.total_in_window)
      setSettings(settingsRes.settings)
      setPendingSettings(settingsRes.settings)

      // Reconcile saved-but-not-applied state stored in localStorage
      // against what the running process actually reports back.
      const stored = localStorage.getItem(RESTART_PENDING_KEY)
      if (stored) {
        try {
          const parsed = JSON.parse(stored) as MCPSettings
          if (settingsEqual(parsed, settingsRes.settings)) {
            // Service was restarted — runtime now matches what was saved.
            localStorage.removeItem(RESTART_PENDING_KEY)
            setRestartPending(null)
          } else {
            setRestartPending(parsed)
          }
        } catch {
          localStorage.removeItem(RESTART_PENDING_KEY)
        }
      } else {
        setRestartPending(null)
      }
    } catch {
      showToast.error('Failed to load Remote MCP state', 'admin')
    } finally {
      setLoading(false)
    }
  }

  const handleSaveSettings = async () => {
    if (!pending || !settings) return
    if (settingsEqual(pending, settings)) return
    setSavingSettings(true)
    try {
      const res = await adminApi.updateMCPSettings({
        http_enabled: pending.http_enabled,
        public_url: pending.public_url,
        require_approval: pending.require_approval,
        write_scope_enabled: pending.write_scope_enabled,
      })
      if (res.status !== 'success') {
        showToast.error(res.message ?? 'Failed to save settings', 'admin')
        return
      }
      // Persist the saved values so we can show the "restart required"
      // banner on reloads until the running process actually picks them up.
      localStorage.setItem(RESTART_PENDING_KEY, JSON.stringify(pending))
      setRestartPending(pending)
      showToast.success('Saved. Restart the openalgo service to apply.', 'admin')
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { message?: string } } })?.response?.data?.message ??
        'Failed to save settings'
      showToast.error(msg, 'admin')
    } finally {
      setSavingSettings(false)
    }
  }

  const handleCopyMcpUrl = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url)
      showToast.success('MCP URL copied', 'admin')
    } catch {
      showToast.error('Copy failed — copy manually', 'admin')
    }
  }

  const settingsDirty = !!(settings && pending && !settingsEqual(settings, pending))

  const reloadAudit = async () => {
    try {
      const res = await adminApi.getMCPAudit({
        limit: 100,
        tool: auditTool || undefined,
        scope: auditScope === '__all' ? undefined : auditScope,
        outcome: auditOutcome === '__all' ? undefined : auditOutcome,
      })
      setAudit(res.data)
      setAuditTotal(res.total_in_window)
    } catch {
      showToast.error('Failed to refresh audit log', 'admin')
    }
  }

  useEffect(() => {
    loadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleApprove = async (clientId: string) => {
    setBusyClient(clientId)
    try {
      await adminApi.approveOAuthClient(clientId)
      showToast.success('Client approved', 'admin')
      await loadAll()
    } catch {
      showToast.error('Failed to approve client', 'admin')
    } finally {
      setBusyClient(null)
    }
  }

  const handleRevoke = async () => {
    if (!revokeTarget) return
    setBusyClient(revokeTarget.client_id)
    try {
      const res = await adminApi.revokeOAuthClient(revokeTarget.client_id)
      showToast.success(`Revoked client and ${res.tokens_revoked} active tokens`, 'admin')
      setRevokeTarget(null)
      await loadAll()
    } catch {
      showToast.error('Failed to revoke client', 'admin')
    } finally {
      setBusyClient(null)
    }
  }

  const handleKillSwitch = async () => {
    setKillSwitchBusy(true)
    try {
      const res = await adminApi.triggerMCPKillSwitch()
      showToast.success(`Kill switch fired — ${res.tokens_revoked} tokens revoked`, 'admin')
      setKillSwitchOpen(false)
      await loadAll()
    } catch {
      showToast.error('Kill switch failed', 'admin')
    } finally {
      setKillSwitchBusy(false)
    }
  }

  const pending = useMemo(() => clients.filter((c) => !c.approved && !c.revoked_at), [clients])
  const approved = useMemo(() => clients.filter((c) => c.approved && !c.revoked_at), [clients])
  const revoked = useMemo(() => clients.filter((c) => c.revoked_at), [clients])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Link to="/admin">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="h-4 w-4 mr-1" /> Back
            </Button>
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Globe className="h-6 w-6" /> Remote MCP
          </h1>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={loadAll}>
            <RefreshCw className="h-4 w-4 mr-1" /> Refresh
          </Button>
          {mcpEnabled ? (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setKillSwitchOpen(true)}
              title="Revoke every active refresh token"
            >
              <AlertTriangle className="h-4 w-4 mr-1" /> Kill switch
            </Button>
          ) : null}
        </div>
      </div>

      {/* Settings card (always visible) */}
      {settings && pending ? (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <Power className="h-5 w-5" />
                  Remote MCP settings
                </CardTitle>
                <CardDescription>
                  Toggle Remote MCP on or off and adjust its OAuth posture. Changes are written to
                  <code className="mx-1">.env</code>; the openalgo service must be restarted before
                  they take effect.
                </CardDescription>
              </div>
              <Badge variant={mcpEnabled ? 'default' : 'secondary'}>
                Currently {mcpEnabled ? 'enabled' : 'disabled'}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* MCP URL display — only when public URL is configured */}
            {pending.mcp_url ? (
              <div className="rounded-lg border bg-muted/30 p-3">
                <div className="text-xs uppercase text-muted-foreground mb-1">MCP URL</div>
                <div className="flex items-center gap-2">
                  <code className="flex-1 font-mono text-sm break-all">{pending.mcp_url}</code>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleCopyMcpUrl(pending.mcp_url)}
                  >
                    <Copy className="h-3.5 w-3.5 mr-1" /> Copy
                  </Button>
                </div>
                <div className="text-xs text-muted-foreground mt-2">
                  Point your hosted AI client (claude.ai, chatgpt.com) at this URL.
                </div>
              </div>
            ) : null}

            {/* Public URL input — required when enabling */}
            <div className="space-y-1.5">
              <label htmlFor="mcp-public-url" className="text-sm font-medium">
                Public HTTPS origin
              </label>
              <Input
                id="mcp-public-url"
                value={pending.public_url}
                onChange={(e) =>
                  setPendingSettings({ ...pending, public_url: e.target.value.trim() })
                }
                placeholder="https://yourdomain.com"
              />
              <p className="text-xs text-muted-foreground">
                Same as your OpenAlgo dashboard URL. Required when MCP is enabled. Used as the
                JWT issuer / audience claim — tokens are scoped to this exact origin.
              </p>
            </div>

            {/* Toggles */}
            <div className="space-y-4">
              <div className="flex items-start justify-between gap-4 py-2 border-t pt-4">
                <div>
                  <div className="text-sm font-medium">Remote MCP enabled</div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Master switch for the <code>/mcp</code> and <code>/oauth/*</code> endpoints.
                    Local stdio MCP (Claude Desktop / Cursor) is unaffected.
                  </p>
                </div>
                <Switch
                  checked={pending.http_enabled}
                  onCheckedChange={(v) => setPendingSettings({ ...pending, http_enabled: v })}
                />
              </div>

              <div className="flex items-start justify-between gap-4 py-2">
                <div>
                  <div className="text-sm font-medium">Auto-approve hosted clients</div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    When ON, DCR-registered clients can complete OAuth without admin approval.
                    Suitable for single-trader self-hosted installs. Turn OFF on shared deployments
                    to require manual approval per client.
                  </p>
                </div>
                <Switch
                  checked={!pending.require_approval}
                  onCheckedChange={(v) =>
                    setPendingSettings({ ...pending, require_approval: !v })
                  }
                />
              </div>

              <div className="flex items-start justify-between gap-4 py-2">
                <div>
                  <div className="text-sm font-medium">Allow order placement (write:orders)</div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    When ON, AI clients can place / modify / cancel orders via MCP. Turn OFF for
                    read-only access (quotes, holdings, positions, market data only).
                  </p>
                </div>
                <Switch
                  checked={pending.write_scope_enabled}
                  onCheckedChange={(v) =>
                    setPendingSettings({ ...pending, write_scope_enabled: v })
                  }
                />
              </div>
            </div>

            {/* Save button */}
            <div className="flex items-center justify-between pt-2 border-t">
              <div className="text-xs text-muted-foreground">
                {settingsDirty ? 'Unsaved changes' : 'No pending changes'}
              </div>
              <div className="flex gap-2">
                {settingsDirty ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setPendingSettings(settings)}
                    disabled={savingSettings}
                  >
                    Discard
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  onClick={handleSaveSettings}
                  disabled={!settingsDirty || savingSettings}
                >
                  {savingSettings ? (
                    <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4 mr-1" />
                  )}
                  Save changes
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* Restart-required banner — shown until the running process picks up the saved values */}
      {restartPending ? (
        <Alert variant="default" className="border-amber-300 dark:border-amber-700">
          <AlertTriangle className="h-4 w-4 text-amber-600" />
          <AlertTitle>Restart required to apply changes</AlertTitle>
          <AlertDescription>
            Settings saved to <code>.env</code>. Run the following on your server to load them:
            <pre className="mt-2 rounded bg-muted px-3 py-2 text-xs font-mono">
              sudo systemctl restart openalgo
            </pre>
            <span className="block mt-2 text-xs">
              This banner clears automatically once the running service reflects the new values.
            </span>
          </AlertDescription>
        </Alert>
      ) : null}

      {/* Disabled state — short hint only; the toggle is in the settings card above */}
      {!mcpEnabled ? (
        <Alert>
          <ShieldAlert className="h-4 w-4" />
          <AlertTitle>Remote MCP is currently disabled</AlertTitle>
          <AlertDescription>
            Hosted AI clients can't reach <code>/mcp</code> right now. Enable it from the settings
            card above, then restart the service. Local stdio MCP (Claude Desktop / Cursor /
            Windsurf) is unaffected and works regardless.
          </AlertDescription>
        </Alert>
      ) : null}

      {/* The dashboard sections below only make sense when MCP is running */}
      {!mcpEnabled ? null : (
        <>
      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="text-xs uppercase text-muted-foreground">Pending</div>
            <div className="text-3xl font-bold text-amber-600">{summary.pending}</div>
            <div className="text-xs text-muted-foreground">awaiting approval</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-xs uppercase text-muted-foreground">Approved</div>
            <div className="text-3xl font-bold text-emerald-600">{summary.approved}</div>
            <div className="text-xs text-muted-foreground">active clients</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-xs uppercase text-muted-foreground">Revoked</div>
            <div className="text-3xl font-bold text-muted-foreground">{summary.revoked}</div>
            <div className="text-xs text-muted-foreground">disabled</div>
          </CardContent>
        </Card>
      </div>

      {/* Pending */}
      <Card>
        <CardHeader>
          <CardTitle>Pending approvals</CardTitle>
          <CardDescription>
            New DCR-registered clients land here. Approve only ones you recognize.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {pending.length === 0 ? (
            <p className="text-sm text-muted-foreground">No clients awaiting approval.</p>
          ) : (
            pending.map((c) => (
              <ClientCard
                key={c.client_id}
                client={c}
                busy={busyClient === c.client_id}
                onApprove={() => handleApprove(c.client_id)}
                onRevoke={() => setRevokeTarget(c)}
              />
            ))
          )}
        </CardContent>
      </Card>

      {/* Approved */}
      <Card>
        <CardHeader>
          <CardTitle>Approved clients</CardTitle>
          <CardDescription>
            Currently authorized to complete OAuth flows and call MCP tools.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {approved.length === 0 ? (
            <p className="text-sm text-muted-foreground">No approved clients yet.</p>
          ) : (
            approved.map((c) => (
              <ClientCard
                key={c.client_id}
                client={c}
                busy={busyClient === c.client_id}
                onApprove={() => handleApprove(c.client_id)}
                onRevoke={() => setRevokeTarget(c)}
              />
            ))
          )}
        </CardContent>
      </Card>

      {/* Revoked (collapsed by default — show count, expand on demand) */}
      {revoked.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Revoked clients ({revoked.length})</CardTitle>
            <CardDescription>Historical record. These cannot complete OAuth.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {revoked.map((c) => (
              <ClientCard
                key={c.client_id}
                client={c}
                busy={false}
                onApprove={() => {}}
                onRevoke={() => {}}
              />
            ))}
          </CardContent>
        </Card>
      ) : null}

      {/* Audit log */}
      <Card>
        <CardHeader>
          <CardTitle>MCP tool call audit</CardTitle>
          <CardDescription>
            Tail of <code>log/mcp.jsonl</code>. Every tool call by any client is recorded with
            timestamp, jti, scope, and outcome — params themselves are stored as a SHA-256 hash.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2 mb-4">
            <Input
              placeholder="Filter by tool name (substring)"
              value={auditTool}
              onChange={(e) => setAuditTool(e.target.value.slice(0, 100))}
              className="max-w-xs"
            />
            <Select value={auditScope} onValueChange={setAuditScope}>
              <SelectTrigger className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SCOPE_FILTERS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={auditOutcome} onValueChange={setAuditOutcome}>
              <SelectTrigger className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {OUTCOME_FILTERS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={reloadAudit}>
              Apply
            </Button>
          </div>

          <div className="text-xs text-muted-foreground mb-2">
            Showing {audit.length} of {auditTotal} entries
          </div>

          {audit.length === 0 ? (
            <p className="text-sm text-muted-foreground">No tool calls yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8" />
                  <TableHead>Time</TableHead>
                  <TableHead>Tool</TableHead>
                  <TableHead>Scope</TableHead>
                  <TableHead>Outcome</TableHead>
                  <TableHead>Latency</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {audit
                  .slice()
                  .reverse()
                  .map((entry, idx) => {
                    const isOpen = expandedAudit === idx
                    return (
                      <Fragment key={`${entry.ts}-${entry.jti}-${idx}`}>
                        <TableRow
                          key={`${entry.ts}-${entry.jti}-${idx}`}
                          className="cursor-pointer hover:bg-muted/50"
                          onClick={() => setExpandedAudit(isOpen ? null : idx)}
                        >
                          <TableCell>
                            {isOpen ? (
                              <ChevronDown className="h-4 w-4" />
                            ) : (
                              <ChevronRight className="h-4 w-4" />
                            )}
                          </TableCell>
                          <TableCell className="font-mono text-xs">{entry.ts}</TableCell>
                          <TableCell className="font-mono text-xs">{entry.tool}</TableCell>
                          <TableCell>
                            <Badge variant="outline" className="text-xs">
                              {entry.scope}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant={entry.outcome === 'success' ? 'default' : 'destructive'}
                              className="text-xs"
                            >
                              {entry.outcome}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-xs">
                            {entry.duration_ms != null ? `${entry.duration_ms} ms` : '—'}
                          </TableCell>
                        </TableRow>
                        {isOpen ? (
                          <TableRow>
                            <TableCell colSpan={6} className="bg-muted/30 text-xs">
                              <div className="grid grid-cols-1 md:grid-cols-3 gap-2 py-2">
                                <div>
                                  <span className="text-muted-foreground">Client:</span>{' '}
                                  <span className="font-mono">{entry.client_id ?? '—'}</span>
                                </div>
                                <div>
                                  <span className="text-muted-foreground">JTI:</span>{' '}
                                  <span className="font-mono">{entry.jti ?? '—'}</span>
                                </div>
                                <div>
                                  <span className="text-muted-foreground">IP:</span>{' '}
                                  <span className="font-mono">{entry.request_ip ?? '—'}</span>
                                </div>
                                <div className="md:col-span-3">
                                  <span className="text-muted-foreground">Params hash:</span>{' '}
                                  <span className="font-mono">{entry.params_hash ?? '—'}</span>
                                </div>
                              </div>
                            </TableCell>
                          </TableRow>
                        ) : null}
                      </Fragment>
                    )
                  })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

        </>
      )}

      {/* Revoke confirmation dialog */}
      <AlertDialog open={!!revokeTarget} onOpenChange={(o) => !o && setRevokeTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <Ban className="h-5 w-5 text-destructive" />
              Revoke {revokeTarget?.client_name}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This immediately revokes the client and every refresh token it owns. The client will
              be unable to call MCP tools and must complete a fresh OAuth dance to regain access —
              if it's still approved. Active access tokens already issued continue to work until
              they expire (15 minutes max).
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRevoke}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Revoke client
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Kill switch dialog */}
      <AlertDialog open={killSwitchOpen} onOpenChange={setKillSwitchOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              Trigger the Remote MCP kill switch?
            </AlertDialogTitle>
            <AlertDialogDescription className="space-y-2">
              <span className="block">
                This revokes <strong>every</strong> refresh token across <strong>all</strong>{' '}
                approved MCP clients in one shot. Use it if you suspect a stolen token, an
                unexpected order, or before disabling Remote MCP entirely.
              </span>
              <span className="block">
                Active access tokens already issued continue to work until they expire — write tools
                have a 15-minute hard cap. Clients are forced through a fresh OAuth dance to regain
                refresh capability.
              </span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={killSwitchBusy}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleKillSwitch}
              disabled={killSwitchBusy}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {killSwitchBusy ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
              Revoke all MCP tokens
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

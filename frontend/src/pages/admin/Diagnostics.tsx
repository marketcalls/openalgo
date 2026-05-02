import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Cpu,
  Database,
  Download,
  FileText,
  Gauge,
  HardDrive,
  Network,
  RefreshCw,
  Server,
  Settings,
  XCircle,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminApi } from '@/api/admin'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type {
  DiagnosticCheck,
  ErrorEntry,
  ErrorGroup,
  ErrorsStats,
  SystemInfo,
} from '@/types/admin'
import { showToast } from '@/utils/toast'

const LEVEL_OPTIONS = ['', 'ERROR', 'CRITICAL', 'WARNING', 'INFO']

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1.5 border-b border-border/40 last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-right break-all">
        {value === null || value === undefined || value === '' ? (
          <span className="text-muted-foreground italic">not set</span>
        ) : typeof value === 'boolean' ? (
          value ? (
            'Yes'
          ) : (
            'No'
          )
        ) : (
          value
        )}
      </span>
    </div>
  )
}

function Section({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className="h-4 w-4" />
          {title}
        </CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

export default function Diagnostics() {
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [errors, setErrors] = useState<ErrorEntry[]>([])
  const [errorStats, setErrorStats] = useState<ErrorsStats | null>(null)
  const [diagChecks, setDiagChecks] = useState<DiagnosticCheck[] | null>(null)
  const [diagRanAt, setDiagRanAt] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isRunningDiag, setIsRunningDiag] = useState(false)
  const [errorLevelFilter, setErrorLevelFilter] = useState('')
  const [errorQuery, setErrorQuery] = useState('')
  const [expandedError, setExpandedError] = useState<number | null>(null)
  const [errorView, setErrorView] = useState<'recent' | 'grouped'>('recent')
  const [groups, setGroups] = useState<ErrorGroup[]>([])
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null)

  const loadAll = async () => {
    setIsLoading(true)
    try {
      const [sys, list, stats, grouped] = await Promise.all([
        adminApi.getSystemInfo(),
        adminApi.getErrors({ limit: 100 }),
        adminApi.getErrorStats(),
        adminApi.getErrorGroups(50),
      ])
      setInfo(sys)
      setErrors(list.data)
      setErrorStats(stats)
      setGroups(grouped.groups)
    } catch {
      showToast.error('Failed to load diagnostics', 'admin')
    } finally {
      setIsLoading(false)
    }
  }

  const reloadErrors = async () => {
    try {
      const list = await adminApi.getErrors({
        limit: 100,
        level: errorLevelFilter || undefined,
        q: errorQuery || undefined,
      })
      setErrors(list.data)
    } catch {
      showToast.error('Failed to reload errors', 'admin')
    }
  }

  const runDiagnostics = async () => {
    setIsRunningDiag(true)
    try {
      const response = await adminApi.runDiagnostics()
      setDiagChecks(response.checks)
      setDiagRanAt(response.ran_at)
      showToast.success('Diagnostics complete', 'admin')
    } catch {
      showToast.error('Diagnostics failed', 'admin')
    } finally {
      setIsRunningDiag(false)
    }
  }

  useEffect(() => {
    loadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const isAnalyze = info?.mode.analyze_mode === true

  const downloadReport = (format: 'md' | 'txt') => {
    adminApi.downloadReport(format)
  }

  const filteredErrors = useMemo(() => errors, [errors])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    )
  }

  return (
    <div className="py-6 space-y-6">
      {/* Header + actions */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Link to="/admin">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="h-4 w-4 mr-1" /> Back
            </Button>
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Gauge className="h-6 w-6" /> Diagnostics
          </h1>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={loadAll}>
            <RefreshCw className="h-4 w-4 mr-1" /> Refresh
          </Button>
          <Button variant="outline" size="sm" onClick={() => downloadReport('md')}>
            <Download className="h-4 w-4 mr-1" /> Download .md
          </Button>
          <Button variant="outline" size="sm" onClick={() => downloadReport('txt')}>
            <FileText className="h-4 w-4 mr-1" /> Download .txt
          </Button>
        </div>
      </div>

      {/* Mode banner */}
      {info?.mode ? (
        <Card
          className={
            isAnalyze
              ? 'border-amber-500/60 bg-amber-50 dark:bg-amber-950/30'
              : 'border-emerald-500/60 bg-emerald-50 dark:bg-emerald-950/30'
          }
        >
          <CardContent className="pt-6 flex items-center justify-between flex-wrap gap-3">
            <div>
              <div className="text-xs uppercase tracking-wider text-muted-foreground">
                Trading Mode
              </div>
              <div
                className={`text-2xl font-bold ${
                  isAnalyze
                    ? 'text-amber-700 dark:text-amber-300'
                    : 'text-emerald-700 dark:text-emerald-300'
                }`}
              >
                {info.mode.label}
              </div>
            </div>
            <div className="text-sm text-muted-foreground max-w-md text-right">
              {isAnalyze
                ? 'Sandbox mode — orders use sandbox capital and never reach the broker.'
                : 'Live mode — orders are routed to the real broker account.'}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <p className="text-sm text-muted-foreground">
        Use this page to troubleshoot issues. Click{' '}
        <span className="font-semibold">Download .md</span> and attach it when asking for help on
        the OpenAlgo community — secrets and tokens are never included.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Host */}
        <Section icon={Server} title="Host">
          <div>
            <KV label="System" value={info?.host.system} />
            <KV label="Release" value={info?.host.release} />
            <KV label="Architecture" value={info?.host.machine} />
            <KV label="Platform" value={info?.host.platform} />
            <KV
              label="Distro"
              value={
                info?.host.distro
                  ? `${info.host.distro.name ?? ''} (${info.host.distro.id ?? ''} ${info.host.distro.version_id ?? ''})`
                  : null
              }
            />
            <KV label="In Docker" value={info?.host.in_docker} />
            {info?.host.is_raspberry_pi ? (
              <KV label="Raspberry Pi" value={info.host.rpi_model} />
            ) : null}
            {info?.host.is_termux ? <KV label="Termux" value={true} /> : null}
            {info?.host.is_android ? <KV label="Android" value={true} /> : null}
          </div>
        </Section>

        {/* Runtime */}
        <Section icon={Cpu} title="Runtime">
          <div>
            <KV label="Python" value={info?.runtime.python_version} />
            <KV label="Implementation" value={info?.runtime.python_implementation} />
            <KV label="Eventlet active" value={info?.runtime.eventlet_active} />
            <KV label="WSGI" value={info?.runtime.wsgi_hint} />
            <KV
              label="Process uptime"
              value={
                info?.runtime.process_uptime_seconds
                  ? `${Math.floor(info.runtime.process_uptime_seconds / 60)} min`
                  : null
              }
            />
          </div>
        </Section>

        {/* Hardware */}
        <Section icon={HardDrive} title="Hardware">
          <div>
            <KV label="CPU count" value={info?.hardware.cpu_count} />
            <KV label="CPU model" value={info?.hardware.cpu_model} />
            <KV
              label="Memory total"
              value={info?.hardware.memory_total_mb ? `${info.hardware.memory_total_mb} MB` : null}
            />
            <KV
              label="Memory available"
              value={
                info?.hardware.memory_available_mb !== undefined &&
                info?.hardware.memory_available_mb !== null
                  ? `${info.hardware.memory_available_mb} MB (${info.hardware.memory_percent}% used)`
                  : null
              }
            />
            {info?.hardware.disk_log ? (
              <KV
                label="Disk (log/)"
                value={`${info.hardware.disk_log.free_gb} GB free of ${info.hardware.disk_log.total_gb} GB`}
              />
            ) : null}
            {info?.hardware.disk_db ? (
              <KV
                label="Disk (db/)"
                value={`${info.hardware.disk_db.free_gb} GB free of ${info.hardware.disk_db.total_gb} GB`}
              />
            ) : null}
          </div>
        </Section>

        {/* Build */}
        <Section icon={Settings} title="Build">
          <div>
            <KV label="OpenAlgo" value={info?.build.openalgo_version} />
            <KV label="OpenAlgo SDK" value={info?.build.openalgo_sdk_version} />
            <KV label="Git branch" value={info?.build.git_branch} />
            <KV label="Git commit" value={info?.build.git_commit} />
            <KV label="Frontend build" value={info?.build.frontend_build_time} />
          </div>
        </Section>

        {/* Time */}
        <Section icon={Settings} title="Time">
          <div>
            <KV label="Server time" value={info?.time.server_time} />
            <KV label="Server timezone" value={info?.time.server_tz} />
            <KV label="IST time" value={info?.time.ist_time} />
          </div>
        </Section>

        {/* Brokers */}
        <Section icon={Network} title="Brokers">
          <div>
            <KV label="Active broker" value={info?.brokers.active_broker} />
            <KV label="User logged in" value={info?.brokers.user_logged_in} />
            <KV
              label="Configured"
              value={
                info?.brokers.configured_brokers && info.brokers.configured_brokers.length > 0
                  ? info.brokers.configured_brokers.join(', ')
                  : null
              }
            />
          </div>
        </Section>
      </div>

      {/* Configuration */}
      <Section
        icon={Settings}
        title="Configuration"
        description="Sensitive values are shown only as set/not set."
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
          <div>
            <KV label="Valid brokers" value={info?.config.valid_brokers.join(', ') || null} />
            <KV label="Log level" value={info?.config.log_level} />
            <KV label="Log to file" value={info?.config.log_to_file} />
            <KV label="Log directory" value={info?.config.log_dir} />
            <KV label="Flask debug" value={info?.config.flask_debug} />
            <KV label="API rate limit" value={info?.config.api_rate_limit} />
          </div>
          <div>
            <KV label="WebSocket host" value={info?.config.websocket_host} />
            <KV label="WebSocket port" value={info?.config.websocket_port} />
            <KV label="Max symbols/WS" value={info?.config.max_symbols_per_websocket} />
            <KV label="Max WS connections" value={info?.config.max_websocket_connections} />
          </div>
        </div>
        {info?.config.secrets_present ? (
          <div className="mt-4">
            <div className="text-sm font-semibold mb-2">Secrets (presence only)</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(info.config.secrets_present).map(([key, present]) => (
                <Badge key={key} variant={present ? 'default' : 'secondary'}>
                  {key}: {present ? 'set' : 'not set'}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
      </Section>

      {/* Databases */}
      <Section icon={Database} title="Databases">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Size</TableHead>
              <TableHead>Modified</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {info?.databases.map((db) => (
              <TableRow key={db.name}>
                <TableCell className="font-medium">{db.name}</TableCell>
                <TableCell>
                  {db.exists ? (
                    <Badge variant="default">present</Badge>
                  ) : (
                    <Badge variant="secondary">missing</Badge>
                  )}
                </TableCell>
                <TableCell>{db.exists ? `${db.size_mb} MB` : '—'}</TableCell>
                <TableCell className="text-muted-foreground">{db.modified ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Section>

      {/* Diagnostics probes */}
      <Section
        icon={Network}
        title="Latency & Connectivity Probes"
        description="On-demand checks. No external HTTP calls — TCP-only probes to known endpoints."
      >
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <div className="text-sm text-muted-foreground">
            {diagRanAt ? `Last run: ${diagRanAt}` : 'Not run yet'}
          </div>
          <Button onClick={runDiagnostics} disabled={isRunningDiag} size="sm">
            <RefreshCw className={`h-4 w-4 mr-1 ${isRunningDiag ? 'animate-spin' : ''}`} />
            Run checks
          </Button>
        </div>
        {diagChecks ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">Status</TableHead>
                <TableHead>Check</TableHead>
                <TableHead>Latency</TableHead>
                <TableHead>Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {diagChecks.map((check) => (
                <TableRow key={check.name}>
                  <TableCell>
                    {check.ok ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                    ) : (
                      <XCircle className="h-4 w-4 text-red-600" />
                    )}
                  </TableCell>
                  <TableCell className="font-medium">{check.name}</TableCell>
                  <TableCell>{check.ms !== null ? `${check.ms} ms` : '—'}</TableCell>
                  <TableCell className="text-muted-foreground text-sm">{check.detail}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="text-sm text-muted-foreground">
            Click "Run checks" to probe DB, loopback HTTP, WebSocket proxy, and active broker
            reachability.
          </p>
        )}
      </Section>

      {/* Recent errors */}
      <Section
        icon={AlertCircle}
        title="Errors"
        description="Browse the tail of log/errors.jsonl, grouped by fingerprint or as a chronological list. Browser errors land here too."
      >
        {errorStats ? (
          <div className="flex flex-wrap gap-2 mb-4">
            <Badge variant="secondary">Total: {errorStats.total}</Badge>
            <Badge variant="secondary">Last 24h: {errorStats.last_24h}</Badge>
            <Badge variant="secondary">Last 1h: {errorStats.last_1h}</Badge>
            {Object.entries(errorStats.by_level).map(([lvl, count]) => (
              <Badge key={lvl} variant="outline">
                {lvl}: {count}
              </Badge>
            ))}
          </div>
        ) : null}

        <div className="inline-flex rounded-md border bg-background p-0.5 mb-4">
          <button
            type="button"
            onClick={() => setErrorView('grouped')}
            className={`px-3 py-1 text-sm rounded ${errorView === 'grouped' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}
          >
            Grouped ({groups.length})
          </button>
          <button
            type="button"
            onClick={() => setErrorView('recent')}
            className={`px-3 py-1 text-sm rounded ${errorView === 'recent' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}
          >
            Recent ({errors.length})
          </button>
        </div>

        {errorView === 'grouped' ? (
          groups.length === 0 ? (
            <p className="text-sm text-muted-foreground">No errors recorded.</p>
          ) : (
            <div className="space-y-2">
              {groups.map((group) => {
                const isOpen = expandedGroup === group.fingerprint
                const sample = group.sample
                const exc = Array.isArray(sample.exception)
                  ? sample.exception.join('')
                  : sample.exception || ''
                return (
                  <div key={group.fingerprint} className="border rounded-md overflow-hidden">
                    <button
                      type="button"
                      className="w-full text-left px-3 py-2 flex items-start gap-2 hover:bg-muted/50"
                      onClick={() => setExpandedGroup(isOpen ? null : group.fingerprint)}
                    >
                      {isOpen ? (
                        <ChevronDown className="h-4 w-4 mt-0.5 shrink-0" />
                      ) : (
                        <ChevronRight className="h-4 w-4 mt-0.5 shrink-0" />
                      )}
                      <Badge variant="outline" className="shrink-0">
                        ×{group.count}
                      </Badge>
                      <Badge
                        variant={
                          group.level === 'CRITICAL' || group.level === 'ERROR'
                            ? 'destructive'
                            : 'secondary'
                        }
                        className="shrink-0"
                      >
                        {group.level ?? '?'}
                      </Badge>
                      <span className="text-xs shrink-0 font-mono text-muted-foreground">
                        {group.module ?? group.logger ?? '?'}
                      </span>
                      <span className="text-sm flex-1 truncate">{sample.message}</span>
                      <span className="text-xs text-muted-foreground shrink-0 hidden md:inline font-mono">
                        last: {group.last_seen}
                      </span>
                    </button>
                    {isOpen ? (
                      <div className="border-t bg-muted/30 px-3 py-2 space-y-2">
                        <div className="text-xs grid grid-cols-1 md:grid-cols-3 gap-2">
                          <div>
                            <span className="text-muted-foreground">Fingerprint:</span>{' '}
                            <span className="font-mono">{group.fingerprint}</span>
                          </div>
                          <div>
                            <span className="text-muted-foreground">First seen:</span>{' '}
                            <span className="font-mono">{group.first_seen ?? '—'}</span>
                          </div>
                          <div>
                            <span className="text-muted-foreground">Logger:</span>{' '}
                            <span className="font-mono break-all">{group.logger ?? '—'}</span>
                          </div>
                        </div>
                        {exc ? (
                          <pre className="text-xs whitespace-pre-wrap break-all max-h-80 overflow-auto bg-background border rounded p-2">
                            {exc}
                          </pre>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </div>
          )
        ) : null}

        {errorView === 'recent' ? (
          <>
            <div className="flex flex-wrap items-center gap-2 mb-4">
              <select
                value={errorLevelFilter}
                onChange={(e) => setErrorLevelFilter(e.target.value)}
                className="h-9 px-3 text-sm rounded-md border border-input bg-background"
              >
                {LEVEL_OPTIONS.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt || 'All levels'}
                  </option>
                ))}
              </select>
              <Input
                placeholder="Search message or exception"
                value={errorQuery}
                onChange={(e) => setErrorQuery(e.target.value.slice(0, 200))}
                className="max-w-sm"
              />
              <Button size="sm" variant="outline" onClick={reloadErrors}>
                Apply
              </Button>
            </div>

            {filteredErrors.length === 0 ? (
              <p className="text-sm text-muted-foreground">No errors recorded.</p>
            ) : (
              <div className="space-y-2">
                {filteredErrors
                  .slice()
                  .reverse()
                  .map((err, idx) => {
                    const isOpen = expandedError === idx
                    const exc = Array.isArray(err.exception)
                      ? err.exception.join('')
                      : err.exception || ''
                    return (
                      <div
                        key={`${err.ts ?? ''}-${idx}`}
                        className="border rounded-md overflow-hidden"
                      >
                        <button
                          type="button"
                          className="w-full text-left px-3 py-2 flex items-start gap-2 hover:bg-muted/50"
                          onClick={() => setExpandedError(isOpen ? null : idx)}
                        >
                          {isOpen ? (
                            <ChevronDown className="h-4 w-4 mt-0.5 shrink-0" />
                          ) : (
                            <ChevronRight className="h-4 w-4 mt-0.5 shrink-0" />
                          )}
                          <Badge
                            variant={
                              err.level === 'CRITICAL' || err.level === 'ERROR'
                                ? 'destructive'
                                : 'secondary'
                            }
                            className="shrink-0"
                          >
                            {err.level ?? '?'}
                          </Badge>
                          <span className="text-xs text-muted-foreground shrink-0 font-mono">
                            {err.ts}
                          </span>
                          <span className="text-xs shrink-0 font-mono text-muted-foreground">
                            {err.module ?? '?'}
                          </span>
                          <span className="text-sm flex-1 truncate">{err.message}</span>
                        </button>
                        {isOpen ? (
                          <div className="border-t bg-muted/30 px-3 py-2 space-y-2">
                            <div className="text-xs grid grid-cols-1 md:grid-cols-3 gap-2">
                              <div>
                                <span className="text-muted-foreground">Logger:</span>{' '}
                                <span className="font-mono">{err.logger ?? '—'}</span>
                              </div>
                              <div>
                                <span className="text-muted-foreground">File:</span>{' '}
                                <span className="font-mono break-all">{err.file ?? '—'}</span>
                              </div>
                              {err.request ? (
                                <div>
                                  <span className="text-muted-foreground">Request:</span>{' '}
                                  <span className="font-mono">
                                    {err.request.method} {err.request.path}
                                  </span>
                                </div>
                              ) : null}
                            </div>
                            {exc ? (
                              <pre className="text-xs whitespace-pre-wrap break-all max-h-80 overflow-auto bg-background border rounded p-2">
                                {exc}
                              </pre>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    )
                  })}
              </div>
            )}
          </>
        ) : null}
      </Section>
    </div>
  )
}

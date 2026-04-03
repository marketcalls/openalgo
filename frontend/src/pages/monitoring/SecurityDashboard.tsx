import {
  AlertTriangle,
  ArrowLeft,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Ban,
  Eye,
  EyeOff,
  Save,
  Shield,
  Trash2,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { webClient } from '@/api/client'
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
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface SecuritySettings {
  auto_ban_enabled: boolean
  '404_threshold': number
  '404_ban_duration': number
  api_threshold: number
  api_ban_duration: number
  repeat_offender_limit: number
}

interface SecurityStats {
  total_bans: number
  permanent_bans: number
  temporary_bans: number
  suspicious_ips: number
  near_threshold: number
}

interface BannedIP {
  ip_address: string
  ban_reason: string
  banned_at: string
  expires_at: string
  is_permanent: boolean
  ban_count: number
  created_by: string
}

interface SuspiciousIP {
  ip_address: string
  error_count: number
  first_error_at: string
  last_error_at: string
  paths_attempted: string
}

interface APIAbuseIP {
  ip_address: string
  attempt_count: number
  first_attempt_at: string
  last_attempt_at: string
  api_keys_tried: string
}

export default function SecurityDashboard() {
  const [isLoading, setIsLoading] = useState(true)
  const [settings, setSettings] = useState<SecuritySettings>({
    auto_ban_enabled: false,
    '404_threshold': 100,
    '404_ban_duration': 0,
    api_threshold: 100,
    api_ban_duration: 0,
    repeat_offender_limit: 2,
  })
  const [stats, setStats] = useState<SecurityStats>({
    total_bans: 0,
    permanent_bans: 0,
    temporary_bans: 0,
    suspicious_ips: 0,
    near_threshold: 0,
  })
  const [bannedIPs, setBannedIPs] = useState<BannedIP[]>([])
  const [suspiciousIPs, setSuspiciousIPs] = useState<SuspiciousIP[]>([])
  const [apiAbuseIPs, setAPIAbuseIPs] = useState<APIAbuseIP[]>([])

  // Settings form state
  const [formSettings, setFormSettings] = useState<SecuritySettings>(settings)
  const [isSavingSettings, setIsSavingSettings] = useState(false)

  // Manual ban form state
  const [banIP, setBanIP] = useState('')
  const [banReason, setBanReason] = useState('')
  const [banDuration, setBanDuration] = useState('24')
  const [isBanning, setIsBanning] = useState(false)

  // Host ban form state
  const [banHost, setBanHost] = useState('')
  const [hostPermanent, setHostPermanent] = useState(false)
  const [isBanningHost, setIsBanningHost] = useState(false)

  // Unban dialog state
  const [unbanIP, setUnbanIP] = useState<string | null>(null)
  const [isUnbanning, setIsUnbanning] = useState(false)

  // Clear tracker dialog state
  const [clearIP, setClearIP] = useState<string | null>(null)
  const [isClearing, setIsClearing] = useState(false)

  // Expanded rows state
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set())
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set())

  // Sorting state
  type SortDir = 'asc' | 'desc'
  const [bannedSort, setBannedSort] = useState<{ key: string; dir: SortDir }>({
    key: 'banned_at',
    dir: 'desc',
  })
  const [suspiciousSort, setSuspiciousSort] = useState<{ key: string; dir: SortDir }>({
    key: 'error_count',
    dir: 'desc',
  })
  const [apiSort, setApiSort] = useState<{ key: string; dir: SortDir }>({
    key: 'attempt_count',
    dir: 'desc',
  })

  const toggleSort = (
    current: { key: string; dir: SortDir },
    setter: (v: { key: string; dir: SortDir }) => void,
    key: string
  ) => {
    if (current.key === key) {
      setter({ key, dir: current.dir === 'asc' ? 'desc' : 'asc' })
    } else {
      setter({ key, dir: 'desc' })
    }
  }

  const SortIcon = ({ column, sort }: { column: string; sort: { key: string; dir: SortDir } }) => {
    if (sort.key !== column)
      return <ArrowUpDown className="h-3 w-3 ml-1 inline opacity-40" />
    return sort.dir === 'asc' ? (
      <ArrowUp className="h-3 w-3 ml-1 inline" />
    ) : (
      <ArrowDown className="h-3 w-3 ml-1 inline" />
    )
  }

  // Parse DD-MM-YYYY HH:MM:SS AM/PM to comparable value
  const parseDate = (dateStr: string): number => {
    if (!dateStr || dateStr === 'Unknown' || dateStr === 'Permanent') return 0
    const [datePart, timePart, ampm] = dateStr.split(' ')
    if (!datePart || !timePart) return 0
    const [dd, mm, yyyy] = datePart.split('-')
    const [hh, min, ss] = timePart.split(':')
    let hour = parseInt(hh, 10)
    if (ampm?.toUpperCase() === 'PM' && hour !== 12) hour += 12
    if (ampm?.toUpperCase() === 'AM' && hour === 12) hour = 0
    return new Date(
      parseInt(yyyy, 10),
      parseInt(mm, 10) - 1,
      parseInt(dd, 10),
      hour,
      parseInt(min, 10),
      parseInt(ss, 10)
    ).getTime()
  }

  const sortedBannedIPs = useMemo(() => {
    const sorted = [...bannedIPs]
    const { key, dir } = bannedSort
    sorted.sort((a, b) => {
      let cmp = 0
      if (key === 'ip_address' || key === 'ban_reason' || key === 'created_by') {
        cmp = (a[key as keyof BannedIP] as string).localeCompare(
          b[key as keyof BannedIP] as string
        )
      } else if (key === 'ban_count') {
        cmp = a.ban_count - b.ban_count
      } else if (key === 'banned_at') {
        cmp = parseDate(a.banned_at) - parseDate(b.banned_at)
      } else if (key === 'expires_at') {
        const aVal = a.is_permanent ? Number.MAX_SAFE_INTEGER : parseDate(a.expires_at)
        const bVal = b.is_permanent ? Number.MAX_SAFE_INTEGER : parseDate(b.expires_at)
        cmp = aVal - bVal
      }
      return dir === 'asc' ? cmp : -cmp
    })
    return sorted
  }, [bannedIPs, bannedSort])

  const sortedSuspiciousIPs = useMemo(() => {
    const sorted = [...suspiciousIPs]
    const { key, dir } = suspiciousSort
    sorted.sort((a, b) => {
      let cmp = 0
      if (key === 'ip_address') {
        cmp = a.ip_address.localeCompare(b.ip_address)
      } else if (key === 'error_count') {
        cmp = a.error_count - b.error_count
      } else if (key === 'first_error_at') {
        cmp = parseDate(a.first_error_at) - parseDate(b.first_error_at)
      } else if (key === 'last_error_at') {
        cmp = parseDate(a.last_error_at) - parseDate(b.last_error_at)
      }
      return dir === 'asc' ? cmp : -cmp
    })
    return sorted
  }, [suspiciousIPs, suspiciousSort])

  const sortedAPIAbuseIPs = useMemo(() => {
    const sorted = [...apiAbuseIPs]
    const { key, dir } = apiSort
    sorted.sort((a, b) => {
      let cmp = 0
      if (key === 'ip_address') {
        cmp = a.ip_address.localeCompare(b.ip_address)
      } else if (key === 'attempt_count') {
        cmp = a.attempt_count - b.attempt_count
      } else if (key === 'first_attempt_at') {
        cmp = parseDate(a.first_attempt_at) - parseDate(b.first_attempt_at)
      } else if (key === 'last_attempt_at') {
        cmp = parseDate(a.last_attempt_at) - parseDate(b.last_attempt_at)
      }
      return dir === 'asc' ? cmp : -cmp
    })
    return sorted
  }, [apiAbuseIPs, apiSort])

  useEffect(() => {
    fetchDashboardData()
    fetchStats()
    // Refresh stats every 30 seconds
    const interval = setInterval(fetchStats, 30000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchDashboardData = async () => {
    try {
      const response = await webClient.get<{
        banned_ips: BannedIP[]
        suspicious_ips: SuspiciousIP[]
        api_abuse_ips: APIAbuseIP[]
        security_settings: SecuritySettings
      }>('/security/api/data')

      setBannedIPs(Array.isArray(response.data.banned_ips) ? response.data.banned_ips : [])
      setSuspiciousIPs(
        Array.isArray(response.data.suspicious_ips) ? response.data.suspicious_ips : []
      )
      setAPIAbuseIPs(Array.isArray(response.data.api_abuse_ips) ? response.data.api_abuse_ips : [])

      if (response.data.security_settings) {
        setSettings(response.data.security_settings)
        setFormSettings(response.data.security_settings)
      }
    } catch (error) {
      showToast.error('Failed to load security data', 'monitoring')
    } finally {
      setIsLoading(false)
    }
  }

  const fetchStats = async () => {
    try {
      const response = await webClient.get<SecurityStats>('/security/stats')
      setStats(response.data)
    } catch (error) {
    }
  }

  const handleSaveSettings = async () => {
    setIsSavingSettings(true)
    try {
      const response = await webClient.post<{ success: boolean; message: string }>(
        '/security/settings',
        {
          auto_ban_enabled: formSettings.auto_ban_enabled,
          threshold_404: formSettings['404_threshold'],
          ban_duration_404: formSettings['404_ban_duration'],
          threshold_api: formSettings.api_threshold,
          ban_duration_api: formSettings.api_ban_duration,
          repeat_offender_limit: formSettings.repeat_offender_limit,
        }
      )

      if (response.data.success) {
        showToast.success(response.data.message || 'Settings saved successfully', 'monitoring')
        setSettings(formSettings)
        fetchStats()
      } else {
        showToast.error(response.data.message || 'Failed to save settings', 'monitoring')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string } } }
      showToast.error(err.response?.data?.error || 'Failed to save settings', 'monitoring')
    } finally {
      setIsSavingSettings(false)
    }
  }

  const handleBanIP = async () => {
    if (!banIP.trim()) {
      showToast.error('Please enter an IP address', 'monitoring')
      return
    }

    setIsBanning(true)
    try {
      const response = await webClient.post<{ success: boolean; message: string; error?: string }>(
        '/security/ban',
        {
          ip_address: banIP.trim(),
          reason: banReason.trim() || 'Manual ban',
          permanent: banDuration === 'permanent',
          duration_hours: banDuration === 'permanent' ? 0 : parseInt(banDuration, 10),
        }
      )

      if (response.data.success) {
        showToast.success(response.data.message || 'IP banned successfully', 'monitoring')
        setBanIP('')
        setBanReason('')
        setBanDuration('24')
        fetchDashboardData()
        fetchStats()
      } else {
        showToast.error(response.data.error || 'Failed to ban IP', 'monitoring')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string } } }
      showToast.error(err.response?.data?.error || 'Failed to ban IP', 'monitoring')
    } finally {
      setIsBanning(false)
    }
  }

  const handleBanHost = async () => {
    if (!banHost.trim()) {
      showToast.error('Please enter a host/domain', 'monitoring')
      return
    }

    setIsBanningHost(true)
    try {
      const response = await webClient.post<{ success: boolean; message: string; error?: string }>(
        '/security/ban-host',
        {
          host: banHost.trim(),
          reason: `Banned host: ${banHost.trim()}`,
          permanent: hostPermanent,
        }
      )

      if (response.data.success) {
        showToast.success(response.data.message || 'Host banned successfully', 'monitoring')
        setBanHost('')
        setHostPermanent(false)
        fetchDashboardData()
        fetchStats()
      } else {
        showToast.error(response.data.error || 'Failed to ban host', 'monitoring')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string; suggestion?: string } } }
      showToast.error(err.response?.data?.error || 'Failed to ban host', 'monitoring')
    } finally {
      setIsBanningHost(false)
    }
  }

  const handleUnban = async () => {
    if (!unbanIP) return

    setIsUnbanning(true)
    try {
      const response = await webClient.post<{ success: boolean; message: string; error?: string }>(
        '/security/unban',
        {
          ip_address: unbanIP,
        }
      )

      if (response.data.success) {
        showToast.success(response.data.message || 'IP unbanned successfully', 'monitoring')
        setUnbanIP(null)
        fetchDashboardData()
        fetchStats()
      } else {
        showToast.error(response.data.error || 'Failed to unban IP', 'monitoring')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string } } }
      showToast.error(err.response?.data?.error || 'Failed to unban IP', 'monitoring')
    } finally {
      setIsUnbanning(false)
    }
  }

  const handleClearTracker = async () => {
    if (!clearIP) return

    setIsClearing(true)
    try {
      const response = await webClient.post<{ success: boolean; message: string; error?: string }>(
        '/security/clear-404',
        {
          ip_address: clearIP,
        }
      )

      if (response.data.success) {
        showToast.success(response.data.message || 'Tracker cleared successfully', 'monitoring')
        setClearIP(null)
        fetchDashboardData()
        fetchStats()
      } else {
        showToast.error(response.data.error || 'Failed to clear tracker', 'monitoring')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string } } }
      showToast.error(err.response?.data?.error || 'Failed to clear tracker', 'monitoring')
    } finally {
      setIsClearing(false)
    }
  }

  const handleQuickBan = async (ip: string) => {
    try {
      const response = await webClient.post<{ success: boolean; message: string; error?: string }>(
        '/security/ban',
        {
          ip_address: ip,
          reason: 'Quick ban from dashboard',
          permanent: false,
          duration_hours: 24,
        }
      )

      if (response.data.success) {
        showToast.success(response.data.message || 'IP banned successfully', 'monitoring')
        fetchDashboardData()
        fetchStats()
      } else {
        showToast.error(response.data.error || 'Failed to ban IP', 'monitoring')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string } } }
      showToast.error(err.response?.data?.error || 'Failed to ban IP', 'monitoring')
    }
  }

  const togglePathsExpanded = (ip: string) => {
    setExpandedPaths((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(ip)) {
        newSet.delete(ip)
      } else {
        newSet.add(ip)
      }
      return newSet
    })
  }

  const toggleKeysExpanded = (ip: string) => {
    setExpandedKeys((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(ip)) {
        newSet.delete(ip)
      } else {
        newSet.add(ip)
      }
      return newSet
    })
  }

  const getBadgeVariant = (
    count: number,
    threshold: number
  ): 'default' | 'destructive' | 'secondary' | 'outline' => {
    const ratio = count / threshold
    if (ratio >= 0.8) return 'destructive'
    if (ratio >= 0.5) return 'secondary'
    return 'outline'
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Link to="/dashboard" className="text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Shield className="h-6 w-6" />
            Security Dashboard
          </h1>
        </div>
        <p className="text-muted-foreground">
          Monitor and manage IP bans, suspicious activity, and security settings
        </p>
      </div>

      {/* Security Settings Card */}
      <Card>
        <CardHeader>
          <CardTitle>Security Threshold Settings</CardTitle>
          <CardDescription>Configure auto-ban thresholds and durations</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between mb-6 p-4 rounded-lg border bg-muted/30">
            <div className="space-y-1">
              <Label className="text-base font-semibold">Auto-Ban</Label>
              <p className="text-sm text-muted-foreground">
                {formSettings.auto_ban_enabled
                  ? 'IPs exceeding thresholds will be automatically banned'
                  : 'Automatic banning is disabled — use manual ban only'}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <span
                className={`text-sm font-medium ${!formSettings.auto_ban_enabled ? 'text-foreground' : 'text-muted-foreground'}`}
              >
                Off
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={formSettings.auto_ban_enabled}
                onClick={() =>
                  setFormSettings({
                    ...formSettings,
                    auto_ban_enabled: !formSettings.auto_ban_enabled,
                  })
                }
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
                  formSettings.auto_ban_enabled ? 'bg-destructive' : 'bg-input'
                }`}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-background shadow-lg ring-0 transition duration-200 ease-in-out ${
                    formSettings.auto_ban_enabled ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
              <span
                className={`text-sm font-medium ${formSettings.auto_ban_enabled ? 'text-destructive' : 'text-muted-foreground'}`}
              >
                On
              </span>
            </div>
          </div>
          <div
            className={`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 ${!formSettings.auto_ban_enabled ? 'opacity-50 pointer-events-none' : ''}`}
          >
            <div className="space-y-2">
              <Label>
                404 Error Threshold <span className="text-muted-foreground text-xs">(per day)</span>
              </Label>
              <Input
                type="number"
                value={formSettings['404_threshold']}
                onChange={(e) =>
                  setFormSettings({
                    ...formSettings,
                    '404_threshold': parseInt(e.target.value, 10) || 20,
                  })
                }
                min={1}
                max={1000}
              />
            </div>
            <div className="space-y-2">
              <Label>
                404 Ban Duration <span className="text-muted-foreground text-xs">(hours)</span>
              </Label>
              <Select
                value={String(formSettings['404_ban_duration'])}
                onValueChange={(val) =>
                  setFormSettings({
                    ...formSettings,
                    '404_ban_duration': parseInt(val, 10),
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="24">24 Hours</SelectItem>
                  <SelectItem value="48">48 Hours</SelectItem>
                  <SelectItem value="72">72 Hours</SelectItem>
                  <SelectItem value="168">1 Week</SelectItem>
                  <SelectItem value="720">30 Days</SelectItem>
                  <SelectItem value="8760">1 Year</SelectItem>
                  <SelectItem value="0">Permanent</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>
                Invalid API Threshold{' '}
                <span className="text-muted-foreground text-xs">(per day)</span>
              </Label>
              <Input
                type="number"
                value={formSettings.api_threshold}
                onChange={(e) =>
                  setFormSettings({
                    ...formSettings,
                    api_threshold: parseInt(e.target.value, 10) || 10,
                  })
                }
                min={1}
                max={100}
              />
            </div>
            <div className="space-y-2">
              <Label>
                API Ban Duration <span className="text-muted-foreground text-xs">(hours)</span>
              </Label>
              <Select
                value={String(formSettings.api_ban_duration)}
                onValueChange={(val) =>
                  setFormSettings({
                    ...formSettings,
                    api_ban_duration: parseInt(val, 10),
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="24">24 Hours</SelectItem>
                  <SelectItem value="48">48 Hours</SelectItem>
                  <SelectItem value="72">72 Hours</SelectItem>
                  <SelectItem value="168">1 Week</SelectItem>
                  <SelectItem value="720">30 Days</SelectItem>
                  <SelectItem value="8760">1 Year</SelectItem>
                  <SelectItem value="0">Permanent</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>
                Repeat Offender Limit{' '}
                <span className="text-muted-foreground text-xs">(before permanent)</span>
              </Label>
              <Input
                type="number"
                value={formSettings.repeat_offender_limit}
                onChange={(e) =>
                  setFormSettings({
                    ...formSettings,
                    repeat_offender_limit: parseInt(e.target.value, 10) || 3,
                  })
                }
                min={1}
                max={10}
              />
            </div>
          </div>
          <div className="mt-4 flex items-center justify-between">
            <Button onClick={handleSaveSettings} disabled={isSavingSettings}>
              <Save className="h-4 w-4 mr-2" />
              {isSavingSettings ? 'Saving...' : 'Save Settings'}
            </Button>
          </div>
          <div className="mt-4 text-xs text-muted-foreground space-y-1">
            <p>
              <strong>404 Threshold:</strong> Number of 404 errors per day before auto-ban
            </p>
            <p>
              <strong>API Threshold:</strong> Number of invalid API attempts per day before auto-ban
            </p>
            <p>
              <strong>Repeat Limit:</strong> Number of bans before permanent ban
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-destructive">{stats.total_bans}</p>
            <p className="text-sm text-muted-foreground">Total Bans</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-yellow-500">{stats.permanent_bans}</p>
            <p className="text-sm text-muted-foreground">Permanent Bans</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-blue-500">{stats.suspicious_ips}</p>
            <p className="text-sm text-muted-foreground">Suspicious IPs</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-purple-500">{stats.near_threshold}</p>
            <p className="text-sm text-muted-foreground">Near Threshold</p>
          </CardContent>
        </Card>
      </div>

      {/* Manual Ban Form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Ban className="h-5 w-5" />
            Manual IP Ban
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <Input
              placeholder="IP Address"
              value={banIP}
              onChange={(e) => setBanIP(e.target.value)}
            />
            <Input
              placeholder="Reason"
              value={banReason}
              onChange={(e) => setBanReason(e.target.value)}
            />
            <Select value={banDuration} onValueChange={setBanDuration}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="24">24 Hours</SelectItem>
                <SelectItem value="48">48 Hours</SelectItem>
                <SelectItem value="168">1 Week</SelectItem>
                <SelectItem value="permanent">Permanent</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="destructive" onClick={handleBanIP} disabled={isBanning}>
              {isBanning ? 'Banning...' : 'Ban IP'}
            </Button>
          </div>

          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-background px-2 text-muted-foreground">OR</span>
            </div>
          </div>

          <div>
            <h3 className="text-lg font-semibold mb-2">Ban by Host/Domain</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Input
                placeholder="Host/Domain (e.g., example.com)"
                value={banHost}
                onChange={(e) => setBanHost(e.target.value)}
              />
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="host-permanent"
                  checked={hostPermanent}
                  onCheckedChange={(checked) => setHostPermanent(checked === true)}
                />
                <label
                  htmlFor="host-permanent"
                  className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70"
                >
                  Permanent Ban
                </label>
              </div>
              <Button variant="destructive" onClick={handleBanHost} disabled={isBanningHost}>
                {isBanningHost ? 'Banning...' : 'Ban Host'}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Banned IPs Table */}
      <Card>
        <CardHeader>
          <CardTitle>Banned IPs</CardTitle>
          <CardDescription>{bannedIPs.length} IPs currently banned</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="border rounded-md">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() => toggleSort(bannedSort, setBannedSort, 'ip_address')}
                  >
                    IP Address
                    <SortIcon column="ip_address" sort={bannedSort} />
                  </TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() => toggleSort(bannedSort, setBannedSort, 'ban_reason')}
                  >
                    Reason
                    <SortIcon column="ban_reason" sort={bannedSort} />
                  </TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() => toggleSort(bannedSort, setBannedSort, 'banned_at')}
                  >
                    Banned At
                    <SortIcon column="banned_at" sort={bannedSort} />
                  </TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() => toggleSort(bannedSort, setBannedSort, 'expires_at')}
                  >
                    Expires At
                    <SortIcon column="expires_at" sort={bannedSort} />
                  </TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() => toggleSort(bannedSort, setBannedSort, 'ban_count')}
                  >
                    Ban Count
                    <SortIcon column="ban_count" sort={bannedSort} />
                  </TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() => toggleSort(bannedSort, setBannedSort, 'created_by')}
                  >
                    Created By
                    <SortIcon column="created_by" sort={bannedSort} />
                  </TableHead>
                  <TableHead className="w-[80px]">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedBannedIPs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                      No banned IPs
                    </TableCell>
                  </TableRow>
                ) : (
                  sortedBannedIPs.map((ban) => (
                    <TableRow key={ban.ip_address}>
                      <TableCell className="font-mono">{ban.ip_address}</TableCell>
                      <TableCell>{ban.ban_reason}</TableCell>
                      <TableCell>{ban.banned_at}</TableCell>
                      <TableCell>
                        {ban.is_permanent ? (
                          <Badge variant="destructive">Permanent</Badge>
                        ) : (
                          ban.expires_at
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={ban.ban_count >= 3 ? 'destructive' : 'secondary'}>
                          {ban.ban_count}
                        </Badge>
                      </TableCell>
                      <TableCell>{ban.created_by}</TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-green-600 hover:text-green-600"
                          onClick={() => setUnbanIP(ban.ip_address)}
                        >
                          Unban
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Invalid API Key Attempts Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5" />
            Invalid API Key Attempts
          </CardTitle>
          <CardDescription>{apiAbuseIPs.length} IPs with invalid API attempts</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="border rounded-md">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() => toggleSort(apiSort, setApiSort, 'ip_address')}
                  >
                    IP Address
                    <SortIcon column="ip_address" sort={apiSort} />
                  </TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() => toggleSort(apiSort, setApiSort, 'attempt_count')}
                  >
                    Attempts
                    <SortIcon column="attempt_count" sort={apiSort} />
                  </TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() => toggleSort(apiSort, setApiSort, 'first_attempt_at')}
                  >
                    First Attempt
                    <SortIcon column="first_attempt_at" sort={apiSort} />
                  </TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() => toggleSort(apiSort, setApiSort, 'last_attempt_at')}
                  >
                    Last Attempt
                    <SortIcon column="last_attempt_at" sort={apiSort} />
                  </TableHead>
                  <TableHead>API Keys Tried</TableHead>
                  <TableHead className="w-[80px]">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedAPIAbuseIPs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                      No invalid API key attempts detected
                    </TableCell>
                  </TableRow>
                ) : (
                  sortedAPIAbuseIPs.map((tracker) => (
                    <TableRow
                      key={tracker.ip_address}
                      className={tracker.attempt_count >= 8 ? 'bg-destructive/10' : ''}
                    >
                      <TableCell className="font-mono">{tracker.ip_address}</TableCell>
                      <TableCell>
                        <Badge
                          variant={getBadgeVariant(tracker.attempt_count, settings.api_threshold)}
                        >
                          {tracker.attempt_count}/{settings.api_threshold}
                        </Badge>
                      </TableCell>
                      <TableCell>{tracker.first_attempt_at}</TableCell>
                      <TableCell>{tracker.last_attempt_at}</TableCell>
                      <TableCell>
                        <Collapsible
                          open={expandedKeys.has(tracker.ip_address)}
                          onOpenChange={() => toggleKeysExpanded(tracker.ip_address)}
                        >
                          <CollapsibleTrigger className="text-sm cursor-pointer hover:underline flex items-center gap-1">
                            {expandedKeys.has(tracker.ip_address) ? (
                              <EyeOff className="h-3 w-3" />
                            ) : (
                              <Eye className="h-3 w-3" />
                            )}
                            View Keys (Hashed)
                          </CollapsibleTrigger>
                          <CollapsibleContent>
                            <div className="text-xs font-mono mt-2 max-h-32 overflow-y-auto p-2 bg-muted rounded">
                              {tracker.api_keys_tried}
                            </div>
                          </CollapsibleContent>
                        </Collapsible>
                      </TableCell>
                      <TableCell>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleQuickBan(tracker.ip_address)}
                        >
                          Ban
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Suspicious IPs Table (404 Tracker) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5" />
            Suspicious IPs (404 Tracker)
          </CardTitle>
          <CardDescription>{suspiciousIPs.length} IPs with 404 errors tracked</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="border rounded-md">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() => toggleSort(suspiciousSort, setSuspiciousSort, 'ip_address')}
                  >
                    IP Address
                    <SortIcon column="ip_address" sort={suspiciousSort} />
                  </TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() => toggleSort(suspiciousSort, setSuspiciousSort, 'error_count')}
                  >
                    404 Count
                    <SortIcon column="error_count" sort={suspiciousSort} />
                  </TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() =>
                      toggleSort(suspiciousSort, setSuspiciousSort, 'first_error_at')
                    }
                  >
                    First Error
                    <SortIcon column="first_error_at" sort={suspiciousSort} />
                  </TableHead>
                  <TableHead
                    className="cursor-pointer select-none"
                    onClick={() =>
                      toggleSort(suspiciousSort, setSuspiciousSort, 'last_error_at')
                    }
                  >
                    Last Error
                    <SortIcon column="last_error_at" sort={suspiciousSort} />
                  </TableHead>
                  <TableHead>Sample Paths</TableHead>
                  <TableHead className="w-[120px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedSuspiciousIPs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                      No suspicious IPs detected
                    </TableCell>
                  </TableRow>
                ) : (
                  sortedSuspiciousIPs.map((tracker) => (
                    <TableRow
                      key={tracker.ip_address}
                      className={tracker.error_count >= 15 ? 'bg-destructive/10' : ''}
                    >
                      <TableCell className="font-mono">{tracker.ip_address}</TableCell>
                      <TableCell>
                        <Badge
                          variant={getBadgeVariant(tracker.error_count, settings['404_threshold'])}
                        >
                          {tracker.error_count}/{settings['404_threshold']}
                        </Badge>
                      </TableCell>
                      <TableCell>{tracker.first_error_at}</TableCell>
                      <TableCell>{tracker.last_error_at}</TableCell>
                      <TableCell>
                        <Collapsible
                          open={expandedPaths.has(tracker.ip_address)}
                          onOpenChange={() => togglePathsExpanded(tracker.ip_address)}
                        >
                          <CollapsibleTrigger className="text-sm cursor-pointer hover:underline flex items-center gap-1">
                            {expandedPaths.has(tracker.ip_address) ? (
                              <EyeOff className="h-3 w-3" />
                            ) : (
                              <Eye className="h-3 w-3" />
                            )}
                            View Paths
                          </CollapsibleTrigger>
                          <CollapsibleContent>
                            <div className="text-xs font-mono mt-2 max-h-32 overflow-y-auto p-2 bg-muted rounded">
                              {tracker.paths_attempted}
                            </div>
                          </CollapsibleContent>
                        </Collapsible>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => handleQuickBan(tracker.ip_address)}
                          >
                            Ban
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setClearIP(tracker.ip_address)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Unban Confirmation Dialog */}
      <AlertDialog open={!!unbanIP} onOpenChange={() => setUnbanIP(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirm Unban</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to unban IP address{' '}
              <span className="font-mono font-bold">{unbanIP}</span>?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleUnban}
              disabled={isUnbanning}
              className="bg-green-600 hover:bg-green-700"
            >
              {isUnbanning ? 'Unbanning...' : 'Unban'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Clear Tracker Confirmation Dialog */}
      <AlertDialog open={!!clearIP} onOpenChange={() => setClearIP(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Clear 404 Tracker</AlertDialogTitle>
            <AlertDialogDescription>
              Clear 404 tracking data for IP address{' '}
              <span className="font-mono font-bold">{clearIP}</span>?
              <br />
              <span className="text-yellow-600">
                This will reset the 404 error count for this IP.
              </span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleClearTracker}
              disabled={isClearing}
              className="bg-yellow-600 hover:bg-yellow-700"
            >
              {isClearing ? 'Clearing...' : 'Clear'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

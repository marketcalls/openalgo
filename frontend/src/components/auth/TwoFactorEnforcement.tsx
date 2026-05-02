import { Loader2, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { webClient } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { showToast } from '@/utils/toast'

interface TwoFactorStatus {
  totp_enabled: boolean
  totp_required_for_login: boolean
  totp_required_for_mcp: boolean
  totp_required_for_password_reset: boolean
  last_totp_verified_at: string | null
}

type PurposeKey =
  | 'totp_required_for_login'
  | 'totp_required_for_mcp'
  | 'totp_required_for_password_reset'

const PURPOSES: { key: PurposeKey; label: string; help: string }[] = [
  {
    key: 'totp_required_for_login',
    label: 'Dashboard sign-in',
    help: 'Require a 6-digit code after password on every login.',
  },
  {
    key: 'totp_required_for_mcp',
    label: 'Remote MCP authorization',
    help: 'Require a fresh code at the OAuth consent screen when an MCP client requests order-placement scope.',
  },
  {
    key: 'totp_required_for_password_reset',
    label: 'Password reset',
    help: 'Disable the email reset path; force the authenticator app for every password reset.',
  },
]

export default function TwoFactorEnforcement() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<TwoFactorStatus | null>(null)
  const [draft, setDraft] = useState<Omit<TwoFactorStatus, 'last_totp_verified_at'>>({
    totp_enabled: false,
    totp_required_for_login: false,
    totp_required_for_mcp: false,
    totp_required_for_password_reset: false,
  })
  const [totpCode, setTotpCode] = useState('')

  useEffect(() => {
    fetchStatus()
  }, [])

  const fetchStatus = async () => {
    setLoading(true)
    try {
      const r = await webClient.get<TwoFactorStatus & { status?: string }>('/auth/2fa/status')
      setStatus(r.data)
      setDraft({
        totp_enabled: r.data.totp_enabled,
        totp_required_for_login: r.data.totp_required_for_login,
        totp_required_for_mcp: r.data.totp_required_for_mcp,
        totp_required_for_password_reset: r.data.totp_required_for_password_reset,
      })
    } catch {
      showToast.error('Failed to load 2FA settings', 'system')
    } finally {
      setLoading(false)
    }
  }

  const isDirty =
    !!status &&
    (draft.totp_enabled !== status.totp_enabled ||
      draft.totp_required_for_login !== status.totp_required_for_login ||
      draft.totp_required_for_mcp !== status.totp_required_for_mcp ||
      draft.totp_required_for_password_reset !== status.totp_required_for_password_reset)

  const allOn =
    draft.totp_enabled &&
    draft.totp_required_for_login &&
    draft.totp_required_for_mcp &&
    draft.totp_required_for_password_reset

  const setMaster = (enabled: boolean) => {
    setDraft((prev) =>
      enabled
        ? { ...prev, totp_enabled: true }
        : {
            totp_enabled: false,
            totp_required_for_login: false,
            totp_required_for_mcp: false,
            totp_required_for_password_reset: false,
          }
    )
  }

  const setAll = (on: boolean) => {
    setDraft({
      totp_enabled: on,
      totp_required_for_login: on,
      totp_required_for_mcp: on,
      totp_required_for_password_reset: on,
    })
  }

  const setPurpose = (key: PurposeKey, value: boolean) => {
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  const handleSave = async () => {
    if (!totpCode || totpCode.length !== 6) {
      showToast.error('Enter your 6-digit authenticator code to confirm.', 'system')
      return
    }
    setSaving(true)
    try {
      const body = { ...draft, totp_code: totpCode }
      await webClient.post('/auth/2fa/configure', body)
      showToast.success('2FA settings updated.', 'system')
      setTotpCode('')
      await fetchStatus()
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { message?: string } } })?.response?.data?.message ||
        'Failed to update 2FA settings.'
      showToast.error(message, 'system')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-6">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5" />
          2FA Enforcement
        </CardTitle>
        <CardDescription>
          Choose where 2FA is required. Default is off — when on, pick which purposes.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Master switch */}
        <div className="flex items-start justify-between gap-4 rounded-lg border p-4">
          <div className="flex-1">
            <Label className="font-semibold">Enable 2FA</Label>
            <p className="text-sm text-muted-foreground mt-1">
              Master switch. When off, every per-purpose toggle below is ignored and the install
              behaves as it did before this feature.
            </p>
          </div>
          <Switch checked={draft.totp_enabled} onCheckedChange={setMaster} />
        </div>

        {/* Per-purpose toggles */}
        {draft.totp_enabled ? (
          <div className="space-y-3 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">Apply 2FA to:</span>
              <button
                type="button"
                className="text-xs text-primary hover:underline"
                onClick={() => setAll(!allOn)}
              >
                {allOn ? 'Clear all' : 'Select all'}
              </button>
            </div>
            {PURPOSES.map((p) => (
              <div key={p.key} className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <Label className="font-medium">{p.label}</Label>
                  <p className="text-xs text-muted-foreground mt-0.5">{p.help}</p>
                </div>
                <Switch
                  checked={Boolean(draft[p.key])}
                  onCheckedChange={(v) => setPurpose(p.key, v)}
                />
              </div>
            ))}
          </div>
        ) : null}

        {/* TOTP confirmation */}
        {isDirty ? (
          <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-4 dark:bg-amber-950/30">
            <Label htmlFor="confirm-totp" className="text-sm font-semibold">
              Confirm with TOTP code
            </Label>
            <p className="text-xs text-muted-foreground">
              Enter the current 6-digit code from your authenticator app to apply this change.
              Required whether you are turning 2FA on or off.
            </p>
            <Input
              id="confirm-totp"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              pattern="[0-9]{6}"
              placeholder="123456"
              value={totpCode}
              onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              className="font-mono text-center tracking-widest max-w-xs"
            />
            <div className="flex gap-2 pt-1">
              <Button onClick={handleSave} disabled={saving || totpCode.length !== 6}>
                {saving ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
                Save 2FA settings
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  if (status) {
                    setDraft({
                      totp_enabled: status.totp_enabled,
                      totp_required_for_login: status.totp_required_for_login,
                      totp_required_for_mcp: status.totp_required_for_mcp,
                      totp_required_for_password_reset: status.totp_required_for_password_reset,
                    })
                  }
                  setTotpCode('')
                }}
                disabled={saving}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : null}

        {status?.last_totp_verified_at ? (
          <p className="text-xs text-muted-foreground">
            Last TOTP verification: {new Date(status.last_totp_verified_at).toLocaleString()}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

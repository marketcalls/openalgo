/**
 * Webhook & Security dialog for a Strategy v2.
 *
 * Sections:
 *   1. URL — copy-able webhook endpoint
 *   2. Signing method — NONE | BODY_SECRET | HMAC_SHA256 | BOTH
 *   3. One-time secret display (only on creation / rotation)
 *   4. Replay window + IP allowlist config
 *   5. TradingView template generator (depends on signing method)
 *   6. Test webhook button (dry-run)
 *   7. Rotate secrets (destructive — requires confirmation)
 */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

import { strategyV2Api } from '@/api/strategy_v2'
import type { SigningMethod, StrategyV2 } from '@/types/strategy_v2'

interface Props {
  strategy: StrategyV2
  oneTimeSecret: { webhook_secret?: string; webhook_hmac_key?: string } | null
  onClose: () => void
  onUpdated: (s: StrategyV2) => void
  onRotated: (secrets: { webhook_secret?: string; webhook_hmac_key?: string } | null) => void
}

export default function StrategyV2WebhookDialog({
  strategy,
  oneTimeSecret,
  onClose,
  onUpdated,
  onRotated,
}: Props) {
  const [method, setMethod] = useState<SigningMethod>(strategy.webhook_signing_method)
  const [replay, setReplay] = useState<number>(strategy.webhook_replay_window_seconds)
  const [allowlist, setAllowlist] = useState<string>(
    strategy.webhook_ip_allowlist?.join('\n') ?? ''
  )
  const [testPayload, setTestPayload] = useState<string>(buildTemplate(strategy, method, oneTimeSecret))
  const [testResult, setTestResult] = useState<string>('')
  const [rotateConfirm, setRotateConfirm] = useState<string>('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setTestPayload(buildTemplate(strategy, method, oneTimeSecret))
  }, [strategy, method, oneTimeSecret])

  const url = strategyV2Api.webhookUrl(strategy.webhook_id)

  const onSaveConfig = async () => {
    setBusy(true)
    try {
      const cidrs = allowlist
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean)
      const r = await strategyV2Api.update(strategy.id, {
        webhook_signing_method: method,
        webhook_replay_window_seconds: replay,
        webhook_ip_allowlist: cidrs.length ? cidrs : null,
      })
      onUpdated(r.strategy)
      toast.success('Webhook config saved')
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      toast.error(e?.response?.data?.message ?? 'Failed to save webhook config')
      console.error(err)
    } finally {
      setBusy(false)
    }
  }

  const onRotate = async () => {
    if (rotateConfirm !== strategy.name) {
      toast.error('Type the strategy name exactly to confirm')
      return
    }
    setBusy(true)
    try {
      const r = await strategyV2Api.rotateWebhook(strategy.id, rotateConfirm)
      onUpdated(r.strategy)
      onRotated({
        webhook_secret: r.strategy.webhook_secret,
        webhook_hmac_key: r.strategy.webhook_hmac_key,
      })
      toast.success('Secrets rotated. Save the new values now.')
      setRotateConfirm('')
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: string } } }
      toast.error(e?.response?.data?.message ?? 'Rotation failed')
    } finally {
      setBusy(false)
    }
  }

  const onTest = async () => {
    setTestResult('Running…')
    try {
      const parsed = JSON.parse(testPayload || '{}')
      const r = await strategyV2Api.testWebhook(strategy.id, parsed)
      setTestResult(JSON.stringify(r, null, 2))
    } catch (err: unknown) {
      const e = err as { response?: { data?: unknown }; message?: string }
      setTestResult(JSON.stringify(e?.response?.data ?? { error: e?.message }, null, 2))
    }
  }

  const copy = (s: string) => {
    navigator.clipboard.writeText(s)
    toast.success('Copied')
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Webhook & Security</DialogTitle>
          <DialogDescription>
            Configure the secret method, replay window, and IP allowlist.
            Test the endpoint with a dry-run before going live.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="config">
          <TabsList>
            <TabsTrigger value="config">Configuration</TabsTrigger>
            <TabsTrigger value="template">TradingView Template</TabsTrigger>
            <TabsTrigger value="test">Test</TabsTrigger>
            <TabsTrigger value="rotate">Rotate</TabsTrigger>
          </TabsList>

          {/* ---------- Configuration ---------- */}
          <TabsContent value="config" className="space-y-4">
            <div className="space-y-1">
              <Label>Webhook URL</Label>
              <div className="flex gap-2">
                <Input value={url} readOnly className="font-mono text-xs" />
                <Button variant="outline" onClick={() => copy(url)}>
                  Copy
                </Button>
              </div>
            </div>

            <div className="space-y-1">
              <Label>Signing Method</Label>
              <Select value={method} onValueChange={(v: SigningMethod) => setMethod(v)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="NONE">NONE — URL secret only</SelectItem>
                  <SelectItem value="BODY_SECRET">BODY_SECRET — TradingView</SelectItem>
                  <SelectItem value="HMAC_SHA256">HMAC_SHA256 — Python / Amibroker</SelectItem>
                  <SelectItem value="BOTH">BOTH — accept either</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                TradingView cannot set custom HTTP headers — use BODY_SECRET there.
                Python/Amibroker can use HMAC_SHA256 over the raw request body.
              </p>
            </div>

            {oneTimeSecret && (oneTimeSecret.webhook_secret || oneTimeSecret.webhook_hmac_key) && (
              <div className="border-2 border-amber-500/50 bg-amber-500/10 rounded-md p-3 space-y-2">
                <p className="text-sm font-medium">
                  Save these now — they will not be displayed again.
                </p>
                {oneTimeSecret.webhook_secret && (
                  <div className="space-y-1">
                    <Label className="text-xs">Body Secret</Label>
                    <div className="flex gap-2">
                      <Input
                        readOnly
                        value={oneTimeSecret.webhook_secret}
                        className="font-mono text-xs"
                      />
                      <Button variant="outline" onClick={() => copy(oneTimeSecret.webhook_secret!)}>
                        Copy
                      </Button>
                    </div>
                  </div>
                )}
                {oneTimeSecret.webhook_hmac_key && (
                  <div className="space-y-1">
                    <Label className="text-xs">HMAC Key</Label>
                    <div className="flex gap-2">
                      <Input
                        readOnly
                        value={oneTimeSecret.webhook_hmac_key}
                        className="font-mono text-xs"
                      />
                      <Button variant="outline" onClick={() => copy(oneTimeSecret.webhook_hmac_key!)}>
                        Copy
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label>Replay window (seconds, 0 = off)</Label>
                <Input
                  type="number"
                  min={0}
                  max={3600}
                  value={replay}
                  onChange={(e) => setReplay(Number(e.target.value) || 0)}
                />
                <p className="text-xs text-muted-foreground">
                  Body must include <code>ts</code> field within ±N seconds. 300 recommended for HMAC users.
                </p>
              </div>
              <div className="space-y-1">
                <Label>IP allowlist (one CIDR per line)</Label>
                <Textarea
                  rows={4}
                  value={allowlist}
                  onChange={(e) => setAllowlist(e.target.value)}
                  placeholder="10.0.0.0/8&#10;52.89.214.238/32"
                />
              </div>
            </div>

            <div className="flex justify-end">
              <Button onClick={onSaveConfig} disabled={busy}>
                {busy ? 'Saving…' : 'Save Configuration'}
              </Button>
            </div>
          </TabsContent>

          {/* ---------- Template ---------- */}
          <TabsContent value="template" className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Paste this into your TradingView alert message body (or Python/Amibroker request body).
              Replace placeholders like <code>{'{{strategy.order.action}}'}</code> with your alert variables.
            </p>
            <Textarea
              rows={10}
              value={testPayload}
              onChange={(e) => setTestPayload(e.target.value)}
              className="font-mono text-xs"
            />
            <div className="flex justify-end">
              <Button variant="outline" onClick={() => copy(testPayload)}>
                Copy Template
              </Button>
            </div>
          </TabsContent>

          {/* ---------- Test ---------- */}
          <TabsContent value="test" className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Sends the request through the same signature/replay/IP pipeline as a real
              webhook, but does NOT create a run or place orders. Use this to verify your
              alert config before going live.
            </p>
            <div className="space-y-1">
              <Label>Request body (JSON)</Label>
              <Textarea
                rows={8}
                value={testPayload}
                onChange={(e) => setTestPayload(e.target.value)}
                className="font-mono text-xs"
              />
            </div>
            <div className="flex justify-end">
              <Button onClick={onTest}>Run Test</Button>
            </div>
            {testResult && (
              <div className="space-y-1">
                <Label>Response</Label>
                <Textarea
                  readOnly
                  rows={8}
                  value={testResult}
                  className="font-mono text-xs"
                />
              </div>
            )}
          </TabsContent>

          {/* ---------- Rotate ---------- */}
          <TabsContent value="rotate" className="space-y-3">
            <div className="border border-destructive/40 bg-destructive/10 rounded-md p-3 space-y-2">
              <p className="text-sm font-medium">Rotate webhook secrets</p>
              <p className="text-xs text-muted-foreground">
                This invalidates the current body-secret + HMAC key immediately. Existing
                signal sources (TradingView alerts etc.) will start failing until you
                update them with the new values. Type the strategy name to confirm.
              </p>
              <Input
                placeholder={strategy.name}
                value={rotateConfirm}
                onChange={(e) => setRotateConfirm(e.target.value)}
              />
              <div className="flex justify-end">
                <Button
                  variant="destructive"
                  onClick={onRotate}
                  disabled={busy || rotateConfirm !== strategy.name}
                >
                  Rotate Now
                </Button>
              </div>
            </div>
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------

function buildTemplate(
  strategy: StrategyV2,
  method: SigningMethod,
  secret: { webhook_secret?: string; webhook_hmac_key?: string } | null
): string {
  const tplParts: string[] = []
  if (method === 'BODY_SECRET' || method === 'BOTH') {
    const value = secret?.webhook_secret ?? '<your-saved-body-secret>'
    tplParts.push(`  "webhook_secret": "${value}"`)
  }
  tplParts.push('  "action": "BUY"')
  if (strategy.webhook_replay_window_seconds && strategy.webhook_replay_window_seconds > 0) {
    tplParts.push(`  "ts": ${Math.floor(Date.now() / 1000)}`)
  }
  tplParts.push('  "signal_id": "your-unique-id-here"')
  return `{\n${tplParts.join(',\n')}\n}`
}

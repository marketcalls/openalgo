import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  MessageCircle,
  Phone,
  Power,
  RefreshCcw,
  Send,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { io, type Socket } from 'socket.io-client'

import { whatsappApi } from '@/api/whatsapp'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type {
  WhatsAppConfigBundle,
  WhatsAppPairCodeEvent,
  WhatsAppPairedEvent,
  WhatsAppPairState,
  WhatsAppQrEvent,
  WhatsAppStatusEvent,
} from '@/types/whatsapp'
import { showToast } from '@/utils/toast'

/**
 * Single-user WhatsApp bot page. The paired device is the operator; once
 * the QR is scanned the bot auto-starts and is implicitly "connected" — no
 * separate start/stop UX. The only lifecycle action exposed is Disconnect,
 * which wipes the encrypted session blob and stops the bot.
 *
 * The QR rotates ~every 30 seconds while pairing. Each `whatsapp_qr`
 * SocketIO event carries a fresh data URL which we drop straight into
 * state so the <img> re-renders automatically.
 */
export default function WhatsAppIndex() {
  const [bundle, setBundle] = useState<WhatsAppConfigBundle | null>(null)
  const [pairState, setPairState] = useState<WhatsAppPairState | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [sendPhone, setSendPhone] = useState('')
  const [sendMessage, setSendMessage] = useState('')
  const socketRef = useRef<Socket | null>(null)

  const refresh = useCallback(async () => {
    try {
      const b = await whatsappApi.getConfig()
      setBundle(b)
      setPairState(b.pair_state)
    } catch {
      showToast.error('Failed to load WhatsApp data', 'whatsapp')
    }
  }, [])

  useEffect(() => {
    refresh()

    const protocol = window.location.protocol
    const host = window.location.hostname
    const port = window.location.port
    const url = port ? `${protocol}//${host}:${port}` : `${protocol}//${host}`

    const socket = io(url, {
      transports: ['polling'],
      upgrade: false,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
      timeout: 20000,
      forceNew: true,
    })
    socketRef.current = socket

    socket.on('whatsapp_qr', (data: WhatsAppQrEvent) => {
      setPairState((prev) => ({
        ...(prev ?? {
          status: 'awaiting_scan',
          qr_data_url: null,
          pair_code: null,
          error: null,
          started_at: null,
          paired_at: null,
        }),
        status: 'awaiting_scan',
        qr_data_url: data.data_url,
        error: null,
      }))
    })

    socket.on('whatsapp_pair_code', (data: WhatsAppPairCodeEvent) => {
      setPairState((prev) => ({
        ...(prev ?? {
          status: 'awaiting_scan',
          qr_data_url: null,
          pair_code: null,
          error: null,
          started_at: null,
          paired_at: null,
        }),
        status: 'awaiting_scan',
        pair_code: data.code,
      }))
    })

    socket.on('whatsapp_paired', (_data: WhatsAppPairedEvent) => {
      // Don't surface the owner's phone in the toast — privacy.
      setPairState((prev) => ({
        ...(prev ?? {
          status: 'paired',
          qr_data_url: null,
          pair_code: null,
          error: null,
          started_at: null,
          paired_at: null,
        }),
        status: 'paired',
        qr_data_url: null,
        paired_at: new Date().toISOString(),
      }))
      showToast.success('WhatsApp paired successfully', 'whatsapp')
      refresh()
    })

    socket.on('whatsapp_pair_status', (s: WhatsAppPairState) => {
      setPairState(s)
      if (s.status === 'failed' && s.error) {
        showToast.error(s.error, 'whatsapp')
      } else if (s.status === 'paired') {
        refresh()
      }
    })

    socket.on('whatsapp_status', (s: WhatsAppStatusEvent) => {
      setBundle((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          config: { ...prev.config, is_running: s.is_running, is_paired: s.is_paired },
        }
      })
    })

    return () => {
      socket.disconnect()
      socketRef.current = null
    }
  }, [refresh])

  const startPair = async () => {
    setBusy('pair')
    try {
      const resp = await whatsappApi.startPair()
      if (resp.status !== 'success') {
        showToast.error(resp.message || 'Pair failed to start', 'whatsapp')
      } else if (resp.data) {
        setPairState(resp.data)
      }
    } catch {
      showToast.error('Pair request failed', 'whatsapp')
    } finally {
      setBusy(null)
    }
  }

  const disconnect = async () => {
    if (
      !window.confirm(
        'Disconnect WhatsApp? The paired device will be removed. You will need to scan a new QR to receive alerts again.'
      )
    ) {
      return
    }
    setBusy('disconnect')
    try {
      const resp = await whatsappApi.unlinkDevice()
      showToast.success(resp.message || 'Disconnected', 'whatsapp')
      setPairState({
        status: 'idle',
        qr_data_url: null,
        pair_code: null,
        error: null,
        started_at: null,
        paired_at: null,
      })
      await refresh()
    } catch {
      showToast.error('Disconnect failed', 'whatsapp')
    } finally {
      setBusy(null)
    }
  }

  const sendToOne = async () => {
    if (!sendPhone || !sendMessage) {
      showToast.error('Phone and message are required', 'whatsapp')
      return
    }
    setBusy('send')
    try {
      const resp = await whatsappApi.sendToPhone({
        phone: sendPhone,
        message: sendMessage,
      })
      if (resp.status === 'success') {
        showToast.success(resp.message || 'Sent', 'whatsapp')
        setSendMessage('')
      } else {
        showToast.error(resp.message || 'Send failed', 'whatsapp')
      }
    } finally {
      setBusy(null)
    }
  }

  const cfg = bundle?.config
  const pairing = pairState?.status === 'starting' || pairState?.status === 'awaiting_scan'
  const isPaired = cfg?.is_paired

  return (
    <div className="container mx-auto max-w-3xl space-y-6 p-6">
      <header className="space-y-1">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <MessageCircle className="h-6 w-6" /> WhatsApp Bot
        </h1>
        <p className="text-sm text-muted-foreground">
          Pair your phone once. Receive order alerts and run slash-command queries ({' '}
          <code className="font-mono">/orderbook</code>,{' '}
          <code className="font-mono">/positions</code>, <code className="font-mono">/quote</code>,
          ... ) from your own device.
        </p>
      </header>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Status</CardTitle>
            <Badge variant={isPaired ? 'default' : 'secondary'} className="gap-1">
              {isPaired ? <CheckCircle2 className="h-3 w-3" /> : null}
              {isPaired ? 'Connected' : 'Not paired'}
            </Badge>
          </div>
          <CardDescription>
            {/* Privacy: the owner's WhatsApp number is intentionally never
                rendered in the UI. We only surface whether a device is
                paired and which OpenAlgo user owns it. */}
            {isPaired
              ? cfg?.owner_username
                ? `Device paired (owner: ${cfg.owner_username})`
                : 'Device paired'
              : 'No device linked yet'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!isPaired && (
            <div className="rounded border bg-muted/30 p-4">
              <div className="mb-3 flex items-center justify-between">
                <div className="text-sm font-medium">Pair this device</div>
                <Button size="sm" onClick={startPair} disabled={busy === 'pair' || pairing}>
                  {busy === 'pair' || pairing ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCcw className="h-4 w-4" />
                  )}
                  <span className="ml-2">{pairing ? 'Pairing…' : 'Start pairing'}</span>
                </Button>
              </div>
              {pairState?.status === 'awaiting_scan' && pairState.qr_data_url && (
                <div className="flex flex-col items-center gap-2">
                  <img
                    src={pairState.qr_data_url}
                    alt="WhatsApp pairing QR"
                    className="h-64 w-64 rounded border bg-white p-2"
                  />
                  <p className="text-xs text-muted-foreground">
                    Open WhatsApp → Linked devices → Link a device → scan. The QR refreshes
                    automatically every ~30 seconds.
                  </p>
                </div>
              )}
              {pairState?.status === 'awaiting_scan' && pairState.pair_code && (
                <div className="mt-3 rounded border bg-background p-3 text-center">
                  <div className="text-xs text-muted-foreground">Or use this pair code</div>
                  <div className="font-mono text-lg tracking-widest">{pairState.pair_code}</div>
                </div>
              )}
              {pairState?.status === 'failed' && pairState.error && (
                <div className="mt-2 flex items-center gap-2 rounded border border-destructive/40 bg-destructive/10 p-2 text-sm">
                  <AlertCircle className="h-4 w-4 text-destructive" />
                  <span>{pairState.error}</span>
                </div>
              )}
            </div>
          )}

          {isPaired && (
            <Button
              size="sm"
              variant="destructive"
              onClick={disconnect}
              disabled={busy === 'disconnect'}
            >
              <Power className="mr-2 h-4 w-4" /> Disconnect
            </Button>
          )}
        </CardContent>
      </Card>

      {isPaired && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Phone className="h-5 w-5" /> Send a one-off message
            </CardTitle>
            <CardDescription>
              Send a WhatsApp message to any number, directly from this page. The recipient does not
              need to be linked.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input
              placeholder="E.164 digits, e.g. 919876543210"
              value={sendPhone}
              onChange={(e) => setSendPhone(e.target.value)}
            />
            <Textarea
              placeholder="Message"
              rows={3}
              value={sendMessage}
              onChange={(e) => setSendMessage(e.target.value)}
            />
            <Button size="sm" onClick={sendToOne} disabled={busy === 'send'}>
              <Send className="mr-2 h-4 w-4" /> Send
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

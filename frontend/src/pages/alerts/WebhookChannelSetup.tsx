import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ArrowLeft, Loader2, Save, Send, ShieldCheck, Trash2 } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Link } from 'react-router'

import {
  ALERT_CHANNELS_KEY,
  type AlertChannel,
  type AlertChannelList,
  alertsApi,
  alertsErrorMessage,
  type WebhookChannelName,
} from '@/api/alerts'
import { Alert, AlertDescription } from '@/components/ui/alert'
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
import { Label } from '@/components/ui/label'
import { showToast } from '@/utils/toast'

/** What differs between the providers: what a URL looks like and where to get one. */
const PROVIDERS: Record<WebhookChannelName, { placeholder: string; steps: string[] }> = {
  slack: {
    placeholder: 'https://hooks.slack.com/services/...',
    steps: [
      'In Slack, open api.slack.com/apps and create an app for your workspace ("From scratch").',
      'Open Incoming Webhooks, switch them on, and choose "Add New Webhook to Workspace".',
      'Pick the channel the alerts should go to, allow it, and copy the webhook URL.',
      'Paste the URL below and save it.',
    ],
  },
  discord: {
    placeholder: 'https://discord.com/api/webhooks/...',
    steps: [
      'In Discord, open the settings of the channel the alerts should go to (Edit Channel).',
      'Open Integrations, then Webhooks, and choose "New Webhook". You need the Manage Webhooks permission.',
      'Choose "Copy Webhook URL".',
      'Paste the URL below and save it.',
    ],
  },
}

/**
 * Set up Slack or Discord alerts: save, test or remove the channel's webhook.
 *
 * The webhook URL is a secret, so the field is masked, and once saved the URL
 * is never shown again: the server only reports that one is saved. Which
 * orders reach the channel is chosen on /alerts with the other channels.
 */
export default function WebhookChannelSetup({ channel: name }: { channel: WebhookChannelName }) {
  const queryClient = useQueryClient()
  const list = useQuery({ queryKey: ALERT_CHANNELS_KEY, queryFn: alertsApi.list })
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState<'save' | 'test' | 'remove' | null>(null)
  const [confirmRemove, setConfirmRemove] = useState(false)

  const channel = list.data?.channels.find((c) => c.name === name)
  const provider = PROVIDERS[name]

  const replace = (updated: AlertChannel) => {
    queryClient.setQueryData<AlertChannelList>(ALERT_CHANNELS_KEY, (current) =>
      current
        ? {
            ...current,
            channels: current.channels.map((c) => (c.name === updated.name ? updated : c)),
          }
        : current
    )
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!channel) return
    setBusy('save')
    try {
      replace(await alertsApi.saveWebhook(name, url))
      setUrl('')
      showToast.success(`${channel.label} webhook saved. ${channel.label} alerts are on.`)
    } catch (error) {
      showToast.error(alertsErrorMessage(error, `The ${channel.label} webhook could not be saved.`))
    } finally {
      setBusy(null)
    }
  }

  const sendTest = async () => {
    if (!channel) return
    setBusy('test')
    try {
      showToast.success(await alertsApi.sendTest(name))
    } catch (error) {
      showToast.error(
        alertsErrorMessage(error, `The ${channel.label} test message could not be sent.`)
      )
    } finally {
      setBusy(null)
    }
  }

  const remove = async () => {
    if (!channel) return
    setConfirmRemove(false)
    setBusy('remove')
    try {
      replace(await alertsApi.forgetWebhook(name))
      showToast.success(`${channel.label} webhook removed. ${channel.label} alerts are off.`)
    } catch (error) {
      showToast.error(
        alertsErrorMessage(error, `The ${channel.label} webhook could not be removed.`)
      )
    } finally {
      setBusy(null)
    }
  }

  if (list.isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading
      </div>
    )
  }

  if (list.isError || !channel) {
    return (
      <div className="container mx-auto max-w-3xl px-4 py-8">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {alertsErrorMessage(list.error, 'The alert settings could not be loaded.')}
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  const saved = channel.status.configured

  return (
    <div className="container mx-auto max-w-3xl space-y-6 px-4 py-8">
      <div>
        <Link
          to="/alerts"
          className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="mr-1 h-4 w-4" />
          All alert channels
        </Link>
        <h1 className="mt-2 text-2xl font-bold">{channel.label} alerts</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          OpenAlgo posts your order alerts to a {channel.label} channel through an incoming webhook.
          Choose which orders it hears about on the{' '}
          <Link to="/alerts" className="underline">
            Alerts page
          </Link>
          .
        </p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="text-lg">Status</CardTitle>
            {channel.enabled ? (
              <Badge className="bg-green-600 text-white">On</Badge>
            ) : (
              <Badge variant="secondary">Off</Badge>
            )}
          </div>
          <CardDescription>{channel.status.detail}</CardDescription>
        </CardHeader>
        {saved && (
          <CardContent className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={!channel.enabled || busy !== null}
              onClick={sendTest}
            >
              {busy === 'test' ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-1 h-4 w-4" />
              )}
              Send test
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy !== null}
              onClick={() => setConfirmRemove(true)}
            >
              <Trash2 className="mr-1 h-4 w-4" />
              Remove webhook
            </Button>
          </CardContent>
        )}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">
            {saved ? 'Replace the webhook' : 'Add a webhook'}
          </CardTitle>
          <CardDescription>How to get one:</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            {provider.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <form onSubmit={save} className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="webhook-url">Webhook URL</Label>
              <Input
                id="webhook-url"
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder={provider.placeholder}
                value={url}
                onChange={(event) => setUrl(event.target.value)}
              />
            </div>
            <Button type="submit" disabled={!url.trim() || busy !== null}>
              {busy === 'save' ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-1 h-4 w-4" />
              )}
              Save webhook
            </Button>
          </form>
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
            Anyone holding this URL can post to your channel. OpenAlgo stores it encrypted, never
            shows it again, and only sends it to {channel.label}.
          </p>
        </CardContent>
      </Card>

      <AlertDialog open={confirmRemove} onOpenChange={setConfirmRemove}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove the {channel.label} webhook?</AlertDialogTitle>
            <AlertDialogDescription>
              {channel.label} alerts stop until you save a webhook again. The webhook itself is not
              deleted in {channel.label}.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={remove}>Remove</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

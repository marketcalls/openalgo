import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ArrowRight, CheckCircle2, Loader2, Send } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import {
  ALERT_CHANNELS_KEY,
  type AlertChannel,
  type AlertChannelList,
  type AlertChannelName,
  alertsApi,
  alertsErrorMessage,
} from '@/api/alerts'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Switch } from '@/components/ui/switch'
import { showToast } from '@/utils/toast'

/**
 * Every alert channel on one page.
 *
 * A card per channel says how it stands, switches it on or off, sends a test
 * and links to the channel's own setup page (/telegram, /whatsapp, /slack,
 * /discord). Below them, one row per group of order events and one column per
 * channel chooses which orders each channel hears about.
 *
 * The server decides everything this page shows: what is configured, what is
 * ready and why not. The page only renders it and sends the trader's changes.
 *
 * **One save per action at a time.** Every action in flight is tracked by its
 * own key, so one finishing never re-enables another. A channel's routing
 * row is one key: each save sends the whole list of groups, so a second tick
 * made while the first was saving would be built from the list as it was
 * before the first, and undo it.
 */
export default function AlertsIndex() {
  const queryClient = useQueryClient()
  const list = useQuery({ queryKey: ALERT_CHANNELS_KEY, queryFn: alertsApi.list })
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set())

  /** Run one action under ``key``, which stays pending until it ends. */
  const track = async (key: string, action: () => Promise<void>) => {
    setPending((current) => new Set(current).add(key))
    try {
      await action()
    } finally {
      setPending((current) => {
        const next = new Set(current)
        next.delete(key)
        return next
      })
    }
  }

  /** Put one channel's new state into the cached list. */
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

  const change = (
    channel: AlertChannel,
    update: { enabled?: boolean; categories?: string[] },
    key: string
  ) =>
    track(key, async () => {
      try {
        replace(await alertsApi.update(channel.name, update))
      } catch (error) {
        showToast.error(alertsErrorMessage(error, `Could not save the ${channel.label} settings.`))
      }
    })

  const sendTest = (name: AlertChannelName, label: string) =>
    track(`test:${name}`, async () => {
      try {
        showToast.success(await alertsApi.sendTest(name))
      } catch (error) {
        showToast.error(alertsErrorMessage(error, `The ${label} test message could not be sent.`))
      }
    })

  if (list.isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading alert channels
      </div>
    )
  }

  if (list.isError || !list.data) {
    return (
      <div className="container mx-auto max-w-5xl px-4 py-8">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {alertsErrorMessage(list.error, 'The alert channels could not be loaded.')}
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  const { categories, channels } = list.data

  return (
    <div className="container mx-auto max-w-5xl space-y-6 px-4 py-8">
      <div>
        <h1 className="text-2xl font-bold">Alerts</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose where OpenAlgo tells you about your orders, and which orders each channel hears
          about. An order that fails on its own is never sent as an alert; a basket, split or
          options alert lists any of its orders that were rejected.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {channels.map((channel) => (
          <ChannelCard
            key={channel.name}
            channel={channel}
            pending={pending}
            onToggle={(enabled) => change(channel, { enabled }, `toggle:${channel.name}`)}
            onTest={() => sendTest(channel.name, channel.label)}
          />
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Which orders each channel hears about</CardTitle>
          <CardDescription>
            A channel that is switched off receives nothing, whatever is ticked here. Its groups can
            still be chosen, ready for when it is switched on.
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b">
                <th className="py-2 pr-4 text-left font-medium">Orders</th>
                {channels.map((channel) => (
                  <th key={channel.name} className="px-3 py-2 text-center font-medium">
                    {channel.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {categories.map((category) => (
                <tr key={category.id} className="border-b last:border-0">
                  <td className="py-3 pr-4">
                    <div className="font-medium">{category.label}</div>
                    <div className="text-xs text-muted-foreground">{category.description}</div>
                  </td>
                  {channels.map((channel) => {
                    const ticked = channel.categories.includes(category.id)
                    // One key per channel: its saves are serialised.
                    const key = `route:${channel.name}`
                    return (
                      <td key={channel.name} className="px-3 py-3 text-center">
                        <Checkbox
                          aria-label={`${category.label} on ${channel.label}`}
                          checked={ticked}
                          disabled={pending.has(key)}
                          onCheckedChange={(next) =>
                            change(
                              channel,
                              {
                                categories: next
                                  ? [...channel.categories, category.id]
                                  : channel.categories.filter((id) => id !== category.id),
                              },
                              key
                            )
                          }
                        />
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

interface ChannelCardProps {
  channel: AlertChannel
  pending: ReadonlySet<string>
  onToggle: (enabled: boolean) => void
  onTest: () => void
}

function ChannelCard({ channel, pending, onToggle, onTest }: ChannelCardProps) {
  const { status } = channel
  // A webhook channel has nothing to switch on until its webhook is saved.
  const canSwitchOn = !channel.uses_webhook || status.configured
  const setupLabel = channel.uses_webhook
    ? `Set up ${channel.label}`
    : `Open ${channel.label} settings`

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="text-lg">{channel.label}</CardTitle>
            <div className="mt-1">
              <StatusBadge channel={channel} />
            </div>
          </div>
          <Switch
            aria-label={`Send alerts to ${channel.label}`}
            checked={channel.enabled}
            disabled={pending.has(`toggle:${channel.name}`) || (!channel.enabled && !canSwitchOn)}
            onCheckedChange={onToggle}
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">{status.detail}</p>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={!channel.enabled || !status.ready || pending.has(`test:${channel.name}`)}
            onClick={onTest}
          >
            {pending.has(`test:${channel.name}`) ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-1 h-4 w-4" />
            )}
            Send test
          </Button>
          <Button size="sm" variant="ghost" asChild>
            <Link to={channel.setup_path}>
              {setupLabel}
              <ArrowRight className="ml-1 h-4 w-4" />
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function StatusBadge({ channel }: { channel: AlertChannel }) {
  if (!channel.enabled) return <Badge variant="secondary">Off</Badge>
  if (channel.status.ready) {
    return (
      <Badge className="bg-green-600 text-white">
        <CheckCircle2 className="mr-1 h-3 w-3" />
        Ready
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="border-amber-500 text-amber-600">
      {channel.status.configured ? 'Not ready' : 'Needs setup'}
    </Badge>
  )
}

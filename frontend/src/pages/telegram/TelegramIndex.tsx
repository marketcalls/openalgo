import {
  ArrowRight,
  BarChart3,
  Bell,
  Bot,
  MessageSquare,
  Power,
  PowerOff,
  Radio,
  Send,
  Settings,
  Users,
} from 'lucide-react'
import { useEffect, useState } from 'react'
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import type { CommandStats, TelegramBotStatus, TelegramUser } from '@/types/telegram'

interface TelegramIndexData {
  bot_status: TelegramBotStatus
  config: {
    bot_username: string | null
    broadcast_enabled: boolean
    rate_limit_per_minute: number
    is_active: boolean
  }
  users: TelegramUser[]
  stats: CommandStats[]
  telegram_user: TelegramUser | null
}

export default function TelegramIndex() {
  const [data, setData] = useState<TelegramIndexData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isStarting, setIsStarting] = useState(false)
  const [isStopping, setIsStopping] = useState(false)
  const [isSendingTest, setIsSendingTest] = useState(false)

  // Broadcast state
  const [broadcastMessage, setBroadcastMessage] = useState('')
  const [showBroadcastConfirm, setShowBroadcastConfirm] = useState(false)
  const [isBroadcasting, setIsBroadcasting] = useState(false)

  useEffect(() => {
    fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchData = async () => {
    try {
      const response = await webClient.get<{ status: string; data: TelegramIndexData }>(
        '/telegram/api/index'
      )
      setData(response.data.data)
    } catch (error) {
      showToast.error('Failed to load Telegram data', 'telegram')
    } finally {
      setIsLoading(false)
    }
  }

  const handleStartBot = async () => {
    setIsStarting(true)
    try {
      const response = await webClient.post<{ status: string; message: string }>(
        '/telegram/bot/start'
      )
      if (response.data.status === 'success') {
        showToast.success(response.data.message || 'Bot started successfully', 'telegram')
        fetchData()
      } else {
        showToast.error(response.data.message || 'Failed to start bot', 'telegram')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to start bot', 'telegram')
    } finally {
      setIsStarting(false)
    }
  }

  const handleStopBot = async () => {
    setIsStopping(true)
    try {
      const response = await webClient.post<{ status: string; message: string }>(
        '/telegram/bot/stop'
      )
      if (response.data.status === 'success') {
        showToast.success(response.data.message || 'Bot stopped successfully', 'telegram')
        fetchData()
      } else {
        showToast.error(response.data.message || 'Failed to stop bot', 'telegram')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to stop bot', 'telegram')
    } finally {
      setIsStopping(false)
    }
  }

  const handleSendTest = async () => {
    setIsSendingTest(true)
    try {
      const response = await webClient.post<{ status: string; message: string }>(
        '/telegram/test-message'
      )
      if (response.data.status === 'success') {
        showToast.success(response.data.message || 'Test message sent', 'telegram')
      } else {
        showToast.error(response.data.message || 'Failed to send test message', 'telegram')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to send test message', 'telegram')
    } finally {
      setIsSendingTest(false)
    }
  }

  const handleBroadcast = async () => {
    if (!broadcastMessage.trim()) {
      showToast.error('Please enter a message to broadcast', 'telegram')
      return
    }
    setShowBroadcastConfirm(true)
  }

  const confirmBroadcast = async () => {
    setShowBroadcastConfirm(false)
    setIsBroadcasting(true)
    try {
      const response = await webClient.post<{
        status: string
        message: string
        success_count?: number
        fail_count?: number
      }>('/telegram/broadcast', { message: broadcastMessage })

      if (response.data.status === 'success') {
        showToast.success(response.data.message || 'Broadcast sent successfully', 'telegram')
        setBroadcastMessage('')
      } else {
        showToast.error(response.data.message || 'Failed to send broadcast', 'telegram')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to send broadcast', 'telegram')
    } finally {
      setIsBroadcasting(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-16">
        <p className="text-muted-foreground">Failed to load Telegram data</p>
      </div>
    )
  }

  const { bot_status, config, users = [], stats = [] } = data
  const safeUsers = Array.isArray(users) ? users : []
  const safeStats = Array.isArray(stats) ? stats : []
  const activeUsers = safeUsers.filter((u) => u.notifications_enabled).length

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <MessageSquare className="h-6 w-6" />
            Telegram Bot
          </h1>
          <p className="text-muted-foreground mt-1">
            Manage your Telegram bot for trade notifications
          </p>
        </div>
        <div className="flex gap-2">
          {bot_status.is_running ? (
            <Button variant="destructive" onClick={handleStopBot} disabled={isStopping}>
              <PowerOff className="h-4 w-4 mr-2" />
              {isStopping ? 'Stopping...' : 'Stop Bot'}
            </Button>
          ) : (
            <Button onClick={handleStartBot} disabled={isStarting || !bot_status.is_configured}>
              <Power className="h-4 w-4 mr-2" />
              {isStarting ? 'Starting...' : 'Start Bot'}
            </Button>
          )}
          <Link to="/telegram/config">
            <Button variant="outline">
              <Settings className="h-4 w-4 mr-2" />
              Configuration
            </Button>
          </Link>
        </div>
      </div>

      {/* Status Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div
                className={`w-12 h-12 rounded-full flex items-center justify-center ${
                  bot_status.is_running ? 'bg-green-500' : 'bg-gray-400'
                }`}
              >
                <Bot className="h-6 w-6 text-white" />
              </div>
              <div>
                <CardTitle>
                  {config.bot_username ? `@${config.bot_username}` : 'Bot Not Configured'}
                </CardTitle>
                <CardDescription>
                  {bot_status.is_running ? 'Bot is running' : 'Bot is stopped'}
                </CardDescription>
              </div>
            </div>
            <Badge
              variant={bot_status.is_running ? 'default' : 'secondary'}
              className={bot_status.is_running ? 'bg-green-500 hover:bg-green-600' : ''}
            >
              {bot_status.is_running ? 'Online' : 'Offline'}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="text-center p-3 bg-muted rounded-lg">
              <p className="text-2xl font-bold">{safeUsers.length}</p>
              <p className="text-sm text-muted-foreground">Total Users</p>
            </div>
            <div className="text-center p-3 bg-muted rounded-lg">
              <p className="text-2xl font-bold">{activeUsers}</p>
              <p className="text-sm text-muted-foreground">Active Users</p>
            </div>
            <div className="text-center p-3 bg-muted rounded-lg">
              <p className="text-2xl font-bold">{safeStats.reduce((sum, s) => sum + s.count, 0)}</p>
              <p className="text-sm text-muted-foreground">Commands (7d)</p>
            </div>
            <div className="text-center p-3 bg-muted rounded-lg">
              <p className="text-2xl font-bold">{config.rate_limit_per_minute}</p>
              <p className="text-sm text-muted-foreground">Rate Limit/min</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Link to="/telegram/config">
          <Card className="h-full hover:shadow-lg transition-shadow cursor-pointer group">
            <CardHeader className="pb-2">
              <div className="w-10 h-10 rounded-lg bg-blue-500 flex items-center justify-center">
                <Settings className="h-5 w-5 text-white" />
              </div>
            </CardHeader>
            <CardContent>
              <h3 className="font-semibold group-hover:text-primary transition-colors flex items-center gap-2">
                Configuration
                <ArrowRight className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
              </h3>
              <p className="text-sm text-muted-foreground">Configure bot settings</p>
            </CardContent>
          </Card>
        </Link>

        <Link to="/telegram/users">
          <Card className="h-full hover:shadow-lg transition-shadow cursor-pointer group">
            <CardHeader className="pb-2">
              <div className="w-10 h-10 rounded-lg bg-green-500 flex items-center justify-center">
                <Users className="h-5 w-5 text-white" />
              </div>
            </CardHeader>
            <CardContent>
              <h3 className="font-semibold group-hover:text-primary transition-colors flex items-center gap-2">
                Users
                <ArrowRight className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
              </h3>
              <p className="text-sm text-muted-foreground">Manage linked users</p>
            </CardContent>
          </Card>
        </Link>

        <Link to="/telegram/analytics">
          <Card className="h-full hover:shadow-lg transition-shadow cursor-pointer group">
            <CardHeader className="pb-2">
              <div className="w-10 h-10 rounded-lg bg-purple-500 flex items-center justify-center">
                <BarChart3 className="h-5 w-5 text-white" />
              </div>
            </CardHeader>
            <CardContent>
              <h3 className="font-semibold group-hover:text-primary transition-colors flex items-center gap-2">
                Analytics
                <ArrowRight className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
              </h3>
              <p className="text-sm text-muted-foreground">View usage statistics</p>
            </CardContent>
          </Card>
        </Link>

        <Card className="h-full">
          <CardHeader className="pb-2">
            <div className="w-10 h-10 rounded-lg bg-orange-500 flex items-center justify-center">
              <Send className="h-5 w-5 text-white" />
            </div>
          </CardHeader>
          <CardContent>
            <h3 className="font-semibold">Test Message</h3>
            <p className="text-sm text-muted-foreground mb-3">Send a test notification</p>
            <Button
              size="sm"
              variant="outline"
              onClick={handleSendTest}
              disabled={isSendingTest || !bot_status.is_running}
            >
              {isSendingTest ? 'Sending...' : 'Send Test'}
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Your Telegram Link Status */}
      {data.telegram_user && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bell className="h-5 w-5" />
              Your Telegram Link
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">
                  @{data.telegram_user.telegram_username || data.telegram_user.first_name}
                </p>
                <p className="text-sm text-muted-foreground">
                  Notifications: {data.telegram_user.notifications_enabled ? 'Enabled' : 'Disabled'}
                </p>
              </div>
              <Badge variant={data.telegram_user.notifications_enabled ? 'default' : 'secondary'}>
                {data.telegram_user.notifications_enabled ? 'Active' : 'Inactive'}
              </Badge>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Popular Commands Table */}
      {safeStats.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Popular Commands (Last 7 Days)</CardTitle>
            <CardDescription>Most used bot commands</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="border rounded-md">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Command</TableHead>
                    <TableHead>Count</TableHead>
                    <TableHead>Percentage</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {safeStats.map((stat) => {
                    const totalCommands = safeStats.reduce((sum, s) => sum + s.count, 0)
                    const percentage = totalCommands > 0 ? (stat.count / totalCommands) * 100 : 0
                    return (
                      <TableRow key={stat.command}>
                        <TableCell>
                          <Badge variant="outline">/{stat.command}</Badge>
                        </TableCell>
                        <TableCell>{stat.count}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <div className="w-24 bg-muted rounded-full h-2">
                              <div
                                className="bg-primary h-2 rounded-full"
                                style={{ width: `${percentage}%` }}
                              />
                            </div>
                            <span className="text-sm text-muted-foreground w-12">
                              {percentage.toFixed(1)}%
                            </span>
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Broadcast Message */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Radio className="h-5 w-5" />
            Broadcast Message
          </CardTitle>
          <CardDescription>Send a message to all users</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            placeholder="Enter your message here..."
            value={broadcastMessage}
            onChange={(e) => setBroadcastMessage(e.target.value)}
            rows={4}
          />
          <div className="flex justify-end">
            <Button
              onClick={handleBroadcast}
              disabled={isBroadcasting || !bot_status.is_running || !config.broadcast_enabled}
            >
              <Send className="h-4 w-4 mr-2" />
              {isBroadcasting ? 'Broadcasting...' : 'Send Broadcast'}
            </Button>
          </div>
          {!config.broadcast_enabled && (
            <p className="text-sm text-muted-foreground">
              Broadcast is disabled. Enable it in Configuration.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Broadcast Confirmation Dialog */}
      <AlertDialog open={showBroadcastConfirm} onOpenChange={setShowBroadcastConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirm Broadcast</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to send this message to all users?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="bg-muted p-3 rounded-lg my-4">
            <p className="text-sm whitespace-pre-wrap">{broadcastMessage}</p>
          </div>
          <p className="text-sm text-muted-foreground">
            This will be sent to {activeUsers} active users ({safeUsers.length} total users)
          </p>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmBroadcast}>Send Broadcast</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

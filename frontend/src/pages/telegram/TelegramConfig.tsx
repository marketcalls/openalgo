import { ArrowLeft, Check, Eye, EyeOff, Key, Save, Settings } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { webClient } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'

interface TelegramConfig {
  has_token: boolean
  bot_username: string | null
  broadcast_enabled: boolean
  rate_limit_per_minute: number
  is_active: boolean
}

export default function TelegramConfig() {
  const [config, setConfig] = useState<TelegramConfig | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)

  // Form state
  const [token, setToken] = useState('')
  const [showToken, setShowToken] = useState(false)
  const [broadcastEnabled, setBroadcastEnabled] = useState(true)
  const [rateLimit, setRateLimit] = useState(10)

  useEffect(() => {
    fetchConfig()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchConfig = async () => {
    try {
      const response = await webClient.get<{ status: string; data: TelegramConfig }>(
        '/telegram/api/config'
      )
      const configData = response.data.data
      setConfig(configData)
      setBroadcastEnabled(configData.broadcast_enabled)
      setRateLimit(configData.rate_limit_per_minute)
    } catch (error) {
      showToast.error('Failed to load configuration', 'telegram')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSave = async () => {
    setIsSaving(true)
    try {
      const updateData: {
        token?: string
        broadcast_enabled: boolean
        rate_limit_per_minute: number
      } = {
        broadcast_enabled: broadcastEnabled,
        rate_limit_per_minute: rateLimit,
      }

      if (token) {
        updateData.token = token
      }

      const response = await webClient.post<{ status: string; message: string }>(
        '/telegram/config',
        updateData
      )

      if (response.data.status === 'success') {
        showToast.success('Configuration saved successfully', 'telegram')
        setToken('') // Clear token field after saving
        fetchConfig() // Refresh config
      } else {
        showToast.error(response.data.message || 'Failed to save configuration', 'telegram')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to save configuration', 'telegram')
    } finally {
      setIsSaving(false)
    }
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
          <Link to="/telegram" className="text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Settings className="h-6 w-6" />
            Bot Configuration
          </h1>
        </div>
        <p className="text-muted-foreground">Configure your Telegram bot settings</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Bot Token */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Key className="h-5 w-5" />
              Bot Token
            </CardTitle>
            <CardDescription>Your Telegram Bot API token from @BotFather</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {config?.has_token && (
              <div className="flex items-center gap-2 p-3 bg-green-500/10 border border-green-500/20 rounded-lg">
                <Check className="h-4 w-4 text-green-500" />
                <span className="text-sm">Token is configured</span>
              </div>
            )}

            <div className="space-y-2">
              <Label>{config?.has_token ? 'Update Token (optional)' : 'Bot Token'}</Label>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Input
                    type={showToken ? 'text' : 'password'}
                    placeholder={
                      config?.has_token ? 'Enter new token to update' : 'Enter your bot token'
                    }
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    className="pr-10"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="absolute right-0 top-0 h-full px-3"
                    onClick={() => setShowToken(!showToken)}
                  >
                    {showToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                Get your token from @BotFather on Telegram
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Settings */}
        <Card>
          <CardHeader>
            <CardTitle>Settings</CardTitle>
            <CardDescription>Configure bot behavior and limits</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Broadcast Toggle */}
            <div className="flex items-center justify-between">
              <div>
                <Label>Broadcast Messages</Label>
                <p className="text-sm text-muted-foreground">
                  Allow sending broadcast messages to all users
                </p>
              </div>
              <Switch checked={broadcastEnabled} onCheckedChange={setBroadcastEnabled} />
            </div>

            {/* Rate Limit */}
            <div className="space-y-2">
              <Label>Rate Limit (messages per minute)</Label>
              <Input
                type="number"
                value={rateLimit}
                onChange={(e) => setRateLimit(parseInt(e.target.value, 10) || 10)}
                min={1}
                max={60}
              />
              <p className="text-xs text-muted-foreground">
                Maximum messages per minute per user (1-60)
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Save Button and Documentation */}
      <div className="flex flex-col sm:flex-row justify-between items-stretch sm:items-center gap-3">
        <a
          href="https://docs.openalgo.in/trading-platform/telegram"
          target="_blank"
          rel="noopener noreferrer"
        >
          <Button variant="outline" className="w-full sm:w-auto">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-4 w-4 mr-2"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path d="M9 4.804A7.968 7.968 0 005.5 4c-1.255 0-2.443.29-3.5.804v10A7.969 7.969 0 015.5 14c1.669 0 3.218.51 4.5 1.385A7.962 7.962 0 0114.5 14c1.255 0 2.443.29 3.5.804v-10A7.968 7.968 0 0014.5 4c-1.255 0-2.443.29-3.5.804V12a1 1 0 11-2 0V4.804z" />
            </svg>
            View Documentation
          </Button>
        </a>
        <Button onClick={handleSave} disabled={isSaving}>
          <Save className="h-4 w-4 mr-2" />
          {isSaving ? 'Saving...' : 'Save Configuration'}
        </Button>
      </div>

      {/* Setup Guide */}
      <Card>
        <CardHeader>
          <CardTitle>Quick Setup Guide</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
            <p className="text-sm">
              <span className="font-semibold">Need detailed instructions?</span> Visit our complete{' '}
              <a
                href="https://docs.openalgo.in/trading-platform/telegram"
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline font-semibold"
              >
                Telegram Bot Setup Guide
              </a>{' '}
              for step-by-step instructions with screenshots.
            </p>
          </div>

          <div className="prose prose-sm dark:prose-invert max-w-none">
            <h4 className="text-base font-semibold mb-2">Quick Steps:</h4>
            <ol className="text-muted-foreground space-y-1 list-decimal list-inside text-sm">
              <li>
                Get a bot token from <strong>@BotFather</strong> on Telegram
              </li>
              <li>Paste the token above and click "Save Configuration"</li>
              <li>Start the bot from the dashboard</li>
              <li>
                Open your bot in Telegram and send{' '}
                <code className="bg-muted px-1 rounded">/start</code>
              </li>
              <li>
                Link your account:{' '}
                <code className="bg-muted px-1 rounded">/link YOUR_API_KEY YOUR_HOST_URL</code>
              </li>
            </ol>
          </div>
        </CardContent>
      </Card>

      {/* Bot Commands Reference */}
      <Card>
        <CardHeader>
          <CardTitle>Bot Commands Available</CardTitle>
          <CardDescription>Commands users can send to your bot</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="bg-muted rounded-lg p-4 font-mono text-sm space-y-4">
            <div>
              <p className="text-muted-foreground mb-1"># Account Management</p>
              <p>/start - Initialize bot</p>
              <p>/link &lt;api_key&gt; &lt;host_url&gt; - Link account</p>
              <p>/unlink - Unlink account</p>
              <p>/status - Check connection</p>
            </div>

            <div>
              <p className="text-muted-foreground mb-1"># Trading Information</p>
              <p>/menu - Interactive menu</p>
              <p>/orderbook - View orders</p>
              <p>/tradebook - View trades</p>
              <p>/positions - Open positions</p>
              <p>/holdings - View holdings</p>
              <p>/funds - Account funds</p>
              <p>/pnl - P&L summary</p>
            </div>

            <div>
              <p className="text-muted-foreground mb-1"># Market Data</p>
              <p>/quote RELIANCE - Get NSE quote</p>
              <p>/quote NIFTY NSE_INDEX - Index quote</p>
            </div>

            <div>
              <p className="text-muted-foreground mb-1"># Charts (default: 5m intraday)</p>
              <p>/chart RELIANCE - 5min chart</p>
              <p>/chart RELIANCE NSE daily - Daily chart</p>
              <p>/chart RELIANCE NSE intraday 15m 10 - Custom</p>
              <p>/chart RELIANCE NSE both - Both charts</p>
            </div>

            <div>
              <p>/help - Show all commands</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

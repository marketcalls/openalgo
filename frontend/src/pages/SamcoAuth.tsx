import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ExternalLink,
  Loader2,
  Network,
  Shield,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { fetchCSRFToken } from '@/api/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuthStore } from '@/stores/authStore'
import { showToast } from '@/utils/toast'

const DASHBOARD_URL = 'https://tradeapi.samco.in/app/login'

interface IpStatus {
  src_ip: string
  primary_ip: string
  secondary_ip: string
  matches: boolean
  matched_as: string | null
  message: string
  dashboard_url: string
}

export default function SamcoAuth() {
  const navigate = useNavigate()
  const { login } = useAuthStore()

  const [isConnecting, setIsConnecting] = useState(false)
  const [isCheckingIp, setIsCheckingIp] = useState(false)
  const [connected, setConnected] = useState(false)
  const [ipStatus, setIpStatus] = useState<IpStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Exchange the API key/secret configured in .env for a daily session token.
  async function handleConnect() {
    setIsConnecting(true)
    setError(null)

    try {
      const csrfToken = await fetchCSRFToken()
      const form = new FormData()
      form.append('csrf_token', csrfToken)

      const response = await fetch('/samco/callback', {
        method: 'POST',
        body: form,
        credentials: 'include',
      })

      const data = await response.json()

      if (data.status === 'success') {
        login('', 'samco')
        setConnected(true)
        showToast.success('Connected to Samco')
        await checkIpStatus()
      } else {
        setError(data.message || 'Authentication failed. Please try again.')
      }
    } catch {
      setError('Authentication failed. Please check your API credentials and try again.')
    } finally {
      setIsConnecting(false)
    }
  }

  // GET /ip/whoami - confirms the IP Samco sees matches a registered static IP.
  async function checkIpStatus() {
    setIsCheckingIp(true)
    // Clear the previous failure so a successful recheck (e.g. after
    // registering the IP) does not leave the old banner on screen.
    setError(null)

    try {
      const response = await fetch('/samco/ip-status', { credentials: 'include' })
      const data = await response.json()

      if (data.status === 'success') {
        setIpStatus(data)
      } else {
        setError(data.message || 'Could not verify the static IP status.')
      }
    } catch {
      setError('Could not verify the static IP status.')
    } finally {
      setIsCheckingIp(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            Connect to Samco
          </CardTitle>
          <CardDescription>
            Samco Trade API v3.2 authenticates with an API Key and API Secret from an OAuth
            app. Create the app, copy both values into your .env as BROKER_API_KEY and
            BROKER_API_SECRET, and register this server's IP under Static IPs.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          <Button asChild variant="outline" className="w-full">
            <a href={DASHBOARD_URL} target="_blank" rel="noopener noreferrer">
              Open Samco Web Dashboard
              <ExternalLink className="ml-2 h-4 w-4" />
            </a>
          </Button>

          {error && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {!connected && (
            <Button className="w-full" onClick={handleConnect} disabled={isConnecting}>
              {isConnecting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Connecting
                </>
              ) : (
                'Connect'
              )}
            </Button>
          )}

          {connected && (
            <Alert>
              <Check className="h-4 w-4" />
              <AlertDescription>
                Session token generated. It stays valid until 08:00 IST tomorrow.
              </AlertDescription>
            </Alert>
          )}

          {isCheckingIp && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Verifying static IP
            </div>
          )}

          {ipStatus && (
            <div className="space-y-3 rounded-md border p-4">
              <div className="flex items-center gap-2 font-medium">
                <Network className="h-4 w-4" />
                Static IP
                {ipStatus.matches ? (
                  <span className="ml-auto flex items-center gap-1 text-sm text-green-600">
                    <Check className="h-4 w-4" />
                    {ipStatus.matched_as}
                  </span>
                ) : (
                  <span className="ml-auto flex items-center gap-1 text-sm text-destructive">
                    <X className="h-4 w-4" />
                    Not registered
                  </span>
                )}
              </div>

              <dl className="space-y-1 text-sm">
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">This server</dt>
                  <dd className="font-mono">{ipStatus.src_ip || 'unknown'}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">Primary</dt>
                  <dd className="font-mono">{ipStatus.primary_ip || 'not set'}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">Secondary</dt>
                  <dd className="font-mono">{ipStatus.secondary_ip || 'not set'}</dd>
                </div>
              </dl>

              {!ipStatus.matches && (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertDescription>
                    Order APIs will reject this host. Register {ipStatus.src_ip || 'this IP'}{' '}
                    under Static IPs in the dashboard. SEBI allows one IP change every 7 days.
                  </AlertDescription>
                </Alert>
              )}
            </div>
          )}

          {connected && (
            <div className="flex gap-2">
              <Button variant="outline" className="flex-1" onClick={checkIpStatus}>
                Recheck IP
              </Button>
              <Button className="flex-1" onClick={() => navigate('/dashboard')}>
                Continue
              </Button>
            </div>
          )}

          <Button asChild variant="ghost" className="w-full">
            <Link to="/broker">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to brokers
            </Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

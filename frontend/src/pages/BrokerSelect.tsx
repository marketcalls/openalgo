import { BookOpen, ExternalLink, Info, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { BrokerAuthSignOut } from '@/components/auth/BrokerAuthSignOut'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  BROKER_SETUP_PATH,
  type ConfiguredBroker,
  fetchConfiguredBrokers,
  startBrokerLogin,
  switchActiveBroker,
} from '@/lib/brokerProfiles'
import { useAuthStore } from '@/stores/authStore'

// All supported brokers with their display names and auth types
const allBrokers = [
  { id: 'fivepaisa', name: '5 Paisa', authType: 'totp' },
  { id: 'fivepaisaxts', name: '5 Paisa (XTS)', authType: 'totp' },
  { id: 'aliceblue', name: 'Alice Blue', authType: 'totp' },
  { id: 'angel', name: 'Angel One', authType: 'totp' },
  { id: 'arrow', name: 'Arrow', authType: 'oauth' },
  { id: 'compositedge', name: 'CompositEdge', authType: 'oauth' },
  { id: 'dhan', name: 'Dhan', authType: 'oauth' },
  { id: 'deltaexchange', name: 'Delta Exchange', authType: 'totp' },
  { id: 'indmoney', name: 'IndMoney', authType: 'totp' },
  { id: 'dhan_sandbox', name: 'Dhan (Sandbox)', authType: 'totp' },
  { id: 'definedge', name: 'Definedge', authType: 'totp' },
  { id: 'firstock', name: 'Firstock', authType: 'totp' },
  { id: 'flattrade', name: 'Flattrade', authType: 'oauth' },
  { id: 'motilal', name: 'Motilal Oswal', authType: 'totp' },
  { id: 'fyers', name: 'Fyers', authType: 'oauth' },
  { id: 'groww', name: 'Groww', authType: 'totp' },
  { id: 'hdfcsecurities', name: 'HDFC Securities', authType: 'oauth' },
  { id: 'hdfcsky', name: 'HDFC Sky', authType: 'oauth' },
  { id: 'ibulls', name: 'Ibulls', authType: 'totp' },
  { id: 'iifl', name: 'IIFL', authType: 'totp' },
  { id: 'iiflcapital', name: 'IIFL Capital', authType: 'oauth' },
  { id: 'jainamxts', name: 'JainamXts', authType: 'totp' },
  { id: 'kotak', name: 'Kotak Securities', authType: 'totp' },
  { id: 'mstock', name: 'mStock by Mirae Asset', authType: 'totp' },
  { id: 'nubra', name: 'Nubra', authType: 'totp' },
  { id: 'paytm', name: 'Paytm Money', authType: 'oauth' },
  { id: 'pocketful', name: 'Pocketful', authType: 'oauth' },
  { id: 'rmoney', name: 'RMoney', authType: 'oauth' },
  { id: 'rupeezy', name: 'Rupeezy', authType: 'oauth' },
  { id: 'sahi', name: 'Sahi', authType: 'totp' },
  { id: 'samco', name: 'Samco', authType: 'totp' },
  { id: 'shoonya', name: 'Shoonya', authType: 'totp' },
  { id: 'tradejini', name: 'Tradejini', authType: 'totp' },
  { id: 'tradesmart', name: 'TradeSmart', authType: 'oauth' },
  { id: 'upstox', name: 'Upstox', authType: 'oauth' },
  { id: 'wisdom', name: 'Wisdom Capital', authType: 'totp' },
  { id: 'zebu', name: 'Zebu', authType: 'totp' },
  { id: 'zerodha', name: 'Zerodha', authType: 'oauth' },
] as const

interface BrokerConfig {
  broker_name: string
  redirect_url: string
}

/**
 * The message for a refused broker callback, which lands here as
 * /broker?error=<code>. Only these fixed sentences are ever shown: the query
 * string is set by whoever built the link, so its text never reaches the page.
 */
const CALLBACK_ERRORS: Record<string, string> = {
  login_not_started:
    'This broker login was not started from OpenAlgo, or it took longer than 10 minutes. Start the broker login again.',
  broker_unavailable:
    'The broker login could not start. Check its keys in Profile > Broker, then try again.',
  form_expired: 'This login form has expired. Reload the page and try again.',
  login_failed: 'The broker login did not complete. Try again.',
}

function callbackErrorMessage(code: string | null): string | null {
  if (code === null) return null
  return Object.hasOwn(CALLBACK_ERRORS, code)
    ? CALLBACK_ERRORS[code]
    : 'The broker login did not complete. Try again.'
}

export default function BrokerSelect() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [selectedBroker, setSelectedBroker] = useState<string>('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(() =>
    callbackErrorMessage(searchParams.get('error'))
  )
  const [brokerConfig, setBrokerConfig] = useState<BrokerConfig | null>(null)
  // Every broker with saved keys, so the trader can switch here.
  const [configured, setConfigured] = useState<ConfiguredBroker[]>([])
  const [reloadKey, setReloadKey] = useState(0)

  // biome-ignore lint/correctness/useExhaustiveDependencies: refetch after a broker switch.
  useEffect(() => {
    // Fetch broker configuration
    const fetchBrokerConfig = async () => {
      try {
        const response = await fetch('/auth/broker-config', {
          credentials: 'include',
        })
        // Signed out of OpenAlgo: the broker list belongs to a signed-in trader.
        if (response.status === 401) {
          navigate('/login', { replace: true })
          return
        }
        const data = await response.json()

        if (data.status === 'success') {
          setBrokerConfig(data)
          // Auto-select the configured broker
          setSelectedBroker(data.broker_name)
        } else {
          setBrokerConfig(null)
          setError(data.message || 'Failed to load broker configuration')
        }
      } catch {
        setError('Failed to load broker configuration')
      } finally {
        setIsLoading(false)
      }
    }

    fetchBrokerConfig()
    fetchConfiguredBrokers().then(setConfigured)
  }, [reloadKey])

  // Picking another configured broker makes it the active one.
  const handleBrokerChange = async (broker: string) => {
    setSelectedBroker(broker)
    if (!broker || broker === brokerConfig?.broker_name) return
    setError(null)
    setIsLoading(true)
    const refusal = await switchActiveBroker(broker)
    if (refusal) {
      setError(refusal)
      setIsLoading(false)
      return
    }
    setReloadKey((k) => k + 1)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!selectedBroker) {
      setError('Please select a broker')
      return
    }

    if (!brokerConfig) {
      setError('Broker configuration not loaded')
      return
    }

    setIsSubmitting(true)
    setError(null)

    // The server builds the sign-in address (the API key never reaches the page).
    const started = await startBrokerLogin(selectedBroker)
    if (started.error !== undefined) {
      setError(started.error)
      setIsSubmitting(false)
      return
    }

    // Use setTimeout to ensure state updates complete before navigation
    setTimeout(() => {
      window.location.href = started.url
    }, 100)
  }

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center py-8 px-4">
      <div className="container max-w-6xl">
        <div className="flex flex-col lg:flex-row items-center justify-between gap-8 lg:gap-16">
          {/* Right side broker form - Shown first on mobile */}
          <Card className="w-full max-w-md shadow-xl order-1 lg:order-2">
            <CardHeader className="text-center">
              <div className="flex justify-center mb-4">
                <img src="/logo.png" alt="OpenAlgo" className="h-20 w-20" />
              </div>
              <CardTitle className="text-2xl">Connect Your Trading Account</CardTitle>
              <CardDescription>
                Welcome, <span className="font-medium">{user?.username}</span>!
              </CardDescription>
            </CardHeader>
            <CardContent>
              {error && (
                <Alert variant="destructive" className="mb-4">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              {/* No broker configured yet: its keys are added in Profile. */}
              {!brokerConfig && !isLoading && (
                <Button asChild variant="outline" className="w-full mb-4">
                  <a href={BROKER_SETUP_PATH}>Configure broker</a>
                </Button>
              )}

              <form onSubmit={handleSubmit} className="space-y-6">
                <div className="space-y-2">
                  <Label htmlFor="broker-select" className="block text-center">
                    Login with your Broker
                  </Label>
                  <Select
                    value={selectedBroker}
                    onValueChange={handleBrokerChange}
                    disabled={isSubmitting}
                  >
                    <SelectTrigger id="broker-select" className="w-full">
                      <SelectValue placeholder="Select a Broker" />
                    </SelectTrigger>
                    <SelectContent>
                      {allBrokers
                        // Every configured broker, not only the active one.
                        .filter(
                          (broker) =>
                            broker.id === brokerConfig?.broker_name ||
                            configured.some((c) => c.name === broker.id)
                        )
                        .map((broker) => (
                          <SelectItem key={broker.id} value={broker.id}>
                            {broker.name}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>

                {(selectedBroker === 'zerodha' || selectedBroker === 'dhan') && (
                  <Alert className="border-amber-500/50 bg-amber-500/10">
                    <Info className="h-4 w-4 text-amber-500" />
                    <AlertDescription className="text-amber-700 dark:text-amber-400">
                      {selectedBroker === 'zerodha'
                        ? 'Zerodha requires an active Kite Connect data subscription for market data access.'
                        : 'Dhan requires an active Data API subscription for market data access.'}
                    </AlertDescription>
                  </Alert>
                )}

                <Button type="submit" className="w-full" disabled={!selectedBroker || isSubmitting}>
                  {isSubmitting ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Connecting...
                    </>
                  ) : (
                    <>
                      <ExternalLink className="mr-2 h-4 w-4" />
                      Connect Account
                    </>
                  )}
                </Button>
              </form>

              {/* Add or edit another broker's keys, then pick it above. */}
              {brokerConfig && (
                <div className="mt-4 text-center text-sm">
                  <a
                    href={BROKER_SETUP_PATH}
                    className="text-muted-foreground underline underline-offset-4 hover:text-foreground"
                  >
                    Configure another broker
                  </a>
                </div>
              )}

              <div className="mt-6 text-center text-sm">
                <BrokerAuthSignOut />
              </div>
            </CardContent>
          </Card>

          {/* Left side content - Shown second on mobile */}
          <div className="flex-1 max-w-xl text-center lg:text-left order-2 lg:order-1">
            <h1 className="text-4xl lg:text-5xl font-bold mb-6">
              Connect Your <span className="text-primary">Broker</span>
            </h1>
            <p className="text-lg lg:text-xl mb-8 text-muted-foreground">
              Link your trading account to start executing trades through OpenAlgo's algorithmic
              trading platform.
            </p>

            <Alert className="mb-6">
              <BookOpen className="h-4 w-4" />
              <AlertTitle>Need Help?</AlertTitle>
              <AlertDescription>Check our documentation for broker setup guides.</AlertDescription>
            </Alert>

            <div className="flex justify-center lg:justify-start gap-4">
              <Button variant="outline" asChild>
                <a href="https://docs.openalgo.in" target="_blank" rel="noopener noreferrer">
                  <BookOpen className="mr-2 h-4 w-4" />
                  Documentation
                </a>
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

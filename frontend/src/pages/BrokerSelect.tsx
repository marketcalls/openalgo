import { BookOpen, ExternalLink, Info, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
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
import { useAuthStore } from '@/stores/authStore'
import { buildBrokerLoginUrl, type BrokerConfig } from '@/utils/brokerLogin'

// All supported brokers with their display names and auth types
const allBrokers = [
  { id: 'fivepaisa', name: '5 Paisa', authType: 'totp' },
  { id: 'fivepaisaxts', name: '5 Paisa (XTS)', authType: 'totp' },
  { id: 'aliceblue', name: 'Alice Blue', authType: 'totp' },
  { id: 'angel', name: 'Angel One', authType: 'totp' },
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
  { id: 'samco', name: 'Samco', authType: 'totp' },
  { id: 'shoonya', name: 'Shoonya', authType: 'totp' },
  { id: 'tradejini', name: 'Tradejini', authType: 'totp' },
  { id: 'upstox', name: 'Upstox', authType: 'oauth' },
  { id: 'wisdom', name: 'Wisdom Capital', authType: 'totp' },
  { id: 'zebu', name: 'Zebu', authType: 'totp' },
  { id: 'zerodha', name: 'Zerodha', authType: 'oauth' },
] as const


export default function BrokerSelect() {
  const { user } = useAuthStore()
  const [selectedBroker, setSelectedBroker] = useState<string>('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [brokerConfig, setBrokerConfig] = useState<BrokerConfig | null>(null)

  useEffect(() => {
    // Fetch broker configuration
    const fetchBrokerConfig = async () => {
      try {
        const response = await fetch('/auth/broker-config', {
          credentials: 'include',
        })
        const data = await response.json()

        if (data.status === 'success') {
          setBrokerConfig(data)
          // Auto-select the configured broker
          setSelectedBroker(data.broker_name)
        } else {
          setError(data.message || 'Failed to load broker configuration')
        }
      } catch {
        setError('Failed to load broker configuration')
      } finally {
        setIsLoading(false)
      }
    }

    fetchBrokerConfig()
  }, [])

  const handleSubmit = (e: React.FormEvent) => {
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

    const loginUrl = buildBrokerLoginUrl(selectedBroker, brokerConfig)
    if (!loginUrl) {
      setError('Please select a broker')
      setIsSubmitting(false)
      return
    }

    setTimeout(() => {
      window.location.href = loginUrl
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

              <form onSubmit={handleSubmit} className="space-y-6">
                <div className="space-y-2">
                  <Label htmlFor="broker-select" className="block text-center">
                    Login with your Broker
                  </Label>
                  <Select
                    value={selectedBroker}
                    onValueChange={setSelectedBroker}
                    disabled={isSubmitting}
                  >
                    <SelectTrigger id="broker-select" className="w-full">
                      <SelectValue placeholder="Select a Broker" />
                    </SelectTrigger>
                    <SelectContent>
                      {allBrokers
                        .filter((broker) => broker.id === brokerConfig?.broker_name)
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
                    <AlertDescription className="text-amber-200">
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

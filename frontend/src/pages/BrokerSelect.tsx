import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Info, Loader2, Search, Settings } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import {
  BrokerConfigError,
  type BrokerEntry,
  brokerConfigApi,
  brokerStatus,
  sortBrokers,
} from '@/api/broker-config'
import { BrokerAuthSignOut } from '@/components/auth/BrokerAuthSignOut'
import { BrokerSwitchConfirm } from '@/components/auth/BrokerSwitchConfirm'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  BROKER_SETUP_PATH,
  brokerConfigPath,
  fetchLiveBroker,
  resumeBrokerSession,
  startBrokerLogin,
} from '@/lib/brokerProfiles'
import { useAuthStore } from '@/stores/authStore'
import { useBrokerStore } from '@/stores/brokerStore'

/**
 * Select Broker, a card per broker, as OpenAlgo Desktop has it.
 *
 * Keys can be saved for many brokers; one broker is logged in at a time.
 * "Login with" asks the server to start the sign-in (the broker's own site,
 * the in-app form, or one action with the saved keys). Logging in to another
 * broker while one is live asks first; the server ends that session only
 * when the new sign-in completes.
 */

/** Brokers whose market data needs a paid data subscription. */
const DATA_SUBSCRIPTION_NOTE: Record<string, string> = {
  zerodha: 'Zerodha requires an active Kite Connect data subscription for market data access.',
  dhan: 'Dhan requires an active Data API subscription for market data access.',
}

/**
 * The sentence for a refused broker login, which comes back here as
 * /broker?error=<code>&broker=<id>. Only these fixed sentences are shown: the
 * query string is set by whoever built the link, so its text never reaches
 * the page.
 */
const LOGIN_ERRORS: Record<string, string> = {
  login_not_started:
    'This broker login was not started from OpenAlgo, or it took longer than 10 minutes. Start the broker login again.',
  form_expired: 'This login form has expired. Reload the page and try again.',
  broker_unavailable:
    'This broker could not be logged in to right now. Check its keys under Broker Configuration, then try again.',
  // A login that completed while the logged-in broker still ran Live
  // automation: that broker stays logged in.
  switch_refused:
    'The broker you are logged in to still runs Live strategies or protection, so it stayed logged in. Stop them first, then switch.',
}
const LOGIN_FAILED = 'The broker login did not complete. Try again.'

function loginErrorMessage(code: string): string {
  return Object.hasOwn(LOGIN_ERRORS, code) ? LOGIN_ERRORS[code] : LOGIN_FAILED
}

function StatusBadge({ broker }: { broker: BrokerEntry }) {
  const status = brokerStatus(broker)
  if (status === 'Active') return <Badge className="bg-green-600 text-white">Active</Badge>
  if (status === 'Configured') return <Badge variant="secondary">Configured</Badge>
  return <Badge variant="outline">Not Configured</Badge>
}

export default function BrokerSelect() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [filter, setFilter] = useState('')
  const [starting, setStarting] = useState<string | null>(null)
  // The reason a sign-in failed, shown on that broker's card.
  const [cardError, setCardError] = useState<{ broker: string; message: string } | null>(null)
  const [pageError, setPageError] = useState<string | null>(null)
  // A login waiting for the trader to confirm ending the live session.
  const [pendingLogin, setPendingLogin] = useState<{ from: string; to: string } | null>(null)

  const list = useQuery({
    queryKey: ['broker-list'],
    queryFn: brokerConfigApi.list,
    staleTime: 0,
    retry: false,
  })

  // A broker sign-in that failed comes back here with a code for the reason
  // (`/broker?error=...&broker=...`).
  useEffect(() => {
    const code = searchParams.get('error')
    if (!code) return
    const message = loginErrorMessage(code)
    const broker = searchParams.get('broker')
    if (broker) setCardError({ broker, message })
    else setPageError(message)
    // Shown once: a reload does not bring the old reason back.
    setSearchParams({}, { replace: true })
  }, [searchParams, setSearchParams])

  useEffect(() => {
    if (list.error instanceof BrokerConfigError && list.error.status === 401) {
      navigate('/login', { replace: true })
    }
  }, [list.error, navigate])

  const brokers = useMemo(() => sortBrokers(list.data?.brokers ?? []), [list.data])
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return brokers
    return brokers.filter((b) => b.name.toLowerCase().includes(q) || b.id.includes(q))
  }, [brokers, filter])
  const nameOf = (id: string) => brokers.find((b) => b.id === id)?.name ?? id

  // A card error for a broker that is not listed shows at the top instead.
  useEffect(() => {
    if (cardError && list.data && !list.data.brokers.some((b) => b.id === cardError.broker)) {
      setPageError(cardError.message)
      setCardError(null)
    }
  }, [cardError, list.data])

  // Ask the server to start the sign-in; it answers with where it begins.
  const startSignIn = async (broker: BrokerEntry) => {
    setStarting(broker.id)
    setCardError(null)
    setPageError(null)
    // This sign-in may replace the logged-in broker's session: an answer
    // about the old session's capabilities still in flight must never be
    // applied after it.
    useBrokerStore.getState().clearCapabilities()
    const started = await startBrokerLogin(broker.id)
    if (started.error !== undefined) {
      setCardError({ broker: broker.id, message: started.error })
      setStarting(null)
      // Refused: the server says which broker is logged in now, not what
      // this page assumed.
      await refresh()
      void useBrokerStore.getState().fetchCapabilities()
      return
    }
    window.location.href = started.url
  }

  // One broker at a time. Logging in to another is confirmed first; the
  // server ends the live session only when the new sign-in completes, so
  // one that fails or is abandoned leaves the logged-in broker connected.
  const handleLogin = async (broker: BrokerEntry) => {
    const live = await fetchLiveBroker(list.data?.logged_in ?? null)
    if (live && live !== broker.id) {
      // Live automation or unsettled orders on the logged-in broker refuse
      // the switch outright (the server enforces it too): say why instead
      // of offering the confirm.
      const refusal = list.data?.switch_refusal
      if (refusal) {
        setCardError({ broker: broker.id, message: refusal })
        await refresh()
        return
      }
      setPendingLogin({ from: live, to: broker.id })
      return
    }
    await startSignIn(broker)
  }

  const confirmLogin = async () => {
    const pending = pendingLogin
    setPendingLogin(null)
    const broker = brokers.find((b) => b.id === pending?.to)
    if (!pending || !broker) return
    await startSignIn(broker)
  }

  // On the web the live broker may have been logged in from another device:
  // this browser joins that session before opening the dashboard.
  const openDashboard = async (broker: BrokerEntry) => {
    setStarting(broker.id)
    setCardError(null)
    const refusal = await resumeBrokerSession()
    if (refusal) {
      setCardError({ broker: broker.id, message: refusal })
      setStarting(null)
      await refresh()
      return
    }
    window.location.href = '/dashboard'
  }

  // Read the broker list again (which broker is logged in, which are saved).
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['broker-list'] })
  }

  if (list.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" aria-label="Loading brokers" />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background py-8 px-4">
      <div className="container mx-auto max-w-6xl space-y-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Select Broker</h1>
            <p className="text-sm text-muted-foreground">
              {user?.username ? (
                <>
                  Welcome, <span className="font-medium">{user.username}</span>.{' '}
                </>
              ) : null}
              Save keys for as many brokers as you like; one broker is logged in at a time.
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <Button asChild variant="outline" size="sm">
              <Link to={BROKER_SETUP_PATH}>
                <Settings className="mr-2 h-4 w-4" />
                Broker Configuration
              </Link>
            </Button>
            <Button asChild variant="ghost" size="sm">
              <a href="https://docs.openalgo.in" target="_blank" rel="noopener noreferrer">
                <BookOpen className="mr-2 h-4 w-4" />
                Documentation
              </a>
            </Button>
            <BrokerAuthSignOut />
          </div>
        </div>

        {(pageError || list.error) && (
          <Alert variant="destructive">
            <AlertDescription>
              {pageError ??
                (list.error instanceof Error
                  ? list.error.message
                  : 'Could not load your brokers. Try again.')}
            </AlertDescription>
          </Alert>
        )}

        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search brokers"
            placeholder="Search brokers"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="pl-9"
          />
        </div>

        {shown.length === 0 && !list.error && (
          <p className="text-sm text-muted-foreground">No broker matches "{filter}".</p>
        )}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((broker) => {
            const error = cardError?.broker === broker.id ? cardError.message : null
            const note = DATA_SUBSCRIPTION_NOTE[broker.id]
            return (
              <Card
                key={broker.id}
                data-testid={`broker-card-${broker.id}`}
                className="flex flex-col transition-shadow hover:shadow-md"
              >
                <CardHeader>
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle className="text-lg">{broker.name}</CardTitle>
                    <StatusBadge broker={broker} />
                  </div>
                  <CardDescription>
                    {broker.exchanges.length > 0
                      ? `Exchanges: ${broker.exchanges.join(', ')}`
                      : 'Exchanges: not listed'}
                  </CardDescription>
                </CardHeader>
                <CardContent className="mt-auto space-y-3">
                  {note && (broker.configured || broker.active) && (
                    <p className="flex gap-2 text-xs text-amber-700 dark:text-amber-400">
                      <Info className="h-4 w-4 shrink-0" />
                      {note}
                    </p>
                  )}
                  {error && (
                    <Alert variant="destructive" role="alert">
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}
                  {broker.active ? (
                    <Button
                      className="w-full"
                      onClick={() => openDashboard(broker)}
                      disabled={starting !== null}
                    >
                      {starting === broker.id ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Opening...
                        </>
                      ) : (
                        'Open Dashboard'
                      )}
                    </Button>
                  ) : broker.configured ? (
                    <Button
                      className="w-full"
                      onClick={() => handleLogin(broker)}
                      disabled={starting !== null}
                    >
                      {starting === broker.id ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Connecting...
                        </>
                      ) : (
                        `Login with ${broker.name}`
                      )}
                    </Button>
                  ) : (
                    <Button asChild variant="outline" className="w-full">
                      <Link to={brokerConfigPath(broker.id)}>Configure</Link>
                    </Button>
                  )}
                  {broker.configured && (
                    <div className="text-center text-xs">
                      <Link
                        to={brokerConfigPath(broker.id)}
                        className="text-muted-foreground underline underline-offset-4 hover:text-foreground"
                        aria-label={`Edit ${broker.name} keys`}
                      >
                        Edit keys
                      </Link>
                    </div>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      </div>

      <BrokerSwitchConfirm
        from={pendingLogin ? nameOf(pendingLogin.from) : null}
        to={pendingLogin ? nameOf(pendingLogin.to) : ''}
        onCancel={() => setPendingLogin(null)}
        onConfirm={confirmLogin}
      />
    </div>
  )
}

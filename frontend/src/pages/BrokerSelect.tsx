import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, ExternalLink, Info, KeyRound, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import {
  brokerQueryKeys,
  type ConfiguredBroker,
  endBrokerSession,
  getBrokerConfig,
  isSignedOut,
  retryUnlessRefused,
  serverMessage,
  startBrokerLogin,
} from '@/api/brokerKeys'
import { BrokerAuthSignOut } from '@/components/auth/BrokerAuthSignOut'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
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
import { brokerName } from '@/lib/brokers'
import { useAuthStore } from '@/stores/authStore'

const LOGIN_FAILED = 'The broker login could not be started. Try again.'
const END_FAILED = 'The broker session could not be ended. Try again.'
const CONFIG_FAILED = 'The broker list could not be loaded. Reload the page to try again.'

/**
 * The message for a refused broker callback, which lands here as
 * /broker?error=<code>. Only these fixed sentences are ever shown: the query
 * string is set by whoever built the link, so its text never reaches the page.
 */
const CALLBACK_ERRORS: Record<string, string> = {
  login_not_started:
    'This broker login was not started from OpenAlgo, or it took longer than 10 minutes. Start the broker login again.',
  broker_unavailable:
    'This broker cannot be used right now. Check its keys under Broker Keys. If another broker is logged in, end that session on this page first.',
  form_expired: 'This login form has expired. Reload the page and try again.',
}

function callbackErrorMessage(code: string | null): string | null {
  if (code === null) return null
  return Object.hasOwn(CALLBACK_ERRORS, code)
    ? CALLBACK_ERRORS[code]
    : 'The broker login did not complete. Try again.'
}

function brokerLabel(broker: ConfiguredBroker): string {
  const name = broker.name || brokerName(broker.broker)
  return broker.source === 'env' ? `${name} (from .env)` : name
}

export default function BrokerSelect() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  // The trader's own pick; until they make one the server's preselection holds.
  const [chosenBroker, setChosenBroker] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(() =>
    callbackErrorMessage(searchParams.get('error'))
  )
  const [notice, setNotice] = useState<string | null>(null)

  const configQuery = useQuery({
    queryKey: brokerQueryKeys.config(),
    queryFn: getBrokerConfig,
    retry: retryUnlessRefused,
  })
  const signedOut = configQuery.isError && isSignedOut(configQuery.error)

  useEffect(() => {
    if (signedOut) navigate('/login', { replace: true })
  }, [signedOut, navigate])

  const loginMutation = useMutation({
    mutationFn: startBrokerLogin,
    onSuccess: (url) => {
      window.location.href = url
    },
    onError: (err) => {
      if (isSignedOut(err)) {
        navigate('/login', { replace: true })
        return
      }
      setError(serverMessage(err, LOGIN_FAILED))
    },
  })

  // Ends the broker session another device holds, the same as logging out
  // there, so this browser can log in to a different broker.
  const endMutation = useMutation({
    mutationFn: endBrokerSession,
    onSuccess: (message) => {
      setNotice(message)
      // live_broker changed: re-read the login list and the keys page's badges.
      return queryClient.invalidateQueries({ queryKey: brokerQueryKeys.all })
    },
    onError: (err) => {
      if (isSignedOut(err)) {
        navigate('/login', { replace: true })
        return
      }
      setError(serverMessage(err, END_FAILED))
    },
  })

  const brokerConfig = configQuery.data ?? null
  const brokers: ConfiguredBroker[] = brokerConfig?.brokers ?? []
  const liveBroker = brokerConfig?.live_broker ?? null
  const selectedBroker =
    chosenBroker && brokers.some((b) => b.broker === chosenBroker)
      ? chosenBroker
      : brokerConfig?.broker_name || brokers[0]?.broker || ''
  // Stays set after a successful start, while the browser leaves for the broker.
  const isSubmitting = loginMutation.isPending || loginMutation.isSuccess
  const isEnding = endMutation.isPending
  const shownError =
    error ??
    (configQuery.isError && !signedOut ? serverMessage(configQuery.error, CONFIG_FAILED) : null)

  const nameOf = (id: string) => {
    const found = brokers.find((b) => b.broker === id)
    return found?.name || brokerName(id)
  }

  const endLiveSession = () => {
    setError(null)
    endMutation.mutate()
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    if (!selectedBroker) {
      setError('Choose a broker to log in to.')
      return
    }

    setError(null)
    loginMutation.mutate(selectedBroker)
  }

  const isLoading = configQuery.isPending || signedOut

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    )
  }

  const noBrokers = brokerConfig !== null && brokers.length === 0

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
              {shownError && (
                <Alert variant="destructive" className="mb-4">
                  <AlertDescription>{shownError}</AlertDescription>
                </Alert>
              )}
              {notice && !shownError && (
                <Alert className="mb-4">
                  <AlertDescription>{notice}</AlertDescription>
                </Alert>
              )}

              {noBrokers ? (
                <div className="space-y-4 text-center">
                  <div className="space-y-1">
                    <p className="font-medium">No broker is set up yet</p>
                    <p className="text-sm text-muted-foreground">
                      Save the API keys your broker gave you, then come back here to log in.
                    </p>
                  </div>
                  <Button asChild className="w-full">
                    <Link to="/broker/keys">
                      <KeyRound className="mr-2 h-4 w-4" />
                      Add broker keys
                    </Link>
                  </Button>
                </div>
              ) : (
                <>
                  <form onSubmit={handleSubmit} className="space-y-6">
                    <div className="space-y-2">
                      <Label htmlFor="broker-select" className="block text-center">
                        Login with your Broker
                      </Label>
                      <Select
                        value={selectedBroker}
                        onValueChange={(value) => {
                          setChosenBroker(value)
                          setError(null)
                        }}
                        disabled={isSubmitting}
                      >
                        <SelectTrigger id="broker-select" className="w-full">
                          <SelectValue placeholder="Select a Broker" />
                        </SelectTrigger>
                        <SelectContent>
                          {brokers.map((broker) => (
                            <SelectItem key={broker.broker} value={broker.broker}>
                              {brokerLabel(broker)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    {liveBroker && selectedBroker && liveBroker !== selectedBroker && (
                      <Alert>
                        <Info className="h-4 w-4" />
                        <AlertDescription className="space-y-3">
                          <p>
                            OpenAlgo is logged in to {nameOf(liveBroker)} on another device. To use
                            a different broker, log out of OpenAlgo on that device first, or end
                            that session here.
                          </p>
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={isEnding || isSubmitting}
                              >
                                {isEnding ? (
                                  <>
                                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                    Ending the session...
                                  </>
                                ) : (
                                  `End the ${nameOf(liveBroker)} session`
                                )}
                              </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>
                                  End the {nameOf(liveBroker)} session?
                                </AlertDialogTitle>
                                <AlertDialogDescription>
                                  Every device is logged out of OpenAlgo, the same as logging out
                                  there, and no order reaches {nameOf(liveBroker)} until you log in
                                  to a broker again. Positions and orders already at the broker are
                                  not affected. You stay signed in here.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Keep it</AlertDialogCancel>
                                <AlertDialogAction onClick={endLiveSession}>
                                  End the session
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </AlertDescription>
                      </Alert>
                    )}

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

                    <Button
                      type="submit"
                      className="w-full"
                      disabled={!selectedBroker || isSubmitting}
                    >
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

                  {brokerConfig && (
                    <div className="mt-4 text-center text-sm">
                      <Link
                        to="/broker/keys"
                        className="text-muted-foreground underline underline-offset-4 hover:text-foreground"
                      >
                        Manage broker keys
                      </Link>
                    </div>
                  )}
                </>
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

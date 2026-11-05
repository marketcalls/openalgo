import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, Loader2, RotateCcw, Save, Trash2 } from 'lucide-react'
import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import {
  BrokerConfigError,
  type BrokerEntry,
  type BrokerKeyField,
  type BrokerKeyName,
  type BrokerKeyUpdate,
  brokerConfigApi,
  brokerStatus,
} from '@/api/broker-config'
import { BrokerSwitchConfirm } from '@/components/auth/BrokerSwitchConfirm'
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
import { useAuthStore } from '@/stores/authStore'
import { useBrokerStore } from '@/stores/brokerStore'

/**
 * Broker Configuration, as OpenAlgo Desktop has it.
 *
 * One key set per broker, for as many brokers as the trader likes. The
 * server says which keys each broker needs and how that broker names them;
 * the page keeps no broker list of its own. Saved values are shown masked
 * and never returned in full; each key has a separate, empty replacement
 * input, and a blank one keeps what is saved. The broker the .env file
 * names keeps its keys there; the server saves them where they belong.
 */

const KEEP_HINT = 'Leave blank to keep the saved value.'

type Drafts = Partial<Record<BrokerKeyName, string>>

function FieldInput({
  field,
  value,
  onChange,
}: {
  field: BrokerKeyField
  value: string
  onChange: (v: string) => void
}) {
  const id = `broker-field-${field.key}`
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>
        {field.label}
        {!field.saved && !field.required && (
          <span className="ml-1 text-muted-foreground">(optional)</span>
        )}
      </Label>
      {field.saved && (
        <p className="text-xs" data-testid={`saved-${field.key}`}>
          <span className="text-muted-foreground">Saved: </span>
          <code className="break-all">{field.saved}</code>
        </p>
      )}
      <Input
        id={id}
        type={field.secret ? 'password' : 'text'}
        autoComplete="off"
        spellCheck={false}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={field.saved ? KEEP_HINT : `Enter ${field.label}`}
      />
      <p className="text-xs text-muted-foreground">
        {field.hint}
        {field.saved ? ` ${KEEP_HINT}` : ''}
      </p>
    </div>
  )
}

export default function BrokerConfig() {
  const navigate = useNavigate()
  const { user, setUser } = useAuthStore()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [selected, setSelected] = useState(() => searchParams.get('broker') ?? '')
  const selectedRef = useRef(selected)
  selectedRef.current = selected
  const [drafts, setDrafts] = useState<Drafts>({})
  // The redirect URL input, prefilled with the URL in use.
  const [redirectDraft, setRedirectDraft] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [confirmForget, setConfirmForget] = useState(false)
  const [confirmNewKeys, setConfirmNewKeys] = useState(false)
  const [forgetting, setForgetting] = useState(false)

  const list = useQuery({
    queryKey: ['broker-list'],
    queryFn: brokerConfigApi.list,
    staleTime: 0,
    retry: false,
  })

  useEffect(() => {
    if (list.error instanceof BrokerConfigError && list.error.status === 401) {
      navigate('/login', { replace: true })
    }
  }, [list.error, navigate])

  const brokers = useMemo(
    () => [...(list.data?.brokers ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [list.data]
  )
  const broker: BrokerEntry | undefined = brokers.find((b) => b.id === selected)

  // A `?broker=` that names no broker selects nothing.
  useEffect(() => {
    if (list.data && selected && !list.data.brokers.some((b) => b.id === selected)) {
      setSelected('')
    }
  }, [list.data, selected])

  // A different broker starts with empty drafts: nothing typed for one
  // broker is ever saved under another.
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset only when the broker changes.
  useEffect(() => {
    setDrafts({})
    setMessage(null)
    setError(null)
  }, [selected])

  // The redirect URL input shows the URL in use for this broker, again
  // after a save changes it.
  // biome-ignore lint/correctness/useExhaustiveDependencies: follow the broker and its saved URL.
  useEffect(() => {
    setRedirectDraft(broker?.redirect_url ?? '')
  }, [selected, broker?.redirect_url])

  const chooseBroker = (id: string) => {
    setSelected(id)
    setSearchParams(id ? { broker: id } : {}, { replace: true })
  }

  const redirectAutomatic = broker?.redirect_url_automatic ?? ''
  const redirectChanged =
    Boolean(broker?.redirect_url) && redirectDraft.trim() !== (broker?.redirect_url ?? '')

  const update = (): BrokerKeyUpdate => {
    const out: BrokerKeyUpdate = {}
    for (const f of broker?.fields ?? []) {
      const v = drafts[f.key]?.trim()
      if (v) out[f.key] = v
    }
    if (broker?.redirect_url && redirectChanged) {
      // An empty URL, or the automatic one typed in, means automatic.
      const v = redirectDraft.trim()
      out.redirect_url = v === redirectAutomatic ? '' : v
    }
    return out
  }
  const hasChanges = Object.keys(update()).length > 0

  const handleSave = async (e: FormEvent) => {
    e.preventDefault()
    if (!broker) return
    setMessage(null)
    setError(null)
    // A broker's first save needs every required key.
    if (!broker.configured) {
      const missing = broker.fields.find((f) => f.required && !drafts[f.key]?.trim())
      if (missing) {
        setError(`Enter the ${missing.label} to save ${broker.name}.`)
        return
      }
    }
    // New keys for the logged-in broker end its session (a session belongs
    // to the keys it signed in with), so the trader confirms first; a
    // redirect URL alone changes nothing live (FLOW-04).
    const changesKeys = broker.fields.some((f) => drafts[f.key]?.trim())
    if (broker.active && changesKeys) {
      setConfirmNewKeys(true)
      return
    }
    await saveNow(false)
  }

  const saveNow = async (signOut: boolean) => {
    if (!broker) return
    const forBroker = broker.id
    // The answer is shown only while the same broker is still selected.
    const stillHere = () => selectedRef.current === forBroker
    setSaving(true)
    try {
      const outcome = await brokerConfigApi.save(forBroker, update(), signOut)
      if (outcome.signed_out) endedLocally()
      if (stillHere()) {
        setDrafts({})
        setMessage(outcome.message)
      }
    } catch (err) {
      if (stillHere()) {
        setError(err instanceof Error ? err.message : 'Your keys were not saved. Try again.')
      }
    } finally {
      setSaving(false)
      // Whatever happened, show what the server holds now.
      await queryClient.invalidateQueries({ queryKey: ['broker-list'] })
    }
  }

  // The logged-in broker's session ended here: no broker is logged in now,
  // and the old session's capabilities must not linger (STATE-01).
  const endedLocally = () => {
    useBrokerStore.getState().clearCapabilities()
    if (user) setUser({ ...user, broker: null, isLoggedIn: false })
  }

  const handleForget = async () => {
    if (!broker) return
    setConfirmForget(false)
    setForgetting(true)
    setMessage(null)
    setError(null)
    try {
      const text = await brokerConfigApi.forget(broker.id, broker.active)
      // Forgetting the logged-in broker signed out of it: no broker is
      // logged in now, so the app's pages send the trader to Select Broker.
      if (broker.active) endedLocally()
      setDrafts({})
      setMessage(text)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The broker was not forgotten. Try again.')
    } finally {
      setForgetting(false)
      // Whatever happened, show what the server holds now.
      await queryClient.invalidateQueries({ queryKey: ['broker-list'] })
    }
  }

  if (list.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" aria-label="Loading brokers" />
      </div>
    )
  }

  const optionLabel = (b: BrokerEntry) => {
    const status = brokerStatus(b)
    return status === 'Not Configured' ? b.name : `${b.name} (${status})`
  }

  return (
    <div className="min-h-screen bg-background py-8 px-4">
      <div className="container mx-auto max-w-2xl space-y-6">
        <div className="space-y-2">
          <Link
            to="/broker"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Select Broker
          </Link>
          <h1 className="text-2xl font-bold tracking-tight">Broker Configuration</h1>
          <p className="text-sm text-muted-foreground">
            Save the keys for each broker you use. Keys stay saved per broker, so switching back to
            a broker needs only a login. One broker is logged in at a time.
          </p>
        </div>

        {list.error && !(list.error instanceof BrokerConfigError && list.error.status === 401) && (
          <Alert variant="destructive">
            <AlertDescription>
              {list.error instanceof Error
                ? list.error.message
                : 'Could not load your brokers. Try again.'}
            </AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader>
            <CardTitle>API Credentials</CardTitle>
            <CardDescription>Choose a broker, then enter the keys from its app.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSave} className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="broker-select">Broker</Label>
                <select
                  id="broker-select"
                  value={selected}
                  onChange={(e) => chooseBroker(e.target.value)}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:bg-input/30"
                >
                  <option value="">Select a broker...</option>
                  {brokers.map((b) => (
                    <option key={b.id} value={b.id}>
                      {optionLabel(b)}
                    </option>
                  ))}
                </select>
              </div>

              {broker && (
                <>
                  <div className="flex items-center gap-2">
                    {broker.active ? (
                      <Badge className="bg-green-600 text-white">Active</Badge>
                    ) : broker.configured ? (
                      <Badge variant="secondary">Configured</Badge>
                    ) : (
                      <Badge variant="outline">Not Configured</Badge>
                    )}
                  </div>

                  <div
                    className="rounded-md border bg-muted/40 p-3 text-sm text-muted-foreground"
                    data-testid="broker-banner"
                  >
                    {broker.banner}
                  </div>

                  {broker.fields.map((f) => (
                    <FieldInput
                      key={`${broker.id}-${f.key}`}
                      field={f}
                      value={drafts[f.key] ?? ''}
                      onChange={(v) => setDrafts((d) => ({ ...d, [f.key]: v }))}
                    />
                  ))}

                  {broker.redirect_url !== null && (
                    <div className="space-y-2">
                      <Label htmlFor="broker-redirect-url">Redirect URL</Label>
                      <Input
                        id="broker-redirect-url"
                        type="url"
                        spellCheck={false}
                        value={redirectDraft}
                        onChange={(e) => setRedirectDraft(e.target.value)}
                        placeholder={redirectAutomatic}
                      />
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-xs text-muted-foreground">
                          {redirectDraft.trim() === '' || redirectDraft.trim() === redirectAutomatic
                            ? 'Automatic: your Host Server URL.'
                            : 'Custom address.'}{' '}
                          {broker.redirect_hint}
                        </p>
                        {redirectDraft.trim() !== redirectAutomatic && (
                          <Button
                            type="button"
                            variant="link"
                            size="sm"
                            className="h-auto p-0"
                            onClick={() => setRedirectDraft(redirectAutomatic)}
                          >
                            <RotateCcw className="mr-1 h-3 w-3" />
                            Use automatic
                          </Button>
                        )}
                      </div>
                    </div>
                  )}

                  {message && (
                    <Alert role="status">
                      <AlertDescription>{message}</AlertDescription>
                    </Alert>
                  )}
                  {error && (
                    <Alert variant="destructive" role="alert">
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}

                  <div className="flex flex-wrap gap-3">
                    <Button type="submit" disabled={saving || !hasChanges}>
                      {saving ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <Save className="mr-2 h-4 w-4" />
                      )}
                      {saving ? 'Saving...' : 'Save'}
                    </Button>
                    {broker.configured && (
                      <Button
                        type="button"
                        variant="outline"
                        className="text-destructive"
                        disabled={forgetting}
                        onClick={() => setConfirmForget(true)}
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        Forget this broker
                      </Button>
                    )}
                    {broker.configured && !broker.active && (
                      <Button asChild type="button" variant="ghost">
                        <Link to="/broker">Log in</Link>
                      </Button>
                    )}
                  </div>
                </>
              )}
            </form>
          </CardContent>
        </Card>
      </div>

      <BrokerSwitchConfirm
        from={confirmNewKeys && broker ? broker.name : null}
        to={broker?.name ?? ''}
        cause="new-keys"
        onCancel={() => setConfirmNewKeys(false)}
        onConfirm={() => {
          setConfirmNewKeys(false)
          void saveNow(true)
        }}
      />

      <AlertDialog open={confirmForget} onOpenChange={setConfirmForget}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-yellow-500" />
              Forget {broker?.name}?
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3">
                {broker?.active && (
                  <p>
                    You are logged in to {broker.name} now. Forgetting it signs you out of{' '}
                    {broker.name} first. Open positions and orders stay with {broker.name}.
                  </p>
                )}
                <p>
                  This removes the saved {broker?.name} keys from OpenAlgo. To use {broker?.name}{' '}
                  again, enter its keys here again.
                </p>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleForget}>
              {broker?.active ? 'Sign out and forget' : 'Forget'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

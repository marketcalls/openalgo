import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Eye,
  EyeOff,
  FileKey,
  Import,
  Info,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-react'
import { useRef, useState } from 'react'
import { Link } from 'react-router'
import {
  type BrokerKeyEntry,
  brokerQueryKeys,
  getBrokerKeys,
  importEnvBrokerKeys,
  removeBrokerKeys,
  retryUnlessRefused,
  type SaveBrokerKeysBody,
  saveBrokerKeys,
  serverMessage,
} from '@/api/brokerKeys'
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
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { BROKER_KEY_FORMATS, brokerName } from '@/lib/brokers'
import { useAuthStore } from '@/stores/authStore'
import { showToast } from '@/utils/toast'

type FormMode = { kind: 'add' } | { kind: 'edit'; broker: string }

const LOAD_FAILED = 'Your broker keys could not be loaded. Try again.'
const SAVE_FAILED = 'The keys could not be saved. Try again.'
const REMOVE_FAILED = 'The keys could not be removed. Try again.'
const IMPORT_FAILED = 'The .env keys could not be copied. Try again.'

/** The server sends UTC with an offset; a timestamp without one is read as UTC too. */
function formatUpdatedAt(value: string | null | undefined): string | null {
  if (!value) return null
  const iso = /(?:[zZ]|[+-]\d\d:?\d\d)$/.test(value) ? value : `${value}Z`
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString()
}

function displayName(entry: { broker: string; name?: string }): string {
  return entry.name || brokerName(entry.broker)
}

function hasMarketKeys(entry: BrokerKeyEntry): boolean {
  return entry.api_key_market_set || entry.api_secret_market_set
}

function MaskedValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1 min-w-0">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <code className="block truncate text-xs">{value || 'Not set'}</code>
    </div>
  )
}

function MaskedKeys({ entry }: { entry: BrokerKeyEntry }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <MaskedValue label="API key" value={entry.api_key} />
      <MaskedValue label="API secret" value={entry.api_secret} />
      {hasMarketKeys(entry) && (
        <>
          <MaskedValue label="Market data API key" value={entry.api_key_market} />
          <MaskedValue label="Market data API secret" value={entry.api_secret_market} />
        </>
      )}
      <div className="space-y-1 min-w-0 sm:col-span-2">
        <div className="text-xs font-medium text-muted-foreground">Redirect URL</div>
        <code className="block text-xs break-all">{entry.redirect_url || 'Not set'}</code>
      </div>
    </div>
  )
}

interface SecretInputProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  placeholder: string
  disabled?: boolean
  hint?: React.ReactNode
}

/** A password input with a show and hide control. Hidden again whenever it remounts. */
function SecretInput({
  id,
  label,
  value,
  onChange,
  placeholder,
  disabled,
  hint,
}: SecretInputProps) {
  const [shown, setShown] = useState(false)
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        <Input
          id={id}
          type={shown ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
          className="pr-10"
        />
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="absolute right-1 top-1/2 -translate-y-1/2"
          aria-label={shown ? `Hide ${label}` : `Show ${label}`}
          aria-pressed={shown}
          onClick={() => setShown((s) => !s)}
          disabled={disabled}
        >
          {shown ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </Button>
      </div>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export default function BrokerKeys() {
  const { user, isAuthenticated } = useAuthStore()
  const queryClient = useQueryClient()

  // The add or edit form is UI state. Secrets live only here, and only until a save.
  const [mode, setMode] = useState<FormMode>({ kind: 'add' })
  const [addBroker, setAddBroker] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [apiKeyMarket, setApiKeyMarket] = useState('')
  const [apiSecretMarket, setApiSecretMarket] = useState('')
  // null follows the saved or default address for the broker in the form.
  const [redirectUrl, setRedirectUrl] = useState<string | null>(null)
  const [clearMarketKeys, setClearMarketKeys] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  // Bumped after a save so the inputs remount with their secrets hidden again.
  const [formKey, setFormKey] = useState(0)
  const formRef = useRef<HTMLDivElement>(null)

  // The target outlives the dialog's close so its title does not blank mid-animation.
  const [removeTarget, setRemoveTarget] = useState<BrokerKeyEntry | null>(null)
  const [removeOpen, setRemoveOpen] = useState(false)

  const brokerLoggedIn = isAuthenticated && Boolean(user?.broker)

  const keysQuery = useQuery({
    queryKey: brokerQueryKeys.keys(),
    queryFn: getBrokerKeys,
    retry: retryUnlessRefused,
  })

  // Every change re-reads the keys, and marks the broker login list stale too,
  // since it lists the brokers that have keys. Returned, so a mutation stays
  // pending until the keys are re-read and no button comes back on stale data.
  const refreshBrokers = () => queryClient.invalidateQueries({ queryKey: brokerQueryKeys.all })

  // The body carries secrets, so this mutation must not keep it: gcTime 0 drops
  // the settled mutation from the cache, and handleSave resets the observer.
  const saveMutation = useMutation({
    mutationFn: saveBrokerKeys,
    gcTime: 0,
    onSuccess: refreshBrokers,
  })

  const removeMutation = useMutation({
    mutationFn: removeBrokerKeys,
    onSuccess: refreshBrokers,
  })

  const importMutation = useMutation({
    mutationFn: importEnvBrokerKeys,
    onSuccess: async (message) => {
      showToast.success(message || 'Copied the .env keys into OpenAlgo.')
      await refreshBrokers()
    },
    onError: (err) => showToast.error(serverMessage(err, IMPORT_FAILED)),
  })

  const isSaving = saveMutation.isPending
  const isRemoving = removeMutation.isPending
  const isImporting = importMutation.isPending

  const clearSecrets = () => {
    setApiKey('')
    setApiSecret('')
    setApiKeyMarket('')
    setApiSecretMarket('')
    setClearMarketKeys(false)
    setFormKey((k) => k + 1)
  }

  const startAdd = () => {
    clearSecrets()
    setMode({ kind: 'add' })
    setAddBroker('')
    setRedirectUrl(null)
    setFormError(null)
  }

  const startEdit = (entry: BrokerKeyEntry) => {
    clearSecrets()
    setMode({ kind: 'edit', broker: entry.broker })
    setRedirectUrl(null)
    setFormError(null)
    formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (keysQuery.isPending) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    )
  }

  const data = keysQuery.data
  const loadError = keysQuery.isError ? serverMessage(keysQuery.error, LOAD_FAILED) : null
  const saved = data?.brokers ?? []
  const env = data?.env ?? null
  const liveBroker = data?.live_broker ?? null
  const addable = (data?.enabled_brokers ?? []).filter(
    (b) => !saved.some((s) => s.broker === b.broker)
  )
  const editing = mode.kind === 'edit' ? saved.find((s) => s.broker === mode.broker) : undefined
  const isEdit = mode.kind === 'edit' && editing !== undefined
  // In add mode the broker defaults to the first one without saved keys.
  const formBroker = isEdit
    ? editing.broker
    : addable.some((b) => b.broker === addBroker)
      ? addBroker
      : (addable[0]?.broker ?? '')
  const formBrokerName = isEdit
    ? displayName(editing)
    : displayName(addable.find((b) => b.broker === formBroker) ?? { broker: formBroker })
  const savedRedirectUrl =
    (isEdit ? editing.redirect_url : null) ?? data?.default_redirect_urls[formBroker] ?? ''
  const shownRedirectUrl = redirectUrl ?? savedRedirectUrl
  const keyFormat = BROKER_KEY_FORMATS[formBroker]
  const canClearMarket = isEdit && hasMarketKeys(editing)

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    if (!formBroker) return
    const typedKey = apiKey.trim()
    if (!isEdit && !typedKey) {
      setFormError('Enter the API key to save this broker.')
      return
    }

    // Only what the trader typed goes to the server; a field left out keeps the
    // saved value. That includes the redirect URL, sent only when changed.
    const body: SaveBrokerKeysBody = { broker: formBroker }
    if (typedKey) body.api_key = typedKey
    if (apiSecret.trim()) body.api_secret = apiSecret.trim()
    if (clearMarketKeys && canClearMarket) {
      // The market inputs are disabled while this is ticked; whatever they held
      // before is not what the trader is asking for now.
      body.clear_market_keys = true
    } else {
      if (apiKeyMarket.trim()) body.api_key_market = apiKeyMarket.trim()
      if (apiSecretMarket.trim()) body.api_secret_market = apiSecretMarket.trim()
    }
    if (shownRedirectUrl.trim() !== savedRedirectUrl.trim()) {
      body.redirect_url = shownRedirectUrl.trim()
    }

    setFormError(null)
    const brokerTitle = formBrokerName
    saveMutation.mutate(body, {
      onSuccess: (message) => {
        showToast.success(message || `Saved the ${brokerTitle} keys.`)
        // Nothing that was submitted stays on screen or in memory.
        startAdd()
      },
      onError: (err) => setFormError(serverMessage(err, SAVE_FAILED)),
      // Detach from the settled mutation so its variables (the body) are not
      // held by this component; with gcTime 0 the cache lets go of it as well.
      onSettled: () => saveMutation.reset(),
    })
  }

  const handleRemove = () => {
    if (!removeTarget) return
    const target = removeTarget
    removeMutation.mutate(target.broker, {
      onSuccess: (message) => {
        showToast.success(message || `Removed the ${displayName(target)} keys.`)
        if (mode.kind === 'edit' && mode.broker === target.broker) startAdd()
      },
      onError: (err) => showToast.error(serverMessage(err, REMOVE_FAILED)),
      onSettled: () => setRemoveOpen(false),
    })
  }

  const envAlsoSaved = env !== null && saved.some((s) => s.broker === env.broker)

  return (
    <div className="min-h-screen bg-background py-8 px-4">
      <div className="container max-w-4xl mx-auto space-y-6">
        <Button variant="ghost" size="sm" asChild>
          <Link to={brokerLoggedIn ? '/dashboard' : '/broker'}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            {brokerLoggedIn ? 'Back to dashboard' : 'Back to broker login'}
          </Link>
        </Button>

        <div className="flex items-start gap-4">
          <div className="h-12 w-12 shrink-0 rounded-full bg-primary/10 flex items-center justify-center">
            <KeyRound className="h-6 w-6 text-primary" />
          </div>
          <div className="space-y-1">
            <h1 className="text-3xl font-bold">Broker Keys</h1>
            <p className="text-muted-foreground">
              Save the API keys of every broker you use. You log in to one broker at a time and
              choose which when you connect.
            </p>
          </div>
        </div>

        {loadError && (
          <Alert variant="destructive">
            <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
              <span>{loadError}</span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => keysQuery.refetch()}
                disabled={keysQuery.isFetching}
              >
                Try again
              </Button>
            </AlertDescription>
          </Alert>
        )}

        {data && (
          <>
            {env && (
              <Card className="shadow-sm">
                <CardHeader>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <CardTitle className="flex items-center gap-2">
                        <FileKey className="h-5 w-5" />
                        {displayName(env)}
                      </CardTitle>
                      <CardDescription>
                        The .env file comes first, so OpenAlgo always uses these keys for{' '}
                        {displayName(env)}. Change them by editing the .env file.
                      </CardDescription>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="secondary">From .env file</Badge>
                      {liveBroker === env.broker && <Badge>Logged in</Badge>}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <MaskedKeys entry={env} />
                  <div className="flex flex-col gap-3 rounded-md border bg-muted/30 p-3 sm:flex-row sm:items-center sm:justify-between">
                    <p className="text-sm text-muted-foreground">
                      Copy these keys into OpenAlgo as the first step to moving off the .env file.
                      OpenAlgo keeps using the .env keys until you remove them from .env.
                      {envAlsoSaved &&
                        ` This replaces the ${displayName(env)} keys already saved in OpenAlgo.`}
                    </p>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => importMutation.mutate()}
                      disabled={isImporting}
                      className="shrink-0"
                    >
                      {isImporting ? (
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      ) : (
                        <Import className="h-4 w-4 mr-2" />
                      )}
                      Copy to OpenAlgo
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}

            <Card className="shadow-sm">
              <CardHeader>
                <CardTitle>Saved in OpenAlgo</CardTitle>
                <CardDescription>
                  Stored encrypted. A secret is never shown again; an API key shows its first few
                  characters.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {saved.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No broker keys are saved in OpenAlgo yet. Add your first broker below.
                  </p>
                ) : (
                  saved.map((entry) => {
                    const name = displayName(entry)
                    const isLive = liveBroker === entry.broker
                    const enabled = entry.enabled !== false
                    const updated = formatUpdatedAt(entry.updated_at)
                    return (
                      <article
                        key={entry.broker}
                        aria-label={`${name} keys`}
                        className="rounded-md border p-4 space-y-3"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="space-y-1 min-w-0">
                            <div className="font-semibold">{name}</div>
                            <div className="flex flex-wrap gap-2">
                              {isLive && <Badge>Logged in</Badge>}
                              {entry.overridden_by_env && (
                                <Badge variant="outline">
                                  Not used while .env sets this broker
                                </Badge>
                              )}
                              {!enabled && (
                                <Badge variant="destructive">Not enabled in VALID_BROKERS</Badge>
                              )}
                            </div>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => startEdit(entry)}
                              disabled={isLive || !enabled}
                              aria-label={`Edit ${name} keys`}
                            >
                              <Pencil className="h-4 w-4 mr-1" />
                              Edit
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              className="text-destructive hover:text-destructive"
                              onClick={() => {
                                setRemoveTarget(entry)
                                setRemoveOpen(true)
                              }}
                              disabled={isLive}
                              aria-label={`Remove ${name} keys`}
                            >
                              <Trash2 className="h-4 w-4 mr-1" />
                              Remove
                            </Button>
                          </div>
                        </div>
                        <MaskedKeys entry={entry} />
                        {isLive ? (
                          <p className="text-xs text-muted-foreground">
                            OpenAlgo is logged in to {name}. Log out first to change or remove its
                            keys.
                          </p>
                        ) : (
                          !enabled && (
                            <p className="text-xs text-muted-foreground">
                              Add {entry.broker} to VALID_BROKERS in the .env file to log in with or
                              edit these keys.
                            </p>
                          )
                        )}
                        {updated && (
                          <p className="text-xs text-muted-foreground">Last changed {updated}</p>
                        )}
                      </article>
                    )
                  })
                )}
              </CardContent>
            </Card>

            <div ref={formRef}>
              <Card className="shadow-xl">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    {isEdit ? <Pencil className="h-5 w-5" /> : <Plus className="h-5 w-5" />}
                    {isEdit ? `Edit ${formBrokerName} keys` : 'Add a broker'}
                  </CardTitle>
                  <CardDescription>
                    {isEdit
                      ? 'Leave a field empty to keep the saved value.'
                      : "Paste the keys from your broker's developer console. OpenAlgo stores them encrypted."}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {!isEdit && addable.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      Every broker in VALID_BROKERS already has keys saved. Use Edit above to change
                      them.
                    </p>
                  ) : (
                    <form key={formKey} onSubmit={handleSave} className="space-y-5">
                      <div className="space-y-2">
                        <Label htmlFor="broker-keys-broker">Broker</Label>
                        <Select
                          value={formBroker}
                          onValueChange={(value) => {
                            setAddBroker(value)
                            setRedirectUrl(null)
                            setFormError(null)
                          }}
                          disabled={isEdit || isSaving}
                        >
                          <SelectTrigger id="broker-keys-broker" className="w-full">
                            <SelectValue placeholder="Select a broker" />
                          </SelectTrigger>
                          <SelectContent>
                            {isEdit ? (
                              <SelectItem value={editing.broker}>{formBrokerName}</SelectItem>
                            ) : (
                              addable.map((b) => (
                                <SelectItem key={b.broker} value={b.broker}>
                                  {displayName(b)}
                                </SelectItem>
                              ))
                            )}
                          </SelectContent>
                        </Select>
                      </div>

                      {!isEdit && env && formBroker === env.broker && (
                        <Alert>
                          <Info className="h-4 w-4" />
                          <AlertDescription>
                            The .env file sets keys for {formBrokerName}, so OpenAlgo uses those
                            until you remove them from .env.
                          </AlertDescription>
                        </Alert>
                      )}

                      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <SecretInput
                          id="broker-keys-api-key"
                          label="API key"
                          value={apiKey}
                          onChange={setApiKey}
                          placeholder={
                            isEdit ? 'Leave empty to keep the saved value' : 'Enter the API key'
                          }
                          disabled={isSaving}
                          hint={
                            keyFormat ? (
                              <>
                                Format: <code>{keyFormat}</code>
                              </>
                            ) : undefined
                          }
                        />
                        <SecretInput
                          id="broker-keys-api-secret"
                          label="API secret"
                          value={apiSecret}
                          onChange={setApiSecret}
                          placeholder={
                            isEdit ? 'Leave empty to keep the saved value' : 'Enter the API secret'
                          }
                          disabled={isSaving}
                        />
                      </div>

                      <fieldset className="space-y-3 rounded-md border p-4">
                        <legend className="px-1 text-sm font-medium">
                          Market data keys (optional)
                        </legend>
                        <p className="text-xs text-muted-foreground">
                          Only for XTS brokers such as 5 Paisa XTS and Jainam XTS.
                        </p>
                        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                          <SecretInput
                            id="broker-keys-api-key-market"
                            label="Market data API key"
                            value={apiKeyMarket}
                            onChange={setApiKeyMarket}
                            placeholder={
                              isEdit && editing.api_key_market_set
                                ? 'Leave empty to keep the saved value'
                                : 'Enter the market data API key'
                            }
                            disabled={isSaving || (canClearMarket && clearMarketKeys)}
                          />
                          <SecretInput
                            id="broker-keys-api-secret-market"
                            label="Market data API secret"
                            value={apiSecretMarket}
                            onChange={setApiSecretMarket}
                            placeholder={
                              isEdit && editing.api_secret_market_set
                                ? 'Leave empty to keep the saved value'
                                : 'Enter the market data API secret'
                            }
                            disabled={isSaving || (canClearMarket && clearMarketKeys)}
                          />
                        </div>
                        {canClearMarket && (
                          <div className="flex items-center gap-2">
                            <Checkbox
                              id="broker-keys-clear-market"
                              checked={clearMarketKeys}
                              onCheckedChange={(checked) => setClearMarketKeys(checked === true)}
                              disabled={isSaving}
                            />
                            <Label htmlFor="broker-keys-clear-market" className="font-normal">
                              Remove saved market data keys
                            </Label>
                          </div>
                        )}
                      </fieldset>

                      <div className="space-y-2">
                        <Label htmlFor="broker-keys-redirect">Redirect URL</Label>
                        <Input
                          id="broker-keys-redirect"
                          type="text"
                          inputMode="url"
                          value={shownRedirectUrl}
                          onChange={(e) => setRedirectUrl(e.target.value)}
                          disabled={isSaving}
                          autoComplete="off"
                          spellCheck={false}
                        />
                        <p className="text-xs text-muted-foreground">
                          Register this exact address as the redirect URL in your broker's developer
                          console.
                        </p>
                      </div>

                      {formError && (
                        <Alert variant="destructive">
                          <AlertTitle>Not saved</AlertTitle>
                          <AlertDescription>{formError}</AlertDescription>
                        </Alert>
                      )}

                      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                        {isEdit && (
                          <Button
                            type="button"
                            variant="outline"
                            onClick={startAdd}
                            disabled={isSaving}
                          >
                            Cancel
                          </Button>
                        )}
                        <Button type="submit" disabled={!formBroker || isSaving}>
                          {isSaving ? (
                            <>
                              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                              Saving...
                            </>
                          ) : (
                            <>
                              <KeyRound className="h-4 w-4 mr-2" />
                              Save keys
                            </>
                          )}
                        </Button>
                      </div>
                    </form>
                  )}
                </CardContent>
              </Card>
            </div>
          </>
        )}
      </div>

      <AlertDialog
        open={removeOpen}
        onOpenChange={(open) => {
          if (!open && !isRemoving) setRemoveOpen(false)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Remove the {removeTarget ? displayName(removeTarget) : ''} keys?
            </AlertDialogTitle>
            <AlertDialogDescription>
              OpenAlgo forgets the keys saved for{' '}
              {removeTarget ? displayName(removeTarget) : 'this broker'}. You can add them again at
              any time.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isRemoving}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-white hover:bg-destructive/90"
              disabled={isRemoving}
              onClick={(e) => {
                // Keep the dialog open until the server answers.
                e.preventDefault()
                handleRemove()
              }}
            >
              {isRemoving ? 'Removing...' : 'Remove'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

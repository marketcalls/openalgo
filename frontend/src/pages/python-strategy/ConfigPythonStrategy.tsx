import { ArrowLeft, Braces, Save, Settings2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { pythonStrategyApi } from '@/api/python-strategy'
import { Alert, AlertDescription } from '@/components/ui/alert'
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
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import type { OCSField, OCSOption, OCSSchema, PythonStrategy } from '@/types/python-strategy'
import { showToast } from '@/utils/toast'

const emptySchema = (strategyId: string): OCSSchema => ({
  ocs_version: '1.0',
  strategy: strategyId,
  title: 'Strategy Configuration',
  description: '',
  fields: [],
})

const optionValue = (option: string | number | boolean | OCSOption) =>
  typeof option === 'object' ? option.value : option

const optionLabel = (option: string | number | boolean | OCSOption) =>
  typeof option === 'object' ? option.label || String(option.value) : String(option)

const fieldInputType = (field: OCSField) => {
  if (field.type === 'password') return 'password'
  if (['int', 'float', 'quantity', 'lot_size', 'percentage', 'price', 'trigger_price', 'strike'].includes(field.type)) {
    return 'number'
  }
  if (field.type === 'date' || field.type === 'time' || field.type === 'color') return field.type
  return 'text'
}

const coerceValue = (field: OCSField, value: string | boolean | string[]) => {
  if (field.type === 'bool') return Boolean(value)
  if (field.type === 'multi_select') return value
  if (fieldInputType(field) === 'number') {
    if (value === '') return ''
    return field.type === 'int' || field.type === 'quantity' || field.type === 'lot_size' || field.type === 'strike'
      ? Number.parseInt(String(value), 10)
      : Number.parseFloat(String(value))
  }
  if (field.type === 'json') {
    try {
      return JSON.parse(String(value || '{}'))
    } catch (_error) {
      return value
    }
  }
  return value
}

export default function ConfigPythonStrategy() {
  const { strategyId } = useParams<{ strategyId: string }>()
  const navigate = useNavigate()
  const [strategy, setStrategy] = useState<PythonStrategy | null>(null)
  const [schema, setSchema] = useState<OCSSchema | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [draftValues, setDraftValues] = useState<Record<string, string>>({})
  const [schemaText, setSchemaText] = useState('')
  const [loading, setLoading] = useState(true)
  const [savingValues, setSavingValues] = useState(false)
  const [savingSchema, setSavingSchema] = useState(false)
  const [error, setError] = useState('')

  const isRunning = strategy?.status === 'running'

  const groupedFields = useMemo(() => {
    const fields = schema?.fields || []
    return fields.reduce<Record<string, OCSField[]>>((groups, field) => {
      const group = field.group || field.section || 'General'
      groups[group] = [...(groups[group] || []), field]
      return groups
    }, {})
  }, [schema])

  const fetchData = async () => {
    if (!strategyId) return
    try {
      setLoading(true)
      const [strategyData, configData] = await Promise.all([
        pythonStrategyApi.getStrategy(strategyId),
        pythonStrategyApi.getConfig(strategyId),
      ])
      const loadedSchema = configData.schema || emptySchema(strategyId)
      setStrategy(strategyData)
      setSchema(loadedSchema)
      setValues(configData.resolved_values || configData.values || {})
      setDraftValues({})
      setSchemaText(JSON.stringify(loadedSchema, null, 2))
    } catch (_error) {
      showToast.error('Failed to load configuration', 'pythonStrategy')
      navigate('/python')
    } finally {
      setLoading(false)
    }
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time fetch for current route id
  useEffect(() => {
    fetchData()
  }, [])

  const updateValue = (field: OCSField, value: string | boolean | string[]) => {
    setValues((current) => ({ ...current, [field.key]: coerceValue(field, value) }))
  }

  const updateNumberValue = (field: OCSField, value: string) => {
    setDraftValues((current) => ({ ...current, [field.key]: value }))

    if (value === '' || value === '-' || value === '.' || value === '-.' || value.endsWith('.')) {
      return
    }

    const parsed =
      field.type === 'int' || field.type === 'quantity' || field.type === 'lot_size' || field.type === 'strike'
        ? Number.parseInt(value, 10)
        : Number.parseFloat(value)

    if (!Number.isNaN(parsed)) {
      setValues((current) => ({ ...current, [field.key]: parsed }))
    }
  }

  const saveValues = async () => {
    if (!strategyId || isRunning) return
    try {
      setSavingValues(true)
      setError('')
      const response = await pythonStrategyApi.saveConfigValues(strategyId, values)
      if (response.status === 'success') {
        showToast.success('Configuration saved', 'pythonStrategy')
      } else {
        setError(response.message || 'Failed to save configuration')
      }
    } catch (err: unknown) {
      const axiosError = err as { response?: { data?: { message?: string } } }
      setError(axiosError.response?.data?.message || 'Failed to save configuration')
    } finally {
      setSavingValues(false)
    }
  }

  const saveSchema = async () => {
    if (!strategyId || isRunning) return
    try {
      setSavingSchema(true)
      setError('')
      const parsed = JSON.parse(schemaText) as OCSSchema
      const response = await pythonStrategyApi.saveConfigSchema(strategyId, parsed)
      if (response.status === 'success') {
        const nextSchema = response.data?.schema || parsed
        setSchema(nextSchema)
        setSchemaText(JSON.stringify(nextSchema, null, 2))
        showToast.success('Configuration schema saved', 'pythonStrategy')
        fetchData()
      } else {
        setError(response.message || 'Failed to save schema')
      }
    } catch (err: unknown) {
      if (err instanceof SyntaxError) {
        setError('Schema JSON is invalid')
      } else {
        const axiosError = err as { response?: { data?: { message?: string } } }
        setError(axiosError.response?.data?.message || 'Failed to save schema')
      }
    } finally {
      setSavingSchema(false)
    }
  }

  const renderField = (field: OCSField) => {
    const currentValue = values[field.key]
    const id = `ocs-${field.key}`

    if (field.type === 'bool') {
      return (
        <div key={field.key} className="flex items-center justify-between gap-4 rounded border p-3">
          <div className="space-y-1">
            <Label htmlFor={id}>{field.label}</Label>
            {field.description && <p className="text-xs text-muted-foreground">{field.description}</p>}
          </div>
          <Switch
            id={id}
            checked={Boolean(currentValue)}
            onCheckedChange={(checked) => updateValue(field, checked)}
            disabled={isRunning}
          />
        </div>
      )
    }

    if (field.type === 'select' || field.type === 'exchange' || field.type === 'product' || field.type === 'option_type') {
      return (
        <div key={field.key} className="space-y-2">
          <Label htmlFor={id}>{field.label}</Label>
          <Select
            value={currentValue == null ? '' : String(currentValue)}
            onValueChange={(value) => updateValue(field, value)}
            disabled={isRunning}
          >
            <SelectTrigger id={id}>
              <SelectValue placeholder={field.placeholder || 'Select'} />
            </SelectTrigger>
            <SelectContent>
              {(field.options || []).map((option) => (
                <SelectItem key={String(optionValue(option))} value={String(optionValue(option))}>
                  {optionLabel(option)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {field.description && <p className="text-xs text-muted-foreground">{field.description}</p>}
        </div>
      )
    }

    if (field.type === 'multi_select') {
      const selected = Array.isArray(currentValue) ? currentValue.map(String) : []
      return (
        <div key={field.key} className="space-y-2">
          <Label>{field.label}</Label>
          <div className="grid gap-2 rounded border p-3 sm:grid-cols-2">
            {(field.options || []).map((option) => {
              const value = String(optionValue(option))
              return (
                <label key={value} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={selected.includes(value)}
                    onCheckedChange={(checked) => {
                      const next = checked
                        ? [...selected, value]
                        : selected.filter((item) => item !== value)
                      updateValue(field, next)
                    }}
                    disabled={isRunning}
                  />
                  {optionLabel(option)}
                </label>
              )
            })}
          </div>
          {field.description && <p className="text-xs text-muted-foreground">{field.description}</p>}
        </div>
      )
    }

    if (field.type === 'json') {
      return (
        <div key={field.key} className="space-y-2">
          <Label htmlFor={id}>{field.label}</Label>
          <Textarea
            id={id}
            value={typeof currentValue === 'string' ? currentValue : JSON.stringify(currentValue ?? {}, null, 2)}
            onChange={(event) => updateValue(field, event.target.value)}
            disabled={isRunning}
            className="min-h-28 font-mono text-xs"
          />
          {field.description && <p className="text-xs text-muted-foreground">{field.description}</p>}
        </div>
      )
    }

    return (
      <div key={field.key} className="space-y-2">
        <Label htmlFor={id}>{field.label}</Label>
        <Input
          id={id}
          type={fieldInputType(field)}
          value={
            fieldInputType(field) === 'number' && field.key in draftValues
              ? draftValues[field.key]
              : currentValue == null
                ? ''
                : String(currentValue)
          }
          min={field.min}
          max={field.max}
          step={field.step}
          placeholder={field.placeholder}
          onChange={(event) =>
            fieldInputType(field) === 'number'
              ? updateNumberValue(field, event.target.value)
              : updateValue(field, event.target.value)
          }
          disabled={isRunning}
        />
        {field.description && <p className="text-xs text-muted-foreground">{field.description}</p>}
      </div>
    )
  }

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  if (!strategy || !schema || !strategyId) return null

  return (
    <div className="container mx-auto py-6 space-y-6 max-w-4xl">
      <Button variant="ghost" asChild>
        <Link to="/python">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Python Strategies
        </Link>
      </Button>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Settings2 className="h-6 w-6" />
            Strategy Configuration
          </h1>
          <p className="text-muted-foreground">{strategy.name}</p>
        </div>
      </div>

      {isRunning && (
        <Alert>
          <AlertDescription>
            This strategy is running. Stop it before changing configuration.
          </AlertDescription>
        </Alert>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Tabs defaultValue="values">
        <TabsList>
          <TabsTrigger value="values">Values</TabsTrigger>
          <TabsTrigger value="schema">Schema</TabsTrigger>
        </TabsList>

        <TabsContent value="values" className="space-y-4">
          {schema.fields.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Braces className="h-10 w-10 mx-auto text-muted-foreground mb-3" />
                <h2 className="font-semibold mb-1">No configuration fields</h2>
                <p className="text-sm text-muted-foreground">
                  Add fields in the Schema tab to generate this form.
                </p>
              </CardContent>
            </Card>
          ) : (
            <>
              {Object.entries(groupedFields).map(([group, fields]) => (
                <Card key={group}>
                  <CardHeader>
                    <CardTitle className="text-base">{group}</CardTitle>
                    {schema.description && group === 'General' && (
                      <CardDescription>{schema.description}</CardDescription>
                    )}
                  </CardHeader>
                  <CardContent className="grid gap-4">{fields.map(renderField)}</CardContent>
                </Card>
              ))}
              <div className="flex justify-end">
                <Button onClick={saveValues} disabled={savingValues || isRunning}>
                  <Save className="h-4 w-4 mr-2" />
                  {savingValues ? 'Saving...' : 'Save Values'}
                </Button>
              </div>
            </>
          )}
        </TabsContent>

        <TabsContent value="schema" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">OCS Schema JSON</CardTitle>
              <CardDescription>
                Defines fields rendered in the generated configuration form.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Textarea
                value={schemaText}
                onChange={(event) => setSchemaText(event.target.value)}
                disabled={isRunning}
                className="min-h-[420px] font-mono text-xs"
              />
              <div className="flex justify-end">
                <Button onClick={saveSchema} disabled={savingSchema || isRunning}>
                  <Save className="h-4 w-4 mr-2" />
                  {savingSchema ? 'Saving...' : 'Save Schema'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

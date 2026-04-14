import { AlertTriangle, ArrowLeft, ExternalLink, Loader2, Shield } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { fetchCSRFToken } from '@/api/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuthStore } from '@/stores/authStore'

// Field configuration type
interface FieldConfig {
  name: string
  label: string
  type: string
  placeholder: string
  pattern?: string
  maxLength?: number
  inputMode?: 'numeric' | 'text' | 'tel'
  prefix?: string
  hint?: string
  optional?: boolean
}

interface BrokerConfig {
  fields: FieldConfig[]
  callbackUrl?: string
  warning?: string
  hiddenFields?: Record<string, string>
}

// Broker-specific field configurations
const brokerFields: Record<string, BrokerConfig> = {
  fivepaisa: {
    fields: [
      {
        name: 'userid',
        label: 'Client ID / Mobile No',
        type: 'text',
        placeholder: 'Enter Client ID or Mobile Number',
      },
      { name: 'pin', label: 'PIN', type: 'password', placeholder: 'Enter your PIN' },
      {
        name: 'totp',
        label: 'TOTP',
        type: 'password',
        placeholder: 'Enter 6-digit TOTP',
        maxLength: 6,
        pattern: '[0-9]{6}',
        inputMode: 'numeric',
      },
    ],
    callbackUrl: '/fivepaisa/callback',
  },
  aliceblue: {
    fields: [
      {
        name: 'userid',
        label: 'User ID',
        type: 'text',
        placeholder: 'Enter your User ID (alphanumeric)',
      },
    ],
    callbackUrl: '/aliceblue/callback',
  },
  angel: {
    fields: [
      { name: 'userid', label: 'Client ID', type: 'text', placeholder: 'Enter your Client ID' },
      { name: 'pin', label: 'PIN', type: 'password', placeholder: 'Enter your PIN (min 4 digits)' },
      {
        name: 'totp',
        label: 'TOTP',
        type: 'text',
        placeholder: 'Enter 6-digit TOTP',
        maxLength: 6,
        pattern: '[0-9]{6}',
        inputMode: 'numeric',
        hint: 'Get TOTP from your authenticator app',
      },
    ],
    callbackUrl: '/angel/callback',
  },
  definedge: {
    fields: [
      {
        name: 'otp',
        label: 'OTP',
        type: 'password',
        placeholder: 'Enter OTP sent to your registered mobile/email',
        inputMode: 'numeric',
        hint: 'OTP has been sent to your registered mobile/email',
      },
    ],
    callbackUrl: '/definedge/callback',
  },
  firstock: {
    fields: [
      { name: 'userid', label: 'User ID', type: 'text', placeholder: 'Enter your User ID' },
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      {
        name: 'totp',
        label: 'TOTP',
        type: 'password',
        placeholder: 'Enter 6-digit TOTP',
        maxLength: 6,
        pattern: '[0-9]{6}',
        inputMode: 'numeric',
        hint: 'Get TOTP from your authenticator app',
      },
    ],
    callbackUrl: '/firstock/callback',
  },
  kotak: {
    fields: [
      {
        name: 'mobile',
        label: 'Mobile Number',
        type: 'tel',
        placeholder: 'Enter 10-digit mobile number',
        maxLength: 10,
        pattern: '[0-9]{10}',
        inputMode: 'numeric',
        prefix: '+91',
        hint: 'Mobile number registered with Kotak NEO',
      },
      {
        name: 'mpin',
        label: 'MPIN',
        type: 'password',
        placeholder: 'Enter 6-digit MPIN',
        maxLength: 6,
        pattern: '[0-9]{6}',
        inputMode: 'numeric',
      },
      {
        name: 'totp',
        label: 'TOTP Code',
        type: 'text',
        placeholder: 'Enter 6-digit TOTP',
        maxLength: 6,
        pattern: '[0-9]{6}',
        inputMode: 'numeric',
      },
    ],
    callbackUrl: '/kotak/callback',
    warning:
      'Make sure TOTP is registered in your Kotak NEO mobile app. Go to Settings > Security > Enable TOTP.',
  },
  motilal: {
    fields: [
      { name: 'userid', label: 'User ID', type: 'text', placeholder: 'Enter your User ID' },
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      {
        name: 'dob',
        label: 'Date of Birth',
        type: 'text',
        placeholder: 'DD/MM/YYYY',
        hint: 'Format: DD/MM/YYYY',
      },
      {
        name: 'totp',
        label: 'TOTP',
        type: 'password',
        placeholder: 'Enter TOTP (optional)',
        maxLength: 6,
        optional: true,
        hint: 'Leave blank to receive OTP via SMS/Email',
      },
    ],
    callbackUrl: '/motilal/callback',
  },
  mstock: {
    fields: [
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      {
        name: 'totp',
        label: 'TOTP',
        type: 'text',
        placeholder: 'Enter 6-digit TOTP',
        maxLength: 6,
        pattern: '[0-9]{6}',
        inputMode: 'numeric',
      },
    ],
    callbackUrl: '/mstock/callback',
  },
  nubra: {
    fields: [
      {
        name: 'totp',
        label: 'TOTP Code',
        type: 'text',
        placeholder: 'Enter 6-digit TOTP',
        maxLength: 6,
        pattern: '[0-9]{6}',
        inputMode: 'numeric',
        hint: 'Enter the 6-digit code from your authenticator app',
      },
    ],
    callbackUrl: '/nubra/callback',
  },
  samco: {
    fields: [
      {
        name: 'yob',
        label: 'Year of Birth',
        type: 'text',
        placeholder: 'YYYY',
        maxLength: 4,
        pattern: '[0-9]{4}',
        inputMode: 'numeric',
        hint: 'Client ID and Password are configured in environment',
      },
    ],
    callbackUrl: '/samco/callback',
  },
  shoonya: {
    fields: [
      { name: 'userid', label: 'User ID', type: 'text', placeholder: 'Enter your User ID' },
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      {
        name: 'totp',
        label: 'TOTP',
        type: 'password',
        placeholder: 'Enter 6-digit TOTP',
        maxLength: 6,
        pattern: '[0-9]{6}',
        inputMode: 'numeric',
        hint: 'Get TOTP from your authenticator app',
      },
    ],
    callbackUrl: '/shoonya/callback',
  },
  tradejini: {
    fields: [
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      {
        name: 'twofa',
        label: '2FA Code / TOTP',
        type: 'text',
        placeholder: 'Enter your 2FA code or TOTP',
        hint: 'You can get TOTP from Tradejini web app under Profile > Security',
      },
    ],
    callbackUrl: '/tradejini/callback',
    hiddenFields: { twofatype: 'totp' },
  },
  zebu: {
    fields: [
      { name: 'userid', label: 'User ID', type: 'text', placeholder: 'Enter your User ID' },
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      {
        name: 'totp',
        label: 'TOTP / DOB / PAN',
        type: 'password',
        placeholder: 'Enter TOTP (6 digits), DOB (DDMMYYYY), or PAN',
        hint: 'Enter 6-digit TOTP, Date of Birth (DDMMYYYY), or PAN number',
      },
    ],
    callbackUrl: '/zebu/callback',
  },
  default: {
    fields: [
      { name: 'userid', label: 'User ID', type: 'text', placeholder: 'Enter your User ID' },
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      {
        name: 'totp',
        label: 'TOTP',
        type: 'text',
        placeholder: 'Enter 6-digit TOTP',
        maxLength: 6,
        pattern: '[0-9]{6}',
        inputMode: 'numeric',
      },
    ],
  },
}

const brokerNames: Record<string, string> = {
  fivepaisa: '5Paisa',
  '5paisa': '5Paisa',
  aliceblue: 'AliceBlue',
  angel: 'Angel One',
  definedge: 'Definedge Securities',
  firstock: 'Firstock',
  kotak: 'Kotak NEO',
  motilal: 'Motilal Oswal',
  mstock: 'MStock',
  nubra: 'Nubra (Nuvama)',
  samco: 'Samco',
  shoonya: 'Shoonya',
  tradejini: 'Tradejini',
  zebu: 'Zebu',
  jmfinancial: 'JM Financial',
}

export default function BrokerTOTP() {
  const { broker } = useParams<{ broker: string }>()
  const navigate = useNavigate()
  const { login } = useAuthStore()
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [formData, setFormData] = useState<Record<string, string>>({})

  // Normalize broker name (handle 5paisa -> fivepaisa)
  const normalizedBroker = broker === '5paisa' ? 'fivepaisa' : broker
  const config =
    normalizedBroker && brokerFields[normalizedBroker]
      ? brokerFields[normalizedBroker]
      : brokerFields.default
  const brokerName = broker
    ? brokerNames[broker] || brokerNames[normalizedBroker || ''] || broker
    : 'Broker'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setError(null)

    // Validate broker parameter
    if (!broker && !normalizedBroker) {
      setError('Invalid broker selected.')
      setIsLoading(false)
      return
    }

    // Validate required fields (skip optional fields)
    const requiredFields = config.fields.filter((f) => !f.optional).map((f) => f.name)
    const missingFields = requiredFields.filter((f) => !formData[f]?.trim())
    if (missingFields.length > 0) {
      setError('Please fill in all required fields.')
      setIsLoading(false)
      return
    }

    try {
      const csrfToken = await fetchCSRFToken()

      const form = new FormData()

      // Add form fields
      Object.entries(formData).forEach(([key, value]) => {
        // Special handling for Kotak mobile - add +91 prefix
        if (normalizedBroker === 'kotak' && key === 'mobile') {
          form.append(key, `+91${value.trim()}`)
        } else {
          form.append(key, value.trim())
        }
      })

      // Add hidden fields if any
      if (config.hiddenFields) {
        Object.entries(config.hiddenFields).forEach(([key, value]) => {
          form.append(key, value)
        })
      }

      form.append('csrf_token', csrfToken)

      // Use custom callback URL or default pattern
      const callbackUrl = config.callbackUrl || `/${broker}/callback`

      const response = await fetch(callbackUrl, {
        method: 'POST',
        body: form,
        credentials: 'include',
      })

      const data = await response.json()

      if (data.status === 'success' || response.ok) {
        login(formData.userid || formData.mobile || '', broker || '')
        showToast.success('Authentication successful')
        navigate('/dashboard')
      } else {
        setError(data.message || 'Authentication failed. Please try again.')
      }
    } catch {
      setError('Authentication failed. Please check your credentials and try again.')
    } finally {
      setIsLoading(false)
    }
  }

  const handleInputChange = (name: string, value: string, field: FieldConfig) => {
    // Apply input filtering based on field type
    let filteredValue = value

    if (field.inputMode === 'numeric') {
      filteredValue = value.replace(/\D/g, '')
    }

    if (field.maxLength) {
      filteredValue = filteredValue.slice(0, field.maxLength)
    }

    setFormData((prev) => ({ ...prev, [name]: filteredValue }))
  }

  return (
    <div className="min-h-screen flex items-center justify-center py-8 px-4">
      <div className="container max-w-md">
        <Card className="shadow-xl">
          <CardHeader className="text-center relative">
            <Button
              variant="ghost"
              size="sm"
              className="absolute left-4 top-4"
              onClick={() => navigate('/broker')}
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back
            </Button>
            <div className="flex justify-center mb-4 pt-6">
              <div className="h-16 w-16 rounded-full bg-primary/10 flex items-center justify-center">
                <Shield className="h-8 w-8 text-primary" />
              </div>
            </div>
            <CardTitle className="text-2xl">{brokerName} Login</CardTitle>
            <CardDescription>
              Enter your credentials to authenticate with {brokerName}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {/* Warning Alert if present */}
            {config.warning && (
              <Alert variant="warning" className="mb-4">
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>{config.warning}</AlertDescription>
              </Alert>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              {config.fields.map((field) => (
                <div key={field.name} className="space-y-2">
                  <Label htmlFor={field.name}>
                    {field.label}
                    {field.optional && (
                      <span className="text-muted-foreground ml-1">(optional)</span>
                    )}
                  </Label>
                  <div className="relative">
                    {field.prefix && (
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                        {field.prefix}
                      </span>
                    )}
                    <Input
                      id={field.name}
                      type={field.type}
                      inputMode={field.inputMode}
                      placeholder={field.placeholder}
                      value={formData[field.name] || ''}
                      onChange={(e) => handleInputChange(field.name, e.target.value, field)}
                      required={!field.optional}
                      disabled={isLoading}
                      maxLength={field.maxLength}
                      pattern={field.pattern}
                      autoComplete={
                        field.type === 'password'
                          ? 'current-password'
                          : field.inputMode === 'numeric'
                            ? 'one-time-code'
                            : 'off'
                      }
                      className={field.prefix ? 'pl-12' : ''}
                    />
                  </div>
                  {field.hint && <p className="text-xs text-muted-foreground">{field.hint}</p>}
                </div>
              ))}

              {error && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              <Button type="submit" className="w-full" disabled={isLoading}>
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Authenticating...
                  </>
                ) : (
                  <>
                    <Shield className="mr-2 h-4 w-4" />
                    Authenticate
                  </>
                )}
              </Button>
            </form>

            <div className="mt-6 space-y-3 text-center text-sm text-muted-foreground">
              <p>Your credentials are securely transmitted and encrypted.</p>
              <div className="flex items-center justify-center gap-4">
                <Link
                  to="/broker"
                  className="text-primary hover:underline inline-flex items-center gap-1"
                >
                  <ArrowLeft className="h-3 w-3" />
                  Back to Broker Selection
                </Link>
                <a
                  href="https://docs.openalgo.in"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline inline-flex items-center gap-1"
                >
                  Documentation
                  <ExternalLink className="h-3 w-3" />
                </a>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

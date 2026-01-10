import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Loader2, ArrowLeft, Shield } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useAuthStore } from '@/stores/authStore';
import { toast } from 'sonner';

// Broker-specific field configurations
const brokerFields: Record<string, { fields: { name: string; label: string; type: string; placeholder: string }[] }> = {
  angel: {
    fields: [
      { name: 'userid', label: 'Client ID', type: 'text', placeholder: 'Enter your Client ID' },
      { name: 'password', label: 'PIN', type: 'password', placeholder: 'Enter your PIN' },
      { name: 'totp', label: 'TOTP', type: 'text', placeholder: 'Enter 6-digit TOTP' },
    ],
  },
  shoonya: {
    fields: [
      { name: 'userid', label: 'User ID', type: 'text', placeholder: 'Enter your User ID' },
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      { name: 'totp', label: 'TOTP', type: 'text', placeholder: 'Enter 6-digit TOTP' },
    ],
  },
  firstock: {
    fields: [
      { name: 'userid', label: 'User ID', type: 'text', placeholder: 'Enter your User ID' },
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      { name: 'totp', label: 'TOTP', type: 'text', placeholder: 'Enter 6-digit TOTP' },
    ],
  },
  kotak: {
    fields: [
      { name: 'userid', label: 'User ID', type: 'text', placeholder: 'Enter your User ID' },
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      { name: 'totp', label: 'TOTP', type: 'text', placeholder: 'Enter 6-digit TOTP' },
    ],
  },
  motilal: {
    fields: [
      { name: 'userid', label: 'Client Code', type: 'text', placeholder: 'Enter your Client Code' },
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      { name: 'totp', label: 'TOTP', type: 'text', placeholder: 'Enter 6-digit TOTP' },
    ],
  },
  '5paisa': {
    fields: [
      { name: 'userid', label: 'Client Code', type: 'text', placeholder: 'Enter your Client Code' },
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      { name: 'totp', label: 'TOTP', type: 'text', placeholder: 'Enter 6-digit TOTP' },
    ],
  },
  aliceblue: {
    fields: [
      { name: 'userid', label: 'User ID', type: 'text', placeholder: 'Enter your User ID' },
      { name: 'totp', label: 'TOTP', type: 'text', placeholder: 'Enter 6-digit TOTP' },
    ],
  },
  default: {
    fields: [
      { name: 'userid', label: 'User ID', type: 'text', placeholder: 'Enter your User ID' },
      { name: 'password', label: 'Password', type: 'password', placeholder: 'Enter your Password' },
      { name: 'totp', label: 'TOTP', type: 'text', placeholder: 'Enter 6-digit TOTP' },
    ],
  },
};

const brokerNames: Record<string, string> = {
  angel: 'Angel One',
  shoonya: 'Shoonya',
  firstock: 'Firstock',
  kotak: 'Kotak',
  motilal: 'Motilal Oswal',
  '5paisa': '5Paisa',
  aliceblue: 'AliceBlue',
  mstock: 'MStock',
  nubra: 'Nubra (Nuvama)',
  samco: 'Samco',
  tradejini: 'Tradejini',
  zebu: 'Zebu',
  jmfinancial: 'JM Financial',
  definedge: 'Definedge',
};

export default function BrokerTOTP() {
  const { broker } = useParams<{ broker: string }>();
  const navigate = useNavigate();
  const { login } = useAuthStore();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formData, setFormData] = useState<Record<string, string>>({});

  const config = broker && brokerFields[broker] ? brokerFields[broker] : brokerFields.default;
  const brokerName = broker ? brokerNames[broker] || broker : 'Broker';

  // List of valid brokers for validation
  const validBrokers = Object.keys(brokerFields);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    // Validate broker parameter
    if (!broker || (!validBrokers.includes(broker) && broker !== 'default')) {
      setError('Invalid broker selected.');
      setIsLoading(false);
      return;
    }

    // Validate required fields
    const requiredFields = config.fields.map(f => f.name);
    const missingFields = requiredFields.filter(f => !formData[f]?.trim());
    if (missingFields.length > 0) {
      setError('Please fill in all required fields.');
      setIsLoading(false);
      return;
    }

    try {
      // First, fetch CSRF token
      const csrfResponse = await fetch('/auth/csrf-token', {
        credentials: 'include',
      });
      const csrfData = await csrfResponse.json();

      const form = new FormData();
      Object.entries(formData).forEach(([key, value]) => {
        form.append(key, value.trim());
      });
      form.append('csrf_token', csrfData.csrf_token);

      const response = await fetch(`/${broker}/auth`, {
        method: 'POST',
        body: form,
        credentials: 'include', // Include cookies for session
      });

      const data = await response.json();

      if (data.status === 'success' || response.ok) {
        login(formData.userid || '', broker || '');
        toast.success('Authentication successful');
        navigate('/dashboard');
      } else {
        setError(data.message || 'Authentication failed. Please try again.');
      }
    } catch (err) {
      console.error('Broker auth error:', err);
      setError('Authentication failed. Please check your credentials and try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleInputChange = (name: string, value: string) => {
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  return (
    <div className="min-h-screen flex items-center justify-center py-8 px-4">
      <div className="container max-w-md">
        <Card className="shadow-xl">
          <CardHeader className="text-center">
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
            <form onSubmit={handleSubmit} className="space-y-4">
              {config.fields.map((field) => (
                <div key={field.name} className="space-y-2">
                  <Label htmlFor={field.name}>{field.label}</Label>
                  <Input
                    id={field.name}
                    type={field.type}
                    placeholder={field.placeholder}
                    value={formData[field.name] || ''}
                    onChange={(e) => handleInputChange(field.name, e.target.value)}
                    required
                    disabled={isLoading}
                    autoComplete={field.type === 'password' ? 'current-password' : 'off'}
                  />
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

            <div className="mt-4 text-center text-sm text-muted-foreground">
              <p>
                Your credentials are securely transmitted and encrypted.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

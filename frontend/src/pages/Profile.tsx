import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  User,
  ArrowLeft,
  Lock,
  Palette,
  Mail,
  Shield,
  Check,
  X,
  Copy,
  Send,
  Bug,
  RefreshCw,
  Sun,
  Moon,
  AlertCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs';
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from '@/components/ui/alert';
import { toast } from 'sonner';
import { webClient } from '@/api/client';
import { useAuthStore } from '@/stores/authStore';
import { useThemeStore, type ThemeMode, type ThemeColor } from '@/stores/themeStore';

// Professional themes suitable for trading terminals
const THEME_MODES: { value: ThemeMode; label: string; icon: typeof Sun; description: string }[] = [
  { value: 'light', label: 'Light', icon: Sun, description: 'Clean, bright interface for daytime trading' },
  { value: 'dark', label: 'Dark', icon: Moon, description: 'Reduced eye strain for extended sessions' },
];

// Accent colors for customization
const ACCENT_COLORS: { value: ThemeColor; label: string; color: string }[] = [
  { value: 'zinc', label: 'Zinc', color: 'bg-zinc-500' },
  { value: 'slate', label: 'Slate', color: 'bg-slate-500' },
  { value: 'gray', label: 'Gray', color: 'bg-gray-500' },
  { value: 'neutral', label: 'Neutral', color: 'bg-neutral-500' },
  { value: 'green', label: 'Green', color: 'bg-green-500' },
  { value: 'blue', label: 'Blue', color: 'bg-blue-500' },
  { value: 'violet', label: 'Violet', color: 'bg-violet-500' },
  { value: 'orange', label: 'Orange', color: 'bg-orange-500' },
];

interface ProfileData {
  username: string;
  smtp_settings: {
    smtp_server: string;
    smtp_port: number;
    smtp_username: string;
    smtp_password: boolean;
    smtp_use_tls: boolean;
    smtp_from_email: string;
    smtp_helo_hostname: string;
  } | null;
  qr_code: string | null;
  totp_secret: string | null;
}

interface PasswordRequirements {
  length: boolean;
  uppercase: boolean;
  lowercase: boolean;
  number: boolean;
  special: boolean;
}

export default function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const { mode, color, appMode, setMode, setColor } = useThemeStore();
  const [activeTab, setActiveTab] = useState('account');
  const [isLoading, setIsLoading] = useState(true);
  const [profileData, setProfileData] = useState<ProfileData | null>(null);

  // Password form state
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordRequirements, setPasswordRequirements] = useState<PasswordRequirements>({
    length: false,
    uppercase: false,
    lowercase: false,
    number: false,
    special: false,
  });
  const [isChangingPassword, setIsChangingPassword] = useState(false);

  // SMTP form state
  const [smtpServer, setSmtpServer] = useState('smtp.gmail.com');
  const [smtpPort, setSmtpPort] = useState('587');
  const [smtpUsername, setSmtpUsername] = useState('');
  const [smtpPassword, setSmtpPassword] = useState('');
  const [smtpFromEmail, setSmtpFromEmail] = useState('');
  const [smtpHeloHostname, setSmtpHeloHostname] = useState('smtp.gmail.com');
  const [smtpUseTls, setSmtpUseTls] = useState(true);
  const [isSavingSmtp, setIsSavingSmtp] = useState(false);
  const [testEmail, setTestEmail] = useState('');
  const [isSendingTest, setIsSendingTest] = useState(false);
  const [isDebugging, setIsDebugging] = useState(false);
  const [debugResult, setDebugResult] = useState<{success: boolean; message: string; details?: string[]} | null>(null);

  // Check if in analyzer mode (theme changes blocked)
  const isAnalyzerMode = appMode === 'analyzer';

  useEffect(() => {
    fetchProfileData();
  }, []);

  const fetchProfileData = async () => {
    try {
      const response = await webClient.get<{ status: string; data: ProfileData }>('/auth/profile-data');
      if (response.data.status === 'success') {
        setProfileData(response.data.data);

        // Populate SMTP form with existing settings
        const smtp = response.data.data.smtp_settings;
        if (smtp) {
          setSmtpServer(smtp.smtp_server || 'smtp.gmail.com');
          setSmtpPort(String(smtp.smtp_port || 587));
          setSmtpUsername(smtp.smtp_username || '');
          setSmtpFromEmail(smtp.smtp_from_email || '');
          setSmtpHeloHostname(smtp.smtp_helo_hostname || 'smtp.gmail.com');
          setSmtpUseTls(smtp.smtp_use_tls !== false);
          setTestEmail(smtp.smtp_username || '');
        }
      }
    } catch (error) {
      console.error('Error fetching profile data:', error);
      toast.error('Failed to load profile data');
    } finally {
      setIsLoading(false);
    }
  };

  // Password validation
  const checkPasswordRequirements = useCallback((password: string) => {
    const requirements: PasswordRequirements = {
      length: password.length >= 8,
      uppercase: /[A-Z]/.test(password),
      lowercase: /[a-z]/.test(password),
      number: /[0-9]/.test(password),
      special: /[!@#$%^&*]/.test(password),
    };
    setPasswordRequirements(requirements);
    return Object.values(requirements).every(Boolean);
  }, []);

  useEffect(() => {
    checkPasswordRequirements(newPassword);
  }, [newPassword, checkPasswordRequirements]);

  const getPasswordStrength = () => {
    const metCount = Object.values(passwordRequirements).filter(Boolean).length;
    if (metCount === 0) return { percentage: 0, label: 'None', color: 'bg-gray-400' };
    if (metCount <= 2) return { percentage: 40, label: 'Weak', color: 'bg-red-500' };
    if (metCount <= 3) return { percentage: 60, label: 'Fair', color: 'bg-yellow-500' };
    if (metCount <= 4) return { percentage: 80, label: 'Good', color: 'bg-blue-500' };
    return { percentage: 100, label: 'Strong', color: 'bg-green-500' };
  };

  const passwordsMatch = newPassword === confirmPassword && confirmPassword !== '';
  const meetsAllRequirements = Object.values(passwordRequirements).every(Boolean);
  const canSubmitPassword = passwordsMatch && meetsAllRequirements && oldPassword !== '';

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmitPassword) return;

    setIsChangingPassword(true);
    try {
      const formData = new FormData();
      formData.append('old_password', oldPassword);
      formData.append('new_password', newPassword);
      formData.append('confirm_password', confirmPassword);

      const response = await webClient.post<{ status: string; message: string }>('/auth/change-password', formData);

      if (response.data.status === 'success') {
        toast.success(response.data.message || 'Password changed successfully');
        setOldPassword('');
        setNewPassword('');
        setConfirmPassword('');
      } else {
        toast.error(response.data.message || 'Failed to change password');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      toast.error(err.response?.data?.message || 'Failed to change password');
    } finally {
      setIsChangingPassword(false);
    }
  };

  const handleSaveSmtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingSmtp(true);
    try {
      const formData = new FormData();
      formData.append('smtp_server', smtpServer);
      formData.append('smtp_port', smtpPort);
      formData.append('smtp_username', smtpUsername);
      if (smtpPassword) {
        formData.append('smtp_password', smtpPassword);
      }
      formData.append('smtp_from_email', smtpFromEmail);
      formData.append('smtp_helo_hostname', smtpHeloHostname);
      if (smtpUseTls) {
        formData.append('smtp_use_tls', 'on');
      }

      const response = await webClient.post<{ status: string; message: string }>('/auth/smtp-config', formData);

      if (response.data.status === 'success') {
        toast.success(response.data.message || 'SMTP settings saved successfully');
        setSmtpPassword(''); // Clear password field after save
      } else {
        toast.error(response.data.message || 'Failed to save SMTP settings');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      toast.error(err.response?.data?.message || 'Failed to save SMTP settings');
    } finally {
      setIsSavingSmtp(false);
    }
  };

  const handleTestEmail = async () => {
    if (!testEmail) {
      toast.error('Please enter an email address to test');
      return;
    }

    setIsSendingTest(true);
    setDebugResult(null);
    try {
      const formData = new FormData();
      formData.append('test_email', testEmail);

      const response = await webClient.post<{ success: boolean; message: string }>('/auth/test-smtp', formData);

      if (response.data.success) {
        toast.success(response.data.message || 'Test email sent successfully');
      } else {
        toast.error(response.data.message || 'Failed to send test email');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      toast.error(err.response?.data?.message || 'Failed to send test email');
    } finally {
      setIsSendingTest(false);
    }
  };

  const handleDebugSmtp = async () => {
    setIsDebugging(true);
    setDebugResult(null);
    try {
      const response = await webClient.post<{ success: boolean; message: string; details?: string[] }>('/auth/debug-smtp', {});
      setDebugResult(response.data);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } };
      setDebugResult({
        success: false,
        message: err.response?.data?.message || 'Failed to debug SMTP',
        details: [],
      });
    } finally {
      setIsDebugging(false);
    }
  };

  const handleThemeModeChange = (newMode: ThemeMode) => {
    if (isAnalyzerMode) {
      toast.error('Cannot change theme while in Analyzer Mode');
      return;
    }
    setMode(newMode);
    toast.success(`Theme changed to ${newMode}`);
  };

  const handleAccentColorChange = (newColor: ThemeColor) => {
    if (isAnalyzerMode) {
      toast.error('Cannot change theme while in Analyzer Mode');
      return;
    }
    setColor(newColor);
    toast.success(`Accent color changed to ${newColor}`);
  };

  const handleResetTheme = () => {
    if (isAnalyzerMode) {
      toast.error('Cannot change theme while in Analyzer Mode');
      return;
    }
    setMode('light');
    setColor('zinc');
    toast.success('Theme reset to default');
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text).then(() => {
      toast.success('Copied to clipboard');
    }).catch(() => {
      toast.error('Failed to copy');
    });
  };

  const strength = getPasswordStrength();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <div className="py-6 max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Link to="/dashboard" className="text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <User className="h-6 w-6" />
            Profile Settings
          </h1>
        </div>
        <p className="text-muted-foreground">
          Manage your account settings and security preferences
        </p>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="account" className="gap-1">
            <Lock className="h-4 w-4" />
            <span className="hidden sm:inline">Account</span>
          </TabsTrigger>
          <TabsTrigger value="theme" className="gap-1">
            <Palette className="h-4 w-4" />
            <span className="hidden sm:inline">Theme</span>
          </TabsTrigger>
          <TabsTrigger value="smtp" className="gap-1">
            <Mail className="h-4 w-4" />
            <span className="hidden sm:inline">SMTP</span>
          </TabsTrigger>
          <TabsTrigger value="totp" className="gap-1">
            <Shield className="h-4 w-4" />
            <span className="hidden sm:inline">TOTP</span>
          </TabsTrigger>
        </TabsList>

        {/* Account Tab */}
        <TabsContent value="account" className="space-y-6">
          {/* Account Info */}
          <Card>
            <CardHeader>
              <CardTitle>Account Information</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Username</Label>
                <Input value={user?.username || profileData?.username || ''} disabled />
              </div>
              <div className="space-y-2">
                <Label>Account Type</Label>
                <div className="pt-2">
                  <Badge>Administrator</Badge>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Password Change */}
          <Card>
            <CardHeader>
              <CardTitle>Change Password</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleChangePassword} className="space-y-4">
                <div className="space-y-2">
                  <Label>Current Password</Label>
                  <Input
                    type="password"
                    placeholder="Enter your current password"
                    value={oldPassword}
                    onChange={(e) => setOldPassword(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label>New Password</Label>
                  <Input
                    type="password"
                    placeholder="Enter your new password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label>Confirm New Password</Label>
                  <Input
                    type="password"
                    placeholder="Confirm your new password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                  />
                  {confirmPassword && (
                    <p className={`text-sm ${passwordsMatch ? 'text-green-500' : 'text-red-500'}`}>
                      {passwordsMatch ? 'Passwords match' : 'Passwords do not match'}
                    </p>
                  )}
                </div>

                {/* Password Strength */}
                <div className="bg-muted rounded-lg p-4 space-y-3">
                  <div className="flex justify-between text-sm">
                    <span>Strength</span>
                    <span className="font-medium">{strength.label}</span>
                  </div>
                  <Progress value={strength.percentage} className={strength.color} />

                  <div className="grid grid-cols-2 gap-2 text-xs">
                    {Object.entries(passwordRequirements).map(([key, met]) => (
                      <div
                        key={key}
                        className={`flex items-center gap-1 px-2 py-1 rounded-full border ${
                          met
                            ? 'bg-green-500/10 border-green-500 text-green-600'
                            : 'bg-muted border-border text-muted-foreground'
                        }`}
                      >
                        {met ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
                        <span>
                          {key === 'length' && '8+ chars'}
                          {key === 'uppercase' && 'A-Z'}
                          {key === 'lowercase' && 'a-z'}
                          {key === 'number' && '0-9'}
                          {key === 'special' && 'Special (@#$%^&*)'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <Button type="submit" disabled={!canSubmitPassword || isChangingPassword}>
                  {isChangingPassword ? (
                    <>
                      <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                      Changing...
                    </>
                  ) : (
                    <>
                      <Lock className="h-4 w-4 mr-2" />
                      Change Password
                    </>
                  )}
                </Button>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Theme Tab */}
        <TabsContent value="theme" className="space-y-6">
          {/* Analyzer Mode Warning */}
          {isAnalyzerMode && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Theme Changes Disabled</AlertTitle>
              <AlertDescription>
                Theme customization is disabled while in Analyzer Mode.
                The purple theme is automatically applied for visual distinction.
                Switch back to Live Mode to change themes.
              </AlertDescription>
            </Alert>
          )}

          {/* Current Theme Status */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Current Theme</CardTitle>
                  <CardDescription>
                    {isAnalyzerMode
                      ? 'Analyzer Mode (Purple Theme)'
                      : `${mode.charAt(0).toUpperCase() + mode.slice(1)} Mode with ${color.charAt(0).toUpperCase() + color.slice(1)} accent`
                    }
                  </CardDescription>
                </div>
                <div className="flex items-center gap-4">
                  <div className="flex gap-2">
                    <div className="w-6 h-6 rounded bg-primary" title="Primary" />
                    <div className="w-6 h-6 rounded bg-secondary" title="Secondary" />
                    <div className="w-6 h-6 rounded bg-accent" title="Accent" />
                    <div className="w-6 h-6 rounded bg-muted" title="Muted" />
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleResetTheme}
                    disabled={isAnalyzerMode || (mode === 'light' && color === 'zinc')}
                  >
                    <RefreshCw className="h-4 w-4 mr-2" />
                    Reset
                  </Button>
                </div>
              </div>
            </CardHeader>
          </Card>

          {/* Theme Mode Selection */}
          <Card className={isAnalyzerMode ? 'opacity-60' : ''}>
            <CardHeader>
              <CardTitle>Theme Mode</CardTitle>
              <CardDescription>Choose between light and dark interface</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {THEME_MODES.map((themeOption) => {
                  const Icon = themeOption.icon;
                  const isSelected = mode === themeOption.value && !isAnalyzerMode;
                  return (
                    <button
                      key={themeOption.value}
                      onClick={() => handleThemeModeChange(themeOption.value)}
                      disabled={isAnalyzerMode}
                      className={`flex items-start gap-4 p-4 rounded-lg border-2 transition-all text-left ${
                        isSelected
                          ? 'border-primary bg-primary/5'
                          : 'border-border hover:border-primary/50'
                      } ${isAnalyzerMode ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                    >
                      <div className={`p-2 rounded-lg ${isSelected ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}>
                        <Icon className="h-5 w-5" />
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{themeOption.label}</span>
                          {isSelected && <Check className="h-4 w-4 text-primary" />}
                        </div>
                        <p className="text-sm text-muted-foreground mt-1">
                          {themeOption.description}
                        </p>
                      </div>
                    </button>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          {/* Accent Color Selection */}
          <Card className={isAnalyzerMode ? 'opacity-60' : ''}>
            <CardHeader>
              <CardTitle>Accent Color</CardTitle>
              <CardDescription>Customize the primary accent color</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-4 sm:grid-cols-8 gap-3">
                {ACCENT_COLORS.map((accentColor) => {
                  const isSelected = color === accentColor.value && !isAnalyzerMode;
                  return (
                    <button
                      key={accentColor.value}
                      onClick={() => handleAccentColorChange(accentColor.value)}
                      disabled={isAnalyzerMode}
                      className={`flex flex-col items-center gap-2 p-3 rounded-lg border-2 transition-all ${
                        isSelected
                          ? 'border-primary bg-primary/5'
                          : 'border-border hover:border-primary/50'
                      } ${isAnalyzerMode ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                      title={accentColor.label}
                    >
                      <div className={`w-8 h-8 rounded-full ${accentColor.color} ring-2 ring-offset-2 ring-offset-background ${isSelected ? 'ring-primary' : 'ring-transparent'}`} />
                      <span className="text-xs font-medium">{accentColor.label}</span>
                    </button>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          {/* Theme Info */}
          <Card>
            <CardHeader>
              <CardTitle>About Themes</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground space-y-2">
              <p>
                <strong>Light Mode:</strong> Optimized for daytime use with high contrast and readability.
              </p>
              <p>
                <strong>Dark Mode:</strong> Reduces eye strain during extended trading sessions, especially in low-light environments.
              </p>
              <p>
                <strong>Analyzer Mode:</strong> When in sandbox/analyzer mode, a distinct purple theme is applied automatically to clearly indicate you are not trading with real funds.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        {/* SMTP Tab */}
        <TabsContent value="smtp" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>SMTP Configuration</CardTitle>
              <CardDescription>
                Configure email settings for password reset notifications
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Alert className="mb-6">
                <Mail className="h-4 w-4" />
                <AlertTitle>Gmail Configuration Tips</AlertTitle>
                <AlertDescription>
                  <ul className="text-sm list-disc list-inside mt-1 space-y-1">
                    <li><strong>Personal Gmail:</strong> Server: smtp.gmail.com:587</li>
                    <li><strong>Password:</strong> Use App Password (not your regular password)</li>
                    <li><strong>Setup:</strong> Google Account - Security - 2-Step Verification - App passwords</li>
                  </ul>
                </AlertDescription>
              </Alert>

              <form onSubmit={handleSaveSmtp} className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>SMTP Server</Label>
                    <Input
                      value={smtpServer}
                      onChange={(e) => setSmtpServer(e.target.value)}
                      placeholder="smtp.gmail.com"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>SMTP Port</Label>
                    <Input
                      type="number"
                      value={smtpPort}
                      onChange={(e) => setSmtpPort(e.target.value)}
                      placeholder="587"
                    />
                    <p className="text-xs text-muted-foreground">587 (STARTTLS) or 465 (SSL/TLS)</p>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>Username/Email</Label>
                  <Input
                    type="email"
                    value={smtpUsername}
                    onChange={(e) => setSmtpUsername(e.target.value)}
                    placeholder="your-email@gmail.com"
                  />
                </div>

                <div className="space-y-2">
                  <Label>Password/App Password</Label>
                  <Input
                    type="password"
                    value={smtpPassword}
                    onChange={(e) => setSmtpPassword(e.target.value)}
                    placeholder={profileData?.smtp_settings?.smtp_password ? 'Password is set (enter new to change)' : 'Enter your App Password'}
                  />
                </div>

                <div className="space-y-2">
                  <Label>From Email</Label>
                  <Input
                    type="email"
                    value={smtpFromEmail}
                    onChange={(e) => setSmtpFromEmail(e.target.value)}
                    placeholder="your-email@gmail.com"
                  />
                </div>

                <div className="space-y-2">
                  <Label>HELO Hostname</Label>
                  <Input
                    value={smtpHeloHostname}
                    onChange={(e) => setSmtpHeloHostname(e.target.value)}
                    placeholder="smtp.gmail.com"
                  />
                </div>

                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="smtp_tls"
                    checked={smtpUseTls}
                    onCheckedChange={(checked) => setSmtpUseTls(checked === true)}
                  />
                  <Label htmlFor="smtp_tls">Use TLS/SSL</Label>
                </div>

                <Button type="submit" disabled={isSavingSmtp}>
                  {isSavingSmtp ? (
                    <>
                      <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <Mail className="h-4 w-4 mr-2" />
                      Save SMTP Settings
                    </>
                  )}
                </Button>

                {/* Test Configuration */}
                <div className="border-t pt-4 mt-4">
                  <h4 className="font-medium mb-3">Test Configuration</h4>
                  <p className="text-sm text-muted-foreground mb-4">
                    Send a test email to verify your SMTP settings.
                  </p>
                  <div className="flex gap-2">
                    <Input
                      type="email"
                      value={testEmail}
                      onChange={(e) => setTestEmail(e.target.value)}
                      placeholder="Enter email address to test"
                      className="flex-1"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleTestEmail}
                      disabled={isSendingTest}
                    >
                      {isSendingTest ? (
                        <RefreshCw className="h-4 w-4 animate-spin" />
                      ) : (
                        <>
                          <Send className="h-4 w-4 mr-1" />
                          Send Test
                        </>
                      )}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={handleDebugSmtp}
                      disabled={isDebugging}
                    >
                      {isDebugging ? (
                        <RefreshCw className="h-4 w-4 animate-spin" />
                      ) : (
                        <>
                          <Bug className="h-4 w-4 mr-1" />
                          Debug
                        </>
                      )}
                    </Button>
                  </div>

                  {debugResult && (
                    <Alert className={`mt-4 ${debugResult.success ? 'border-green-500' : 'border-yellow-500'}`}>
                      <AlertTitle>{debugResult.success ? 'SMTP Debug Complete' : 'SMTP Connection Issues'}</AlertTitle>
                      <AlertDescription>
                        <p>{debugResult.message}</p>
                        {debugResult.details && debugResult.details.length > 0 && (
                          <ul className="text-xs mt-2 list-disc list-inside">
                            {debugResult.details.map((detail, i) => (
                              <li key={i}>{detail}</li>
                            ))}
                          </ul>
                        )}
                      </AlertDescription>
                    </Alert>
                  )}
                </div>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TOTP Tab */}
        <TabsContent value="totp" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>TOTP Authentication</CardTitle>
              <CardDescription>
                Manage your Two-Factor Authentication settings
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <Alert>
                <Shield className="h-4 w-4" />
                <AlertTitle>About TOTP Authentication</AlertTitle>
                <AlertDescription>
                  TOTP (Time-based One-Time Password) provides an additional layer of security.
                  You&apos;ll need an authenticator app like Google Authenticator or Authy to generate
                  codes for password recovery.
                </AlertDescription>
              </Alert>

              {profileData?.qr_code && profileData?.totp_secret ? (
                <div className="bg-muted rounded-lg p-6 space-y-6">
                  <h3 className="font-semibold text-center">Your TOTP QR Code</h3>

                  {/* QR Code */}
                  <div className="flex justify-center">
                    <div className="p-4 bg-white rounded-lg shadow">
                      <img
                        src={`data:image/png;base64,${profileData.qr_code}`}
                        alt="TOTP QR Code"
                        className="w-48 h-48"
                      />
                    </div>
                  </div>

                  {/* Manual Entry */}
                  <div className="bg-background rounded-lg p-4 space-y-2">
                    <h4 className="font-semibold">Manual Entry</h4>
                    <p className="text-sm text-muted-foreground">Secret key for manual entry:</p>
                    <div className="flex items-center gap-2">
                      <code className="flex-1 bg-muted p-2 rounded text-sm break-all">
                        {profileData.totp_secret}
                      </code>
                      <Button
                        size="icon"
                        variant="outline"
                        onClick={() => copyToClipboard(profileData.totp_secret!)}
                      >
                        <Copy className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>

                  {/* Instructions */}
                  <div className="space-y-2">
                    <p className="font-medium">Setup Instructions:</p>
                    <ol className="list-decimal list-inside space-y-1 text-sm text-muted-foreground">
                      <li>Install an authenticator app (Google Authenticator, Authy, etc.)</li>
                      <li>Scan the QR code above or enter the secret key manually</li>
                      <li>Save your backup codes in a safe place</li>
                      <li>You&apos;ll need the TOTP code to reset your password if you forget it</li>
                    </ol>
                  </div>
                </div>
              ) : (
                <Alert variant="destructive">
                  <AlertTitle>TOTP Not Available</AlertTitle>
                  <AlertDescription>
                    Unable to load TOTP setup. Please contact your administrator.
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

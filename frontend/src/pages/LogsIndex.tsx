import { Link } from 'react-router-dom';
import {
  FileText,
  ArrowLeft,
  ClipboardList,
  FlaskConical,
  Clock,
  Activity,
  Shield,
  BookOpen,
  CheckCircle,
  ArrowRight,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

interface LogCardProps {
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  href: string;
  features: string[];
  buttonText: string;
  gradient: string;
  isExternal?: boolean;
}

function LogCard({ title, description, icon: Icon, href, features, buttonText, gradient, isExternal }: LogCardProps) {
  const content = (
    <Card className="h-full hover:shadow-lg transition-all duration-300 group overflow-hidden">
      <CardHeader className="text-center pb-2">
        <div className={`w-20 h-20 mx-auto rounded-2xl ${gradient} flex items-center justify-center mb-4 group-hover:scale-105 transition-transform`}>
          <Icon className="h-10 w-10 text-white" />
        </div>
        <CardTitle className="text-xl">{title}</CardTitle>
        <CardDescription className="text-sm min-h-[3rem]">
          {description}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="space-y-2">
          {features.map((feature, index) => (
            <li key={index} className="flex items-center gap-2 text-sm text-muted-foreground">
              <CheckCircle className="h-4 w-4 text-green-500 flex-shrink-0" />
              <span>{feature}</span>
            </li>
          ))}
        </ul>
        <Button className={`w-full ${gradient} border-0 text-white hover:opacity-90`}>
          {buttonText}
          <ArrowRight className="h-4 w-4 ml-2" />
        </Button>
      </CardContent>
    </Card>
  );

  if (isExternal) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className="block">
        {content}
      </a>
    );
  }

  return (
    <Link to={href} className="block">
      {content}
    </Link>
  );
}

export default function LogsIndex() {
  const logCards: LogCardProps[] = [
    {
      title: 'Live Logs',
      description: 'View real-time API order logs with detailed request and response data. Filter by date, search, and export logs to CSV.',
      icon: ClipboardList,
      href: '/logs/live',
      features: [
        'Order request & response logs',
        'Date range filtering',
        'CSV export',
      ],
      buttonText: 'View Live Logs',
      gradient: 'bg-gradient-to-br from-cyan-400 to-blue-500',
    },
    {
      title: 'Sandbox Logs',
      description: 'Sandbox testing logs to track and test your trading strategies before going live. Validate strategy performance in a safe environment.',
      icon: FlaskConical,
      href: '/logs/sandbox',
      features: [
        'Strategy testing logs',
        'Paper trading validation',
        'Risk-free testing',
      ],
      buttonText: 'Open Sandbox',
      gradient: 'bg-gradient-to-br from-pink-400 to-purple-500',
    },
    {
      title: 'Latency Monitor',
      description: 'Track order execution latency for your connected broker. View histograms, percentiles, and identify performance bottlenecks.',
      icon: Clock,
      href: '/logs/latency',
      features: [
        'Order execution timing',
        'Performance metrics',
        'Latency histograms',
      ],
      buttonText: 'View Latency',
      gradient: 'bg-gradient-to-br from-yellow-400 to-orange-500',
    },
    {
      title: 'Traffic Monitor',
      description: 'Monitor all incoming HTTP requests to your OpenAlgo instance. Track endpoints, methods, status codes, and response times.',
      icon: Activity,
      href: '/logs/traffic',
      features: [
        'Request/response tracking',
        'Endpoint analytics',
        'Response time metrics',
      ],
      buttonText: 'View Traffic',
      gradient: 'bg-gradient-to-br from-teal-400 to-cyan-500',
    },
    {
      title: 'Security Logs',
      description: 'Monitor security events including banned IPs, 404 errors, and invalid API key attempts. Manage IP bans and security thresholds.',
      icon: Shield,
      href: '/logs/security',
      features: [
        'IP ban management',
        'Security event tracking',
        'Threat monitoring',
      ],
      buttonText: 'View Security',
      gradient: 'bg-gradient-to-br from-red-400 to-pink-500',
    },
    {
      title: 'Documentation',
      description: 'Access comprehensive guides, API references, and troubleshooting tips. Learn how to configure and optimize your OpenAlgo setup.',
      icon: BookOpen,
      href: 'https://docs.openalgo.in',
      features: [
        'API documentation',
        'Setup guides',
        'Troubleshooting tips',
      ],
      buttonText: 'View Docs',
      gradient: 'bg-gradient-to-br from-orange-400 to-amber-500',
      isExternal: true,
    },
  ];

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Link to="/dashboard" className="text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <FileText className="h-6 w-6" />
            Logs & Monitoring
          </h1>
        </div>
        <p className="text-muted-foreground">
          Access trading logs, monitor system performance, and track security events
        </p>
      </div>

      {/* Log Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {logCards.map((card) => (
          <LogCard key={card.title} {...card} />
        ))}
      </div>
    </div>
  );
}

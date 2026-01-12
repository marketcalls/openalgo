import { Link } from 'react-router-dom';
import { BarChart3, LineChart, Lightbulb, Zap, ExternalLink, CheckCircle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

interface PlatformCardProps {
  title: string;
  description: string;
  features: string[];
  icon: React.ReactNode;
  gradient: string;
  link: string;
  buttonText: string;
  buttonVariant?: 'default' | 'secondary' | 'outline';
}

function PlatformCard({ title, description, features, icon, gradient, link, buttonText, buttonVariant = 'default' }: PlatformCardProps) {
  return (
    <Card className="hover:shadow-xl transition-all duration-300 hover:-translate-y-2">
      <CardContent className="pt-10 pb-6 text-center">
        {/* Icon */}
        <div className="flex justify-center mb-6">
          <div
            className="w-32 h-32 rounded-2xl flex items-center justify-center"
            style={{ background: gradient }}
          >
            {icon}
          </div>
        </div>

        {/* Title */}
        <h2 className="text-2xl font-bold mb-2">{title}</h2>

        {/* Description */}
        <p className="text-muted-foreground mb-6">{description}</p>

        {/* Features */}
        <div className="text-left mb-6 space-y-2">
          {features.map((feature, index) => (
            <div key={index} className="flex items-start gap-2">
              <CheckCircle className="h-5 w-5 text-green-500 mt-0.5 flex-shrink-0" />
              <span className="text-sm">{feature}</span>
            </div>
          ))}
        </div>

        {/* Button */}
        <Button asChild variant={buttonVariant} className="w-full gap-2" size="lg">
          <Link to={link}>
            <Zap className="h-5 w-5" />
            {buttonText}
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

export default function Platforms() {
  const platforms: PlatformCardProps[] = [
    {
      title: 'TradingView',
      description: "World's leading charting platform with advanced technical analysis tools and real-time data. Set up webhooks to automate your trading strategies.",
      features: [
        'Advanced charting & indicators',
        'Pine Script strategy alerts',
        'Smart order execution',
      ],
      icon: <BarChart3 className="h-20 w-20 text-white" />,
      gradient: 'linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%)',
      link: '/tradingview',
      buttonText: 'Configure TradingView',
      buttonVariant: 'default',
    },
    {
      title: 'GoCharting',
      description: 'Professional HTML5 charting platform designed for Indian markets. Powerful analysis tools with seamless webhook integration for live trading.',
      features: [
        'Indian market optimized',
        'Real-time market data',
        'Simple webhook setup',
      ],
      icon: <LineChart className="h-20 w-20 text-white" />,
      gradient: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)',
      link: '/gocharting',
      buttonText: 'Configure GoCharting',
      buttonVariant: 'default',
    },
    {
      title: 'Chartink',
      description: 'Build custom stock screeners with powerful technical analysis filters. Automate trading based on your screening conditions and market scans.',
      features: [
        'Custom stock screeners',
        'Technical scan automation',
        'Multi-symbol execution',
      ],
      icon: <Lightbulb className="h-20 w-20 text-white" />,
      gradient: 'linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)',
      link: '/chartink',
      buttonText: 'Configure Chartink',
      buttonVariant: 'default',
    },
  ];

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="text-center mb-12">
        <h1 className="text-4xl font-bold mb-4">Trading Platforms</h1>
        <p className="text-lg text-muted-foreground">
          Connect your favorite charting platforms with OpenAlgo for automated trading
        </p>
      </div>

      {/* Platform Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 max-w-7xl mx-auto">
        {platforms.map((platform) => (
          <PlatformCard key={platform.title} {...platform} />
        ))}
      </div>

      {/* Information Section */}
      <div className="mt-16 max-w-4xl mx-auto">
        <Alert>
          <Lightbulb className="h-5 w-5" />
          <AlertTitle className="font-bold">Getting Started</AlertTitle>
          <AlertDescription className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <span>
              Each platform requires webhook configuration. Click on the platform cards above to generate your webhook URLs and JSON payloads. Make sure you have set up your API key before configuring webhooks.
            </span>
            <Button asChild variant="outline" size="sm" className="gap-1 flex-shrink-0">
              <a href="https://docs.openalgo.in" target="_blank" rel="noopener noreferrer">
                View Documentation
                <ExternalLink className="h-4 w-4" />
              </a>
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    </div>
  );
}

import { useThemeStore } from '@/stores/themeStore';
import type { StrategyConfig } from '..';
import { MOCK_USER_STRATEGIES } from '../../mockData';
import { TrendingUp, Target, Shield, AlertCircle, Zap } from 'lucide-react';

interface StrategyDetailsProps {
    config: StrategyConfig;
}

export default function StrategyDetails({ config }: StrategyDetailsProps) {
    const { mode, appMode } = useThemeStore()
    const darkMode = mode === 'dark' || appMode === 'analyzer';

    const strategyName = config.strategyId 
        ? MOCK_USER_STRATEGIES.find(s => s.id === config.strategyId)?.name 
        : 'AI Suggested Strategy';

    const totalIndicators = config.indicators.length;

    return (
        <div className={`h-full flex flex-col overflow-y-auto hide-scrollbar ${
            darkMode ? 'bg-gray-800' : 'bg-gray-50'
        }`}>
            {/* Header */}
            <div className={`p-6 border-b ${
                darkMode ? 'border-gray-700 bg-gray-800' : 'border-gray-200 bg-white'
            }`}>
                <div className="flex items-center gap-3 mb-2">
                    <TrendingUp className={`w-6 h-6 ${
                        darkMode ? 'text-blue-400' : 'text-blue-600'
                    }`} />
                    <h2 className={`text-lg font-bold ${
                        darkMode ? 'text-white' : 'text-gray-900'
                    }`}>
                        Strategy Configuration
                    </h2>
                </div>
                <p className={`text-sm ${
                    darkMode ? 'text-gray-400' : 'text-gray-600'
                }`}>
                    Review your strategy details before deployment
                </p>
            </div>

            {/* Content */}
            <div className="flex-1 p-6 space-y-6">
                {/* Strategy Name */}
                <div className={`p-4 rounded-lg border ${
                    darkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-200'
                }`}>
                    <div className={`text-xs font-semibold mb-1 ${
                        darkMode ? 'text-gray-400' : 'text-gray-600'
                    }`}>
                        STRATEGY NAME
                    </div>
                    <div className={`text-base font-bold ${
                        darkMode ? 'text-white' : 'text-gray-900'
                    }`}>
                        {strategyName}
                    </div>
                </div>

                {/* Broker & Exchange */}
                <div className={`p-4 rounded-lg border ${
                    darkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-200'
                }`}>
                    <div className={`text-xs font-semibold mb-3 ${
                        darkMode ? 'text-gray-400' : 'text-gray-600'
                    }`}>
                        BROKER & EXCHANGE
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <div className={`text-xs mb-1 ${
                                darkMode ? 'text-gray-500' : 'text-gray-500'
                            }`}>
                                Broker
                            </div>
                            <div className={`text-sm font-semibold ${
                                darkMode ? 'text-white' : 'text-gray-900'
                            }`}>
                                {config.brokerName}
                            </div>
                        </div>
                        <div>
                            <div className={`text-xs mb-1 ${
                                darkMode ? 'text-gray-500' : 'text-gray-500'
                            }`}>
                                Exchange
                            </div>
                            <div className={`text-sm font-semibold ${
                                darkMode ? 'text-white' : 'text-gray-900'
                            }`}>
                                {config.exchange}
                            </div>
                        </div>
                    </div>
                </div>

                {/* Trading Parameters */}
                <div className={`p-4 rounded-lg border ${
                    darkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-200'
                }`}>
                    <div className={`text-xs font-semibold mb-3 ${
                        darkMode ? 'text-gray-400' : 'text-gray-600'
                    }`}>
                        TRADING PARAMETERS
                    </div>
                    <div className="space-y-2">
                        <div className="flex justify-between">
                            <span className={`text-sm ${
                                darkMode ? 'text-gray-400' : 'text-gray-600'
                            }`}>
                                Position Type
                            </span>
                            <span className={`text-sm font-semibold ${
                                darkMode ? 'text-white' : 'text-gray-900'
                            }`}>
                                {config.positionType}
                            </span>
                        </div>
                        <div className="flex justify-between">
                            <span className={`text-sm ${
                                darkMode ? 'text-gray-400' : 'text-gray-600'
                            }`}>
                                Time in Force
                            </span>
                            <span className={`text-sm font-semibold ${
                                darkMode ? 'text-white' : 'text-gray-900'
                            }`}>
                                {config.timeInForce}
                            </span>
                        </div>
                    </div>
                </div>

                {/* Technical Indicators */}
                <div className={`p-4 rounded-lg border ${
                    darkMode ? 'bg-blue-500/10 border-blue-500/30' : 'bg-blue-50 border-blue-200'
                }`}>
                    <div className="flex items-center gap-2 mb-3">
                        <Zap className={`w-4 h-4 ${
                            darkMode ? 'text-blue-400' : 'text-blue-600'
                        }`} />
                        <div className={`text-xs font-semibold ${
                            darkMode ? 'text-blue-400' : 'text-blue-600'
                        }`}>
                            TECHNICAL INDICATORS
                        </div>
                    </div>
                    <div className="space-y-2">
                        {config.indicators.slice(0, 5).map((indicator) => (
                            <div 
                                key={indicator.indicatorId}
                                className={`text-sm ${
                                    darkMode ? 'text-blue-300' : 'text-blue-700'
                                }`}
                            >
                                • {indicator.indicatorName}
                            </div>
                        ))}
                        {totalIndicators > 5 && (
                            <div className={`text-sm font-medium ${
                                darkMode ? 'text-blue-400' : 'text-blue-600'
                            }`}>
                                +{totalIndicators - 5} more indicators
                            </div>
                        )}
                    </div>
                </div>

                {/* Stop Loss & Target */}
                {config.strategyParameters && (
                    <div className={`p-4 rounded-lg border ${
                        darkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-200'
                    }`}>
                        <div className="flex items-center gap-2 mb-3">
                            <Target className={`w-4 h-4 ${
                                darkMode ? 'text-green-400' : 'text-green-600'
                            }`} />
                            <div className={`text-xs font-semibold ${
                                darkMode ? 'text-gray-400' : 'text-gray-600'
                            }`}>
                                ENTRY & EXIT CONDITIONS
                            </div>
                        </div>
                        <div className="space-y-3">
                            <div>
                                <div className={`text-xs mb-1 ${
                                    darkMode ? 'text-gray-500' : 'text-gray-500'
                                }`}>
                                    Stop Loss
                                </div>
                                <div className={`text-lg font-bold text-red-500`}>
                                    {config.strategyParameters.stopLossPercentage}%
                                </div>
                            </div>
                            <div>
                                <div className={`text-xs mb-1 ${
                                    darkMode ? 'text-gray-500' : 'text-gray-500'
                                }`}>
                                    Take Profit
                                </div>
                                <div className={`text-lg font-bold text-green-500`}>
                                    {config.strategyParameters.takeProfitPercentage}%
                                </div>
                            </div>
                            {config.strategyParameters.trailingStopLoss && (
                                <div>
                                    <div className={`text-xs mb-1 ${
                                        darkMode ? 'text-gray-500' : 'text-gray-500'
                                    }`}>
                                        Trailing Stop Loss
                                    </div>
                                    <div className={`text-sm font-semibold ${
                                        darkMode ? 'text-green-400' : 'text-green-600'
                                    }`}>
                                        Enabled ({config.strategyParameters.trailingStopPercentage}%)
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* Risk Management */}
                <div className={`p-4 rounded-lg border ${
                    darkMode ? 'bg-red-500/10 border-red-500/30' : 'bg-red-50 border-red-200'
                }`}>
                    <div className="flex items-center gap-2 mb-3">
                        <Shield className={`w-4 h-4 ${
                            darkMode ? 'text-red-400' : 'text-red-600'
                        }`} />
                        <div className={`text-xs font-semibold ${
                            darkMode ? 'text-red-400' : 'text-red-600'
                        }`}>
                            RISK MANAGEMENT
                        </div>
                    </div>
                    <div className="space-y-2">
                        <div className="flex justify-between">
                            <span className={`text-sm ${
                                darkMode ? 'text-red-300' : 'text-red-700'
                            }`}>
                                Max Position Size
                            </span>
                            <span className={`text-sm font-bold ${
                                darkMode ? 'text-red-400' : 'text-red-600'
                            }`}>
                                ₹{config.riskManagement.maxPositionSize?.toLocaleString()}
                            </span>
                        </div>
                        <div className="flex justify-between">
                            <span className={`text-sm ${
                                darkMode ? 'text-red-300' : 'text-red-700'
                            }`}>
                                Max Daily Loss
                            </span>
                            <span className={`text-sm font-bold ${
                                darkMode ? 'text-red-400' : 'text-red-600'
                            }`}>
                                ₹{config.riskManagement.maxDailyLoss?.toLocaleString()}
                            </span>
                        </div>
                    </div>
                </div>

                {/* Symbol Filter Status */}
                <div className={`p-4 rounded-lg border ${
                    darkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-200'
                }`}>
                    <div className="flex items-center gap-2 mb-2">
                        <AlertCircle className={`w-4 h-4 ${
                            darkMode ? 'text-yellow-400' : 'text-yellow-600'
                        }`} />
                        <div className={`text-xs font-semibold ${
                            darkMode ? 'text-gray-400' : 'text-gray-600'
                        }`}>
                            SYMBOL FILTER
                        </div>
                    </div>
                    <div className={`text-sm ${
                        darkMode ? 'text-gray-300' : 'text-gray-700'
                    }`}>
                        {config.filterSymbols.length > 0 ? (
                            <>
                                <span className="font-semibold">{config.filterSymbols.length}</span> symbols selected for trading
                            </>
                        ) : (
                            <>Using strategy entry conditions to filter symbols</>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
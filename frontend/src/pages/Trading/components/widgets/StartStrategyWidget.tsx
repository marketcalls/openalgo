
import { useState } from 'react';
import { Play, CheckCircle, AlertCircle, Rocket, Loader2 } from 'lucide-react';
import type { StrategyConfig } from '..';
import { useThemeStore } from '@/stores/themeStore';

interface StartStrategyWidgetProps {
    strategyConfig: StrategyConfig;
    onStart: () => void;
}

export default function StartStrategyWidget({ strategyConfig, onStart }: StartStrategyWidgetProps) {
    const { mode } = useThemeStore()
    const darkMode = mode === 'dark';
    
    const [showConfirmation, setShowConfirmation] = useState(false);
    const [isStarting, setIsStarting] = useState(false);

    const handleStartClick = () => {
        setShowConfirmation(true);
    };

    const handleConfirm = async () => {
        setIsStarting(true);
        // Simulate API call delay
        await new Promise(resolve => setTimeout(resolve, 2000));
        onStart();
    };

    const handleCancel = () => {
        setShowConfirmation(false);
    };

    const activeIndicators = strategyConfig.indicators.filter(ind => ind.visible);
    const totalIndicators = strategyConfig.indicators.length;

    if (showConfirmation) {
        return (
            <div className={`my-4 p-6 rounded-xl border ${
                darkMode 
                    ? 'bg-gradient-to-br from-yellow-500/10 to-orange-500/10 border-yellow-500/30' 
                    : 'bg-gradient-to-br from-yellow-50 to-orange-50 border-yellow-300'
            }`}>
                {!isStarting ? (
                    <>
                        {/* Confirmation Header */}
                        <div className="flex items-start gap-4 mb-6">
                            <div className={`p-3 rounded-xl ${
                                darkMode ? 'bg-yellow-500/20' : 'bg-yellow-100'
                            }`}>
                                <AlertCircle className={`w-7 h-7 ${
                                    darkMode ? 'text-yellow-400' : 'text-yellow-600'
                                }`} />
                            </div>
                            <div>
                                <h3 className={`font-bold text-lg mb-2 ${
                                    darkMode ? 'text-white' : 'text-gray-900'
                                }`}>
                                    Confirm Strategy Deployment
                                </h3>
                                <p className={`text-sm ${
                                    darkMode ? 'text-gray-300' : 'text-gray-700'
                                }`}>
                                    Please review your strategy configuration before starting live trading.
                                </p>
                            </div>
                        </div>

                        {/* Configuration Summary */}
                        <div className={`mb-6 p-4 rounded-lg space-y-3 ${
                            darkMode ? 'bg-gray-800/50' : 'bg-white/50'
                        }`}>
                            <div className={`text-sm ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                                <div className="grid grid-cols-2 gap-3">
                                    <div>
                                        <span className="font-semibold">Broker:</span> {strategyConfig.brokerName}
                                    </div>
                                    <div>
                                        <span className="font-semibold">Exchange:</span> {strategyConfig.exchange}
                                    </div>
                                    <div>
                                        <span className="font-semibold">Position Type:</span> {strategyConfig.positionType}
                                    </div>
                                    <div>
                                        <span className="font-semibold">Time in Force:</span> {strategyConfig.timeInForce}
                                    </div>
                                    <div>
                                        <span className="font-semibold">Active Indicators:</span> {activeIndicators.length}
                                    </div>
                                    <div>
                                        <span className="font-semibold">Symbols:</span> {strategyConfig.filterSymbols.length}
                                    </div>
                                </div>
                                <div className="mt-3 pt-3 border-t ${darkMode ? 'border-gray-700' : 'border-gray-200'}">
                                    <div className="font-semibold mb-1">Risk Limits:</div>
                                    <div className="grid grid-cols-2 gap-3">
                                        <div>Max Position: ₹{strategyConfig.riskManagement.maxPositionSize?.toLocaleString()}</div>
                                        <div>Max Daily Loss: ₹{strategyConfig.riskManagement.maxDailyLoss?.toLocaleString()}</div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Warning */}
                        <div className={`mb-6 p-4 rounded-lg border ${
                            darkMode 
                                ? 'bg-red-500/10 border-red-500/30' 
                                : 'bg-red-50 border-red-200'
                        }`}>
                            <div className="flex items-start gap-2">
                                <AlertCircle className={`w-5 h-5 flex-shrink-0 mt-0.5 ${
                                    darkMode ? 'text-red-400' : 'text-red-600'
                                }`} />
                                <div className={`text-sm ${
                                    darkMode ? 'text-red-300' : 'text-red-800'
                                }`}>
                                    <strong>Warning:</strong> This will start live trading with real money. 
                                    Ensure you have reviewed all settings and are comfortable with the configured risk parameters.
                                </div>
                            </div>
                        </div>

                        {/* Confirmation Buttons */}
                        <div className="flex gap-3">
                            <button
                                onClick={handleConfirm}
                                className={`flex-1 flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl text-sm font-bold transition-all ${
                                    darkMode
                                        ? 'bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white'
                                        : 'bg-gradient-to-r from-green-500 to-emerald-500 hover:from-green-600 hover:to-emerald-600 text-white'
                                } shadow-lg hover:shadow-xl transform hover:scale-[1.02]`}
                            >
                                <CheckCircle className="w-5 h-5" />
                                Yes, Start Strategy
                            </button>
                            <button
                                onClick={handleCancel}
                                className={`px-6 py-3.5 rounded-xl text-sm font-bold transition-colors ${
                                    darkMode
                                        ? 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                                        : 'bg-gray-200 hover:bg-gray-300 text-gray-700'
                                }`}
                            >
                                Cancel
                            </button>
                        </div>
                    </>
                ) : (
                    // Starting State
                    <div className="text-center py-8">
                        <Loader2 className={`w-16 h-16 mx-auto mb-4 animate-spin ${
                            darkMode ? 'text-blue-400' : 'text-blue-600'
                        }`} />
                        <h3 className={`font-bold text-lg mb-2 ${
                            darkMode ? 'text-white' : 'text-gray-900'
                        }`}>
                            Executing Strategy...
                        </h3>
                        <p className={`text-sm ${
                            darkMode ? 'text-gray-400' : 'text-gray-600'
                        }`}>
                            Connecting to broker and initializing trading system
                        </p>
                    </div>
                )}
            </div>
        );
    }

    return (
        <div className="my-4">
            {/* Ready to Deploy Card */}
            <div className={`mb-5 p-6 rounded-xl border ${
                darkMode 
                    ? 'bg-gradient-to-br from-green-500/10 to-emerald-500/10 border-green-500/30' 
                    : 'bg-gradient-to-br from-green-50 to-emerald-50 border-green-200'
            }`}>
                <div className="flex items-start gap-4">
                    <div className={`p-3 rounded-xl ${
                        darkMode ? 'bg-green-500/20' : 'bg-green-100'
                    }`}>
                        <CheckCircle className={`w-7 h-7 ${
                            darkMode ? 'text-green-400' : 'text-green-600'
                        }`} />
                    </div>
                    <div className="flex-1">
                        <h3 className={`font-bold text-xl mb-2 ${
                            darkMode ? 'text-white' : 'text-gray-900'
                        }`}>
                            Strategy Ready for Run
                        </h3>
                        <p className={`text-sm mb-4 ${
                            darkMode ? 'text-gray-300' : 'text-gray-700'
                        }`}>
                            Your strategy is fully configured and ready to start trading. 
                            All parameters have been validated and saved.
                        </p>

                        {/* Quick Stats */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                            <div className={`p-3 rounded-lg ${
                                darkMode ? 'bg-gray-800/50' : 'bg-white/50'
                            }`}>
                                <div className={`text-xs mb-1 ${
                                    darkMode ? 'text-gray-400' : 'text-gray-600'
                                }`}>
                                    Symbols
                                </div>
                                <div className={`text-lg font-bold ${
                                    darkMode ? 'text-white' : 'text-gray-900'
                                }`}>
                                    {strategyConfig.filterSymbols.length}
                                </div>
                            </div>

                            <div className={`p-3 rounded-lg ${
                                darkMode ? 'bg-gray-800/50' : 'bg-white/50'
                            }`}>
                                <div className={`text-xs mb-1 ${
                                    darkMode ? 'text-gray-400' : 'text-gray-600'
                                }`}>
                                    Indicators
                                </div>
                                <div className={`text-lg font-bold ${
                                    darkMode ? 'text-white' : 'text-gray-900'
                                }`}>
                                     {totalIndicators}
                                </div>
                            </div>

                            <div className={`p-3 rounded-lg ${
                                darkMode ? 'bg-gray-800/50' : 'bg-white/50'
                            }`}>
                                <div className={`text-xs mb-1 ${
                                    darkMode ? 'text-gray-400' : 'text-gray-600'
                                }`}>
                                    Max Position
                                </div>
                                <div className={`text-lg font-bold ${
                                    darkMode ? 'text-white' : 'text-gray-900'
                                }`}>
                                    ₹{(strategyConfig.riskManagement.maxPositionSize! / 1000).toFixed(0)}K
                                </div>
                            </div>
                            <div className={`p-3 rounded-lg ${
                                darkMode ? 'bg-gray-800/50' : 'bg-white/50'
                            }`}>
                                <div className={`text-xs mb-1 ${
                                    darkMode ? 'text-gray-400' : 'text-gray-600'
                                }`}>
                                    Max Daily Loss
                                </div>
                                <div className={`text-lg font-bold ${
                                    darkMode ? 'text-white' : 'text-gray-900'
                                }`}>
                                    ₹{(strategyConfig.riskManagement.maxDailyLoss! / 1000).toFixed(0)}K
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Start Button */}
            <button
                onClick={handleStartClick}
                className={`w-full flex items-center justify-center gap-3 px-8 py-5 rounded-xl text-base font-bold transition-all ${
                    darkMode
                        ? 'bg-gradient-to-r from-blue-600 via-purple-600 to-pink-600 hover:from-blue-700 hover:via-purple-700 hover:to-pink-700 text-white'
                        : 'bg-gradient-to-r from-blue-500 via-purple-500 to-pink-500 hover:from-blue-600 hover:via-purple-600 hover:to-pink-600 text-white'
                } shadow-2xl hover:shadow-3xl transform hover:scale-[1.02] relative overflow-hidden group`}
            >
                <div className="absolute inset-0 bg-white/20 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
                <Rocket className="w-6 h-6 animate-bounce" />
                <span>Start Strategy Now</span>
                <Play className="w-6 h-6" />
            </button>

            <p className={`text-center text-xs mt-3 ${
                darkMode ? 'text-gray-500' : 'text-gray-500'
            }`}>
                You will be asked to confirm before the strategy starts
            </p>
        </div>
    );
}
import { X, Info, TrendingUp, Filter, Target, Shield, Zap, AlertCircle, Loader2, FileText } from 'lucide-react';
import { MOCK_STRATEGY_DETAILS } from '../../mockData';
import { useState, useEffect } from 'react';
import { useThemeStore } from '@/stores/themeStore';

interface StrategyInfoModalProps {
    isOpen: boolean;
    onClose: () => void;
    strategyId: string;
}

export default function StrategyInfoModal({ isOpen, onClose, strategyId }: StrategyInfoModalProps) {
    const { mode, appMode } = useThemeStore()
    const darkMode = mode === 'dark' || appMode === 'analyzer';
    
    const [loading, setLoading] = useState(false);
    const [strategyDetails, setStrategyDetails] = useState<any>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (isOpen && strategyId) {
            fetchStrategyDetails();
        }
    }, [isOpen, strategyId]);

    const fetchStrategyDetails = async () => {
        try {
            setLoading(true);
            setError(null);
            
            // TODO: Replace with actual API call
            // const data = await getStrategyDetails(strategyId);
            
            // Simulate API delay
            await new Promise(resolve => setTimeout(resolve, 1000));
            
            const data = MOCK_STRATEGY_DETAILS[strategyId];
            
            if (!data) {
                throw new Error('Strategy details not found');
            }
            
            setStrategyDetails(data);
        } catch (err: any) {
            console.error('Error fetching strategy details:', err);
            setError(err.message || 'Failed to load strategy details');
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            {/* Backdrop */}
            <div 
                className={`absolute inset-0 ${
                    darkMode ? 'bg-black/70' : 'bg-black/50'
                } backdrop-blur-sm`}
                onClick={onClose}
            />
            
            {/* Modal Content */}
            <div 
                className={`relative w-full max-w-4xl max-h-[90vh] m-4 rounded-xl shadow-2xl overflow-hidden ${
                    darkMode ? 'bg-gray-800' : 'bg-white'
                }`}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className={`px-6 py-4 border-b flex items-center justify-between ${
                    darkMode 
                        ? 'border-gray-700 bg-gradient-to-r from-blue-600/20 to-purple-600/20' 
                        : 'border-gray-200 bg-gradient-to-r from-blue-50 to-purple-50'
                }`}>
                    <div className="flex items-center gap-3">
                        <div className={`p-2 rounded-lg ${
                            darkMode ? 'bg-blue-500/20' : 'bg-blue-100'
                        }`}>
                            <Info className={`w-5 h-5 ${
                                darkMode ? 'text-blue-400' : 'text-blue-600'
                            }`} />
                        </div>
                        <div>
                            <h3 className={`text-lg font-bold ${
                                darkMode ? 'text-white' : 'text-gray-900'
                            }`}>
                                Strategy Information
                            </h3>
                            <p className={`text-xs ${
                                darkMode ? 'text-gray-400' : 'text-gray-600'
                            }`}>
                                {strategyDetails?.name || 'Loading...'}
                            </p>
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        className={`p-2 rounded-lg transition-colors ${
                            darkMode
                                ? 'hover:bg-gray-700 text-gray-400'
                                : 'hover:bg-gray-100 text-gray-600'
                        }`}
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>
                
                {/* Body */}
                <div className="overflow-y-auto max-h-[calc(90vh-80px)] hide-scrollbar">
                    {loading ? (
                        <div className="flex items-center justify-center py-20">
                            <div className="text-center">
                                <Loader2 className={`w-12 h-12 mx-auto mb-4 animate-spin ${
                                    darkMode ? 'text-blue-400' : 'text-blue-600'
                                }`} />
                                <p className={`text-sm ${
                                    darkMode ? 'text-gray-400' : 'text-gray-600'
                                }`}>
                                    Loading strategy details...
                                </p>
                            </div>
                        </div>
                    ) : error ? (
                        <div className="p-6">
                            <div className={`p-4 rounded-lg border ${
                                darkMode 
                                    ? 'bg-red-500/10 border-red-500/30' 
                                    : 'bg-red-50 border-red-200'
                            }`}>
                                <div className="flex items-center gap-2 mb-2">
                                    <AlertCircle className={`w-5 h-5 ${
                                        darkMode ? 'text-red-400' : 'text-red-600'
                                    }`} />
                                    <h4 className={`font-semibold ${
                                        darkMode ? 'text-red-400' : 'text-red-600'
                                    }`}>
                                        Error Loading Strategy
                                    </h4>
                                </div>
                                <p className={`text-sm ${
                                    darkMode ? 'text-red-300' : 'text-red-700'
                                }`}>
                                    {error}
                                </p>
                                <button
                                    onClick={fetchStrategyDetails}
                                    className={`mt-3 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                                        darkMode
                                            ? 'bg-red-600 hover:bg-red-700 text-white'
                                            : 'bg-red-500 hover:bg-red-600 text-white'
                                    }`}
                                >
                                    Retry
                                </button>
                            </div>
                        </div>
                    ) : strategyDetails ? (
                        <div className="p-6 space-y-5">
                            {/* Strategy Name */}
                            <section>
                                <div className={`p-5 rounded-xl border ${
                                    darkMode 
                                        ? 'bg-gradient-to-br from-blue-500/10 to-purple-500/10 border-blue-500/30' 
                                        : 'bg-gradient-to-br from-blue-50 to-purple-50 border-blue-200'
                                }`}>
                                    <h2 className={`text-2xl font-bold mb-2 ${
                                        darkMode ? 'text-white' : 'text-gray-900'
                                    }`}>
                                        {strategyDetails.name}
                                    </h2>
                                    <p className={`text-xs uppercase tracking-wide font-semibold ${
                                        darkMode ? 'text-blue-400' : 'text-blue-600'
                                    }`}>
                                        Strategy ID: {strategyDetails.id}
                                    </p>
                                </div>
                            </section>

                            {/* Introduction */}
                            <section>
                                <div className="flex items-center gap-2 mb-3">
                                    <FileText className={`w-5 h-5 ${
                                        darkMode ? 'text-blue-400' : 'text-blue-600'
                                    }`} />
                                    <h4 className={`text-sm font-bold uppercase ${
                                        darkMode ? 'text-blue-400' : 'text-blue-600'
                                    }`}>
                                        Introduction
                                    </h4>
                                </div>
                                <div className={`p-4 rounded-lg border ${
                                    darkMode ? 'bg-gray-700/50 border-gray-600' : 'bg-gray-50 border-gray-200'
                                }`}>
                                    <p className={`text-sm leading-relaxed ${
                                        darkMode ? 'text-gray-300' : 'text-gray-700'
                                    }`}>
                                        {strategyDetails.intro}
                                    </p>
                                </div>
                            </section>

                            {/* Selected Indicators */}
                            {strategyDetails.selectedIndicators && strategyDetails.selectedIndicators.length > 0 && (
                                <section>
                                    <div className="flex items-center gap-2 mb-3">
                                        <Zap className={`w-5 h-5 ${
                                            darkMode ? 'text-purple-400' : 'text-purple-600'
                                        }`} />
                                        <h4 className={`text-sm font-bold uppercase ${
                                            darkMode ? 'text-purple-400' : 'text-purple-600'
                                        }`}>
                                            Selected Indicators ({strategyDetails.selectedIndicators.length})
                                        </h4>
                                    </div>
                                    <div className={`p-4 rounded-lg border ${
                                        darkMode ? 'bg-gray-700/50 border-gray-600' : 'bg-gray-50 border-gray-200'
                                    }`}>
                                        <div className="space-y-3">
                                            {strategyDetails.selectedIndicators.map((indicator: any) => (
                                                <div 
                                                    key={indicator.indicatorId}
                                                    className={`p-3 rounded-lg border ${
                                                        darkMode ? 'bg-gray-800 border-gray-600' : 'bg-white border-gray-200'
                                                    }`}
                                                >
                                                    <div className="flex items-start justify-between mb-1">
                                                        <div>
                                                            <div className={`font-semibold text-sm ${
                                                                darkMode ? 'text-white' : 'text-gray-900'
                                                            }`}>
                                                                {indicator.indicatorName}
                                                            </div>
                                                            <div className={`text-xs ${
                                                                darkMode ? 'text-gray-400' : 'text-gray-600'
                                                            }`}>
                                                                {indicator.indicatorType}
                                                            </div>
                                                        </div>
                                                    </div>
                                                    <div className={`text-xs ${
                                                        darkMode ? 'text-gray-400' : 'text-gray-600'
                                                    }`}>
                                                        <strong>Parameters:</strong> {Object.entries(indicator.parameters)
                                                            .map(([key, value]) => `${key}=${value}`)
                                                            .join(', ')}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </section>
                            )}

                            {/* Filter Condition */}
                            <section>
                                <div className="flex items-center gap-2 mb-3">
                                    <Filter className={`w-5 h-5 ${
                                        darkMode ? 'text-indigo-400' : 'text-indigo-600'
                                    }`} />
                                    <h4 className={`text-sm font-bold uppercase ${
                                        darkMode ? 'text-indigo-400' : 'text-indigo-600'
                                    }`}>
                                        Filter Condition
                                    </h4>
                                </div>
                                <div className={`p-4 rounded-lg border ${
                                    darkMode ? 'bg-gray-700/50 border-gray-600' : 'bg-gray-50 border-gray-200'
                                }`}>
                                    <p className={`text-sm leading-relaxed mb-3 ${
                                        darkMode ? 'text-gray-300' : 'text-gray-700'
                                    }`}>
                                        {strategyDetails.filterCondition}
                                    </p>
                                    {strategyDetails.selectedSymbols && strategyDetails.selectedSymbols.length > 0 && (
                                        <div>
                                            <div className={`text-xs font-semibold mb-2 ${
                                                darkMode ? 'text-gray-400' : 'text-gray-600'
                                            }`}>
                                                Selected Symbols ({strategyDetails.selectedSymbols.length}):
                                            </div>
                                            <div className="flex flex-wrap gap-2">
                                                {strategyDetails.selectedSymbols.map((symbol: string) => (
                                                    <span 
                                                        key={symbol}
                                                        className={`px-3 py-1 rounded-full text-xs font-semibold ${
                                                            darkMode 
                                                                ? 'bg-indigo-500/20 text-indigo-300' 
                                                                : 'bg-indigo-100 text-indigo-700'
                                                        }`}
                                                    >
                                                        {symbol}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </section>

                            {/* Entry Condition */}
                            <section>
                                <div className="flex items-center gap-2 mb-3">
                                    <TrendingUp className={`w-5 h-5 ${
                                        darkMode ? 'text-green-400' : 'text-green-600'
                                    }`} />
                                    <h4 className={`text-sm font-bold uppercase ${
                                        darkMode ? 'text-green-400' : 'text-green-600'
                                    }`}>
                                        Entry Condition
                                    </h4>
                                </div>
                                <div className={`p-4 rounded-lg border ${
                                    darkMode ? 'bg-gray-700/50 border-gray-600' : 'bg-gray-50 border-gray-200'
                                }`}>
                                    <p className={`text-sm leading-relaxed ${
                                        darkMode ? 'text-gray-300' : 'text-gray-700'
                                    }`}>
                                        {strategyDetails.entryCondition}
                                    </p>
                                </div>
                            </section>

                            {/* Stop Loss Condition */}
                            <section>
                                <div className="flex items-center gap-2 mb-3">
                                    <Shield className={`w-5 h-5 ${
                                        darkMode ? 'text-red-400' : 'text-red-600'
                                    }`} />
                                    <h4 className={`text-sm font-bold uppercase ${
                                        darkMode ? 'text-red-400' : 'text-red-600'
                                    }`}>
                                        Stop Loss Condition
                                    </h4>
                                </div>
                                <div className={`p-4 rounded-lg border ${
                                    darkMode 
                                        ? 'bg-red-500/10 border-red-500/30' 
                                        : 'bg-red-50 border-red-200'
                                }`}>
                                    <p className={`text-sm leading-relaxed ${
                                        darkMode ? 'text-red-300' : 'text-red-700'
                                    }`}>
                                        {strategyDetails.stopLossCondition}
                                    </p>
                                </div>
                            </section>

                            {/* Target Condition */}
                            <section>
                                <div className="flex items-center gap-2 mb-3">
                                    <Target className={`w-5 h-5 ${
                                        darkMode ? 'text-emerald-400' : 'text-emerald-600'
                                    }`} />
                                    <h4 className={`text-sm font-bold uppercase ${
                                        darkMode ? 'text-emerald-400' : 'text-emerald-600'
                                    }`}>
                                        Target Condition
                                    </h4>
                                </div>
                                <div className={`p-4 rounded-lg border ${
                                    darkMode 
                                        ? 'bg-green-500/10 border-green-500/30' 
                                        : 'bg-green-50 border-green-200'
                                }`}>
                                    <p className={`text-sm leading-relaxed ${
                                        darkMode ? 'text-green-300' : 'text-green-700'
                                    }`}>
                                        {strategyDetails.targetCondition}
                                    </p>
                                </div>
                            </section>
                        </div>
                    ) : null}
                </div>
            </div>
        </div>
    );
}
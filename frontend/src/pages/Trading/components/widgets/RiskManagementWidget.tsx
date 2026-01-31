import { useState } from 'react';
import { Shield, AlertTriangle, Save, TrendingDown, Wallet } from 'lucide-react';
import { useThemeStore } from '@/stores/themeStore';

interface RiskManagementWidgetProps {
    onSave: (riskConfig: { maxPositionSize: number; maxDailyLoss: number }) => void;
}

export default function RiskManagementWidget({ onSave }: RiskManagementWidgetProps) {
    const { mode } = useThemeStore()
    const darkMode = mode === 'dark';
    
    const [maxPositionSize, setMaxPositionSize] = useState<string>('');
    const [maxDailyLoss, setMaxDailyLoss] = useState<string>('');
    const [errors, setErrors] = useState<{ maxPositionSize?: string; maxDailyLoss?: string }>({});

    const validate = () => {
        const newErrors: { maxPositionSize?: string; maxDailyLoss?: string } = {};
        
        if (!maxPositionSize || parseFloat(maxPositionSize) <= 0) {
            newErrors.maxPositionSize = 'Max Position Size is required and must be greater than 0';
        }
        
        if (!maxDailyLoss || parseFloat(maxDailyLoss) <= 0) {
            newErrors.maxDailyLoss = 'Max Daily Loss is required and must be greater than 0';
        }

        // Additional validation: daily loss should be reasonable compared to position size
        if (maxPositionSize && maxDailyLoss) {
            const posSize = parseFloat(maxPositionSize);
            const dailyLoss = parseFloat(maxDailyLoss);
            
            if (dailyLoss > posSize * 10) {
                newErrors.maxDailyLoss = 'Daily loss seems too high compared to position size';
            }
        }
        
        setErrors(newErrors);
        return Object.keys(newErrors).length === 0;
    };

    const handleSave = () => {
        if (validate()) {
            onSave({
                maxPositionSize: parseFloat(maxPositionSize),
                maxDailyLoss: parseFloat(maxDailyLoss)
            });
        }
    };

    const handlePositionSizeChange = (value: string) => {
        setMaxPositionSize(value);
        if (errors.maxPositionSize) {
            setErrors(prev => ({ ...prev, maxPositionSize: undefined }));
        }
    };

    const handleDailyLossChange = (value: string) => {
        setMaxDailyLoss(value);
        if (errors.maxDailyLoss) {
            setErrors(prev => ({ ...prev, maxDailyLoss: undefined }));
        }
    };

    const isFormValid = maxPositionSize && maxDailyLoss && 
                        parseFloat(maxPositionSize) > 0 && 
                        parseFloat(maxDailyLoss) > 0;

    return (
        <div className="my-4">
            {/* Header */}
            <div className={`mb-6 p-5 rounded-xl border ${
                darkMode 
                    ? 'bg-gradient-to-br from-red-500/10 via-orange-500/10 to-yellow-500/10 border-red-500/30' 
                    : 'bg-gradient-to-br from-red-50 via-orange-50 to-yellow-50 border-red-200'
            }`}>
                <div className="flex items-start gap-4">
                    <div className={`p-3 rounded-lg ${
                        darkMode ? 'bg-red-500/20' : 'bg-red-100'
                    }`}>
                        <Shield className={`w-7 h-7 ${
                            darkMode ? 'text-red-400' : 'text-red-600'
                        }`} />
                    </div>
                    <div className="flex-1">
                        <h3 className={`font-bold text-lg mb-2 ${
                            darkMode ? 'text-white' : 'text-gray-900'
                        }`}>
                            Risk Management
                        </h3>
                        <p className={`text-sm mb-3 ${
                            darkMode ? 'text-gray-300' : 'text-gray-700'
                        }`}>
                            Protect your capital by setting position and loss limits. These parameters are crucial for safe trading.
                        </p>
                        <div className={`flex items-start gap-2 p-3 rounded-lg ${
                            darkMode ? 'bg-yellow-500/10 border border-yellow-500/30' : 'bg-yellow-50 border border-yellow-200'
                        }`}>
                            <AlertTriangle className={`w-4 h-4 flex-shrink-0 mt-0.5 ${
                                darkMode ? 'text-yellow-400' : 'text-yellow-600'
                            }`} />
                            <p className={`text-xs ${
                                darkMode ? 'text-yellow-300' : 'text-yellow-800'
                            }`}>
                                <strong>Important:</strong> These limits will be enforced in real-time. Once reached, the system will prevent further trades.
                            </p>
                        </div>
                    </div>
                </div>
            </div>

            {/* Form Fields */}
            <div className="space-y-5">
                {/* Max Position Size */}
                <div className={`p-5 rounded-xl border ${
                    errors.maxPositionSize
                        ? darkMode
                            ? 'border-red-500 bg-red-500/5'
                            : 'border-red-300 bg-red-50'
                        : darkMode
                            ? 'border-gray-700 bg-gray-800'
                            : 'border-gray-200 bg-white'
                }`}>
                    <div className="flex items-start gap-3 mb-3">
                        <div className={`p-2 rounded-lg ${
                            darkMode ? 'bg-blue-500/20' : 'bg-blue-100'
                        }`}>
                            <Wallet className={`w-5 h-5 ${
                                darkMode ? 'text-blue-400' : 'text-blue-600'
                            }`} />
                        </div>
                        <div className="flex-1">
                            <label className={`block text-sm font-semibold mb-1 ${
                                darkMode ? 'text-gray-200' : 'text-gray-800'
                            }`}>
                                Max Position Size <span className="text-red-500">*</span>
                            </label>
                            <p className={`text-xs mb-3 ${
                                darkMode ? 'text-gray-400' : 'text-gray-600'
                            }`}>
                                Maximum amount (in ₹) you can allocate to a single position
                            </p>
                        </div>
                    </div>
                    
                    <div className="relative">
                        <span className={`absolute left-3 top-1/2 transform -translate-y-1/2 text-sm font-semibold ${
                            darkMode ? 'text-gray-400' : 'text-gray-600'
                        }`}>
                            ₹
                        </span>
                        <input
                            type="number"
                            value={maxPositionSize}
                            onChange={(e) => handlePositionSizeChange(e.target.value)}
                            placeholder="e.g., 10000"
                            min="1"
                            step="1000"
                            className={`w-full pl-8 pr-4 py-3 rounded-lg border text-sm font-medium ${
                                errors.maxPositionSize
                                    ? darkMode
                                        ? 'bg-red-500/10 border-red-500 text-red-400 placeholder-red-400/50'
                                        : 'bg-red-50 border-red-400 text-red-700 placeholder-red-400'
                                    : darkMode
                                        ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-500'
                                        : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
                            } focus:outline-none focus:ring-2 ${
                                errors.maxPositionSize 
                                    ? 'focus:ring-red-500' 
                                    : 'focus:ring-blue-500'
                            }`}
                        />
                    </div>
                    
                    {errors.maxPositionSize && (
                        <p className={`mt-2 text-xs font-medium flex items-center gap-1 ${
                            darkMode ? 'text-red-400' : 'text-red-600'
                        }`}>
                            <AlertTriangle className="w-3 h-3" />
                            {errors.maxPositionSize}
                        </p>
                    )}
                    
                    {maxPositionSize && !errors.maxPositionSize && (
                        <div className={`mt-2 text-xs ${
                            darkMode ? 'text-gray-500' : 'text-gray-500'
                        }`}>
                            💡 Recommended: 1-5% of your total capital
                        </div>
                    )}
                </div>

                {/* Max Daily Loss */}
                <div className={`p-5 rounded-xl border ${
                    errors.maxDailyLoss
                        ? darkMode
                            ? 'border-red-500 bg-red-500/5'
                            : 'border-red-300 bg-red-50'
                        : darkMode
                            ? 'border-gray-700 bg-gray-800'
                            : 'border-gray-200 bg-white'
                }`}>
                    <div className="flex items-start gap-3 mb-3">
                        <div className={`p-2 rounded-lg ${
                            darkMode ? 'bg-orange-500/20' : 'bg-orange-100'
                        }`}>
                            <TrendingDown className={`w-5 h-5 ${
                                darkMode ? 'text-orange-400' : 'text-orange-600'
                            }`} />
                        </div>
                        <div className="flex-1">
                            <label className={`block text-sm font-semibold mb-1 ${
                                darkMode ? 'text-gray-200' : 'text-gray-800'
                            }`}>
                                Max Daily Loss <span className="text-red-500">*</span>
                            </label>
                            <p className={`text-xs mb-3 ${
                                darkMode ? 'text-gray-400' : 'text-gray-600'
                            }`}>
                                Maximum loss (in ₹) allowed per day before trading stops
                            </p>
                        </div>
                    </div>
                    
                    <div className="relative">
                        <span className={`absolute left-3 top-1/2 transform -translate-y-1/2 text-sm font-semibold ${
                            darkMode ? 'text-gray-400' : 'text-gray-600'
                        }`}>
                            ₹
                        </span>
                        <input
                            type="number"
                            value={maxDailyLoss}
                            onChange={(e) => handleDailyLossChange(e.target.value)}
                            placeholder="e.g., 5000"
                            min="1"
                            step="500"
                            className={`w-full pl-8 pr-4 py-3 rounded-lg border text-sm font-medium ${
                                errors.maxDailyLoss
                                    ? darkMode
                                        ? 'bg-red-500/10 border-red-500 text-red-400 placeholder-red-400/50'
                                        : 'bg-red-50 border-red-400 text-red-700 placeholder-red-400'
                                    : darkMode
                                        ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-500'
                                        : 'bg-white border-gray-300 text-gray-900 placeholder-gray-400'
                            } focus:outline-none focus:ring-2 ${
                                errors.maxDailyLoss 
                                    ? 'focus:ring-red-500' 
                                    : 'focus:ring-blue-500'
                            }`}
                        />
                    </div>
                    
                    {errors.maxDailyLoss && (
                        <p className={`mt-2 text-xs font-medium flex items-center gap-1 ${
                            darkMode ? 'text-red-400' : 'text-red-600'
                        }`}>
                            <AlertTriangle className="w-3 h-3" />
                            {errors.maxDailyLoss}
                        </p>
                    )}
                    
                    {maxDailyLoss && !errors.maxDailyLoss && (
                        <div className={`mt-2 text-xs ${
                            darkMode ? 'text-gray-500' : 'text-gray-500'
                        }`}>
                            💡 Recommended: 2-5% of your total capital
                        </div>
                    )}
                </div>
            </div>

            {/* Summary Box */}
            {isFormValid && (
                <div className={`mt-5 p-4 rounded-lg border ${
                    darkMode 
                        ? 'bg-green-500/10 border-green-500/30' 
                        : 'bg-green-50 border-green-200'
                }`}>
                    <h4 className={`text-sm font-semibold mb-2 ${
                        darkMode ? 'text-green-400' : 'text-green-800'
                    }`}>
                        Risk Summary
                    </h4>
                    <div className={`text-xs space-y-1 ${
                        darkMode ? 'text-green-300' : 'text-green-700'
                    }`}>
                        <p>• Maximum ₹{parseFloat(maxPositionSize).toLocaleString()} per position</p>
                        <p>• Trading stops after ₹{parseFloat(maxDailyLoss).toLocaleString()} daily loss</p>
                        <p>• Risk-to-position ratio: {((parseFloat(maxDailyLoss) / parseFloat(maxPositionSize)) * 100).toFixed(1)}%</p>
                    </div>
                </div>
            )}

            {/* Save Button */}
            <button
                onClick={handleSave}
                disabled={!isFormValid}
                className={`w-full mt-6 flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl text-sm font-bold transition-all ${
                    isFormValid
                        ? darkMode
                            ? 'bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white shadow-lg hover:shadow-xl'
                            : 'bg-gradient-to-r from-green-500 to-emerald-500 hover:from-green-600 hover:to-emerald-600 text-white shadow-lg hover:shadow-xl'
                        : darkMode
                            ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                            : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                } transform ${isFormValid ? 'hover:scale-[1.02]' : ''}`}
            >
                <Save className="w-5 h-5" />
                {isFormValid ? 'Save Risk Management Settings' : 'Please fill all required fields'}
            </button>
        </div>
    );
}
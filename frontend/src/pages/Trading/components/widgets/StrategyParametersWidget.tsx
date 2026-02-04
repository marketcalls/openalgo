import { useState } from 'react';
import { Save, TrendingUp, AlertCircle } from 'lucide-react';
import type { StrategyParameter } from '..';
import { useThemeStore } from '@/stores/themeStore';

interface StrategyParametersWidgetProps {
    parameters: StrategyParameter[];
    onSave: (parameters: Record<string, any>) => void;
}

export default function StrategyParametersWidget({ 
    parameters, 
    onSave 
}: StrategyParametersWidgetProps) {
    const { mode, appMode } = useThemeStore()
    const darkMode = mode === 'dark' || appMode === 'analyzer';
    
    const [paramValues, setParamValues] = useState<Record<string, any>>(
        parameters.reduce((acc, param) => ({
            ...acc,
            [param.key]: param.value
        }), {})
    );

    const handleParameterChange = (key: string, value: any) => {
        setParamValues(prev => ({ ...prev, [key]: value }));
    };

    const handleSave = () => {
        onSave(paramValues);
    };

    const renderInput = (param: StrategyParameter) => {
        const value = paramValues[param.key];

        switch (param.type) {
            case 'boolean':
                return (
                    <label className="flex items-center gap-3 cursor-pointer">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={value}
                                onChange={(e) => handleParameterChange(param.key, e.target.checked)}
                                className="sr-only"
                            />
                            <div className={`w-11 h-6 rounded-full transition-colors ${
                                value
                                    ? darkMode ? 'bg-blue-600' : 'bg-blue-500'
                                    : darkMode ? 'bg-gray-600' : 'bg-gray-300'
                            }`}>
                                <div className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${
                                    value ? 'transform translate-x-5' : ''
                                }`} />
                            </div>
                        </div>
                        <span className={`text-sm font-medium ${
                            darkMode ? 'text-gray-300' : 'text-gray-700'
                        }`}>
                            {value ? 'Enabled' : 'Disabled'}
                        </span>
                    </label>
                );

            case 'select':
                return (
                    <select
                        value={value}
                        onChange={(e) => handleParameterChange(param.key, e.target.value)}
                        className={`w-full px-3 py-2.5 rounded-lg border text-sm ${
                            darkMode
                                ? 'bg-gray-700 border-gray-600 text-white'
                                : 'bg-white border-gray-300 text-gray-900'
                        } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                    >
                        {param.options?.map(option => (
                            <option key={option} value={option}>
                                {option.replace(/_/g, ' ')}
                            </option>
                        ))}
                    </select>
                );

            case 'number':
                return (
                    <div className="relative">
                        <input
                            type="number"
                            value={value}
                            onChange={(e) => handleParameterChange(
                                param.key, 
                                parseFloat(e.target.value) || 0
                            )}
                            min={param.min}
                            max={param.max}
                            step="any"
                            className={`w-full px-3 py-2.5 rounded-lg border text-sm ${
                                darkMode
                                    ? 'bg-gray-700 border-gray-600 text-white'
                                    : 'bg-white border-gray-300 text-gray-900'
                            } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                        />
                        {(param.min !== undefined || param.max !== undefined) && (
                            <div className={`text-xs mt-1 ${
                                darkMode ? 'text-gray-500' : 'text-gray-500'
                            }`}>
                                Range: {param.min} - {param.max}
                            </div>
                        )}
                    </div>
                );

            case 'text':
            default:
                return (
                    <input
                        type="text"
                        value={value}
                        onChange={(e) => handleParameterChange(param.key, e.target.value)}
                        className={`w-full px-3 py-2.5 rounded-lg border text-sm ${
                            darkMode
                                ? 'bg-gray-700 border-gray-600 text-white'
                                : 'bg-white border-gray-300 text-gray-900'
                        } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                    />
                );
        }
    };

    return (
        <div className="my-4">
            {/* Header */}
            <div className={`mb-6 p-4 rounded-lg border ${
                darkMode 
                    ? 'bg-gradient-to-r from-purple-500/10 to-blue-500/10 border-purple-500/30' 
                    : 'bg-gradient-to-r from-purple-50 to-blue-50 border-purple-200'
            }`}>
                <div className="flex items-start gap-3">
                    <TrendingUp className={`w-6 h-6 flex-shrink-0 ${
                        darkMode ? 'text-purple-400' : 'text-purple-600'
                    }`} />
                    <div>
                        <h3 className={`font-semibold text-base mb-1 ${
                            darkMode ? 'text-white' : 'text-gray-900'
                        }`}>
                            Strategy Parameters
                        </h3>
                        <p className={`text-sm ${
                            darkMode ? 'text-gray-300' : 'text-gray-700'
                        }`}>
                            Configure risk management, order types, and trading rules for your strategy
                        </p>
                    </div>
                </div>
            </div>

            {/* Parameters Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                {parameters.map((param) => (
                    <div
                        key={param.key}
                        className={`p-4 rounded-lg border ${
                            darkMode
                                ? 'bg-gray-800 border-gray-700'
                                : 'bg-white border-gray-200'
                        }`}
                    >
                        <div className="flex items-start gap-2 mb-2">
                            <label className={`block text-sm font-semibold flex-1 ${
                                darkMode ? 'text-gray-200' : 'text-gray-800'
                            }`}>
                                {param.label}
                            </label>
                            {param.description && (
                                <div className="group relative">
                                    <AlertCircle className={`w-4 h-4 cursor-help ${
                                        darkMode ? 'text-gray-500' : 'text-gray-400'
                                    }`} />
                                    <div className={`absolute right-0 top-6 w-64 p-2 rounded-lg text-xs hidden group-hover:block z-10 ${
                                        darkMode 
                                            ? 'bg-gray-700 text-gray-200 border border-gray-600' 
                                            : 'bg-white text-gray-700 border border-gray-300 shadow-lg'
                                    }`}>
                                        {param.description}
                                    </div>
                                </div>
                            )}
                        </div>
                        {renderInput(param)}
                    </div>
                ))}
            </div>

            {/* Save Button */}
            <button
                onClick={handleSave}
                className={`w-full flex items-center justify-center gap-2 px-6 py-3 rounded-lg text-sm font-semibold transition-all ${
                    darkMode
                        ? 'bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700 text-white'
                        : 'bg-gradient-to-r from-purple-500 to-blue-500 hover:from-purple-600 hover:to-blue-600 text-white'
                } shadow-lg hover:shadow-xl transform hover:scale-[1.02]`}
            >
                <Save className="w-5 h-5" />
                Save Strategy Parameters
            </button>
        </div>
    );
}
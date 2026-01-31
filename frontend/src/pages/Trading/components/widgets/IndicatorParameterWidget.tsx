
import { useState, useEffect } from 'react';
import { Save, Info } from 'lucide-react';
import type { IndicatorConfig } from '..';
import { useThemeStore } from '@/stores/themeStore';

interface IndicatorParameterWidgetProps {
    indicator: IndicatorConfig;
    onSave: (indicatorId: string, parameters: Record<string, any>) => void;
    onCancel: () => void;
}

export default function IndicatorParameterWidget({ 
    indicator, 
    onSave, 
    onCancel 
}: IndicatorParameterWidgetProps) {
    const { mode } = useThemeStore()
    const darkMode = mode === 'dark';
    
    const [parameters, setParameters] = useState(indicator.indicatorParameters);

    // Sync parameters when indicator changes
    useEffect(() => {
        setParameters(indicator.indicatorParameters);
    }, [indicator.indicatorId, indicator.indicatorParameters]);

    const handleParameterChange = (key: string, value: any) => {
        setParameters(prev => ({ ...prev, [key]: value }));
    };

    const handleSave = () => {
        onSave(indicator.indicatorId, parameters);
    };

    const renderInput = (key: string, value: any) => {
        const inputType = typeof value === 'boolean' ? 'checkbox' : typeof value === 'number' ? 'number' : 'text';
        
        if (typeof value === 'boolean') {
            return (
                <label className="flex items-center gap-2 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={value}
                        onChange={(e) => handleParameterChange(key, e.target.checked)}
                        className={`w-4 h-4 rounded ${
                            darkMode 
                                ? 'bg-gray-700 border-gray-600' 
                                : 'bg-white border-gray-300'
                        }`}
                    />
                    <span className={`text-sm ${
                        darkMode ? 'text-gray-300' : 'text-gray-700'
                    }`}>
                        {value ? 'Enabled' : 'Disabled'}
                    </span>
                </label>
            );
        }

        return (
            <input
                type={inputType}
                value={value}
                onChange={(e) => handleParameterChange(
                    key, 
                    inputType === 'number' ? parseFloat(e.target.value) || 0 : e.target.value
                )}
                className={`w-full px-3 py-2 rounded-lg border text-sm ${
                    darkMode
                        ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400'
                        : 'bg-white border-gray-300 text-gray-900'
                } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                step={inputType === 'number' ? 'any' : undefined}
            />
        );
    };

    return (
        <div className="p-6">
            {/* Indicator Info Section */}
            <div className={`mb-6 p-4 rounded-lg ${
                darkMode ? 'bg-blue-500/10 border border-blue-500/30' : 'bg-blue-50 border border-blue-200'
            }`}>
                <div className="flex items-start gap-3">
                    <Info className={`w-5 h-5 flex-shrink-0 mt-0.5 ${
                        darkMode ? 'text-blue-400' : 'text-blue-600'
                    }`} />
                    <div>
                        <h4 className={`font-semibold text-sm mb-1 ${
                            darkMode ? 'text-blue-300' : 'text-blue-900'
                        }`}>
                            {indicator.indicatorName}
                        </h4>
                        <p className={`text-xs mb-2 ${
                            darkMode ? 'text-blue-200/80' : 'text-blue-800'
                        }`}>
                            {indicator.indicatorDescription}
                        </p>
                        <div className={`text-xs space-y-1 ${
                            darkMode ? 'text-blue-200/70' : 'text-blue-700'
                        }`}>
                            <div><strong>Signal:</strong> {indicator.signalDescription}</div>
                            <div><strong>Calculation:</strong> {indicator.calculationDescription}</div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Parameters Form */}
            <div className="space-y-4 mb-6">
                <h5 className={`text-sm font-semibold ${
                    darkMode ? 'text-gray-200' : 'text-gray-800'
                }`}>
                    Configure Parameters
                </h5>
                {Object.entries(parameters).map(([key, value]) => (
                    <div key={key}>
                        <label className={`block text-sm font-medium mb-1.5 capitalize ${
                            darkMode ? 'text-gray-300' : 'text-gray-700'
                        }`}>
                            {key.replace(/([A-Z])/g, ' $1').trim()}
                        </label>
                        {renderInput(key, value)}
                    </div>
                ))}
            </div>

            {/* Action Buttons */}
            <div className={`flex gap-3 pt-4 border-t ${darkMode ? 'border-gray-700' : 'border-gray-200'}`}>
                <button
                    onClick={handleSave}
                    className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold transition-all ${
                        darkMode
                            ? 'bg-blue-600 hover:bg-blue-700 text-white'
                            : 'bg-blue-500 hover:bg-blue-600 text-white'
                    } shadow-lg hover:shadow-xl transform hover:scale-[1.02]`}
                >
                    <Save className="w-4 h-4" />
                    Save Parameters
                </button>
                <button
                    onClick={onCancel}
                    className={`px-6 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                        darkMode
                            ? 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                            : 'bg-gray-200 hover:bg-gray-300 text-gray-700'
                    }`}
                >
                    Cancel
                </button>
            </div>
        </div>
    );
}
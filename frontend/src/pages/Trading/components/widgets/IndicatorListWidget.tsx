import { Settings } from 'lucide-react';
import type { IndicatorConfig } from '..';
import { useThemeStore } from '@/stores/themeStore';

interface IndicatorListWidgetProps {
    indicators: IndicatorConfig[];
    onConfigureParameters: (indicatorId: string) => void;
}

export default function IndicatorListWidget({ 
    indicators, 
    onConfigureParameters 
}: IndicatorListWidgetProps) {
    const { mode, appMode } = useThemeStore()
    const darkMode = mode === 'dark' || appMode === 'analyzer';

    return (
        <div className="flex flex-col gap-3 my-4 max-h-[500px] overflow-y-auto hide-scrollbar">
            {indicators.map((indicator) => {
                return (
                    <div
                        key={indicator.indicatorId}
                        className={`p-4 rounded-lg border transition-all ${
                            darkMode
                                ? 'bg-gray-800 border-gray-600'
                                : 'bg-white border-gray-300'
                        }`}
                    >
                        <div className="flex items-start gap-3">
                            {/* Indicator Info */}
                            <div className="flex-1 min-w-0">
                                <div className="flex items-start justify-between gap-2 mb-2">
                                    <div>
                                        <h4 className={`font-semibold text-sm ${
                                            darkMode ? 'text-white' : 'text-gray-900'
                                        }`}>
                                            {indicator.indicatorName}
                                        </h4>
                                        <span className={`text-xs ${
                                            darkMode ? 'text-gray-400' : 'text-gray-600'
                                        }`}>
                                            {indicator.indicatorType} • {indicator.indicatorPurpose}
                                        </span>
                                    </div>
                                    
                                    {/* Configure Button */}
                                    <button
                                        onClick={() => onConfigureParameters(indicator.indicatorId)}
                                        className={`p-2 rounded-lg transition-all flex items-center gap-1.5 ${
                                            darkMode
                                                ? 'bg-blue-600/20 hover:bg-blue-600/30 text-blue-400'
                                                : 'bg-blue-100 hover:bg-blue-200 text-blue-700'
                                        } shadow-sm hover:shadow`}
                                        title="Configure parameters"
                                    >
                                        <Settings className="w-4 h-4" />
                                        <span className="text-xs font-medium">Configure</span>
                                    </button>
                                </div>

                                <p className={`text-xs mb-2 ${
                                    darkMode ? 'text-gray-400' : 'text-gray-600'
                                }`}>
                                    {indicator.indicatorDescription}
                                </p>

                                {/* Signal Info */}
                                <div className={`text-xs px-2 py-1 rounded ${
                                    darkMode ? 'bg-gray-700/50 text-gray-400' : 'bg-gray-100 text-gray-600'
                                }`}>
                                    <strong>Signal:</strong> {indicator.signalDescription}
                                </div>
                            </div>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
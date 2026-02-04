import { useThemeStore } from '@/stores/themeStore';
import { Play, Square, TrendingUp } from 'lucide-react';

interface ReRunConfirmationWidgetProps {
    profit: number;
    onConfirm: () => void;
    onStop: () => void;
}

export default function ReRunConfirmationWidget({ profit, onConfirm, onStop }: ReRunConfirmationWidgetProps) {
    const { mode, appMode } = useThemeStore()
    const darkMode = mode === 'dark' || appMode === 'analyzer';

    return (
        <div className={`my-4 p-5 rounded-xl border ${
            darkMode 
                ? 'bg-gradient-to-br from-green-500/10 to-emerald-500/10 border-green-500/30' 
                : 'bg-gradient-to-br from-green-50 to-emerald-50 border-green-200'
        }`}>
            <div className="flex items-center gap-3 mb-4">
                <div className={`p-3 rounded-xl ${
                    darkMode ? 'bg-green-500/20' : 'bg-green-100'
                }`}>
                    <TrendingUp className={`w-6 h-6 ${
                        darkMode ? 'text-green-400' : 'text-green-600'
                    }`} />
                </div>
                <div>
                    <h3 className={`font-bold text-lg ${
                        darkMode ? 'text-white' : 'text-gray-900'
                    }`}>
                        Profitable Trade! 🎉
                    </h3>
                    <p className={`text-sm ${
                        darkMode ? 'text-green-300' : 'text-green-700'
                    }`}>
                        Net profit: <strong>₹{profit.toFixed(2)}</strong>
                    </p>
                </div>
            </div>

            <p className={`text-sm mb-4 ${
                darkMode ? 'text-gray-300' : 'text-gray-700'
            }`}>
                Your strategy completed a successful trade. Would you like to continue running the strategy for the next opportunity?
            </p>

            <div className="flex gap-3">
                <button
                    onClick={onConfirm}
                    className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg text-sm font-bold transition-all ${
                        darkMode
                            ? 'bg-green-600 hover:bg-green-700 text-white'
                            : 'bg-green-500 hover:bg-green-600 text-white'
                    } shadow-lg hover:shadow-xl transform hover:scale-[1.02]`}
                >
                    <Play className="w-4 h-4" />
                    Yes, Continue
                </button>
                <button
                    onClick={onStop}
                    className={`px-6 py-3 rounded-lg text-sm font-bold transition-colors ${
                        darkMode
                            ? 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                            : 'bg-gray-200 hover:bg-gray-300 text-gray-700'
                    }`}
                >
                    <Square className="w-4 h-4 inline mr-1" />
                    Stop Strategy
                </button>
            </div>
        </div>
    );
}
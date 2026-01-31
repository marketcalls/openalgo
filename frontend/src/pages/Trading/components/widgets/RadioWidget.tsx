import { useThemeStore } from "@/stores/themeStore";
import type { RadioOption } from "..";


interface RadioWidgetProps {
    options: RadioOption[];
    selectedValue: string | null;
    onSelect: (value: string) => void;
}

export default function RadioWidget({ options, selectedValue, onSelect }: RadioWidgetProps) {
    const { mode } = useThemeStore()
    const darkMode = mode === 'dark';

    return (
        <div className="flex flex-col gap-2 my-4">
            {options.map((option) => (
                <button
                    key={option.value}
                    onClick={() => onSelect(option.value)}
                    className={`p-3 rounded-lg border text-left transition-all ${
                        selectedValue === option.value
                            ? darkMode
                                ? 'bg-blue-600/20 border-blue-500 ring-2 ring-blue-500'
                                : 'bg-blue-50 border-blue-500 ring-2 ring-blue-500'
                            : darkMode
                                ? 'bg-gray-800 border-gray-600 hover:border-gray-500'
                                : 'bg-white border-gray-300 hover:border-gray-400'
                    }`}
                >
                    <div className="flex items-center gap-3">
                        <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                            selectedValue === option.value
                                ? darkMode
                                    ? 'border-blue-500'
                                    : 'border-blue-600'
                                : darkMode
                                    ? 'border-gray-600'
                                    : 'border-gray-400'
                        }`}>
                            {selectedValue === option.value && (
                                <div className={`w-2 h-2 rounded-full ${
                                    darkMode ? 'bg-blue-500' : 'bg-blue-600'
                                }`} />
                            )}
                        </div>
                        <div className="flex-1">
                            <div className={`font-medium text-sm ${
                                darkMode ? 'text-white' : 'text-gray-900'
                            }`}>
                                {option.label}
                            </div>
                            {option.description && (
                                <div className={`text-xs mt-0.5 ${
                                    darkMode ? 'text-gray-400' : 'text-gray-600'
                                }`}>
                                    {option.description}
                                </div>
                            )}
                        </div>
                    </div>
                </button>
            ))}
        </div>
    );
}
import { useThemeStore } from '@/stores/themeStore';
import { X } from 'lucide-react';
import { useEffect } from 'react';

interface ModalProps {
    isOpen: boolean;
    onClose: () => void;
    children: React.ReactNode;
    title?: string;
}

export default function Modal({ isOpen, onClose, children, title }: ModalProps) {
    const { mode, appMode } = useThemeStore()
    const darkMode = mode === 'dark' || appMode === 'analyzer';

    // Prevent body scroll when modal is open
    useEffect(() => {
        if (isOpen) {
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = 'unset';
        }
        return () => {
            document.body.style.overflow = 'unset';
        };
    }, [isOpen]);

    // Handle escape key
    useEffect(() => {
        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && isOpen) {
                onClose();
            }
        };
        document.addEventListener('keydown', handleEscape);
        return () => document.removeEventListener('keydown', handleEscape);
    }, [isOpen, onClose]);

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
                className={`relative w-full max-w-2xl max-h-[85vh] m-4 rounded-xl shadow-2xl overflow-hidden ${
                    darkMode ? 'bg-gray-800' : 'bg-white'
                }`}
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                {title && (
                    <div className={`flex items-center justify-between px-6 py-4 border-b ${
                        darkMode ? 'border-gray-700' : 'border-gray-200'
                    }`}>
                        <h3 className={`text-lg font-semibold ${
                            darkMode ? 'text-white' : 'text-gray-900'
                        }`}>
                            {title}
                        </h3>
                        <button
                            onClick={onClose}
                            className={`p-1 rounded-lg transition-colors ${
                                darkMode
                                    ? 'hover:bg-gray-700 text-gray-400'
                                    : 'hover:bg-gray-100 text-gray-600'
                            }`}
                        >
                            <X className="w-5 h-5" />
                        </button>
                    </div>
                )}
                
                {/* Body */}
                <div className="overflow-y-auto max-h-[calc(85vh-80px)] hide-scrollbar">
                    {children}
                </div>
            </div>
        </div>
    );
}
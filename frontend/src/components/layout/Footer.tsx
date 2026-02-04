import { useThemeStore } from '@/stores/themeStore';
import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';

type FooterLink = 'terms' | 'disclaimer';

const footerFiles: Record<FooterLink, string> = {
    terms: '/docs/terms.md',
    disclaimer: '/docs/disclaimer.md',
};

const footerTitles: Record<FooterLink, string> = {
    terms: 'Terms & Conditions',
    disclaimer: 'Disclaimer',
};

const tooltipText: Record<FooterLink, string> = {
    terms: 'Click here to know more about company terms and conditions',
    disclaimer: 'Click here to know more about company disclaimer',
};

/**
 * The .md files use plain text lines instead of proper markdown syntax.
 * This function converts them into well-structured markdown so ReactMarkdown
 * can render headings, bullet lists, and paragraphs correctly.
 */
function preprocessMarkdown(raw: string): string {
    const lines = raw.split('\n');
    const result: string[] = [];

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trim();

        // Skip empty lines — we'll add spacing via markdown structure
        if (!trimmed) {
            result.push('');
            continue;
        }

        // Main document title (first non-empty line or specific titles)
        if (
            trimmed === 'Terms and Conditions' ||
            trimmed === 'Risk Disclaimer & Legal Notice'
        ) {
            result.push(`# ${trimmed}`);
            continue;
        }

        // Subtitle line (platform name line right after title)
        if (trimmed.startsWith('Zenxo.ai - ')) {
            result.push(`*${trimmed}*`);
            continue;
        }

        // Effective/Updated date line
        if (trimmed.startsWith('Effective Date:') || trimmed.startsWith('Last Updated:')) {
            result.push(`> ${trimmed}`);
            continue;
        }

        // Section headings like "1\. Introduction and Acceptance" or "10\. Changes"
        if (/^\d+\\?\.\s+/.test(trimmed)) {
            const heading = trimmed.replace(/^(\d+)\\\./, '$1.');
            result.push(`## ${heading}`);
            continue;
        }

        // Sub-section headings like "1.1 Agreement to Terms"
        if (/^\d+\.\d+\s+/.test(trimmed)) {
            result.push(`### ${trimmed}`);
            continue;
        }

        // Category sub-headings (like "Market Risks", "AI and Strategy Risks")
        // These are standalone short lines followed by bullet-like items
        const nextNonEmpty = lines.slice(i + 1).find((l) => l.trim() !== '');
        if (
            trimmed.length < 60 &&
            !trimmed.endsWith('.') &&
            !trimmed.endsWith(':') &&
            !trimmed.startsWith('—') &&
            !trimmed.startsWith('-') &&
            !/^\d/.test(trimmed) &&
            !trimmed.startsWith('You ') &&
            !trimmed.startsWith('We ') &&
            !trimmed.startsWith('Our ') &&
            !trimmed.startsWith('Any ') &&
            !trimmed.startsWith('All ') &&
            !trimmed.startsWith('Be ') &&
            !trimmed.startsWith('Have ') &&
            !trimmed.startsWith('Not ') &&
            !trimmed.startsWith('If ') &&
            !trimmed.startsWith('In ') &&
            !trimmed.startsWith('The ') &&
            !trimmed.startsWith('To ') &&
            !trimmed.startsWith('No ') &&
            !trimmed.startsWith('TRADE') &&
            !trimmed.startsWith('BY ') &&
            !trimmed.startsWith('PLEASE') &&
            !trimmed.startsWith('THE ') &&
            !trimmed.startsWith('ZENXO') &&
            !trimmed.startsWith('TO THE') &&
            nextNonEmpty &&
            /^[A-Z]/.test(trimmed) &&
            // Check if next line looks like a list item (short, no period, or starts with a known pattern)
            nextNonEmpty.trim().length < 80
        ) {
            // Check if this looks like a category label above list items
            const nextTrimmed = nextNonEmpty.trim();
            if (
                !nextTrimmed.startsWith('#') &&
                !/^\d+[\\.]/.test(nextTrimmed) &&
                trimmed !== 'Important Notice' &&
                trimmed !== 'Summary of Key Points' &&
                !trimmed.startsWith('Risk Category')
            ) {
                // Only make it a bold label if it's clearly a sub-category
                if (
                    trimmed === 'Market Risks' ||
                    trimmed === 'Algorithmic Trading Risks' ||
                    trimmed === 'AI and Strategy Risks' ||
                    trimmed === 'Broker and Execution Risks'
                ) {
                    result.push(`**${trimmed}**`);
                    continue;
                }
            }
        }

        // "Important Notice" and "Summary of Key Points" as H2
        if (trimmed === 'Important Notice' || trimmed === 'Summary of Key Points') {
            result.push(`## ${trimmed}`);
            continue;
        }

        // Lines that are short, don't end with period, and appear to be list items
        // (standalone lines between blank lines that aren't headings)
        const prevLine = i > 0 ? lines[i - 1].trim() : '';
        const nextLine = i < lines.length - 1 ? lines[i + 1].trim() : '';

        if (
            prevLine === '' &&
            nextLine === '' &&
            trimmed.length < 80 &&
            !trimmed.endsWith('.') &&
            !trimmed.startsWith('#') &&
            !trimmed.startsWith('*') &&
            !trimmed.startsWith('>') &&
            !/^\d+[\\.]/.test(trimmed) &&
            !trimmed.startsWith('TRADE') &&
            !trimmed.startsWith('BY ') &&
            !trimmed.startsWith('PLEASE') &&
            !trimmed.startsWith('Risk Category')
        ) {
            result.push(`- ${trimmed}`);
            continue;
        }

        // Everything else is a regular paragraph
        result.push(trimmed);
    }

    // Clean up excessive blank lines
    return result.join('\n').replace(/\n{3,}/g, '\n\n');
}

export const Footer: React.FC = () => {
    const { mode, appMode } = useThemeStore()
    const isDark = mode === 'dark' || appMode === 'analyzer';
    const subTextClass = isDark ? 'text-gray-400' : 'text-gray-600';

    const [activeModal, setActiveModal] = useState<FooterLink | null>(null);
    const [content, setContent] = useState<string>('');
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        if (!activeModal) return;
        setLoading(true);
        fetch(footerFiles[activeModal])
            .then((res) => res.text())
            .then((text) => {
                setContent(preprocessMarkdown(text));
                setLoading(false);
            })
            .catch(() => {
                setContent('Failed to load content.');
                setLoading(false);
            });
    }, [activeModal]);

    const closeModal = () => {
        setActiveModal(null);
        setContent('');
    };

    const markdownComponents: Components = {
        h1: ({ children }) => (
            <h1 className={`text-2xl font-bold mb-1 pb-2 border-b ${isDark ? 'text-white border-gray-600' : 'text-gray-900 border-gray-300'}`}>
                {children}
            </h1>
        ),
        h2: ({ children }) => (
            <h2 className={`text-lg font-bold mt-6 mb-2 pb-1 border-b ${isDark ? 'text-blue-400 border-gray-700' : 'text-blue-700 border-gray-200'}`}>
                {children}
            </h2>
        ),
        h3: ({ children }) => (
            <h3 className={`text-base font-semibold mt-4 mb-1 ${isDark ? 'text-gray-200' : 'text-gray-800'}`}>
                {children}
            </h3>
        ),
        p: ({ children }) => (
            <p className={`text-sm leading-relaxed mb-2 ${isDark ? 'text-gray-300' : 'text-gray-700'}`}>
                {children}
            </p>
        ),
        ul: ({ children }) => (
            <ul className={`list-disc list-outside ml-5 mb-3 space-y-1 text-sm ${isDark ? 'text-gray-300' : 'text-gray-700'}`}>
                {children}
            </ul>
        ),
        li: ({ children }) => (
            <li className="leading-relaxed">{children}</li>
        ),
        strong: ({ children }) => (
            <strong className={`font-semibold ${isDark ? 'text-gray-100' : 'text-gray-900'}`}>
                {children}
            </strong>
        ),
        blockquote: ({ children }) => (
            <blockquote className={`border-l-4 pl-3 my-2 text-xs italic ${isDark ? 'border-blue-500 text-gray-400' : 'border-blue-400 text-gray-500'}`}>
                {children}
            </blockquote>
        ),
        em: ({ children }) => (
            <em className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
                {children}
            </em>
        ),
        a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-500 underline hover:text-blue-600">
                {children}
            </a>
        ),
    };

    return (
        <>
            <footer
                className={`px-4 py-1 border-t text-center text-sm
          ${isDark
                        ? 'bg-gray-800 border-gray-700'
                        : 'bg-gray-50 border-gray-200'
                    }`}
            >
                <p className={`mb-1 ${subTextClass}`}>
                    © 2026 <span className="font-semibold">Smart Touch Infotech Private Limited</span>. All rights reserved.
                </p>

                <div className="flex justify-center gap-4">
                    {(['terms', 'disclaimer'] as FooterLink[]).map((item) => (
                        <div key={item} className="relative group">
                            <button
                                onClick={() => setActiveModal(item)}
                                className={`
                                text-xs
                                font-medium
                                underline-offset-2
                                hover:underline
                                transition-colors
                                ${mode === 'dark'
                                    ? 'text-gray-400 hover:text-gray-200'
                                    : 'text-gray-600 hover:text-gray-800'}
                                `}
                            >
                                {footerTitles[item]}
                            </button>

                            <div
                                className={`absolute bottom-full mb-2 left-1/2 -translate-x-1/2
    whitespace-nowrap px-3 py-1.5 rounded-md text-xs z-10
    opacity-0 group-hover:opacity-100 transition-opacity
    ${isDark
                                        ? 'bg-gray-700 text-gray-200'
                                        : 'bg-gray-200 text-gray-800'
                                    }`}
                            >
                                {tooltipText[item]}
                            </div>
                        </div>
                    ))}
                </div>
            </footer>

            {activeModal && (
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
                    onClick={closeModal}
                >
                    <div
                        onClick={(e) => e.stopPropagation()}
                        className={`w-full max-w-2xl max-h-[80vh] flex flex-col rounded-lg shadow-xl mx-4
              ${isDark
                                ? 'bg-gray-800 text-gray-100'
                                : 'bg-white text-gray-800'
                            }`}
                    >
                        <div className={`flex items-center justify-between px-6 py-4 border-b shrink-0 ${isDark ? 'border-gray-700' : 'border-gray-200'}`}>
                            <h3 className="text-lg font-bold">
                                {footerTitles[activeModal]}
                            </h3>
                            <button
                                onClick={closeModal}
                                className={`text-xl leading-none px-2 py-1 rounded hover:bg-gray-500/20`}
                            >
                                ✕
                            </button>
                        </div>

                        <div className="flex-1 overflow-y-auto px-6 py-4">
                            {loading ? (
                                <div className="flex items-center justify-center py-10">
                                    <div className="animate-spin rounded-full h-6 w-6 border-2 border-blue-500 border-t-transparent"></div>
                                    <span className="ml-2 text-sm">Loading...</span>
                                </div>
                            ) : (
                                <div className="max-w-none">
                                    <ReactMarkdown components={markdownComponents}>
                                        {content}
                                    </ReactMarkdown>
                                </div>
                            )}
                        </div>

                        <div className={`flex justify-end px-6 py-3 border-t shrink-0 ${isDark ? 'border-gray-700' : 'border-gray-200'}`}>
                            <button
                                onClick={closeModal}
                                className={`px-4 py-2 rounded-lg text-sm font-medium
                  ${isDark
                                        ? 'bg-blue-600 hover:bg-blue-700 text-white'
                                        : 'bg-blue-500 hover:bg-blue-600 text-white'
                                    }`}
                            >
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};

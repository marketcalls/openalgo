/**
 * Professional Trading Terminal JavaScript Module
 * Handles interactivity, animations, and real-time updates
 */

// Professional Terminal Module
const ProfessionalTerminal = (function() {
    'use strict';

    // Configuration
    const config = {
        animationDuration: 300,
        updateInterval: 5000,
        priceFlashDuration: 600,
        themes: {
            'professional': { name: 'Professional', icon: '☀️' },
            'professional_dark': { name: 'Professional Dark', icon: '🌙' },
            'analytics': { name: 'Analytics', icon: '📊' }
        }
    };

    // Price Formatter
    const formatPrice = (value, decimals = 2) => {
        if (isNaN(value)) return '0.00';
        return new Intl.NumberFormat('en-IN', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        }).format(value);
    };

    // Percentage Formatter
    const formatPercentage = (value, showSign = true) => {
        if (isNaN(value)) return '0.00%';
        const formatted = Math.abs(value).toFixed(2) + '%';
        if (showSign && value > 0) return '+' + formatted;
        if (showSign && value < 0) return '-' + formatted;
        return formatted;
    };

    // Animate Number Changes
    const animateNumber = (element, startValue, endValue, duration = 600) => {
        const startTime = Date.now();
        const difference = endValue - startValue;

        const animate = () => {
            const elapsed = Date.now() - startTime;
            const progress = Math.min(elapsed / duration, 1);

            // Easing function
            const easeOutQuad = t => t * (2 - t);
            const currentValue = startValue + (difference * easeOutQuad(progress));

            element.textContent = formatPrice(currentValue);

            if (progress < 1) {
                requestAnimationFrame(animate);
            } else {
                element.textContent = formatPrice(endValue);
                // Flash effect on completion
                flashElement(element, endValue > startValue);
            }
        };

        requestAnimationFrame(animate);
    };

    // Flash Element (for price updates)
    const flashElement = (element, isPositive = true) => {
        const flashClass = isPositive ? 'flash-positive' : 'flash-negative';
        element.classList.add(flashClass);
        setTimeout(() => {
            element.classList.remove(flashClass);
        }, config.priceFlashDuration);
    };

    // Initialize Price Animations
    const initPriceAnimations = () => {
        // Add CSS for flash effects
        if (!document.getElementById('price-flash-styles')) {
            const style = document.createElement('style');
            style.id = 'price-flash-styles';
            style.textContent = `
                @keyframes flash-positive {
                    0% { background-color: rgba(16, 185, 129, 0.2); }
                    100% { background-color: transparent; }
                }
                @keyframes flash-negative {
                    0% { background-color: rgba(239, 68, 68, 0.2); }
                    100% { background-color: transparent; }
                }
                .flash-positive {
                    animation: flash-positive 0.6s ease-out;
                }
                .flash-negative {
                    animation: flash-negative 0.6s ease-out;
                }
            `;
            document.head.appendChild(style);
        }

        // Animate metric values on page load
        document.querySelectorAll('.metric-value .font-mono').forEach(el => {
            const value = parseFloat(el.textContent.replace(/[,₹]/g, ''));
            if (!isNaN(value) && value !== 0) {
                const startValue = 0;
                setTimeout(() => {
                    animateNumber(el, startValue, value);
                }, Math.random() * 200); // Stagger animations
            }
        });
    };

    // Initialize Smooth Theme Transitions
    const initThemeTransitions = () => {
        // Add transition classes to body
        document.body.style.transition = 'background-color 0.3s ease, color 0.3s ease';

        // Override theme change to add smooth transition
        const originalSetTheme = window.setTheme;
        if (originalSetTheme) {
            window.setTheme = function(theme) {
                document.body.classList.add('theme-transitioning');
                originalSetTheme(theme);
                setTimeout(() => {
                    document.body.classList.remove('theme-transitioning');
                }, 300);
            };
        }
    };

    // Initialize Table Row Hover Effects
    const initTableEffects = () => {
        // Add hover delay for better UX
        document.querySelectorAll('.data-table tbody tr').forEach(row => {
            let hoverTimeout;

            row.addEventListener('mouseenter', () => {
                hoverTimeout = setTimeout(() => {
                    row.classList.add('row-hover');
                }, 50);
            });

            row.addEventListener('mouseleave', () => {
                clearTimeout(hoverTimeout);
                row.classList.remove('row-hover');
            });
        });
    };

    // Initialize Tooltips
    const initTooltips = () => {
        // Create tooltip container
        let tooltipContainer = document.getElementById('tooltip-container');
        if (!tooltipContainer) {
            tooltipContainer = document.createElement('div');
            tooltipContainer.id = 'tooltip-container';
            tooltipContainer.className = 'fixed z-50 px-2 py-1 text-xs font-medium text-white bg-gray-900 rounded shadow-lg opacity-0 pointer-events-none transition-opacity duration-200';
            document.body.appendChild(tooltipContainer);
        }

        // Add tooltips to elements with title attribute
        document.querySelectorAll('[title]').forEach(element => {
            const tooltipText = element.getAttribute('title');
            element.removeAttribute('title');
            element.setAttribute('data-tooltip', tooltipText);

            element.addEventListener('mouseenter', (e) => {
                tooltipContainer.textContent = tooltipText;
                tooltipContainer.classList.remove('opacity-0');
                tooltipContainer.classList.add('opacity-100');

                const rect = element.getBoundingClientRect();
                tooltipContainer.style.left = rect.left + (rect.width / 2) - (tooltipContainer.offsetWidth / 2) + 'px';
                tooltipContainer.style.top = rect.top - tooltipContainer.offsetHeight - 8 + 'px';
            });

            element.addEventListener('mouseleave', () => {
                tooltipContainer.classList.remove('opacity-100');
                tooltipContainer.classList.add('opacity-0');
            });
        });
    };

    // Initialize Keyboard Shortcuts
    const initKeyboardShortcuts = () => {
        document.addEventListener('keydown', (e) => {
            // Alt + T: Toggle Theme
            if (e.altKey && e.key === 't') {
                e.preventDefault();
                const themes = Object.keys(config.themes);
                const currentTheme = localStorage.getItem('theme') || 'professional';
                const currentIndex = themes.indexOf(currentTheme);
                const nextIndex = (currentIndex + 1) % themes.length;
                window.setTheme(themes[nextIndex]);
            }

            // Alt + D: Go to Dashboard
            if (e.altKey && e.key === 'd') {
                e.preventDefault();
                window.location.href = '/dashboard';
            }

            // Alt + O: Go to Order Book
            if (e.altKey && e.key === 'o') {
                e.preventDefault();
                window.location.href = '/orderbook';
            }

            // Alt + P: Go to Positions
            if (e.altKey && e.key === 'p') {
                e.preventDefault();
                window.location.href = '/positions';
            }
        });
    };

    // Initialize Real-time Data Simulation (for demo)
    const initRealTimeSimulation = () => {
        // Only simulate if we're on dashboard
        if (!window.location.pathname.includes('dashboard')) return;

        setInterval(() => {
            // Simulate market ticker updates
            document.querySelectorAll('.ticker-item').forEach(item => {
                const valueEl = item.querySelector('.ticker-value');
                const changeEl = item.querySelector('.ticker-change');

                if (valueEl && changeEl) {
                    const currentValue = parseFloat(valueEl.textContent.replace(/[,]/g, ''));
                    const change = (Math.random() - 0.5) * 100; // Random change
                    const newValue = currentValue + change;

                    // Update value with animation
                    animateNumber(valueEl, currentValue, newValue, 300);

                    // Update change percentage
                    const changePercent = (change / currentValue) * 100;
                    changeEl.textContent = formatPercentage(changePercent);

                    // Update color
                    if (change > 0) {
                        changeEl.classList.remove('text-error');
                        changeEl.classList.add('text-success');
                    } else {
                        changeEl.classList.remove('text-success');
                        changeEl.classList.add('text-error');
                    }
                }
            });
        }, config.updateInterval);
    };

    // Initialize Smooth Scroll
    const initSmoothScroll = () => {
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function(e) {
                e.preventDefault();
                const target = document.querySelector(this.getAttribute('href'));
                if (target) {
                    target.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }
            });
        });
    };

    // Initialize Loading States
    const initLoadingStates = () => {
        // Add loading class to buttons on click
        document.querySelectorAll('.btn-pro').forEach(button => {
            button.addEventListener('click', function() {
                if (!this.classList.contains('btn-loading')) {
                    this.classList.add('btn-loading');
                    setTimeout(() => {
                        this.classList.remove('btn-loading');
                    }, 1000);
                }
            });
        });
    };

    // Public API
    return {
        init: function() {
            // Initialize all components
            initPriceAnimations();
            initThemeTransitions();
            initTableEffects();
            initTooltips();
            initKeyboardShortcuts();
            initRealTimeSimulation();
            initSmoothScroll();
            initLoadingStates();

            console.log('Professional Terminal initialized successfully');
        },

        // Expose utility functions
        formatPrice: formatPrice,
        formatPercentage: formatPercentage,
        animateNumber: animateNumber,
        flashElement: flashElement
    };
})();

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ProfessionalTerminal.init);
} else {
    ProfessionalTerminal.init();
}

// Export for use in other modules
window.ProfessionalTerminal = ProfessionalTerminal;
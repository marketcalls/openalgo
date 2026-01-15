// Theme management
const themeKey = 'theme';
const previousThemeKey = 'previousTheme';
const defaultTheme = 'light';
const analyzeTheme = 'dracula';
const themes = [
    'light', 'dark', 'cupcake', 'bumblebee', 'emerald', 'corporate',
    'synthwave', 'retro', 'cyberpunk', 'valentine', 'halloween', 'garden',
    'aqua', 'lofi', 'pastel', 'fantasy', 'wireframe',
    'luxury', 'dracula', 'cmyk', 'autumn', 'business', 'acid', 'lemonade',
    'night', 'coffee', 'winter', 'dim', 'nord', 'sunset'
];

// Check if we're in analyze mode
function isAnalyzeMode() {
    const analyzeMode = sessionStorage.getItem('analyzeMode') || localStorage.getItem('analyzeMode');
    return analyzeMode === 'true';
}

// Set theme and persist to localStorage
function setTheme(theme, force = false) {
    // If in analyze mode and not forcing, don't allow theme changes
    if (!force && isAnalyzeMode() && theme !== analyzeTheme) {
        console.log('[Theme] Cannot change theme while in Analyze Mode');
        return;
    }

    if (!themes.includes(theme)) {
        theme = defaultTheme;
    }

    // Store current theme before changing to dracula (analyze mode)
    if (!force && theme === analyzeTheme) {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        if (currentTheme !== analyzeTheme) {
            localStorage.setItem(previousThemeKey, currentTheme);
            sessionStorage.setItem(previousThemeKey, currentTheme);
        }
    }

    document.documentElement.setAttribute('data-theme', theme);

    // Only update localStorage if not dracula theme or if forced
    if (theme !== analyzeTheme || force) {
        localStorage.setItem(themeKey, theme);
        sessionStorage.setItem(themeKey, theme);
    }

    // Update theme controller checkboxes and visibility
    const themeControllers = document.querySelectorAll('.theme-controller');
    const themeSwitcher = document.querySelector('.theme-switcher');

    const shouldBeChecked = theme === 'dark';
    const shouldBeDisabled = theme === 'dracula';

    // Temporarily hide theme switcher during state change to prevent visible flip
    if (themeSwitcher) {
        themeSwitcher.style.transition = 'none';
        themeSwitcher.style.opacity = '0';
    }

    themeControllers.forEach(controller => {
        // Only update if different to prevent icon flip
        if (controller.checked !== shouldBeChecked) {
            controller.checked = shouldBeChecked;
        }
        controller.disabled = shouldBeDisabled;
    });

    // Toggle theme switcher disabled state and show it
    if (themeSwitcher) {
        if (theme === 'dracula') {
            themeSwitcher.classList.add('disabled');
        } else {
            themeSwitcher.classList.remove('disabled');
        }

        // Small delay to ensure checkbox state is applied, then show
        setTimeout(() => {
            themeSwitcher.style.transition = '';
            themeSwitcher.style.opacity = '1';
        }, 10);
    }
}

// Theme toggle event handler
function handleThemeToggle(e) {
    // Don't allow theme toggle in analyze mode
    if (isAnalyzeMode()) {
        e.preventDefault();
        e.target.checked = !e.target.checked; // Revert the toggle
        return;
    }
    const newTheme = e.target.checked ? 'dark' : 'light';
    setTheme(newTheme);
}

// Initialize theme from localStorage or sessionStorage
function initializeTheme() {
    // If in analyze mode, always use analyze theme
    if (isAnalyzeMode()) {
        document.documentElement.setAttribute('data-theme', analyzeTheme);

        // Update controllers only if different
        const themeControllers = document.querySelectorAll('.theme-controller');
        themeControllers.forEach(controller => {
            if (controller.checked !== false) {
                controller.checked = false;
            }
            controller.disabled = true;
        });

        // Update theme switcher state
        const themeSwitcher = document.querySelector('.theme-switcher');
        if (themeSwitcher) {
            themeSwitcher.classList.add('disabled');
        }

        return analyzeTheme;
    }

    // Check sessionStorage first for navigation consistency
    const sessionTheme = sessionStorage.getItem(themeKey);
    const savedTheme = sessionTheme || localStorage.getItem(themeKey) || defaultTheme;

    // Set theme without triggering storage events
    document.documentElement.setAttribute('data-theme', savedTheme);

    // Update controllers only if different
    const shouldBeChecked = savedTheme === 'dark';
    const themeControllers = document.querySelectorAll('.theme-controller');
    themeControllers.forEach(controller => {
        if (controller.checked !== shouldBeChecked) {
            controller.checked = shouldBeChecked;
        }
        controller.disabled = false;
    });

    // Update theme switcher state
    const themeSwitcher = document.querySelector('.theme-switcher');
    if (themeSwitcher) {
        themeSwitcher.classList.remove('disabled');
    }

    return savedTheme;
}

// Function to restore previous theme
function restorePreviousTheme() {
    const previousTheme = localStorage.getItem(previousThemeKey) || sessionStorage.getItem(previousThemeKey) || defaultTheme;

    if (previousTheme && previousTheme !== 'dracula') {
        setTheme(previousTheme, true);
        // Clear the stored previous theme after restoration
        localStorage.removeItem(previousThemeKey);
        sessionStorage.removeItem(previousThemeKey);
    } else {
        setTheme(defaultTheme, true);
    }
}

// Initialize theme immediately to prevent flash
(function() {
    // Check if we're in analyze mode first
    const analyzeMode = sessionStorage.getItem('analyzeMode') || localStorage.getItem('analyzeMode');
    if (analyzeMode === 'true') {
        document.documentElement.setAttribute('data-theme', analyzeTheme);
        return;
    }

    const savedTheme = localStorage.getItem(themeKey) || sessionStorage.getItem(themeKey) || defaultTheme;
    document.documentElement.setAttribute('data-theme', savedTheme);
})();

// Add event listeners when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Initialize theme
    const currentTheme = initializeTheme();
    
    // Set initial state of theme toggles and add event listeners
    const themeControllers = document.querySelectorAll('.theme-controller');
    themeControllers.forEach(controller => {
        // Only update if state is different to prevent icon flip
        const shouldBeChecked = currentTheme === 'dark';
        if (controller.checked !== shouldBeChecked) {
            controller.checked = shouldBeChecked;
        }
        controller.addEventListener('change', handleThemeToggle);
    });

    // Handle page visibility changes
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            // If in analyze mode, always enforce analyze theme
            if (isAnalyzeMode()) {
                const currentTheme = document.documentElement.getAttribute('data-theme');
                if (currentTheme !== analyzeTheme) {
                    document.documentElement.setAttribute('data-theme', analyzeTheme);
                }
                return;
            }

            // When page becomes visible, ensure theme is consistent
            const sessionTheme = sessionStorage.getItem(themeKey);
            if (sessionTheme) {
                setTheme(sessionTheme);
            }
        }
    });

    // Handle storage events for cross-tab consistency
    window.addEventListener('storage', function(e) {
        // Check for analyze mode changes
        if (e.key === 'analyzeMode') {
            const isAnalyze = e.newValue === 'true';
            if (isAnalyze) {
                document.documentElement.setAttribute('data-theme', analyzeTheme);
                initializeTheme();
            } else {
                initializeTheme();
            }
            return;
        }

        // Don't change theme if in analyze mode
        if (e.key === themeKey && !isAnalyzeMode()) {
            const newTheme = e.newValue || defaultTheme;
            setTheme(newTheme);
        }
    });
});

// Export functions for use in other scripts
window.themeManager = {
    setTheme,
    restorePreviousTheme,
    initializeTheme,
    isAnalyzeMode,
    defaultTheme,
    analyzeTheme
};

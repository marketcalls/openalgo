// Theme management
const themeKey = 'theme';
const previousThemeKey = 'previousTheme';
const defaultTheme = 'light';
const themes = ['light', 'dark', 'garden'];

// Set theme and persist to localStorage
function setTheme(theme, force = false) {
    if (!themes.includes(theme)) {
        theme = defaultTheme;
    }
    
    // Store current theme before changing to garden
    if (!force && theme === 'garden') {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        if (currentTheme !== 'garden') {
            localStorage.setItem(previousThemeKey, currentTheme);
            sessionStorage.setItem(previousThemeKey, currentTheme);
        }
    }
    
    document.documentElement.setAttribute('data-theme', theme);
    
    // Only update localStorage if not garden theme or if forced
    if (theme !== 'garden' || force) {
        localStorage.setItem(themeKey, theme);
        sessionStorage.setItem(themeKey, theme);
    }
    
    // Update theme controller checkboxes and visibility
    const themeControllers = document.querySelectorAll('.theme-controller');
    const themeSwitcher = document.querySelector('.theme-switcher');
    
    themeControllers.forEach(controller => {
        controller.checked = theme === 'dark';
        controller.disabled = theme === 'garden';
    });

    // Toggle theme switcher disabled state
    if (themeSwitcher) {
        if (theme === 'garden') {
            themeSwitcher.classList.add('disabled');
        } else {
            themeSwitcher.classList.remove('disabled');
        }
    }
}

// Theme toggle event handler
function handleThemeToggle(e) {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    if (currentTheme === 'garden') {
        return; // Don't allow theme toggle in garden mode
    }
    const newTheme = e.target.checked ? 'dark' : 'light';
    setTheme(newTheme);
}

// Initialize theme from localStorage or sessionStorage
function initializeTheme() {
    // Check sessionStorage first for navigation consistency
    const sessionTheme = sessionStorage.getItem(themeKey);
    const savedTheme = sessionTheme || localStorage.getItem(themeKey) || defaultTheme;
    
    // Set theme without triggering storage events
    document.documentElement.setAttribute('data-theme', savedTheme);
    
    // Update controllers
    const themeControllers = document.querySelectorAll('.theme-controller');
    themeControllers.forEach(controller => {
        controller.checked = savedTheme === 'dark';
        controller.disabled = savedTheme === 'garden';
    });

    // Update theme switcher state
    const themeSwitcher = document.querySelector('.theme-switcher');
    if (themeSwitcher) {
        if (savedTheme === 'garden') {
            themeSwitcher.classList.add('disabled');
        } else {
            themeSwitcher.classList.remove('disabled');
        }
    }

    return savedTheme;
}

// Function to restore previous theme
function restorePreviousTheme() {
    const previousTheme = localStorage.getItem(previousThemeKey) || sessionStorage.getItem(previousThemeKey) || defaultTheme;
    
    if (previousTheme && previousTheme !== 'garden') {
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
        controller.checked = currentTheme === 'dark';
        controller.addEventListener('change', handleThemeToggle);
    });

    // Handle page visibility changes
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            // When page becomes visible, ensure theme is consistent
            const sessionTheme = sessionStorage.getItem(themeKey);
            if (sessionTheme) {
                setTheme(sessionTheme);
            }
        }
    });

    // Handle storage events for cross-tab consistency
    window.addEventListener('storage', function(e) {
        if (e.key === themeKey) {
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
    defaultTheme
};

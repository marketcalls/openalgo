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
        }
    }
    
    document.documentElement.setAttribute('data-theme', theme);
    
    // Only update localStorage if not garden theme or if forced
    if (theme !== 'garden' || force) {
        localStorage.setItem(themeKey, theme);
    }
    
    // Update theme controller checkboxes and visibility
    const themeControllers = document.querySelectorAll('.theme-controller');
    const themeSwitcher = document.querySelector('.theme-switcher');
    
    themeControllers.forEach(controller => {
        controller.checked = theme === 'dark';
        // Enable/disable the controller based on theme
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
    const newTheme = e.target.checked ? 'dark' : 'light';
    setTheme(newTheme);
}

// Initialize theme from localStorage
function initializeTheme() {
    const savedTheme = localStorage.getItem(themeKey) || defaultTheme;
    setTheme(savedTheme);
    return savedTheme;
}

// Function to restore previous theme
function restorePreviousTheme() {
    const previousTheme = localStorage.getItem(previousThemeKey);
    if (previousTheme && previousTheme !== 'garden') {
        setTheme(previousTheme, true);
        // Clear the stored previous theme after restoration
        localStorage.removeItem(previousThemeKey);
        
        // Ensure the theme persists by updating localStorage
        localStorage.setItem(themeKey, previousTheme);
        
        // Update theme controllers immediately
        const themeControllers = document.querySelectorAll('.theme-controller');
        themeControllers.forEach(controller => {
            controller.checked = previousTheme === 'dark';
            controller.disabled = false;
        });
    } else {
        setTheme(defaultTheme, true);
    }
}

// Initialize theme immediately to prevent flash
(function() {
    const savedTheme = localStorage.getItem(themeKey);
    if (savedTheme) {
        document.documentElement.setAttribute('data-theme', savedTheme);
        // Set initial controller state
        const themeControllers = document.querySelectorAll('.theme-controller');
        themeControllers.forEach(controller => {
            controller.checked = savedTheme === 'dark';
        });
    }
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
});

// Export functions for use in mode-toggle.js
window.themeManager = {
    setTheme,
    restorePreviousTheme,
    defaultTheme
};

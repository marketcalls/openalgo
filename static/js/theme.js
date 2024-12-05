// Theme management
const themeKey = 'theme';
const defaultTheme = 'light';
const themes = ['light', 'dark'];

// Set theme and persist to localStorage
function setTheme(theme) {
    if (!themes.includes(theme)) {
        theme = defaultTheme;
    }
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(themeKey, theme);
    
    // Update theme controller checkboxes
    const themeControllers = document.querySelectorAll('.theme-controller');
    themeControllers.forEach(controller => {
        controller.checked = theme === 'dark';
    });
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

// Initialize theme immediately to prevent flash
(function() {
    const savedTheme = localStorage.getItem(themeKey);
    if (savedTheme) {
        document.documentElement.setAttribute('data-theme', savedTheme);
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

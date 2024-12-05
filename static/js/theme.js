// Theme management
const themeKey = 'theme';
const previousThemeKey = 'previousTheme';
const defaultTheme = 'light';
const themes = ['light', 'dark', 'garden'];

// Set theme and persist to localStorage
function setTheme(theme, force = false) {
    console.log(`[Theme] Setting theme to: ${theme}, force: ${force}`);
    console.log(`[Theme] Current theme before change: ${document.documentElement.getAttribute('data-theme')}`);

    if (!themes.includes(theme)) {
        console.log(`[Theme] Invalid theme: ${theme}, using default: ${defaultTheme}`);
        theme = defaultTheme;
    }
    
    // Store current theme before changing to garden
    if (!force && theme === 'garden') {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        console.log(`[Theme] Storing current theme before garden: ${currentTheme}`);
        if (currentTheme !== 'garden') {
            localStorage.setItem(previousThemeKey, currentTheme);
            sessionStorage.setItem(previousThemeKey, currentTheme);
            console.log(`[Theme] Stored previous theme: ${currentTheme}`);
        }
    }
    
    document.documentElement.setAttribute('data-theme', theme);
    console.log(`[Theme] Theme attribute set to: ${document.documentElement.getAttribute('data-theme')}`);
    
    // Only update localStorage if not garden theme or if forced
    if (theme !== 'garden' || force) {
        localStorage.setItem(themeKey, theme);
        sessionStorage.setItem(themeKey, theme);
        console.log(`[Theme] Theme stored in storage: ${theme}`);
    }
    
    // Update theme controller checkboxes and visibility
    const themeControllers = document.querySelectorAll('.theme-controller');
    const themeSwitcher = document.querySelector('.theme-switcher');
    
    console.log(`[Theme] Found ${themeControllers.length} theme controllers`);
    themeControllers.forEach((controller, index) => {
        controller.checked = theme === 'dark';
        controller.disabled = theme === 'garden';
        console.log(`[Theme] Controller ${index}: checked=${controller.checked}, disabled=${controller.disabled}`);
    });

    // Toggle theme switcher disabled state
    if (themeSwitcher) {
        if (theme === 'garden') {
            themeSwitcher.classList.add('disabled');
            console.log('[Theme] Theme switcher disabled');
        } else {
            themeSwitcher.classList.remove('disabled');
            console.log('[Theme] Theme switcher enabled');
        }
    }

    // Update mode badge if in garden theme
    const modeBadge = document.getElementById('mode-badge');
    if (modeBadge) {
        console.log(`[Theme] Updating mode badge for theme: ${theme}`);
        if (theme === 'garden') {
            modeBadge.textContent = 'Analyze Mode';
            modeBadge.classList.remove('badge-success');
            modeBadge.classList.add('badge-warning');
            console.log('[Theme] Mode badge set to Analyze Mode');
        } else {
            // Don't update badge text here, let mode-toggle.js handle it
            modeBadge.classList.remove('badge-warning');
            modeBadge.classList.add('badge-success');
            console.log('[Theme] Mode badge classes updated for Live Mode');
        }
    } else {
        console.log('[Theme] Mode badge element not found');
    }
}

// Theme toggle event handler
function handleThemeToggle(e) {
    console.log(`[Theme] Theme toggle triggered, checked: ${e.target.checked}`);
    const newTheme = e.target.checked ? 'dark' : 'light';
    setTheme(newTheme);
}

// Initialize theme from localStorage or sessionStorage
function initializeTheme() {
    console.log('[Theme] Initializing theme');
    // Check sessionStorage first for navigation consistency
    const sessionTheme = sessionStorage.getItem(themeKey);
    const savedTheme = sessionTheme || localStorage.getItem(themeKey) || defaultTheme;
    console.log(`[Theme] Retrieved theme - session: ${sessionTheme}, local: ${localStorage.getItem(themeKey)}, using: ${savedTheme}`);
    
    // Set theme without triggering storage events
    document.documentElement.setAttribute('data-theme', savedTheme);
    console.log(`[Theme] Initial theme attribute set to: ${savedTheme}`);
    
    // Update controllers
    const themeControllers = document.querySelectorAll('.theme-controller');
    console.log(`[Theme] Found ${themeControllers.length} theme controllers during initialization`);
    themeControllers.forEach((controller, index) => {
        controller.checked = savedTheme === 'dark';
        controller.disabled = savedTheme === 'garden';
        console.log(`[Theme] Initialized controller ${index}: checked=${controller.checked}, disabled=${controller.disabled}`);
    });

    // Update theme switcher state
    const themeSwitcher = document.querySelector('.theme-switcher');
    if (themeSwitcher) {
        if (savedTheme === 'garden') {
            themeSwitcher.classList.add('disabled');
            console.log('[Theme] Theme switcher initialized as disabled');
        } else {
            themeSwitcher.classList.remove('disabled');
            console.log('[Theme] Theme switcher initialized as enabled');
        }
    }

    // Update mode badge classes only, let mode-toggle.js handle the text
    const modeBadge = document.getElementById('mode-badge');
    if (modeBadge) {
        console.log(`[Theme] Initializing mode badge for theme: ${savedTheme}`);
        if (savedTheme === 'garden') {
            modeBadge.classList.remove('badge-success');
            modeBadge.classList.add('badge-warning');
            console.log('[Theme] Mode badge classes set for Analyze Mode');
        } else {
            modeBadge.classList.remove('badge-warning');
            modeBadge.classList.add('badge-success');
            console.log('[Theme] Mode badge classes set for Live Mode');
        }
    } else {
        console.log('[Theme] Mode badge element not found during initialization');
    }

    return savedTheme;
}

// Function to restore previous theme
function restorePreviousTheme() {
    console.log('[Theme] Restoring previous theme');
    const previousTheme = localStorage.getItem(previousThemeKey) || sessionStorage.getItem(previousThemeKey) || defaultTheme;
    console.log(`[Theme] Previous theme found: ${previousTheme}`);
    
    if (previousTheme && previousTheme !== 'garden') {
        setTheme(previousTheme, true);
        // Clear the stored previous theme after restoration
        localStorage.removeItem(previousThemeKey);
        sessionStorage.removeItem(previousThemeKey);
        console.log('[Theme] Previous theme restored and cleared from storage');
    } else {
        setTheme(defaultTheme, true);
        console.log(`[Theme] No valid previous theme, restored to default: ${defaultTheme}`);
    }
}

// Initialize theme immediately to prevent flash
(function() {
    console.log('[Theme] Immediate theme initialization');
    const savedTheme = localStorage.getItem(themeKey) || sessionStorage.getItem(themeKey) || defaultTheme;
    document.documentElement.setAttribute('data-theme', savedTheme);
    console.log(`[Theme] Initial theme set to: ${savedTheme}`);
})();

// Add event listeners when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    console.log('[Theme] DOM Content Loaded');
    // Initialize theme
    const currentTheme = initializeTheme();
    console.log(`[Theme] Theme initialized to: ${currentTheme}`);
    
    // Set initial state of theme toggles and add event listeners
    const themeControllers = document.querySelectorAll('.theme-controller');
    console.log(`[Theme] Setting up ${themeControllers.length} theme controllers`);
    themeControllers.forEach((controller, index) => {
        controller.checked = currentTheme === 'dark';
        controller.addEventListener('change', handleThemeToggle);
        console.log(`[Theme] Controller ${index} setup: checked=${controller.checked}`);
    });

    // Handle page visibility changes
    document.addEventListener('visibilitychange', function() {
        console.log(`[Theme] Visibility changed: ${document.hidden ? 'hidden' : 'visible'}`);
        if (!document.hidden) {
            // When page becomes visible, ensure theme is consistent
            const sessionTheme = sessionStorage.getItem(themeKey);
            console.log(`[Theme] Retrieved theme from session: ${sessionTheme}`);
            if (sessionTheme) {
                setTheme(sessionTheme, true);
            }
        }
    });

    // Handle storage events for cross-tab consistency
    window.addEventListener('storage', function(e) {
        console.log(`[Theme] Storage event: key=${e.key}, newValue=${e.newValue}`);
        if (e.key === themeKey) {
            const newTheme = e.newValue || defaultTheme;
            setTheme(newTheme, true);
        }
    });
});

// Export functions for use in mode-toggle.js
window.themeManager = {
    setTheme,
    restorePreviousTheme,
    initializeTheme,
    defaultTheme
};

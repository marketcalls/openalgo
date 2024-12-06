// Mode toggle functionality
document.addEventListener('DOMContentLoaded', function() {
    const modeToggle = document.querySelector('.mode-controller');
    const modeBadge = document.getElementById('mode-badge');
    
    if (!modeToggle || !modeBadge) {
        console.error('[Mode] Required elements not found');
        return;
    }

    // Set initial badge text to prevent flash of empty content
    modeBadge.textContent = 'Live Mode';
    modeBadge.classList.add('badge-success');

    function updateBadge(isAnalyzeMode) {
        if (isAnalyzeMode) {
            // Store current theme before switching to garden
            const currentTheme = document.documentElement.getAttribute('data-theme');
            if (currentTheme !== 'garden') {
                localStorage.setItem('previousTheme', currentTheme);
                sessionStorage.setItem('previousTheme', currentTheme);
            }
            
            // Set garden theme when switching to analyze mode
            window.themeManager.setTheme('garden');
        } else {
            modeBadge.textContent = 'Live Mode';
            modeBadge.classList.remove('badge-warning');
            modeBadge.classList.add('badge-success');
            
            // Only restore theme if we're switching from analyze mode
            const currentTheme = document.documentElement.getAttribute('data-theme');
            if (currentTheme === 'garden') {
                const previousTheme = localStorage.getItem('previousTheme') || sessionStorage.getItem('previousTheme') || 'light';
                window.themeManager.setTheme(previousTheme, true);
            }
            
            // Clear stored previous theme
            localStorage.removeItem('previousTheme');
            sessionStorage.removeItem('previousTheme');
            
            // Re-enable theme controllers
            const themeControllers = document.querySelectorAll('.theme-controller');
            themeControllers.forEach(controller => {
                const currentTheme = document.documentElement.getAttribute('data-theme');
                controller.checked = currentTheme === 'dark';
                controller.disabled = false;
            });
            
            // Remove disabled class from theme switcher
            const themeSwitcher = document.querySelector('.theme-switcher');
            if (themeSwitcher) {
                themeSwitcher.classList.remove('disabled');
            }
        }
    }

    // Initialize mode from server
    fetch('/settings/analyze-mode')
        .then(response => response.json())
        .then(data => {
            modeToggle.checked = data.analyze_mode;
            
            if (data.analyze_mode) {
                // If in analyze mode, ensure we store the current theme before switching
                const currentTheme = document.documentElement.getAttribute('data-theme');
                if (currentTheme !== 'garden') {
                    localStorage.setItem('previousTheme', currentTheme);
                    sessionStorage.setItem('previousTheme', currentTheme);
                }
                window.themeManager.setTheme('garden');
            } else {
                // Just update the badge, don't change theme
                updateBadge(false);
            }
        })
        .catch(error => {
            console.error('[Mode] Error fetching analyze mode:', error);
            // Ensure badge shows Live Mode if fetch fails
            updateBadge(false);
        });

    // Handle mode toggle
    modeToggle.addEventListener('change', function(e) {
        const mode = e.target.checked ? 1 : 0;
        
        fetch(`/settings/analyze-mode/${mode}`, {
            method: 'POST',
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateBadge(data.analyze_mode);
                showToast(data.message, 'success');
                
                // Store current state in sessionStorage before reload
                sessionStorage.setItem('analyzeMode', data.analyze_mode);
                
                // Reload page to ensure all components update
                setTimeout(() => window.location.reload(), 1000);
            }
        })
        .catch(error => {
            console.error('[Mode] Error updating mode:', error);
            showToast('Failed to update mode', 'error');
            // Reset toggle state
            e.target.checked = !e.target.checked;
        });
    });

    // Handle page visibility changes
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            // When page becomes visible, check and restore theme state
            const analyzeMode = sessionStorage.getItem('analyzeMode') === 'true';
            if (analyzeMode) {
                const previousTheme = localStorage.getItem('previousTheme') || sessionStorage.getItem('previousTheme');
                if (previousTheme) {
                    window.themeManager.setTheme('garden');
                }
            }
        }
    });

    // Handle storage events for cross-tab consistency
    window.addEventListener('storage', function(e) {
        if (e.key === 'analyzeMode') {
            const isAnalyzeMode = e.newValue === 'true';
            modeToggle.checked = isAnalyzeMode;
            updateBadge(isAnalyzeMode);
        }
    });
});

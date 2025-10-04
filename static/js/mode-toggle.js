// Mode toggle functionality
document.addEventListener('DOMContentLoaded', function() {
    const modeToggle = document.querySelector('.mode-controller');
    const modeBadge = document.getElementById('mode-badge');
    
    if (!modeToggle || !modeBadge) {
        console.error('[Mode] Required elements not found');
        return;
    }

    // State management variables
    let isInitialized = false;
    let currentMode = false; // false = Live Mode, true = Analyze Mode

    function updateBadge(isAnalyzeMode, skipThemeChange = false) {
        // Prevent unnecessary updates if mode hasn't actually changed
        if (isInitialized && currentMode === isAnalyzeMode) {
            return;
        }

        currentMode = isAnalyzeMode;

        // Only update toggle state if it's different to prevent icon flip
        if (modeToggle.checked !== isAnalyzeMode) {
            modeToggle.checked = isAnalyzeMode;
        }

        // Clear all badge classes first
        modeBadge.classList.remove('badge-success', 'badge-warning', 'badge-neutral');

        // Hide theme switcher BEFORE theme change to prevent icon flip
        const themeSwitcher = document.querySelector('.theme-switcher');
        if (!skipThemeChange && themeSwitcher) {
            themeSwitcher.style.transition = 'none';
            themeSwitcher.style.opacity = '0';
        }

        if (isAnalyzeMode) {
            modeBadge.textContent = 'Analyze Mode';
            modeBadge.classList.add('badge-warning');
            modeBadge.style.opacity = '1';

            if (!skipThemeChange && window.themeManager) {
                // Store current theme before switching to dracula (analyze theme)
                const currentTheme = document.documentElement.getAttribute('data-theme');
                if (currentTheme !== 'dracula') {
                    localStorage.setItem('previousTheme', currentTheme);
                    sessionStorage.setItem('previousTheme', currentTheme);
                }
                window.themeManager.setTheme('dracula');
            }
        } else {
            modeBadge.textContent = 'Live Mode';
            modeBadge.classList.add('badge-success');
            modeBadge.style.opacity = '1';

            if (!skipThemeChange && window.themeManager) {
                // Only restore theme if we're switching from dracula (analyze) mode
                const currentTheme = document.documentElement.getAttribute('data-theme');
                if (currentTheme === 'dracula') {
                    window.themeManager.restorePreviousTheme();
                }
            }
        }

        // Show theme switcher after theme change is complete
        if (!skipThemeChange && themeSwitcher) {
            setTimeout(() => {
                themeSwitcher.style.transition = '';
                themeSwitcher.style.opacity = '1';
            }, 10);
        }
        
        // Update session storage
        sessionStorage.setItem('analyzeMode', isAnalyzeMode.toString());
        localStorage.setItem('analyzeMode', isAnalyzeMode.toString()); // For cross-tab sync
    }

    // Initialize mode from server (authoritative source)
    function initializeFromServer() {
        fetch('/settings/analyze-mode')
            .then(response => response.json())
            .then(data => {
                const serverMode = Boolean(data.analyze_mode);
                updateBadge(serverMode);
                isInitialized = true;
                console.log('[Mode] Initialized from server:', serverMode ? 'Analyze Mode' : 'Live Mode');
            })
            .catch(error => {
                console.error('[Mode] Error fetching analyze mode:', error);
                // Fallback to Live Mode if server fetch fails
                updateBadge(false);
                isInitialized = true;
            });
    }
    
    // Initialize immediately
    initializeFromServer();

    // Handle mode toggle
    modeToggle.addEventListener('change', function(e) {
        // Prevent multiple rapid clicks
        if (!isInitialized) {
            e.target.checked = currentMode;
            return;
        }
        
        const newMode = e.target.checked ? 1 : 0;
        const newModeBoolean = Boolean(newMode);
        
        // Optimistically update UI
        updateBadge(newModeBoolean);
        
        fetch(`/settings/analyze-mode/${newMode}`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken()
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Ensure UI matches server response
                updateBadge(Boolean(data.analyze_mode));
                showToast(data.message, 'success');

                // Show disclaimer toast when enabling analyzer mode
                if (newModeBoolean === true) {
                    setTimeout(() => {
                        showToast('⚠️ Analyzer (Sandbox) mode is for testing purposes only', 'warning', 20000);
                    }, 2000); // Slight delay to show after success toast
                }

                // Refresh current page content to reflect the mode change
                console.log('[Mode] Mode switched successfully, refreshing content');

                // Use the refreshCurrentPageContent function if available
                if (typeof refreshCurrentPageContent === 'function') {
                    setTimeout(() => {
                        refreshCurrentPageContent();
                    }, 500); // Small delay to ensure mode is properly set
                } else {
                    // Fallback: reload the page if refresh function is not available
                    setTimeout(() => {
                        window.location.reload();
                    }, 500);
                }
            } else {
                throw new Error(data.error || 'Unknown error');
            }
        })
        .catch(error => {
            console.error('[Mode] Error updating mode:', error);
            showToast('Failed to update mode', 'error');
            
            // Revert to previous state on error
            updateBadge(!newModeBoolean);
        });
    });

    // Handle page visibility changes - re-sync with server when page becomes visible
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden && isInitialized) {
            // Re-sync with server when page becomes visible
            console.log('[Mode] Page visible, re-syncing with server');
            initializeFromServer();
        }
    });

    // Handle storage events for cross-tab consistency  
    window.addEventListener('storage', function(e) {
        if (e.key === 'analyzeMode' && isInitialized) {
            const isAnalyzeMode = e.newValue === 'true';
            console.log('[Mode] Storage event received, updating to:', isAnalyzeMode ? 'Analyze Mode' : 'Live Mode');
            updateBadge(isAnalyzeMode, true); // Skip theme change for storage events
        }
    });
});

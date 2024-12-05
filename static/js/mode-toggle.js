// Mode toggle functionality
document.addEventListener('DOMContentLoaded', function() {
    console.log('[Mode] DOM Content Loaded');
    const modeToggle = document.querySelector('.mode-controller');
    const modeBadge = document.getElementById('mode-badge');
    
    if (!modeToggle || !modeBadge) {
        console.log('[Mode] Required elements not found:', {
            modeToggle: !!modeToggle,
            modeBadge: !!modeBadge
        });
        return;
    }

    console.log('[Mode] Setting initial badge state');
    // Set initial badge text to prevent flash of empty content
    modeBadge.textContent = 'Live Mode';
    modeBadge.classList.add('badge-success');

    function updateBadge(isAnalyzeMode) {
        console.log(`[Mode] Updating badge for analyze mode: ${isAnalyzeMode}`);
        
        if (isAnalyzeMode) {
            console.log('[Mode] Switching to Analyze Mode');
            // Store current theme before switching to garden
            const currentTheme = document.documentElement.getAttribute('data-theme');
            console.log(`[Mode] Current theme before garden: ${currentTheme}`);
            
            if (currentTheme !== 'garden') {
                localStorage.setItem('previousTheme', currentTheme);
                sessionStorage.setItem('previousTheme', currentTheme);
                console.log(`[Mode] Stored previous theme: ${currentTheme}`);
            }
            
            // Set garden theme when switching to analyze mode
            console.log('[Mode] Setting garden theme');
            window.themeManager.setTheme('garden');
        } else {
            console.log('[Mode] Setting Live Mode badge');
            modeBadge.textContent = 'Live Mode';
            modeBadge.classList.remove('badge-warning');
            modeBadge.classList.add('badge-success');
            
            // Only restore theme if we're switching from analyze mode
            const currentTheme = document.documentElement.getAttribute('data-theme');
            if (currentTheme === 'garden') {
                console.log('[Mode] Switching from analyze mode, restoring theme');
                const previousTheme = localStorage.getItem('previousTheme') || sessionStorage.getItem('previousTheme') || 'light';
                console.log(`[Mode] Restoring previous theme: ${previousTheme}`);
                window.themeManager.setTheme(previousTheme, true);
            } else {
                console.log('[Mode] Already in live mode, keeping current theme:', currentTheme);
            }
            
            // Clear stored previous theme
            localStorage.removeItem('previousTheme');
            sessionStorage.removeItem('previousTheme');
            console.log('[Mode] Cleared previous theme from storage');
            
            // Re-enable theme controllers
            const themeControllers = document.querySelectorAll('.theme-controller');
            console.log(`[Mode] Re-enabling ${themeControllers.length} theme controllers`);
            themeControllers.forEach((controller, index) => {
                const currentTheme = document.documentElement.getAttribute('data-theme');
                controller.checked = currentTheme === 'dark';
                controller.disabled = false;
                console.log(`[Mode] Controller ${index} updated: checked=${controller.checked}, disabled=false`);
            });
            
            // Remove disabled class from theme switcher
            const themeSwitcher = document.querySelector('.theme-switcher');
            if (themeSwitcher) {
                themeSwitcher.classList.remove('disabled');
                console.log('[Mode] Theme switcher enabled');
            }
        }
    }

    // Initialize mode from server
    console.log('[Mode] Fetching initial mode from server');
    fetch('/settings/analyze-mode')
        .then(response => {
            console.log('[Mode] Server response received:', response.status);
            return response.json();
        })
        .then(data => {
            console.log('[Mode] Server data:', data);
            modeToggle.checked = data.analyze_mode;
            console.log(`[Mode] Toggle checked state set to: ${data.analyze_mode}`);
            
            if (data.analyze_mode) {
                console.log('[Mode] Initializing analyze mode');
                // If in analyze mode, ensure we store the current theme before switching
                const currentTheme = document.documentElement.getAttribute('data-theme');
                console.log(`[Mode] Current theme: ${currentTheme}`);
                
                if (currentTheme !== 'garden') {
                    localStorage.setItem('previousTheme', currentTheme);
                    sessionStorage.setItem('previousTheme', currentTheme);
                    console.log(`[Mode] Stored initial theme: ${currentTheme}`);
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
        console.log(`[Mode] Toggle changed: ${e.target.checked}`);
        const mode = e.target.checked ? 1 : 0;
        
        console.log(`[Mode] Sending mode update to server: ${mode}`);
        fetch(`/settings/analyze-mode/${mode}`, {
            method: 'POST',
        })
        .then(response => {
            console.log('[Mode] Server response received:', response.status);
            return response.json();
        })
        .then(data => {
            console.log('[Mode] Server update response:', data);
            if (data.success) {
                updateBadge(data.analyze_mode);
                showToast(data.message, 'success');
                
                // Store current state in sessionStorage before reload
                sessionStorage.setItem('analyzeMode', data.analyze_mode);
                console.log(`[Mode] Stored analyze mode in session: ${data.analyze_mode}`);
                
                // Reload page to ensure all components update
                console.log('[Mode] Reloading page in 1 second');
                setTimeout(() => window.location.reload(), 1000);
            }
        })
        .catch(error => {
            console.error('[Mode] Error updating mode:', error);
            showToast('Failed to update mode', 'error');
            // Reset toggle state
            e.target.checked = !e.target.checked;
            console.log(`[Mode] Reset toggle to: ${e.target.checked}`);
        });
    });

    // Handle page visibility changes
    document.addEventListener('visibilitychange', function() {
        console.log(`[Mode] Visibility changed: ${document.hidden ? 'hidden' : 'visible'}`);
        if (!document.hidden) {
            // When page becomes visible, check and restore theme state
            const analyzeMode = sessionStorage.getItem('analyzeMode') === 'true';
            console.log(`[Mode] Retrieved analyze mode from session: ${analyzeMode}`);
            
            if (analyzeMode) {
                const previousTheme = localStorage.getItem('previousTheme') || sessionStorage.getItem('previousTheme');
                console.log(`[Mode] Previous theme found: ${previousTheme}`);
                
                if (previousTheme) {
                    console.log('[Mode] Setting garden theme on visibility change');
                    window.themeManager.setTheme('garden');
                }
            }
        }
    });

    // Handle storage events for cross-tab consistency
    window.addEventListener('storage', function(e) {
        console.log(`[Mode] Storage event: key=${e.key}, newValue=${e.newValue}`);
        if (e.key === 'analyzeMode') {
            const isAnalyzeMode = e.newValue === 'true';
            console.log(`[Mode] Analyze mode changed in another tab: ${isAnalyzeMode}`);
            modeToggle.checked = isAnalyzeMode;
            updateBadge(isAnalyzeMode);
        }
    });
});

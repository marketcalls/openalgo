document.addEventListener('DOMContentLoaded', function() {
    const modeToggle = document.querySelector('.mode-controller');
    const modeBadge = document.getElementById('mode-badge');
    if (!modeToggle || !modeBadge) return;

    function updateBadge(isAnalyzeMode) {
        if (isAnalyzeMode) {
            modeBadge.textContent = 'Analyze Mode';
            modeBadge.classList.remove('badge-success');
            modeBadge.classList.add('badge-warning');
            // Set garden theme when switching to analyze mode
            window.themeManager.setTheme('garden');
        } else {
            modeBadge.textContent = 'Live Mode';
            modeBadge.classList.remove('badge-warning');
            modeBadge.classList.add('badge-success');
            // Force restore previous theme when switching back to live mode
            window.themeManager.restorePreviousTheme();
            
            // Re-enable theme controllers
            const themeControllers = document.querySelectorAll('.theme-controller');
            themeControllers.forEach(controller => {
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
            updateBadge(data.analyze_mode);
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
                // Reload page to ensure all components update
                setTimeout(() => window.location.reload(), 1000);
            }
        });
    });
});

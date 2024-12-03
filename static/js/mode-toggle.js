document.addEventListener('DOMContentLoaded', function() {
    const modeToggle = document.querySelector('.mode-controller');
    if (!modeToggle) return;

    // Initialize mode from server
    fetch('/settings/analyze-mode')
        .then(response => response.json())
        .then(data => {
            modeToggle.checked = data.analyze_mode;
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
                showToast(data.message, 'success');
                // Reload page to ensure all components update
                setTimeout(() => window.location.reload(), 1000);
            }
        });
    });
});

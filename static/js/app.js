document.addEventListener('DOMContentLoaded', function() {
    const regenerateKeyBtn = document.getElementById('regenerateKey');
    if (regenerateKeyBtn) {
        regenerateKeyBtn.addEventListener('click', function() {
            regenerateApiKey();
        });
    }
});

function regenerateApiKey() {
    // Example user ID - replace with actual logic to retrieve the user ID, if necessary
    const userInfo = document.getElementById('userInfo');
    if (!userInfo) return;
    
    const userId = userInfo.getAttribute('data-login-username');

    // Use fetchWithCSRF if available, otherwise fallback to regular fetch with CSRF header
    const csrfToken = typeof getCSRFToken === 'function' ? getCSRFToken() : '';
    
    fetch('/apikey', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ user_id: userId })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    })
    .then(data => {
        const apiKeyDisplay = document.getElementById('apiKeyDisplay');
        if (apiKeyDisplay) {
            apiKeyDisplay.textContent = data.api_key;
        }
    })
    .catch((error) => {
        console.error('Error:', error);
    });
}

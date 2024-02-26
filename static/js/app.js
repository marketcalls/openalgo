document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('regenerateKey').addEventListener('click', function() {
        regenerateApiKey();
    });
});

function regenerateApiKey() {
    // Example user ID - replace with actual logic to retrieve the user ID, if necessary
    const userId = document.getElementById('userInfo').getAttribute('data-login-username');

    fetch('/apikey', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
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
        document.getElementById('apiKeyDisplay').textContent = data.api_key;
    })
    .catch((error) => {
        console.error('Error:', error);
    });
}

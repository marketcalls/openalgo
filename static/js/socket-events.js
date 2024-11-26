document.addEventListener('DOMContentLoaded', function() {
    var socket = io();
    var alertSound = document.getElementById('alert-sound');

    socket.on('connect', function() {
        console.log('Connected to WebSocket server');
    });

    socket.on('disconnect', function() {
        console.log('Disconnected from WebSocket server');
    });

    socket.on('order_notification', function(data) {
        // Play alert sound
        if (alertSound) {
            alertSound.play().catch(function(error) {
                console.log("Error playing sound:", error);
            });
        }

        // Determine notification type based on status
        let type = 'info';
        if (data.status && typeof data.status === 'string') {
            if (data.status.toLowerCase().includes('success')) {
                type = 'success';
            } else if (data.status.toLowerCase().includes('error') || data.status.toLowerCase().includes('reject')) {
                type = 'error';
            } else if (data.status.toLowerCase().includes('pending')) {
                type = 'warning';
            }
        }

        // Create notification message
        let message = '';
        if (data.symbol) {
            message += `${data.symbol}: `;
        }
        if (data.status) {
            message += data.status;
        }
        if (data.message) {
            message += data.message;
        }

        // Show toast notification
        showToast(message, type);
    });

    // Helper function to create toast notifications
    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        
        // Set toast class based on type
        let alertClass = 'alert-info';
        switch(type) {
            case 'success':
                alertClass = 'alert-success';
                break;
            case 'error':
                alertClass = 'alert-error';
                break;
            case 'warning':
                alertClass = 'alert-warning';
                break;
        }
        
        toast.className = `alert ${alertClass} mb-2`;
        
        // Add appropriate icon based on type
        let icon = '';
        switch(type) {
            case 'success':
                icon = `<svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>`;
                break;
            case 'error':
                icon = `<svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>`;
                break;
            case 'warning':
                icon = `<svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>`;
                break;
            default:
                icon = `<svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>`;
        }
        
        toast.innerHTML = `
            ${icon}
            <span>${message}</span>
        `;
        
        // Add to toast container
        const container = document.getElementById('toast-container');
        if (container) {
            container.appendChild(toast);
            
            // Remove toast after 5 seconds
            setTimeout(() => {
                toast.classList.add('fade-out');
                setTimeout(() => {
                    toast.remove();
                }, 300);
            }, 5000);
        }
    }

    // Add CSS animation for fade out
    const style = document.createElement('style');
    style.textContent = `
        .fade-out {
            opacity: 0;
            transition: opacity 0.3s ease-out;
        }
        
        #toast-container {
            position: fixed;
            top: 1rem;
            right: 1rem;
            z-index: 1000;
            max-width: 24rem;
        }
        
        .alert {
            animation: slideIn 0.3s ease-out;
        }
        
        @keyframes slideIn {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
    `;
    document.head.appendChild(style);
});

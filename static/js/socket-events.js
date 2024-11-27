document.addEventListener('DOMContentLoaded', function() {
    var socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);
    var alertSound = document.getElementById('alert-sound');

    socket.on('connect', function() {
        console.log('Connected to WebSocket server');
    });

    socket.on('disconnect', function() {
        console.log('Disconnected from WebSocket server');
    });

    // Password change notification
    socket.on('password_change', function(data) {
        playAlertSound();
        showToast(data.message, 'info');
    });

    // Master contract download notification
    socket.on('master_contract_download', function(data) {
        playAlertSound();
        showToast(`Master Contract: ${data.message}`, 'info');
    });

    // Cancel order notification
    socket.on('cancel_order_event', function(data) {
        playAlertSound();
        showToast(`Cancel Order ID: ${data.orderid}`, 'warning');
    });

    // Modify order notification
    socket.on('modify_order_event', function(data) {
        playAlertSound();
        showToast(`ModifyOrder - Order ID: ${data.orderid}`, 'warning');
    });

    // Close position notification
    socket.on('close_position', function(data) {
        playAlertSound();
        showToast(`${data.message}`, 'info');
    });

    // Order placement notification
    socket.on('order_event', function(data) {
        playAlertSound();
        const type = data.action.toUpperCase() === 'BUY' ? 'success' : 'error';
        showToast(`${data.action.toUpperCase()} Order Placed for Symbol: ${data.symbol}, Order ID: ${data.orderid}`, type);
    });

    // Generic order notification handler
    socket.on('order_notification', function(data) {
        playAlertSound();
        
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

        showToast(message, type);
    });

    // Helper function to play alert sound
    function playAlertSound() {
        if (alertSound) {
            alertSound.play().catch(function(error) {
                console.log("Error playing sound:", error);
            });
        }
    }
});

// Functions for mobile menu toggle
function toggleMobileMenu() {
    var menu = document.getElementById('mobile-menu');
    menu.classList.remove('-translate-x-full');
    document.querySelector('button[onclick="toggleMobileMenu()"]').style.display = 'none';
}

function closeMobileMenu() {
    var menu = document.getElementById('mobile-menu');
    menu.classList.add('-translate-x-full');
    document.querySelector('button[onclick="toggleMobileMenu()"]').style.display = 'block';
}

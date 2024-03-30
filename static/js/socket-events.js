document.addEventListener('DOMContentLoaded', function() {
    var socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);
    var alertSound = document.getElementById('alert-sound');

    socket.on('password_change', function(data) {
        showFlashMessage('bg-blue-500', `Password Change: ${data.message}`);
    });

    socket.on('master_contract_download', function(data) {
        showFlashMessage('bg-blue-500', `Master Contract: ${data.message}`);
    });

    socket.on('cancel_order_event', function(data) {
        showFlashMessage('bg-black-500', `Cancel Order ID : ${data.orderid}`);
    });

    socket.on('modify_order_event', function(data) {
        showFlashMessage('bg-black-500', `ModifyOrder - Order ID : ${data.orderid}`);
    });

    socket.on('close_position', function(data) {
        showFlashMessage('bg-blue-500', `Message: ${data.message}`);
    });

    socket.on('order_event', function(data) {
        var bgColorClass = data.action.toUpperCase() === 'BUY' ? 'bg-green-500' : 'bg-red-500';
        showFlashMessage(bgColorClass, `${data.action.toUpperCase()} Order Placed for Symbol: ${data.symbol}, Order ID: ${data.orderid}`);
    });

    function showFlashMessage(bgColorClass, message) {
        var flashMessage = document.createElement('div');
        flashMessage.className = `fixed bottom-3 right-3 md:bottom-5 md:right-5 ${bgColorClass} text-white py-2 px-4 rounded-lg text-sm`;
        flashMessage.textContent = message;
        document.body.appendChild(flashMessage);
        alertSound.play();
        setTimeout(function() {
            document.body.removeChild(flashMessage);
        }, 5000);
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

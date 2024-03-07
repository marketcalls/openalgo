// Functions for mobile menu toggle (existing functionality)
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

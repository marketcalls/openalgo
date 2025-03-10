/**
 * OpenAlgo Main JavaScript
 * Contains essential client-side functionality for the application
 */

// Wait for DOM to be fully loaded
document.addEventListener('DOMContentLoaded', () => {
    // Initialize theme handling
    initTheme();
    
    // Initialize password forms
    initPasswordForms();
    
    // Initialize toast notifications
    initToasts();
});

/**
 * Theme initialization and management
 * Supports light/dark mode toggling with system preference detection
 */
function initTheme() {
    const themeToggle = document.getElementById('theme-toggle');
    
    if (themeToggle) {
        // Check for saved theme preference or use system preference
        const savedTheme = localStorage.getItem('theme');
        const systemDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
        
        // Set initial theme
        if (savedTheme) {
            document.documentElement.setAttribute('data-theme', savedTheme);
        } else if (systemDarkMode) {
            document.documentElement.setAttribute('data-theme', 'dark');
        }
        
        // Toggle theme when button is clicked
        themeToggle.addEventListener('click', () => {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'light' ? 'dark' : 'light';
            
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
        });
    }
}

/**
 * Password form enhancements
 * Adds client-side validation and visual feedback
 */
function initPasswordForms() {
    // Find all password input fields
    const passwordInputs = document.querySelectorAll('input[type="password"]');
    
    passwordInputs.forEach(input => {
        // Toggle password visibility if there's a toggle button
        const toggleButton = input.parentElement.querySelector('.password-toggle');
        if (toggleButton) {
            toggleButton.addEventListener('click', () => {
                const type = input.getAttribute('type') === 'password' ? 'text' : 'password';
                input.setAttribute('type', type);
                
                // Update toggle button icon
                const icon = toggleButton.querySelector('svg');
                if (icon) {
                    if (type === 'password') {
                        icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />';
                    } else {
                        icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />';
                    }
                }
            });
        }
    });
}

/**
 * Initialize toast notifications system
 * For displaying non-intrusive messages to users
 */
function initToasts() {
    // Find all toast messages in the DOM
    const toasts = document.querySelectorAll('.toast');
    
    // Auto-dismiss toasts after a delay
    toasts.forEach(toast => {
        setTimeout(() => {
            toast.classList.add('toast-hide');
            
            // Remove from DOM after animation completes
            toast.addEventListener('transitionend', () => {
                toast.remove();
            });
        }, 5000);
        
        // Allow manual dismissal
        const closeBtn = toast.querySelector('.toast-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                toast.classList.add('toast-hide');
                
                // Remove from DOM after animation completes
                toast.addEventListener('transitionend', () => {
                    toast.remove();
                });
            });
        }
    });
}

/**
 * Create and display a toast notification
 * @param {string} message - The message to display
 * @param {string} type - The type of toast (success, error, info, warning)
 */
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    // Create toast content
    toast.innerHTML = `
        <div class="alert alert-${type}">
            <span>${message}</span>
            <button class="toast-close btn btn-ghost btn-sm">×</button>
        </div>
    `;
    
    // Add to the DOM
    document.body.appendChild(toast);
    
    // Set up auto-dismiss
    setTimeout(() => {
        toast.classList.add('toast-hide');
        
        // Remove from DOM after animation completes
        toast.addEventListener('transitionend', () => {
            toast.remove();
        });
    }, 5000);
    
    // Allow manual dismissal
    const closeBtn = toast.querySelector('.toast-close');
    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            toast.classList.add('toast-hide');
            
            // Remove from DOM after animation completes
            toast.addEventListener('transitionend', () => {
                toast.remove();
            });
        });
    }
}

/**
 * HTMX extended functionality for custom behaviors
 * Enhances HTMX with additional features
 */
document.addEventListener('htmx:load', function() {
    // Add any custom HTMX extensions or event handlers here
    
    // Example: Flash message handling
    document.body.addEventListener('showMessage', function(e) {
        if (e.detail) {
            showToast(e.detail.message, e.detail.type || 'info');
        }
    });
});

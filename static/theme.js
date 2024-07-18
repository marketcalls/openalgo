document.addEventListener('DOMContentLoaded', () => {
    const themeController = document.querySelector('.theme-controller');

    // Load the stored theme from local storage
    const storedTheme = localStorage.getItem('theme');
    if (storedTheme) {
        document.documentElement.setAttribute('data-theme', storedTheme);
        themeController.checked = storedTheme === 'light';
    }

    themeController.addEventListener('change', (event) => {
        const theme = event.target.checked ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
    });
});

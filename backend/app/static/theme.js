(function (global) {
    'use strict';

    const STORAGE_KEY = 'kupujpl-theme';
    const THEME = 'ice';
    const THEME_COLOR = '#dbeafe';

    function updateMetaThemeColor() {
        document.querySelectorAll('meta[name="theme-color"]').forEach((el) => {
            el.setAttribute('content', THEME_COLOR);
        });
    }

    function applyTheme() {
        document.documentElement.dataset.theme = THEME;
        try {
            localStorage.setItem(STORAGE_KEY, THEME);
        } catch (_) { /* ignore */ }
        updateMetaThemeColor();
        document.documentElement.classList.remove('theme-matrix-active');
        document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: THEME } }));
    }

    function mountThemeSwitcher() {
        // Theme switcher removed — site is locked to ICE.
        document.querySelectorAll('[data-theme-switch-slot], .theme-switch-wrap').forEach((el) => {
            el.remove();
        });
        applyTheme();
    }

    global.KupujPLTheme = {
        getTheme: () => THEME,
        setTheme: applyTheme,
        bootTheme: applyTheme,
        mountThemeSwitcher,
        THEMES: [THEME],
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mountThemeSwitcher);
    } else {
        mountThemeSwitcher();
    }
    applyTheme();
})(typeof window !== 'undefined' ? window : globalThis);

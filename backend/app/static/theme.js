(function (global) {
    'use strict';

    const STORAGE_KEY = 'kupujpl-theme';
    const THEMES = ['night', 'ice', 'void', 'matrix'];

    const THEME_COLORS = {
        night: '#fcee09',
        ice: '#dbeafe',
        void: '#7c3aed',
        matrix: '#020804',
    };

    const FALLBACK_LABELS = {
        night: 'CP',
        ice: 'ICE',
        void: 'VOID',
        matrix: 'MX',
    };

    function tt(key, fallback) {
        if (global.I18n && typeof I18n.t === 'function') {
            const v = I18n.t(key);
            if (v && v !== key) return v;
        }
        return fallback;
    }

    function getTheme() {
        try {
            const saved = localStorage.getItem(STORAGE_KEY);
            if (THEMES.includes(saved)) return saved;
        } catch (_) { /* ignore */ }
        return 'night';
    }

    function updateMetaThemeColor(themeId) {
        const color = THEME_COLORS[themeId] || THEME_COLORS.night;
        document.querySelectorAll('meta[name="theme-color"]').forEach((el) => {
            el.setAttribute('content', color);
        });
    }

    function applyTheme(themeId, persist = true) {
        const id = THEMES.includes(themeId) ? themeId : 'night';
        document.documentElement.dataset.theme = id;
        if (persist) {
            try {
                localStorage.setItem(STORAGE_KEY, id);
            } catch (_) { /* ignore */ }
        }
        updateMetaThemeColor(id);
        document.querySelectorAll('.theme-switch .theme-btn').forEach((btn) => {
            const active = btn.dataset.theme === id;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: id } }));
    }

    function bootTheme() {
        applyTheme(getTheme(), false);
    }

    function refreshThemeLabels() {
        document.querySelectorAll('.theme-switch-label').forEach((el) => {
            el.textContent = tt('theme.label', 'Motyw:');
        });
        document.querySelectorAll('.theme-switch .theme-btn').forEach((btn) => {
            const id = btn.dataset.theme;
            if (!id) return;
            btn.textContent = tt('theme.' + id, FALLBACK_LABELS[id] || id);
            btn.title = tt('theme.' + id + '_title', btn.textContent);
        });
        document.querySelectorAll('.theme-switch').forEach((nav) => {
            nav.setAttribute('aria-label', tt('theme.aria', 'Zmień motyw strony'));
        });
    }

    function mountThemeSwitcher() {
        document.querySelectorAll('.header-inner').forEach((inner) => {
            if (inner.querySelector('.theme-switch-wrap')) return;

            let host = inner.querySelector('.header-actions');
            const authNav = inner.querySelector('#auth-nav');
            if (!host && authNav) {
                host = document.createElement('div');
                host.className = 'header-actions';
                inner.insertBefore(host, authNav);
                host.appendChild(authNav);
            }
            if (!host) host = inner;

            const wrap = document.createElement('div');
            wrap.className = 'theme-switch-wrap';

            const label = document.createElement('span');
            label.className = 'theme-switch-label';
            label.textContent = tt('theme.label', 'Motyw:');
            wrap.appendChild(label);

            const nav = document.createElement('nav');
            nav.className = 'theme-switch';
            nav.setAttribute('aria-label', tt('theme.aria', 'Zmień motyw strony'));

            THEMES.forEach((id) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'theme-btn';
                btn.dataset.theme = id;
                btn.textContent = tt('theme.' + id, FALLBACK_LABELS[id] || id);
                btn.title = tt('theme.' + id + '_title', btn.textContent);
                btn.addEventListener('click', () => applyTheme(id));
                nav.appendChild(btn);
            });
            wrap.appendChild(nav);

            const langSwitch = host.querySelector('.lang-switch');
            if (langSwitch) {
                langSwitch.insertAdjacentElement('afterend', wrap);
            } else if (host.classList.contains('header-actions')) {
                host.insertBefore(wrap, host.firstChild);
            } else if (authNav) {
                inner.insertBefore(wrap, authNav);
            } else {
                host.appendChild(wrap);
            }
        });

        refreshThemeLabels();
        applyTheme(getTheme(), false);
    }

    document.addEventListener('langchange', refreshThemeLabels);

    global.KupujPLTheme = {
        getTheme,
        setTheme: applyTheme,
        bootTheme,
        mountThemeSwitcher,
        THEMES,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mountThemeSwitcher);
    } else {
        mountThemeSwitcher();
    }
})(typeof window !== 'undefined' ? window : globalThis);

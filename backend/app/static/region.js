/**
 * Geo + region UX: shopping region PL|US.
 * Default PL mode: clear PLN (zł) only — no USD dual prices, no conversion banners.
 * US mode: optional approximate USD, with a short localized note.
 */
(function (global) {
    'use strict';

    const GEO_CACHE_KEY = 'kupujpl_geo_cc';
    const GEO_CACHE_AT = 'kupujpl_geo_at';
    const BANNER_DISMISS = 'kupujpl_region_banner_dismissed';
    const LANG_KEY = 'kupujpl_lang';
    const SHOPPING_REGION_KEY = 'kupujpl_shopping_region';
    const GEO_TTL_MS = 12 * 60 * 60 * 1000;
    const EN_COUNTRIES = {
        US: 1, CA: 1, GB: 1, AU: 1, NZ: 1, IE: 1,
    };

    let countryCode = null;
    let usdPerPln = null;
    let shoppingRegion = null; // 'pl' | 'us'
    let ready = false;
    const listeners = [];

    function apiBase() {
        const b = document.querySelector('base');
        const href = (b && b.getAttribute('href')) || '/games/';
        return String(href).replace(/\/?$/, '/') + 'api/';
    }

    function api(path) {
        return apiBase() + String(path || '').replace(/^\//, '');
    }

    function cachedCountry() {
        try {
            const at = Number(sessionStorage.getItem(GEO_CACHE_AT) || 0);
            if (Date.now() - at > GEO_TTL_MS) return null;
            return sessionStorage.getItem(GEO_CACHE_KEY) || null;
        } catch (_) {
            return null;
        }
    }

    function storeCountry(cc) {
        try {
            sessionStorage.setItem(GEO_CACHE_KEY, cc || '');
            sessionStorage.setItem(GEO_CACHE_AT, String(Date.now()));
        } catch (_) { /* ignore */ }
    }

    function readSavedShoppingRegion() {
        try {
            const v = (localStorage.getItem(SHOPPING_REGION_KEY) || '').toLowerCase();
            if (v === 'pl' || v === 'us') return v;
        } catch (_) { /* ignore */ }
        return null;
    }

    function persistShoppingRegion(r) {
        try {
            localStorage.setItem(SHOPPING_REGION_KEY, r);
        } catch (_) { /* ignore */ }
    }

    function getShoppingRegion() {
        return shoppingRegion || 'pl';
    }

    function setShoppingRegion(r, { silent } = {}) {
        const next = (r || '').toLowerCase() === 'us' ? 'us' : 'pl';
        const prev = getShoppingRegion();
        shoppingRegion = next;
        persistShoppingRegion(next);
        updateRegionToggleUi();
        if (!silent && prev !== next) {
            document.dispatchEvent(new CustomEvent('shoppingregionchange', {
                detail: { region: next },
            }));
            document.dispatchEvent(new CustomEvent('langchange', {
                detail: { lang: global.I18n?.getLang?.() },
            }));
        }
        renderBanner();
        return next;
    }

    function resolveDefaultShoppingRegion() {
        const saved = readSavedShoppingRegion();
        if (saved) return saved;
        if (countryCode === 'US') return 'us';
        return 'pl';
    }

    function isNonPl() {
        return !!(countryCode && countryCode !== 'PL');
    }

    /** USD dual display only in explicit US shopping mode — never for PL. */
    function shouldShowUsd() {
        return getShoppingRegion() === 'us';
    }

    function maybeAutoEnglish() {
        if (!countryCode || !EN_COUNTRIES[countryCode]) return;
        try {
            if (localStorage.getItem(LANG_KEY)) return;
        } catch (_) {
            return;
        }
        if (global.I18n?.setLang) {
            global.I18n.setLang('en');
        } else {
            try { localStorage.setItem(LANG_KEY, 'en'); } catch (_) { /* ignore */ }
        }
    }

    function t(key, fallback) {
        if (global.I18n?.t) {
            const v = global.I18n.t(key, typeof fallback === 'string' ? fallback : undefined);
            if (v && v !== key) return v;
        }
        return fallback;
    }

    function ensureBannerHost() {
        let el = document.getElementById('region-banner');
        if (el) return el;
        el = document.createElement('div');
        el.id = 'region-banner';
        el.className = 'region-banner';
        el.hidden = true;
        const header = document.querySelector('header.header');
        if (header && header.parentNode) {
            header.parentNode.insertBefore(el, header.nextSibling);
        } else {
            document.body.prepend(el);
        }
        return el;
    }

    function hideBanner() {
        const el = document.getElementById('region-banner');
        if (el) {
            el.hidden = true;
            el.innerHTML = '';
        }
    }

    function renderBanner() {
        // PL shopping: no conversion / geo banners — prices are simply PLN.
        if (getShoppingRegion() !== 'us') {
            hideBanner();
            return;
        }
        try {
            if (sessionStorage.getItem(BANNER_DISMISS) === '1') {
                hideBanner();
                return;
            }
        } catch (_) { /* ignore */ }

        const el = ensureBannerHost();
        const close = t('region.dismiss', 'Rozumiem');
        const text = t(
            'region.banner_us',
            'Ceny bazowe są w złotówkach (PLN). Pokazujemy też przybliżony odpowiednik w USD. Przed zakupem sprawdź region aktywacji klucza.'
        );
        el.hidden = false;
        el.innerHTML =
            `<div class="region-banner-inner wrap">` +
            `<p class="region-banner-text">${text}</p>` +
            `<button type="button" class="region-banner-close" aria-label="${close}">×</button>` +
            `</div>`;
        el.querySelector('.region-banner-close')?.addEventListener('click', () => {
            hideBanner();
            try { sessionStorage.setItem(BANNER_DISMISS, '1'); } catch (_) { /* ignore */ }
        });
    }

    function updateRegionToggleUi() {
        const region = getShoppingRegion();
        document.querySelectorAll('.region-switch .region-btn').forEach((btn) => {
            const active = btn.getAttribute('data-region') === region;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    }

    function buildRegionSwitch({ extraClass = '' } = {}) {
        const nav = document.createElement('nav');
        nav.className = ['region-switch', extraClass].filter(Boolean).join(' ');
        nav.setAttribute('aria-label', t('region.toggle_aria', 'Region zakupów'));
        ['pl', 'us'].forEach((code) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'region-btn';
            btn.dataset.region = code;
            btn.textContent = t('region.' + code, code.toUpperCase());
            btn.title = t(
                code === 'pl' ? 'region.pl_hint' : 'region.us_hint',
                code === 'pl' ? 'Ceny w PLN (Polska)' : 'Przybliżone ceny w USD'
            );
            btn.addEventListener('click', () => setShoppingRegion(code));
            nav.appendChild(btn);
        });
        return nav;
    }

    function mountRegionIntoHeader({ extraClass = '' } = {}) {
        document.querySelectorAll('.header-inner').forEach((inner) => {
            if (extraClass && inner.querySelector('.' + extraClass)) return;
            if (!extraClass && inner.querySelector('.region-switch')) return;

            let host = inner.querySelector('.header-actions');
            if (!host) {
                const authNav = inner.querySelector('#auth-nav');
                if (authNav) {
                    host = document.createElement('div');
                    host.className = 'header-actions';
                    inner.insertBefore(host, authNav);
                    host.appendChild(authNav);
                } else {
                    host = inner;
                }
            }
            const nav = buildRegionSwitch({ extraClass });
            const lang = host.querySelector('.lang-switch');
            if (lang) {
                host.insertBefore(nav, lang.nextSibling);
            } else if (host.classList.contains('header-actions')) {
                host.insertBefore(nav, host.firstChild);
            } else {
                host.appendChild(nav);
            }
            updateRegionToggleUi();
        });
    }

    function mountRegionToggle() {
        const slots = document.querySelectorAll('[data-region-switch-slot]');
        if (slots.length) {
            slots.forEach((slot) => {
                if (slot.querySelector('.region-switch')) return;
                slot.appendChild(buildRegionSwitch());
            });
            // Tablet mid (768–1023): classic header still visible.
            mountRegionIntoHeader({ extraClass: 'region-switch--header' });
        } else {
            mountRegionIntoHeader();
        }
        updateRegionToggleUi();
    }

    function formatUsd(pln) {
        if (usdPerPln == null || pln == null || !Number.isFinite(Number(pln))) return '';
        const usd = Number(pln) * usdPerPln;
        if (!Number.isFinite(usd)) return '';
        return `$${usd.toFixed(2)}`;
    }

    function formatPrice(pln) {
        const n = Number(pln);
        if (!Number.isFinite(n)) return '—';
        const plnTxt = `${n.toFixed(2)} zł`;
        // Default (PL): only zł — clear for Polish shoppers.
        if (getShoppingRegion() !== 'us') return plnTxt;
        const usd = formatUsd(n);
        if (!usd) return plnTxt;
        return `${plnTxt} <span class="price-usd">≈ ${usd}</span>`;
    }

    function formatPricePlain(pln) {
        const n = Number(pln);
        if (!Number.isFinite(n)) return '—';
        const plnTxt = `${n.toFixed(2)} zł`;
        if (getShoppingRegion() !== 'us') return plnTxt;
        const usd = formatUsd(n);
        return usd ? `${plnTxt} ≈ ${usd}` : plnTxt;
    }

    function notifyReady() {
        ready = true;
        listeners.splice(0).forEach((fn) => {
            try { fn({ countryCode, usdPerPln, shoppingRegion: getShoppingRegion() }); } catch (_) { /* ignore */ }
        });
        document.dispatchEvent(new CustomEvent('regionready', {
            detail: {
                countryCode,
                usdPerPln,
                showUsd: shouldShowUsd(),
                shoppingRegion: getShoppingRegion(),
            },
        }));
    }

    function onReady(fn) {
        if (ready) fn({ countryCode, usdPerPln, shoppingRegion: getShoppingRegion() });
        else listeners.push(fn);
    }

    async function loadFx() {
        try {
            const res = await fetch(api('fx'));
            if (!res.ok) return;
            const data = await res.json();
            if (data?.usd_per_pln) usdPerPln = Number(data.usd_per_pln);
        } catch (_) { /* ignore */ }
    }

    async function loadGeo() {
        const cached = cachedCountry();
        if (cached) {
            countryCode = cached || null;
            return;
        }
        try {
            const res = await fetch(api('geo'));
            if (!res.ok) return;
            const data = await res.json();
            countryCode = (data?.country_code || '').toUpperCase() || null;
            storeCountry(countryCode || '');
        } catch (_) { /* ignore */ }
    }

    async function init() {
        await Promise.all([loadGeo(), loadFx()]);
        shoppingRegion = resolveDefaultShoppingRegion();
        if (!readSavedShoppingRegion() && shoppingRegion === 'us') {
            persistShoppingRegion('us');
        }
        maybeAutoEnglish();
        mountRegionToggle();
        updateRegionToggleUi();
        renderBanner();
        notifyReady();
        document.dispatchEvent(new CustomEvent('langchange', {
            detail: { lang: global.I18n?.getLang?.() },
        }));
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    document.addEventListener('langchange', () => {
        renderBanner();
        document.querySelectorAll('.region-switch').forEach((nav) => {
            nav.setAttribute('aria-label', t('region.toggle_aria', 'Region zakupów'));
        });
        document.querySelectorAll('.region-switch .region-btn').forEach((btn) => {
            const code = btn.getAttribute('data-region');
            if (code) {
                btn.textContent = t('region.' + code, code.toUpperCase());
                btn.title = t(
                    code === 'pl' ? 'region.pl_hint' : 'region.us_hint',
                    code === 'pl' ? 'Ceny w PLN (Polska)' : 'Przybliżone ceny w USD'
                );
            }
        });
    });

    document.addEventListener('DOMContentLoaded', () => {
        setTimeout(mountRegionToggle, 0);
    });

    global.KupujPLRegion = {
        getCountry: () => countryCode,
        isNonPl,
        shouldShowUsd,
        formatUsd,
        formatPrice,
        formatPricePlain,
        onReady,
        getUsdPerPln: () => usdPerPln,
        getShoppingRegion,
        setShoppingRegion,
    };
})(typeof window !== 'undefined' ? window : globalThis);

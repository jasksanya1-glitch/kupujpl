/** KupujPL Gry — cookie consent (RODO). Self-contained, no dependencies. */
(function () {
    var KEY = 'kupujpl_cookie_consent';
    var LANG_KEY = 'kupujpl_lang';

    if (localStorage.getItem(KEY)) return;

    var T = {
        pl: {
            text: 'Używamy niezbędnych plików cookie do działania serwisu (logowanie, ustawienia). Linki do sklepów mogą zawierać pliki partnerskie. Szczegóły w ',
            policy: 'Polityce prywatności',
            accept: 'Akceptuję',
            necessary: 'Tylko niezbędne',
            aria: 'Zgoda na pliki cookie',
        },
        uk: {
            text: 'Ми використовуємо необхідні файли cookie для роботи сервісу (вхід, налаштування). Посилання на магазини можуть містити партнерські файли. Деталі в ',
            policy: 'Політиці конфіденційності',
            accept: 'Приймаю',
            necessary: 'Лише необхідні',
            aria: 'Згода на файли cookie',
        },
        en: {
            text: 'We use necessary cookies for the site to work (login, settings). Store links may contain affiliate cookies. Details in the ',
            policy: 'Privacy Policy',
            accept: 'Accept',
            necessary: 'Only necessary',
            aria: 'Cookie consent',
        },
    };

    function lang() {
        var l = localStorage.getItem(LANG_KEY);
        if (l && T[l]) return l;
        var n = (navigator.language || '').toLowerCase();
        if (n.indexOf('uk') === 0 || n.indexOf('ru') === 0) return 'uk';
        if (n.indexOf('en') === 0) return 'en';
        return 'pl';
    }

    function policyHref() {
        // works whether page uses <base href="/games/"> or not
        return 'polityka-prywatnosci';
    }

    function save(value) {
        try { localStorage.setItem(KEY, value); } catch (e) { /* ignore */ }
        if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
    }

    var t = T[lang()];
    var banner = document.createElement('div');
    banner.className = 'cookie-consent';
    banner.setAttribute('role', 'dialog');
    banner.setAttribute('aria-label', t.aria);
    banner.innerHTML =
        '<p class="cookie-consent__text">' + t.text +
        '<a href="' + policyHref() + '">' + t.policy + '</a>.</p>' +
        '<div class="cookie-consent__actions">' +
        '<button type="button" class="cookie-consent__btn cookie-consent__btn--ghost" data-cc="necessary">' + t.necessary + '</button>' +
        '<button type="button" class="cookie-consent__btn cookie-consent__btn--primary" data-cc="all">' + t.accept + '</button>' +
        '</div>';

    function mount() {
        document.body.appendChild(banner);
        banner.querySelector('[data-cc="all"]').addEventListener('click', function () { save('all'); });
        banner.querySelector('[data-cc="necessary"]').addEventListener('click', function () { save('necessary'); });
    }

    if (document.body) mount();
    else document.addEventListener('DOMContentLoaded', mount);
})();

/** Quenly / KupujPL — Site Chat widget (honest unavailable mode).
 *
 * Full `app.core.site_chat` + Telegram reply pipeline is not deployed.
 * Do not imply messages were sent or stored. Surface unavailable state only.
 */
(function () {
    if (window.__kupujplSiteChat) return;
    window.__kupujplSiteChat = true;

    var OPEN_KEY = 'kupujpl_site_chat_open';
    var LANG_KEY = 'kupujpl_lang';

    var T = {
        pl: {
            title: 'Czat',
            open: 'Otwórz czat',
            close: 'Zamknij',
            unavailable:
                'Czat jest tymczasowo niedostępny. Wiadomości nie są przyjmowane ani zapisywane.',
        },
        uk: {
            title: 'Чат',
            open: 'Відкрити чат',
            close: 'Закрити',
            unavailable:
                'Чат тимчасово недоступний. Повідомлення не приймаються і не зберігаються.',
        },
        en: {
            title: 'Chat',
            open: 'Open chat',
            close: 'Close',
            unavailable:
                'Chat is temporarily unavailable. Messages are not accepted or stored.',
        },
    };

    function lang() {
        try {
            var l = localStorage.getItem(LANG_KEY);
            if (l && T[l]) return l;
        } catch (e) {}
        var n = (navigator.language || '').toLowerCase();
        if (n.indexOf('uk') === 0 || n.indexOf('ru') === 0) return 'uk';
        if (n.indexOf('en') === 0) return 'en';
        return 'pl';
    }

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function api(path) {
        if (typeof window.apiUrl === 'function') return window.apiUrl(path);
        var match = window.location.pathname.match(/^(.*\/games)\/?/i);
        var root = match ? match[1] + '/' : '/games/';
        return root + 'api/' + String(path || '').replace(/^\//, '');
    }

    var t = T[lang()];
    var style = document.createElement('style');
    style.textContent =
        '.sc-root{position:fixed;right:0;bottom:88px;z-index:9400;font-family:inherit;pointer-events:none}' +
        '.sc-tab,.sc-panel{pointer-events:auto}' +
        '.sc-tab{display:flex;align-items:center;gap:6px;margin:0;padding:10px 12px 10px 14px;' +
        'border:1px solid rgba(0,0,0,.12);border-right:0;border-radius:12px 0 0 12px;' +
        'background:rgba(255,248,240,.96);color:#3a2a1a;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.12);' +
        'font-size:13px;font-weight:600}' +
        '.sc-tab-dot{width:8px;height:8px;border-radius:50%;background:#c45c26;opacity:.55}' +
        '.sc-panel{display:none;width:min(320px,calc(100vw - 16px));' +
        'flex-direction:column;border:1px solid rgba(0,0,0,.12);border-right:0;' +
        'border-radius:14px 0 0 14px;background:rgba(255,250,244,.98);color:#3a2a1a;' +
        'box-shadow:0 16px 40px rgba(0,0,0,.16);overflow:hidden}' +
        '.sc-root.is-open .sc-panel{display:flex}' +
        '.sc-root.is-open .sc-tab{display:none}' +
        '.sc-head{display:flex;justify-content:space-between;gap:8px;padding:12px;border-bottom:1px solid rgba(0,0,0,.08)}' +
        '.sc-head h3{margin:0;font-size:14px}' +
        '.sc-x{border:0;background:transparent;cursor:pointer;font-size:20px;line-height:1;color:#3a2a1a}' +
        '.sc-body{padding:14px 12px 16px;font-size:13px;line-height:1.45}' +
        '.sc-body strong{display:block;margin-bottom:6px}' +
        '@media (max-width:640px){.sc-root{bottom:max(108px,calc(env(safe-area-inset-bottom,0px)+96px))}}';
    document.head.appendChild(style);

    var root = document.createElement('div');
    root.className = 'sc-root';
    root.setAttribute('data-site-chat', 'unavailable');
    root.innerHTML =
        '<button type="button" class="sc-tab" aria-label="' + esc(t.open) + '">' +
        '<span class="sc-tab-dot" aria-hidden="true"></span><span>' + esc(t.title) + '</span></button>' +
        '<div class="sc-panel" role="dialog" aria-label="' + esc(t.title) + '">' +
        '<div class="sc-head"><h3>' + esc(t.title) + '</h3>' +
        '<button type="button" class="sc-x" aria-label="' + esc(t.close) + '">&times;</button></div>' +
        '<div class="sc-body"><strong>' + esc(t.unavailable) + '</strong></div></div>';
    document.body.appendChild(root);

    function setOpen(v) {
        root.classList.toggle('is-open', !!v);
        try {
            sessionStorage.setItem(OPEN_KEY, v ? '1' : '0');
        } catch (e) {}
    }

    root.querySelector('.sc-tab').addEventListener('click', function () {
        setOpen(true);
        // Probe API once so operators see 503 in network tab; never fake success.
        fetch(api('site-chat'), { credentials: 'same-origin' }).catch(function () {});
    });
    root.querySelector('.sc-x').addEventListener('click', function () {
        setOpen(false);
    });

    try {
        if (sessionStorage.getItem(OPEN_KEY) === '1') setOpen(true);
    } catch (e) {}
})();

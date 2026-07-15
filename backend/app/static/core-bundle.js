/** KupujPL Gry — core bundle (api-config, auth, covers, site-info) */
/** Resolve API/static base when app is served under /games/ */
(function () {
    const match = window.location.pathname.match(/^(.*\/games)\/?/i);
    const root = match ? `${match[1]}/` : "/games/";
    window.GAMES_ROOT = root;
    window.apiUrl = function apiUrl(path) {
        const clean = String(path || "").replace(/^\//, "");
        return `${root}api/${clean}`;
    };
})();

/** Wspólna autoryzacja JWT dla KupujPL Gry */
const TOKEN_KEY = 'kupujpl_games_token';
const USER_KEY = 'kupujpl_games_user';

function getToken() {
    return localStorage.getItem(TOKEN_KEY);
}

function getStoredUser() {
    try {
        const raw = localStorage.getItem(USER_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

function setAuth(token, user) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function clearAuth() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
}

function isLoggedIn() {
    return !!getToken();
}

function authHeaders(json = true) {
    const h = {};
    if (json) h['Content-Type'] = 'application/json';
    const t = getToken();
    if (t) h['Authorization'] = `Bearer ${t}`;
    return h;
}

function resolveApi(path) {
    if (typeof apiUrl === 'function') {
        return apiUrl(String(path || '').replace(/^\//, ''));
    }
    return path;
}

async function authFetch(url, options = {}) {
    const opts = { ...options };
    opts.headers = { ...authHeaders(!opts.body || typeof opts.body === 'string'), ...(options.headers || {}) };
    const res = await fetch(resolveApi(url), opts);
    if (res.status === 401) {
        clearAuth();
    }
    return res;
}

function requireAuth(redirectTo = 'login') {
    if (!isLoggedIn()) {
        window.location.href = redirectTo;
        return false;
    }
    return true;
}

/** Redirect only when JWT is still valid (avoids login↔panel loop after deploy/restart). */
async function redirectIfValidSession(target = 'panel') {
    if (!isLoggedIn()) return false;
    try {
        const res = await fetch(resolveApi('auth/me'), { headers: authHeaders(false) });
        if (res.ok) {
            window.location.href = target;
            return true;
        }
        clearAuth();
    } catch (_) {
        clearAuth();
    }
    return false;
}

function updateAuthNav() {
    const el = document.getElementById('auth-nav');
    if (!el) return;
    const tt = typeof t === 'function' ? t : (k) => k;
    const user = getStoredUser();
    if (user) {
        el.innerHTML = `
            <a href="panel" class="btn-nav btn-panel">${escapeHtml(tt('nav.panel'))}</a>
            <span class="nav-user">${escapeHtml(user.email)}</span>
            <button type="button" class="btn-nav btn-logout" id="btn-logout">${escapeHtml(tt('nav.logout'))}</button>
        `;
        const btn = document.getElementById('btn-logout');
        if (btn) {
            btn.addEventListener('click', () => {
                clearAuth();
                window.location.href = './';
            });
        }
    } else {
        el.innerHTML = `
            <a href="login" class="btn-nav btn-login">${escapeHtml(tt('nav.login'))}</a>
            <a href="register" class="btn-nav btn-register">${escapeHtml(tt('nav.register'))}</a>
        `;
    }
}

document.addEventListener('langchange', updateAuthNav);

function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
}

document.addEventListener('DOMContentLoaded', updateAuthNav);

/** Shared Steam cover URLs + fallback chain for game cards. */
const PLACEHOLDER_COVER =
    'data:image/svg+xml,' +
    encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="460" height="215">' +
            '<rect fill="#1f1f1f" width="100%" height="100"/>' +
            '<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" ' +
            'fill="#aaa" font-family="system-ui,sans-serif" font-size="14">Brak okładki</text>' +
            '</svg>'
    );

const STEAM_CDN = 'https://shared.cloudflare.steamstatic.com';
const LEGACY_CDN = 'https://cdn.akamai.steamstatic.com';

function normalizeCoverUrl(url) {
    if (!url || !String(url).trim()) return null;
    return String(url)
        .trim()
        .replace(/shared\.akamai\.steamstatic\.com/g, 'shared.cloudflare.steamstatic.com')
        .replace(/cdn\.akamai\.steamstatic\.com/g, 'shared.cloudflare.steamstatic.com')
        .replace(/shared\.fastly\.steamstatic\.com/g, 'shared.cloudflare.steamstatic.com');
}

function isLowResCover(url) {
    if (!url) return true;
    const u = url.toLowerCase();
    return (
        u.includes('capsule_sm_120') ||
        u.includes('capsule_sm_') ||
        u.includes('231x87') ||
        u.includes('467x181') ||
        u.includes('_120.jpg')
    );
}

function steamFallbackUrls(steamAppid) {
    if (!steamAppid) return [];
    const id = String(steamAppid);
    return [
        `${STEAM_CDN}/store_item_assets/steam/apps/${id}/header.jpg`,
        `${STEAM_CDN}/store_item_assets/steam/apps/${id}/capsule_616x353.jpg`,
        `${STEAM_CDN}/steam/apps/${id}/header.jpg`,
        `${STEAM_CDN}/steam/apps/${id}/capsule_616x353.jpg`,
        `${STEAM_CDN}/steam/apps/${id}/library_600x900.jpg`,
        `${LEGACY_CDN}/steam/apps/${id}/header.jpg`,
        `${LEGACY_CDN}/steam/apps/${id}/capsule_616x353.jpg`,
    ];
}

function isGenericSteamCover(url) {
    if (!url) return false;
    return /\/apps\/\d+\/(header|capsule_616x353)\.jpg/i.test(url);
}

function coverChainForGame(game) {
    const urls = [];
    const stored = normalizeCoverUrl(game?.cover_image);
    const appid = game?.steam_appid;
    const isHashAsset = stored && /\/apps\/\d+\/[a-f0-9]{40}\//i.test(stored);
    const tryHdFirst =
        appid && !isHashAsset && (isLowResCover(stored) || isGenericSteamCover(stored));

    if (tryHdFirst) {
        urls.push(...steamFallbackUrls(appid));
        if (stored) urls.push(stored);
    } else {
        if (stored) urls.push(stored);
        if (appid) urls.push(...steamFallbackUrls(appid));
    }
    if (!urls.length) urls.push(PLACEHOLDER_COVER);
    return [...new Set(urls)];
}

function coverFallbackUrls(steamAppid) {
    const chain = steamFallbackUrls(steamAppid);
    chain.push(PLACEHOLDER_COVER);
    return chain.length ? chain : [PLACEHOLDER_COVER];
}

function gameCoverSrc(game) {
    return coverChainForGame(game)[0];
}

function bindCoverFallback(img, gameOrAppid) {
    if (!img) return;
    const game =
        typeof gameOrAppid === 'object' && gameOrAppid !== null
            ? gameOrAppid
            : { steam_appid: gameOrAppid };
    const chain = [...coverChainForGame(game), PLACEHOLDER_COVER];
    const unique = [...new Set(chain)];
    img.dataset.fallbackStep = '0';
    img.onerror = () => {
        const next = parseInt(img.dataset.fallbackStep || '0', 10) + 1;
        if (next < unique.length) {
            img.dataset.fallbackStep = String(next);
            img.src = unique[next];
        }
    };
}

/** Inject contact / donate URLs from API (env on server). */
(function () {
    function apply(info) {
        if (!info) return;
        const map = [
            ['#contact-email', 'contact_email', 'mailto:'],
            ['#privacy-email', 'contact_email', 'mailto:'],
            ['#donate-email', 'contact_email', 'mailto:'],
            ['#contact-telegram', 'telegram_url', ''],
            ['#privacy-telegram', 'telegram_url', ''],
            ['#contact-instagram', 'instagram_url', ''],
            ['#contact-donate', 'donate_url', ''],
            ['#contact-donate-qr', 'donate_url', ''],
            ['#donate-main', 'donate_url', ''],
        ];
        for (const [sel, key, prefix] of map) {
            document.querySelectorAll(sel).forEach((el) => {
                const val = info[key];
                if (!val) return;
                if (prefix === 'mailto:') {
                    el.href = 'mailto:' + val.replace(/^mailto:/, '');
                    if (el.id.includes('email')) el.textContent = val.replace(/^mailto:/, '');
                } else {
                    el.href = val;
                    if (key === 'donate_url' && info.donate_label && !el.querySelector('img')) {
                        el.textContent = el.classList.contains('btn-donate')
                            ? 'Postaw kawę — ' + info.donate_label
                            : info.donate_label;
                    }
                    if (key === 'telegram_url' && info.telegram_label && el.id.includes('telegram')) {
                        el.textContent = info.telegram_label;
                    }
                    if (key === 'instagram_url' && info.instagram_label && el.id.includes('instagram')) {
                        el.textContent = info.instagram_label;
                    }
                }
            });
        }
    }

    fetch(resolveApi('site/info'))
        .then((r) => (r.ok ? r.json() : null))
        .then(apply)
        .catch(() => {});
})();

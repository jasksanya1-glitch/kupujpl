/** Wspólna autoryzacja JWT + cookie-sesja dla KupujPL Gry */
const TOKEN_KEY = 'kupujpl_games_token';
const USER_KEY = 'kupujpl_games_user';

function getToken() {
    try {
        return localStorage.getItem(TOKEN_KEY);
    } catch {
        return null;
    }
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
    try {
        if (token) localStorage.setItem(TOKEN_KEY, token);
        if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    } catch (_) {
        /* private mode / blocked storage — cookie session still works */
    }
}

function clearAuth() {
    try {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
    } catch (_) {}
    try {
        fetch(resolveApi('auth/logout'), {
            method: 'POST',
            credentials: 'same-origin',
            keepalive: true,
        }).catch(() => {});
    } catch (_) {}
}

function isLoggedIn() {
    // Token OR stored user (HttpOnly cookie may still authenticate API).
    return !!(getToken() || getStoredUser());
}

function authHeaders(json = true) {
    const h = {};
    if (json) h['Content-Type'] = 'application/json';
    const token = getToken();
    if (token) h['Authorization'] = `Bearer ${token}`;
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
    const hadToken = !!getToken();
    opts.headers = { ...authHeaders(!opts.body || typeof opts.body === 'string'), ...(options.headers || {}) };
    opts.credentials = 'same-origin';
    const res = await fetch(resolveApi(url), opts);
    // Drop local session only when we sent a Bearer token and it was rejected.
    // Cookie-only sessions must not be wiped by a transient 401.
    if (res.status === 401 && hadToken) {
        try {
            localStorage.removeItem(TOKEN_KEY);
            localStorage.removeItem(USER_KEY);
        } catch (_) {}
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

/** Redirect only when JWT/cookie session is still valid. */
async function redirectIfValidSession(target = 'panel') {
    if (!isLoggedIn()) return false;
    try {
        const res = await fetch(resolveApi('auth/me'), {
            headers: authHeaders(false),
            credentials: 'same-origin',
        });
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
    if (user && isLoggedIn()) {
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
            <a href="register?intent=alert" class="btn-nav btn-register btn-register-alert" title="${escapeHtml(tt('nav.register'))}">
                <span class="btn-register-full">${escapeHtml(tt('nav.register'))}</span>
                <span class="btn-register-short">${escapeHtml(tt('nav.register_short'))}</span>
            </a>
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

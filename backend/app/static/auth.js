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

/** Google Sign-In (GIS) вЂ” login / register */
(function () {
    function api(path) {
        if (typeof apiUrl === 'function') return apiUrl(String(path || '').replace(/^\//, ''));
        const root = window.GAMES_ROOT || '/games/';
        return `${root}api/${String(path || '').replace(/^\//, '')}`;
    }

    async function handleGoogleCredential(credential, errorEl) {
        const res = await fetch(api('auth/google'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ credential }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const msg = typeof data.detail === 'string' ? data.detail : 'Logowanie Google nie powiodЕ‚o siД™.';
            if (errorEl) {
                errorEl.textContent = msg;
                errorEl.hidden = false;
            }
            return;
        }
        if (typeof setAuth === 'function') {
            setAuth(data.access_token, data.user);
        }
        window.location.href = 'panel';
    }

    function loadGisScript() {
        return new Promise((resolve, reject) => {
            if (window.google?.accounts?.id) {
                resolve();
                return;
            }
            const existing = document.querySelector('script[src="https://accounts.google.com/gsi/client"]');
            if (existing) {
                existing.addEventListener('load', () => resolve());
                existing.addEventListener('error', () => reject(new Error('GIS load failed')));
                return;
            }
            const s = document.createElement('script');
            s.src = 'https://accounts.google.com/gsi/client';
            s.async = true;
            s.defer = true;
            s.onload = () => resolve();
            s.onerror = () => reject(new Error('GIS load failed'));
            document.head.appendChild(s);
        });
    }

    async function initGoogleSignIn(containerId, errorElId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        let config;
        try {
            const res = await fetch(api('auth/google-config'));
            config = await res.json();
        } catch {
            return;
        }
        if (!config?.enabled || !config.client_id) {
            container.hidden = true;
            container.setAttribute('aria-hidden', 'true');
            return;
        }

        try {
            await loadGisScript();
        } catch {
            return;
        }

        const errorEl = errorElId ? document.getElementById(errorElId) : null;

        window.google.accounts.id.initialize({
            client_id: config.client_id,
            callback: (response) => {
                if (response.credential) {
                    handleGoogleCredential(response.credential, errorEl);
                }
            },
            auto_select: false,
            cancel_on_tap_outside: true,
        });

        window.google.accounts.id.renderButton(container, {
            type: 'standard',
            theme: 'outline',
            size: 'large',
            text: 'continue_with',
            shape: 'rectangular',
            logo_alignment: 'left',
            width: Math.min(400, container.offsetWidth || 320),
            locale: 'pl',
        });
    }

    window.initGoogleSignIn = initGoogleSignIn;
})();


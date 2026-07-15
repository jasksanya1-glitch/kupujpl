/** Web Push (PWA) — rejestracja SW i subskrypcja alertów cenowych */
(function () {
    function gamesRoot() {
        return window.GAMES_ROOT || '/games/';
    }

    function api(path) {
        if (typeof apiUrl === 'function') return apiUrl(String(path || '').replace(/^\//, ''));
        return `${gamesRoot()}api/${String(path || '').replace(/^\//, '')}`;
    }

    function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const raw = atob(base64);
        const arr = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i += 1) arr[i] = raw.charCodeAt(i);
        return arr;
    }

    function pushSupported() {
        return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
    }

    async function fetchVapidPublicKey() {
        const res = await fetch(api('push/vapid-public-key'), { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Nie udało się pobrać klucza push.');
        const data = await res.json();
        if (!data.configured || !data.public_key) {
            throw new Error('Push nie jest skonfigurowany na serwerze.');
        }
        return data.public_key;
    }

    async function registerServiceWorker() {
        const root = gamesRoot();
        const swUrl = `${root}sw.js`;
        const reg = await navigator.serviceWorker.register(swUrl, { scope: root });
        await navigator.serviceWorker.ready;
        return reg;
    }

    async function getPushStatus() {
        if (!pushSupported()) {
            return { supported: false, configured: false, subscribed: false, subscription_count: 0 };
        }
        if (!isLoggedIn || !isLoggedIn()) {
            return { supported: true, configured: false, subscribed: false, subscription_count: 0 };
        }
        try {
            const res = await authFetch('push/status', { headers: authHeaders(false) });
            if (!res.ok) return { supported: true, configured: false, subscribed: false, subscription_count: 0 };
            return await res.json();
        } catch {
            return { supported: true, configured: false, subscribed: false, subscription_count: 0 };
        }
    }

    async function subscribeWebPush() {
        if (!pushSupported()) throw new Error('Twoja przeglądarka nie obsługuje powiadomień push.');
        if (!isLoggedIn || !isLoggedIn()) throw new Error('Zaloguj się, aby włączyć push.');

        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
            throw new Error('Brak zgody na powiadomienia. Włącz je w ustawieniach przeglądarki.');
        }

        const publicKey = await fetchVapidPublicKey();
        const reg = await registerServiceWorker();
        let sub = await reg.pushManager.getSubscription();
        if (!sub) {
            sub = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(publicKey),
            });
        }

        const res = await authFetch('push/subscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders(true) },
            body: JSON.stringify(sub.toJSON()),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Nie udało się zapisać subskrypcji push.');
        return data;
    }

    async function unsubscribeWebPush() {
        if (!pushSupported()) return { ok: true };
        const reg = await navigator.serviceWorker.getRegistration(gamesRoot());
        const sub = reg ? await reg.pushManager.getSubscription() : null;
        if (sub) {
            await authFetch('push/unsubscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders(true) },
                body: JSON.stringify({ endpoint: sub.endpoint }),
            }).catch(() => {});
            try {
                await sub.unsubscribe();
            } catch (_) { /* ignore */ }
        } else if (isLoggedIn && isLoggedIn()) {
            await authFetch('push/unsubscribe', {
                method: 'POST',
                headers: authHeaders(true),
                body: JSON.stringify({}),
            }).catch(() => {});
        }
        return { ok: true };
    }

    window.KupujPLPush = {
        pushSupported,
        getPushStatus,
        subscribeWebPush,
        unsubscribeWebPush,
        registerServiceWorker,
    };
})();

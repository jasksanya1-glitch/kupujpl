/* KupujPL Gry — Web Push service worker */
self.addEventListener('push', (event) => {
    let payload = {
        title: 'KupujPL Gry',
        body: 'Spadek ceny w śledzonej grze',
        url: '/games/panel',
        tag: 'kupujpl-alert',
    };
    if (event.data) {
        try {
            payload = { ...payload, ...event.data.json() };
        } catch (_) {
            payload.body = event.data.text() || payload.body;
        }
    }
    const options = {
        body: payload.body,
        icon: '/games/static/icons/icon-192.png',
        badge: '/games/static/icons/icon-192.png',
        tag: payload.tag || 'kupujpl-alert',
        data: { url: payload.url || '/games/panel' },
        requireInteraction: false,
    };
    event.waitUntil(self.registration.showNotification(payload.title, options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const target = event.notification.data?.url || '/games/panel';
    const absolute = target.startsWith('http') ? target : `${self.location.origin}${target.startsWith('/') ? '' : '/'}${target}`;
    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
            for (const client of clients) {
                if (client.url.includes('/games/') && 'focus' in client) {
                    client.navigate(absolute);
                    return client.focus();
                }
            }
            if (self.clients.openWindow) {
                return self.clients.openWindow(absolute);
            }
            return undefined;
        })
    );
});

self.addEventListener('install', (event) => {
    event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

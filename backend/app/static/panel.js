document.addEventListener('DOMContentLoaded', () => {
    if (!requireAuth()) return;

    const grid = document.getElementById('favorites-grid');
    const welcome = document.getElementById('panel-welcome');
    const panelCount = document.getElementById('panel-count');
    const panelStats = document.getElementById('panel-stats');
    const sortSelect = document.getElementById('fav-sort');
    const onlyPriced = document.getElementById('fav-only-priced');
    const refreshBtn = document.getElementById('btn-refresh-prices');
    const refreshMsg = document.getElementById('refresh-msg');
    const modal = document.getElementById('game-modal');
    const overlay = document.querySelector('.modal-overlay');
    const closeBtn = document.querySelector('.modal-close');
    const panelAvatar = document.getElementById('panel-avatar');

    let favoritesCache = [];
    let spotlightGames = [];
    let spotlightSearchTimer = null;
    const navSpotlight = document.getElementById('nav-spotlight');
    const panelSpotlight = document.getElementById('panel-spotlight');
    const spotlightList = document.getElementById('spotlight-list');
    const spotlightMsg = document.getElementById('spotlight-msg');
    const spotlightSteamInput = document.getElementById('spotlight-steam-input');
    const spotlightSearchInput = document.getElementById('spotlight-search-input');
    const spotlightSearchResults = document.getElementById('spotlight-search-results');

    const api = (path) => (typeof apiUrl === 'function' ? apiUrl(path) : `api/${path}`);
    const tt = (k, v) => (typeof t === 'function' ? t(k, v) : k);

    function closeModal() {
        modal.hidden = true;
        document.body.style.overflow = '';
    }

    closeBtn?.addEventListener('click', closeModal);
    overlay?.addEventListener('click', closeModal);

    fetch(api('track-visit'), {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify({ path: '/panel' }),
        credentials: 'same-origin',
    }).catch(() => {});

    document.querySelectorAll('.panel-cp-nav-btn, .panel-nav-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const target = btn.dataset.panel;
            document.querySelectorAll('.panel-cp-nav-btn, .panel-nav-btn').forEach(b => b.classList.toggle('active', b === btn));
            document.getElementById('panel-watchlist').hidden = target !== 'watchlist';
            document.getElementById('panel-account').hidden = target !== 'account';
            if (panelSpotlight) panelSpotlight.hidden = target !== 'spotlight';
        });
    });

    sortSelect?.addEventListener('change', () => renderFavorites(getFilteredSorted()));
    onlyPriced?.addEventListener('change', () => renderFavorites(getFilteredSorted()));

    refreshBtn?.addEventListener('click', async () => {
        refreshBtn.disabled = true;
        refreshMsg.hidden = true;
        try {
            const res = await authFetch('favorites/refresh-offers', { method: 'POST' });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Błąd');
            refreshMsg.textContent = data.message || 'Odświeżanie w tle…';
            refreshMsg.hidden = false;
            setTimeout(() => loadFavorites(), 8000);
        } catch (e) {
            refreshMsg.textContent = e.message || 'Nie udało się odświeżyć.';
            refreshMsg.hidden = false;
        } finally {
            refreshBtn.disabled = false;
        }
    });

    document.getElementById('password-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const err = document.getElementById('pwd-error');
        const ok = document.getElementById('pwd-success');
        err.hidden = true;
        ok.hidden = true;
        const fd = new FormData(e.target);
        if (fd.get('new') !== fd.get('new2')) {
            err.textContent = 'Nowe hasła nie są identyczne';
            err.hidden = false;
            return;
        }
        try {
            const res = await authFetch('account/change-password', {
                method: 'POST',
                body: JSON.stringify({
                    current_password: fd.get('current'),
                    new_password: fd.get('new'),
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Błąd');
            ok.textContent = data.message || 'Hasło zmienione.';
            ok.hidden = false;
            e.target.reset();
        } catch (ex) {
            err.textContent = ex.message || 'Błąd zmiany hasła';
            err.hidden = false;
        }
    });

    loadSummary();
    loadAlertsSettings();
    loadFavorites();
    initWishlistImport();
    initSpotlightPanel();

    function showSpotlightMsg(text, isErr) {
        if (!spotlightMsg) return;
        spotlightMsg.textContent = text;
        spotlightMsg.className = isErr ? 'panel-cp-flash panel-cp-flash--err' : 'panel-cp-flash panel-cp-flash--ok';
        spotlightMsg.hidden = !text;
    }

    async function initSpotlightPanel() {
        try {
            const res = await authFetch('auth/me');
            if (!res.ok) return;
            const me = await res.json();
            if (!me.is_site_owner) return;
            if (navSpotlight) navSpotlight.hidden = false;
            await loadSpotlightCuration();
            document.getElementById('btn-spotlight-save')?.addEventListener('click', saveSpotlightCuration);
            document.getElementById('btn-spotlight-import')?.addEventListener('click', importSpotlightSteam);
            spotlightSteamInput?.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') importSpotlightSteam();
            });
            spotlightSearchInput?.addEventListener('input', () => {
                clearTimeout(spotlightSearchTimer);
                spotlightSearchTimer = setTimeout(searchSpotlightCatalog, 350);
            });
        } catch (e) {
            console.warn('spotlight init', e);
        }
    }

    async function loadSpotlightCuration() {
        const res = await authFetch('panel/home-curation');
        if (!res.ok) return;
        const data = await res.json();
        spotlightGames = data.games || [];
        renderSpotlightList();
    }

    function renderSpotlightList() {
        if (!spotlightList) return;
        if (!spotlightGames.length) {
            spotlightList.innerHTML = `<p class="panel-cp-muted">${escapeHtml(tt('panel.spotlight_empty'))}</p>`;
            return;
        }
        spotlightList.innerHTML = spotlightGames.map((game, idx) => {
            const price = game.best_price_pln != null
                ? `${Number(game.best_price_pln).toFixed(2)} zł`
                : tt('card.check_price');
            const shops = game.in_stock_shop_count != null ? game.in_stock_shop_count : 0;
            const cover = gameCoverSrc(game);
            return `<article class="panel-cp-spotlight-item" data-slug="${escapeHtml(game.slug)}">
                <img class="panel-cp-spotlight-cover" src="${escapeHtml(cover)}" alt="">
                <div class="panel-cp-spotlight-body">
                    <h3>${escapeHtml(game.title)}</h3>
                    <p class="panel-cp-muted">${escapeHtml(price)} · ${shops} sklepów</p>
                    <div class="panel-cp-spotlight-actions">
                        <button type="button" class="cp-btn cp-btn-red btn-spotlight-scan" data-slug="${escapeHtml(game.slug)}">${escapeHtml(tt('panel.scan_all_shops'))}</button>
                        <button type="button" class="cp-btn cp-btn-ghost btn-spotlight-up" data-idx="${idx}" ${idx === 0 ? 'disabled' : ''}>↑</button>
                        <button type="button" class="cp-btn cp-btn-ghost btn-spotlight-down" data-idx="${idx}" ${idx >= spotlightGames.length - 1 ? 'disabled' : ''}>↓</button>
                        <button type="button" class="cp-btn cp-btn-ghost btn-spotlight-remove" data-slug="${escapeHtml(game.slug)}">✕</button>
                    </div>
                    <p class="panel-cp-spotlight-scan-msg panel-cp-muted" data-slug="${escapeHtml(game.slug)}" hidden></p>
                </div>
            </article>`;
        }).join('');

        spotlightList.querySelectorAll('.btn-spotlight-scan').forEach(btn => {
            btn.addEventListener('click', () => scanSpotlightGame(btn.dataset.slug, btn));
        });
        spotlightList.querySelectorAll('.btn-spotlight-remove').forEach(btn => {
            btn.addEventListener('click', () => {
                spotlightGames = spotlightGames.filter(g => g.slug !== btn.dataset.slug);
                renderSpotlightList();
                saveSpotlightCuration();
            });
        });
        spotlightList.querySelectorAll('.btn-spotlight-up').forEach(btn => {
            btn.addEventListener('click', () => moveSpotlightGame(Number(btn.dataset.idx), -1));
        });
        spotlightList.querySelectorAll('.btn-spotlight-down').forEach(btn => {
            btn.addEventListener('click', () => moveSpotlightGame(Number(btn.dataset.idx), 1));
        });
    }

    function moveSpotlightGame(idx, delta) {
        const next = idx + delta;
        if (next < 0 || next >= spotlightGames.length) return;
        const copy = spotlightGames.slice();
        const [item] = copy.splice(idx, 1);
        copy.splice(next, 0, item);
        spotlightGames = copy;
        renderSpotlightList();
        saveSpotlightCuration();
    }

    function addSpotlightGame(game) {
        if (!game?.slug) return;
        if (spotlightGames.some(g => g.slug === game.slug)) {
            showSpotlightMsg(tt('panel.spotlight_duplicate'), true);
            return;
        }
        if (spotlightGames.length >= 8) {
            showSpotlightMsg(tt('panel.spotlight_max'), true);
            return;
        }
        spotlightGames.push({
            ...game,
            in_stock_shop_count: game.in_stock_shop_count ?? 0,
        });
        renderSpotlightList();
        showSpotlightMsg(tt('panel.spotlight_added'), false);
        saveSpotlightCuration();
    }

    async function importSpotlightSteam() {
        const url = spotlightSteamInput?.value?.trim();
        if (!url) return;
        showSpotlightMsg('', false);
        try {
            const res = await authFetch('panel/home-curation/import-steam', {
                method: 'POST',
                body: JSON.stringify({ url }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Błąd importu');
            if (spotlightSteamInput) spotlightSteamInput.value = '';
            addSpotlightGame(data);
        } catch (e) {
            showSpotlightMsg(e.message || 'Błąd', true);
        }
    }

    async function searchSpotlightCatalog() {
        const q = spotlightSearchInput?.value?.trim();
        if (!q || q.length < 2) {
            if (spotlightSearchResults) spotlightSearchResults.hidden = true;
            return;
        }
        try {
            const res = await fetch(api(`games?q=${encodeURIComponent(q)}&limit=8`));
            const data = await res.json();
            const items = data.items || [];
            if (!spotlightSearchResults) return;
            if (!items.length) {
                spotlightSearchResults.innerHTML = `<p class="panel-cp-muted">${escapeHtml(tt('search.no_results'))}</p>`;
                spotlightSearchResults.hidden = false;
                return;
            }
            spotlightSearchResults.innerHTML = items.map(g => `
                <button type="button" class="panel-cp-spotlight-pick" data-slug="${escapeHtml(g.slug)}">
                    <img src="${escapeHtml(gameCoverSrc(g))}" alt="">
                    <span>${escapeHtml(g.title)}</span>
                </button>`).join('');
            spotlightSearchResults.hidden = false;
            spotlightSearchResults.querySelectorAll('.panel-cp-spotlight-pick').forEach(btn => {
                btn.addEventListener('click', () => {
                    const game = items.find(x => x.slug === btn.dataset.slug);
                    if (game) addSpotlightGame({ ...game, in_stock_shop_count: 0 });
                    if (spotlightSearchResults) spotlightSearchResults.hidden = true;
                    if (spotlightSearchInput) spotlightSearchInput.value = '';
                });
            });
        } catch (e) {
            console.warn(e);
        }
    }

    async function saveSpotlightCuration() {
        const btn = document.getElementById('btn-spotlight-save');
        if (btn) btn.disabled = true;
        try {
            const res = await authFetch('panel/home-curation', {
                method: 'PUT',
                body: JSON.stringify({ spotlight_slugs: spotlightGames.map(g => g.slug) }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Błąd zapisu');
            spotlightGames = data.games || spotlightGames;
            renderSpotlightList();
            showSpotlightMsg(tt('panel.spotlight_saved'), false);
        } catch (e) {
            showSpotlightMsg(e.message || 'Błąd', true);
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async function scanSpotlightGame(slug, btn) {
        if (!slug) return;
        const statusEl = btn?.closest('.panel-cp-spotlight-item')?.querySelector('.panel-cp-spotlight-scan-msg');
        if (btn) btn.disabled = true;
        if (statusEl) {
            statusEl.textContent = tt('panel.spotlight_scanning');
            statusEl.hidden = false;
        }
        try {
            const res = await authFetch(`panel/home-curation/${encodeURIComponent(slug)}/scan-all`, {
                method: 'POST',
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Błąd skanu');
            if (statusEl) statusEl.textContent = data.message || tt('panel.spotlight_scan_done');
            setTimeout(() => loadSpotlightCuration(), 12000);
        } catch (e) {
            if (statusEl) statusEl.textContent = e.message || 'Błąd';
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    function initWishlistImport() {
        const form = document.getElementById('wishlist-import-form');
        const input = document.getElementById('wishlist-profile');
        const btn = document.getElementById('wishlist-import-btn');
        const msg = document.getElementById('wishlist-import-msg');
        const results = document.getElementById('wishlist-import-results');
        if (!form || !input) return;

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const profile = input.value.trim();
            if (!profile) return;
            if (btn) btn.disabled = true;
            if (msg) {
                msg.hidden = true;
                msg.className = 'panel-cp-flash panel-cp-flash--ok';
            }
            if (results) {
                results.hidden = true;
                results.innerHTML = '';
            }
            try {
                const res = await authFetch('favorites/import-steam-wishlist', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', ...authHeaders(true) },
                    body: JSON.stringify({ profile }),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    const detail = data.detail;
                    const text = typeof detail === 'string'
                        ? detail
                        : detail?.detail || detail?.message || 'Import nie powiódł się.';
                    const hint = typeof detail === 'object' && detail?.hint ? ` ${detail.hint}` : '';
                    throw new Error(text + hint);
                }
                if (msg) {
                    msg.textContent = data.message || 'Import zakończony.';
                    msg.hidden = false;
                }
                renderWishlistImportResults(data, results);
                input.value = '';
                loadFavorites();
            } catch (err) {
                if (msg) {
                    msg.textContent = err.message || 'Błąd importu wishlisty.';
                    msg.className = 'panel-cp-flash panel-cp-flash--err';
                    msg.hidden = false;
                }
            } finally {
                if (btn) btn.disabled = false;
            }
        });
    }

    function renderWishlistImportResults(data, container) {
        if (!container) return;
        const sched = data.schedule || {};
        const scheduleLine = sched.vps_local
            ? `Harmonogram skanów Tier A: VPS ~${sched.vps_local}, PC ~${sched.pc_local}, laptop ~${sched.laptop_local} (${sched.timezone || 'Europe/Warsaw'}).`
            : '';

        const section = (title, items, emptyText) => {
            if (!items?.length) return '';
            const rows = items.map((g) => {
                const note = g.message ? `<span class="panel-cp-wishlist-note">${escapeHtml(g.message)}</span>` : '';
                return `<li><strong>${escapeHtml(g.title || g.slug || g.steam_appid)}</strong>${note}</li>`;
            }).join('');
            return `<div class="panel-cp-wishlist-group"><h4>${title} (${items.length})</h4><ul>${rows}</ul></div>`;
        };

        const html = [
            `<p class="panel-cp-wishlist-summary">${escapeHtml(data.message || '')}</p>`,
            data.truncated ? '<p class="panel-cp-muted">Wishlista była dłuższa — przetworzono pierwsze gry (limit importu).</p>' : '',
            scheduleLine ? `<p class="panel-cp-muted">${escapeHtml(scheduleLine)}</p>` : '',
            section('Nowo śledzone', data.tracked, ''),
            section('Dodane do katalogu (wcześniej nie było w bazie)', data.added_to_catalog, ''),
            section('Dodane do kolejki skanów Tier A', data.queued_for_scan, ''),
            section('Już śledziłeś', data.already_tracked, ''),
            section('Pominięte', data.skipped, ''),
        ].filter(Boolean).join('');

        if (!html) return;
        container.innerHTML = html;
        container.hidden = false;
    }

    function formatDate(iso) {
        if (!iso) return '—';
        try {
            return new Intl.DateTimeFormat('pl-PL', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso));
        } catch {
            return iso;
        }
    }

    function formatMoney(n) {
        if (n == null) return '—';
        return `${Number(n).toFixed(2)} zł`;
    }

    async function loadAlertsSettings() {
        const emailCb = document.getElementById('acc-email-alerts');
        const cmdEl = document.getElementById('telegram-start-cmd');
        const botLink = document.getElementById('telegram-bot-link');
        const msg = document.getElementById('alerts-msg');
        const pushStatus = document.getElementById('push-status-line');
        const pushEnable = document.getElementById('btn-push-enable');
        const pushDisable = document.getElementById('btn-push-disable');
        const pushBox = document.getElementById('push-alerts-box');

        try {
            const res = await authFetch('account/telegram-link');
            if (res.ok) {
                const data = await res.json();
                if (cmdEl) cmdEl.textContent = data.start_command || '';
                if (botLink && data.bot_username) {
                    botLink.href = `https://t.me/${data.bot_username}`;
                }
            }
        } catch (e) {
            console.warn('telegram link', e);
        }

        async function refreshPushUi() {
            const push = window.KupujPLPush;
            if (!push || !pushBox) return;
            if (!push.pushSupported()) {
                if (pushStatus) pushStatus.textContent = 'Push niedostępny w tej przeglądarce (użyj e-mail lub Telegram).';
                if (pushEnable) pushEnable.hidden = true;
                if (pushDisable) pushDisable.hidden = true;
                return;
            }
            try {
                const st = await push.getPushStatus();
                if (!st.configured) {
                    if (pushStatus) pushStatus.textContent = 'Push na serwerze wkrótce — na razie e-mail i Telegram.';
                    if (pushEnable) pushEnable.hidden = true;
                    if (pushDisable) pushDisable.hidden = true;
                    return;
                }
                if (st.subscribed) {
                    if (pushStatus) pushStatus.textContent = `Push włączony (${st.subscription_count || 1} urządzenie).`;
                    if (pushEnable) pushEnable.hidden = true;
                    if (pushDisable) pushDisable.hidden = false;
                } else {
                    if (pushStatus) pushStatus.textContent = 'Push wyłączony — kliknij, aby otrzymywać alerty w przeglądarce.';
                    if (pushEnable) pushEnable.hidden = false;
                    if (pushDisable) pushDisable.hidden = true;
                }
            } catch (e) {
                if (pushStatus) pushStatus.textContent = 'Nie udało się sprawdzić statusu push.';
            }
        }

        pushEnable?.addEventListener('click', async () => {
            pushEnable.disabled = true;
            try {
                await window.KupujPLPush.subscribeWebPush();
                if (msg) {
                    msg.textContent = 'Powiadomienia push włączone.';
                    msg.className = 'panel-cp-flash panel-cp-flash--ok';
                    msg.hidden = false;
                }
                await refreshPushUi();
            } catch (err) {
                if (msg) {
                    msg.textContent = err.message || 'Nie udało się włączyć push.';
                    msg.className = 'panel-cp-flash panel-cp-flash--err';
                    msg.hidden = false;
                }
            } finally {
                pushEnable.disabled = false;
            }
        });

        pushDisable?.addEventListener('click', async () => {
            pushDisable.disabled = true;
            try {
                await window.KupujPLPush.unsubscribeWebPush();
                if (msg) {
                    msg.textContent = 'Powiadomienia push wyłączone.';
                    msg.className = 'panel-cp-flash panel-cp-flash--ok';
                    msg.hidden = false;
                }
                await refreshPushUi();
            } catch (err) {
                if (msg) {
                    msg.textContent = err.message || 'Nie udało się wyłączyć push.';
                    msg.className = 'panel-cp-flash panel-cp-flash--err';
                    msg.hidden = false;
                }
            } finally {
                pushDisable.disabled = false;
            }
        });

        refreshPushUi();

        emailCb?.addEventListener('change', async () => {
            try {
                const res = await authFetch('account/alerts', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json', ...authHeaders(true) },
                    body: JSON.stringify({ email_alerts_enabled: emailCb.checked }),
                });
                if (msg) {
                    msg.textContent = res.ok ? 'Zapisano ustawienia alertów.' : 'Nie udało się zapisać.';
                    msg.hidden = false;
                }
            } catch (e) {
                console.warn('alerts settings', e);
            }
        });
    }

    function setAvatar(email) {
        if (!panelAvatar || !email) return;
        const letter = String(email).trim().charAt(0).toUpperCase() || '?';
        panelAvatar.textContent = letter;
    }

    function statTile(value, label, extraClass = '') {
        return `<article class="panel-cp-stat ${extraClass}"><span class="panel-cp-stat-val">${value}</span><span class="panel-cp-stat-lbl">${label}</span></article>`;
    }

    async function loadSummary() {
        try {
            const res = await authFetch('account/summary');
            if (!res.ok) return;
            const s = await res.json();
            setAvatar(s.email);
            if (welcome) welcome.textContent = s.email;
            document.getElementById('acc-email').textContent = s.email;
            document.getElementById('acc-since').textContent = formatDate(s.member_since);
            document.getElementById('acc-last').textContent = formatDate(s.last_seen_at);

            const emailCb = document.getElementById('acc-email-alerts');
            if (emailCb && typeof s.email_alerts_enabled === 'boolean') {
                emailCb.checked = s.email_alerts_enabled;
            }

            if (panelStats) {
                panelStats.hidden = false;
                const dealTitle = s.cheapest_game_title
                    ? escapeHtml(s.cheapest_game_title)
                    : '—';
                panelStats.innerHTML = [
                    statTile(s.favorites_count, 'Śledzone'),
                    statTile(s.favorites_with_price, 'Z ceną'),
                    statTile(formatMoney(s.cheapest_price_pln), 'Najtaniej'),
                    `<article class="panel-cp-stat panel-cp-stat--wide"><span class="panel-cp-stat-lbl">Najlepsza okazja</span><span class="panel-cp-stat-deal">${dealTitle}</span></article>`,
                ].join('');
            }
        } catch (e) {
            console.warn('summary', e);
        }
    }

    async function loadFavorites() {
        grid.innerHTML = '<div class="loading-spinner"></div>';
        try {
            const res = await authFetch('favorites');
            if (res.status === 401) { window.location.href = 'login'; return; }
            if (!res.ok) throw new Error('fetch failed');
            favoritesCache = await res.json();
            updateCount();
            renderFavorites(getFilteredSorted());
            loadSummary();
        } catch (e) {
            grid.innerHTML = '<p class="error-message">Nie udało się załadować śledzonych gier.</p>';
        }
    }

    function updateCount() {
        const n = favoritesCache.length;
        if (panelCount) {
            panelCount.textContent = n
                ? `${n} ${n === 1 ? 'gra' : n < 5 ? 'gry' : 'gier'} na liście`
                : 'Brak gier na liście';
        }
    }

    function getFilteredSorted() {
        let list = [...favoritesCache];
        if (onlyPriced?.checked) {
            list = list.filter(g => g.best_price_pln != null);
        }
        const sort = sortSelect?.value || 'newest';
        list.sort((a, b) => {
            if (sort === 'name') return a.title.localeCompare(b.title, 'pl');
            if (sort === 'price-asc') {
                const pa = a.best_price_pln ?? Infinity;
                const pb = b.best_price_pln ?? Infinity;
                return pa - pb;
            }
            if (sort === 'price-desc') {
                const pa = a.best_price_pln ?? -1;
                const pb = b.best_price_pln ?? -1;
                return pb - pa;
            }
            return new Date(b.favorited_at) - new Date(a.favorited_at);
        });
        return list;
    }

    function renderFavorites(games) {
        if (!games.length) {
            grid.innerHTML = `
                <div class="panel-cp-empty">
                    <p class="panel-cp-empty-kicker">pusty stash</p>
                    <h3>Brak śledzonych gier</h3>
                    <p>Dodaj tytuły z katalogu — będziemy trzymać oko na ceny za Ciebie.</p>
                    <a href="./" class="cp-btn">Przeglądaj katalog</a>
                </div>`;
            return;
        }
        grid.innerHTML = '';
        games.forEach(game => {
            const card = document.createElement('article');
            card.className = 'game-card panel-cp-fav-card';
            const price = game.best_price_pln != null
                ? `<span class="card-price">${Number(game.best_price_pln).toFixed(2)} zł</span>`
                : '<span class="card-price empty">Brak w sklepach</span>';
            const shop = game.best_shop_name
                ? `<span class="card-shop">${escapeHtml(game.best_shop_name)}</span>`
                : '';
            const savings = (game.savings_pln != null && game.savings_pct != null && game.savings_pln > 0)
                ? `<span class="card-savings" title="Oszczędzasz vs Steam">−${game.savings_pct}% vs Steam</span>`
                : '';
            const coverSrc = gameCoverSrc(game);
            const alertBadge = game.alert_enabled
                ? '<span class="card-alert-badge">Alert ON</span>'
                : '';
            card.innerHTML = `
                <div class="card-cover">
                    <img src="${coverSrc}" alt="${escapeHtml(game.title)}" loading="lazy">
                </div>
                <div class="card-body">
                    <h3 class="card-title">${escapeHtml(game.title)}</h3>
                    <div class="card-foot"><span class="card-from">Od</span>${price}${shop}${savings}${alertBadge}</div>
                    <p class="card-meta">Dodano ${formatDate(game.favorited_at)}</p>
                    <div class="panel-cp-fav-actions">
                        <button type="button" class="btn-alert panel-cp-alert${game.alert_enabled ? ' active' : ''}" aria-pressed="${game.alert_enabled ? 'true' : 'false'}">${game.alert_enabled ? 'Alert włączony' : 'Alert cenowy'}</button>
                        <button type="button" class="btn-watch active btn-unwatch panel-cp-unwatch">Usuń ze śledzenia</button>
                    </div>
                </div>
            `;
            const img = card.querySelector('img');
            bindCoverFallback(img, game);
            card.querySelector('.card-cover')?.addEventListener('click', () => showGame(game.slug));
            card.querySelector('.card-title')?.addEventListener('click', () => showGame(game.slug));
            card.querySelector('.panel-cp-alert')?.addEventListener('click', async (ev) => {
                ev.stopPropagation();
                const btn = ev.currentTarget;
                await toggleFavoriteAlert(game, btn, card);
            });
            card.querySelector('.btn-unwatch')?.addEventListener('click', async (ev) => {
                ev.stopPropagation();
                const res = await authFetch(`favorites/slug/${encodeURIComponent(game.slug)}`, { method: 'DELETE' });
                if (res.ok) loadFavorites();
            });
            grid.appendChild(card);
        });
    }

    async function toggleFavoriteAlert(game, btn, card) {
        const next = !game.alert_enabled;
        btn.disabled = true;
        try {
            const res = await authFetch(`favorites/slug/${encodeURIComponent(game.slug)}/alert`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json', ...authHeaders(true) },
                body: JSON.stringify({ alert_enabled: next }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Nie udało się zapisać alertu.');
            game.alert_enabled = !!data.alert_enabled;
            const cached = favoritesCache.find((g) => g.slug === game.slug);
            if (cached) cached.alert_enabled = game.alert_enabled;
            btn.classList.toggle('active', game.alert_enabled);
            btn.textContent = game.alert_enabled ? 'Alert włączony' : 'Alert cenowy';
            btn.setAttribute('aria-pressed', game.alert_enabled ? 'true' : 'false');
            const badge = card.querySelector('.card-alert-badge');
            if (game.alert_enabled) {
                if (!badge) {
                    const foot = card.querySelector('.card-foot');
                    if (foot) foot.insertAdjacentHTML('beforeend', '<span class="card-alert-badge">Alert ON</span>');
                }
            } else if (badge) {
                badge.remove();
            }
        } catch (err) {
            const msg = document.getElementById('alerts-msg');
            if (msg) {
                msg.textContent = err.message || 'Błąd alertu.';
                msg.className = 'panel-cp-flash panel-cp-flash--err';
                msg.hidden = false;
            }
        } finally {
            btn.disabled = false;
        }
    }

    const ALL_SHOPS = ['Steam', 'GOG', 'Epic Games', 'Instant Gaming', 'Eneba', 'Kinguin', 'CDKeys', 'G2A', 'Gamivo', 'Fanatical'];

    function renderOffers(offers) {
        const list = document.getElementById('offers-list');
        const priced = (offers || []).filter(o => o?.shop_name && Number(o.price_pln) > 0);
        const byShop = {};
        priced.forEach(o => { byShop[o.shop_name] = o; });
        const bestPrice = priced.length ? Math.min(...priced.map(o => o.price_pln)) : null;

        list.innerHTML = '';
        priced.sort((a, b) => a.price_pln - b.price_pln).forEach(offer => {
            const shopName = offer.shop_name;
            const shopClass = shopName.toLowerCase().replace(/\s+/g, '');
            const row = document.createElement('div');
            row.className = 'offer-row' + (offer.price_pln === bestPrice ? ' cheapest' : '');
            row.innerHTML = `
                <div><span class="offer-shop shop-${shopClass}">${escapeHtml(offer.shop_name)}</span>
                <span class="offer-type">${offer.is_official ? 'Oficjalny sklep' : 'Marketplace kluczy'}</span></div>
                <span class="offer-price">${Number(offer.price_pln).toFixed(2)} zł</span>
                <a href="${offer.affiliate_url}" target="_blank" rel="noopener" class="btn-buy">Kup</a>
            `;
            list.appendChild(row);
        });
    }

    async function showGame(slug) {
        modal.hidden = false;
        document.body.style.overflow = 'hidden';
        document.getElementById('offers-list').innerHTML = '<div class="offers-empty">Ładowanie…</div>';
        try {
            const res = await fetch(api(`games/${slug}`));
            const game = await res.json();
            document.getElementById('modal-title').textContent = game.title;
            document.getElementById('modal-desc').textContent = game.description || 'Brak opisu.';
            const cover = document.getElementById('modal-cover');
            cover.src = gameCoverSrc(game);
            bindCoverFallback(cover, game);
            renderOffers(game.offers);
        } catch {
            document.getElementById('modal-title').textContent = 'Błąd';
        }
    }
});

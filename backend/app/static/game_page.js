/**
 * Full game page interactivity (offers refresh, favorites, alerts, live scan).
 */
(function () {
    const boot = window.__GAME_BOOTSTRAP__ || {};
    const slug = boot.slug;
    if (!slug) return;

    const tt = (k, v) => (typeof t === 'function' ? t(k, v) : k);

    const apiBase = (() => {
        const b = document.querySelector('base');
        const href = b ? b.getAttribute('href') : '/games/';
        return (href || '/games/').replace(/\/?$/, '/') + 'api/';
    })();

    function api(path) {
        return apiBase + path.replace(/^\//, '');
    }

    function shoppingRegion() {
        return window.KupujPLRegion?.getShoppingRegion?.() || 'pl';
    }

    function withRegion(path) {
        const sep = path.includes('?') ? '&' : '?';
        return `${path}${sep}region=${encodeURIComponent(shoppingRegion())}`;
    }

    function filterOffersForRegion(offers) {
        const region = shoppingRegion();
        return (offers || []).filter((o) => {
            if (!o?.shop_name) return false;
            if (region === 'us' && o.shop_name === 'Steam') return false;
            if (region === 'pl' && o.shop_name === 'Steam US') return false;
            const act = String(o.activation_region || 'unknown').toLowerCase();
            if (act === 'unknown') return true;
            if (region === 'us') return act === 'na' || act === 'global';
            return act === 'eu' || act === 'global';
        });
    }

    function activationBadge(offer) {
        const act = String(offer?.activation_region || '').toLowerCase();
        if (act === 'na') return tt('offer.region_na');
        if (act === 'eu') return tt('offer.region_eu');
        if (act === 'global') return tt('offer.region_global');
        return '';
    }

    function authHeaders(json) {
        const h = {};
        const tok = localStorage.getItem('kupujpl_games_token');
        if (tok) h.Authorization = 'Bearer ' + tok;
        if (json) h['Content-Type'] = 'application/json';
        return h;
    }

    function isLoggedIn() {
        return !!localStorage.getItem('kupujpl_games_token');
    }

    async function authFetch(path, opts = {}) {
        const headers = { ...authHeaders(!!opts.body), ...(opts.headers || {}) };
        return fetch(api(path), { ...opts, headers });
    }

    function escapeHtml(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function sleep(ms) {
        return new Promise((r) => setTimeout(r, ms));
    }

    function formatPrice(pln) {
        if (window.KupujPLRegion) return KupujPLRegion.formatPrice(pln);
        return `${Number(pln).toFixed(2)} zł`;
    }

    function trustBadge(o) {
        if (o.is_official) return tt('card.official');
        const m = String(o.trust_label || '').match(/tier\s*([A-C])/i);
        if (m) return tt('offer.marketplace_tier', { tier: m[1].toUpperCase() });
        return tt('card.marketplace');
    }

    function histLowText(apiLabel) {
        const lang = window.I18n?.getLang?.() || 'pl';
        if (lang === 'pl' && apiLabel) return apiLabel;
        return tt('badge.hist_low');
    }

    const offersEl = document.getElementById('gp-offers');
    const btnFav = document.getElementById('btn-favorite');
    const btnAlertToggle = document.getElementById('btn-alert-toggle');
    const alertPanel = document.getElementById('alert-panel');
    const alertTarget = document.getElementById('alert-target');
    const alertShop = document.getElementById('alert-shop-filter');
    const btnAlertSave = document.getElementById('btn-alert-save');
    const btnAlertOff = document.getElementById('btn-alert-off');

    let gameId = null;
    let favorited = false;
    let alertEnabled = false;
    let lastTrackedPath = '';
    let heartbeatTimer = null;
    let offersPollToken = 0;
    let scanStatusEl = null;
    let lastOffers = null;
    let lastGame = null;

    function ensureScanStatus() {
        if (scanStatusEl) return scanStatusEl;
        scanStatusEl = document.getElementById('gp-scan-status');
        if (scanStatusEl) return scanStatusEl;
        scanStatusEl = document.createElement('p');
        scanStatusEl.id = 'gp-scan-status';
        scanStatusEl.className = 'gp-scan-status muted';
        scanStatusEl.hidden = true;
        const title = document.querySelector('.offers-title');
        if (title?.parentNode) {
            title.parentNode.insertBefore(scanStatusEl, title.nextSibling);
        } else {
            offersEl?.parentNode?.insertBefore(scanStatusEl, offersEl);
        }
        return scanStatusEl;
    }

    function setScanning(active) {
        const el = ensureScanStatus();
        if (!el) return;
        if (active) {
            el.hidden = false;
            el.textContent = tt('region.scanning');
        } else {
            el.hidden = true;
            el.textContent = '';
        }
    }

    function trackPageView(path) {
        const normalized = (path || '').trim();
        if (!normalized || normalized === lastTrackedPath) return;
        lastTrackedPath = normalized;
        fetch(api('track-visit'), {
            method: 'POST',
            headers: authHeaders(true),
            body: JSON.stringify({ path: normalized }),
            credentials: 'same-origin',
        }).catch(() => {});
        // Parallel Umami pageview (consent-gated); does not replace track-visit.
        try {
            if (window.KupujPLUmami) window.KupujPLUmami.trackPage();
        } catch (_) { /* ignore */ }
    }

    function sendHeartbeat() {
        if (document.hidden) return;
        fetch(api('track-heartbeat'), {
            method: 'POST',
            headers: authHeaders(true),
            body: JSON.stringify({ path: lastTrackedPath || `/gra/${slug}` }),
            credentials: 'same-origin',
        }).catch(() => {});
    }

    function startHeartbeat() {
        if (heartbeatTimer) return;
        sendHeartbeat();
        heartbeatTimer = setInterval(sendHeartbeat, 30000);
    }

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) sendHeartbeat();
    });

    function bindBuyTracking() {
        offersEl?.querySelectorAll('a.btn-buy').forEach((link) => {
            if (link.dataset.tracked) return;
            link.dataset.tracked = '1';
            const shop =
                link.closest('.offer-row')?.querySelector('.offer-shop strong')?.textContent?.trim() ||
                '';
            link.addEventListener('click', () => {
                trackPageView(`/out/${encodeURIComponent(slug)}/${encodeURIComponent(shop)}`);
            });
        });
    }

    function shopLabel(name) {
        if (name === 'Steam US') {
            const v = tt('shop.steam_us');
            if (v && v !== 'shop.steam_us') return v;
        }
        return name;
    }

    function renderOffers(offers) {
        if (!offersEl) return;
        lastOffers = offers;
        const list = filterOffersForRegion(offers || []).filter((o) => o.in_stock && o.price_pln > 0);
        if (!list.length) {
            offersEl.innerHTML = `<p class="offers-empty" data-i18n="offer.empty">${escapeHtml(tt('offer.empty'))}</p>`;
            return;
        }
        offersEl.innerHTML = list
            .map((o) => {
                const trust = trustBadge(o);
                const kind = o.is_official ? 'official' : 'keyshop';
                const go = api(`go/${o.id}`);
                const priceTxt = formatPrice(o.price_pln);
                const regionBadge = activationBadge(o);
                const regionHtml = regionBadge
                    ? `<span class="badge badge-region">${escapeHtml(regionBadge)}</span>`
                    : '';
                return `<div class="offer-row" data-shop-kind="${kind}">
                    <div class="offer-shop"><strong>${escapeHtml(shopLabel(o.shop_name))}</strong>
                    <span class="badge">${escapeHtml(trust)}</span>${regionHtml}</div>
                    <div class="offer-price">${priceTxt}</div>
                    <a class="btn-buy" href="${escapeHtml(go)}" rel="noopener noreferrer sponsored" target="_blank">${escapeHtml(tt('offer.buy'))}</a>
                </div>`;
            })
            .join('');
        bindBuyTracking();
    }

    function updateFavBtn() {
        if (!btnFav) return;
        btnFav.classList.toggle('active', favorited);
        btnFav.textContent = favorited ? tt('card.watching') : tt('card.watch');
    }

    function updateAlertUi() {
        if (btnAlertToggle) {
            btnAlertToggle.classList.toggle('active', alertEnabled);
            btnAlertToggle.textContent = alertEnabled ? tt('modal.alert_on') : tt('modal.alert');
        }
    }


    function clamp(n, lo, hi) {
        return Math.max(lo, Math.min(hi, n));
    }

    function computeWorthBuy(game) {
        let price = Number(game?.best_price_pln);
        if (!(price > 0) && Array.isArray(game?.offers)) {
            const prices = game.offers.map((o) => Number(o.price_pln)).filter((n) => n > 0);
            if (prices.length) price = Math.min(...prices);
        }
        if (!(price > 0)) return null;
        const histLow = game.lowest_ever_pln != null ? Number(game.lowest_ever_pln) : null;
        const avg30 = game.avg_best_price_30d != null ? Number(game.avg_best_price_30d) : null;
        const steam = game.steam_price_pln != null ? Number(game.steam_price_pln) : null;
        let savingsPct = game.savings_pct != null ? Number(game.savings_pct) : null;
        const atLow = !!game.at_historical_low;

        const parts = [];
        if (histLow && histLow > 0) {
            const ratio = price / histLow;
            let hist = ratio <= 1.01 ? 100 : ratio <= 1.05 ? 88 : ratio <= 1.12 ? 72 : ratio <= 1.25 ? 48 : ratio <= 1.45 ? 22 : 5;
            if (atLow) hist = Math.max(hist, 96);
            parts.push([hist, 0.32]);
        }
        if (avg30 && avg30 > 0) {
            const ratio = price / avg30;
            const avg = ratio <= 0.88 ? 100 : ratio <= 0.95 ? 86 : ratio <= 1.0 ? 72 : ratio <= 1.05 ? 48 : ratio <= 1.12 ? 28 : ratio <= 1.25 ? 12 : 4;
            parts.push([avg, 0.28]);
        }
        if (savingsPct == null && steam && steam > 0) {
            savingsPct = price < steam ? Math.round((1 - price / steam) * 100) : 0;
        }
        if (savingsPct != null) {
            const pct = savingsPct;
            const steamScore = pct >= 55 ? 100 : pct >= 40 ? 88 : pct >= 25 ? 74 : pct >= 15 ? 58 : pct >= 8 ? 40 : pct >= 1 ? 24 : 8;
            parts.push([steamScore, 0.25]);
            parts.push([clamp(pct * 1.35, 0, 100), 0.15]);
        }
        if (!parts.length) return null;
        const tw = parts.reduce((s, x) => s + x[1], 0);
        const score = Math.round(parts.reduce((s, x) => s + x[0] * x[1], 0) / tw);
        let tier, emoji, label, reason;
        if (score >= 75) {
            tier = 'buy'; emoji = '🟢'; label = 'KUP TERAZ';
            if (atLow || (histLow && price <= histLow * 1.02)) reason = 'Cena jest bardzo dobra — blisko historycznego minimum.';
            else if (savingsPct && savingsPct >= 25) reason = `Cena jest bardzo dobra — ok. ${savingsPct}% taniej niż na Steam.`;
            else if (avg30 && price < avg30) reason = 'Cena jest bardzo dobra — poniżej średniej z 30 dni.';
            else reason = 'Cena jest bardzo dobra względem dostępnych sygnałów.';
        } else if (score >= 45) {
            tier = 'maybe'; emoji = '🟡'; label = 'MOŻESZ POCZEKAĆ';
            if (avg30 && price > avg30 * 1.03) reason = 'Cena jest przeciętna — drożej niż średnia z 30 dni.';
            else if (savingsPct != null && savingsPct < 15) reason = 'Różnica vs Steam jest umiarkowana — warto obserwować.';
            else reason = 'Cena jest OK, ale nie rewelacyjna — możesz poczekać na lepszy moment.';
        } else {
            tier = 'wait'; emoji = '🔴'; label = 'POCZEKAJ';
            if (histLow && price > histLow * 1.35) reason = 'Cena jest wysoka względem historycznego minimum.';
            else if (avg30 && price > avg30 * 1.1) reason = 'Cena jest wyraźnie powyżej średniej z 30 dni.';
            else reason = 'Na razie lepiej poczekać — sygnały cenowe są słabe.';
        }
        return { score, tier, emoji, label, reason };
    }

    function updateWorthBuy(game) {
        const answer = document.getElementById('gp-answer');
        if (!answer) return;
        const result = computeWorthBuy(game);
        let el = document.getElementById('gp-worth-buy');
        if (!result) {
            // Keep SSR verdict if live payload cannot recompute yet.
            return;
        }
        if (!el) {
            el = document.createElement('div');
            el.id = 'gp-worth-buy';
            const buy = answer.querySelector('.game-page-answer-buy');
            const row = answer.querySelector('.game-page-answer-row');
            if (row && row.nextSibling) answer.insertBefore(el, row.nextSibling);
            else if (row) row.after(el);
            else answer.prepend(el);
        }
        el.className = `worth-buy is-${result.tier}`;
        el.dataset.score = String(result.score);
        el.dataset.tier = result.tier;
        el.innerHTML = `<p class="worth-buy-kicker" data-i18n="game.worth_title">Czy warto kupić?</p>` +
            `<p class="worth-buy-score"><span class="worth-buy-emoji" aria-hidden="true">${result.emoji}</span> ` +
            `<strong class="worth-buy-points">${result.score}/100</strong>` +
            `<span class="worth-buy-label"> — ${result.label}</span></p>` +
            `<p class="worth-buy-reason"></p>`;
        el.querySelector('.worth-buy-reason').textContent = result.reason;
    }

    function updateSavings(game) {
        const host = document.querySelector('.game-page-head > div');
        let el = document.querySelector('.game-page-savings');
        if (!game?.savings_pln || !game?.savings_pct || !game?.steam_price_pln) {
            if (el) el.remove();
            return;
        }
        const amount = formatPrice(game.savings_pln);
        const steam = formatPrice(game.steam_price_pln);
        const text = tt('offer.savings', {
            amount: String(Number(game.savings_pln).toFixed(2)),
            pct: String(game.savings_pct),
            steam: String(Number(game.steam_price_pln).toFixed(2)),
        });
        // Prefer formatted prices when region FX is active
        const pretty = text
            .replace(String(Number(game.savings_pln).toFixed(2)) + ' zł', amount)
            .replace(String(Number(game.steam_price_pln).toFixed(2)) + ' zł', steam)
            .replace(String(Number(game.savings_pln).toFixed(2)) + ' PLN', amount)
            .replace(String(Number(game.steam_price_pln).toFixed(2)) + ' PLN', steam);
        if (!el && host) {
            el = document.createElement('p');
            el.className = 'game-page-savings';
            host.appendChild(el);
        }
        if (el) el.textContent = pretty;
    }

    function updateHistoryMeta(game) {
        const el = document.getElementById('gp-history-meta');
        if (!el) return;
        if (!game?.lowest_ever_pln) {
            el.textContent = '';
            return;
        }
        const low = formatPrice(game.lowest_ever_pln);
        if (game.avg_best_price_30d) {
            el.textContent = tt('game.history_meta_avg', {
                low,
                avg: formatPrice(game.avg_best_price_30d),
            });
        } else {
            el.textContent = tt('game.history_meta', { low });
        }
    }

    function updateHistBadge(game) {
        const titleEl = document.getElementById('gp-title');
        if (!(game?.at_historical_low || game?.lowest_ever_label)) {
            document.querySelector('.hist-low-badge')?.remove();
            return;
        }
        let badge = document.querySelector('.hist-low-badge');
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'hist-low-badge';
            titleEl?.after(badge);
        }
        badge.textContent = histLowText(game.lowest_ever_label);
    }

    async function loadGame() {
        const res = await fetch(api(withRegion(`games/${encodeURIComponent(slug)}`)));
        if (!res.ok) return;
        const game = await res.json();
        lastGame = game;
        gameId = game.id;
        const titleEl = document.getElementById('gp-title');
        const descEl = document.getElementById('gp-desc');
        const coverEl = document.getElementById('gp-cover');
        if (titleEl) titleEl.textContent = `${game.title}${tt('game.h1_suffix') || ' – gdzie najtaniej?'}`;
        if (descEl) descEl.textContent = game.description || '';
        if (coverEl && game.cover_image) {
            coverEl.src = game.cover_image;
            coverEl.alt = game.title;
        }
        document.title = `${game.title}${tt('game.title_suffix')}`;
        renderOffers(game.offers);
        updateHistBadge(game);
        updateWorthBuy(game);
        updateSavings(game);
        updateHistoryMeta(game);

        let relatedHost = document.getElementById('gp-related');
        if (!relatedHost) {
            relatedHost = document.createElement('div');
            relatedHost.id = 'gp-related';
            relatedHost.className = 'game-page-related';
            const prices = document.querySelector('.game-page-prices');
            const mainCol = document.querySelector('.game-page-main');
            if (prices) prices.after(relatedHost);
            else if (mainCol) mainCol.appendChild(relatedHost);
            else document.querySelector('.game-page-grid')?.after(relatedHost);
        }
        function renderRelatedSection(selector, className, titleKey, items) {
            let sec = relatedHost.querySelector(selector);
            if (!items?.length) {
                if (sec) sec.remove();
                relatedHost.hidden = !relatedHost.querySelector('.game-dlc');
                return;
            }
            if (!sec) {
                sec = document.createElement('section');
                sec.className = className;
                relatedHost.appendChild(sec);
            }
            const title = tt(titleKey);
            const priceTxt = (g) => {
                if (g.best_price_pln == null) return '—';
                return formatPrice(g.best_price_pln);
            };
            sec.innerHTML =
                `<div class="home-section-head"><div>` +
                `<h2 class="home-section-title gp-related-title" data-i18n="${titleKey}">${escapeHtml(title)}</h2>` +
                `</div></div><div class="dlc-row home-section-row">` +
                items
                    .map((g) => {
                        const img = escapeHtml(g.cover_image || '');
                        const name = escapeHtml(g.title || '');
                        return `<a class="dlc-tile game-card game-card-row" href="gra/${encodeURIComponent(g.slug)}">
                            <span class="card-cover"><img src="${img}" alt="${name}" loading="lazy" width="196" height="92"></span>
                            <span class="card-body"><span class="card-title">${name}</span>
                            <span class="card-price">${priceTxt(g)}</span></span></a>`;
                    })
                    .join('') +
                '</div>';
            relatedHost.hidden = false;
            relatedHost.removeAttribute('hidden');
        }

        renderRelatedSection(
            '.game-parent',
            'game-dlc game-parent home-feed-block home-section-block',
            'game.parent_title',
            game.parent_game ? [game.parent_game] : []
        );
        renderRelatedSection(
            '.game-dlc:not(.game-parent)',
            'game-dlc home-feed-block home-section-block',
            'game.dlc_title',
            game.related_dlc
        );

        if (isLoggedIn()) await refreshFavorite();
    }

    function applyLangUi() {
        updateFavBtn();
        updateAlertUi();
        if (lastOffers) renderOffers(lastOffers);
        else {
            // Translate SSR buy/empty if still present
            offersEl?.querySelectorAll('a.btn-buy').forEach((a) => {
                a.textContent = tt('offer.buy');
            });
            const empty = offersEl?.querySelector('.offers-empty');
            if (empty) empty.textContent = tt(empty.getAttribute('data-i18n') || 'offer.empty');
            offersEl?.querySelectorAll('.badge[data-i18n]').forEach((b) => {
                b.textContent = tt(b.getAttribute('data-i18n'));
            });
        }
        if (lastGame) {
            updateHistBadge(lastGame);
            updateSavings(lastGame);
            updateHistoryMeta(lastGame);
            document.querySelectorAll('.gp-related-title[data-i18n]').forEach((el) => {
                el.textContent = tt(el.getAttribute('data-i18n'));
            });
            if (lastGame.title) {
                document.title = `${lastGame.title}${tt('game.title_suffix')}`;
            }
        }
        const footer = document.querySelector('footer .footer-inner p, footer p');
        if (footer) footer.textContent = tt('footer.copy');
        if (!document.getElementById('gp-scan-status')?.hidden) {
            setScanning(true);
        }
    }

    async function requestOffersRefresh() {
        const token = ++offersPollToken;
        try {
            const res = await fetch(api(`games/${encodeURIComponent(slug)}/refresh-offers`), {
                method: 'POST',
            });
            if (!res.ok || token !== offersPollToken) return;
            const data = await res.json();
            if (data.queued) {
                setScanning(true);
                await pollOffers(token);
            }
        } catch (_) {
            /* soft-fail: page still usable */
        } finally {
            if (token === offersPollToken) setScanning(false);
        }
    }

    async function pollOffers(token) {
        const delays = [400, 600, 800, 1000, 1200, 1500, 2000, 2500, 3000, 4000];
        let lastCount = 0;
        let stable = 0;
        for (const delay of delays) {
            await sleep(delay);
            if (token !== offersPollToken) return;
            try {
                const res = await fetch(api(withRegion(`games/${encodeURIComponent(slug)}/offers`)));
                if (!res.ok) continue;
                const offers = await res.json();
                const filtered = filterOffersForRegion(offers);
                renderOffers(filtered);
                const count = filtered.length;
                if (count === lastCount) {
                    stable += 1;
                    if (stable >= 2 && count > 0) break;
                } else {
                    stable = 0;
                    lastCount = count;
                }
            } catch (_) {
                /* ignore poll errors */
            }
        }
        if (token !== offersPollToken) return;
        try {
            const gameRes = await fetch(api(withRegion(`games/${encodeURIComponent(slug)}`)));
            if (gameRes.ok) {
                const game = await gameRes.json();
                lastGame = game;
                renderOffers(game.offers);
                updateSavings(game);
                updateHistoryMeta(game);
                updateHistBadge(game);
            }
        } catch (_) { /* ignore */ }
    }

    async function refreshFavorite() {
        const url = gameId
            ? `favorites/check/${gameId}`
            : `favorites/check/slug/${encodeURIComponent(slug)}`;
        const res = await authFetch(url);
        if (!res.ok) return;
        const data = await res.json();
        favorited = !!data.favorited;
        alertEnabled = !!data.alert_enabled;
        if (data.game_id) gameId = data.game_id;
        if (data.target_price_pln != null && alertTarget) {
            alertTarget.value = data.target_price_pln;
        }
        if (data.alert_shop_filter && alertShop) {
            alertShop.value = data.alert_shop_filter;
        }
        updateFavBtn();
        updateAlertUi();
    }

    btnFav?.addEventListener('click', async () => {
        if (!isLoggedIn()) {
            location.href = 'login';
            return;
        }
        const method = favorited ? 'DELETE' : 'POST';
        const res = await authFetch(`favorites/slug/${encodeURIComponent(slug)}`, { method });
        if (res.ok) {
            favorited = !favorited;
            updateFavBtn();
            if (!favorited) {
                alertEnabled = false;
                alertPanel.hidden = true;
                updateAlertUi();
            } else {
                await refreshFavorite();
            }
        }
    });

    btnAlertToggle?.addEventListener('click', () => {
        if (!isLoggedIn()) {
            location.href = 'login';
            return;
        }
        alertPanel.hidden = !alertPanel.hidden;
    });

    async function saveAlert(enabled) {
        if (!isLoggedIn()) {
            location.href = 'login';
            return;
        }
        if (!favorited) {
            await authFetch(`favorites/slug/${encodeURIComponent(slug)}`, { method: 'POST' });
            favorited = true;
            updateFavBtn();
        }
        const targetRaw = alertTarget?.value;
        const target = targetRaw === '' || targetRaw == null ? null : Number(targetRaw);
        const body = {
            alert_enabled: enabled,
            target_price_pln: enabled && target != null && !Number.isNaN(target) ? target : null,
            alert_shop_filter: alertShop?.value || 'any',
        };
        const res = await authFetch(`favorites/slug/${encodeURIComponent(slug)}/alert`, {
            method: 'PATCH',
            body: JSON.stringify(body),
        });
        if (res.ok) {
            const data = await res.json();
            alertEnabled = !!data.alert_enabled;
            updateAlertUi();
            if (!enabled) alertPanel.hidden = true;
        }
    }

    btnAlertSave?.addEventListener('click', () => saveAlert(true));
    btnAlertOff?.addEventListener('click', () => saveAlert(false));

    trackPageView(`/gra/${encodeURIComponent(slug)}`);
    startHeartbeat();
    bindBuyTracking();

    // Translate SSR Polish defaults ASAP (before/while API load)
    applyLangUi();

    loadGame()
        .then(() => requestOffersRefresh())
        .catch(() => {});

    document.addEventListener('langchange', () => {
        applyLangUi();
    });

    document.addEventListener('regionready', () => {
        fetch(api(withRegion(`games/${encodeURIComponent(slug)}/offers`)))
            .then((r) => (r.ok ? r.json() : null))
            .then((offers) => { if (offers) renderOffers(offers); })
            .catch(() => {});
        if (lastGame) {
            updateSavings(lastGame);
            updateHistoryMeta(lastGame);
        }
    });

    document.addEventListener('shoppingregionchange', () => {
        loadGame().catch(() => {});
    });
})();

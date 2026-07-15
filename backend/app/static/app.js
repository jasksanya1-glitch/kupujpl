function agentDebugLog() { /* debug telemetry removed */ }

window.addEventListener('error', (event) => {
    agentDebugLog('pre-fix', 'B', 'app/static/app.js:window.error', 'Frontend runtime error', {
        message: event.message,
        source: event.filename,
        line: event.lineno,
        column: event.colno,
    });
});

window.addEventListener('unhandledrejection', (event) => {
    agentDebugLog('pre-fix', 'B', 'app/static/app.js:unhandledrejection', 'Frontend unhandled promise rejection', {
        reason: String(event.reason && (event.reason.message || event.reason)),
    });
});
// #endregion

document.addEventListener('DOMContentLoaded', () => {
    const tt = (k, v) => (typeof t === 'function' ? t(k, v) : k);
    const numLocale = () => (window.I18n && I18n.locale()) || 'pl-PL';
    const gamesGrid = document.getElementById('games-grid');
    const searchInput = document.getElementById('search-input');
    const modal = document.getElementById('game-modal');
    const closeModal = document.querySelector('.modal-close');
    const modalOverlay = document.querySelector('.modal-overlay');
    const modalTitle = document.getElementById('modal-title');
    const modalCover = document.getElementById('modal-cover');
    const modalDesc = document.getElementById('modal-desc');
    const offersList = document.getElementById('offers-list');
    const btnFavorite = document.getElementById('btn-favorite');
    const categoriesBar = document.getElementById('categories-bar');
    const gamesMeta = document.getElementById('games-meta');
    const loadMoreBtn = document.getElementById('load-more');
    const catalogStats = document.getElementById('catalog-stats');
    const gamesHeading = document.getElementById('games-heading');
    const gamesSubtitle = document.getElementById('games-subtitle');
    const sortSelect = document.getElementById('sort-select');
    const homeSections = document.getElementById('home-sections');
    const homeSpotlight = document.getElementById('home-spotlight');
    const homeSpotlightRow = document.getElementById('home-spotlight-row');
    const catalogSection = document.getElementById('catalog-section');
    const heroSection = document.getElementById('hero-section');
    const homeHero = document.querySelector('.cp-home-hero');
    const homePromo = document.querySelector('.cp-panel-promo');
    const splitRight = document.getElementById('split-right');
    const heroGamesCount = document.getElementById('hero-games-count');
    const heroCatsCount = document.getElementById('hero-cats-count');
    const offersScan = document.getElementById('offers-scan');
    const offersScanShops = document.getElementById('offers-scan-shops');
    const offersScanCountdown = document.getElementById('offers-scan-countdown');
    const modalSavings = document.getElementById('modal-savings');
    const modalPriceHistory = document.getElementById('modal-price-history');
    const btnAlert = document.getElementById('btn-alert');

    const SCAN_ESTIMATE_SEC = 8;
    const SCAN_POLL_BUFFER_SEC = 4;
    const MIN_SHOPS_TARGET = 4;
    let scanCountdownInterval = null;
    let scanCountdownRemaining = 0;

    const ALL_SHOPS = ['Steam', 'GOG', 'Epic Games', 'Instant Gaming', 'Eneba', 'Kinguin', 'CDKeys', 'G2A', 'Gamivo', 'Fanatical'];
    let ACTIVE_SHOPS = ALL_SHOPS.slice();
    let DISABLED_SHOPS = new Set(['Eneba']);
    let currentGameInTierA = false;
    const SHOP_SHORT = {
        Steam: 'Steam',
        GOG: 'GOG',
        'Epic Games': 'Epic',
        'Instant Gaming': 'IG',
        Eneba: 'Eneba',
        Kinguin: 'Kinguin',
        Gamivo: 'Gamivo',
        Fanatical: 'Fanatical',
        G2A: 'G2A',
    };

    let searchDebounceTimeout = null;
    let gamesFetchController = null;
    let gamesFetchSeq = 0;
    let offersPollToken = 0;
    let modalOffersByShop = {};
    const MODAL_OPEN_MS = 1500;
    let currentGameSlug = null;
    let currentGameId = null;
    let isFavorited = false;
    let alertEnabled = false;
    let currentPage = 1;
    let totalPages = 1;
    let currentCategory = '';
    let currentCategoryName = '';
    let currentQuery = '';
    let currentSort = '';
    let loading = false;
    let bodyOverflowBeforeModal = '';
    const watchedSlugs = new Set();
    const api = (path) => (typeof apiUrl === 'function' ? apiUrl(path) : `api/${path}`);

    // #region agent log
    agentDebugLog('pre-fix', 'B', 'app/static/app.js:DOMContentLoaded', 'Home app DOM readiness', {
        hasGamesGrid: Boolean(gamesGrid),
        hasSearchInput: Boolean(searchInput),
        hasHomeSections: Boolean(homeSections),
        hasCatalogSection: Boolean(catalogSection),
        hasCategoriesBar: Boolean(categoriesBar),
    });
    // #endregion

    let lastTrackedPath = '';
    let trackVisitTimer = null;
    const HEARTBEAT_MS = 30000;
    let heartbeatTimer = null;
    const AGENT_STORAGE_KEY = 'kupujpl_agent';

    function detectClientAgent() {
        try {
            const stored = sessionStorage.getItem(AGENT_STORAGE_KEY);
            if (stored === 'cursor') return 'cursor';
        } catch (_) { /* ignore */ }
        try {
            const agentParam = new URLSearchParams(location.search).get('agent');
            if (agentParam === 'cursor') {
                sessionStorage.setItem(AGENT_STORAGE_KEY, 'cursor');
                return 'cursor';
            }
        } catch (_) { /* ignore */ }
        const ua = navigator.userAgent || '';
        if (/\bCursor\b/i.test(ua)) return 'cursor';
        return null;
    }

    const clientAgent = detectClientAgent();

    function trackingPayload(path) {
        const payload = { path };
        if (clientAgent) payload.client_agent = clientAgent;
        return payload;
    }

    function sendHeartbeat() {
        if (document.hidden) return;
        const headers = typeof authHeaders === 'function' ? authHeaders(true) : { 'Content-Type': 'application/json' };
        const path = lastTrackedPath || (location.pathname.replace(/^\/games/, '') || '/');
        fetch(api('track-heartbeat'), {
            method: 'POST',
            headers,
            body: JSON.stringify(trackingPayload(path)),
            credentials: 'same-origin',
        }).catch(() => {});
    }

    function startSessionHeartbeat() {
        if (heartbeatTimer) return;
        sendHeartbeat();
        heartbeatTimer = setInterval(sendHeartbeat, HEARTBEAT_MS);
    }

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) sendHeartbeat();
    });
    startSessionHeartbeat();

    function trackPageView(path) {
        let normalized = (path || '').trim();
        const params = new URLSearchParams(window.location.search);
        const utmSource = params.get('utm_source');
        const utmMedium = params.get('utm_medium');
        const utmCampaign = params.get('utm_campaign');
        if (utmSource) {
            const sep = normalized.includes('?') ? '&' : '?';
            normalized = `${normalized}${sep}utm_source=${encodeURIComponent(utmSource)}`;
        }
        if (!normalized || normalized === lastTrackedPath) return;
        lastTrackedPath = normalized;
        clearTimeout(trackVisitTimer);
        trackVisitTimer = setTimeout(() => {
            const headers = typeof authHeaders === 'function' ? authHeaders(true) : { 'Content-Type': 'application/json' };
            fetch(api('track-visit'), {
                method: 'POST',
                headers,
                body: JSON.stringify({
                    ...trackingPayload(normalized),
                    utm_source: utmSource,
                    utm_medium: utmMedium,
                    utm_campaign: utmCampaign,
                }),
                credentials: 'same-origin',
            }).catch(() => {});
        }, 400);
    }

    function catalogBasePath() {
        const base = document.querySelector('base')?.getAttribute('href') || '/games/';
        try {
            return new URL(base, location.origin).pathname.replace(/\/?$/, '') + '/';
        } catch {
            return '/games/';
        }
    }

    function setGameUrlParam(slug) {
        const url = new URL(location.href);
        url.searchParams.delete('gra');
        const basePath = catalogBasePath();
        if (slug) {
            url.pathname = `${basePath}gra/${encodeURIComponent(slug)}`.replace(/\/{2,}/g, '/');
        } else {
            url.pathname = basePath;
        }
        history.replaceState(slug ? { gra: slug } : null, '', url.pathname + url.search + url.hash);
    }

    function setBrowseMode(mode) {
        const isHome = mode === 'home';
        if (homeSpotlight) {
            homeSpotlight.hidden = isHome ? homeSpotlightRow?.childElementCount === 0 : true;
        }
        if (homeHero) homeHero.hidden = !isHome;
        if (homePromo) homePromo.hidden = !isHome;
        if (homeSections) homeSections.hidden = !isHome;
        if (heroSection) heroSection.hidden = true;
        if (catalogSection) catalogSection.hidden = isHome;
        if (splitRight) {
            splitRight.classList.toggle('split-right--catalog', !isHome);
            if (!isHome) splitRight.scrollTop = 0;
        }
    }

    function updateCatalogSubtitle() {
        if (!gamesSubtitle) return;
        if (currentQuery) {
            gamesSubtitle.textContent = tt('catalog.search_results');
        } else if (currentCategory) {
            gamesSubtitle.textContent = currentCategoryName || tt('catalog.full');
        } else {
            gamesSubtitle.textContent = tt('catalog.full');
        }
    }

    function scrollToCatalog() {
        if (splitRight) {
            splitRight.scrollTo({ top: 0, behavior: 'smooth' });
        } else if (catalogSection) {
            catalogSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    function showHomeView() {
        currentCategory = '';
        currentQuery = '';
        searchInput.value = '';
        setBrowseMode('home');
        categoriesBar.querySelectorAll('.cat').forEach(el => {
            el.classList.toggle('active', el.dataset.slug === '');
        });
        trackPageView('/view/home');
    }

    function showCatalogView() {
        setBrowseMode('catalog');
    }

    function showAllGamesCatalog() {
        currentCategory = '';
        currentCategoryName = '';
        currentQuery = '';
        searchInput.value = '';
        showCatalogView();
        gamesHeading.textContent = tt('catalog.all_games');
        updateCatalogSubtitle();
        categoriesBar.querySelectorAll('.cat').forEach(el => {
            el.classList.toggle('active', el.dataset.slug === '');
        });
        trackPageView('/view/catalog');
        fetchGames(1, false);
    }

    function openModal() {
        bodyOverflowBeforeModal = document.body.style.overflow || '';
        modal.hidden = false;
        document.body.style.overflow = 'hidden';
    }

    function closeModalFn() {
        offersPollToken += 1;
        modal.hidden = true;
        modal.classList.remove('modal--loading', 'modal--scanning', 'modal--opening');
        setOffersScanning(false);
        document.body.style.overflow = bodyOverflowBeforeModal;
        currentGameSlug = null;
        setGameUrlParam(null);
        document.title = tt('title.home');
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    function updateWatchButton(btn, active) {
        if (!btn) return;
        btn.classList.toggle('active', active);
        btn.textContent = active ? tt('card.watching') : tt('card.watch');
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    }

    async function loadWatchedSlugs() {
        try {
            const res = await authFetch('favorites');
            if (!res.ok) return;
            const items = await res.json();
            watchedSlugs.clear();
            items.forEach(g => watchedSlugs.add(g.slug));
        } catch (e) {
            console.warn('watched slugs', e);
        }
    }

    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            clearTimeout(searchDebounceTimeout);
            runSearch(searchInput.value.trim());
        }
    });

    function runSearch(query) {
        currentQuery = query;
        if (currentQuery) {
            // Search combines with any active genre filter (backend supports both).
            showCatalogView();
            gamesHeading.textContent = tt('catalog.results', { q: currentQuery });
            updateCatalogSubtitle();
            scrollToCatalog();
            trackPageView(`/szukaj?q=${encodeURIComponent(currentQuery).slice(0, 120)}`);
            fetchGames(1, false);
        } else if (!currentCategory) {
            showHomeView();
        } else {
            gamesHeading.textContent = currentCategoryName || tt('catalog.all_games');
            updateCatalogSubtitle();
            fetchGames(1, false);
        }
    }

    async function loadShopConfig() {
        try {
            const res = await fetch(api('shop-config'));
            if (!res.ok) return;
            const data = await res.json();
            if (Array.isArray(data.display_shops) && data.display_shops.length) {
                ACTIVE_SHOPS = data.display_shops;
            } else if (Array.isArray(data.active_shops) && data.active_shops.length) {
                ACTIVE_SHOPS = data.expected_shops?.length ? data.expected_shops : data.active_shops;
            }
            const scanOff = data.disabled_scan_shops || data.disabled_shops;
            if (Array.isArray(scanOff)) {
                DISABLED_SHOPS = new Set(scanOff);
            }
            initOffersScanShops();
        } catch (e) {
            console.warn('shop-config', e);
        }
    }

    loadShopConfig();

    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchDebounceTimeout);
        searchDebounceTimeout = setTimeout(() => runSearch(e.target.value.trim()), 250);
    });

    sortSelect?.addEventListener('change', (e) => {
        currentSort = e.target.value || '';
        if (currentQuery || currentCategory) {
            fetchGames(1, false);
        } else {
            showAllGamesCatalog();
        }
    });

    closeModal?.addEventListener('click', closeModalFn);
    modalOverlay?.addEventListener('click', closeModalFn);
    btnFavorite?.addEventListener('click', () => toggleWatch(currentGameSlug, btnFavorite));
    loadMoreBtn?.addEventListener('click', () => {
        if (currentPage < totalPages) fetchGames(currentPage + 1, true);
    });

    async function loadHomeSections() {
        try {
            const res = await fetch(api('home'));
            if (!res.ok) throw new Error('home failed');
            const data = await res.json();
            renderHomeSpotlight(data.spotlight || []);
            renderHomeSections(data.sections || []);
            trackPageView('/view/home');
        } catch (e) {
            console.warn('home sections', e);
            homeSections.innerHTML = `<p class="no-results">${tt('home.load_fail')}</p>`;
        }
    }

    function renderHomeSpotlight(games) {
        if (!homeSpotlight || !homeSpotlightRow) return;
        if (!games.length) {
            homeSpotlight.hidden = true;
            homeSpotlightRow.innerHTML = '';
            return;
        }
        homeSpotlight.hidden = false;
        homeSpotlightRow.innerHTML = games.map(game => {
            const hasPrice = game.best_price_pln != null;
            const priceHtml = hasPrice
                ? `<span class="cp-spotlight-price">${Number(game.best_price_pln).toFixed(2)} zł</span>`
                : `<span class="cp-spotlight-price cp-spotlight-price--empty">${tt('card.check_price')}</span>`;
            const coverSrc = gameCoverSrc(game);
            const gameUrl = `gra/${encodeURIComponent(game.slug)}`;
            const savingsHtml = cardSavingsHtml(game);
            return `<a href="${gameUrl}" class="cp-spotlight-tile" data-slug="${escapeHtml(game.slug)}">
                <span class="cp-spotlight-cover"><img src="${escapeHtml(coverSrc)}" alt="${escapeHtml(game.title)}" loading="lazy"></span>
                <span class="cp-spotlight-meta">
                    <span class="cp-spotlight-name">${escapeHtml(game.title)}</span>
                    ${priceHtml}
                    ${savingsHtml}
                </span>
            </a>`;
        }).join('');
        homeSpotlightRow.querySelectorAll('.cp-spotlight-tile').forEach(tile => {
            const slug = tile.dataset.slug;
            const game = games.find(g => g.slug === slug);
            tile.addEventListener('click', (ev) => {
                if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button === 1) return;
                ev.preventDefault();
                showGameDetails(slug, game);
            });
            const img = tile.querySelector('img');
            if (img && game) bindCoverFallback(img, game);
        });
    }

    function renderHomeSections(sections) {
        if (!sections.length) {
            homeSections.innerHTML = `<p class="no-results">${tt('home.loading')}</p>`;
            return;
        }
        homeSections.innerHTML = '';
        sections.forEach(section => {
            const block = document.createElement('article');
            block.className = 'home-section-block';
            block.innerHTML = `
                <div class="home-section-head">
                    <div>
                        <h2 class="home-section-title">${section.name}</h2>
                        <p class="home-section-sub">${section.subtitle || ''}</p>
                    </div>
                    ${section.slug !== 'top' ? `<button type="button" class="btn-see-more" data-slug="${section.slug}">${tt('home.see_more')}</button>` : ''}
                </div>
                <div class="home-section-row"></div>
            `;
            const row = block.querySelector('.home-section-row');
            section.games.forEach((game, idx) => {
                row.appendChild(buildGameCard(game, section.slug === 'top' && idx < 3 ? idx + 1 : 0));
            });
            const moreBtn = block.querySelector('.btn-see-more');
            if (moreBtn) {
                const catSlug = section.catalog_slug || section.slug;
                moreBtn.addEventListener('click', () => {
                    selectCategory(catSlug, section.name.replace(/^🔥\s*/, ''), true);
                });
            }
            homeSections.appendChild(block);
        });
    }

    function formatNum(n) {
        if (n == null) return '—';
        if (n >= 1000) return `${Math.round(n / 1000)}k+`;
        return String(n);
    }

    function formatCount(n) {
        if (n == null) return '—';
        return new Intl.NumberFormat(numLocale()).format(n);
    }

    function rankClass(rank) {
        if (rank === 1) return '';
        if (rank === 2) return 'silver';
        if (rank === 3) return 'bronze';
        return '';
    }

    function buildGameCard(game, rank) {
        const card = document.createElement('article');
        card.className = rank === false ? 'game-card' : 'game-card game-card-row';
        card.dataset.slug = game.slug;

        const hasPrice = game.best_price_pln != null;
        const priceHtml = hasPrice
            ? `<span class="card-price">${Number(game.best_price_pln).toFixed(2)} zł</span>`
            : `<span class="card-price empty">${tt('card.check_price')}</span>`;
        const tagHtml = hasPrice && game.best_price_is_official
            ? `<span class="card-tag">${tt('card.official')}</span>`
            : '';
        const savingsHtml = cardSavingsHtml(game);
        const historyLabel = game.lowest_ever_label
            ? `<span class="card-history-label">${escapeHtml(game.lowest_ever_label)}</span>`
            : '';
        const watched = watchedSlugs.has(game.slug);

        const coverSrc = gameCoverSrc(game);
        const gameUrl = `gra/${encodeURIComponent(game.slug)}`;
        card.innerHTML = `
            ${rank ? `<span class="card-rank ${rankClass(rank)}">${rank}</span>` : ''}
            <div class="card-cover">
                <a class="card-cover-link" href="${gameUrl}" aria-label="${escapeHtml(game.title)} — ${tt('card.compare_prices')}">
                    <img src="${coverSrc}" alt="${escapeHtml(game.title)}" loading="lazy">
                </a>
                <button type="button" class="btn-watch btn-watch-card ${watched ? 'active' : ''}" data-slug="${game.slug}" aria-pressed="${watched ? 'true' : 'false'}">${watched ? tt('card.watching') : tt('card.watch')}</button>
            </div>
            <div class="card-body">
                <h3 class="card-title"><a class="card-title-link" href="${gameUrl}">${escapeHtml(game.title)}</a></h3>
                <div class="card-foot">
                    <span class="card-from">${tt('card.from')}</span>
                    ${priceHtml}
                    ${savingsHtml}
                    ${historyLabel}
                    ${tagHtml}
                </div>
            </div>
        `;
        const img = card.querySelector('img');
        bindCoverFallback(img, game);
        card.querySelector('.btn-watch-card')?.addEventListener('click', (ev) => {
            ev.stopPropagation();
            toggleWatch(game.slug, ev.currentTarget);
        });
        card.querySelectorAll('.card-title-link, .card-cover-link').forEach((link) => {
            link.addEventListener('click', (ev) => {
                if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button === 1) return;
                ev.preventDefault();
                ev.stopPropagation();
                showGameDetails(game.slug, game);
            });
        });
        card.addEventListener('click', () => {
            // #region agent log
            agentDebugLog('prices-pre-fix', 'P1,P2', 'app/static/app.js:buildGameCard.click', 'Game card opened', {
                slug: game.slug,
                title: game.title,
                bestShopName: game.best_shop_name,
                bestPricePln: game.best_price_pln,
                offersUpdatedAt: game.offers_updated_at,
            });
            // #endregion
            showGameDetails(game.slug, game);
        });
        return card;
    }

    const CURATED_CATEGORIES = [
        { slug: 'nowe-gry', labelKey: 'cat.new_games', nameKey: 'cat.new_games' },
        { slug: 'top-sprzedaz', labelKey: 'cat.top_sales', nameKey: 'cat.top_sales' },
    ];

    function appendCategoryButton(slug, label, name) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'cat cat-curated';
        btn.dataset.slug = slug;
        btn.textContent = label;
        btn.addEventListener('click', () => selectCategory(slug, name, true));
        categoriesBar.appendChild(btn);
    }

    async function loadCategories() {
        CURATED_CATEGORIES.forEach(c => {
            const label = (c.slug === 'nowe-gry' ? '🆕 ' : '🏆 ') + tt(c.labelKey);
            appendCategoryButton(c.slug, label, tt(c.nameKey));
        });
        try {
            const res = await fetch(api('categories?kind=genre'));
            if (!res.ok) return;
            const cats = await res.json();
            const curatedSlugs = new Set(CURATED_CATEGORIES.map(c => c.slug));
            cats.filter(c => c.game_count > 0 && !curatedSlugs.has(c.slug)).forEach(cat => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'cat';
                btn.dataset.slug = cat.slug;
                btn.textContent = cat.name;
                btn.addEventListener('click', () => selectCategory(cat.slug, cat.name, true));
                categoriesBar.appendChild(btn);
            });
        } catch (e) {
            console.warn('categories', e);
        }
    }

    async function loadCatalogStats() {
        try {
            const res = await fetch(api('catalog/status'));
            if (!res.ok) return;
            const s = await res.json();
            catalogStats.textContent = tt('catalog.games_count', { n: formatCount(s.games_total) });
            if (heroGamesCount) heroGamesCount.textContent = formatNum(s.games_total);
        } catch (e) {
            console.warn(e);
        }
    }

    function selectCategory(slug, name, fromChip) {
        if (!slug) {
            showAllGamesCatalog();
            return;
        }
        currentCategory = slug;
        currentCategoryName = name;
        // Keep any active search query so genre + search combine.
        showCatalogView();
        gamesHeading.textContent = currentQuery ? tt('catalog.results', { q: currentQuery }) : name;
        updateCatalogSubtitle();
        scrollToCatalog();
        categoriesBar.querySelectorAll('.cat').forEach(el => {
            el.classList.toggle('active', el.dataset.slug === slug);
        });
        trackPageView(`/kategoria/${encodeURIComponent(slug)}`);
        fetchGames(1, false);
    }

    async function fetchGames(page, append) {
        if (append && loading) return;

        const seq = ++gamesFetchSeq;
        const querySnapshot = currentQuery;
        const categorySnapshot = currentCategory;

        if (!append) {
            gamesFetchController?.abort();
            gamesFetchController = new AbortController();
            gamesGrid.innerHTML = '<div class="loading-spinner"></div>';
            currentPage = page;
        } else {
            loadMoreBtn.disabled = true;
            loadMoreBtn.textContent = tt('catalog.loading');
        }
        loading = true;

        try {
            const params = new URLSearchParams({ page: String(page), limit: '48' });
            if (querySnapshot) params.set('q', querySnapshot);
            if (categorySnapshot) params.set('category', categorySnapshot);
            if (currentSort) params.set('sort', currentSort);

            const response = await fetch(`${api('games')}?${params}`, {
                signal: append ? undefined : gamesFetchController?.signal,
            });
            if (seq !== gamesFetchSeq) return;
            if (!response.ok) throw new Error('Failed to fetch games');
            const data = await response.json();
            if (seq !== gamesFetchSeq) return;
            if (querySnapshot !== currentQuery || categorySnapshot !== currentCategory) return;

            currentPage = data.page;
            totalPages = data.pages;
            renderGamesGrid(data.items, append);
            gamesMeta.textContent = tt('catalog.page', { page: data.page, pages: data.pages, total: data.total });
            loadMoreBtn.hidden = data.page >= data.pages;
            loadMoreBtn.disabled = false;
            loadMoreBtn.textContent = tt('catalog.load_more');
        } catch (error) {
            if (error.name === 'AbortError' || seq !== gamesFetchSeq) return;
            console.error('Error fetching games:', error);
            if (!append) {
                gamesGrid.innerHTML = `<p class="error-message">${tt('grid.error')}</p>`;
            }
        } finally {
            if (seq === gamesFetchSeq) loading = false;
        }
    }

    function initOffersScanShops() {
        updateOffersScanShops();
    }

    function isValidOfferPrice(price) {
        const n = Number(price);
        return Number.isFinite(n) && n > 0;
    }

    function hasShopOffer(shopName) {
        const o = modalOffersByShop[shopName];
        return Boolean(o && isValidOfferPrice(o.price_pln));
    }

    function pricedModalOffers() {
        return Object.values(modalOffersByShop).filter(
            o => o?.shop_name && isValidOfferPrice(o.price_pln),
        );
    }

    const NO_COMMISSION_SHOPS = new Set(['Steam', 'Epic Games']);

    function steamPriceForModal() {
        const steam = modalOffersByShop.Steam;
        return steam && isValidOfferPrice(steam.price_pln) ? Number(steam.price_pln) : null;
    }

    function offerEligibleForCta(offer, steamPrice) {
        if (!offer?.shop_name || !isValidOfferPrice(offer.price_pln)) return false;
        if (offer.low_confidence) return false;
        if (!offer.is_official) {
            const conf = offer.match_confidence;
            if (conf != null && conf < 0.55) return false;
        }
        const price = Number(offer.price_pln);
        if (steamPrice != null && steamPrice >= 5 && offer.shop_name !== 'Steam') {
            if (price / steamPrice < 0.12) return false;
        }
        if (steamPrice != null && steamPrice >= 25 && price <= 3 && !offer.is_official) return false;
        return true;
    }

    function eligibleModalOffers() {
        const steamPrice = steamPriceForModal();
        return pricedModalOffers().filter(o => offerEligibleForCta(o, steamPrice));
    }

    function offerGoUrl(offer) {
        if (!offer?.id) return offer?.affiliate_url || '#';
        return api(`go/${offer.id}`);
    }

    function formatPln(price) {
        return `${Number(price).toFixed(2)} zł`;
    }

    function cardSavingsHtml(game) {
        const savings = game?.savings_pln;
        const pct = game?.savings_pct;
        if (savings == null || pct == null || Number(savings) <= 0) return '';
        const title = tt('card.savings_title', {
            amount: formatPln(savings),
            steam: formatPln(game.steam_price_pln),
        });
        const label = tt('card.vs_steam', { pct });
        return `<span class="card-savings" title="${escapeHtml(title)}">${escapeHtml(label)}</span>`;
    }

    function getCheapestOffer() {
        const eligible = eligibleModalOffers();
        if (!eligible.length) return null;
        return eligible.reduce((best, offer) => (
            Number(offer.price_pln) < Number(best.price_pln) ? offer : best
        ));
    }

    function getCtaOffer() {
        const monetized = eligibleModalOffers().filter(o => !NO_COMMISSION_SHOPS.has(o.shop_name));
        if (!monetized.length) return null;
        return monetized.reduce((best, offer) => (
            Number(offer.price_pln) < Number(best.price_pln) ? offer : best
        ));
    }

    function computeSteamSavings() {
        const steam = modalOffersByShop.Steam;
        const cheapest = getCtaOffer();
        if (!steam || !cheapest || !isValidOfferPrice(steam.price_pln)) return null;

        const steamPrice = Number(steam.price_pln);
        const bestPrice = Number(cheapest.price_pln);
        if (!Number.isFinite(steamPrice) || !Number.isFinite(bestPrice) || bestPrice >= steamPrice) {
            return null;
        }

        const savings = steamPrice - bestPrice;
        if (savings < 0.01) return null;

        return {
            steamPrice,
            bestPrice,
            savings,
            pct: Math.round((savings / steamPrice) * 100),
            cheapest,
        };
    }

    function attachOfferBuyTracking(link, offer) {
        link?.addEventListener('click', () => {
            trackPageView(`/out/${encodeURIComponent(currentGameSlug || '')}/${encodeURIComponent(offer?.shop_name || '')}`);
        });
    }

    function renderModalSavings() {
        if (!modalSavings) return;

        const savings = computeSteamSavings();
        if (!savings) {
            modalSavings.hidden = true;
            modalSavings.innerHTML = '';
            return;
        }

        const { steamPrice, bestPrice, savings: amount, pct, cheapest } = savings;
        modalSavings.hidden = false;
        modalSavings.innerHTML = `
            <p class="modal-savings-kicker">${tt('modal.savings_kicker')}</p>
            <p class="modal-savings-amount">${tt('modal.savings_amount', { amount: formatPln(amount), pct })}</p>
            <p class="modal-savings-detail">${tt('modal.savings_detail', { steam: formatPln(steamPrice), best: formatPln(bestPrice), shop: escapeHtml(cheapest.shop_name) })}</p>
            <a href="${offerGoUrl(cheapest)}" target="_blank" rel="noopener noreferrer nofollow sponsored" class="modal-savings-cta btn-buy">${tt('modal.savings_cta', { price: formatPln(bestPrice) })}</a>
        `;
        attachOfferBuyTracking(modalSavings.querySelector('.modal-savings-cta'), cheapest);
    }

    function offerRefundNote(offer) {
        const lang = (document.documentElement.lang || 'pl').toLowerCase();
        if (lang.startsWith('uk')) {
            return offer.refund_note_uk || offer.refund_note_pl || '';
        }
        if (lang.startsWith('en')) {
            return offer.refund_note_pl || '';
        }
        return offer.refund_note_pl || '';
    }

    function offerRefundHtml(offer) {
        const note = offerRefundNote(offer);
        if (!note) return '';
        const policyLink = offer.refund_policy_url
            ? `<a class="offer-refund-policy-link" href="${escapeHtml(offer.refund_policy_url)}" target="_blank" rel="noopener noreferrer">${tt('offer.refund_shop_link')}</a>`
            : '';
        return `<details class="offer-refund-details">
            <summary class="offer-refund-toggle" title="${escapeHtml(tt('offer.refund_toggle_hint'))}">${tt('offer.refund')}</summary>
            <div class="offer-refund-panel">
                <p class="offer-refund-kupujpl__kicker">${tt('offer.refund_kicker')}</p>
                <p class="offer-refund-panel__text">${escapeHtml(note)}</p>
                ${policyLink ? `<p class="offer-refund-panel__foot">${policyLink}</p>` : ''}
                <p class="offer-refund-panel__disclaimer">${tt('offer.refund_disclaimer')}</p>
            </div>
        </details>`;
    }

    function shopsForOfferList() {
        const priced = new Set(pricedModalOffers().map(o => o.shop_name));
        const ordered = ACTIVE_SHOPS.filter(name => priced.has(name));
        const extra = [...priced].filter(name => !ACTIVE_SHOPS.includes(name));
        return [...ordered, ...extra];
    }

    function updateScanCountdownDisplay() {
        if (!offersScanCountdown) return;
        if (scanCountdownRemaining > 0) {
            offersScanCountdown.textContent = tt('modal.scan_eta', { s: scanCountdownRemaining });
        } else {
            offersScanCountdown.textContent = tt('modal.scan_finishing');
        }
    }

    function startScanCountdown() {
        stopScanCountdown();
        scanCountdownRemaining = SCAN_ESTIMATE_SEC;
        updateScanCountdownDisplay();
        scanCountdownInterval = setInterval(() => {
            scanCountdownRemaining -= 1;
            updateScanCountdownDisplay();
        }, 1000);
    }

    function stopScanCountdown() {
        if (scanCountdownInterval) {
            clearInterval(scanCountdownInterval);
            scanCountdownInterval = null;
        }
        if (offersScanCountdown) offersScanCountdown.textContent = '';
    }

    function setOffersScanning(active) {
        if (!offersScan) return;
        const wasActive = offersScan.classList.contains('is-active');
        offersScan.classList.toggle('is-active', active);
        offersScan.setAttribute('aria-hidden', active ? 'false' : 'true');
        modal?.classList.toggle('modal--scanning', active);
        if (active && !wasActive) startScanCountdown();
        if (!active && wasActive) stopScanCountdown();
    }

    function updateOffersScanShops() {
        if (!offersScanShops) return;
        const found = shopsForOfferList();
        offersScanShops.innerHTML = found.map((name, i) => {
            const cls = name.toLowerCase().replace(/\s+/g, '');
            return `<span class="offers-scan-shop is-found shop-${cls}" data-shop="${name}" style="--i:${i}">${SHOP_SHORT[name] || name}</span>`;
        }).join('');
    }

    function resetModalOffers() {
        modalOffersByShop = {};
    }

    function mergeModalOffers(offers) {
        for (const o of offers || []) {
            if (!o?.shop_name || !isValidOfferPrice(o.price_pln)) continue;
            const prev = modalOffersByShop[o.shop_name];
            if (!prev) {
                modalOffersByShop[o.shop_name] = o;
                continue;
            }
            const prevTs = prev.updated_at ? new Date(prev.updated_at).getTime() : 0;
            const nextTs = o.updated_at ? new Date(o.updated_at).getTime() : 0;
            if (nextTs >= prevTs || o.price_pln !== prev.price_pln) {
                modalOffersByShop[o.shop_name] = o;
            }
        }
    }

    async function requestOffersRefresh(slug, force = false) {
        const token = offersPollToken;
        if (force) {
            setOffersScanning(true);
            updateOffersScanShops();
        }
        try {
            const url = force
                ? api(`games/${encodeURIComponent(slug)}/refresh-offers?force=true`)
                : api(`games/${encodeURIComponent(slug)}/refresh-offers`);
            const res = await fetch(url, { method: 'POST' });
            if (!res.ok || token !== offersPollToken || modal.hidden) return null;
            const data = await res.json();
            if (data.queued) {
                if (!force) {
                    setOffersScanning(true);
                    updateOffersScanShops();
                }
                pollOffers(slug, token, { queued: true });
            } else if (force) {
                setOffersScanning(false);
            }
            return data;
        } catch (e) {
            console.warn('refresh offers', e);
            return null;
        }
    }

    function showGameDetails(slug, preview = null) {
        resetModalOffers();
        offersPollToken += 1;
        const token = offersPollToken;

        openModal();
        modal.classList.add('modal--opening');
        setOffersScanning(false);
        updateOffersScanShops();
        if (modalSavings) {
            modalSavings.hidden = true;
            modalSavings.innerHTML = '';
        }
        if (modalPriceHistory) {
            modalPriceHistory.hidden = true;
            modalPriceHistory.innerHTML = '';
        }
        if (btnAlert) btnAlert.hidden = true;

        currentGameId = null;
        currentGameSlug = slug;
        btnFavorite.hidden = true;
        setGameUrlParam(slug);
        trackPageView(`/gra/${encodeURIComponent(slug)}`);

        if (preview?.title) {
            modalTitle.textContent = preview.title;
            modalCover.src = gameCoverSrc(preview);
            modalCover.alt = preview.title;
            bindCoverFallback(modalCover, preview);
            modalDesc.textContent = tt('modal.loading_desc');
            modalDesc.classList.add('modal-desc--pending');
            modal.classList.remove('modal--loading');
            renderOffers([], false);
        } else {
            modal.classList.add('modal--loading');
            modalTitle.textContent = tt('modal.loading');
            modalDesc.textContent = '';
            modalDesc.classList.remove('modal-desc--pending');
            modalCover.src = '';
            offersList.innerHTML = '';
        }

        const animDone = sleep(MODAL_OPEN_MS).then(() => {
            if (token === offersPollToken) {
                modal.classList.remove('modal--opening');
            }
        });

        fetch(api(`games/${encodeURIComponent(slug)}`))
            .then(response => {
                if (!response.ok) throw new Error('Failed to fetch game details');
                return response.json();
            })
            .then(async game => {
                if (token !== offersPollToken || modal.hidden) return;

                currentGameId = game.id;
                currentGameSlug = game.slug;
                currentGameInTierA = Boolean(game.in_tier_a_daily_scan);
                modalTitle.textContent = game.title;
                document.title = `${game.title} — KupujPL Gry`;
                modalDesc.textContent = game.description || tt('modal.no_desc');
                modalDesc.classList.remove('modal-desc--pending');
                modalCover.src = gameCoverSrc(game);
                modalCover.alt = game.title;
                bindCoverFallback(modalCover, game);
                modal.classList.remove('modal--loading');

                mergeModalOffers(game.offers);
                // #region agent log
                agentDebugLog('prices-pre-fix', 'P2,P3,P5', 'app/static/app.js:showGameDetails.loaded', 'Game details offers loaded', {
                    slug: game.slug,
                    title: game.title,
                    inStockShopCount: game.in_stock_shop_count,
                    offersUpdatedAt: game.offers_updated_at,
                    offers: (game.offers || []).map(o => ({
                        shopName: o.shop_name,
                        pricePln: o.price_pln,
                        originalPricePln: o.original_price_pln,
                        updatedAt: o.updated_at,
                        lowConfidence: o.low_confidence,
                        matchConfidence: o.match_confidence,
                    })),
                });
                // #endregion
                renderOffers(game.offers, false);

                if (btnFavorite) {
                    btnFavorite.hidden = false;
                    if (isLoggedIn()) {
                        refreshFavoriteState();
                    } else {
                        updateWatchButton(btnFavorite, watchedSlugs.has(game.slug));
                        updateAlertButton(false);
                    }
                }
                loadPriceHistory(game.slug);

                return animDone;
            })
            .catch(error => {
                if (token !== offersPollToken || modal.hidden) return;
                console.error('Error fetching game details:', error);
                modal.classList.remove('modal--loading', 'modal--opening');
                modalDesc.classList.remove('modal-desc--pending');
                setOffersScanning(false);
                modalTitle.textContent = preview?.title || tt('modal.error');
                modalDesc.textContent = tt('modal.error_load');
                offersList.innerHTML = `<div class="offers-empty">${tt('modal.offers_error')}</div>`;
            });
    }

    async function pollOffers(slug, token, options = {}) {
        if (!options.queued) return;

        let stableRounds = 0;
        const pollStartedAt = Date.now();
        const minPollMs = (SCAN_ESTIMATE_SEC + SCAN_POLL_BUFFER_SEC) * 1000;
        const pollDelays = [400, 600, 800, 1000, 1200, 1500, 2000, 2500, 3000, 3500, 4000, 5000];

        for (let i = 0; i < pollDelays.length; i++) {
            await sleep(pollDelays[i]);
            if (token !== offersPollToken || modal.hidden) return;
            try {
                const pollSlug = currentGameSlug || slug;
                const res = await fetch(api(`games/${pollSlug}/offers`));
                if (!res.ok) continue;
                const offers = await res.json();
                const before = Object.keys(modalOffersByShop).length;
                mergeModalOffers(offers);
                const after = Object.keys(modalOffersByShop).length;
                const stillMissing = ACTIVE_SHOPS.some(
                    name => !hasShopOffer(name) && !DISABLED_SHOPS.has(name)
                );
                const elapsed = Date.now() - pollStartedAt;
                const scanLikelyDone = elapsed >= minPollMs;
                renderOffers(offers, !scanLikelyDone && stillMissing);
                if (after >= MIN_SHOPS_TARGET && scanLikelyDone) break;
                if (!stillMissing && after > 0) break;
                if (after === before) {
                    stableRounds += 1;
                    if (stableRounds >= 2 && scanLikelyDone) break;
                } else {
                    stableRounds = 0;
                }
            } catch (e) {
                console.warn('poll offers', e);
            }
        }

        if (token !== offersPollToken || modal.hidden) return;

        const elapsed = Date.now() - pollStartedAt;
        if (elapsed < minPollMs) {
            await sleep(minPollMs - elapsed);
        }
        if (token !== offersPollToken || modal.hidden) return;

        try {
            const pollSlug = currentGameSlug || slug;
            const res = await fetch(api(`games/${pollSlug}/offers`));
            if (res.ok) mergeModalOffers(await res.json());
        } catch (e) {
            console.warn('poll offers final', e);
        }

        if (token === offersPollToken && !modal.hidden) {
            renderOffers([], false);
            setOffersScanning(false);
            try {
                const pollSlug = currentGameSlug || slug;
                const gameRes = await fetch(api(`games/${pollSlug}`));
                if (gameRes.ok) {
                    const game = await gameRes.json();
                    mergeModalOffers(game.offers);
                }
            } catch (e) {
                console.warn('poll final game', e);
            }
        }
    }

    function updateAlertButton(enabled) {
        if (!btnAlert) return;
        btnAlert.hidden = !isLoggedIn() || !isFavorited;
        btnAlert.classList.toggle('active', enabled);
        btnAlert.textContent = enabled ? tt('modal.alert_on') : tt('modal.alert');
        btnAlert.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    }

    async function togglePriceAlert() {
        if (!currentGameSlug || !isLoggedIn()) {
            window.location.href = 'login';
            return;
        }
        if (!isFavorited) {
            await toggleWatch(currentGameSlug, btnFavorite);
        }
        const next = !alertEnabled;
        const res = await authFetch(`favorites/slug/${encodeURIComponent(currentGameSlug)}/alert`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...authHeaders(true) },
            body: JSON.stringify({ alert_enabled: next }),
        });
        if (res.ok) {
            const data = await res.json();
            alertEnabled = !!data.alert_enabled;
            updateAlertButton(alertEnabled);
        }
    }

    async function loadPriceHistory(slug) {
        if (!modalPriceHistory || !slug) return;
        modalPriceHistory.hidden = true;
        modalPriceHistory.innerHTML = '';
        try {
            const res = await fetch(api(`games/${encodeURIComponent(slug)}/price-history`));
            if (!res.ok) return;
            const data = await res.json();
            if (!data.points?.length) return;
            const recent = data.points.slice(-7);
            const rows = recent.map(p => `<tr><td>${escapeHtml(p.date)}</td><td>${Number(p.best_price_pln).toFixed(2)} zł</td></tr>`).join('');
            let meta = '';
            if (data.lowest_ever_pln) meta += `Najniższa: ${Number(data.lowest_ever_pln).toFixed(2)} zł`;
            if (data.avg_best_price_30d) meta += `${meta ? ' · ' : ''}Średnia 30 dni: ${Number(data.avg_best_price_30d).toFixed(2)} zł`;
            modalPriceHistory.hidden = false;
            modalPriceHistory.innerHTML = `
                <h4 class="modal-history-title">Historia cen</h4>
                ${meta ? `<p class="modal-history-meta">${escapeHtml(meta)}</p>` : ''}
                <table class="modal-history-table"><tr><th>Dzień</th><th>Najniższa</th></tr>${rows}</table>
            `;
        } catch (e) {
            console.warn('price history', e);
        }
    }

    async function refreshFavoriteState() {
        if (!currentGameSlug || !isLoggedIn()) return;
        try {
            const url = currentGameId
                ? `favorites/check/${currentGameId}`
                : `favorites/check/slug/${encodeURIComponent(currentGameSlug)}`;
            const res = await authFetch(url);
            if (res.ok) {
                const data = await res.json();
                isFavorited = !!data.favorited;
                alertEnabled = !!data.alert_enabled;
                if (data.game_id) currentGameId = data.game_id;
                if (isFavorited) watchedSlugs.add(currentGameSlug);
                else watchedSlugs.delete(currentGameSlug);
                updateWatchButton(btnFavorite, isFavorited);
                updateAlertButton(alertEnabled);
            }
        } catch (e) {
            console.warn(e);
        }
    }

    async function toggleWatch(slug, btn) {
        if (!slug) return;
        if (!isLoggedIn()) {
            window.location.href = 'login';
            return;
        }
        const active = btn?.classList.contains('active') || watchedSlugs.has(slug);
        const method = active ? 'DELETE' : 'POST';
        const res = await authFetch(`favorites/slug/${encodeURIComponent(slug)}`, { method });
        if (res.status === 401) {
            window.location.href = 'login';
            return;
        }
        if (res.ok) {
            const data = await res.json().catch(() => ({}));
            if (data.game_id) currentGameId = data.game_id;
            if (active) watchedSlugs.delete(slug);
            else watchedSlugs.add(slug);
            isFavorited = !active;
            document.querySelectorAll(`.btn-watch[data-slug="${CSS.escape(slug)}"]`).forEach(el => {
                updateWatchButton(el, !active);
            });
            updateWatchButton(btnFavorite, !active);
        }
    }

    function renderGamesGrid(games, append) {
        if (!append) gamesGrid.innerHTML = '';
        if (!games.length && !append) {
            const hint = currentQuery && currentCategory
                ? tt('grid.hint_both')
                : tt('grid.hint');
            gamesGrid.innerHTML = `<p class="no-results">${tt('grid.not_found')} ${hint}</p>`;
            return;
        }

        games.forEach(game => {
            gamesGrid.appendChild(buildGameCard(game, false));
        });
    }

    function renderOffers(offers, pending = false) {
        mergeModalOffers(offers);
        const scanning = pending && ACTIVE_SHOPS.some(
            name => !hasShopOffer(name) && !DISABLED_SHOPS.has(name)
        );
        setOffersScanning(scanning);
        updateOffersScanShops();

        const priced = pricedModalOffers();
        const ctaOffer = getCtaOffer();
        const cheapestOffer = getCheapestOffer();
        const highlightOffer = ctaOffer || cheapestOffer;
        const bestPrice = highlightOffer ? Number(highlightOffer.price_pln) : null;

        renderModalSavings();

        offersList.innerHTML = '';
        let rowIndex = 0;
        shopsForOfferList().forEach(shopName => {
            const offer = modalOffersByShop[shopName];
            const shopClass = shopName.toLowerCase().replace(/\s+/g, '');
            const row = document.createElement('div');
            const blik = ['eneba', 'gog'].includes(shopClass)
                ? ' <span class="blik-badge">BLIK</span>' : '';
            const isCheapest = highlightOffer && offer.id === highlightOffer.id;

            row.className = 'offer-row offer-row--enter' + (isCheapest ? ' cheapest' : '');
            row.style.setProperty('--enter-i', rowIndex);
            row.style.animationDelay = `${rowIndex * 50}ms`;
            rowIndex += 1;
            const isOfficial = Boolean(offer.is_official) || offer.trust_tier === 'A' && /oficjaln/i.test(offer.trust_label || '');
            const badgeClass = offer.is_official ? 'offer-badge--official' : `offer-badge--tier-${(offer.trust_tier || 'c').toLowerCase()}`;
            const typeLabel = offer.is_official ? tt('offer.official') : tt('offer.marketplace');
            const noteText = offer.trust_note
                ? offer.trust_note
                : (offer.is_official ? tt('offer.official_note') : tt('offer.marketplace_note'));
            const infoBadge = noteText
                ? ` <span class="offer-info" tabindex="0" role="button" aria-label="${escapeHtml(noteText)}" title="${escapeHtml(noteText)}">i</span>`
                : '';
            const refundHtml = offerRefundHtml(offer);
            const warnBadge = offer.low_confidence
                ? ` <span class="offer-warn-badge" title="${escapeHtml(tt('offer.low_conf_note'))}">${tt('offer.check')}</span>`
                : '';
            const buyLabel = isCheapest ? tt('offer.buy_cheapest', { price: formatPln(offer.price_pln) }) : tt('offer.buy');
            const orig = Number(offer.original_price_pln);
            const hasDiscount = Number.isFinite(orig) && orig > Number(offer.price_pln) + 0.01;
            const priceHtml = hasDiscount
                ? `<span class="offer-price"><span class="offer-price-old">${formatPln(orig)}</span> ${formatPln(offer.price_pln)}</span>`
                : `<span class="offer-price">${formatPln(offer.price_pln)}</span>`;
            row.innerHTML = `
                <div class="offer-row-main">
                    <span class="offer-shop shop-${shopClass}">${offer.shop_name}${blik}</span>
                    <span class="offer-type"><span class="offer-badge ${badgeClass}">${typeLabel}</span>${infoBadge}${warnBadge}${refundHtml}</span>
                </div>
                ${priceHtml}
                <a href="${offerGoUrl(offer)}" target="_blank" rel="noopener noreferrer nofollow sponsored" class="btn-buy${isCheapest ? ' btn-buy--best' : ''}">${buyLabel}</a>
            `;
            attachOfferBuyTracking(row.querySelector('.btn-buy'), offer);
            offersList.appendChild(row);
        });

        if (priced.length) {
            const note = document.createElement('p');
            note.className = 'offers-affiliate-note';
            note.textContent = tt('offer.affiliate_note');
            offersList.appendChild(note);
        }

        if (!priced.length && !scanning) {
            if (modalSavings) {
                modalSavings.hidden = true;
                modalSavings.innerHTML = '';
            }
            offersList.innerHTML = `<div class="offers-empty">${tt('modal.no_offers')}</div>`;
        }
    }

    btnAlert?.addEventListener('click', togglePriceAlert);

    categoriesBar.querySelector('.cat[data-slug=""]')?.addEventListener('click', showHomeView);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.hidden) closeModalFn();
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            searchInput.focus();
        }
    });

    loadCategories();
    loadCatalogStats();
    setInterval(loadCatalogStats, 5 * 60 * 1000);
    loadHomeSections();
    initOffersScanShops();
    if (isLoggedIn()) loadWatchedSlugs();

    document.addEventListener('langchange', () => {
        if (window.I18n) I18n.applyPage();
        const allCat = categoriesBar?.querySelector('.cat[data-slug=""]');
        if (allCat) allCat.textContent = tt('cat.all');
        if (!currentCategory && !currentQuery) gamesHeading.textContent = tt('catalog.all_games');
        document.querySelectorAll('.btn-watch-card, #btn-favorite').forEach((btn) => {
            const slug = btn.dataset.slug;
            if (!slug) return;
            updateWatchButton(btn, watchedSlugs.has(slug));
        });
        if (btnAlert && isLoggedIn() && isFavorited) updateAlertButton(alertEnabled);
    });

    const pathGra = location.pathname.match(/\/gra\/([^/]+)/);
    const deepLinkGra = pathGra ? decodeURIComponent(pathGra[1]) : new URLSearchParams(location.search).get('gra');
    const urlQuery = new URLSearchParams(location.search).get('q');
    if (urlQuery && urlQuery.trim()) {
        searchInput.value = urlQuery.trim();
        runSearch(urlQuery.trim());
    } else if (deepLinkGra) {
        setTimeout(() => showGameDetails(deepLinkGra), 300);
    }
});

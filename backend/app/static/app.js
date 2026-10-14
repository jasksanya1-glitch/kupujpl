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

    function localizeDealAge(label) {
        if (!label) return '';
        const lang = window.I18n?.getLang?.() || 'pl';
        if (lang === 'pl') return label;
        if (label === 'przed chwilą') return tt('deal.just_now');
        let m = label.match(/^(\d+)\s*min temu$/i);
        if (m) return tt('deal.mins_ago', { n: m[1] });
        m = label.match(/^(\d+)\s*godz\.?\s*temu$/i);
        if (m) return tt('deal.hours_ago', { n: m[1] });
        m = label.match(/^(\d+)\s*dni temu$/i);
        if (m) return tt('deal.days_ago', { n: m[1] });
        return label;
    }

    /** Mount mobile-only legacy home if the server left <template> (JS fallback). */
    function mountMobileHomeLegacy() {
        const tpl = document.getElementById('tpl-mobile-home-legacy');
        const mount = document.getElementById('mobile-home-mount');
        if (!tpl || !mount) return;
        const frag = tpl.content.cloneNode(true);
        const sortLabel = frag.querySelector('#mobile-catalog-sort');
        const sortSlot = document.getElementById('catalog-sort-slot');
        if (sortLabel && sortSlot && !sortSlot.querySelector('#sort-select')) {
            sortSlot.appendChild(sortLabel);
        }
        mount.appendChild(frag);
        mount.hidden = false;
        tpl.remove();
    }
    mountMobileHomeLegacy();

    const gamesGrid = document.getElementById('games-grid');
    const searchInput = document.getElementById('search-input');

    const heroSearchBtn = document.getElementById('hero-search-btn');
    if (heroSearchBtn && searchInput) {
        heroSearchBtn.addEventListener('click', () => {
            try {
                searchInput.focus({ preventScroll: false });
            } catch (_) {
                searchInput.focus();
            }
            searchInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
            if (typeof searchInput.select === 'function') searchInput.select();
        });
    }
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
    const homeFeeds = document.getElementById('home-feeds');
    const homeSpotlight = document.getElementById('home-spotlight');
    const homeSpotlightRow = document.getElementById('home-spotlight-row');
    const catalogSection = document.getElementById('catalog-section');
    const heroSection = document.getElementById('hero-section');
    const homeHero = document.querySelector('.cp-home-hero');
    const homeTop = document.querySelector('.cp-home-top');
    const homePromo = document.querySelector('.cp-panel-promo');
    const homeNews = document.getElementById('home-news');
    const featuredHost = document.getElementById('m-featured-host');
    const splitRight = document.getElementById('split-right');
    const d3Hero = document.getElementById('d3-hero');
    const d3Discover = document.getElementById('d3-discover');
    const d3Cats = document.getElementById('d3-cats');
    let d3HeroGames = [];
    let d3HeroIndex = 0;
    let d3HeroBound = false;
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
        'Steam US': 'Steam US',
        GOG: 'GOG',
        'Epic Games': 'Epic',
        'Instant Gaming': 'IG',
        Eneba: 'Eneba',
        Kinguin: 'Kinguin',
        Gamivo: 'Gamivo',
        Fanatical: 'Fanatical',
        G2A: 'G2A',
        CDKeys: 'CDKeys',
    };

    function shoppingRegion() {
        return window.KupujPLRegion?.getShoppingRegion?.() || 'pl';
    }

    function withRegion(path) {
        const sep = path.includes('?') ? '&' : '?';
        return `${path}${sep}region=${encodeURIComponent(shoppingRegion())}`;
    }

    function preferredSteamShop() {
        return shoppingRegion() === 'us' ? 'Steam US' : 'Steam';
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

    function shopsForRegionList(shops) {
        const region = shoppingRegion();
        const list = (shops || []).slice();
        if (region === 'us') {
            return list.map((s) => (s === 'Steam' ? 'Steam US' : s));
        }
        return list.filter((s) => s !== 'Steam US');
    }

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
        const utmTerm = params.get('utm_term');
        const utmContent = params.get('utm_content');
        const gclid = params.get('gclid');
        const wbraid = params.get('wbraid');
        const gbraid = params.get('gbraid');
        const referrerUrl = document.referrer || null;
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
                    utm_term: utmTerm,
                    utm_content: utmContent,
                    gclid,
                    wbraid,
                    gbraid,
                    referrer_url: referrerUrl,
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

    function isDesktopViewport() {
        return window.matchMedia('(min-width: 1024px)').matches;
    }

    function syncDesktopAccountChrome() {
        const loggedIn = typeof isLoggedIn === 'function' && isLoggedIn();
        document.body.classList.toggle('d3-logged-in', !!loggedIn);
        const account = document.getElementById('d3-tool-account');
        if (account) {
            account.href = loggedIn ? 'panel' : 'login';
            const label = account.querySelector('span');
            if (label) label.textContent = loggedIn ? tt('nav.panel') : tt('nav.account');
            account.setAttribute('aria-label', loggedIn ? tt('nav.account_panel') : tt('nav.account'));
        }
    }

    function syncDesktopCats() {
        if (!d3Cats || !categoriesBar) return;
        d3Cats.innerHTML = '';
        categoriesBar.querySelectorAll('.cat').forEach((el) => {
            d3Cats.appendChild(el.cloneNode(true));
        });
    }

    function syncActiveCats(slug) {
        const activeSlug = slug == null ? '' : String(slug);
        [categoriesBar, d3Cats].forEach((host) => {
            if (!host) return;
            host.querySelectorAll('.cat').forEach((el) => {
                const elSlug = el.dataset.slug == null ? '' : String(el.dataset.slug);
                const isLink = el.tagName === 'A';
                el.classList.toggle('active', !isLink && elSlug === activeSlug);
            });
        });
    }

    function syncHeroTitleMode() {
        // Single site H1 (.site-h1); mobile marketing copy is a separate <p>, never an H1.
        if (heroSearchBtn) heroSearchBtn.hidden = true;
        const promoCard = document.querySelector('.cp-panel-promo-card');
        if (promoCard) promoCard.hidden = true;
    }

    function syncSortTabs(val) {
        const sortVal = val == null ? currentSort : String(val);
        document.querySelectorAll('#m-sort-tabs button[data-sort]').forEach((btn) => {
            btn.setAttribute('aria-selected', (btn.dataset.sort || '') === sortVal ? 'true' : 'false');
        });
        if (sortSelect && sortSelect.value !== sortVal) sortSelect.value = sortVal;
    }

    function applySortValue(sort, { fetch = true } = {}) {
        currentSort = sort == null ? '' : String(sort);
        syncSortTabs(currentSort);
        if (!fetch) return;
        if (currentQuery || currentCategory) {
            fetchGames(1, false);
        } else {
            showAllGamesCatalog();
        }
    }

    function setBrowseMode(mode) {
        const isHome = mode === 'home';
        const mobile = window.matchMedia('(max-width: 767px)').matches;
        const desktop = isDesktopViewport();
        if (homeSpotlight) {
            // Mobile: Polecane merges into featured card.
            // Desktop Concept #3: cinematic hero replaces the old spotlight strip.
            homeSpotlight.hidden = mobile || desktop || (isHome ? homeSpotlightRow?.childElementCount === 0 : true);
        }
        if (homeTop) {
            homeTop.hidden = !isHome || desktop;
            homeTop.setAttribute('aria-hidden', homeTop.hidden ? 'true' : 'false');
        }
        if (homeHero) homeHero.hidden = !isHome || desktop;
        if (homePromo) homePromo.hidden = !isHome;
        if (homeNews) {
            if (!isHome) {
                homeNews.hidden = true;
            } else {
                const list = document.getElementById('home-news-list');
                homeNews.hidden = !(list && list.childElementCount > 0);
            }
        }
        if (homeFeeds) homeFeeds.hidden = !isHome || mobile || desktop;
        if (homeSections) homeSections.hidden = !isHome || mobile || desktop;
        if (heroSection) heroSection.hidden = true;
        if (d3Hero) {
            d3Hero.hidden = !(desktop && isHome && d3Hero.dataset.hasGames === '1');
        }
        if (d3Cats) d3Cats.hidden = !(desktop && isHome);
        if (d3Discover) d3Discover.hidden = !(desktop && isHome);
        // Mobile + desktop homepage show the real catalogue ("Wszystkie gry").
        if (catalogSection) {
            catalogSection.hidden = (mobile || desktop) ? false : isHome;
        }
        if (splitRight) {
            splitRight.classList.toggle('split-right--catalog', !isHome);
            splitRight.classList.toggle('split-right--mobile-home', mobile && isHome);
            splitRight.classList.toggle('split-right--desktop-home', desktop && isHome);
            if (!isHome) splitRight.scrollTop = 0;
        }
        syncHeroTitleMode();
        syncDesktopAccountChrome();
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
        const heroInput = document.getElementById('hero-search-input');
        if (heroInput) heroInput.value = '';
        setBrowseMode('home');
        syncActiveCats('');
        if (window.matchMedia('(max-width: 767px)').matches || isDesktopViewport()) {
            fetchGames(1, false);
        }
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
        syncActiveCats('');
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
            // Search shows matching games only — clear genre/category filter.
            currentCategory = '';
            currentCategoryName = '';
            categoriesBar?.querySelectorAll('.cat').forEach((el) => {
                el.classList.toggle('active', el.dataset.slug === '');
            });
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
        applySortValue(e.target.value || '');
    });

    closeModal?.addEventListener('click', closeModalFn);
    modalOverlay?.addEventListener('click', closeModalFn);
    btnFavorite?.addEventListener('click', () => toggleWatch(currentGameSlug, btnFavorite));
    loadMoreBtn?.addEventListener('click', () => {
        if (currentPage < totalPages) fetchGames(currentPage + 1, true);
    });

    async function loadHomeNews() {
        const host = document.getElementById('home-news');
        const list = document.getElementById('home-news-list');
        if (!host || !list) return;
        try {
            const res = await fetch(api('articles/latest?limit=6'));
            if (!res.ok) return;
            const data = await res.json();
            const items = (data.items || []).slice(0, 4);
            if (!items.length) {
                host.hidden = true;
                list.innerHTML = '';
                return;
            }
            host.hidden = false;
            const typeLabel = (raw) => {
                const key = String(raw || 'news').toLowerCase();
                if (key === 'deal' || key === 'price_drop' || key === 'promocje') return 'PROMOCJE';
                if (key === 'guide' || key === 'poradnik') return 'PORADNIK';
                if (key === 'release' || key === 'free_game') return 'NOWOŚCI';
                if (key === 'news') return 'NOWOŚCI';
                return String(raw || 'NOWOŚCI').toUpperCase();
            };
            list.innerHTML = items.map((it) => {
                const href = escapeHtml(it.url || ('blog/' + it.slug));
                const thumb = it.featured_image
                    ? `<span class="home-news-card-thumb"><img src="${escapeHtml(it.featured_image)}" alt="" loading="lazy" width="320" height="180"></span>`
                    : '';
                return `
                <a class="home-news-card" href="${href}">
                    ${thumb}
                    <span class="home-news-card-type">${escapeHtml(typeLabel(it.article_type))}</span>
                    <strong>${escapeHtml(it.title)}</strong>
                    <span class="home-news-card-date">${escapeHtml(it.date || '')}</span>
                    <span class="home-news-card-ex">${escapeHtml(it.excerpt || '')}</span>
                </a>`;
            }).join('');
        } catch (e) {
            console.warn('home news', e);
        }
    }

    async function loadHomeSections() {
        try {
            const res = await fetch(api(withRegion('home')));
            if (!res.ok) throw new Error('home failed');
            const data = await res.json();
            try { renderHomeSpotlight(data.spotlight || []); } catch (e) { console.warn(e); }
            try {
                // Desktop hero/side panel must use the same manual Polecane list (spotlight order).
                const spotlightGames = Array.isArray(data.spotlight)
                    ? data.spotlight.filter((game) => game && game.slug)
                    : [];
                renderDesktopHero(spotlightGames.length ? spotlightGames : pickFeaturedDealGames(data));
            } catch (e) { console.warn(e); }
            try { renderFeaturedDeals(data); } catch (e) { console.warn(e); }
            try { renderDealFeeds(data); } catch (e) { console.warn(e); }
            try { renderHomeSections(data.sections || []); } catch (e) { console.warn(e); }
            try { loadWishlistDeals(); } catch (e) { console.warn(e); }
            try { loadHomeNews(); } catch (e) { console.warn(e); }
            try { refreshMobilePromoCounts(); } catch (e) { console.warn(e); }
            if (!currentCategory && !currentQuery) {
                setBrowseMode('home');
            }
            const bootCatalog = (
                (window.matchMedia('(max-width: 767px)').matches || isDesktopViewport())
                && !currentCategory
                && !currentQuery
            );
            if (bootCatalog) {
                try {
                    if (!document.body.dataset.sortBoot) {
                        document.body.dataset.sortBoot = '1';
                        applySortValue('rating', { fetch: false });
                    }
                    fetchGames(1, false);
                } catch (e) { console.warn(e); }
            }
            trackPageView('/view/home');
        } catch (e) {
            console.warn('home sections', e);
            homeSections.innerHTML = `<p class="no-results">${tt('home.load_fail')}</p>`;
            trackPageView('/view/home');
        }
    }

    function renderFeedBlock(targetId, title, subtitle, games, opts = {}) {
        const host = document.getElementById(targetId);
        if (!host) return;
        if (!games?.length) {
            host.hidden = true;
            host.innerHTML = '';
            return;
        }
        host.hidden = false;
        host.className = 'home-feed-block home-section-block';
        host.innerHTML = `
            <div class="home-section-head">
                <div>
                    <h2 class="home-section-title">${escapeHtml(title)}</h2>
                    <p class="home-section-sub">${escapeHtml(subtitle || '')}</p>
                </div>
            </div>
            <div class="home-section-row"></div>
        `;
        const row = host.querySelector('.home-section-row');
        games.forEach((game) => row.appendChild(buildGameCard(game, 0)));
    }

    function renderGiveawayFeed(items) {
        const host = document.getElementById('feed-giveaways');
        if (!host) return;
        const list = Array.isArray(items) ? items.filter((g) => g && g.title) : [];
        if (!list.length) {
            host.hidden = true;
            host.innerHTML = '';
            return;
        }
        host.hidden = false;
        const title = tt('feed.giveaways') || 'Darmowe gry teraz';
        const subtitle = tt('feed.giveaways_sub') || 'Epic Free Games i Steam — weź zanim znikną';
        const more = tt('feed.giveaways_more') || 'Wszystkie darmowe gry →';
        host.innerHTML = `
            <div class="home-section-head">
                <div>
                    <h2 class="home-section-title">${escapeHtml(title)}</h2>
                    <p class="home-section-sub">${escapeHtml(subtitle)}</p>
                </div>
                <a class="home-section-more" href="darmowe-gry">${escapeHtml(more)}</a>
            </div>
            <div class="home-section-row"></div>
        `;
        const row = host.querySelector('.home-section-row');
        list.slice(0, 12).forEach((g) => {
            const href = g.slug
                ? `gra/${encodeURIComponent(g.slug)}`
                : (g.affiliate_url || g.store_url || 'darmowe-gry');
            const cover = g.cover_image || 'static/favicon.png';
            const shop = g.shop || '';
            const ends = (g.ends_at || '').slice(0, 10);
            const orig = g.original_price_pln != null ? `${Number(g.original_price_pln).toFixed(2)} zł` : '';
            const a = document.createElement('a');
            a.className = 'game-card game-card-row giveaway-card';
            a.href = href;
            if (!g.slug) {
                a.rel = 'noopener noreferrer sponsored';
                a.target = '_blank';
            }
            a.innerHTML = `
                <span class="card-cover"><img src="${escapeHtml(cover)}" alt="${escapeHtml(g.title)}" loading="lazy" width="196" height="92"></span>
                <span class="card-body">
                    <span class="card-title">${escapeHtml(g.title)}</span>
                    <span class="card-price">0,00 zł · ${escapeHtml(shop)}${orig ? ` <s>${escapeHtml(orig)}</s>` : ''}</span>
                    <span class="card-meta">${ends ? escapeHtml(ends) : escapeHtml(tt('feed.giveaways') || 'Za darmo')}</span>
                </span>`;
            row.appendChild(a);
        });
    }

    function renderDealFeeds(data) {
        renderGiveawayFeed(data.giveaways || []);
        renderFeedBlock(
            'feed-new-deals',
            tt('feed.new_deals') || 'Nowe okazje',
            tt('feed.new_deals_sub') || 'Świeże spadki cen',
            data.new_deals || []
        );
        renderFeedBlock(
            'feed-hist-lows',
            tt('feed.hist_lows') || 'Najniższe w historii',
            tt('feed.hist_lows_sub') || 'Aktualna cena = rekord all-time',
            data.historical_lows || []
        );
        renderFeedBlock(
            'feed-freebies',
            tt('feed.freebies') || 'Za darmo',
            tt('feed.freebies_sub') || 'Freebies ze Steam / GOG / Epic · pełna lista',
            data.freebies || []
        );
        const freeHost = document.getElementById('feed-freebies');
        if (freeHost && !freeHost.hidden && !freeHost.querySelector('.home-section-more')) {
            const head = freeHost.querySelector('.home-section-head');
            if (head) {
                const more = document.createElement('a');
                more.className = 'home-section-more';
                more.href = 'darmowe-gry';
                more.textContent = tt('feed.giveaways_more') || 'Wszystkie darmowe gry →';
                head.appendChild(more);
            }
        }
    }

    async function loadWishlistDeals() {
        if (!isLoggedIn()) {
            const el = document.getElementById('feed-wishlist');
            if (el) { el.hidden = true; el.innerHTML = ''; }
            return;
        }
        try {
            const res = await authFetch('favorites');
            if (!res.ok) return;
            const favs = await res.json();
            const deals = (favs || []).filter(
                (g) => (g.savings_pct && g.savings_pct >= 10) || g.at_historical_low || g.lowest_ever_label
            ).slice(0, 14);
            renderFeedBlock(
                'feed-wishlist',
                tt('feed.wishlist') || 'Twoje ulubione w promocji',
                tt('feed.wishlist_sub') || 'Zniżki na gry ze śledzonych',
                deals
            );
        } catch (e) {
            console.warn('wishlist deals', e);
        }
    }

    function pickFeaturedDealGames(data) {
        // Priority 1: owner-curated Polecane (home_curation.json → API spotlight), keep order.
        const spotlight = Array.isArray(data?.spotlight)
            ? data.spotlight.filter((game) => game && game.slug)
            : [];
        if (spotlight.length) return spotlight;

        // Priority 2: fallback only when Polecane is empty.
        const ranked = [];
        const seen = new Set();
        const push = (game) => {
            if (!game?.slug || seen.has(game.slug) || game.best_price_pln == null) return;
            seen.add(game.slug);
            ranked.push(game);
        };
        const deals = Array.isArray(data?.new_deals) ? [...data.new_deals] : [];
        deals.sort((a, b) => Number(b.savings_pct || 0) - Number(a.savings_pct || 0));
        deals.forEach(push);
        (data?.historical_lows || []).forEach(push);
        return ranked.slice(0, 5);
    }

    function featuredImageFor(game) {
        if (typeof featuredCoverInfo === 'function') return featuredCoverInfo(game);
        const src = typeof gameCoverSrc === 'function' ? gameCoverSrc(game) : (game?.cover_image || '');
        return { src, isPortrait: false, chain: [src].filter(Boolean) };
    }

    function setMobileHeroArt(game) {
        const art = document.getElementById('m-hero-art');
        const img = document.getElementById('m-hero-art-img');
        if (!art || !img) return;
        if (!game) {
            art.hidden = true;
            img.removeAttribute('src');
            return;
        }
        const info = featuredImageFor(game);
        img.src = info.src;
        img.alt = '';
        img.loading = 'eager';
        img.fetchPriority = 'high';
        art.hidden = false;
        bindCoverFallback(img, game, { preferWide: true });
    }

    function buildFeaturedSlideHtml(game, index) {
        const info = featuredImageFor(game);
        const gameUrl = `gra/${encodeURIComponent(game.slug)}`;
        const hasPrice = game.best_price_pln != null;
        const hasSteam = hasPrice
            && game.steam_price_pln != null
            && Number(game.steam_price_pln) > Number(game.best_price_pln) + 0.01;
        const pct = game.savings_pct != null ? Number(game.savings_pct) : null;
        const shop = game.best_shop_name ? `<span>${escapeHtml(game.best_shop_name)}</span>` : '';
        const platform = `<span>${escapeHtml((game.platform || 'pc').toUpperCase())}</span>`;
        const badge = (pct != null && pct > 0)
            ? `<span class="m-featured-badge">−${Math.round(pct)}%</span>`
            : (game.at_historical_low || game.lowest_ever_label)
                ? `<span class="m-featured-badge">HISTORYCZNE MIN.</span>`
                : '';
        const mediaClass = info.isPortrait
            ? 'm-featured-media m-featured-media--portrait'
            : 'm-featured-media';
        const eager = index === 0;
        const priceBlock = hasPrice
            ? `<div class="m-featured-price">
                    ${pct != null && pct > 0 ? `<span class="m-featured-discount">-${Math.round(pct)}%</span>` : ''}
                    ${hasSteam ? `<span class="m-featured-old">${formatPln(game.steam_price_pln)}</span>` : ''}
                    <span class="m-featured-now">${formatPln(game.best_price_pln, { html: true })}</span>
               </div>`
            : `<div class="m-featured-price"><span class="m-featured-now">${tt('card.check_price')}</span></div>`;
        return `
            <a class="m-featured" href="${gameUrl}" data-slug="${escapeHtml(game.slug)}" data-index="${index}">
                <div class="${mediaClass}">
                    ${badge}
                    <img src="${escapeHtml(info.src)}"
                         alt="${escapeHtml(game.title)}"
                         width="640" height="360"
                         loading="${eager ? 'eager' : 'lazy'}"
                         decoding="async"
                         ${eager ? 'fetchpriority="high"' : ''}
                         data-featured-img="${index}">
                </div>
                <div class="m-featured-body">
                    <h2 class="m-featured-title">${escapeHtml(game.title)}</h2>
                    <div class="m-featured-meta">${platform}${shop}</div>
                    ${priceBlock}
                    <span class="m-featured-cta">${escapeHtml(tt('d3.compare'))}</span>
                </div>
            </a>`;
    }

    function renderFeaturedDeals(data) {
        const host = document.getElementById('m-featured-host');
        const mount = document.getElementById('m-featured-mount');
        const dots = document.getElementById('m-featured-dots');
        const kicker = document.getElementById('m-featured-kicker');
        if (!host || !mount) return;
        const games = pickFeaturedDealGames(data);
        const fromSpotlight = Array.isArray(data?.spotlight) && data.spotlight.length > 0;
        if (!games.length) {
            host.classList.add('is-empty');
            mount.innerHTML = '';
            setMobileHeroArt(null);
            if (kicker) kicker.hidden = true;
            if (dots) {
                dots.hidden = true;
                dots.innerHTML = '';
            }
            return;
        }
        host.classList.remove('is-empty');
        if (kicker) {
            kicker.hidden = false;
            kicker.textContent = fromSpotlight ? tt('featured.polecane') : tt('featured.picked');
        }

        // Render first slide immediately, then remaining slides — never Promise.all on images.
        setMobileHeroArt(games[0]);
        mount.innerHTML = games.map((game, index) => buildFeaturedSlideHtml(game, index)).join('');
        mount.querySelectorAll('img[data-featured-img]').forEach((img) => {
            const idx = Number(img.dataset.featuredImg || 0);
            const game = games[idx];
            if (game) bindCoverFallback(img, game, { preferWide: true });
            const media = img.closest('.m-featured-media--portrait');
            if (media && img.src) media.style.setProperty('--image', `url("${img.src}")`);
        });

        const syncDots = (index) => {
            if (!dots) return;
            dots.querySelectorAll('button').forEach((btn, i) => {
                btn.setAttribute('aria-current', i === index ? 'true' : 'false');
            });
        };

        const scrollToIndex = (index) => {
            const slide = mount.querySelector(`.m-featured[data-index="${index}"]`);
            if (!slide) return;
            mount.scrollTo({ left: slide.offsetLeft, behavior: 'smooth' });
            setMobileHeroArt(games[index]);
            syncDots(index);
        };

        if (dots) {
            if (games.length > 1) {
                dots.hidden = false;
                dots.innerHTML = games.map((_, i) => (
                    `<button type="button" aria-label="${escapeHtml(tt('d3.featured_n', { n: i + 1 }))}" aria-current="${i === 0 ? 'true' : 'false'}"></button>`
                )).join('');
                dots.querySelectorAll('button').forEach((btn, i) => {
                    btn.addEventListener('click', () => scrollToIndex(i));
                });
            } else {
                dots.hidden = true;
                dots.innerHTML = '';
            }
        }

        if (!host.dataset.featuredBound) {
            host.dataset.featuredBound = '1';
            let scrollTimer = 0;
            mount.addEventListener('scroll', () => {
                window.clearTimeout(scrollTimer);
                scrollTimer = window.setTimeout(() => {
                    const width = mount.clientWidth || 1;
                    const index = Math.round(mount.scrollLeft / width);
                    const clamped = Math.max(0, Math.min(games.length - 1, index));
                    setMobileHeroArt(games[clamped]);
                    syncDots(clamped);
                }, 60);
            }, { passive: true });
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
                ? `<span class="cp-spotlight-price">${formatPln(game.best_price_pln, { html: true })}</span>`
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
            // Full page navigation — no modal intercept
            const img = tile.querySelector('img');
            if (img && game) bindCoverFallback(img, game);
        });
    }

    function paintDesktopHeroSlide() {
        if (!d3Hero || !d3HeroGames.length) return;
        const game = d3HeroGames[d3HeroIndex];
        if (!game) return;
        const main = document.getElementById('d3-hero-main');
        const img = document.getElementById('d3-hero-img');
        const title = document.getElementById('d3-hero-title');
        const sub = document.getElementById('d3-hero-sub');
        const tags = document.getElementById('d3-hero-tags');
        const price = document.getElementById('d3-hero-price');
        const gameUrl = `gra/${encodeURIComponent(game.slug)}`;
        if (main) main.href = gameUrl;
        if (title) title.textContent = game.title || '—';
        if (sub) {
            const desc = (game.description || '').trim();
            if (desc) {
                sub.hidden = false;
                sub.textContent = desc.length > 140 ? `${desc.slice(0, 137)}…` : desc;
            } else {
                sub.hidden = true;
                sub.textContent = '';
            }
        }
        if (tags) {
            const bits = [];
            bits.push(`<span class="d3-hero-tag">${escapeHtml((game.platform || 'pc').toUpperCase())}</span>`);
            if (game.best_shop_name) {
                bits.push(`<span class="d3-hero-tag">${escapeHtml(game.best_shop_name)}</span>`);
            }
            if (game.rating != null && Number(game.rating) > 0) {
                bits.push(`<span class="d3-hero-tag">★ ${Number(game.rating).toFixed(1)}</span>`);
            }
            tags.innerHTML = bits.join('');
        }
        if (price) {
            const hasPrice = game.best_price_pln != null;
            const pct = game.savings_pct != null ? Number(game.savings_pct) : null;
            const hasSteam = hasPrice
                && game.steam_price_pln != null
                && Number(game.steam_price_pln) > Number(game.best_price_pln) + 0.01
                && pct != null
                && pct > 0;
            if (!hasPrice) {
                price.innerHTML = `<span class="d3-hero-now">${tt('card.check_price')}</span>`;
            } else {
                price.innerHTML = `
                    ${pct != null && pct > 0 ? `<span class="d3-hero-discount">-${Math.round(pct)}%</span>` : ''}
                    ${hasSteam ? `<span class="d3-hero-old">${formatPln(game.steam_price_pln)}</span>` : ''}
                    <span class="d3-hero-now">${formatPln(game.best_price_pln, { html: true })}</span>
                    <span class="d3-hero-best">${escapeHtml(game.best_shop_name ? tt('d3.best_price_shop', { shop: game.best_shop_name }) : tt('d3.best_price'))}</span>
                `;
            }
        }
        if (img) {
            const info = featuredImageFor(game);
            const media = img.closest('.d3-hero-media');
            img.alt = game.title || '';
            img.loading = 'eager';
            img.fetchPriority = d3HeroIndex === 0 ? 'high' : 'auto';
            img.src = info.src;
            if (media && info.src) {
                media.style.setProperty('--d3-hero-bg', `url("${String(info.src).replace(/"/g, '\\"')}")`);
            }
            bindCoverFallback(img, game, { preferWide: true });
            // Keep blurred backdrop in sync when fallback chain advances.
            img.onload = () => {
                const host = img.closest('.d3-hero-media');
                const src = img.currentSrc || img.src;
                if (host && src) host.style.setProperty('--d3-hero-bg', `url("${src.replace(/"/g, '\\"')}")`);
            };
        }
        const dots = document.getElementById('d3-hero-dots');
        if (dots) {
            dots.querySelectorAll('button').forEach((btn, i) => {
                btn.setAttribute('aria-current', i === d3HeroIndex ? 'true' : 'false');
            });
        }
        const sideList = document.getElementById('d3-hero-side-list');
        if (sideList) {
            sideList.querySelectorAll('.d3-side-row').forEach((row) => {
                row.classList.toggle('is-active', row.dataset.slug === game.slug);
            });
        }
    }

    function renderDesktopHero(games) {
        if (!d3Hero) return;
        d3HeroGames = (games || []).filter((g) => g && g.slug);
        const prev = document.getElementById('d3-hero-prev');
        const next = document.getElementById('d3-hero-next');
        const dots = document.getElementById('d3-hero-dots');
        const sideList = document.getElementById('d3-hero-side-list');
        if (!d3HeroGames.length) {
            d3Hero.hidden = true;
            delete d3Hero.dataset.hasGames;
            if (sideList) sideList.innerHTML = '';
            if (dots) {
                dots.hidden = true;
                dots.innerHTML = '';
            }
            if (prev) prev.hidden = true;
            if (next) next.hidden = true;
            return;
        }
        d3Hero.dataset.hasGames = '1';
        d3HeroIndex = 0;
        const sideGames = d3HeroGames.slice(1, 5);
        if (sideList) {
            sideList.innerHTML = sideGames.map((game) => {
                // Side thumbs are landscape — use header/capsule, not portrait library art.
                const coverSrc = gameCoverSrc(game);
                const gameUrl = `gra/${encodeURIComponent(game.slug)}`;
                const pct = game.savings_pct != null ? Number(game.savings_pct) : null;
                const priceHtml = game.best_price_pln != null
                    ? formatPln(game.best_price_pln, { html: true })
                    : tt('card.check_price');
                return `<a class="d3-side-row" href="${gameUrl}" data-slug="${escapeHtml(game.slug)}">
                    <span class="d3-side-cover"><img src="${escapeHtml(coverSrc)}" alt="" width="88" height="42" loading="eager" decoding="async"></span>
                    <span class="d3-side-meta">
                        <span class="d3-side-title">${escapeHtml(game.title)}</span>
                        ${pct != null && pct > 0 ? `<span class="d3-side-discount">-${Math.round(pct)}%</span>` : ''}
                        <span class="d3-side-price">${priceHtml}</span>
                    </span>
                    <span class="d3-side-chevron" aria-hidden="true">›</span>
                </a>`;
            }).join('');
            sideList.querySelectorAll('img').forEach((img, i) => {
                const game = sideGames[i];
                if (game) bindCoverFallback(img, game);
            });
            sideList.querySelectorAll('.d3-side-row').forEach((row) => {
                row.addEventListener('click', (ev) => {
                    const idx = d3HeroGames.findIndex((g) => g.slug === row.dataset.slug);
                    if (idx < 0) return;
                    // Keep navigation; also sync hero when middle-click / modifier not used.
                    if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button === 1) return;
                    d3HeroIndex = idx;
                    paintDesktopHeroSlide();
                });
            });
        }
        const multi = d3HeroGames.length > 1;
        if (prev) prev.hidden = !multi;
        if (next) next.hidden = !multi;
        if (dots) {
            if (multi) {
                dots.hidden = false;
                dots.innerHTML = d3HeroGames.map((_, i) => (
                    `<button type="button" aria-label="${escapeHtml(tt('d3.featured_n', { n: i + 1 }))}" aria-current="${i === 0 ? 'true' : 'false'}"></button>`
                )).join('');
                dots.querySelectorAll('button').forEach((btn, i) => {
                    btn.addEventListener('click', () => {
                        d3HeroIndex = i;
                        paintDesktopHeroSlide();
                    });
                });
            } else {
                dots.hidden = true;
                dots.innerHTML = '';
            }
        }
        if (!d3HeroBound) {
            d3HeroBound = true;
            prev?.addEventListener('click', () => {
                if (!d3HeroGames.length) return;
                d3HeroIndex = (d3HeroIndex - 1 + d3HeroGames.length) % d3HeroGames.length;
                paintDesktopHeroSlide();
            });
            next?.addEventListener('click', () => {
                if (!d3HeroGames.length) return;
                d3HeroIndex = (d3HeroIndex + 1) % d3HeroGames.length;
                paintDesktopHeroSlide();
            });
            document.getElementById('d3-hero-side-all')?.addEventListener('click', (ev) => {
                ev.preventDefault();
                document.getElementById('catalog-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
        }
        paintDesktopHeroSlide();
        if (isDesktopViewport() && !currentCategory && !currentQuery) {
            d3Hero.hidden = false;
        }
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
            ? `<span class="card-price">${formatPln(game.best_price_pln, { html: true })}</span>`
            : `<span class="card-price empty">${tt('card.check_price')}</span>`;
        const oldPriceHtml = (
            hasPrice
            && game.steam_price_pln != null
            && Number(game.steam_price_pln) > Number(game.best_price_pln) + 0.01
            && Number(game.savings_pct || 0) > 0
        )
            ? `<span class="card-old-price">${formatPln(game.steam_price_pln)}</span>`
            : '';
        const tagHtml = hasPrice && game.best_price_is_official
            ? `<span class="card-tag">${tt('card.official')}</span>`
            : '';
        const savingsHtml = cardSavingsHtml(game);
        const historyLabel = (game.lowest_ever_label || game.at_historical_low)
            ? `<span class="card-history-label hist-low-badge">${escapeHtml(
                ((window.I18n?.getLang?.() || 'pl') === 'pl' && game.lowest_ever_label)
                    ? game.lowest_ever_label
                    : (tt('badge.hist_low') || 'historical low')
            )}</span>`
            : '';
        const dealAge = game.deal_age_label
            ? `<span class="card-deal-age">${escapeHtml(localizeDealAge(game.deal_age_label))}</span>`
            : '';
        const freeBadge = game.is_free || (game.best_price_pln != null && game.best_price_pln <= 0.01)
            ? `<span class="card-free-badge">${tt('badge.free') || 'ZA DARMO'}</span>`
            : '';
        const watched = watchedSlugs.has(game.slug);
        const discountPct = game.savings_pct != null ? Number(game.savings_pct) : null;
        const coverBadge = (discountPct != null && discountPct > 0)
            ? `<span class="d3-card-badge">-${Math.round(discountPct)}%</span>`
            : '';

        const coverSrc = gameCoverSrc(game);
        const gameUrl = `gra/${encodeURIComponent(game.slug)}`;
        const platform = escapeHtml((game.platform || 'pc').toUpperCase());
        const ratingHtml = (game.rating != null && Number(game.rating) > 0)
            ? `<span class="card-rating">★ ${Number(game.rating).toFixed(1)}</span>`
            : '';
        const bestShop = game.best_shop_name ? escapeHtml(game.best_shop_name) : '';
        const shopRows = hasPrice ? `
            <div class="card-shops" aria-label="${escapeHtml(tt('card.compare_aria'))}">
                <div class="card-shop-row is-best">
                    <span class="card-shop-name">${bestShop || escapeHtml(tt('card.lowest'))}${bestShop ? ` <em>${escapeHtml(tt('card.lowest_price'))}</em>` : ''}</span>
                    <span class="card-shop-price">${formatPln(game.best_price_pln, { html: true })}</span>
                    <a class="card-shop-go" href="${gameUrl}">${escapeHtml(tt('d3.compare'))}</a>
                </div>
                ${
                    game.steam_price_pln != null
                    && Number(game.steam_price_pln) > Number(game.best_price_pln) + 0.01
                        ? `<div class="card-shop-row">
                            <span class="card-shop-name">Steam</span>
                            <span class="card-shop-price">${formatPln(game.steam_price_pln, { html: true })}</span>
                            <a class="card-shop-go" href="${gameUrl}">${escapeHtml(tt('card.view_offer'))}</a>
                           </div>`
                        : ''
                }
            </div>` : '';
        card.innerHTML = `
            ${rank ? `<span class="card-rank ${rankClass(rank)}">${rank}</span>` : ''}
            <div class="card-cover">
                ${coverBadge}
                <a class="card-cover-link" href="${gameUrl}" aria-label="${escapeHtml(game.title)} — ${tt('card.compare_prices')}">
                    <img src="${coverSrc}" alt="${escapeHtml(game.title)}" loading="lazy" decoding="async" width="460" height="215">
                </a>
                <button type="button" class="btn-watch btn-watch-card ${watched ? 'active' : ''}" data-slug="${game.slug}" aria-pressed="${watched ? 'true' : 'false'}">${watched ? tt('card.watching') : tt('card.watch')}</button>
            </div>
            <div class="card-body">
                <h3 class="card-title"><a class="card-title-link" href="${gameUrl}">${escapeHtml(game.title)}</a></h3>
                <div class="card-meta-row">
                    <span class="card-platform">${platform}</span>
                    ${ratingHtml}
                </div>
                <div class="card-foot">
                    <span class="card-from">${tt('card.from')}</span>
                    ${savingsHtml}
                    ${priceHtml}
                    ${oldPriceHtml}
                    ${historyLabel}
                    ${dealAge}
                    ${freeBadge}
                    ${tagHtml}
                </div>
                ${shopRows}
                ${bestShop ? `<span class="d3-card-shop">${escapeHtml(tt('d3.best_price_shop', { shop: game.best_shop_name }))}</span>` : ''}
                <a class="d3-card-cta" href="${gameUrl}" aria-label="${escapeHtml(tt('d3.compare'))}">→</a>
            </div>
        `;
        const img = card.querySelector('img');
        bindCoverFallback(img, game);
        card.querySelector('.btn-watch-card')?.addEventListener('click', (ev) => {
            ev.stopPropagation();
            toggleWatch(game.slug, ev.currentTarget);
        });
        // Navigate to full game page (no modal)
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
            if (res.ok) {
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
            }
            syncDesktopCats();
        } catch (e) {
            console.warn('categories', e);
            syncDesktopCats();
        }
    }

    async function loadCatalogStats() {
        try {
            const res = await fetch(api('catalog/status'));
            if (!res.ok) return;
            const s = await res.json();
            catalogStats.textContent = tt('catalog.games_count', { n: formatCount(s.games_total) });
            if (heroGamesCount) heroGamesCount.textContent = formatNum(s.games_total);
            const dealMeta = document.getElementById('m-deal-meta');
            if (dealMeta) {
                const shops = Number(s.stores_total)
                    || (Array.isArray(s.display_shops) ? s.display_shops.length : 0)
                    || ACTIVE_SHOPS.length
                    || 0;
                const gamesN = Number(s.games_total) || 0;
                if (shops > 0) {
                    const shopsLabel = (shops === 1) ? `${shops} sklep`
                        : (shops % 10 >= 2 && shops % 10 <= 4 && (shops % 100 < 10 || shops % 100 >= 20))
                            ? `${shops} sklepy`
                            : `${shops} sklepów`;
                    const gamesLabel = formatCount(gamesN) + (gamesN === 1 ? ' gra' : ' gier');
                    dealMeta.textContent = tt('hero.deal_meta', {
                        shops_label: shopsLabel,
                        games_label: gamesLabel,
                        shops,
                        n: formatCount(gamesN),
                    });
                }
            }
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
        // Category browse is exclusive — clear search query.
        currentQuery = '';
        if (searchInput) searchInput.value = '';
        showCatalogView();
        gamesHeading.textContent = name;
        updateCatalogSubtitle();
        scrollToCatalog();
        syncActiveCats(slug);
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
            const pageSize = window.matchMedia('(max-width: 768px)').matches ? 24 : 48;
            const params = new URLSearchParams({ page: String(page), limit: String(pageSize) });
            if (querySnapshot) params.set('q', querySnapshot);
            if (categorySnapshot) params.set('category', categorySnapshot);
            if (currentSort) params.set('sort', currentSort);
            params.set('region', shoppingRegion());

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

    const NO_COMMISSION_SHOPS = new Set(['Steam', 'Steam US', 'Epic Games']);

    function steamPriceForModal() {
        const preferred = preferredSteamShop();
        let steam = modalOffersByShop[preferred];
        if (!steam && preferred === 'Steam US') steam = modalOffersByShop.Steam;
        return steam && isValidOfferPrice(steam.price_pln) ? Number(steam.price_pln) : null;
    }

    function offerEligibleForCta(offer, steamPrice) {
        if (!offer?.shop_name || !isValidOfferPrice(offer.price_pln)) return false;
        if (offer.low_confidence) return false;
        const price = Number(offer.price_pln);
        const isSteam = offer.shop_name === 'Steam' || offer.shop_name === 'Steam US';
        if (!offer.is_official) {
            const conf = offer.match_confidence;
            if (conf == null || conf < 0.55) return false;
        }
        if (steamPrice != null && steamPrice >= 5 && !isSteam) {
            if (price / steamPrice < 0.12) return false;
        }
        if (steamPrice != null && steamPrice >= 25 && price <= 3 && !isSteam) return false;
        // Peer outlier (also catches wrong GOG/Epic matches like 15 zł vs ~200 zł)
        if (!isSteam) {
            const peers = pricedModalOffers()
                .filter(o => o.id !== offer.id && isValidOfferPrice(o.price_pln))
                .map(o => Number(o.price_pln));
            if (peers.length >= 1) {
                const sorted = peers.slice().sort((a, b) => a - b);
                const med = sorted[Math.floor(sorted.length / 2)];
                if (med >= 25 && price <= med * 0.4 && (med - price) >= 20) return false;
            }
        }
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

    function formatPln(price, { html = false } = {}) {
        if (window.KupujPLRegion) {
            return html
                ? KupujPLRegion.formatPrice(price)
                : KupujPLRegion.formatPricePlain(price);
        }
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
        const preferred = preferredSteamShop();
        let steam = modalOffersByShop[preferred];
        if (!steam && preferred === 'Steam US') steam = modalOffersByShop.Steam;
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
        const regionShops = shopsForRegionList(ACTIVE_SHOPS);
        const priced = new Set(pricedModalOffers().map(o => o.shop_name));
        const ordered = regionShops.filter(name => priced.has(name));
        const extra = [...priced].filter(
            name => !regionShops.includes(name) && name !== (shoppingRegion() === 'us' ? 'Steam' : 'Steam US')
        );
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
        for (const o of filterOffersForRegion(offers || [])) {
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
        // Drop opposite-region Steam row if present from a prior merge
        if (shoppingRegion() === 'us') delete modalOffersByShop.Steam;
        else delete modalOffersByShop['Steam US'];
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

        fetch(api(withRegion(`games/${encodeURIComponent(slug)}`)))
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
                const res = await fetch(api(withRegion(`games/${pollSlug}/offers`)));
                if (!res.ok) continue;
                const offers = await res.json();
                const before = Object.keys(modalOffersByShop).length;
                mergeModalOffers(offers);
                const after = Object.keys(modalOffersByShop).length;
                const stillMissing = shopsForRegionList(ACTIVE_SHOPS).some(
                    name => !hasShopOffer(name) && !DISABLED_SHOPS.has(name === 'Steam US' ? 'Steam' : name)
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
            const res = await fetch(api(withRegion(`games/${pollSlug}/offers`)));
            if (res.ok) mergeModalOffers(await res.json());
        } catch (e) {
            console.warn('poll offers final', e);
        }

        if (token === offersPollToken && !modal.hidden) {
            renderOffers([], false);
            setOffersScanning(false);
            try {
                const pollSlug = currentGameSlug || slug;
                const gameRes = await fetch(api(withRegion(`games/${pollSlug}`)));
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
            const rows = recent.map(p => `<tr><td>${escapeHtml(p.date)}</td><td>${formatPln(p.best_price_pln)}</td></tr>`).join('');
            let meta = '';
            if (data.lowest_ever_pln) meta += tt('history.lowest_meta', { price: formatPln(data.lowest_ever_pln) });
            if (data.avg_best_price_30d) {
                meta += `${meta ? ' · ' : ''}${tt('history.avg_meta', { price: formatPln(data.avg_best_price_30d) })}`;
            }
            modalPriceHistory.hidden = false;
            modalPriceHistory.innerHTML = `
                <h4 class="modal-history-title">${escapeHtml(tt('history.title'))}</h4>
                ${meta ? `<p class="modal-history-meta">${escapeHtml(meta)}</p>` : ''}
                <table class="modal-history-table"><tr><th>${escapeHtml(tt('history.day'))}</th><th>${escapeHtml(tt('history.lowest_col'))}</th></tr>${rows}</table>
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
        const scanning = pending && shopsForRegionList(ACTIVE_SHOPS).some(
            name => !hasShopOffer(name) && !DISABLED_SHOPS.has(name === 'Steam US' ? 'Steam' : name)
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
            if (!offer) return;
            // Hide absurd wrong-SKU rows (incl. wrong GOG/Epic @15 zł vs ~200 zł peers).
            if (offer.low_confidence && offer.shop_name !== 'Steam' && offer.shop_name !== 'Steam US') return;
            if (!offerEligibleForCta(offer, steamPriceForModal()) && offer.shop_name !== 'Steam' && offer.shop_name !== 'Steam US') {
                const price = Number(offer.price_pln);
                const peers = pricedModalOffers().filter(o => o.id !== offer.id);
                if (peers.length >= 1) {
                    const sorted = peers.map(o => Number(o.price_pln)).sort((a, b) => a - b);
                    const med = sorted[Math.floor(sorted.length / 2)];
                    if (med >= 25 && price <= med * 0.4 && (med - price) >= 20) return;
                }
                const steamPrice = steamPriceForModal();
                if (steamPrice != null && steamPrice >= 5 && price / steamPrice < 0.12) return;
            }
            const shopClass = shopName.toLowerCase().replace(/\s+/g, '');
            const row = document.createElement('div');
            const blik = ['eneba', 'gog'].includes(shopClass)
                ? ' <span class="blik-badge">BLIK</span>' : '';
            const isCheapest = highlightOffer && offer.id === highlightOffer.id;

            row.className = 'offer-row offer-row--enter' + (isCheapest ? ' cheapest' : '');
            row.style.setProperty('--enter-i', rowIndex);
            row.style.animationDelay = `${rowIndex * 50}ms`;
            rowIndex += 1;
            const storeClass = String(offer.store_class || '').toUpperCase();
            const isOfficial = storeClass === 'OFFICIAL_STORE'
                || Boolean(offer.is_official)
                || (offer.trust_tier === 'A' && /oficjaln/i.test(offer.trust_label || ''));
            const isAuthorized = storeClass === 'AUTHORIZED_RESELLER'
                || /autoryzowan/i.test(offer.trust_label || '');
            const badgeClass = isOfficial
                ? 'offer-badge--official'
                : isAuthorized
                    ? 'offer-badge--authorized'
                    : `offer-badge--tier-${(offer.trust_tier || 'c').toLowerCase()}`;
            const typeLabel = offer.trust_label
                || (isOfficial
                    ? tt('offer.official')
                    : isAuthorized
                        ? tt('offer.authorized')
                        : tt('offer.marketplace'));
            const noteText = offer.trust_note
                ? offer.trust_note
                : (isOfficial
                    ? tt('offer.official_note')
                    : isAuthorized
                        ? tt('offer.authorized_note')
                        : tt('offer.marketplace_note'));
            const infoBadge = noteText
                ? ` <span class="offer-info" tabindex="0" role="button" aria-label="${escapeHtml(noteText)}" title="${escapeHtml(noteText)}">i</span>`
                : '';
            const refundHtml = offerRefundHtml(offer);
            const warnBadge = offer.low_confidence
                ? ` <span class="offer-warn-badge" title="${escapeHtml(tt('offer.low_conf_note'))}">${tt('offer.check')}</span>`
                : '';
            const act = String(offer.activation_region || '').toLowerCase();
            const regionLabel = act === 'na'
                ? tt('offer.region_na')
                : act === 'eu'
                    ? tt('offer.region_eu')
                    : act === 'global'
                        ? tt('offer.region_global')
                        : '';
            const regionBadge = regionLabel
                ? ` <span class="badge badge-region">${escapeHtml(regionLabel)}</span>`
                : '';
            const buyLabel = isCheapest ? tt('offer.buy_cheapest', { price: formatPln(offer.price_pln) }) : tt('offer.buy');
            const orig = Number(offer.original_price_pln);
            const hasDiscount = Number.isFinite(orig) && orig > Number(offer.price_pln) + 0.01;
            const priceHtml = hasDiscount
                ? `<span class="offer-price"><span class="offer-price-old">${formatPln(orig)}</span> ${formatPln(offer.price_pln, { html: true })}</span>`
                : `<span class="offer-price">${formatPln(offer.price_pln, { html: true })}</span>`;
            const bestBadge = isCheapest
                ? '<span class="offer-best-badge">NAJNIŻSZA CENA</span>'
                : '';
            row.innerHTML = `
                <div class="offer-row-main">
                    <span class="offer-shop shop-${shopClass}">${offer.shop_name}${blik}</span>
                    <span class="offer-type"><span class="offer-badge ${badgeClass}">${typeLabel}</span>${infoBadge}${warnBadge}${regionBadge}${refundHtml}</span>
                </div>
                ${priceHtml}
                ${bestBadge}
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
        if (e.key === 'Escape') closeMobileDrawer();
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            focusMobileSearch();
        }
    });

    function isMobileViewport() {
        return window.matchMedia('(max-width: 767px)').matches;
    }

    function focusMobileSearch() {
        const heroInput = document.getElementById('hero-search-input');
        const target = (isMobileViewport() && heroInput) ? heroInput : searchInput;
        if (!target) return;
        try {
            target.focus({ preventScroll: false });
        } catch (_) {
            target.focus();
        }
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        if (typeof target.select === 'function') target.select();
    }

    function openMobileDrawer() {
        const drawer = document.getElementById('m-drawer');
        const btn = document.getElementById('m-menu-btn');
        if (!drawer) return;
        drawer.hidden = false;
        document.body.classList.add('mmenu-open');
        if (btn) btn.setAttribute('aria-expanded', 'true');
        syncMobileDrawerAuth();
        document.getElementById('m-drawer-close')?.focus();
    }

    function closeMobileDrawer() {
        const drawer = document.getElementById('m-drawer');
        const btn = document.getElementById('m-menu-btn');
        if (!drawer || drawer.hidden) return;
        drawer.hidden = true;
        document.body.classList.remove('mmenu-open');
        if (btn) {
            btn.setAttribute('aria-expanded', 'false');
            btn.focus();
        }
    }

    function syncMobileDrawerAuth() {
        const host = document.getElementById('m-drawer-auth');
        if (!host) return;
        if (typeof isLoggedIn === 'function' && isLoggedIn()) {
            document.body.classList.add('is-logged-in');
            host.innerHTML = `
                <a class="m-btn-primary" href="panel">Mój panel</a>
                <button type="button" class="m-btn-ghost" id="m-drawer-logout">Wyloguj</button>
            `;
            host.querySelector('#m-drawer-logout')?.addEventListener('click', () => {
                document.getElementById('btn-logout')?.click();
                closeMobileDrawer();
            });
        } else {
            document.body.classList.remove('is-logged-in');
            host.innerHTML = `
                <a class="m-btn-primary" href="register">Załóż darmowe konto</a>
                <a class="m-btn-ghost" href="login">Zaloguj się</a>
            `;
        }
    }

    async function refreshMobilePromoCounts() {
        const trackedEl = document.getElementById('m-promo-tracked');
        const alertsEl = document.getElementById('m-promo-alerts');
        if (!trackedEl || !alertsEl) return;
        if (typeof isLoggedIn !== 'function' || !isLoggedIn()) {
            document.body.classList.remove('is-logged-in');
            trackedEl.textContent = '—';
            alertsEl.textContent = '—';
            return;
        }
        document.body.classList.add('is-logged-in');
        try {
            const res = await authFetch('favorites');
            if (!res?.ok) return;
            const data = await res.json();
            const list = Array.isArray(data) ? data : (data.items || data.favorites || []);
            trackedEl.textContent = String(list.length);
            const alertsOn = list.filter((g) => g && g.alert_enabled).length;
            alertsEl.textContent = String(alertsOn);
        } catch (_) {
            trackedEl.textContent = String(watchedSlugs?.size || '—');
            alertsEl.textContent = '—';
        }
    }

    function initMobileChrome() {
        document.getElementById('m-menu-btn')?.addEventListener('click', openMobileDrawer);
        document.getElementById('m-drawer-close')?.addEventListener('click', closeMobileDrawer);
        document.getElementById('m-drawer-overlay')?.addEventListener('click', closeMobileDrawer);
        document.getElementById('m-search-btn')?.addEventListener('click', () => {
            closeMobileDrawer();
            focusMobileSearch();
        });
        document.getElementById('m-nav-search')?.addEventListener('click', focusMobileSearch);
        document.getElementById('m-nav-more')?.addEventListener('click', openMobileDrawer);

        const heroForm = document.getElementById('m-hero-search');
        const heroInput = document.getElementById('hero-search-input');
        if (heroForm && heroInput && searchInput) {
            heroInput.addEventListener('input', () => {
                searchInput.value = heroInput.value;
                searchInput.dispatchEvent(new Event('input', { bubbles: true }));
            });
            heroForm.addEventListener('submit', (e) => {
                e.preventDefault();
                const q = heroInput.value.trim();
                searchInput.value = q;
                if (q) runSearch(q);
                else showHomeView();
            });
            searchInput.addEventListener('input', () => {
                if (heroInput.value !== searchInput.value) heroInput.value = searchInput.value;
            });
        }

        const sortTabs = document.getElementById('m-sort-tabs');
        if (sortTabs && !sortTabs.dataset.bound) {
            sortTabs.dataset.bound = '1';
            sortTabs.addEventListener('click', (e) => {
                const btn = e.target.closest('button[data-sort]');
                if (!btn) return;
                applySortValue(btn.dataset.sort || '');
            });
            syncSortTabs(currentSort);
        }

        if (d3Cats && !d3Cats.dataset.bound) {
            d3Cats.dataset.bound = '1';
            d3Cats.addEventListener('click', (e) => {
                const cat = e.target.closest('.cat');
                if (!cat || cat.tagName === 'A') return;
                e.preventDefault();
                const slug = cat.dataset.slug || '';
                selectCategory(slug, cat.textContent.trim(), true);
            });
        }

        if (d3Discover && !d3Discover.dataset.bound) {
            d3Discover.dataset.bound = '1';
            d3Discover.addEventListener('click', (e) => {
                const btn = e.target.closest('[data-d3-sort]');
                if (!btn) return;
                e.preventDefault();
                const sort = btn.getAttribute('data-d3-sort') || '';
                currentCategory = '';
                currentCategoryName = '';
                currentQuery = '';
                if (searchInput) searchInput.value = '';
                showCatalogView();
                gamesHeading.textContent = tt('catalog.all_games');
                updateCatalogSubtitle();
                syncActiveCats('');
                applySortValue(sort);
                document.getElementById('catalog-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
        }

        syncHeroTitleMode();
        syncDesktopAccountChrome();
        syncMobileDrawerAuth();
        document.addEventListener('langchange', () => {
            syncMobileDrawerAuth();
            refreshMobilePromoCounts();
            syncDesktopAccountChrome();
            syncHeroTitleMode();
        });
        const authNav = document.getElementById('auth-nav');
        if (authNav && typeof MutationObserver !== 'undefined') {
            new MutationObserver(() => {
                syncMobileDrawerAuth();
                refreshMobilePromoCounts();
                syncDesktopAccountChrome();
            }).observe(authNav, { childList: true, subtree: true });
        }

        let d3ResizeTimer = 0;
        window.addEventListener('resize', () => {
            window.clearTimeout(d3ResizeTimer);
            d3ResizeTimer = window.setTimeout(() => {
                if (!currentCategory && !currentQuery) setBrowseMode('home');
                else setBrowseMode('catalog');
            }, 120);
        });
    }

    initMobileChrome();

    loadCategories();
    loadCatalogStats();
    setInterval(loadCatalogStats, 5 * 60 * 1000);
    loadHomeSections();
    initOffersScanShops();
    if (isLoggedIn()) loadWatchedSlugs();

    document.addEventListener('shoppingregionchange', () => {
        loadHomeSections();
        if (currentCategory || currentQuery) fetchGames(1, false);
        if (!modal.hidden && currentGameSlug) {
            showGameDetails(currentGameSlug);
        }
    });

    document.addEventListener('langchange', () => {
        if (window.I18n) I18n.applyPage();
        syncDesktopAccountChrome();
        syncDesktopCats();
        const allCat = categoriesBar?.querySelector('.cat[data-slug=""]');
        if (allCat) allCat.textContent = tt('cat.all');
        if (!currentCategory && !currentQuery) gamesHeading.textContent = tt('catalog.all_games');
        document.querySelectorAll('.btn-watch-card, #btn-favorite').forEach((btn) => {
            const slug = btn.dataset.slug;
            if (!slug) return;
            updateWatchButton(btn, watchedSlugs.has(slug));
        });
        if (btnAlert && isLoggedIn() && isFavorited) updateAlertButton(alertEnabled);
        if (d3HeroGames.length) paintDesktopHeroSlide();
        // Refresh home cards when language/region USD display may change
        if (!currentCategory && !currentQuery) loadHomeSections();
        else if (currentCategory || currentQuery) fetchGames(1, false);
    });

    document.addEventListener('regionready', () => {
        if (window.KupujPLRegion?.shouldShowUsd?.() && !currentCategory && !currentQuery) {
            loadHomeSections();
        }
    });

    const pathGra = location.pathname.match(/\/gra\/([^/]+)/);
    const deepLinkGra = pathGra ? decodeURIComponent(pathGra[1]) : new URLSearchParams(location.search).get('gra');
    const urlQuery = new URLSearchParams(location.search).get('q');
    if (urlQuery && urlQuery.trim()) {
        searchInput.value = urlQuery.trim();
        runSearch(urlQuery.trim());
    } else if (deepLinkGra) {
        location.replace(`gra/${encodeURIComponent(deepLinkGra)}`);
    }
});

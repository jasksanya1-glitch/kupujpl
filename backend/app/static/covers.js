/** Shared Steam cover URLs + fallback chain for game cards. */
const PLACEHOLDER_COVER =
    'data:image/svg+xml,' +
    encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="460" height="215">' +
            '<rect fill="#1f1f1f" width="100%" height="100"/>' +
            '<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" ' +
            'fill="#aaa" font-family="Inter,sans-serif" font-size="14">Brak okładki</text>' +
            '</svg>'
    );

const STEAM_CDN = 'https://shared.cloudflare.steamstatic.com';
const LEGACY_CDN = 'https://cdn.akamai.steamstatic.com';

function normalizeCoverUrl(url) {
    if (!url || !String(url).trim()) return null;
    let u = String(url).trim();
    if (!u || u === 'null' || u === 'undefined') return null;
    // Guard against bad relative joins like "/games/https://..."
    u = u.replace(/^\/games\/(https?:\/\/)/i, '$1');
    if (u.startsWith('//')) u = `https:${u}`;
    if (u.startsWith('http://')) u = `https://${u.slice(7)}`;
    return u
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

/** Large wide Steam hero art (~1920×620) — use for homepage hero, not tiny header.jpg. */
function steamHeroFallbackUrls(steamAppid) {
    if (!steamAppid) return [];
    const id = String(steamAppid);
    return [
        `${STEAM_CDN}/store_item_assets/steam/apps/${id}/library_hero.jpg`,
        `${STEAM_CDN}/steam/apps/${id}/library_hero.jpg`,
        `${STEAM_CDN}/store_item_assets/steam/apps/${id}/header.jpg`,
        `${STEAM_CDN}/steam/apps/${id}/header.jpg`,
        `${STEAM_CDN}/store_item_assets/steam/apps/${id}/capsule_616x353.jpg`,
        `${STEAM_CDN}/steam/apps/${id}/capsule_616x353.jpg`,
        `${LEGACY_CDN}/steam/apps/${id}/header.jpg`,
        `${LEGACY_CDN}/steam/apps/${id}/capsule_616x353.jpg`,
    ];
}

function isGenericSteamCover(url) {
    if (!url) return false;
    return /\/apps\/\d+\/(header|capsule_616x353)\.jpg/i.test(url);
}

/** HD covers first; keep working Steam search thumbs in the chain. */
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

function isPortraitCoverUrl(url) {
    if (!url) return false;
    return /library_600x900|portrait|vertical/i.test(url)
        && !/library_hero|header|capsule_616|header_alt/i.test(url);
}

function isHeroWideCoverUrl(url) {
    if (!url || isPortraitCoverUrl(url)) return false;
    return /\/(library_hero|header|header_alt_assets|capsule_616x353)/i.test(url);
}

/** Prefer Steam library_hero (HD wide) for featured/hero banners. */
function featuredCoverChain(game) {
    const hero = steamHeroFallbackUrls(game?.steam_appid);
    const chain = [...hero, ...coverChainForGame(game)].filter(Boolean);
    const wide = [];
    const other = [];
    chain.forEach((u) => {
        if (isHeroWideCoverUrl(u)) wide.push(u);
        else other.push(u);
    });
    // library_hero first among wide assets
    wide.sort((a, b) => {
        const score = (u) => (/library_hero/i.test(u) ? 0 : /\/header(\.jpg|_alt)/i.test(u) ? 1 : 2);
        return score(a) - score(b);
    });
    const out = [...wide, ...other, PLACEHOLDER_COVER];
    return [...new Set(out.map(normalizeCoverUrl).filter(Boolean))];
}

function featuredCoverInfo(game) {
    const chain = featuredCoverChain(game);
    const src = chain[0] || PLACEHOLDER_COVER;
    return { src, isPortrait: isPortraitCoverUrl(src), chain };
}

function bindCoverFallback(img, gameOrAppid, opts) {
    if (!img) return;
    const game =
        typeof gameOrAppid === 'object' && gameOrAppid !== null
            ? gameOrAppid
            : { steam_appid: gameOrAppid };
    const preferWide = !!(opts && opts.preferWide);
    const chain = preferWide
        ? featuredCoverChain(game)
        : [...coverChainForGame(game), PLACEHOLDER_COVER];
    const unique = [...new Set(chain.map(normalizeCoverUrl).filter(Boolean))];
    if (!unique.length) unique.push(PLACEHOLDER_COVER);
    img.dataset.fallbackStep = '0';
    if (!img.getAttribute('src') && unique[0]) img.src = unique[0];
    img.onerror = () => {
        const next = parseInt(img.dataset.fallbackStep || '0', 10) + 1;
        if (next < unique.length) {
            img.dataset.fallbackStep = String(next);
            img.src = unique[next];
        }
    };
}

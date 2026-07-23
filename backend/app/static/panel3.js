(function () {
    function agentDebugLog() { /* debug telemetry removed */ }

    window.addEventListener('error', (event) => {
        agentDebugLog('pre-fix', 'D', 'app/static/panel3.js:window.error', 'Panel3 runtime error', {
            message: event.message,
            source: event.filename,
            line: event.lineno,
            column: event.colno,
        });
    });

    window.addEventListener('unhandledrejection', (event) => {
        agentDebugLog('pre-fix', 'D', 'app/static/panel3.js:unhandledrejection', 'Panel3 unhandled promise rejection', {
            reason: String(event.reason && (event.reason.message || event.reason)),
        });
    });
    // #endregion

    const STATS_POLL_MS = 60000;
    const TIER_A_POLL_MS = 5000;
    const NOTIF_TTL_MS = 12000;
    const SS_USER = 'panel3_last_user_id';
    const SS_VISIT = 'panel3_last_visit_id';
    const SS_NOTIFIED_USERS = 'panel3_notified_users';
    const SS_NOTIFIED_VISITS = 'panel3_notified_visits';
    const NOTIFIED_CAP = 200;

    let eventsReady = false;

    function loadCursor(key) {
        try {
            const raw = sessionStorage.getItem(key);
            if (raw != null) return Math.max(0, parseInt(raw, 10) || 0);
        } catch (_) { /* ignore */ }
        return 0;
    }

    function saveCursor(key, value) {
        try {
            sessionStorage.setItem(key, String(Math.max(0, value | 0)));
        } catch (_) { /* ignore */ }
    }

    function loadNotifiedSet(key) {
        const set = new Set();
        try {
            const raw = sessionStorage.getItem(key);
            if (!raw) return set;
            raw.split(',').forEach((part) => {
                const id = parseInt(part, 10);
                if (id > 0) set.add(id);
            });
        } catch (_) { /* ignore */ }
        return set;
    }

    function saveNotifiedSet(key, set) {
        try {
            const ids = [...set].filter((id) => id > 0).slice(-NOTIFIED_CAP);
            sessionStorage.setItem(key, ids.join(','));
        } catch (_) { /* ignore */ }
    }

    function persistEventCursors() {
        saveCursor(SS_USER, lastUserId);
        saveCursor(SS_VISIT, lastVisitId);
        saveNotifiedSet(SS_NOTIFIED_USERS, notifiedUserIds);
        saveNotifiedSet(SS_NOTIFIED_VISITS, notifiedVisitIds);
    }

    let lastUserId = loadCursor(SS_USER);
    let lastVisitId = loadCursor(SS_VISIT);
    const notifiedUserIds = loadNotifiedSet(SS_NOTIFIED_USERS);
    const notifiedVisitIds = loadNotifiedSet(SS_NOTIFIED_VISITS);

    function fmtDate(iso) {
        if (!iso) return '—';
        try {
            const d = new Date(iso);
            return d.toLocaleString('uk-UA', { dateStyle: 'short', timeStyle: 'short' });
        } catch {
            return iso;
        }
    }

    function esc(text) {
        return String(text ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function kpi(label, value, sub, live) {
        return `<div class="panel3-kpi${live ? ' panel3-kpi--live' : ''}">
            <div class="panel3-kpi__value">${value}</div>
            <div class="panel3-kpi__label">${label}</div>
            ${sub ? `<div class="panel3-kpi__sub">${sub}</div>` : ''}
        </div>`;
    }

    function removeNotif(el) {
        if (!el || !el.parentNode) return;
        el.classList.add('hide');
        setTimeout(() => el.remove(), 300);
    }

    function pushNotif(kind, icon, title, name, sub) {
        // Popup notifications are disabled. Keep event polling/cursors working
        // without showing "new user" / "new guest" toasts in Panel3.
        return;
    }

    function notifyNewUser(u) {
        pushNotif('user', '👤', 'Games · новий користувач', u.email || '—', fmtDate(u.created_at));
    }

    function notifyNewVisit(v) {
        if (v.user) return;
        const loc = v.geo ? `📍 ${v.geo}` : '📍 ?';
        if (v.agent === 'cursor') {
            pushNotif('visit', '🌐', 'Games · Cursor', 'Cursor', `${loc} · ${v.path || '/'}`);
            return;
        }
        pushNotif('visit', '🌐', 'Games · новий гість', 'Гість', `${loc} · ${v.path || '/'}`);
    }

    function processEvents(data) {
        const users = data.users || [];
        const visits = data.visits || [];

        if (!eventsReady) {
            eventsReady = true;
            const coldStart = lastUserId === 0 && lastVisitId === 0;
            if (coldStart) {
                lastUserId = data.max_user_id || 0;
                lastVisitId = data.max_visit_id || 0;
                users.forEach((u) => {
                    if (u.id) notifiedUserIds.add(u.id);
                });
                visits.forEach((v) => {
                    if (v.id) notifiedVisitIds.add(v.id);
                });
                persistEventCursors();
                return;
            }
        }

        let maxUserId = lastUserId;
        let maxVisitId = lastVisitId;

        users.forEach((u) => {
            if (!u.id) return;
            maxUserId = Math.max(maxUserId, u.id);
            if (u.id <= lastUserId || notifiedUserIds.has(u.id)) return;
            notifiedUserIds.add(u.id);
            notifyNewUser(u);
        });

        visits.forEach((v) => {
            if (!v.id) return;
            maxVisitId = Math.max(maxVisitId, v.id);
            if (v.id <= lastVisitId || notifiedVisitIds.has(v.id)) return;
            notifiedVisitIds.add(v.id);
            notifyNewVisit(v);
        });

        if (typeof data.max_user_id === 'number') maxUserId = Math.max(maxUserId, data.max_user_id);
        if (typeof data.max_visit_id === 'number') maxVisitId = Math.max(maxVisitId, data.max_visit_id);

        lastUserId = maxUserId;
        lastVisitId = maxVisitId;
        persistEventCursors();
    }

    async function pollEvents() {
        const q = new URLSearchParams({
            last_user_id: String(lastUserId),
            last_visit_id: String(lastVisitId),
        });
        const res = await fetch(`api/admin/events?${q}`, { credentials: 'same-origin' });
        if (res.status === 401) {
            window.location.href = 'panel3';
            return;
        }
        if (!res.ok) return;
        processEvents(await res.json());
    }

    function trafficWhoCell(v) {
        if (v.agent === 'cursor') {
            return `<span class="panel3-traffic-who panel3-traffic-who--cursor" title="Cursor IDE — agent test">
                <span class="panel3-traffic-icon" aria-hidden="true">⌁</span>
                <span class="panel3-traffic-label">Cursor</span>
            </span>`;
        }
        const isGuest = v.guest !== false && !v.user;
        if (isGuest) {
            return `<span class="panel3-traffic-who panel3-traffic-who--guest" title="Гість — bez logowania">
                <span class="panel3-traffic-icon" aria-hidden="true">◎</span>
                <span class="panel3-traffic-label">Гість</span>
            </span>`;
        }
        return `<span class="panel3-traffic-who panel3-traffic-who--user" title="Zarejestrowany użytkownik">
            <span class="panel3-traffic-icon" aria-hidden="true">👤</span>
            <span class="panel3-traffic-label">${esc(v.user)}</span>
            <span class="panel3-traffic-badge">konto</span>
        </span>`;
    }

    function renderTrafficLegend(t) {
        const el = document.getElementById('traffic-user-legend');
        if (!el) return;
        const reg15 = t.registered_views_15m ?? 0;
        const guest15 = t.guest_views_15m ?? 0;
        const reg24 = t.registered_views_24h ?? 0;
        const guest24 = t.guest_views_24h ?? 0;
        const crawler15 = t.crawler_views_15m ?? 0;
        const crawler24 = t.crawler_views_24h ?? 0;
        el.innerHTML = `
            <div class="panel3-traffic-legend-bar-inner">
                <span class="panel3-traffic-legend-title">Користувачі у трафіку</span>
                <span class="panel3-traffic-who panel3-traffic-who--user panel3-traffic-who--inline" title="Zalogowany użytkownik — widać e-mail">
                    <span class="panel3-traffic-icon" aria-hidden="true">👤</span>
                    <span>Зареєстрований</span>
                    <strong>${reg15}</strong><span class="panel3-traffic-legend-muted">/15хв</span>
                    <strong>${reg24}</strong><span class="panel3-traffic-legend-muted">/24г</span>
                </span>
                <span class="panel3-traffic-who panel3-traffic-who--guest panel3-traffic-who--inline" title="Gość bez konta">
                    <span class="panel3-traffic-icon" aria-hidden="true">◎</span>
                    <span>Гість</span>
                    <strong>${guest15}</strong><span class="panel3-traffic-legend-muted">/15хв</span>
                    <strong>${guest24}</strong><span class="panel3-traffic-legend-muted">/24г</span>
                </span>
                <span class="panel3-traffic-who panel3-traffic-who--inline" title="Bot/crawler traffic">
                    <span class="panel3-traffic-icon" aria-hidden="true">🤖</span>
                    <span>Crawler</span>
                    <strong>${crawler15}</strong><span class="panel3-traffic-legend-muted">/15хв</span>
                    <strong>${crawler24}</strong><span class="panel3-traffic-legend-muted">/24г</span>
                </span>
            </div>`;
    }

    function renderTraffic(t) {
        document.getElementById('traffic-kpis').innerHTML = [
            kpi('Унікальні (15 хв)', t.unique_15m, `${t.views_15m} переглядів`, true),
            kpi('👤 Konta (15 хв)', t.registered_views_15m ?? 0, `${t.guest_views_15m ?? 0} gości`),
            kpi('Унікальні (24 год)', t.unique_24h, `${t.views_24h} переглядів`),
            kpi('👤 Konta (24 год)', t.registered_views_24h ?? 0, `${t.guest_views_24h ?? 0} gości`),
            kpi('🤖 Crawler (15 хв)', t.crawler_unique_15m ?? 0, `${t.crawler_views_15m ?? 0} переглядів`),
            kpi('🤖 Crawler (24 год)', t.crawler_unique_24h ?? 0, `${t.crawler_views_24h ?? 0} переглядів`),
        ].join('');
        renderTrafficLegend(t);

        const recent = t.recent || [];
        document.getElementById('traffic-recent').innerHTML = recent.length
            ? `<table class="panel3-table"><thead><tr><th>Час</th><th>Звідки</th><th>Сторінка</th><th><span class="panel3-th-who"><span aria-hidden="true">👤</span> Хто</span></th></tr></thead><tbody>${
                  recent
                      .map(
                          (v) => `<tr class="${v.guest === false || v.user ? 'panel3-traffic-row--user' : 'panel3-traffic-row--guest'}">
                <td>${fmtDate(v.at)}</td>
                <td>${v.geo ? esc(v.geo) : '<span class="panel3-muted">—</span>'}</td>
                <td><code>${esc(v.path)}</code></td>
                <td>${trafficWhoCell(v)}</td>
            </tr>`
                      )
                      .join('')
              }</tbody></table>`
            : '<p class="panel3-muted">Немає візитів — відкрийте магазин у режимі інкогніто.</p>';

        const paths = t.top_paths || [];
        document.getElementById('traffic-paths').innerHTML = paths.length
            ? paths.map((p) => `<li><code>${p.path}</code><strong>${p.count}</strong></li>`).join('')
            : '<li class="panel3-muted">—</li>';
    }

    function renderClicks(c, cfg) {
        const elKpis = document.getElementById('click-kpis');
        if (!elKpis) return;
        elKpis.innerHTML = [
            kpi('Кліки (24 год)', c.clicks_24h ?? 0, null, true),
            kpi('Кліки (7 днів)', c.clicks_7d ?? 0, `${c.tracked_clicks_7d ?? 0} tracked`),
            kpi('Monetized (7д)', c.monetized_clicks_7d ?? 0, `${c.untracked_clicks_7d ?? 0} без трекінгу`),
        ].join('');

        const byShop = c.by_shop || [];
        document.getElementById('click-by-shop').innerHTML = byShop.length
            ? `<table class="panel3-table"><thead><tr><th>Магазин</th><th>Кліки</th><th>Tracked</th><th>Останній клік</th></tr></thead><tbody>${
                  byShop.map((r) => `<tr><td>${esc(r.shop)}</td><td>${r.clicks}</td><td>${r.tracked}</td><td>${fmtDate(r.last_clicked_at)}</td></tr>`).join('')
              }</tbody></table>`
            : '<p class="panel3-muted">Ще немає кліків після деплою /api/go.</p>';

        const items = (cfg && cfg.items) || [];
        document.getElementById('affiliate-config-box').innerHTML = items.length
            ? `<table class="panel3-table"><thead><tr><th>Магазин</th><th>Env</th><th>Статус</th></tr></thead><tbody>${
                  items.map((i) => `<tr><td>${esc(i.shop)}</td><td><code>${esc(i.env)}</code></td><td>${i.configured ? '✓' : '<span class="panel3-warn">brak ID</span>'}</td></tr>`).join('')
              }</tbody></table><p class="panel3-muted">${esc(cfg.note || '')}</p>`
            : '<p class="panel3-muted">—</p>';

        const recent = c.recent || [];
        document.getElementById('click-recent').innerHTML = recent.length
            ? `<table class="panel3-table"><thead><tr><th>Час</th><th>Гра</th><th>Магазин</th><th>Ціна</th><th>Tracked</th></tr></thead><tbody>${
                  recent.map((r) => `<tr>
                <td>${fmtDate(r.clicked_at)}</td>
                <td>${esc(r.game_title || r.game_slug || '')}</td>
                <td>${esc(r.shop_name)}</td>
                <td>${r.price_pln != null ? Number(r.price_pln).toFixed(2) + ' zł' : '—'}</td>
                <td>${r.has_tracking ? '✓' : '—'}</td>
            </tr>`).join('')
              }</tbody></table>`
            : '<p class="panel3-muted">Немає кліків.</p>';
    }

    function renderUsers(u) {
        document.getElementById('user-kpis').innerHTML = [
            kpi('Акаунти', u.total, null),
            kpi('Онлайн (15 хв)', u.online_15m, null, true),
            kpi('Реєстрації (7 днів)', u.signups_7d, null),
            kpi('Обране / корист.', u.favorites_total, `${u.users_with_favorites} корист.`),
        ].join('');

        const online = u.online || [];
        document.getElementById('users-online').innerHTML = online.length
            ? `<table class="panel3-table"><thead><tr><th>Email</th><th>Останній раз</th></tr></thead><tbody>${online
                  .map((x) => `<tr><td>${x.email}</td><td>${fmtDate(x.last_seen_at)}</td></tr>`)
                  .join('')}</tbody></table>`
            : '<p class="panel3-muted">Нікого онлайн.</p>';

        const recent = u.recent || [];
        document.getElementById('users-recent').innerHTML = recent.length
            ? `<table class="panel3-table"><thead><tr><th>Email</th><th>Реєстрація</th><th>Останній раз</th></tr></thead><tbody>${recent
                  .map(
                      (x) => `<tr><td>${x.email}</td><td>${fmtDate(x.created_at)}</td><td>${fmtDate(x.last_seen_at)}</td></tr>`
                  )
                  .join('')}</tbody></table>`
            : '<p class="panel3-muted">Немає користувачів.</p>';
    }

    function fmtNum(n) {
        if (n == null || Number.isNaN(n)) return '—';
        return Number(n).toLocaleString('uk-UA');
    }

    function renderOfferCoverage(cov) {
        if (!cov) return;
        const dist = cov.shop_count_distribution || {};
        const expected = (cov.expected_shops || []).length;
        const target = cov.min_shops_target || 4;
        const targetHint = document.getElementById('coverage-target-hint');
        if (targetHint) targetHint.textContent = String(target);

        document.getElementById('coverage-kpis').innerHTML = [
            kpi(
                'Ігор з цінами',
                fmtNum(cov.games_with_offers),
                'є хоча б 1 пропозиція (in_stock) у БД'
            ),
            kpi(
                'Лише 1 магазин',
                fmtNum(cov.steam_only_games),
                'часто лише Steam — слабке порівняння',
                true
            ),
            kpi(
                '≥2 магазини',
                fmtNum(cov.multi_shop_games),
                'користувач бачить вибір цін'
            ),
            kpi(
                `< ${target} магазинів`,
                fmtNum(cov.sparse_games_lt_target),
                'потребує скану / upload з PC'
            ),
            kpi(
                `Усі ${expected} магазинів`,
                fmtNum(cov.full_coverage_games),
                'рідко; keyshop-и часто падають на VPS'
            ),
        ].join('');

        const shops = cov.offers_by_shop || {};
        const expectedList = cov.expected_shops || Object.keys(shops);
        const rows = expectedList.map((name) => {
            const cnt = shops[name] || 0;
            const miss = (cov.games_missing_shop || {})[name];
            const warn = cnt === 0 ? ' panel3-row--warn' : '';
            return `<tr class="${warn}"><td>${esc(name)}</td><td><strong>${fmtNum(cnt)}</strong> <span class="panel3-cell-hint">ігор з ціною</span></td><td class="panel3-muted">${fmtNum(miss)} <span class="panel3-cell-hint">без ціни тут</span></td></tr>`;
        });
        document.getElementById('coverage-shops-table').innerHTML = rows.length
            ? `<table class="panel3-table"><thead><tr><th>Магазин</th><th>Є ціна</th><th>Ще немає</th></tr></thead><tbody>${rows.join('')}</tbody></table>`
            : '<p class="panel3-muted">—</p>';

        const distEntries = Object.entries(dist)
            .map(([k, v]) => [Number(k), v])
            .sort((a, b) => a[0] - b[0]);
        const shopWord = (n) => {
            if (n === 1) return 'магазин';
            if (n >= 2 && n <= 4) return 'магазини';
            return 'магазинів';
        };
        const gameWord = (n) => {
            const mod10 = n % 10;
            const mod100 = n % 100;
            if (mod10 === 1 && mod100 !== 11) return 'гра';
            if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'гри';
            return 'ігор';
        };
        document.getElementById('coverage-distribution').innerHTML = distEntries.length
            ? distEntries
                  .map(
                      ([shopCount, games]) =>
                          `<li><span>${shopCount} ${shopWord(shopCount)}${shopCount >= expected ? ' ✓' : ''}</span><strong>${fmtNum(games)} ${gameWord(games)}</strong></li>`
                  )
                  .join('')
            : '<li class="panel3-muted">—</li>';

        const cmd = document.getElementById('worker-cmd');
        if (cmd) {
            cmd.textContent = [
                'cd D:\\CursorProjects\\kupujpl-games\\backend',
                '$env:GAMES_API_URL = "https://kupujpl.pl/games"',
                '$env:PANEL3_ACCESS_CODE = "ВАШ_КОД_PANEL3"',
                'python tools/local_offer_worker.py --limit 15 --shops Eneba,G2A,CDKeys',
            ].join('\n');
        }

        const ws = cov.local_worker || {};
        const wsEl = document.getElementById('worker-stats');
        if (wsEl) {
            const has = ws.offers_upserted != null;
            wsEl.innerHTML = has
                ? `<p>Останній upload з домашнього PC: <strong>${fmtNum(ws.offers_upserted)}</strong> нових/оновлених пропозицій у <strong>${fmtNum(ws.games_touched)}</strong> іграх · джерело: <code>${esc(ws.source || '—')}</code> · ${fmtDate(ws.updated_at)}</p>`
                : '<p class="panel3-muted">Ще не було uploadів з PC — keyshop-и (Eneba, G2A, CDKeys) на VPS часто недоступні.</p>';
        }
    }

    function renderCatalog(c, topWatched) {
        document.getElementById('catalog-kpis').innerHTML = [
            kpi('Ігор у базі', c.total_games, null),
            kpi('З Steam', c.steam_enriched, `${c.not_enriched} без даних`),
            kpi('Без пропозицій', c.zero_offers, null),
            kpi('З пропозиціями', c.games_with_offers, null),
        ].join('');

        const shops = c.offers_by_shop || {};
        const shopEntries = Object.entries(shops).sort((a, b) => b[1] - a[1]);
        document.getElementById('offers-shops').innerHTML = shopEntries.length
            ? shopEntries.map(([name, cnt]) => `<li><span>${name}</span><strong>${cnt}</strong></li>`).join('')
            : '<li class="panel3-muted">—</li>';

        document.getElementById('top-watched').innerHTML = (topWatched || []).length
            ? topWatched
                  .map((g) => `<li><span>${g.title}</span><strong>${g.count}×</strong></li>`)
                  .join('')
            : '<li class="panel3-muted">Немає обраного.</li>';
    }

    function fmtDuration(sec) {
        if (sec == null || sec === '' || Number.isNaN(Number(sec))) return '';
        const total = Math.max(0, Math.round(Number(sec)));
        const h = Math.floor(total / 3600);
        const m = Math.floor((total % 3600) / 60);
        const s = total % 60;
        if (h > 0) return `${h} год ${m} хв`;
        if (m > 0) return `${m} хв ${s} с`;
        return `${s} с`;
    }

    function workerDurationSec(worker) {
        if (!worker) return null;
        if (worker.duration_sec != null && Number(worker.duration_sec) > 0) {
            return Math.round(Number(worker.duration_sec));
        }
        if (worker.phase === 'done' && worker.elapsed_sec != null && Number(worker.elapsed_sec) > 0) {
            return Math.round(Number(worker.elapsed_sec));
        }
        if (worker.phase === 'done' && worker.started_at && worker.finished_at) {
            try {
                const ms = new Date(worker.finished_at) - new Date(worker.started_at);
                if (ms > 0) return Math.round(ms / 1000);
            } catch (_) { /* ignore */ }
        }
        return null;
    }

    function fmtEta(sec) {
        if (sec == null || sec === '' || Number.isNaN(Number(sec))) return '—';
        const s = Math.max(0, Math.round(Number(sec)));
        if (s < 60) return `${s} с`;
        const m = Math.floor(s / 60);
        const r = s % 60;
        return r ? `${m} хв ${r} с` : `${m} хв`;
    }

    function phaseClass(phase) {
        if (phase === 'done') return 'panel3-phase--done';
        if (phase === 'rebuild_list' || phase === 'scan_official' || phase === 'scan_keyshops') {
            return 'panel3-phase--active';
        }
        return 'panel3-phase--idle';
    }

    function renderScanWorker(prefix, worker, label) {
        const total = worker.games_total || 0;
        const done = worker.games_done || 0;
        const pct = worker.progress_pct != null ? worker.progress_pct : (total ? done / total * 100 : 0);
        const phase = worker.phase || 'idle';
        const phaseLabel = worker.phase_label || phase;

        const meta = document.getElementById(`tier-a-${prefix}-meta`);
        const bar = document.getElementById(`tier-a-${prefix}-bar`);
        const detail = document.getElementById(`tier-a-${prefix}-detail`);
        if (!meta || !bar || !detail) return;

        meta.innerHTML = `
            <span class="${phaseClass(phase)}">${esc(phaseLabel)}</span>
            <strong>${fmtNum(done)} / ${fmtNum(total)}</strong>`;
        bar.style.width = `${Math.min(100, Math.max(0, pct))}%`;
        const lines = [
            `Прогрес: <strong>${pct.toFixed(1)}%</strong>`,
            worker.phase === 'done' && workerDurationSec(worker)
                ? `Тривалість: <strong>${fmtDuration(workerDurationSec(worker))}</strong>`
                : null,
            worker.phase !== 'done' && worker.games_per_min ? `Швидкість: ${worker.games_per_min} ігор/хв` : null,
            worker.phase !== 'done' && worker.eta_sec != null ? `ETA: ${fmtEta(worker.eta_sec)}` : null,
            worker.phase !== 'done' && worker.current_game ? `Зараз: ${esc(worker.current_game)}` : null,
            worker.updated_at ? `Оновлено: ${fmtDate(worker.updated_at)}` : null,
        ].filter(Boolean);
        detail.innerHTML = lines.join(' · ');
    }

    function renderTierA(t) {
        if (!t) return;
        const vps = t.vps || {};
        const laptop = t.laptop || {};
        const pc = t.pc || {};
        const live = document.getElementById('tier-a-live-badge');
        if (live) live.hidden = !t.scan_active;

        const kpis = document.getElementById('tier-a-kpis');
        if (kpis) {
            kpis.innerHTML = [
                kpi(
                    'Список top-5000',
                    t.list_ready ? 'Готовий' : 'Очікує',
                    `${fmtNum(t.list_count)} ігор · v${t.list_version || '—'}`,
                    t.list_ready
                ),
                kpi('VPS', `${(vps.progress_pct || 0).toFixed(0)}%`, vps.phase_label || '—', vps.phase === 'scan_official'),
                kpi('Ноутбук', `${(laptop.progress_pct || 0).toFixed(0)}%`, laptop.phase_label || '—', laptop.phase === 'scan_keyshops'),
                kpi('ПК', `${(pc.progress_pct || 0).toFixed(0)}%`, pc.phase_label || '—', pc.phase === 'scan_cdkeys'),
                kpi('Наступний scan', fmtDate(t.next_scheduled_at), 'щодня о 10:00'),
            ].join('');
        }

        renderScanWorker('vps', vps, 'VPS');
        renderScanWorker('laptop', laptop, 'Ноутбук');
        renderScanWorker('pc', pc, 'ПК');

        const foot = document.getElementById('tier-a-foot');
        if (foot) {
            const parts = [];
            if (t.cache_rebuilt_at) parts.push(`Список перебудовано: ${fmtDate(t.cache_rebuilt_at)}`);
            if (vps.bootstrap_run_at) parts.push(`Bootstrap VPS: ${fmtDate(vps.bootstrap_run_at)}`);
            if (vps.finished_at && vps.phase === 'done') {
                const dur = workerDurationSec(vps);
                parts.push(dur ? `VPS завершено за ${fmtDuration(dur)}` : `VPS завершено: ${fmtDate(vps.finished_at)}`);
            }
            if (laptop.finished_at && laptop.phase === 'done') {
                const dur = workerDurationSec(laptop);
                parts.push(dur ? `Ноутбук завершено за ${fmtDuration(dur)}` : `Ноутбук завершено: ${fmtDate(laptop.finished_at)}`);
            }
            if (pc.finished_at && pc.phase === 'done') {
                const dur = workerDurationSec(pc);
                parts.push(dur ? `ПК завершено за ${fmtDuration(dur)}` : `ПК завершено: ${fmtDate(pc.finished_at)}`);
            }
            foot.textContent = parts.join(' · ') || 'Скан не активний — очікування наступного запуску о 10:00.';
        }
    }

    function workerLabel(worker) {
        if (worker === 'vps') return 'VPS';
        if (worker === 'pc') return 'ПК';
        if (worker === 'laptop') return 'Ноутбук';
        return worker || '—';
    }

    function speedLabel(speed) {
        if (speed === 'fast_official') return 'офіційний';
        if (speed === 'fast_keyshop') return 'keyshop';
        if (speed === 'slow') return 'повільний';
        return speed || '—';
    }

    function renderScanControls(cfg) {
        const el = document.getElementById('scan-controls');
        if (!el) return;
        const shops = cfg.expected_shops || [];
        const disabled = new Set(cfg.disabled_scan_shops || cfg.disabled_shops || []);
        const routing = cfg.routing || {};
        const speed = cfg.speed || {};
        if (!shops.length) {
            el.innerHTML = '<p class="panel3-muted">Немає конфігурації магазинів.</p>';
            return;
        }
        el.innerHTML = shops
            .map((shop) => {
                const off = disabled.has(shop);
                const btnLabel = off ? 'Увімкнути' : 'Вимкнути';
                const route = workerLabel(routing[shop]);
                const cls = off ? 'panel3-scan-toggle panel3-scan-toggle--on' : 'panel3-scan-toggle panel3-scan-toggle--off';
                return `<div class="panel3-scan-control-row${off ? ' is-disabled' : ''}">
                    <div class="panel3-scan-control-main">
                        <strong>${esc(shop)}</strong>
                        <span>${route} · ${speedLabel(speed[shop])}</span>
                    </div>
                    <div class="panel3-scan-control-state">${off ? 'Скан вимкнено' : 'Скан увімкнено'}</div>
                    <button type="button" class="${cls}" data-shop="${esc(shop)}" data-enabled="${off ? 'true' : 'false'}">${btnLabel}</button>
                </div>`;
            })
            .join('');
        el.querySelectorAll('[data-shop]').forEach((btn) => {
            btn.addEventListener('click', () => toggleScanShop(btn.dataset.shop, btn.dataset.enabled === 'true', btn));
        });
    }

    async function loadScanControls() {
        const el = document.getElementById('scan-controls');
        if (!el) return;
        try {
            const res = await fetch('api/admin/scan-shops', { credentials: 'same-origin' });
            if (res.status === 401) {
                window.location.href = 'panel3';
                return;
            }
            if (!res.ok) throw new Error('HTTP ' + res.status);
            renderScanControls(await res.json());
        } catch (err) {
            el.innerHTML = `<p class="panel3-muted">Не вдалося завантажити кнопки сканів: ${esc(err.message)}</p>`;
        }
    }

    async function toggleScanShop(shop, enabled, btn) {
        const el = document.getElementById('scan-controls');
        if (!shop || !btn) return;
        btn.disabled = true;
        btn.textContent = 'Збереження…';
        try {
            const res = await fetch('api/admin/scan-shops', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ shop, enabled }),
            });
            if (res.status === 401) {
                window.location.href = 'panel3';
                return;
            }
            if (!res.ok) throw new Error('HTTP ' + res.status);
            renderScanControls(await res.json());
            pollTierA().catch(() => {});
        } catch (err) {
            if (el) el.insertAdjacentHTML('afterbegin', `<p class="panel3-muted">Помилка збереження ${esc(shop)}: ${esc(err.message)}</p>`);
            btn.disabled = false;
        }
    }

    function setStopStatus(message) {
        const el = document.getElementById('scan-stop-status');
        if (el) el.textContent = message || '';
    }

    function setStopButtonsDisabled(disabled) {
        ['btn-stop-vps', 'btn-stop-local', 'btn-stop-all-scans'].forEach((id) => {
            const btn = document.getElementById(id);
            if (btn) btn.disabled = disabled;
        });
    }

    async function stopVpsScan() {
        const res = await fetch('api/admin/tier-a/stop-vps', {
            method: 'POST',
            credentials: 'same-origin',
        });
        if (res.status === 401) {
            window.location.href = 'panel3';
            return { ok: false, message: 'Потрібен вхід у Panel3' };
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok && res.status !== 409) {
            throw new Error(data.detail || data.message || `HTTP ${res.status}`);
        }
        return data;
    }

    async function stopLocalScans() {
        const res = await fetch('api/admin/tier-a/stop-local', {
            method: 'POST',
            credentials: 'same-origin',
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 401) {
            window.location.href = 'panel3';
            return { ok: false, message: 'Потрібен вхід у Panel3' };
        }
        if (!res.ok) throw new Error(data.detail || data.message || `HTTP ${res.status}`);
        try {
            const localRes = await fetch('http://127.0.0.1:8878/api/tier-a/stop', {
                method: 'POST',
                mode: 'cors',
            });
            const local = await localRes.json().catch(() => ({}));
            if (localRes.ok) data.killed_pids = local.killed_pids || [];
        } catch (_) {
            data.local_listener_unavailable = true;
        }
        return data;
    }

    async function runStopAction(kind) {
        setStopButtonsDisabled(true);
        setStopStatus('Зупиняю скан…');
        const parts = [];
        try {
            if (kind === 'vps' || kind === 'all') {
                const vps = await stopVpsScan();
                parts.push(vps.message || (vps.ok === false ? 'VPS не був активний' : 'VPS stop sent'));
            }
            if (kind === 'local' || kind === 'all') {
                try {
                    const local = await stopLocalScans();
                    const killed = Array.isArray(local.killed_pids) ? local.killed_pids.length : 0;
                    parts.push(`ПК/ноутбук stop sent (${killed} процесів)`);
                } catch (err) {
                    parts.push(`ПК/ноутбук: ${err.message}`);
                }
            }
            setStopStatus(parts.join(' · '));
            await pollTierA();
        } catch (err) {
            setStopStatus(`Помилка stop: ${err.message}`);
        } finally {
            setStopButtonsDisabled(false);
        }
    }

    function bindStopButtons() {
        document.getElementById('btn-stop-vps')?.addEventListener('click', () => runStopAction('vps'));
        document.getElementById('btn-stop-local')?.addEventListener('click', () => runStopAction('local'));
        document.getElementById('btn-stop-all-scans')?.addEventListener('click', () => runStopAction('all'));
    }

    async function pollTierA() {
        try {
            const res = await fetch('api/admin/tier-a/status', { credentials: 'same-origin' });
            if (res.status === 401) return;
            if (!res.ok) return;
            renderTierA(await res.json());
        } catch (_) { /* ignore */ }
    }

    function renderScheduler(s) {
        const el = document.getElementById('scheduler-box');
        const last = s.last_cycle || {};
        el.innerHTML = `<div class="panel3-pre">Планувальник пропозицій: ${s.running ? 'працює' : 'вимкнено'}
Пакет: ${s.batch_size || '—'} · кожні ${s.interval_sec || '—'} с · швидкий режим=${s.fast_refresh}
Останній цикл: ${last.games_refreshed || 0}/${last.games_selected || 0} ігор
${JSON.stringify(last.offers_by_shop || s.offers_by_shop || {}, null, 2)}

Імпорт Steam: ${JSON.stringify(s.steam_import || {}, null, 2) || '—'}</div>`;
    }

    async function loadStats() {
        const res = await fetch('api/admin/stats', { credentials: 'same-origin' });
        if (res.status === 401) {
            window.location.href = 'panel3';
            return;
        }
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        document.getElementById('generated-at').textContent =
            'Оновлено: ' + fmtDate(data.generated_at);
        renderTraffic(data.traffic || {});
        renderClicks(data.clicks || {}, data.affiliate_config || {});
        renderUsers(data.users || {});
        renderOfferCoverage(data.offer_coverage || {});
        renderTierA(data.tier_a || {});
        renderCatalog(data.catalog || {}, data.top_watched);
        await loadScanControls();
        const sched = { ...(data.scheduler || {}), steam_import: data.catalog?.steam_import };
        renderScheduler(sched);
    }

    async function boot() {
        // #region agent log
        agentDebugLog('pre-fix', 'D', 'app/static/panel3.js:boot', 'Panel3 boot started', {
            hasGeneratedAt: Boolean(document.getElementById('generated-at')),
            hasMain: Boolean(document.getElementById('panel3-main')),
            hasTierA: Boolean(document.getElementById('tier-a-box')),
        });
        // #endregion
        bindStopButtons();
        await loadStats();
        pollEvents().catch(() => {});
        pollTierA().catch(() => {});
        setInterval(() => pollEvents().catch(() => {}), 20000);
        setInterval(() => loadStats().catch(() => {}), STATS_POLL_MS);
        setInterval(() => pollTierA().catch(() => {}), TIER_A_POLL_MS);
    }

    boot().catch((err) => {
        // #region agent log
        agentDebugLog('pre-fix', 'D', 'app/static/panel3.js:boot.catch', 'Panel3 boot failed', {
            message: err.message,
        });
        // #endregion
        const generatedAt = document.getElementById('generated-at');
        if (generatedAt) generatedAt.textContent = `Помилка завантаження: ${err.message}`;
    });
})();

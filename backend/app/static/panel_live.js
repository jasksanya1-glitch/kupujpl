(function () {
    const POLL_MS = 4000;
    const SS_SOUND = 'live_dash_sound';
    const KIND_LABEL = { visit: 'Візит', game: 'Вибрав гру', click: 'Перейшов', signup: 'Реєстр' };
    const KIND_CLASS = { visit: 'visit', game: 'game', click: 'click', signup: 'signup' };

    let knownIds = new Set();
    let firstLoad = true;
    let soundOn = true;
    let pollTimer = null;
    let clockTimer = null;

    const elPulse = document.getElementById('live-pulse');
    const elStatus = document.getElementById('live-status');
    const elKpis = document.getElementById('live-kpis');
    const elSessionsWrap = document.getElementById('live-sessions-wrap');
    const elSessions = document.getElementById('live-sessions');
    const elFeed = document.getElementById('live-feed');
    const elClock = document.getElementById('live-clock');
    const elFootLeft = document.getElementById('live-foot-left');
    const btnSound = document.getElementById('btn-sound');

    try {
        soundOn = sessionStorage.getItem(SS_SOUND) !== '0';
    } catch (_) { /* ignore */ }

    function esc(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function fmtTime(iso) {
        if (!iso) return '—';
        try {
            return new Date(iso).toLocaleTimeString('uk-UA', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
            });
        } catch {
            return '—';
        }
    }

    function updateClock() {
        const now = new Date();
        if (elClock) {
            elClock.textContent = now.toLocaleTimeString('uk-UA', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
            });
        }
    }

    function beep() {
        if (!soundOn) return;
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.value = 880;
            gain.gain.value = 0.08;
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
            osc.stop(ctx.currentTime + 0.26);
        } catch (_) { /* ignore */ }
    }

    function syncSoundBtn() {
        if (!btnSound) return;
        btnSound.textContent = soundOn ? '🔔' : '🔕';
        btnSound.classList.toggle('live-btn--muted', !soundOn);
        btnSound.title = soundOn ? 'Звук увімкнено' : 'Звук вимкнено';
    }

    function kpi(val, lbl, sub, hot) {
        const cls = hot ? ' live-kpi__val--hot' : '';
        return `<div class="live-kpi">
            <div class="live-kpi__val${cls}">${esc(val)}</div>
            <div class="live-kpi__lbl">${esc(lbl)}</div>
            ${sub ? `<div class="live-kpi__sub">${esc(sub)}</div>` : ''}
        </div>`;
    }

    function renderKpis(k) {
        if (!elKpis || !k) return;
        elKpis.innerHTML = [
            kpi(k.visits_5m, 'Візити 5 хв', `${k.unique_5m} унік.`),
            kpi(k.visits_24h, 'Візити 24 год', `${k.unique_24h} унік.`),
            kpi(k.visits_1h, 'Візити 1 год', `${k.unique_1h} унік.`),
            kpi(k.crawler_visits_5m ?? 0, '🤖 Crawlers 5 хв', `24г: ${k.crawler_visits_24h ?? 0}`, (k.crawler_visits_5m ?? 0) > 0),
            kpi(k.clicks_15m, 'Kup 15 хв', `24г: ${k.clicks_24h}`, k.clicks_5m > 0),
            kpi(k.signups_24h, 'Реєстр 24г', `7д: ${k.signups_7d}`, k.signups_24h > 0),
            kpi(k.sessions_active ?? 0, 'На сайті', `${k.users_online_15m} акаунтів`, (k.sessions_active || 0) > 0),
        ].join('');
    }

    function durationBadge(item) {
        if (!item.session_duration_label) return '';
        return ` · <span class="live-row__dur">${esc(item.session_duration_label)}</span>`;
    }

    function renderSessions(sessions) {
        if (!elSessions || !elSessionsWrap) return;
        if (!sessions || !sessions.length) {
            elSessionsWrap.hidden = true;
            elSessions.innerHTML = '';
            return;
        }
        elSessionsWrap.hidden = false;
        elSessions.innerHTML = sessions.map((s) => {
            const who = esc(s.who || (s.agent === 'cursor' ? 'Cursor' : (s.guest ? 'Гість' : 'Користувач')));
            const dur = esc(s.duration_label || '—');
            const meta = [s.geo, s.path].filter(Boolean).map((x) => esc(x)).join(' · ');
            const whoClass = s.agent === 'cursor' ? ' live-session__who--cursor' : '';
            return `<div class="live-session" role="listitem">
                <span class="live-session__who${whoClass}">${who}</span>
                <span class="live-session__dur">${dur}</span>
                ${meta ? `<span class="live-session__meta">${meta}</span>` : ''}
            </div>`;
        }).join('');
    }

    function rowDetail(item) {
        if (item.kind === 'game') {
            const who = item.agent === 'cursor' ? 'Cursor' : (item.guest ? 'Гість' : esc(item.user || 'Користувач'));
            const geo = item.geo ? ` · ${esc(item.geo)}` : '';
            const title = esc(item.game_title || item.game_slug || item.path || '—');
            return `<strong class="live-row__detail--game">Вибрав гру</strong> → ${who} · ${title}${geo}${durationBadge(item)}`;
        }
        if (item.kind === 'visit') {
            const who = item.agent === 'cursor' ? 'Cursor' : (item.guest ? 'Гість' : esc(item.user || 'Користувач'));
            const geo = item.geo ? ` · ${esc(item.geo)}` : '';
            const path = item.path ? ` · ${esc(item.path)}` : '';
            return `${who}${geo}${path}${durationBadge(item)}`;
        }
        if (item.kind === 'click') {
            const cls = item.has_tracking ? 'live-row__detail--click' : 'live-row__detail--click-noref';
            const hint = item.has_tracking ? '' : ' <span class="live-row__detail--click-noref-hint">(без рефералки)</span>';
            return `<strong class="${cls}">Перейшов</strong> → ${esc(item.detail)}${hint}${durationBadge(item)}`;
        }
        return esc(item.detail || item.email || '—');
    }

    function renderFeed(feed) {
        if (!elFeed) return;
        if (!feed || !feed.length) {
            elFeed.innerHTML = '<p class="live-feed__empty">Поки тихо — чекаємо на візити, переходи в магазин і реєстрації</p>';
            return;
        }

        let newCount = 0;
        const rows = feed.map((item) => {
            const isNew = !knownIds.has(item.id);
            if (!firstLoad && isNew) newCount += 1;
            knownIds.add(item.id);
            const kind = item.kind === 'click'
                ? (item.has_tracking ? 'click' : 'click-noref')
                : (KIND_CLASS[item.kind] || 'visit');
            let rowTone = '';
            if (item.kind === 'click') {
                rowTone = item.has_tracking ? ' live-row--click' : ' live-row--click-noref';
            } else if (item.kind === 'game') {
                rowTone = ' live-row--game';
            }
            let newCls = '';
            if (isNew && !firstLoad) {
                if (item.kind === 'click') {
                    newCls = item.has_tracking ? ' live-row--new-click' : ' live-row--new-click-noref';
                } else if (item.kind === 'game') {
                    newCls = ' live-row--new-game';
                } else {
                    newCls = ' live-row--new';
                }
            }
            return `<div class="live-row${rowTone}${newCls}" data-id="${esc(item.id)}">
                <div class="live-row__head">
                    <span class="live-row__time">${fmtTime(item.at)}</span>
                    <span class="live-row__kind live-row__kind--${kind}">${KIND_LABEL[item.kind] || item.kind}</span>
                </div>
                <span class="live-row__detail">${rowDetail(item)}</span>
            </div>`;
        });

        elFeed.innerHTML = rows.join('');

        if (!firstLoad && newCount > 0) {
            beep();
            document.title = `(${newCount}) LIVE · KupujPL`;
            setTimeout(() => { document.title = 'LIVE · KupujPL'; }, 8000);
        }
        firstLoad = false;

        if (knownIds.size > 120) {
            const keep = new Set(feed.map((f) => f.id));
            knownIds = keep;
        }
    }

    function setStatus(text, active) {
        if (elStatus) elStatus.textContent = text;
        if (elPulse) elPulse.classList.toggle('live-pulse--on', !!active);
    }

    async function poll() {
        try {
            const res = await fetch('api/admin/live', { credentials: 'same-origin' });
            if (res.status === 401) {
                window.location.href = 'panel3';
                return;
            }
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            renderKpis(data.kpis);
            renderSessions(data.active_sessions || []);
            renderFeed(data.feed || []);
            const k = data.kpis || {};
            const parts = [];
            if (data.active_now) parts.push('активність зараз');
            if (k.clicks_5m) parts.push(`${k.clicks_5m} Kup за 5 хв`);
            if (k.visits_5m) parts.push(`${k.visits_5m} візитів за 5 хв`);
            if (k.crawler_visits_5m) parts.push(`🤖 ${k.crawler_visits_5m} crawler за 5 хв`);
            setStatus(parts.length ? parts.join(' · ') : 'тихо', !!data.active_now);
            if (elFootLeft) {
                const t = data.server_time ? fmtTime(data.server_time) : '—';
                elFootLeft.textContent = `Сервер ${t} · оновлення кожні ${POLL_MS / 1000} с`;
            }
        } catch (err) {
            setStatus('помилка зʼєднання', false);
            if (elFootLeft) elFootLeft.textContent = String(err.message || err);
        }
    }

    function start() {
        syncSoundBtn();
        updateClock();
        clockTimer = setInterval(updateClock, 1000);
        poll();
        pollTimer = setInterval(poll, POLL_MS);
    }

    if (btnSound) {
        btnSound.addEventListener('click', () => {
            soundOn = !soundOn;
            try { sessionStorage.setItem(SS_SOUND, soundOn ? '1' : '0'); } catch (_) { /* ignore */ }
            syncSoundBtn();
            if (soundOn) beep();
        });
    }

    document.addEventListener('visibilitychange', () => {
        if (document.hidden) return;
        poll();
    });

    start();
})();

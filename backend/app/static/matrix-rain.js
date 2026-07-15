(function (global) {
    'use strict';

    const GLYPHS = 'ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿ0123456789ABCDEFKUPUJPL$#<>[]{}';
    let canvas = null;
    let ctx = null;
    let cols = [];
    let fontSize = 16;
    let running = false;
    let rafId = 0;

    function layers() {
        let c = document.getElementById('matrix-rain-canvas');
        if (!c) {
            c = document.createElement('canvas');
            c.id = 'matrix-rain-canvas';
            c.setAttribute('aria-hidden', 'true');
            document.body.prepend(c);
        }
        let v = document.getElementById('matrix-vignette');
        if (!v) {
            v = document.createElement('div');
            v.id = 'matrix-vignette';
            v.className = 'matrix-vignette';
            v.setAttribute('aria-hidden', 'true');
            document.body.prepend(v);
        }
        return c;
    }

    function resize() {
        if (!canvas || !ctx) return;
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.floor(window.innerWidth * dpr);
        canvas.height = Math.floor(window.innerHeight * dpr);
        canvas.style.width = window.innerWidth + 'px';
        canvas.style.height = window.innerHeight + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        fontSize = Math.max(14, Math.round(window.innerWidth / 85));
        const columnCount = Math.ceil(window.innerWidth / fontSize);
        cols = new Array(columnCount).fill(0).map(() => Math.random() * -80);
    }

    function drawFrame() {
        if (!running || !ctx) return;
        ctx.fillStyle = 'rgba(0, 8, 2, 0.09)';
        ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);
        ctx.font = fontSize + 'px Consolas, "Courier New", monospace';

        for (let i = 0; i < cols.length; i++) {
            if (Math.random() > 0.975) continue;
            const char = GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
            const x = i * fontSize;
            const y = cols[i] * fontSize;
            const head = y <= fontSize * 2;
            ctx.fillStyle = head ? '#ccffcc' : `rgba(0, 255, 65, ${0.32 + Math.random() * 0.5})`;
            ctx.shadowColor = head ? '#00ff41' : 'transparent';
            ctx.shadowBlur = head ? 6 : 0;
            ctx.fillText(char, x, y);
            if (y > window.innerHeight + fontSize * 4 && Math.random() > 0.975) {
                cols[i] = 0;
            } else {
                cols[i] += 0.4 + Math.random() * 0.85;
            }
        }
        ctx.shadowBlur = 0;
        rafId = requestAnimationFrame(drawFrame);
    }

    function start() {
        canvas = layers();
        ctx = canvas.getContext('2d');
        if (!ctx) return;
        running = true;
        resize();
        cancelAnimationFrame(rafId);
        rafId = requestAnimationFrame(drawFrame);
    }

    function stop() {
        running = false;
        cancelAnimationFrame(rafId);
        if (ctx && canvas) {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
    }

    function setActive(active) {
        document.documentElement.classList.toggle('theme-matrix-active', active);
        if (active) {
            start();
        } else {
            stop();
        }
    }

    function syncFromTheme() {
        const theme = global.KupujPLTheme?.getTheme?.()
            || document.documentElement.dataset.theme
            || 'night';
        setActive(theme === 'matrix');
    }

    window.addEventListener('resize', () => {
        if (running) resize();
    });

    document.addEventListener('themechange', (e) => {
        setActive(e.detail?.theme === 'matrix');
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', syncFromTheme);
    } else {
        syncFromTheme();
    }

    global.KupujPLMatrixRain = { setActive, syncFromTheme };
})(typeof window !== 'undefined' ? window : globalThis);

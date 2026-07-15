/** Inject contact / donate URLs from API (env on server). */
(function () {
    function apply(info) {
        if (!info) return;
        const map = [
            ['#contact-email', 'contact_email', 'mailto:'],
            ['#privacy-email', 'contact_email', 'mailto:'],
            ['#donate-email', 'contact_email', 'mailto:'],
            ['#contact-telegram', 'telegram_url', ''],
            ['#privacy-telegram', 'telegram_url', ''],
            ['#contact-instagram', 'instagram_url', ''],
            ['#contact-donate', 'donate_url', ''],
            ['#contact-donate-qr', 'donate_url', ''],
            ['#donate-main', 'donate_url', ''],
        ];
        for (const [sel, key, prefix] of map) {
            document.querySelectorAll(sel).forEach((el) => {
                const val = info[key];
                if (!val) return;
                if (prefix === 'mailto:') {
                    el.href = 'mailto:' + val.replace(/^mailto:/, '');
                    if (el.id.includes('email')) el.textContent = val.replace(/^mailto:/, '');
                } else {
                    el.href = val;
                    if (key === 'donate_url' && info.donate_label && !el.querySelector('img')) {
                        el.textContent = el.classList.contains('btn-donate')
                            ? 'Postaw kawę — ' + info.donate_label
                            : info.donate_label;
                    }
                    if (key === 'telegram_url' && info.telegram_label && el.id.includes('telegram')) {
                        el.textContent = info.telegram_label;
                    }
                    if (key === 'instagram_url' && info.instagram_label && el.id.includes('instagram')) {
                        el.textContent = info.instagram_label;
                    }
                }
            });
        }
    }

    fetch(resolveApi('site/info'))
        .then((r) => (r.ok ? r.json() : null))
        .then(apply)
        .catch(() => {});
})();

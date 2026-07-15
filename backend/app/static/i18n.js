/** KupujPL Gry — PL / UK / EN */
(function (global) {
    const LANG_KEY = 'kupujpl_lang';
    const DEFAULT_LANG = 'pl';
    const LOCALES = { pl: 'pl-PL', uk: 'uk-UA', en: 'en-GB' };

    const M = {
        pl: {
            'lang.pl': 'PL', 'lang.uk': 'UA', 'lang.en': 'EN',
            'theme.label': 'Motyw:',
            'theme.aria': 'Zmień motyw kolorystyczny strony',
            'theme.night': 'CP', 'theme.ice': 'ICE', 'theme.void': 'VOID', 'theme.matrix': 'MX',
            'theme.night_title': 'Night City — żółty styl Cyberpunk 2077 (domyślny)',
            'theme.ice_title': 'Arctic ICE — chłodna niebieska paleta',
            'theme.void_title': 'Void Purple — fiolet i neon',
            'theme.matrix_title': 'Matrix — żółty interfejs + animowany deszcz cyfrowy',
            'nav.about': 'O nas', 'nav.blog': 'Blog',
            'nav.regulamin': 'Regulamin', 'nav.privacy': 'Prywatność', 'nav.contact': 'Kontakt', 'nav.support': '☕ Wsparcie',
            'nav.login': 'Zaloguj', 'nav.register': 'Rejestracja', 'nav.panel': 'Panel', 'nav.logout': 'Wyloguj',
            'nav.info': 'Informacje', 'nav.legal': 'Informacje prawne',
            'search.placeholder': 'Szukaj gier…',
            'banner.dev': 'Projekt w fazie rozwoju. Zauważyłeś błąd? {link} — bardzo prosimy, szybko go naprawimy.',
            'banner.dev_link': 'Napisz do nas',
            'cat.title': 'Kategorie', 'cat.all': 'Wszystkie', 'cat.new_games': 'Nowe gry', 'cat.top_sales': 'Top sprzedaż',
            'hero.not_shop': 'To nie sklep internetowy', 'hero.compare': 'Porównywarka cen gier PC',
            'hero.kicker': 'night city // najniższa cena',
            'hero.title': 'Wstań', 'hero.title_span': 'łowco okazji',
            'hero.lead': 'Nie sprzedajemy gier — porównujemy ceny w 10 sklepach i pokazujemy, gdzie kupić taniej. Skan na żywo: Steam, GOG, Epic, Kinguin, G2A, Fanatical, CDKeys i reszta.',
            'hero.scan': 'Skanuj ceny', 'hero.report': 'Zgłoś błąd',
            'hero.deal_kicker': 'polecana okazja', 'hero.deal_title': 'Cyber Okazje', 'hero.deal_live': 'na żywo',
            'hero.deal_meta': '10 sklepów // 5000+ gier',
            'promo.about_kicker': 'night city // kim jesteśmy', 'promo.about_title': 'Poznaj KupujPL',
            'promo.about_lead': 'Chcesz wiedzieć, kim jesteśmy i jak działa porównywarka? Przeczytaj o nas — przycisk „O nas" znajdziesz na górze strony.',
            'promo.about_cta': 'Przeczytaj o nas',
            'promo.kicker': 'night city // twój stash', 'promo.title': 'Panel łowcy okazji',
            'promo.lead': 'Załóż darmowe konto i korzystaj z narzędzi, których nie ma zwykły gość — wszystko w jednym miejscu, bez sprzedawania gier.',
            'promo.f1': 'Śledzone gry', 'promo.f1d': 'zapisuj tytuły i wracaj do najlepszych cen w 10 sklepach.',
            'promo.f2': 'Alerty cenowe', 'promo.f2d': 'e-mail, Telegram lub powiadomienia push (PWA), gdy cena spada.',
            'promo.f3': 'Import Steam Wishlist', 'promo.f3d': 'jednym kliknięciem dodaj publiczną listę życzeń do śledzenia.',
            'promo.f4': 'Odświeżanie cen', 'promo.f4d': 'wymuś skan ulubionych gier bez czekania na cykl Tier A.',
            'promo.f5': 'Oszczędności vs Steam', 'promo.f5d': 'na karcie widać, ile taniej niż w Steamie.',
            'promo.f6': 'Historia cen', 'promo.f6d': 'przy grze sprawdzisz trend i najniższą cenę z ostatnich dni.',
            'promo.open': 'Otwórz panel', 'promo.signup': 'Załóż konto', 'promo.have_account': 'Mam konto',
            'promo.preview': 'Twój panel', 'promo.preview1': '◉ 12 śledzonych', 'promo.preview2': '⚡ 5 alertów ON',
            'catalog.all_games': 'Wszystkie gry', 'catalog.full': 'Pełny katalog', 'catalog.load_more': 'Załaduj więcej',
            'catalog.loading': 'Ładowanie...', 'catalog.page': 'Strona {page} / {pages} · {total} gier',
            'catalog.games_count': '{n} gier', 'catalog.results': 'Wyniki: „{q}"',
            'catalog.search_results': 'Tylko pasujące gry',
            'sort.label': 'Sortuj', 'sort.relevance': 'Domyślnie', 'sort.price_asc': 'Cena: rosnąco',
            'sort.price_desc': 'Cena: malejąco', 'sort.rating': 'Najwyżej oceniane', 'sort.release': 'Najnowsze', 'sort.title': 'Nazwa: A–Z',
            'card.from': 'Od', 'card.check_price': 'Sprawdź cenę', 'card.official': 'Oficjalny',
            'card.watch': 'Śledź', 'card.watching': 'Śledzisz', 'card.compare_prices': 'porównaj ceny',
            'modal.close': 'Zamknij', 'modal.prices': 'Ceny w sklepach', 'modal.refresh': 'Odśwież ceny',
            'modal.game_desc': 'Opis gry',
            'modal.alert': 'Alert cenowy', 'modal.alert_on': 'Alert włączony',
            'modal.loading': 'Ładowanie…', 'modal.loading_desc': 'Ładowanie opisu…', 'modal.no_desc': 'Brak opisu gry.',
            'modal.error': 'Błąd', 'modal.error_load': 'Nie udało się załadować szczegółów gry.',
            'modal.no_offers': 'Brak dostępnych ofert w sklepach.', 'modal.offers_error': 'Wystąpił błąd podczas ładowania ofert.',
            'modal.scan_label': 'Trwa skan cen w sklepach',
            'modal.scan_info': 'Skanujemy na żywo 10 sklepów (Steam, GOG, Epic, keyshopy…). Najpierw widzisz zapisane ceny, potem zapisujemy świeże wyniki.',
            'modal.scan_finishing': 'Kończymy skan… jeszcze chwilę.',
            'modal.scan_eta': 'Szacowany czas do końca skanu: ok. {s} s',
            'offer.buy': 'Kup', 'offer.buy_cheapest': 'Kup najtaniej — {price}',
            'offer.official': 'Oficjalny sklep', 'offer.marketplace': 'Marketplace kluczy',
            'offer.refund': 'Zwroty', 'offer.check': 'Sprawdź ofertę',
            'offer.refund_toggle_hint': 'Kliknij — przeczytaj, co ten sklep obiecuje przy zwrotach',
            'offer.refund_shop_link': 'Regulamin sklepu',
            'offer.refund_kicker': 'KupujPL — co obiecują zwroty:',
            'offer.refund_disclaimer': 'To skrót według regulaminów sklepów — przed zakupem sprawdź aktualne warunki u sprzedawcy.',
            'offer.savings': 'Oszczędzasz {amount} zł (−{pct}%) vs Steam ({steam} zł)',
            'offer.affiliate_note': 'Część linków to linki partnerskie — cena dla Ciebie się nie zmienia.',
            'offer.stale': 'Ceny mogą być nieaktualne — użyj „Odśwież oferty”',
            'offer.official_note': 'Oficjalny sklep — kupujesz bezpośrednio, pełne wsparcie i zwroty.',
            'offer.marketplace_note': 'Marketplace kluczy — sprawdź ocenę sprzedawcy, region klucza i politykę zwrotów przed zakupem.',
            'offer.low_conf_note': 'Nie mamy pewności, że to dokładnie ta gra/edycja — zweryfikuj na stronie sklepu.',
            'card.vs_steam': '−{pct}% vs Steam',
            'card.savings_title': 'Oszczędzasz {amount} vs Steam ({steam})',
            'modal.savings_kicker': 'vs Steam',
            'modal.savings_amount': 'Oszczędzasz <strong>{amount}</strong> <span class="modal-savings-pct">(−{pct}%)</span>',
            'modal.savings_detail': 'Steam: {steam} → najtaniej: {best} · {shop}',
            'modal.savings_cta': 'Kup najtaniej — {price}',
            'home.load_fail': 'Nie udało się załadować polecanych gier.',
            'home.loading': 'Ładowanie popularnych gier…', 'home.see_more': 'Zobacz więcej →',
            'grid.not_found': 'Nie znaleziono gier.', 'grid.hint_both': 'Spróbuj wyczyścić wyszukiwanie lub wybrać inną kategorię.',
            'grid.hint': 'Spróbuj innej frazy lub kategorii.', 'grid.error': 'Wystąpił błąd podczas ładowania gier.',
            'auth.login_title': 'Logowanie', 'auth.login_sub': 'Zapisuj ulubione gry i wracaj do najlepszych cen.',
            'auth.register_title': 'Rejestracja', 'auth.register_sub': 'Załóż konto, aby zapisywać ulubione gry.',
            'auth.email': 'E-mail', 'auth.password': 'Hasło', 'auth.password2': 'Powtórz hasło',
            'auth.password_min': 'Hasło (min. 8 znaków)', 'auth.forgot': 'Zapomniałeś hasła?',
            'auth.submit_login': 'Zaloguj', 'auth.submit_register': 'Zarejestruj się',
            'auth.no_account': 'Nie masz konta?', 'auth.have_account': 'Masz konto?', 'auth.go_register': 'Zarejestruj się', 'auth.go_login': 'Zaloguj się',
            'auth.legal_use': 'Korzystając z serwisu, akceptujesz {reg} i {priv}.',
            'auth.legal_reg': 'Regulamin', 'auth.legal_priv': 'Politykę prywatności',
            'auth.oauth_divider': 'lub e-mail i hasło',
            'auth.oauth_login': 'Logując się przez Google, przekazujesz nam adres e-mail (oraz opcjonalnie imię) niezbędne do utworzenia konta — zgodnie z {link}.',
            'auth.oauth_register': 'Rejestrując się przez Google, przekazujesz nam adres e-mail (oraz opcjonalnie imię) niezbędne do utworzenia konta — zgodnie z {link}.',
            'auth.privacy_link': 'Polityką prywatności',
            'auth.err_login': 'Błąd logowania', 'auth.err_connection': 'Błąd połączenia.',
            'auth.err_password_match': 'Hasła nie są identyczne',
            'panel.kicker': 'night city // twój stash', 'panel.title': 'Twój', 'panel.title_span': 'panel',
            'panel.loading': 'Ładowanie…', 'panel.watchlist': 'Śledzone gry', 'panel.account': 'Konto',
            'panel.back': '← Katalog gier', 'panel.reset_pw': 'Reset hasła e-mailem',
            'panel.watch_sub': 'Import wishlisty, alerty cenowe i lista tytułów',
            'panel.sort': 'Sortuj', 'panel.sort_newest': 'Najnowsze', 'panel.sort_price_asc': 'Cena rosnąco',
            'panel.sort_price_desc': 'Cena malejąco', 'panel.sort_name': 'Alfabetycznie', 'panel.only_priced': 'Tylko z ceną',
            'panel.refresh_prices': 'Odśwież ceny', 'panel.alerts': 'Alerty cenowe',
            'panel.spotlight_nav': 'Główna', 'panel.spotlight_title': 'Spotlight na stronie głównej',
            'panel.spotlight_sub': 'Do 8 gier — duże okładki u góry katalogu. Kolejność = od lewej na stronie.',
            'panel.spotlight_save': 'Zapisz na stronie głównej', 'panel.spotlight_steam': 'Link Steam lub appid',
            'panel.spotlight_add': 'Dodaj', 'panel.spotlight_search': 'Szukaj w katalogu',
            'panel.spotlight_empty': 'Brak gier — dodaj link Steam lub wyszukaj tytuł.',
            'panel.spotlight_duplicate': 'Ta gra jest już na liście.', 'panel.spotlight_max': 'Maksymalnie 8 gier.',
            'panel.spotlight_added': 'Dodano do listy (kliknij Zapisz).', 'panel.spotlight_saved': 'Zapisano na stronie głównej.',
            'panel.scan_all_shops': 'Skanuj wszystkie sklepy', 'panel.spotlight_scanning': 'Skan w tle…',
            'panel.spotlight_scan_done': 'Skan uruchomiony — odśwież za chwilę.',
            'spotlight.kicker': 'night city // twój wybór', 'spotlight.title': 'Polecane',
            'search.no_results': 'Brak wyników',
            'legal.pl_only': 'Pełna treść prawna dostępna po polsku. Poniżej skrót w wybranym języku.',
            'footer.copy': '© 2026 KupujPL · Porównywarka cen gier PC',
            'trust.aria': 'Zaufanie', 'trust.games': 'gier w bazie', 'trust.shops': 'sklepów porównywanych',
            'trust.updated_val': 'na żywo', 'trust.updated': 'aktualizacja cen',
            'trust.free_val': '0 zł', 'trust.free': 'zawsze za darmo',
            'faq.kicker': 'night city // FAQ', 'faq.title': 'Najczęstsze pytania',
            'faq.q1': 'Czy KupujPL sprzedaje gry lub klucze?',
            'faq.a1': 'Nie. Jesteśmy porównywarką cen — pokazujemy oferty sklepów, a zakupu dokonujesz bezpośrednio u wybranego sprzedawcy. Nie pobieramy płatności i nie przechowujemy danych kart.',
            'faq.q2': 'Czy korzystanie z serwisu jest bezpieczne?',
            'faq.a2': 'Tak. Strona działa po HTTPS, nie prowadzimy sprzedaży ani nie przetwarzamy płatności. Przekierowujemy tylko do sklepów — oznaczamy, które są oficjalne, a które to marketplace kluczy.',
            'faq.q3': "Dlaczego ceny na marketplace'ach kluczy są niższe?",
            'faq.a3': "Marketplace'y (np. Eneba, Kinguin, G2A) to platformy z ofertami wielu sprzedawców — stąd niższe ceny, ale i większe ryzyko. Zawsze sprawdzaj ocenę sprzedawcy i zasady zwrotów.",
            'faq.q4': 'Jak często aktualizujecie ceny?',
            'faq.a4': 'Ceny odświeżamy regularnie, a najpopularniejsze tytuły skanujemy na żywo, gdy otwierasz stronę gry. Zalogowani użytkownicy mogą wymusić odświeżenie ulubionych tytułów.',
            'faq.q5': 'Czy serwis jest darmowy?',
            'faq.a5': 'Tak, w całości i bez limitów. Część linków do sklepów jest partnerska — jeśli kupisz po przejściu z naszego linku, sklep może przekazać nam prowizję. Cena dla Ciebie się nie zmienia.',
            'title.home': 'KupujPL — Porównywarka cen gier PC',
        },
        uk: {
            'lang.pl': 'PL', 'lang.uk': 'UA', 'lang.en': 'EN',
            'theme.label': 'Тема:',
            'theme.aria': 'Змінити колірну тему сайту',
            'theme.night': 'CP', 'theme.ice': 'ICE', 'theme.void': 'VOID', 'theme.matrix': 'MX',
            'theme.night_title': 'Night City — жовтий стиль Cyberpunk 2077 (за замовч.)',
            'theme.ice_title': 'Arctic ICE — холодна блакитна палітра',
            'theme.void_title': 'Void Purple — фіолет і неон',
            'theme.matrix_title': 'Matrix — жовтий інтерфейс + анімований цифровий дощ',
            'nav.about': 'Про нас', 'nav.blog': 'Блог',
            'nav.regulamin': 'Правила', 'nav.privacy': 'Конфіденційність', 'nav.contact': 'Контакт', 'nav.support': '☕ Підтримка',
            'nav.login': 'Увійти', 'nav.register': 'Реєстрація', 'nav.panel': 'Панель', 'nav.logout': 'Вийти',
            'nav.info': 'Інформація', 'nav.legal': 'Правова інформація',
            'search.placeholder': 'Пошук ігор…',
            'banner.dev': 'Проєкт у розробці. Помітили помилку? {link} — швидко виправимо.',
            'banner.dev_link': 'Напишіть нам',
            'cat.title': 'Категорії', 'cat.all': 'Усі', 'cat.new_games': 'Нові ігри', 'cat.top_sales': 'Топ продажів',
            'hero.not_shop': 'Це не інтернет-магазин', 'hero.compare': 'Порівняння цін на ігри для ПК',
            'hero.kicker': 'night city // найнижча ціна',
            'hero.title': 'Вставай', 'hero.title_span': 'мисливцю на знижки',
            'hero.lead': 'Ми не продаємо ігри — порівнюємо ціни в 10 магазинах і показуємо, де купити дешевше. Скан у реальному часі: Steam, GOG, Epic, Kinguin, G2A, Fanatical, CDKeys та інші.',
            'hero.scan': 'Сканувати ціни', 'hero.report': 'Повідомити про помилку',
            'hero.deal_kicker': 'рекомендована знижка', 'hero.deal_title': 'Cyber Знижки', 'hero.deal_live': 'наживо',
            'hero.deal_meta': '10 магазинів // 5000+ ігор',
            'promo.about_kicker': 'night city // хто ми', 'promo.about_title': 'Дізнайся про KupujPL',
            'promo.about_lead': 'Хочеш знати, хто ми і як працює порівнювач цін? Прочитай про нас — кнопку «Про нас» знайдеш угорі сторінки.',
            'promo.about_cta': 'Прочитати про нас',
            'promo.kicker': 'night city // твій stash', 'promo.title': 'Панель мисливця на знижки',
            'promo.lead': 'Створи безкоштовний акаунт і користуйся інструментами, яких немає у гостя — усе в одному місці, без продажу ігор.',
            'promo.f1': 'Відстежувані ігри', 'promo.f1d': 'зберігай назви та повертайся до найкращих цін у 10 магазинах.',
            'promo.f2': 'Цінові алерти', 'promo.f2d': 'e-mail, Telegram або push (PWA), коли ціна падає.',
            'promo.f3': 'Імпорт Steam Wishlist', 'promo.f3d': 'одним кліком додай публічний список бажань.',
            'promo.f4': 'Оновлення цін', 'promo.f4d': 'примусовий скан улюблених без очікування циклу Tier A.',
            'promo.f5': 'Економія vs Steam', 'promo.f5d': 'на картці видно, скільки дешевше ніж у Steam.',
            'promo.f6': 'Історія цін', 'promo.f6d': 'переглядай тренд і найнижчу ціну за останні дні.',
            'promo.open': 'Відкрити панель', 'promo.signup': 'Створити акаунт', 'promo.have_account': 'Маю акаунт',
            'promo.preview': 'Твоя панель', 'promo.preview1': '◉ 12 відстежуваних', 'promo.preview2': '⚡ 5 алертів ON',
            'catalog.all_games': 'Усі ігри', 'catalog.full': 'Повний каталог', 'catalog.load_more': 'Завантажити ще',
            'catalog.loading': 'Завантаження...', 'catalog.page': 'Сторінка {page} / {pages} · {total} ігор',
            'catalog.games_count': '{n} ігор', 'catalog.results': 'Результати: „{q}"',
            'catalog.search_results': 'Лише знайдені ігри',
            'sort.label': 'Сортувати', 'sort.relevance': 'За замовчуванням', 'sort.price_asc': 'Ціна: зростання',
            'sort.price_desc': 'Ціна: спадання', 'sort.rating': 'Найвищий рейтинг', 'sort.release': 'Найновіші', 'sort.title': 'Назва: А–Я',
            'card.from': 'Від', 'card.check_price': 'Перевірити ціну', 'card.official': 'Офіційний',
            'card.watch': 'Стежити', 'card.watching': 'Стежите', 'card.compare_prices': 'порівняти ціни',
            'modal.close': 'Закрити', 'modal.prices': 'Ціни в магазинах', 'modal.refresh': 'Оновити ціни',
            'modal.game_desc': 'Опис гри',
            'modal.alert': 'Ціновий алерт', 'modal.alert_on': 'Алерт увімкнено',
            'modal.loading': 'Завантаження…', 'modal.loading_desc': 'Завантаження опису…', 'modal.no_desc': 'Немає опису гри.',
            'modal.error': 'Помилка', 'modal.error_load': 'Не вдалося завантажити деталі гри.',
            'modal.no_offers': 'Немає доступних пропозицій у магазинах.', 'modal.offers_error': 'Помилка завантаження пропозицій.',
            'modal.scan_label': 'Триває сканування цін у магазинах',
            'modal.scan_info': 'Скануємо наживо 10 магазинів (Steam, GOG, Epic, keyshop…). Спочатку бачите збережені ціни, потім оновлюємо.',
            'modal.scan_finishing': 'Завершуємо скан… ще трохи.',
            'modal.scan_eta': 'Орієнтовний час до кінця скану: ~{s} с',
            'offer.buy': 'Купити', 'offer.buy_cheapest': 'Купити найдешевше — {price}',
            'offer.official': 'Офіційний магазин', 'offer.marketplace': 'Маркетплейс ключів',
            'offer.refund': 'Повернення', 'offer.check': 'Перевірити пропозицію',
            'offer.refund_toggle_hint': 'Натисни — прочитай, що магазин обіцяє з поверненням',
            'offer.refund_shop_link': 'Правила магазину',
            'offer.refund_kicker': 'KupujPL — що обіцяють з поверненням:',
            'offer.refund_disclaimer': 'Короткий виклад правил магазину — перед покупкою перевір актуальні умови у продавця.',
            'offer.savings': 'Економія {amount} zł (−{pct}%) vs Steam ({steam} zł)',
            'offer.affiliate_note': 'Частина посилань — партнерські. Ціна для вас не змінюється.',
            'offer.stale': 'Ціни можуть бути застарілими — натисніть «Оновити пропозиції»',
            'offer.official_note': 'Офіційний магазин — купуєте напряму, повна підтримка та повернення.',
            'offer.marketplace_note': 'Маркетплейс ключів — перевірте рейтинг продавця, регіон ключа й політику повернення перед покупкою.',
            'offer.low_conf_note': 'Ми не впевнені, що це саме ця гра/видання — перевірте на сторінці магазину.',
            'card.vs_steam': '−{pct}% vs Steam',
            'card.savings_title': 'Економія {amount} vs Steam ({steam})',
            'modal.savings_kicker': 'vs Steam',
            'modal.savings_amount': 'Економія <strong>{amount}</strong> <span class="modal-savings-pct">(−{pct}%)</span>',
            'modal.savings_detail': 'Steam: {steam} → найдешевше: {best} · {shop}',
            'modal.savings_cta': 'Купити найдешевше — {price}',
            'home.load_fail': 'Не вдалося завантажити рекомендовані ігри.',
            'home.loading': 'Завантаження популярних ігор…', 'home.see_more': 'Дивитись більше →',
            'grid.not_found': 'Ігор не знайдено.', 'grid.hint_both': 'Спробуйте очистити пошук або обрати іншу категорію.',
            'grid.hint': 'Спробуйте інший запит або категорію.', 'grid.error': 'Помилка завантаження ігор.',
            'auth.login_title': 'Вхід', 'auth.login_sub': 'Зберігай улюблені ігри та повертайся до найкращих цін.',
            'auth.register_title': 'Реєстрація', 'auth.register_sub': 'Створи акаунт, щоб зберігати улюблені ігри.',
            'auth.email': 'E-mail', 'auth.password': 'Пароль', 'auth.password2': 'Повторіть пароль',
            'auth.password_min': 'Пароль (мін. 8 символів)', 'auth.forgot': 'Забули пароль?',
            'auth.submit_login': 'Увійти', 'auth.submit_register': 'Зареєструватися',
            'auth.no_account': 'Немає акаунта?', 'auth.have_account': 'Маєте акаунт?', 'auth.go_register': 'Зареєструватися', 'auth.go_login': 'Увійти',
            'auth.legal_use': 'Користуючись сервісом, ви приймаєте {reg} та {priv}.',
            'auth.legal_reg': 'Правила', 'auth.legal_priv': 'Політику конфіденційності',
            'auth.oauth_divider': 'або e-mail і пароль',
            'auth.oauth_login': 'Входячи через Google, ви передаєте нам e-mail (та за наявності ім’я) для створення акаунта — згідно з {link}.',
            'auth.oauth_register': 'Реєструючись через Google, ви передаєте нам e-mail (та за наявності ім’я) для створення акаунта — згідно з {link}.',
            'auth.privacy_link': 'Політикою конфіденційності',
            'auth.err_login': 'Помилка входу', 'auth.err_connection': 'Помилка з’єднання.',
            'auth.err_password_match': 'Паролі не збігаються',
            'panel.kicker': 'night city // твій stash', 'panel.title': 'Твоя', 'panel.title_span': 'панель',
            'panel.loading': 'Завантаження…', 'panel.watchlist': 'Відстежувані ігри', 'panel.account': 'Акаунт',
            'panel.back': '← Каталог ігор', 'panel.reset_pw': 'Скинути пароль на e-mail',
            'panel.watch_sub': 'Імпорт wishlist, цінові алерти та список ігор',
            'panel.sort': 'Сортувати', 'panel.sort_newest': 'Найновіші', 'panel.sort_price_asc': 'Ціна за зростанням',
            'panel.sort_price_desc': 'Ціна за спаданням', 'panel.sort_name': 'За алфавітом', 'panel.only_priced': 'Лише з ціною',
            'panel.refresh_prices': 'Оновити ціни', 'panel.alerts': 'Цінові алерти',
            'panel.spotlight_nav': 'Головна', 'panel.spotlight_title': 'Spotlight на головній',
            'panel.spotlight_sub': 'До 8 ігор — великі обкладинки вгорі каталогу. Порядок = зліва направо.',
            'panel.spotlight_save': 'Зберегти на головній', 'panel.spotlight_steam': 'Посилання Steam або appid',
            'panel.spotlight_add': 'Додати', 'panel.spotlight_search': 'Пошук у каталозі',
            'panel.spotlight_empty': 'Немає ігор — додай Steam або знайди назву.',
            'panel.spotlight_duplicate': 'Ця гра вже в списку.', 'panel.spotlight_max': 'Максимум 8 ігор.',
            'panel.spotlight_added': 'Додано (натисни Зберегти).', 'panel.spotlight_saved': 'Збережено на головній.',
            'panel.scan_all_shops': 'Сканувати всі магазини', 'panel.spotlight_scanning': 'Скан у фоні…',
            'panel.spotlight_scan_done': 'Скан запущено — оновиться незабаром.',
            'spotlight.kicker': 'night city // твій вибір', 'spotlight.title': 'Рекомендовані',
            'search.no_results': 'Немає результатів',
            'legal.pl_only': 'Повний юридичний текст — польською. Нижче короткий виклад обраною мовою.',
            'footer.copy': '© 2026 KupujPL · Порівняння цін на ігри для ПК',
            'trust.aria': 'Довіра', 'trust.games': 'ігор у базі', 'trust.shops': 'магазинів порівнюємо',
            'trust.updated_val': 'наживо', 'trust.updated': 'оновлення цін',
            'trust.free_val': '0 zł', 'trust.free': 'завжди безкоштовно',
            'faq.kicker': 'night city // FAQ', 'faq.title': 'Часті запитання',
            'faq.q1': 'Чи продає KupujPL ігри або ключі?',
            'faq.a1': 'Ні. Ми — порівнювач цін: показуємо пропозиції магазинів, а купівлю ви робите безпосередньо в обраного продавця. Ми не приймаємо оплат і не зберігаємо дані карток.',
            'faq.q2': 'Чи безпечно користуватися сервісом?',
            'faq.a2': 'Так. Сайт працює через HTTPS, ми не ведемо продажів і не обробляємо платежі. Ми лише перенаправляємо в магазини — і позначаємо, які з них офіційні, а які маркетплейси ключів.',
            'faq.q3': 'Чому ціни на маркетплейсах ключів нижчі?',
            'faq.a3': 'Маркетплейси (напр. Eneba, Kinguin, G2A) — це майданчики з пропозиціями багатьох продавців, звідси нижчі ціни, але й більший ризик. Завжди перевіряйте рейтинг продавця та умови повернення.',
            'faq.q4': 'Як часто ви оновлюєте ціни?',
            'faq.a4': 'Ціни оновлюємо регулярно, а найпопулярніші ігри скануємо наживо, коли ви відкриваєте сторінку гри. Авторизовані користувачі можуть примусово оновити улюблені ігри.',
            'faq.q5': 'Чи сервіс безкоштовний?',
            'faq.a5': 'Так, повністю й без обмежень. Частина посилань на магазини — партнерські: якщо купите після переходу з нашого посилання, магазин може виплатити нам комісію. Ціна для вас не змінюється.',
            'title.home': 'KupujPL — Порівняння цін на ігри для ПК',
        },
        en: {
            'lang.pl': 'PL', 'lang.uk': 'UA', 'lang.en': 'EN',
            'theme.label': 'Theme:',
            'theme.aria': 'Change site colour theme',
            'theme.night': 'CP', 'theme.ice': 'ICE', 'theme.void': 'VOID', 'theme.matrix': 'MX',
            'theme.night_title': 'Night City — yellow Cyberpunk 2077 style (default)',
            'theme.ice_title': 'Arctic ICE — cool blue palette',
            'theme.void_title': 'Void Purple — violet and neon',
            'theme.matrix_title': 'Matrix — yellow UI + animated digital rain',
            'nav.about': 'About', 'nav.blog': 'Blog',
            'nav.regulamin': 'Terms', 'nav.privacy': 'Privacy', 'nav.contact': 'Contact', 'nav.support': '☕ Support',
            'nav.login': 'Log in', 'nav.register': 'Sign up', 'nav.panel': 'Dashboard', 'nav.logout': 'Log out',
            'nav.info': 'Info', 'nav.legal': 'Legal',
            'search.placeholder': 'Search games…',
            'banner.dev': 'Project in development. Spotted a bug? {link} — we’ll fix it quickly.',
            'banner.dev_link': 'Contact us',
            'cat.title': 'Categories', 'cat.all': 'All', 'cat.new_games': 'New games', 'cat.top_sales': 'Top sellers',
            'hero.not_shop': 'This is not an online store', 'hero.compare': 'PC game price comparison',
            'hero.kicker': 'night city // lowest price',
            'hero.title': 'Rise up', 'hero.title_span': 'deal hunter',
            'hero.lead': 'We don’t sell games — we compare prices across 10 stores and show where to buy cheaper. Live scan: Steam, GOG, Epic, Kinguin, G2A, Fanatical, CDKeys and more.',
            'hero.scan': 'Scan prices', 'hero.report': 'Report a bug',
            'hero.deal_kicker': 'featured deal', 'hero.deal_title': 'Cyber Deals', 'hero.deal_live': 'live',
            'hero.deal_meta': '10 stores // 5000+ games',
            'promo.about_kicker': 'night city // who we are', 'promo.about_title': 'Get to know KupujPL',
            'promo.about_lead': 'Want to know who we are and how the price comparison works? Read about us — the “About” button is at the top of the page.',
            'promo.about_cta': 'Read about us',
            'promo.kicker': 'night city // your stash', 'promo.title': 'Deal hunter dashboard',
            'promo.lead': 'Create a free account and use tools guests don’t get — all in one place, without selling games.',
            'promo.f1': 'Tracked games', 'promo.f1d': 'save titles and return to the best prices in 10 stores.',
            'promo.f2': 'Price alerts', 'promo.f2d': 'email, Telegram or browser push (PWA) when the price drops.',
            'promo.f3': 'Steam Wishlist import', 'promo.f3d': 'add a public wishlist to tracking in one click.',
            'promo.f4': 'Price refresh', 'promo.f4d': 'force a scan of favourites without waiting for the Tier A cycle.',
            'promo.f5': 'Savings vs Steam', 'promo.f5d': 'see on each card how much cheaper than Steam.',
            'promo.f6': 'Price history', 'promo.f6d': 'check trends and the lowest price over recent days.',
            'promo.open': 'Open dashboard', 'promo.signup': 'Create account', 'promo.have_account': 'I have an account',
            'promo.preview': 'Your dashboard', 'promo.preview1': '◉ 12 tracked', 'promo.preview2': '⚡ 5 alerts ON',
            'catalog.all_games': 'All games', 'catalog.full': 'Full catalogue', 'catalog.load_more': 'Load more',
            'catalog.loading': 'Loading...', 'catalog.page': 'Page {page} / {pages} · {total} games',
            'catalog.games_count': '{n} games', 'catalog.results': 'Results: „{q}"',
            'catalog.search_results': 'Matching games only',
            'sort.label': 'Sort', 'sort.relevance': 'Default', 'sort.price_asc': 'Price: low to high',
            'sort.price_desc': 'Price: high to low', 'sort.rating': 'Top rated', 'sort.release': 'Newest', 'sort.title': 'Name: A–Z',
            'card.from': 'From', 'card.check_price': 'Check price', 'card.official': 'Official',
            'card.watch': 'Track', 'card.watching': 'Tracking', 'card.compare_prices': 'compare prices',
            'modal.close': 'Close', 'modal.prices': 'Store prices', 'modal.refresh': 'Refresh prices',
            'modal.game_desc': 'Game description',
            'modal.alert': 'Price alert', 'modal.alert_on': 'Alert on',
            'modal.loading': 'Loading…', 'modal.loading_desc': 'Loading description…', 'modal.no_desc': 'No game description.',
            'modal.error': 'Error', 'modal.error_load': 'Could not load game details.',
            'modal.no_offers': 'No offers available in stores.', 'modal.offers_error': 'Error loading offers.',
            'modal.scan_label': 'Scanning store prices',
            'modal.scan_info': 'Live scan across 10 stores (Steam, GOG, Epic, key shops…). Saved prices first, then fresh results.',
            'modal.scan_finishing': 'Finishing scan… almost done.',
            'modal.scan_eta': 'Estimated time left: ~{s} s',
            'offer.buy': 'Buy', 'offer.buy_cheapest': 'Buy cheapest — {price}',
            'offer.official': 'Official store', 'offer.marketplace': 'Key marketplace',
            'offer.refund': 'Refunds', 'offer.check': 'Check offer',
            'offer.refund_toggle_hint': 'Click to read what this shop promises on refunds',
            'offer.refund_shop_link': 'Shop policy',
            'offer.refund_kicker': 'KupujPL — what they promise on refunds:',
            'offer.refund_disclaimer': 'Summary based on shop policies — check the seller’s current terms before buying.',
            'offer.savings': 'Save {amount} PLN (−{pct}%) vs Steam ({steam} PLN)',
            'offer.affiliate_note': 'Some links are affiliate links — the price for you stays the same.',
            'offer.stale': 'Prices may be outdated — use “Refresh offers”',
            'offer.official_note': 'Official store — you buy directly, with full support and refunds.',
            'offer.marketplace_note': 'Key marketplace — check the seller rating, key region and refund policy before buying.',
            'offer.low_conf_note': 'We are not fully sure this is the exact game/edition — verify on the store page.',
            'card.vs_steam': '−{pct}% vs Steam',
            'card.savings_title': 'You save {amount} vs Steam ({steam})',
            'modal.savings_kicker': 'vs Steam',
            'modal.savings_amount': 'You save <strong>{amount}</strong> <span class="modal-savings-pct">(−{pct}%)</span>',
            'modal.savings_detail': 'Steam: {steam} → cheapest: {best} · {shop}',
            'modal.savings_cta': 'Buy cheapest — {price}',
            'home.load_fail': 'Could not load featured games.',
            'home.loading': 'Loading popular games…', 'home.see_more': 'See more →',
            'grid.not_found': 'No games found.', 'grid.hint_both': 'Try clearing search or picking another category.',
            'grid.hint': 'Try another phrase or category.', 'grid.error': 'Error loading games.',
            'auth.login_title': 'Log in', 'auth.login_sub': 'Save favourite games and return to the best prices.',
            'auth.register_title': 'Sign up', 'auth.register_sub': 'Create an account to save favourite games.',
            'auth.email': 'Email', 'auth.password': 'Password', 'auth.password2': 'Repeat password',
            'auth.password_min': 'Password (min. 8 characters)', 'auth.forgot': 'Forgot password?',
            'auth.submit_login': 'Log in', 'auth.submit_register': 'Sign up',
            'auth.no_account': 'No account?', 'auth.have_account': 'Have an account?', 'auth.go_register': 'Sign up', 'auth.go_login': 'Log in',
            'auth.legal_use': 'By using the service you accept the {reg} and {priv}.',
            'auth.legal_reg': 'Terms', 'auth.legal_priv': 'Privacy Policy',
            'auth.oauth_divider': 'or email and password',
            'auth.oauth_login': 'By signing in with Google you share your email (and optionally name) needed to create an account — per our {link}.',
            'auth.oauth_register': 'By signing up with Google you share your email (and optionally name) needed to create an account — per our {link}.',
            'auth.privacy_link': 'Privacy Policy',
            'auth.err_login': 'Login error', 'auth.err_connection': 'Connection error.',
            'auth.err_password_match': 'Passwords do not match',
            'panel.kicker': 'night city // your stash', 'panel.title': 'Your', 'panel.title_span': 'dashboard',
            'panel.loading': 'Loading…', 'panel.watchlist': 'Tracked games', 'panel.account': 'Account',
            'panel.back': '← Game catalogue', 'panel.reset_pw': 'Reset password via email',
            'panel.watch_sub': 'Wishlist import, price alerts and your list',
            'panel.sort': 'Sort', 'panel.sort_newest': 'Newest', 'panel.sort_price_asc': 'Price low to high',
            'panel.sort_price_desc': 'Price high to low', 'panel.sort_name': 'Alphabetical', 'panel.only_priced': 'Priced only',
            'panel.refresh_prices': 'Refresh prices', 'panel.alerts': 'Price alerts',
            'panel.spotlight_nav': 'Homepage', 'panel.spotlight_title': 'Homepage spotlight',
            'panel.spotlight_sub': 'Up to 8 games — large covers at the top. Order = left to right on site.',
            'panel.spotlight_save': 'Save to homepage', 'panel.spotlight_steam': 'Steam link or appid',
            'panel.spotlight_add': 'Add', 'panel.spotlight_search': 'Search catalogue',
            'panel.spotlight_empty': 'No games yet — add a Steam link or search by title.',
            'panel.spotlight_duplicate': 'This game is already on the list.', 'panel.spotlight_max': 'Maximum 8 games.',
            'panel.spotlight_added': 'Added to list (click Save).', 'panel.spotlight_saved': 'Saved to homepage.',
            'panel.scan_all_shops': 'Scan all stores', 'panel.spotlight_scanning': 'Scanning in background…',
            'panel.spotlight_scan_done': 'Scan started — refresh in a moment.',
            'spotlight.kicker': 'night city // your picks', 'spotlight.title': 'Featured',
            'search.no_results': 'No results',
            'legal.pl_only': 'Full legal text is in Polish. Summary in your selected language below.',
            'footer.copy': '© 2026 KupujPL · PC game price comparison',
            'trust.aria': 'Trust', 'trust.games': 'games in database', 'trust.shops': 'stores compared',
            'trust.updated_val': 'live', 'trust.updated': 'price updates',
            'trust.free_val': 'free', 'trust.free': 'always, no limits',
            'faq.kicker': 'night city // FAQ', 'faq.title': 'Frequently asked questions',
            'faq.q1': 'Does KupujPL sell games or keys?',
            'faq.a1': 'No. We are a price comparison site — we show store offers, and you buy directly from the chosen seller. We take no payments and store no card data.',
            'faq.q2': 'Is the service safe to use?',
            'faq.a2': 'Yes. The site runs over HTTPS, we don’t sell anything or process payments. We only redirect to stores — and mark which are official and which are key marketplaces.',
            'faq.q3': 'Why are prices on key marketplaces lower?',
            'faq.a3': 'Marketplaces (e.g. Eneba, Kinguin, G2A) host offers from many sellers — hence lower prices but higher risk. Always check the seller’s rating and refund policy.',
            'faq.q4': 'How often do you update prices?',
            'faq.a4': 'We refresh prices regularly, and scan the most popular titles live when you open a game page. Logged-in users can force a refresh of their favourites.',
            'faq.q5': 'Is the service free?',
            'faq.a5': 'Yes, fully and without limits. Some store links are affiliate links — if you buy after following our link, the store may pay us a commission. The price for you stays the same.',
            'title.home': 'KupujPL — PC game price comparison',
        },
    };

    function getLang() {
        const stored = localStorage.getItem(LANG_KEY);
        if (stored && M[stored]) return stored;
        const nav = (navigator.language || '').toLowerCase();
        if (nav.startsWith('uk') || nav.startsWith('ru')) return 'uk';
        if (nav.startsWith('en')) return 'en';
        return DEFAULT_LANG;
    }

    function setLang(lang) {
        if (!M[lang]) return;
        localStorage.setItem(LANG_KEY, lang);
        document.documentElement.lang = lang === 'uk' ? 'uk' : lang;
        applyPage();
        document.dispatchEvent(new CustomEvent('langchange', { detail: { lang } }));
    }

    function t(key, vars) {
        const lang = getLang();
        let s = (M[lang] && M[lang][key]) || (M.pl[key]) || key;
        if (vars) {
            Object.keys(vars).forEach((k) => {
                s = s.replace(new RegExp(`\\{${k}\\}`, 'g'), vars[k]);
            });
        }
        return s;
    }

    function tHtml(key, vars) {
        return t(key, vars);
    }

    function applyPage() {
        document.querySelectorAll('[data-i18n]').forEach((el) => {
            const key = el.getAttribute('data-i18n');
            if (!key) return;
            el.textContent = t(key);
        });
        document.querySelectorAll('[data-i18n-html]').forEach((el) => {
            const key = el.getAttribute('data-i18n-html');
            if (!key) return;
            el.innerHTML = t(key);
        });
        document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
            el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
        });
        document.querySelectorAll('[data-i18n-aria]').forEach((el) => {
            el.setAttribute('aria-label', t(el.getAttribute('data-i18n-aria')));
        });
        const titleKey = document.body?.getAttribute('data-i18n-title');
        if (titleKey) document.title = t(titleKey);

        document.querySelectorAll('[data-i18n-banner]').forEach((el) => {
            const link = `<a href="kontakt">${t('banner.dev_link')}</a>`;
            el.innerHTML = t('banner.dev', { link });
        });
        document.querySelectorAll('[data-i18n-legal]').forEach((el) => {
            el.innerHTML = t('auth.legal_use', {
                reg: `<a href="regulamin">${t('auth.legal_reg')}</a>`,
                priv: `<a href="polityka-prywatnosci">${t('auth.legal_priv')}</a>`,
            });
        });
        document.querySelectorAll('[data-i18n-oauth]').forEach((el) => {
            const isReg = el.id?.includes('register');
            const key = isReg ? 'auth.oauth_register' : 'auth.oauth_login';
            el.innerHTML = t(key, {
                link: `<a href="polityka-prywatnosci">${t('auth.privacy_link')}</a>`,
            });
        });

        document.querySelectorAll('.legal-lang-note').forEach((el) => {
            if (getLang() !== 'pl') {
                el.hidden = false;
                el.textContent = t('legal.pl_only');
            } else {
                el.hidden = true;
            }
        });

        document.querySelectorAll('.lang-switch .lang-btn').forEach((btn) => {
            const active = btn.getAttribute('data-lang') === getLang();
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });

        document.querySelectorAll('.theme-switch-label').forEach((el) => {
            el.textContent = t('theme.label');
        });
        document.querySelectorAll('.theme-switch .theme-btn').forEach((btn) => {
            const id = btn.getAttribute('data-theme');
            if (!id) return;
            btn.textContent = t('theme.' + id);
            btn.title = t('theme.' + id + '_title');
        });
        const themeNav = document.querySelector('.theme-switch');
        if (themeNav) {
            themeNav.setAttribute('aria-label', t('theme.aria'));
        }
    }

    function mountLangSwitcher() {
        document.querySelectorAll('.header-inner').forEach((inner) => {
            if (inner.querySelector('.lang-switch')) return;
            const authNav = inner.querySelector('#auth-nav');
            let host = inner.querySelector('.header-actions');
            if (!host && authNav) {
                host = document.createElement('div');
                host.className = 'header-actions';
                inner.insertBefore(host, authNav);
                host.appendChild(authNav);
            }
            if (!host) host = inner;

            const nav = document.createElement('nav');
            nav.className = 'lang-switch';
            nav.setAttribute('aria-label', 'Language');
            ['pl', 'uk', 'en'].forEach((code) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'lang-btn';
                btn.dataset.lang = code;
                btn.textContent = t('lang.' + code);
                btn.addEventListener('click', () => setLang(code));
                nav.appendChild(btn);
            });
            if (host.classList.contains('header-actions')) {
                host.insertBefore(nav, host.firstChild);
            } else if (authNav) {
                inner.insertBefore(nav, authNav);
            } else {
                host.appendChild(nav);
            }
        });
    }

    function locale() {
        return LOCALES[getLang()] || LOCALES.pl;
    }

    const I18n = { getLang, setLang, t, tHtml, applyPage, mountLangSwitcher, locale };
    global.I18n = I18n;
    global.t = t;

    document.addEventListener('DOMContentLoaded', () => {
        document.documentElement.lang = getLang() === 'uk' ? 'uk' : getLang();
        mountLangSwitcher();
        applyPage();
    });
})(typeof window !== 'undefined' ? window : globalThis);

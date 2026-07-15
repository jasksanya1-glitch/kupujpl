const MOCK_GAMES = [
    { title: "Counter-Strike 2", price: "0,00 zł", img: "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/730/header.jpg" },
    { title: "Wiedźmin 3: Dziki Gon", price: "29,80 zł", img: "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/292030/header.jpg" },
    { title: "Cyberpunk 2077", price: "119,99 zł", img: "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/1091500/header.jpg" },
    { title: "Hades", price: "47,99 zł", img: "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/1145360/header.jpg" },
    { title: "ELDEN RING", price: "149,99 zł", img: "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/1245620/header.jpg" },
    { title: "Forza Horizon 5", price: "89,99 zł", img: "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/1551360/header.jpg" },
    { title: "Baldur's Gate 3", price: "199,99 zł", img: "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/1086940/header.jpg" },
    { title: "Red Dead Redemption 2", price: "79,99 zł", img: "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/1174180/header.jpg" },
];
const MOCK_CATS = ["Wszystkie", "Akcja", "RPG", "Indie", "Sport", "Strategie", "Przygodowe"];

function cardHtml(g) {
    return `<article class="card"><img src="${g.img}" alt=""><div class="card-body"><h3>${g.title}</h3><div class="price">${g.price}</div></div></article>`;
}

function catsHtml(cls = "cat") {
    return MOCK_CATS.map((c, i) => `<button type="button" class="${cls}${i === 0 ? " active" : ""}">${c}</button>`).join("");
}

function headerHtml() {
    return `<header class="site wrap"><a class="logo" href="#">Kupuj<span>PL</span></a><input class="search" placeholder="Szukaj gry…"><a class="nav" href="#">Zaloguj</a></header>`;
}

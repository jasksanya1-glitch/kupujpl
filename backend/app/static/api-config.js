/** Resolve API/static base when app is served under /games/ */
(function () {
    const match = window.location.pathname.match(/^(.*\/games)\/?/i);
    const root = match ? `${match[1]}/` : "/games/";
    window.GAMES_ROOT = root;
    window.apiUrl = function apiUrl(path) {
        const clean = String(path || "").replace(/^\//, "");
        return `${root}api/${clean}`;
    };
})();

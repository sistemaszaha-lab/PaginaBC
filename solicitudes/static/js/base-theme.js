// Apply theme before first paint to avoid flicker.
(function () {
    try {
        var saved = localStorage.getItem("theme");
        var prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
        var theme = saved || (prefersDark ? "dark" : "light");
        var html = document.documentElement;
        html.setAttribute("data-bs-theme", theme);
        html.classList.toggle("dark", theme === "dark");
    } catch (e) { }
})();

const toggleBtn = document.getElementById("themeToggle");
const htmlElement = document.documentElement;
const body = document.body;
const sidebarToggle = document.getElementById("sidebarToggle");
const sidebarBackdrop = document.getElementById("sidebarBackdrop");
const sidebarLinks = document.querySelectorAll(".sidebar a");

function applyTheme(theme) {
    htmlElement.setAttribute("data-bs-theme", theme);
    htmlElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("theme", theme);
    updateButton(theme);
}

const savedTheme = localStorage.getItem("theme");
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
applyTheme(savedTheme || (prefersDark ? "dark" : "light"));

toggleBtn.addEventListener("click", () => {
    const currentTheme = htmlElement.getAttribute("data-bs-theme") || "light";
    applyTheme(currentTheme === "dark" ? "light" : "dark");
});

function updateButton(theme) {
    toggleBtn.innerHTML = theme === "dark" ? "Modo claro" : "Modo oscuro";
    toggleBtn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
}

const mobileQuery = window.matchMedia("(max-width: 768px)");
const savedSidebarState = localStorage.getItem("sidebarCollapsed");

function updateSidebarIcon() {
    if (mobileQuery.matches) {
        sidebarToggle.innerHTML = body.classList.contains("sidebar-open") ? "&times;" : "&#9776;";
    } else {
        sidebarToggle.innerHTML = body.classList.contains("sidebar-collapsed") ? "&#9776;" : "&times;";
    }
}

function syncSidebarMode() {
    if (mobileQuery.matches) {
        body.classList.remove("sidebar-collapsed");
        body.classList.remove("sidebar-open");
    } else {
        body.classList.remove("sidebar-open");
        if (savedSidebarState === "true") {
            body.classList.add("sidebar-collapsed");
        } else {
            body.classList.remove("sidebar-collapsed");
        }
    }
    updateSidebarIcon();
}

syncSidebarMode();
mobileQuery.addEventListener("change", syncSidebarMode);

sidebarToggle.addEventListener("click", (e) => {
    e.stopPropagation(); // Evitar propagación para no cerrar de inmediato
    if (mobileQuery.matches) {
        body.classList.toggle("sidebar-open");
    } else {
        body.classList.toggle("sidebar-collapsed");
        const collapsed = body.classList.contains("sidebar-collapsed");
        localStorage.setItem("sidebarCollapsed", collapsed ? "true" : "false");
    }
    updateSidebarIcon();
});

// Evento global para cerrar al hacer click fuera
document.addEventListener("click", (e) => {
    if (!mobileQuery.matches) return;

    // Detectar si el sidebar está abierto en móvil
    if (body.classList.contains("sidebar-open")) {
        const sidebar = document.querySelector(".sidebar");
        // Si el click NO fue dentro del sidebar (el click del botón ya fue bloqueado por stopPropagation)
        if (sidebar && !sidebar.contains(e.target)) {
            body.classList.remove("sidebar-open");
            updateSidebarIcon();
        }
    }
});

// OPCIONAL: Cerrar el menú al hacer click en los enlaces (<a>) dentro del sidebar
sidebarLinks.forEach((link) => {
    link.addEventListener("click", () => {
        if (!mobileQuery.matches) return;
        body.classList.remove("sidebar-open");
        updateSidebarIcon();
    });
});

(() => {
    const normalizeUppercaseCliente = (value) => value.trimStart().replace(/\s+/g, " ").toUpperCase();

    document.addEventListener("input", (event) => {
        const input = event.target;
        if (!input || !input.classList || !input.classList.contains("js-uppercase-cliente")) return;
        if (typeof input.selectionStart !== "number" || typeof input.selectionEnd !== "number") return;

        const start = input.selectionStart;
        const end = input.selectionEnd;
        const original = input.value;
        const normalized = normalizeUppercaseCliente(original);

        if (original === normalized) return;

        const beforeStart = normalizeUppercaseCliente(original.slice(0, start));
        const beforeEnd = normalizeUppercaseCliente(original.slice(0, end));

        input.value = normalized;
        input.setSelectionRange(beforeStart.length, beforeEnd.length);
    });
})();

window.getCookie = window.getCookie || function (name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (const cookie of cookies) {
            const trimmed = cookie.trim();
            if (trimmed.startsWith(name + "=")) {
                cookieValue = decodeURIComponent(trimmed.slice(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
};

window.getCSRFToken = window.getCSRFToken || function (root = document) {
    let token = window.getCookie("csrftoken");
    if (!token && root && root.querySelector) {
        const input = root.querySelector('input[name="csrfmiddlewaretoken"]');
        if (input && input.value) {
            token = input.value;
        }
    }
    if (!token) {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.content) {
            token = meta.content;
        }
    }
    return token || null;
};

window.csrfFetch = function (url, options = {}) {
    const requestOptions = { ...options };
    const headers = new Headers(requestOptions.headers || {});
    const method = (requestOptions.method || "GET").toUpperCase();

    if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) {
        const formToken = document.querySelector(
            'input[name="csrfmiddlewaretoken"]'
        )?.value;

        const cookieToken = document.cookie
            .split("; ")
            .find(row => row.startsWith("csrftoken="))
            ?.split("=")[1];

        const token = formToken || cookieToken;

        if (!token) {
            throw new Error("CSRF token not found");
        }

        headers.set("X-CSRFToken", decodeURIComponent(token));
    }

    return fetch(url, {
        ...requestOptions,
        headers,
        credentials: "same-origin",
    });
};

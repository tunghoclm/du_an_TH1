// =========================
// LOAD THEME
// =========================

const savedSettings =
    JSON.parse(localStorage.getItem("settings")) || {};

if (savedSettings.darkMode) {
    document.body.classList.add("dark-mode");
}
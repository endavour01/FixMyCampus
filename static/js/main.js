const currentYear = document.getElementById("current-year");
const menuToggle = document.querySelector("[data-menu-toggle]");
const siteNav = document.querySelector("[data-site-nav]");

if (currentYear) {
    currentYear.textContent = new Date().getFullYear();
}

if (menuToggle && siteNav) {
    const closeMenu = () => {
        menuToggle.setAttribute("aria-expanded", "false");
        menuToggle.querySelector(".visually-hidden").textContent = "Open navigation";
        siteNav.classList.remove("is-open");
    };

    menuToggle.addEventListener("click", () => {
        const isOpen = menuToggle.getAttribute("aria-expanded") === "true";
        menuToggle.setAttribute("aria-expanded", String(!isOpen));
        menuToggle.querySelector(".visually-hidden").textContent = isOpen
            ? "Open navigation"
            : "Close navigation";
        siteNav.classList.toggle("is-open", !isOpen);
    });

    siteNav.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", closeMenu);
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeMenu();
        }
    });
}
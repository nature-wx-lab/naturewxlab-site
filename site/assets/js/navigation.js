(function () {
  "use strict";

  document.documentElement.classList.add("nav-js");

  function initializeNavigation() {
    var toggle = document.querySelector("[data-nav-toggle]");
    var nav = document.querySelector("[data-global-nav]");

    if (!toggle || !nav) {
      return;
    }

    var header = toggle.closest(".site-header");
    var desktopQuery = window.matchMedia("(min-width: 881px)");

    function setOpen(isOpen, restoreFocus) {
      toggle.setAttribute("aria-expanded", String(isOpen));
      toggle.setAttribute("aria-label", isOpen ? "メニューを閉じる" : "メニューを開く");
      nav.classList.toggle("is-open", isOpen);

      if (header) {
        header.classList.toggle("nav-open", isOpen);
      }

      if (!isOpen && restoreFocus) {
        toggle.focus();
      }
    }

    toggle.addEventListener("click", function () {
      setOpen(toggle.getAttribute("aria-expanded") !== "true", false);
    });

    nav.addEventListener("click", function (event) {
      if (event.target.closest("a")) {
        setOpen(false, false);
      }
    });

    document.addEventListener("click", function (event) {
      if (header && !header.contains(event.target)) {
        setOpen(false, false);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setOpen(false, true);
      }
    });

    function handleDesktopChange(event) {
      if (event.matches) {
        setOpen(false, false);
      }
    }

    if (desktopQuery.addEventListener) {
      desktopQuery.addEventListener("change", handleDesktopChange);
    } else {
      desktopQuery.addListener(handleDesktopChange);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeNavigation);
  } else {
    initializeNavigation();
  }
})();

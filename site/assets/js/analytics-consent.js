(function () {
  "use strict";

  var CONSENT_KEY = "naturewxlab.analytics-consent.v1";
  var PRODUCTION_HOST = "naturewxlab.com";
  var SAFE_PATHS = Object.freeze({
    "/": "/",
    "/index.html": "/",
    "/tools/": "/tools/",
    "/tools/index.html": "/tools/",
    "/about/": "/about/",
    "/about/index.html": "/about/",
    "/vision/": "/vision/",
    "/vision/index.html": "/vision/",
    "/policy/": "/policy/",
    "/policy/index.html": "/policy/",
    "/404.html": "/404/"
  });
  var CONFIG = window.NATUREWXLAB_ANALYTICS || {};
  var measurementId = typeof CONFIG.measurementId === "string" ? CONFIG.measurementId.trim() : "";
  var hasValidMeasurementId = /^G-[A-Z0-9]{6,}$/.test(measurementId);
  var isProductionHost = window.location.hostname === PRODUCTION_HOST;
  var analyticsLoaded = false;
  var settingsTrigger = null;

  window.dataLayer = window.dataLayer || [];

  function gtag() {
    window.dataLayer.push(arguments);
  }

  gtag("consent", "default", {
    analytics_storage: "denied",
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
    wait_for_update: 500
  });

  function readConsent() {
    try {
      return window.localStorage.getItem(CONSENT_KEY);
    } catch (_error) {
      return null;
    }
  }

  function writeConsent(value) {
    try {
      window.localStorage.setItem(CONSENT_KEY, value);
    } catch (_error) {
      return;
    }
  }

  function safePathname() {
    return SAFE_PATHS[window.location.pathname] || "/404/";
  }

  function safeLocation() {
    return window.location.origin + safePathname();
  }

  function safeReferrer() {
    if (!document.referrer) {
      return "";
    }

    try {
      var referrer = new URL(document.referrer);
      return referrer.origin;
    } catch (_error) {
      return "";
    }
  }

  function loadAnalytics() {
    if (!hasValidMeasurementId || !isProductionHost || analyticsLoaded) {
      return;
    }

    analyticsLoaded = true;
    window["ga-disable-" + measurementId] = false;

    gtag("consent", "update", {
      analytics_storage: "granted",
      ad_storage: "denied",
      ad_user_data: "denied",
      ad_personalization: "denied"
    });
    gtag("js", new Date());
    gtag("config", measurementId, {
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
      ads_data_redaction: true,
      cookie_expires: 7776000,
      cookie_flags: "SameSite=Lax;Secure",
      page_location: safeLocation(),
      page_referrer: safeReferrer(),
      send_page_view: false
    });
    gtag("event", "page_view", {
      page_location: safeLocation(),
      page_referrer: safeReferrer(),
      page_title: document.title
    });

    var script = document.createElement("script");
    script.async = true;
    script.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(measurementId);
    script.referrerPolicy = "strict-origin-when-cross-origin";
    document.head.appendChild(script);
  }

  function clearAnalyticsCookies() {
    document.cookie.split(";").forEach(function (cookie) {
      var name = cookie.split("=")[0].trim();
      if (name === "_ga" || name.indexOf("_ga_") === 0) {
        document.cookie = name + "=; Max-Age=0; Path=/; SameSite=Lax; Secure";
        document.cookie = name + "=; Max-Age=0; Path=/; Domain=.naturewxlab.com; SameSite=Lax; Secure";
      }
    });
  }

  function disableAnalytics() {
    if (hasValidMeasurementId) {
      window["ga-disable-" + measurementId] = true;
    }
    gtag("consent", "update", {
      analytics_storage: "denied",
      ad_storage: "denied",
      ad_user_data: "denied",
      ad_personalization: "denied"
    });
    clearAnalyticsCookies();
  }

  function showBanner(event) {
    if (event && event.currentTarget) {
      settingsTrigger = event.currentTarget;
    }
    var banner = document.querySelector("[data-analytics-consent]");
    if (banner) {
      banner.hidden = false;
      var firstButton = banner.querySelector("button");
      if (firstButton) {
        firstButton.focus();
      }
    }
  }

  function hideBanner(restoreFocus) {
    var banner = document.querySelector("[data-analytics-consent]");
    if (banner) {
      banner.hidden = true;
    }
    if (restoreFocus && settingsTrigger) {
      settingsTrigger.focus();
      settingsTrigger = null;
    }
  }

  function setConsent(value) {
    var shouldReload = value === "denied" && analyticsLoaded;
    writeConsent(value);
    if (value === "granted") {
      loadAnalytics();
    } else {
      disableAnalytics();
    }
    hideBanner(!shouldReload);
    if (shouldReload) {
      window.location.reload();
    }
  }

  function trackSafeOutboundClick(event) {
    if (readConsent() !== "granted" || !analyticsLoaded) {
      return;
    }

    var link = event.target.closest("a[data-track-destination]");
    if (!link) {
      return;
    }

    var destination = link.getAttribute("data-track-destination") || "";
    if (!/^[a-z0-9_-]{1,48}$/.test(destination)) {
      return;
    }

    gtag("event", "outbound_click", {
      destination: destination,
      transport_type: "beacon"
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var consent = readConsent();
    var accept = document.querySelector("[data-analytics-accept]");
    var decline = document.querySelector("[data-analytics-decline]");
    var settings = document.querySelectorAll("[data-analytics-settings]");

    if (accept) {
      accept.addEventListener("click", function () {
        setConsent("granted");
      });
    }

    if (decline) {
      decline.addEventListener("click", function () {
        setConsent("denied");
      });
    }

    settings.forEach(function (button) {
      button.addEventListener("click", showBanner);
    });

    document.addEventListener("click", trackSafeOutboundClick);

    if (consent === "granted") {
      loadAnalytics();
    } else if (consent === "denied") {
      disableAnalytics();
    } else {
      showBanner();
    }
  });
})();

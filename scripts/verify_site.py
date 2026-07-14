#!/usr/bin/env python3
"""Dependency-free publication checks for the NatureWxLab static site."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = REPO_ROOT / "site"
HTML_FILES = sorted(SITE_ROOT.glob("*.html")) + sorted(SITE_ROOT.glob("*/index.html"))
REQUIRED_FILES = {
    "index.html",
    "tools/index.html",
    "about/index.html",
    "vision/index.html",
    "policy/index.html",
    "404.html",
    "assets/css/styles.css",
    "assets/js/analytics-config.js",
    "assets/js/analytics-consent.js",
    "assets/icons/naturewxlab-icon.png",
    "assets/images/hero-family-garden-medaka-v2.png",
    "assets/images/og-image.jpg",
    "assets/images/og-image.svg",
    "robots.txt",
    "sitemap.xml",
    "site.webmanifest",
    "_headers",
}
FORBIDDEN_TAGS = {"form", "input", "textarea", "select", "iframe", "object", "embed"}
LOCAL_ASSET_ATTRIBUTES = {
    ("script", "src"),
    ("link", "href"),
    ("img", "src"),
    ("source", "srcset"),
}
MEASUREMENT_ID_RE = re.compile(r"\bG-[A-Z0-9]{6,}\b")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


class PageParser(HTMLParser):
    def __init__(self, path: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.path = path
        self.errors: list[str] = []
        self.h1_count = 0
        self.title_count = 0
        self.description_count = 0
        self.viewport_count = 0
        self.html_lang = ""
        self.links: list[str] = []
        self.has_analytics_config = False
        self.has_analytics_consent = False
        self.has_consent_ui = False
        self.has_versioned_stylesheet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "html":
            self.html_lang = attributes.get("lang") or ""
        if tag == "h1":
            self.h1_count += 1
        if tag == "title":
            self.title_count += 1
        if tag == "meta" and attributes.get("name") == "description":
            self.description_count += 1
        if tag == "meta" and attributes.get("name") == "viewport":
            self.viewport_count += 1
        if tag in FORBIDDEN_TAGS:
            self.errors.append(f"forbidden <{tag}> element")
        if tag == "script" and "src" not in attributes:
            self.errors.append("inline script is not allowed")
        if tag == "style":
            self.errors.append("inline style element is not allowed")
        for name, value in attrs:
            if name.lower().startswith("on"):
                self.errors.append(f"inline event handler {name} is not allowed")
            if name == "style":
                self.errors.append("style attribute is not allowed")
            if value and value.strip().lower().startswith("javascript:"):
                self.errors.append(f"javascript URL in {name}")
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"])
        if tag == "script" and attributes.get("src") == "/assets/js/analytics-config.js":
            self.has_analytics_config = True
        if tag == "script" and attributes.get("src") == "/assets/js/analytics-consent.js":
            self.has_analytics_consent = True
        if tag == "link" and attributes.get("rel") == "stylesheet":
            stylesheet = urlsplit(attributes.get("href") or "")
            if stylesheet.path == "/assets/css/styles.css" and stylesheet.query:
                self.has_versioned_stylesheet = True
        if "data-analytics-consent" in attributes:
            self.has_consent_ui = True
        for element, attribute in LOCAL_ASSET_ATTRIBUTES:
            if tag != element or not attributes.get(attribute):
                continue
            value = attributes[attribute]
            if element == "link" and attributes.get("rel") == "canonical":
                continue
            if value.startswith(("http://", "https://", "//")):
                self.errors.append(f"remote {element} asset is not allowed: {value}")


def internal_target(href: str) -> Path | None:
    if not href.startswith("/") or href.startswith("//"):
        return None
    path = urlsplit(href).path
    if path == "/":
        return SITE_ROOT / "index.html"
    candidate = SITE_ROOT / path.lstrip("/")
    if path.endswith("/"):
        return candidate / "index.html"
    return candidate


def main() -> int:
    errors: list[str] = []
    expected_measurement_id = os.environ.get("NATUREWXLAB_GA4_ID", "").strip()
    if expected_measurement_id and not MEASUREMENT_ID_RE.fullmatch(expected_measurement_id):
        errors.append("NATUREWXLAB_GA4_ID is not a valid GA4 measurement ID")
    actual_files = {str(path.relative_to(SITE_ROOT)) for path in SITE_ROOT.rglob("*") if path.is_file()}
    for missing in sorted(REQUIRED_FILES - actual_files):
        errors.append(f"missing required file: {missing}")
    for unexpected in sorted(actual_files - REQUIRED_FILES):
        errors.append(f"unexpected file in deploy artifact: {unexpected}")
    expected_asset_sha256 = {
        "assets/icons/naturewxlab-icon.png": "7dd3f9bb3cd0eebeaf76a8e0145656bab6391a0e5892334d7ebb32953d9093e1",
        "assets/images/hero-family-garden-medaka-v2.png": "8e812c8d3e02afd15fa60fffcd65195940a1623c998e0ebc1a72842ae5462bc1",
        "assets/images/og-image.jpg": "9198c25cae29d01cdfaab1941c5095bad66627abd17003bedf6c04294e9ad35b",
    }
    for relative, expected_sha256 in expected_asset_sha256.items():
        asset = SITE_ROOT / relative
        if asset.is_file() and hashlib.sha256(asset.read_bytes()).hexdigest() != expected_sha256:
            errors.append(f"{relative}: supplied image bytes changed unexpectedly")
    for path in SITE_ROOT.rglob("*"):
        if path.is_symlink():
            errors.append(f"symlink is not allowed in deploy artifact: {path.relative_to(SITE_ROOT)}")
    for relative in sorted(actual_files):
        parts = Path(relative).parts
        if "__pycache__" in parts or relative.endswith((".pyc", ".pyo")):
            errors.append(f"generated Python artifact must not be published: {relative}")

    for path in HTML_FILES:
        parser = PageParser(path)
        parser.feed(path.read_text(encoding="utf-8"))
        relative = path.relative_to(SITE_ROOT)
        for error in parser.errors:
            errors.append(f"{relative}: {error}")
        if parser.html_lang != "ja":
            errors.append(f"{relative}: html lang must be ja")
        if parser.h1_count != 1:
            errors.append(f"{relative}: expected one h1, found {parser.h1_count}")
        if parser.title_count != 1:
            errors.append(f"{relative}: expected one title, found {parser.title_count}")
        if parser.description_count != 1:
            errors.append(f"{relative}: expected one meta description")
        if parser.viewport_count != 1:
            errors.append(f"{relative}: expected one viewport meta")
        if not parser.has_analytics_config or not parser.has_analytics_consent:
            errors.append(f"{relative}: analytics safety scripts are missing")
        if not parser.has_versioned_stylesheet:
            errors.append(f"{relative}: stylesheet URL must include a cache-busting version")
        if not parser.has_consent_ui:
            errors.append(f"{relative}: analytics consent UI is missing")
        for href in parser.links:
            if href.startswith("http://"):
                errors.append(f"{relative}: insecure external link: {href}")
            target = internal_target(href)
            if target is not None and not target.is_file():
                errors.append(f"{relative}: broken internal link: {href}")

    expected_canonicals = {
        Path("index.html"): "https://naturewxlab.com/",
        Path("tools/index.html"): "https://naturewxlab.com/tools/",
        Path("about/index.html"): "https://naturewxlab.com/about/",
        Path("vision/index.html"): "https://naturewxlab.com/vision/",
        Path("policy/index.html"): "https://naturewxlab.com/policy/",
    }
    expected_tool_states = {
        "気温リスクナビ": ("status", "公開中", "気温リスクナビを開く"),
        "天気分布予報プラス": ("status", "公開中", "天気分布予報プラスを開く"),
        "うるおい管理ナビ": ("status beta", "β版", "うるおい管理ナビβ版を開く"),
        "気候ものさしナビ": ("status beta", "β版", "気候ものさしナビβ版を開く"),
    }
    for relative in (Path("index.html"), Path("tools/index.html")):
        text = (SITE_ROOT / relative).read_text(encoding="utf-8")
        for tool_name, (status_class, status_label, link_label) in expected_tool_states.items():
            card_pattern = re.compile(
                rf'<article class="tool-card">(?:(?!</article>).)*<h3>{re.escape(tool_name)}</h3>'
                rf'(?:(?!</article>).)*<span class="{status_class}">{status_label}</span>'
                rf'(?:(?!</article>).)*>{re.escape(link_label)}</a>(?:(?!</article>).)*</article>',
                re.DOTALL,
            )
            if not card_pattern.search(text):
                errors.append(f"{relative}: unexpected status or link label for {tool_name}")
    expected_brand_icon = '<img src="/assets/icons/naturewxlab-icon.png" width="54" height="54" alt="" aria-hidden="true">'
    expected_favicon = '<link rel="icon" href="/assets/icons/naturewxlab-icon.png" type="image/png">'
    expected_apple_touch = '<link rel="apple-touch-icon" href="/assets/icons/naturewxlab-icon.png">'
    expected_stylesheet = '<link rel="stylesheet" href="/assets/css/styles.css?v=20260714-4">'
    for relative in HTML_FILES:
        text = relative.read_text(encoding="utf-8")
        page = relative.relative_to(SITE_ROOT)
        if text.count(expected_brand_icon) != 1:
            errors.append(f"{page}: official brand icon is missing or duplicated")
        if text.count(expected_favicon) != 1 or text.count(expected_apple_touch) != 1:
            errors.append(f"{page}: official browser icon links are missing or duplicated")
        if text.count(expected_stylesheet) != 1:
            errors.append(f"{page}: current stylesheet version is missing or duplicated")
        if any(old_asset in text for old_asset in ("favicon.svg", "apple-touch-icon.png", "logo.svg")):
            errors.append(f"{page}: obsolete brand icon reference remains")
    home_text = (SITE_ROOT / "index.html").read_text(encoding="utf-8")
    expected_hero = '<img src="/assets/images/hero-family-garden-medaka-v2.png" width="1254" height="1254" alt="" decoding="async" fetchpriority="high">'
    if home_text.count(expected_hero) != 1:
        errors.append("index.html: supplied family garden hero image is missing or duplicated")
    if "hero-weather-nature-v2" in home_text or "hero-family-garden-medaka.jpg" in home_text:
        errors.append("index.html: obsolete hero image reference remains")
    expected_instagram = '<a href="https://www.instagram.com/nature_wx_lab/" data-track-destination="media_instagram">Instagramを見る</a>'
    if home_text.count(expected_instagram) != 1:
        errors.append("index.html: official Instagram link is missing or duplicated")
    for relative, canonical in expected_canonicals.items():
        text = (SITE_ROOT / relative).read_text(encoding="utf-8")
        if text.count(f'<link rel="canonical" href="{canonical}">') != 1:
            errors.append(f"{relative}: canonical URL is missing or duplicated")
        if 'content="https://naturewxlab.com/assets/images/og-image.jpg"' not in text:
            errors.append(f"{relative}: social preview image is missing")

    manifest = json.loads((SITE_ROOT / "site.webmanifest").read_text(encoding="utf-8"))
    if manifest.get("name") != "NatureWxLab" or manifest.get("display") != "browser":
        errors.append("site.webmanifest: unexpected name or display mode")
    expected_manifest_icons = [
        {
            "src": "/assets/icons/naturewxlab-icon.png",
            "sizes": "1024x1024",
            "type": "image/png",
            "purpose": "any",
        }
    ]
    if manifest.get("icons") != expected_manifest_icons:
        errors.append("site.webmanifest: official icon set does not match")
    for icon in manifest.get("icons", []):
        icon_target = internal_target(icon.get("src", ""))
        if icon_target is None or not icon_target.is_file():
            errors.append(f"site.webmanifest: broken icon path: {icon.get('src', '')}")

    sitemap_tree = ET.parse(SITE_ROOT / "sitemap.xml")
    sitemap_locations = {
        node.text for node in sitemap_tree.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
    }
    if sitemap_locations != set(expected_canonicals.values()):
        errors.append("sitemap.xml: URLs do not match the canonical page set")
    robots = (SITE_ROOT / "robots.txt").read_text(encoding="utf-8")
    if "Sitemap: https://naturewxlab.com/sitemap.xml" not in robots:
        errors.append("robots.txt: canonical sitemap URL is missing")

    forbidden_byte_markers = (
        (b"/" + b"Users" + b"/", "macOS home path"),
        (b"file" + b"://", "local file URL"),
        (b"C:" + b"\\Users\\", "Windows home path"),
    )
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        relative = path.relative_to(REPO_ROOT)
        for marker, label in forbidden_byte_markers:
            if marker in payload:
                errors.append(f"{relative}: {label} found")

    observed_measurement_ids: dict[Path, set[str]] = {}
    public_text_extensions = {".html", ".css", ".js", ".json", ".xml", ".txt", ".md", ".py", ".svg"}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in public_text_extensions:
            continue
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(REPO_ROOT)
        if EMAIL_RE.search(text):
            errors.append(f"{relative}: email address found")
        matches = set(MEASUREMENT_ID_RE.findall(text))
        if matches:
            observed_measurement_ids[relative] = matches

    analytics = (SITE_ROOT / "assets/js/analytics-consent.js").read_text(encoding="utf-8")
    analytics_config = (SITE_ROOT / "assets/js/analytics-config.js").read_text(encoding="utf-8")
    for expected in (
        'var PRODUCTION_HOST = "naturewxlab.com"',
        "window.location.hostname === PRODUCTION_HOST",
        'analytics_storage: "denied"',
        'ad_storage: "denied"',
        'ad_user_data: "denied"',
        'ad_personalization: "denied"',
        "window.location.origin + safePathname()",
        "send_page_view: false",
    ):
        if expected not in analytics:
            errors.append(f"analytics-consent.js: missing safety invariant: {expected}")
    config_relative = Path("site/assets/js/analytics-config.js")
    if not expected_measurement_id:
        for relative, matches in observed_measurement_ids.items():
            errors.append(f"{relative}: GA4 measurement ID is present without release approval: {sorted(matches)}")
        if "measurementId" in analytics_config:
            errors.append("analytics-config.js: measurement ID must remain absent until the real dedicated ID is approved")
    else:
        for relative, matches in observed_measurement_ids.items():
            if relative != config_relative:
                errors.append(f"{relative}: GA4 measurement ID is only allowed in analytics-config.js")
            if matches != {expected_measurement_id}:
                errors.append(f"{relative}: GA4 measurement ID differs from the approved dedicated ID")
        if observed_measurement_ids.get(config_relative) != {expected_measurement_id}:
            errors.append("analytics-config.js: approved dedicated GA4 measurement ID is missing")
        if f'measurementId: "{expected_measurement_id}"' not in analytics_config:
            errors.append("analytics-config.js: approved ID is not assigned to measurementId")

    headers = (SITE_ROOT / "_headers").read_text(encoding="utf-8")
    for directive in (
        "Content-Security-Policy:",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "form-action 'none'",
        "script-src-attr 'none'",
        "style-src-attr 'none'",
        "X-Content-Type-Options: nosniff",
        "Referrer-Policy: strict-origin-when-cross-origin",
        "Permissions-Policy:",
    ):
        if directive not in headers:
            errors.append(f"_headers: missing security directive: {directive}")

    if errors:
        print("SITE VERIFICATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"SITE VERIFICATION PASSED ({len(HTML_FILES)} HTML pages, {len(actual_files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

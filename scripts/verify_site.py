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
    "assets/js/navigation.js",
    "assets/js/analytics-config.js",
    "assets/js/analytics-consent.js",
    "assets/icons/naturewxlab-icon.png",
    "assets/icons/service-auction.svg",
    "assets/icons/service-mercari.png",
    "assets/icons/social-instagram.svg",
    "assets/icons/social-note.svg",
    "assets/icons/social-x.svg",
    "assets/icons/social-youtube.svg",
    "assets/images/hero-family-garden-medaka-v2.png",
    "assets/images/og-image.jpg",
    "assets/images/og-image.svg",
    "assets/images/editorial-rose-garden-banner-20260716.jpg",
    "assets/images/editorial-medaka-pond-banner-20260716.jpg",
    "assets/images/editorial-summer-sky-banner-20260716.jpg",
    "assets/images/tool-preview-climate-outlook-20260716.jpg",
    "assets/images/tool-preview-temperature-risk-20260716.jpg",
    "assets/images/tool-preview-water-care-20260716.jpg",
    "assets/images/tool-preview-weather-distribution-20260716.jpg",
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
        self.has_navigation_script = False
        self.has_nav_toggle = False
        self.has_global_nav = False
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
        if tag == "script" and attributes.get("src") == "/assets/js/navigation.js":
            self.has_navigation_script = True
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
        if (
            tag == "button"
            and "data-nav-toggle" in attributes
            and attributes.get("aria-controls") == "global-nav"
            and attributes.get("aria-expanded") == "false"
        ):
            self.has_nav_toggle = True
        if (
            tag == "nav"
            and "data-global-nav" in attributes
            and attributes.get("id") == "global-nav"
        ):
            self.has_global_nav = True
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


def jpeg_dimensions(payload: bytes) -> tuple[int, int] | None:
    """Return JPEG width and height without adding an image-library dependency."""
    if not payload.startswith(b"\xff\xd8"):
        return None
    offset = 2
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    standalone_markers = {0x01, 0xD8, 0xD9, *range(0xD0, 0xD8)}
    while offset + 4 <= len(payload):
        if payload[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(payload) and payload[offset] == 0xFF:
            offset += 1
        if offset >= len(payload):
            break
        marker = payload[offset]
        offset += 1
        if marker in standalone_markers:
            continue
        if offset + 2 > len(payload):
            break
        segment_length = int.from_bytes(payload[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(payload):
            break
        if marker in sof_markers:
            if segment_length < 7:
                return None
            height = int.from_bytes(payload[offset + 3 : offset + 5], "big")
            width = int.from_bytes(payload[offset + 5 : offset + 7], "big")
            return width, height
        if marker == 0xDA:
            break
        offset += segment_length
    return None


def jpeg_app_segments(payload: bytes) -> list[tuple[int, bytes]] | None:
    """Return JPEG APP/comment segments before image data for metadata checks."""
    if not payload.startswith(b"\xff\xd8"):
        return None
    offset = 2
    segments: list[tuple[int, bytes]] = []
    standalone_markers = {0x01, 0xD8, 0xD9, *range(0xD0, 0xD8)}
    while offset + 2 <= len(payload):
        if payload[offset] != 0xFF:
            return None
        while offset < len(payload) and payload[offset] == 0xFF:
            offset += 1
        if offset >= len(payload):
            return None
        marker = payload[offset]
        offset += 1
        if marker in (0xD9, 0xDA):
            return segments
        if marker in standalone_markers:
            continue
        if offset + 2 > len(payload):
            return None
        segment_length = int.from_bytes(payload[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(payload):
            return None
        segment_payload = payload[offset + 2 : offset + segment_length]
        if 0xE0 <= marker <= 0xEF or marker == 0xFE:
            segments.append((marker, segment_payload))
        offset += segment_length
    return None


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
        "assets/icons/service-auction.svg": "478d6b3dfd463b6d20e231196282f21dcf2c713c3ccfec46e37620b194d673d6",
        "assets/icons/service-mercari.png": "e10e59e32930d1ef264d9aca191f1cee9e868a2abc30188b97b14a7a89575ab7",
        "assets/icons/social-instagram.svg": "103ab72561b73436703a2129eaf77bb9357b008b8f97a344ba0389a3990c9d41",
        "assets/icons/social-note.svg": "aae7e7cf0b0e9af6ba7fad113d38ade534835b5235c5c0ba9ae74814c83a34c8",
        "assets/icons/social-x.svg": "30bd48f0082d513928f4a04e6df09a22bcfb045ca9a8c52ecbff721fb4017012",
        "assets/icons/social-youtube.svg": "0410b0414d8f8c5f413970592e0a11edb3e3293f0e8efdd20c7d74d16067dd8b",
        "assets/images/hero-family-garden-medaka-v2.png": "8e812c8d3e02afd15fa60fffcd65195940a1623c998e0ebc1a72842ae5462bc1",
        "assets/images/og-image.jpg": "9198c25cae29d01cdfaab1941c5095bad66627abd17003bedf6c04294e9ad35b",
        "assets/images/editorial-rose-garden-banner-20260716.jpg": "b4faded810f7a6416a0c985324ebee3d902f0b6bb9072e9a8e8b87cf144295be",
        "assets/images/editorial-medaka-pond-banner-20260716.jpg": "b262dd031bf4c2ae230df2b7d60ccd01534817c89c98b82a89ad20e7bbedfb78",
        "assets/images/editorial-summer-sky-banner-20260716.jpg": "e8cc7c78ecbb04c621cb65c04a2106c429b2527eef355575a44a5fe337b2b27e",
        "assets/images/tool-preview-climate-outlook-20260716.jpg": "036e25c730b6864b6b1d963e28ffa90b05fc83f981d0be0921ab999a3b745b6f",
        "assets/images/tool-preview-temperature-risk-20260716.jpg": "3fb8f2c87de0ecb4e78b47fb27a88926d0b7f98104a46901c287a3642646e1bf",
        "assets/images/tool-preview-water-care-20260716.jpg": "db56f994547e8745fdfb05f55312698c995f4652b86f7369b4fa64365b28c7b2",
        "assets/images/tool-preview-weather-distribution-20260716.jpg": "49419fb547f5433be519e07343d3b362f474b9907187f7cf33aa37ab98190a04",
    }
    for relative, expected_sha256 in expected_asset_sha256.items():
        asset = SITE_ROOT / relative
        if asset.is_file() and hashlib.sha256(asset.read_bytes()).hexdigest() != expected_sha256:
            errors.append(f"{relative}: pinned asset bytes changed unexpectedly")

    preview_images = tuple(relative for relative in expected_asset_sha256 if relative.startswith("assets/images/tool-preview-"))
    for relative in preview_images:
        asset = SITE_ROOT / relative
        if not asset.is_file():
            continue
        payload = asset.read_bytes()
        if not payload.startswith(b"\xff\xd8\xff"):
            errors.append(f"{relative}: tool preview must be a JPEG file")
        if jpeg_dimensions(payload) != (1425, 891):
            errors.append(f"{relative}: tool preview dimensions must be 1425x891")

    editorial_photos = {
        "assets/images/editorial-rose-garden-banner-20260716.jpg": (2172, 724),
        "assets/images/editorial-medaka-pond-banner-20260716.jpg": (2048, 626),
        "assets/images/editorial-summer-sky-banner-20260716.jpg": (2048, 626),
    }
    if not set(editorial_photos).issubset(REQUIRED_FILES):
        errors.append("editorial photos must be present in the deploy allowlist")
    if not set(editorial_photos).issubset(expected_asset_sha256):
        errors.append("editorial photos must have pinned hashes")
    for relative, expected_dimensions in editorial_photos.items():
        asset = SITE_ROOT / relative
        if not asset.is_file():
            continue
        payload = asset.read_bytes()
        if not payload.startswith(b"\xff\xd8\xff"):
            errors.append(f"{relative}: editorial photo must be a JPEG file")
        if jpeg_dimensions(payload) != expected_dimensions:
            errors.append(f"{relative}: editorial photo dimensions changed")
        app_segments = jpeg_app_segments(payload)
        if app_segments is None:
            errors.append(f"{relative}: editorial photo has malformed JPEG metadata")
            continue
        if [marker for marker, _ in app_segments] != [0xE0, 0xE1]:
            errors.append(f"{relative}: editorial photo has unexpected metadata segments")
            continue
        app0, app1 = (segment for _, segment in app_segments)
        if not app0.startswith(b"JFIF\x00"):
            errors.append(f"{relative}: editorial photo is missing the expected JFIF marker")
        if len(app1) != 74 or not app1.startswith(b"Exif\x00\x00"):
            errors.append(f"{relative}: editorial photo EXIF block changed")
        metadata = b"".join(segment for _, segment in app_segments).lower()
        for marker in (b"gps", b"latitude", b"longitude", b"prompt", b"seed", b"/users/", b"file" + b"://", b"http", b"@"):
            if marker in metadata:
                errors.append(f"{relative}: editorial photo contains disallowed metadata")
                break

    safe_svg_files = (
        "assets/icons/service-auction.svg",
        "assets/icons/social-note.svg",
        "assets/icons/social-x.svg",
        "assets/icons/social-instagram.svg",
        "assets/icons/social-youtube.svg",
    )
    allowed_svg_tags = {"svg", "rect", "path"}
    forbidden_svg_markers = (
        "<!doctype",
        "<!entity",
        "<?xml-stylesheet",
        "javascript:",
        "data:",
        "url(",
    )
    for relative in safe_svg_files:
        asset = SITE_ROOT / relative
        if not asset.is_file():
            continue
        svg_text = asset.read_text(encoding="utf-8")
        lowered_svg = svg_text.lower()
        for marker in forbidden_svg_markers:
            if marker in lowered_svg:
                errors.append(f"{relative}: forbidden SVG marker: {marker}")
        try:
            svg_root = ET.fromstring(svg_text)
        except ET.ParseError as exc:
            errors.append(f"{relative}: invalid SVG XML: {exc}")
            continue
        root_tag = svg_root.tag.rsplit("}", 1)[-1]
        if root_tag != "svg" or not svg_root.get("viewBox"):
            errors.append(f"{relative}: SVG root or viewBox is invalid")
        for element in svg_root.iter():
            tag_name = element.tag.rsplit("}", 1)[-1]
            if tag_name not in allowed_svg_tags:
                errors.append(f"{relative}: forbidden SVG element: {tag_name}")
            if element.text and element.text.strip():
                errors.append(f"{relative}: visible or executable SVG text is not allowed")
            if element.tail and element.tail.strip():
                errors.append(f"{relative}: unexpected SVG tail text is not allowed")
            for attribute, value in element.attrib.items():
                attribute_name = attribute.rsplit("}", 1)[-1].lower()
                lowered_value = value.strip().lower()
                if attribute_name.startswith("on") or attribute_name in {"href", "style"}:
                    errors.append(f"{relative}: forbidden SVG attribute: {attribute_name}")
                if any(marker in lowered_value for marker in ("javascript:", "data:", "url(")):
                    errors.append(f"{relative}: forbidden SVG attribute value")
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
        if not parser.has_navigation_script or not parser.has_nav_toggle or not parser.has_global_nav:
            errors.append(f"{relative}: accessible mobile navigation is missing")
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
        "気温リスクナビ": ("status", "公開中", "気温リスクナビを開く", "https://nature-wx-lab.github.io/temperature-risk-navi/"),
        "天気分布予報プラス": ("status", "公開中", "天気分布予報プラスを開く", "https://nature-wx-lab.github.io/weather-distribution-plus/"),
        "うるおい管理ナビ": ("status beta", "β版", "うるおい管理ナビβ版を開く", "https://nature-wx-lab.github.io/water_care/"),
        "気候ものさしナビ": ("status beta", "β版", "気候ものさしナビβ版を開く", "https://nature-wx-lab.github.io/climate-outlook-navi/"),
    }
    for relative in (Path("index.html"), Path("tools/index.html")):
        text = (SITE_ROOT / relative).read_text(encoding="utf-8")
        for tool_name, (status_class, status_label, link_label, link_url) in expected_tool_states.items():
            card_pattern = re.compile(
                rf'<article class="tool-card">(?:(?!</article>).)*<h3>{re.escape(tool_name)}</h3>'
                rf'(?:(?!</article>).)*<span class="{status_class}">{status_label}</span>'
                rf'(?:(?!</article>).)*<a class="button compact" href="{re.escape(link_url)}" '
                rf'data-track-destination="[^"]+">{re.escape(link_label)}</a>(?:(?!</article>).)*</article>',
                re.DOTALL,
            )
            if not card_pattern.search(text):
                errors.append(f"{relative}: unexpected status or link label for {tool_name}")
    expected_brand_icon = '<img src="/assets/icons/naturewxlab-icon.png" width="54" height="54" alt="" aria-hidden="true">'
    expected_favicon = '<link rel="icon" href="/assets/icons/naturewxlab-icon.png" type="image/png">'
    expected_apple_touch = '<link rel="apple-touch-icon" href="/assets/icons/naturewxlab-icon.png">'
    expected_stylesheet = '<link rel="stylesheet" href="/assets/css/styles.css?v=20260722-3">'
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
    expected_footer = re.compile(
        r'<footer class="site-footer">\s*<div class="footer-inner">\s*'
        r'<div class="footer-compact">\s*<div class="footer-identity">\s*'
        r'<div class="footer-brand">NatureWxLab</div>\s*'
        r'<p>天気を味方に、自然と暮らす知恵や体験を形にします。</p>\s*</div>\s*'
        r'<div class="footer-meta">\s*<span>© 2026 NatureWxLab</span>\s*'
        r'<button class="footer-link-button" type="button" data-analytics-settings>'
        r'アクセス解析の設定</button>\s*</div>\s*</div>\s*</div>\s*</footer>',
        re.DOTALL,
    )
    for relative in HTML_FILES:
        text = relative.read_text(encoding="utf-8")
        page = relative.relative_to(SITE_ROOT)
        if len(expected_footer.findall(text)) != 1:
            errors.append(f"{page}: compact footer is missing or duplicated")
        if text.count("data-analytics-settings") != 1:
            errors.append(f"{page}: analytics settings trigger must appear exactly once")
        if any(obsolete_class in text for obsolete_class in ('class="footer-main"', 'class="footer-links"', 'class="footer-bottom"')):
            errors.append(f"{page}: obsolete expanded footer structure remains")
    home_text = (SITE_ROOT / "index.html").read_text(encoding="utf-8")
    about_text = (SITE_ROOT / "about/index.html").read_text(encoding="utf-8")
    vision_text = (SITE_ROOT / "vision/index.html").read_text(encoding="utf-8")
    policy_text = (SITE_ROOT / "policy/index.html").read_text(encoding="utf-8")
    styles_text = (SITE_ROOT / "assets/css/styles.css").read_text(encoding="utf-8")
    expected_editorial_photos = (
        (
            "index.html",
            home_text,
            '<section class="section white" aria-labelledby="approach-title">',
            '<figure class="editorial-photo home-garden-photo">\n'
            '          <img src="/assets/images/editorial-rose-garden-banner-20260716.jpg" width="2172" height="724" alt="日差しの中で色とりどりのバラが咲く庭園" loading="lazy" decoding="async">\n'
            "        </figure>",
        ),
        (
            "about/index.html",
            about_text,
            '<section class="section white about-section" aria-labelledby="about-origin-title">',
            '<figure class="editorial-photo about-biotope-photo">\n'
            '            <img src="/assets/images/editorial-medaka-pond-banner-20260716.jpg" width="2048" height="626" alt="緑に囲まれた池を泳ぐメダカ" loading="lazy" decoding="async">\n'
            "          </figure>",
        ),
        (
            "vision/index.html",
            vision_text,
            '<section class="section white">',
            '<figure class="editorial-photo vision-sky-photo">\n'
            '          <img src="/assets/images/editorial-summer-sky-banner-20260716.jpg" width="2048" height="626" alt="強い日差しの下に青空と白い雲が広がる風景" loading="lazy" decoding="async">\n'
            "        </figure>",
        ),
    )
    for page, page_text, section_start, markup in expected_editorial_photos:
        if page_text.count(markup) != 1:
            errors.append(f"{page}: editorial photo is missing or duplicated")
            continue
        start = page_text.find(section_start)
        end = page_text.find("</section>", start)
        position = page_text.find(markup)
        if start < 0 or end < 0 or not start < position < end:
            errors.append(f"{page}: editorial photo is outside its intended section")
    if sum(text.count('<figure class="editorial-photo ') for text in (home_text, about_text, vision_text, policy_text)) != 3:
        errors.append("editorial photos must appear exactly once on Home, About, and Vision")
    for relative in (SITE_ROOT / "tools/index.html", SITE_ROOT / "policy/index.html", SITE_ROOT / "404.html"):
        if "editorial-photo" in relative.read_text(encoding="utf-8"):
            errors.append(f"{relative.relative_to(SITE_ROOT)}: decorative editorial photos are not allowed on this page")
    if not re.search(
        r"\.editorial-photo\s+img\s*\{[^}]*\bdisplay:\s*block\s*;[^}]*"
        r"\bwidth:\s*100%\s*;[^}]*\bheight:\s*auto\s*;[^}]*"
        r"\bborder:\s*1px\s+solid\s+var\(--line\)\s*;[^}]*"
        r"\bborder-radius:\s*var\(--radius\)\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: uncropped responsive editorial photo rules are missing")
    editorial_photo_rule = re.search(r"\.editorial-photo\s+img\s*\{([^}]*)\}", styles_text, re.DOTALL)
    if editorial_photo_rule:
        declarations = editorial_photo_rule.group(1)
        height_match = re.search(r"\bheight:\s*([^;]+);", declarations)
        if (
            re.search(r"\b(?:object-fit|aspect-ratio|max-height)\s*:", declarations)
            or height_match is None
            or height_match.group(1).strip() != "auto"
        ):
            errors.append("styles.css: editorial photos must not be cropped or stretched")
    if re.search(r"\.editorial-photo\s+figcaption\s*\{", styles_text):
        errors.append("styles.css: obsolete editorial photo caption styling remains")
    if not re.search(
        r"\.editorial-photo\s*\{[^}]*\bwidth:\s*100%\s*;[^}]*"
        r"\bmax-width:\s*var\(--content\)\s*;[^}]*\bmargin:\s*34px\s+auto\s+0\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: content-width editorial banner layout is missing")
    editorial_container_rule = re.search(r"\.editorial-photo\s*\{([^}]*)\}", styles_text, re.DOTALL)
    if editorial_container_rule and re.search(
        r"\b(?:left|right|transform)\s*:|\bwidth\s*:[^;]*\b(?:vw|dvw)\b",
        editorial_container_rule.group(1),
    ):
        errors.append("styles.css: editorial banners must not break out to viewport width")
    for page, page_text in (("index.html", home_text), ("about/index.html", about_text), ("vision/index.html", vision_text)):
        if "AI生成イメージ" in page_text:
            errors.append(f"{page}: obsolete AI-generated image annotation remains")
    if any("background" in line and "editorial-" in line for line in styles_text.splitlines()):
        errors.append("styles.css: editorial photos must remain semantic images, not CSS backgrounds")
    if not re.search(
        r"\.site-footer\s*\{[^}]*\bpadding-block:\s*18px\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: compact footer padding is missing")
    if not re.search(
        r"\.footer-compact\s*\{[^}]*\bdisplay:\s*grid\s*;[^}]*"
        r"\bgrid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: compact footer layout is missing")
    if not re.search(
        r"\.footer-meta\s*\{[^}]*\bdisplay:\s*flex\s*;[^}]*\bjustify-content:\s*flex-end\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: compact footer metadata layout is missing")
    if not re.search(
        r"\.footer-brand\s*\{[^}]*\bline-height:\s*1\.3\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: compact footer brand line height is missing")
    if any(selector in styles_text for selector in (".footer-main", ".footer-links", ".footer-bottom")):
        errors.append("styles.css: obsolete expanded footer selectors remain")
    not_found_text = (SITE_ROOT / "404.html").read_text(encoding="utf-8")
    if not re.search(r'<body class="not-found-page">', not_found_text):
        errors.append("404.html: full-height page class is missing")
    if not re.search(
        r"\.not-found-page\s*\{[^}]*\bdisplay:\s*flex\s*;[^}]*\bmin-height:\s*100vh\s*;"
        r"[^}]*\bflex-direction:\s*column\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: full-height 404 page layout is missing")
    if not re.search(
        r"\.not-found-page\s+\.not-found\s*\{[^}]*\bmin-height:\s*0\s*;[^}]*\bflex:\s*1\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: flexible 404 content layout is missing")
    expected_home_meta = (
        '<title>NatureWxLab｜データと経験を、自然と暮らす知恵へ</title>',
        '<meta name="description" content="NatureWxLabは、現役気象予報士の知識と実体験をもとに、気象データを自然のある暮らしに役立つ情報、無料ツール、記事、動画へ変えて届ける小さな研究拠点です。">',
        '<meta property="og:title" content="NatureWxLab｜データと経験を、自然と暮らす知恵へ">',
        '<meta property="og:description" content="NatureWxLabは、現役気象予報士の知識と実体験をもとに、気象データを自然のある暮らしに役立つ情報、無料ツール、記事、動画へ変えて届ける小さな研究拠点です。">',
        '<meta name="twitter:title" content="NatureWxLab｜データと経験を、自然と暮らす知恵へ">',
        '<meta name="twitter:description" content="NatureWxLabは、現役気象予報士の知識と実体験をもとに、気象データを自然のある暮らしに役立つ情報、無料ツール、記事、動画へ変えて届ける小さな研究拠点です。">',
    )
    for markup in expected_home_meta:
        if home_text.count(markup) != 1:
            errors.append(f"index.html: required home metadata is missing or duplicated: {markup}")
    expected_home_copy = (
        '<p class="eyebrow">NATURE × WEATHER × DAILY LIFE</p>',
        '<h1>データと経験が交わり、<span>自然と暮らす知恵に変わる<span class="no-break">場所。</span></span></h1>',
        'NatureWxLabは、現役気象予報士の知識と実体験をもとに、<br>自然のある暮らしに役立つ情報を届ける、小さな研究拠点です。',
        '<div class="section-heading approach-section-heading">',
        '<h2 id="approach-title" class="home-section-title">天気を読み、自然で確かめ、知恵をつなぐ。</h2>',
        '<p class="approach-section-copy">気象データを読み解き、植物やメダカとの暮らしの中で確かめ、得られた発見をツール・記事・動画として共有する。NatureWxLabは、この循環を少しずつ育てています。</p>',
        '<h3>気象データを読み解く</h3>',
        '<h3>自然の中で確かめる</h3>',
        '<h3>知恵をひらき、つなげる</h3>',
        '<div class="section-heading tools-section-heading">',
        '<h2 id="tools-title" class="home-section-title"><span class="heading-line"><span class="tools-title-mobile-line">“天気を味方につけた</span><span class="tools-title-mobile-line">管理術”を、</span></span><span class="heading-line">誰でも使えるカタチに。</span></h2>',
        '<p>園芸・農業、メダカ飼育をはじめ、自然との暮らしの中で生まれる日々の管理判断を支える、4つの無料の意思決定支援ツールです。</p>',
        '<p>植物もメダカも、屋外で育つ生きものは、天気の影響を大きく受けます。<br>「いつ動くか」「どう動くか」の判断は、気温や雨、日照、風などによって大きく左右されます。<br>だからこそ、“天気を味方につけた管理術” を、誰でも使えるかたちにしました。<br>一つの正解を決めるのではなく、自分の地域や環境に合わせて考えるための「共通のものさし」を目指しています。</p>',
        '<p class="eyebrow">MEDIA &amp; UPDATES</p>',
        '<h2 id="content-title" class="home-section-title">媒体ごとに、いちばん伝わるかたちで。</h2>',
        '<p>公式HPを入口に、伝えたい内容に合わせて4つの媒体を使い分けています。</p>',
        '<h2 id="vision-title" class="home-vision-title"><span class="heading-line"><span class="vision-title-mobile-line">自然を楽しむ人が、</span><span class="vision-title-mobile-line">つながり、</span></span><span class="heading-line">学び合える場所へ。</span></h2>',
    )
    for markup in expected_home_copy:
        if home_text.count(markup) != 1:
            errors.append(f"index.html: required home copy is missing or duplicated: {markup}")
    for obsolete_copy in (
        "データを、使える手がかりへ",
        "天気と気候を調べる4つのツール",
        "自然の営みと結ぶ",
        "判断は利用者に残す",
        "園芸やメダカをはじめ、自然との暮らしの",
        "共通のものさしを目指しています。",
        "地点ごとに、過去30年の統計、現在の観測、2週間先までの見通しを見比べます。",
        "予報と観測、その差を地図で見ながら、天気・気温・雨・雪の分布を確認します。",
        "雨や天気のデータから、植物の乾燥・水やり・根腐れと、メダカ容器のあふれリスクを推定します。",
        "独自算出した全国陸域1km格子の気候平均と、気象庁の1か月・3か月予報による地域傾向を同じ場所で確認します。",
        "ほぼすべて天気が決めていると言っても過言ではありません。",
        "園芸・農業やメダカ飼育をはじめ、自然との暮らしのなかでのお世話の判断に関わる意思決定支援ツールです。",
        "植物もメダカも、屋外の生きものは、天気の影響を受けます。",
        "判断は、天気によって大きく左右されます。",
        "知恵をひらく。",
        "ARTICLES &amp; UPDATES",
        "記事・動画・日々の発信",
        "公式HPを入口に、詳しい解説や日々の更新はそれぞれの媒体で届けます。",
        "ツールの使い方や自然との向き合い方を、実演や検証を交えて紹介します。",
        "天気や自然、園芸、メダカ、公開ツールの背景を、文章で深く掘り下げます。",
        "日々の気象・自然情報と、記事やツールの更新を短くお知らせします。",
        "園芸、メダカ、自然観察の写真や短い動画を通して、日々の実践を紹介します。",
        ">YouTubeを見る</a>",
        ">noteを読む</a>",
        ">Xの投稿を見る</a>",
        ">Instagramを見る</a>",
    ):
        if obsolete_copy in home_text:
            errors.append(f"index.html: obsolete home copy remains: {obsolete_copy}")

    if not re.search(r"\.tools-section-heading\s*\{[^}]*\bmax-width:\s*none\s*;", styles_text, re.DOTALL):
        errors.append("styles.css: PUBLIC TOOLS heading width override is missing")
    if not re.search(
        r"\.approach-section-heading\s*,\s*\.tools-section-heading\s*\{[^}]*\bmax-width:\s*none\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: OUR APPROACH heading width override is missing")
    if not re.search(
        r'<section class="section white" aria-labelledby="approach-title">\s*<div class="section-inner">\s*'
        r'<div class="section-heading approach-section-heading">',
        home_text,
    ):
        errors.append("index.html: OUR APPROACH width class is not scoped to the approach section")
    if "@media (min-width: 1160px)" not in styles_text or not re.search(
        r"\.approach-section-copy\s*\{[^}]*\bfont-size:\s*0\.875rem\s*;[^}]*\bwhite-space:\s*nowrap\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: OUR APPROACH desktop one-line copy rule is missing")
    if not re.search(
        r'<section class="section" aria-labelledby="tools-title">\s*<div class="section-inner">\s*'
        r'<div class="section-heading tools-section-heading">',
        home_text,
    ):
        errors.append("index.html: PUBLIC TOOLS heading width class is not scoped to the tools section")
    responsive_heading_rules = (
        (
            r"#tools-title\s*\{[^}]*\btext-wrap:\s*wrap\s*;",
            "PUBLIC TOOLS natural wrapping rule",
        ),
        (
            r"\.home-vision-title\s*>\s*\.heading-line\s*\{[^}]*\bdisplay:\s*block\s*;",
            "Home VISION desktop semantic lines",
        ),
        (
            r"\.about-section\s+h2\.about-one-line-title\s*\{[^}]*"
            r"\bfont-size:\s*clamp\(1\.55rem,\s*3\.25vw,\s*2\.4rem\)\s*;[^}]*"
            r"\btext-wrap:\s*wrap\s*;",
            "About wide one-line title sizing",
        ),
        (
            r"@media\s*\(max-width:\s*560px\)(?:(?!@media).)*"
            r"#tools-title\s+\.tools-title-mobile-line\s*,\s*"
            r"\.home-vision-title\s+\.vision-title-mobile-line\s*\{[^}]*"
            r"\bdisplay:\s*block\s*;[^}]*\bwhite-space:\s*nowrap\s*;",
            "Home narrow semantic line layout",
        ),
        (
            r"@media\s*\(max-width:\s*719px\)(?:(?!@media).)*"
            r"\.about-one-line-title\s+\.about-title-mobile-line\s*\{[^}]*"
            r"\bdisplay:\s*block\s*;[^}]*\bwhite-space:\s*nowrap\s*;",
            "About narrow semantic line layout",
        ),
        (
            r"@media\s*\(max-width:\s*560px\)(?:(?!@media).)*"
            r"#tools-title\s*\{[^}]*"
            r"\bfont-size:\s*clamp\(1\.45rem,\s*6\.9vw,\s*1\.9rem\)\s*;",
            "PUBLIC TOOLS narrow title sizing",
        ),
        (
            r"@media\s*\(max-width:\s*560px\)(?:(?!@media).)*"
            r"\.vision-panel\s+h2\s*\{[^}]*"
            r"\bfont-size:\s*clamp\(1\.5rem,\s*6\.7vw,\s*1\.7rem\)\s*;",
            "Home VISION narrow title sizing",
        ),
        (
            r"@media\s*\(max-width:\s*560px\)(?:(?!@media).)*"
            r"\.about-section\s+h2\.about-one-line-title\s*\{[^}]*"
            r"\bfont-size:\s*clamp\(1\.45rem,\s*6\.5vw,\s*1\.6rem\)\s*;",
            "About narrow title sizing",
        ),
    )
    for pattern, label in responsive_heading_rules:
        if not re.search(pattern, styles_text, re.DOTALL):
            errors.append(f"styles.css: missing {label}")

    expected_tool_descriptions = {
        "気温リスクナビ": "地点ごとに、過去30年の統計、現在や過去の観測値、2週間先までの見通しを、グラフ形式で確認できます。",
        "天気分布予報プラス": "気象庁の予測と実況を地図で表現し、それらの平年差や前日差なども含めて、天気分布の過去・現在・未来の詳細を把握できます。",
        "うるおい管理ナビ": "雨の予報と観測データから、植物の水やりタイミング・根腐れリスクと、屋外メダカ容器のあふれリスクを推定できます。",
        "気候ものさしナビ": "独自算出した全国1kmメッシュの気候平均と、気象庁の最新の季節予報や観測データを組み合わせて、その土地の気候のすべてを把握できます。",
    }
    for relative in (Path("index.html"), Path("tools/index.html")):
        page_text = (SITE_ROOT / relative).read_text(encoding="utf-8")
        for tool_name, description in expected_tool_descriptions.items():
            description_pattern = re.compile(
                rf'<article class="tool-card">(?:(?!</article>).)*<h3>{re.escape(tool_name)}</h3>'
                rf'(?:(?!</article>).)*<p>{re.escape(description)}</p>(?:(?!</article>).)*</article>',
                re.DOTALL,
            )
            if not description_pattern.search(page_text):
                errors.append(f"{relative}: unexpected description for {tool_name}")

    tools_text = (SITE_ROOT / "tools/index.html").read_text(encoding="utf-8")
    expected_tool_previews = (
        (
            "気温リスクナビ",
            "/assets/images/tool-preview-temperature-risk-20260716.jpg",
            "東京都の過去30年の日最低気温グラフを表示した気温リスクナビの初期画面",
            expected_tool_descriptions["気温リスクナビ"],
        ),
        (
            "天気分布予報プラス",
            "/assets/images/tool-preview-weather-distribution-20260716.jpg",
            "全国の最高気温予報を地図に表示した天気分布予報プラスの初期画面",
            expected_tool_descriptions["天気分布予報プラス"],
        ),
        (
            "うるおい管理ナビ",
            "/assets/images/tool-preview-water-care-20260716.jpg",
            "全国のうるおい残量マップを表示したうるおい管理ナビの初期画面",
            expected_tool_descriptions["うるおい管理ナビ"],
        ),
        (
            "気候ものさしナビ",
            "/assets/images/tool-preview-climate-outlook-20260716.jpg",
            "全国の7月平均気温と季節予報を表示した気候ものさしナビの初期画面",
            expected_tool_descriptions["気候ものさしナビ"],
        ),
    )
    if tools_text.count('<figure class="tool-preview">') != 4:
        errors.append("tools/index.html: exactly four tool previews are required")
    if home_text.count('<figure class="tool-preview">') != 0:
        errors.append("index.html: tool previews must remain scoped to the public tools page")
    preview_positions: list[int] = []
    for tool_name, image_src, image_alt, description in expected_tool_previews:
        preview_pattern = re.compile(
            rf'<article class="tool-card">(?:(?!</article>).)*<h3>{re.escape(tool_name)}</h3>'
            rf'(?:(?!</article>).)*<figure class="tool-preview">\s*'
            rf'<img src="{re.escape(image_src)}" width="1425" height="891" '
            rf'alt="{re.escape(image_alt)}" loading="lazy" decoding="async">\s*'
            rf'<figcaption>初期表示例（2026年7月16日撮影）</figcaption>\s*</figure>\s*'
            rf'<p>{re.escape(description)}</p>(?:(?!</article>).)*</article>',
            re.DOTALL,
        )
        match = preview_pattern.search(tools_text)
        if match is None:
            errors.append(f"tools/index.html: preview structure or card association is invalid for {tool_name}")
        else:
            preview_positions.append(match.start())
    if preview_positions != sorted(preview_positions) or len(preview_positions) != 4:
        errors.append("tools/index.html: tool preview order must remain TOOL 01 through TOOL 04")
    if not re.search(r"\.tool-preview\s*\{[^}]*\bmargin:\s*16px\s+0\s+0\s*;", styles_text, re.DOTALL):
        errors.append("styles.css: tool preview spacing is missing")
    if not re.search(
        r"\.tool-preview\s+img\s*\{[^}]*\bdisplay:\s*block\s*;[^}]*"
        r"\bwidth:\s*100%\s*;[^}]*\bheight:\s*auto\s*;[^}]*"
        r"\bborder:\s*1px\s+solid\s+var\(--line\)\s*;[^}]*\bborder-radius:\s*6px\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: uncropped responsive tool preview rules are missing")
    if re.search(r"\.tool-preview\s+img\s*\{[^}]*\bobject-fit:\s*cover\s*;", styles_text, re.DOTALL):
        errors.append("styles.css: tool preview images must not be cropped")
    if not re.search(
        r"\.tool-preview\s+figcaption\s*\{[^}]*\bfont-size:\s*12px\s*;[^}]*\bline-height:\s*1\.6\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: tool preview caption styling is missing")
    expected_tools_intro = (
        '<p class="page-lede tools-page-lede">知りたい時間軸や目的に合わせて、4つのツールを使い分けられます。すべてブラウザから無料で利用できます。</p>',
        '<div class="section-heading tools-list-heading"><h2 id="tool-list-title">目的に合うツールを選ぶ</h2><p>各ツールは独立したページで公開しています。リンク先の出典、更新時刻、注意事項もあわせてご確認ください。</p></div>',
    )
    for markup in expected_tools_intro:
        if tools_text.count(markup) != 1:
            errors.append(f"tools/index.html: required full-width tools intro is missing or duplicated: {markup}")
    if not re.search(
        r"\.tools-page-lede\s*,\s*\.tools-list-heading\s*\{[^}]*\bmax-width:\s*none\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: tools page full-width intro rules are missing")
    if not re.search(
        r"@media\s*\(min-width:\s*1160px\)(?:(?!@media).)*"
        r"\.tools-page-lede\s*,\s*\.tools-list-heading\s*>\s*p\s*\{[^}]*\bwhite-space:\s*nowrap\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: tools page desktop one-line intro rules are missing")

    expected_tool_guide_intro = (
        '<p class="eyebrow">HOW TO CHOOSE</p>',
        '<h2 id="guide-title">「いつ」と「何を判断したいか」で、使い分ける。</h2>',
        '<p>4つのツールは、判断の材料として役立つ情報がそれぞれ異なります。'
        '一つの地点を深く見たいのか、周辺を含む地域を面で見たいのか。</p>',
        '<p>過去から未来までの流れを追いたいのか、今日・明日の変化を知りたいのか。'
        '「自分の地域や環境ならどうか」を判断するための根拠を提供します。</p>',
    )
    for markup in expected_tool_guide_intro:
        if tools_text.count(markup) != 1:
            errors.append(f"tools/index.html: required HOW TO CHOOSE intro is missing or duplicated: {markup}")
    if not re.search(r"\.tool-guide-intro\s*\{[^}]*\bmax-width:\s*none\s*;", styles_text, re.DOTALL):
        errors.append("styles.css: HOW TO CHOOSE intro must use the full section width")
    if tools_text.count('<div class="tool-guide-lede">') != 1 or tools_text.count('<div class="tool-guide-lede">\n            <p>') != 1:
        errors.append("tools/index.html: HOW TO CHOOSE lede must remain a single two-line group")
    if not re.search(
        r"@media\s*\(min-width:\s*1160px\)(?:(?!@media).)*"
        r"\.tool-guide-lede\s+p\s*\{[^}]*\bwhite-space:\s*nowrap\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: HOW TO CHOOSE desktop lede must keep each sentence pair on one line")
    expected_guide_views = (
        (
            "guide-view-card point-view",
            "POINT｜地点を深く見る",
            "特定の地点に絞り、過去・現在・未来を同じ軸で重ねて詳しく見ます。",
            "平年と今年の違いを確認し、植え付けや屋外管理などの作業時期を、具体的なスケジュールへ落とし込みやすくなります。",
        ),
        (
            "guide-view-card area-view",
            "AREA｜地域を面で見る",
            "知りたい地域とその周辺を一緒に見て、分布と時間変化を把握します。",
            "地域ごとの比較がしやすいだけでなく、雨域や高温域などの予測位置が少しずれた場合に、どうなりそうかも想定しやすくなります。",
        ),
    )
    for card_class, heading, first_paragraph, second_paragraph in expected_guide_views:
        view_pattern = re.compile(
            rf'<article class="{re.escape(card_class)}">\s*<h3>{re.escape(heading)}</h3>\s*'
            rf'<p>{re.escape(first_paragraph)}</p>\s*<p>{re.escape(second_paragraph)}</p>\s*</article>',
            re.DOTALL,
        )
        if view_pattern.search(tools_text) is None:
            errors.append(f"tools/index.html: HOW TO CHOOSE view card is invalid: {heading}")

    expected_guide_explanations = (
        (
            "point-tool",
            "POINT｜地点",
            "過去30年〜2週間先／年間の管理計画",
            "植え付けや屋外管理の時期を、地点ごとに考えたい",
            "気温リスクナビ",
            "特定地点の過去30年の統計、過去の任意年、今年ここまでの観測値、2週間気温予報を一つのグラフに重ねます。",
            "「平年ならいつ動くか」と「今年はどう進んでいるか」を見比べ、植え付け、屋外移行、遮光、取り込みなどの時期を考える材料にできます。",
        ),
        (
            "area-tool",
            "AREA｜地域",
            "過去1週間〜2日後",
            "今日から明日、どこで何が変わるかを広く見たい",
            "天気分布予報プラス",
            "気象庁が別々に提供している予報と実況を一つの地図にまとめ、天気・気温・雨・雪の分布と時間変化を確認できます。",
            "NatureWxLab独自の、予測値の前日差・平年差マップも使い、「今日こうだったから、明日はどう変わるか」を考えながら、予測域の位置が少しずれた場合の影響も想定しやすくします。",
        ),
        (
            "personal-tool",
            "AREA＋PERSONAL｜地域＋個別条件",
            "過去数日〜2週間先",
            "雨を軸に、水やりタイミングや根腐れリスクを考えたい",
            "うるおい管理ナビ β版",
            "どのくらい雨が降ったか、これからどのくらい降りそうかを、周辺の分布も含めて確認できます。",
            "地植え・鉢植え・畑、雨ざらしかどうか、土壌の種類など、自分の環境を設定することで、水やりのタイミング、長雨や多湿による根腐れ、屋外メダカ容器のあふれリスクを考えるための目安を示します。",
        ),
        (
            "climate-tool",
            "AREA｜地域",
            "過去30年〜3か月先",
            "その土地の「いつも」と、この先の傾向を地域差ごと見たい",
            "気候ものさしナビ β版",
            "全国陸域1kmメッシュの気候平均をベースに、ここまでの気候の経過と最新の季節予報を重ねて、地図上で気候の全貌を把握できます。",
            "自分の地域とその周辺、ほかの地域との違いを把握しながら、その土地の「いつもの気候」と「今年はどうなのか」を考える材料にできます。",
        ),
    )
    explanation_positions: list[int] = []
    for explanation_class, scope, period, purpose, tool_name, first_paragraph, second_paragraph in expected_guide_explanations:
        explanation_pattern = re.compile(
            rf'<article class="guide-explanation {re.escape(explanation_class)}">\s*'
            rf'<div class="decision-tool-meta"><span class="decision-scope">{re.escape(scope)}</span>'
            rf'<span class="decision-time">{re.escape(period)}</span></div>\s*'
            rf'<p class="decision-purpose">{re.escape(purpose)}</p>\s*<h3>{re.escape(tool_name)}</h3>\s*'
            rf'<p>{re.escape(first_paragraph)}</p>\s*<p>{re.escape(second_paragraph)}</p>\s*</article>',
            re.DOTALL,
        )
        match = explanation_pattern.search(tools_text)
        if match is None:
            errors.append(f"tools/index.html: HOW TO CHOOSE explanation is invalid: {tool_name}")
            explanation_positions.append(-1)
        else:
            explanation_positions.append(match.start())
    if any(position < 0 for position in explanation_positions) or explanation_positions != sorted(explanation_positions):
        errors.append("tools/index.html: HOW TO CHOOSE explanations must retain the specified order")

    guide_section_match = re.search(
        r'<section class="section white tool-guide-section"[^>]*>(.*?)</section>\s*</main>',
        tools_text,
        re.DOTALL,
    )
    if guide_section_match is None:
        errors.append("tools/index.html: HOW TO CHOOSE section is missing")
    else:
        guide_section_html = guide_section_match.group(1)
        if "data-track-destination" in guide_section_html or "https://nature-wx-lab.github.io/" in guide_section_html:
            errors.append("tools/index.html: HOW TO CHOOSE must not duplicate the four tool links")

    expected_tool_note = re.compile(
        r'<aside class="tool-guide-note" aria-labelledby="tools-note-title">\s*'
        r'<h2 id="tools-note-title">ご利用前に</h2>\s*'
        r'<div class="tool-guide-note-copy">\s*'
        r'<p>ツールによって、観測・予報・気候平均・独自推定を扱います。</p>\s*'
        r'<p>表示結果は、日々の判断を助けるための目安です。</p>\s*'
        r'<p>安全・健康・財産に関わる判断は、公的機関の最新情報と、実際の植物・土・水・容器の状態もあわせて確認してください。</p>\s*'
        r'</div>\s*<a class="guide-note-link" href="/policy/#tools">ツール利用上の注意を見る</a>\s*</aside>',
        re.DOTALL,
    )
    if len(expected_tool_note.findall(tools_text)) != 1:
        errors.append("tools/index.html: HOW TO CHOOSE usage note is missing or duplicated")
    for obsolete_copy in (
        "時間軸で使い分ける",
        "今と、この先を知りたい",
        "植物やメダカの管理に結びたい",
        "その場所の「いつも」を知りたい",
        ">ツール利用上の注意</a>",
        "「自分の地域や環境ならどうか」の判断をするため",
        "地域ごとの比較がしやすいことの他にも",
        "過去30年〜2週間先 or 年間計画",
        "NatureWxLab独自の予測の前日差・平年差マップ",
        "ここまで気候の経過",
    ):
        if obsolete_copy in tools_text:
            errors.append(f"tools/index.html: obsolete HOW TO CHOOSE copy remains: {obsolete_copy}")
    if not re.search(
        r"\.tool-guide-layout\s*\{[^}]*\bdisplay:\s*grid\s*;[^}]*\bgrid-template-columns:\s*"
        r"minmax\(0,\s*1\.72fr\)\s+minmax\(280px,\s*0\.68fr\)\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: HOW TO CHOOSE explanation and note columns are missing")
    if not re.search(
        r"\.guide-view-grid\s*\{[^}]*\bdisplay:\s*grid\s*;[^}]*"
        r"\bgrid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: HOW TO CHOOSE point and area comparison is missing")
    if not re.search(
        r"\.guide-explanation-list\s*\{[^}]*\bborder-top:\s*1px\s+solid\s+var\(--line\)\s*;",
        styles_text,
        re.DOTALL,
    ) or not re.search(
        r"\.guide-explanation\s*\{[^}]*\bborder-bottom:\s*1px\s+solid\s+var\(--line\)\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: HOW TO CHOOSE explanatory rows are missing")
    if not re.search(
        r"\.tool-guide-note\s*\{[^}]*\bposition:\s*sticky\s*;[^}]*\bdisplay:\s*grid\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: HOW TO CHOOSE side note layout is missing")
    if not re.search(
        r"@media\s*\(max-width:\s*1024px\)(?:(?!@media).)*"
        r"\.tool-guide-layout\s*\{[^}]*\bgrid-template-columns:\s*1fr\s*;",
        styles_text,
        re.DOTALL,
    ) or not re.search(
        r"@media\s*\(max-width:\s*1024px\)(?:(?!@media).)*"
        r"\.tool-guide-note\s*\{[^}]*\bposition:\s*static\s*;",
        styles_text,
        re.DOTALL,
    ) or not re.search(
        r"@media\s*\(max-width:\s*880px\)(?:(?!@media).)*"
        r"\.guide-view-grid\s*\{[^}]*\bgrid-template-columns:\s*1fr\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: HOW TO CHOOSE mobile one-column layout is missing")

    expected_about_meta = (
        '<title>NatureWxLabとは｜データと経験を、自然と暮らす知恵へ</title>',
        '<meta name="description" content="NatureWxLabは、現役気象予報士が個人で運営し、気象データと実体験、AIとの協働から、自然のある暮らしに役立つ情報、ツール、記事、動画を生み出す小さな研究拠点です。">',
        '<meta property="og:title" content="NatureWxLabとは｜データと経験を、自然と暮らす知恵へ">',
        '<meta property="og:description" content="NatureWxLabは、現役気象予報士が個人で運営し、気象データと実体験、AIとの協働から、自然のある暮らしに役立つ情報、ツール、記事、動画を生み出す小さな研究拠点です。">',
        '<meta name="twitter:title" content="NatureWxLabとは｜データと経験を、自然と暮らす知恵へ">',
        '<meta name="twitter:description" content="NatureWxLabは、現役気象予報士が個人で運営し、気象データと実体験、AIとの協働から、自然のある暮らしに役立つ情報、ツール、記事、動画を生み出す小さな研究拠点です。">',
    )
    for markup in expected_about_meta:
        if about_text.count(markup) != 1:
            errors.append(f"about/index.html: required metadata is missing or duplicated: {markup}")
    expected_about_copy = (
        '<p class="eyebrow">ABOUT NATUREWXLAB</p>',
        '<h1><span class="heading-line">一人の気象予報士から始まり、</span><span class="heading-line">知恵がつながる場所へ。</span></h1>',
        '<p>NatureWxLabは、気象情報の現場で働く現役気象予報士が、個人で運営している小さな研究拠点です。</p>',
        '<p>気象データ、家庭での園芸やメダカ飼育、親子での自然観察、そしてAIとの協働から生まれた発見を、自然のある暮らしに役立つ形で届けています。</p>',
        '<p>今は、一人でこの場所を育てています。けれど、目指しているのは、一人の答えを発信するだけの場所ではありません。</p>',
        '<p>地域も環境も異なる人たちの経験が行き交い、園芸、メダカ、天気、自然について互いに学び合える場所へ。NatureWxLabを、そんな研究拠点に育てていきます。</p>',
        '<p class="eyebrow">ORIGIN</p>',
        '<h2 id="about-origin-title" class="about-one-line-title"><span class="about-title-mobile-line">空を読む仕事と、自然を</span><span class="about-title-mobile-line">育てる暮らしの間から。</span></h2>',
        '<p class="eyebrow">THE LAB CYCLE</p>',
        '<h2 id="about-cycle-title" class="about-one-line-title"><span class="about-title-mobile-line">読む。試す。形にする。</span><span class="about-title-mobile-line">そして、また確かめる。</span></h2>',
        '<p class="eyebrow">SHARED LANGUAGE</p>',
        '<h2 id="about-language-title" class="about-one-line-title"><span class="about-title-mobile-line">ツールは、答えではなく、</span><span class="about-title-mobile-line">経験を持ち寄るための</span><span class="about-title-mobile-line">共通言語。</span></h2>',
        '<p class="eyebrow">HUMAN × AI</p>',
        '<h2 id="about-ai-title" class="about-one-line-title"><span class="about-title-mobile-line">一人で運営し、AIと</span><span class="about-title-mobile-line">協働してつくる研究所。</span></h2>',
        '<p class="eyebrow">OUR PRINCIPLES</p>',
        '<h2 id="about-principles-title" class="about-one-line-title"><span class="about-title-mobile-line">この場所を育てる</span><span class="about-title-mobile-line">ための、4つの約束。</span></h2>',
        '<p class="eyebrow">FROM NOW TO NEXT</p>',
        "ChatGPT、Codex、ClaudeなどのAIを協働相手として活用しています。",
        "人が責任を持って確認しながら形にします。",
        "さらに将来は、植物やメダカとの出会い、自然をテーマにした店やイベントなど、画面の外にも体験が広がる場所を目指します。",
    )
    for markup in expected_about_copy:
        if about_text.count(markup) != 1:
            errors.append(f"about/index.html: required copy is missing or duplicated: {markup}")
    expected_about_links = (
        '<a class="button" href="/tools/">4つの公開ツールを見る</a>',
        '<a class="button" href="/tools/">現在の公開ツールを見る</a>',
        '<a class="button secondary" href="/vision/">これからの構想を読む</a>',
        '<a class="button secondary" href="https://note.com/nature_wx_lab/m/mef6e32773d03" data-track-destination="note_profile">noteの詳しい自己紹介を読む</a>',
    )
    for markup in expected_about_links:
        if about_text.count(markup) != 1:
            errors.append(f"about/index.html: required CTA is missing or duplicated: {markup}")
    for obsolete_copy in (
        "天気と自然の距離を近づける",
        "大切にしていること",
        "発信者について",
        "活動の3つの柱",
    ):
        if obsolete_copy in about_text:
            errors.append(f"about/index.html: obsolete about copy remains: {obsolete_copy}")

    expected_wide_ledes = (
        (
            "about/index.html",
            about_text,
            '<div class="page-lede page-lede-wide page-intro">',
        ),
        (
            "vision/index.html",
            vision_text,
            '<p class="page-lede page-lede-wide">自然を楽しむ人が、つながり、学び合える場所へ。現在地を確かめながら、できることを一つずつ増やしていきます。</p>',
        ),
        (
            "policy/index.html",
            policy_text,
            '<p class="page-lede page-lede-wide">安心してご利用いただくために、データの扱い、アクセス解析、外部リンク、公開ツールの注意事項をお知らせします。</p>',
        ),
    )
    for page, page_text, markup in expected_wide_ledes:
        if page_text.count(markup) != 1:
            errors.append(f"{page}: full-width hero copy is missing or duplicated")

    expected_vision_meta = (
        '<meta name="description" content="NatureWxLabの現在地と、アバターで集うオンライン上の街、'
        'リアルな体験と交流を結び、自然を楽しむ人の交流を広げる将来構想を紹介します。">'
    )
    if vision_text.count(expected_vision_meta) != 1:
        errors.append("vision/index.html: current roadmap meta description is missing or duplicated")

    expected_vision_social_descriptions = (
        '<meta property="og:description" content="仮想と現実を結び、自然を楽しむ人がつながる場所へ。">',
        '<meta name="twitter:description" content="仮想と現実を結び、自然を楽しむ人がつながる場所へ。">',
    )
    for markup in expected_vision_social_descriptions:
        if vision_text.count(markup) != 1:
            errors.append("vision/index.html: current social description is missing or duplicated")

    expected_vision_fragments = (
        '<p class="eyebrow">NOW</p>\n          <h2>今は、地道な発信とツールづくりを積み重ねています</h2>',
        '<p>NatureWxLabの現在の中心は、天気と自然を結ぶ無料の公開ツール、noteの記事、Xでの日々の発信、'
        'Instagramの写真・短い動画、YouTubeでの実演です。</p>',
        '<p>まずは、役立つ情報を継続して届け、実際に試し、寄せられた声を受け取りながら、検証と改善を積み重ねます。'
        '必要な人が迷わず情報や判断材料へたどり着ける状態を、一つずつ整えていきます。</p>',
        '<p>公式HPは、それぞれの活動を一つにつなぐ総合入口です。ここですべてを完結させるのではなく、'
        '知りたいことに合う場所を選べる道しるべを目指します。</p>',
        '<div class="section-heading vision-future-heading"><p class="eyebrow">FUTURE</p>'
        '<h2 id="future-title">描いている将来への道のり</h2>'
        '<p>地道な情報発信から、頼られるブランドへ。<br>そこで生まれた信頼とつながりをリアルな体験へ広げ、'
        'やがて、住んでいる場所を越えて自然を楽しむ人が集う「街」へ——。</p>'
        '<p>NatureWxLabが、長い時間をかけて目指している成長の道のりです。</p></div>',
        '<div class="continuity-heading"><p class="eyebrow">CONTINUITY</p>'
        '<h2 id="continuity-title">この道のりを支える、<span>継続の仕組み</span></h2></div>',
        '<div class="continuity-copy"><p>寄せられた声や応援、活動から得られた支援・収益を、次の記事、検証、'
        'ツール、動画、イベント、交流の場づくりへ還元します。</p><p>無料の情報を大切な入口として守りながら、'
        '一つひとつの活動が次の活動を支え、無理なく成長していく仕組みを育てます。</p></div>',
        '<div><p class="eyebrow">PROMISE</p><h2 id="promise-title">大きな夢も、足元の検証から。</h2>'
        '<p>現在できていることと、これから実現したいことを分けて伝えます。安全性、わかりやすさ、'
        'データの誠実な扱いを優先し、急がず育てます。</p></div><div class="section-actions">'
        '<a class="button" href="/tools/">現在の公開ツールを見る</a></div>',
    )
    for fragment in expected_vision_fragments:
        if vision_text.count(fragment) != 1:
            errors.append("vision/index.html: required Vision roadmap copy is missing or duplicated")

    expected_roadmap_items = (
        '<li><span class="timeline-number">01</span><div class="timeline-body">'
        '<h3>地道な発信を積み重ねる</h3><p>まずは、今できることを一つずつ。</p>'
        '<p>天気、植物、園芸、農業、メダカなどをテーマに、毎日の暮らしや判断に役立つ記事・動画・無料ツールを地道に届けます。<br>'
        '実際に試し、寄せられた声を受け取り、検証と改善を重ねながら、NatureWxLabの土台を育てます。</p></div></li>',
        '<li><span class="timeline-number">02</span><div class="timeline-body">'
        '<h3>信頼され、頼られるブランドを築く</h3><p>発信と実績を積み重ね、</p>'
        '<p class="roadmap-quote"><strong>「植物やメダカ、天気のことなら、まずNatureWxLabを見てみよう」</strong></p>'
        '<p>と思い出してもらえる存在を目指します。</p><p>情報を探している人、育て方に迷っている人、'
        '天気を自然との暮らしに生かしたい人が、判断のよりどころにできるブランドを育てます。</p></div></li>',
        '<li><span class="timeline-number">03</span><div class="timeline-body">'
        '<h3>発信から、リアルな出会いと拠点づくりへ</h3><p>オンラインで生まれた信頼やつながりを、画面の外へ広げます。</p>'
        '<p>自然観察会や園芸・メダカのイベント、展示・販売会、ワークショップなどを自ら企画・主催し、'
        '人と自然、人と人が直接出会い、学びや体験を共有できる機会を少しずつ増やしていきます。</p>'
        '<p>さらに将来は、植物やメダカを実際に見て購入でき、育て方や楽しみ方について気軽に語り合える、'
        'NatureWxLabの店舗を持つことも目標です。単発のイベントだけでなく、自然が好きな人が日常的に集まり、'
        '交流できるリアルな拠点へと育てていきます。</p></div></li>',
        '<li class="timeline-goal"><span class="timeline-number">04</span><div class="timeline-body">'
        '<h3>リアルとオンラインを結ぶ、「自然の街」へ</h3>'
        '<p>リアルな場で生まれたつながりを、住んでいる場所や生活環境にかかわらず、さらに多くの人へ広げます。'
        '園芸、農業、メダカ飼育、天気、自然観察など、<strong>「自然」への関心を共通点に、'
        '全国や世界の人が交流できるオンライン上の街</strong>を構想しています。</p>'
        '<p>そこでは、自分の分身となるアバターを通じてリアルタイムにつながり、育て方や経験を教え合い、情報を共有する。'
        '大切に育てた植物やメダカを紹介し合い、適切な仕組みのもとで交換や販売もできる——そんな交流の形を思い描いています。</p>'
        '<p>オンラインで生まれたつながりが、リアルなイベントや店舗へ広がり、そこで得た体験や知恵が再びオンラインへ持ち寄られる。'
        '人や経験がリアルとオンラインを行き来することで、自然を楽しむ人たちが自由につながり、学び合い、'
        '今よりもっと自然を楽しめる世界の実現を目指します。</p></div></li>',
    )
    roadmap_start = vision_text.find('<ol class="timeline vision-roadmap">')
    roadmap_end = vision_text.find("</ol>", roadmap_start)
    if roadmap_start < 0 or roadmap_end < 0:
        errors.append("vision/index.html: numbered Vision roadmap is missing")
        roadmap_text = ""
    else:
        roadmap_text = vision_text[roadmap_start : roadmap_end + len("</ol>")]
        if roadmap_text.count("<li") != 4:
            errors.append("vision/index.html: Vision roadmap must contain exactly four stages")
        if re.findall(r'<span class="timeline-number">(\d{2})</span>', roadmap_text) != [
            "01",
            "02",
            "03",
            "04",
        ]:
            errors.append("vision/index.html: Vision roadmap numbers must be visible and ordered 01-04")
        if roadmap_text.count('class="timeline-goal"') != 1:
            errors.append("vision/index.html: only the final Vision roadmap stage may be highlighted")
        item_positions = [roadmap_text.find(item) for item in expected_roadmap_items]
        if any(position < 0 for position in item_positions) or item_positions != sorted(item_positions):
            errors.append("vision/index.html: Vision roadmap stage copy or ordering changed")

    continuity_markup = '<section class="section continuity-section" aria-labelledby="continuity-title">'
    continuity_start = vision_text.find(continuity_markup)
    continuity_end = vision_text.find("</section>", continuity_start)
    promise_start = vision_text.find(
        '<section class="section white" aria-labelledby="promise-title">'
    )
    if not (roadmap_end >= 0 and roadmap_end < continuity_start < continuity_end < promise_start):
        errors.append("vision/index.html: CONTINUITY must remain independent between FUTURE and PROMISE")
    elif any(
        marker in vision_text[continuity_start:continuity_end]
        for marker in ("<ol", "timeline-number", 'class="timeline', ">05<")
    ):
        errors.append("vision/index.html: CONTINUITY must not become a fifth roadmap stage")

    for forbidden_copy in (
        "今は、情報の拠点を育てています",
        "描いている将来構想",
        "以下は実現済みのサービスではありません",
        "活動が次の活動を支える循環をつくる",
        "01は現在取り組んでいる段階",
        "02〜04は長期構想",
    ):
        if forbidden_copy in vision_text:
            errors.append(f"vision/index.html: rejected or obsolete Vision copy remains: {forbidden_copy}")
    if vision_text.count("自然を楽しむ人") < 2:
        errors.append("vision/index.html: inclusive long-term audience wording is missing")
    if vision_text.count('<div class="section-inner two-column vision-now-layout">') != 1:
        errors.append("vision/index.html: dedicated NOW alignment layout is missing or duplicated")

    vision_css_contracts = (
        (
            r"\.vision-roadmap\s*\{[^}]*\bmax-width:\s*none\s*;[^}]*"
            r"\bmargin-left:\s*20px\s*;",
            "full-width roadmap and line alignment",
        ),
        (
            r"\.vision-future-heading\s*\{[^}]*\bmax-width:\s*none\s*;",
            "full-width FUTURE heading",
        ),
        (
            r"\.vision-roadmap\s+li::before\s*\{[^}]*\bdisplay:\s*none\s*;",
            "single numbered roadmap marker",
        ),
        (
            r"\.vision-roadmap\s+\.timeline-number\s*\{[^}]*\bposition:\s*absolute\s*;[^}]*"
            r"\bleft:\s*-21px\s*;[^}]*\bdisplay:\s*inline-flex\s*;[^}]*"
            r"\balign-items:\s*center\s*;[^}]*\bjustify-content:\s*center\s*;",
            "visible centered roadmap numbers",
        ),
        (
            r"\.vision-roadmap\s+\.timeline-goal\s+\.timeline-body\s*\{[^}]*"
            r"\bborder:\s*1px\s+solid\s+rgba\(36,\s*114,\s*93,\s*0\.26\)\s*;[^}]*"
            r"\bbackground:\s*linear-gradient\(",
            "restrained final-stage emphasis",
        ),
        (
            r"\.continuity-section\s*\{[^}]*\bpadding-block:\s*0\s+72px\s*;[^}]*"
            r"\bbackground:\s*var\(--mist\)\s*;",
            "integrated continuity section",
        ),
        (
            r"\.continuity-layout\s*\{[^}]*\bmax-width:\s*none\s*;[^}]*"
            r"\bborder-left:\s*4px\s+solid\s+var\(--leaf\)\s*;[^}]*"
            r"\bbackground:\s*linear-gradient\([^}]*\bgrid-template-columns:\s*1fr\s*;",
            "full-width timeline-aligned continuity panel",
        ),
        (
            r"\.continuity-heading\s+h2\s+span\s*\{[^}]*\bwhite-space:\s*nowrap\s*;",
            "natural continuity heading wrap",
        ),
        (
            r"@media\s*\(min-width:\s*1160px\)(?:(?!@media).)*\.continuity-copy\s+p:last-child\s*\{"
            r"[^}]*\bwhite-space:\s*nowrap\s*;",
            "single-line desktop continuity closing copy",
        ),
        (
            r"\.vision-now-layout\s+\.content-block\s*\{[^}]*\bmargin-top:\s*-14px\s*;",
            "desktop NOW visual alignment",
        ),
        (
            r"\.vision-now-layout\s+\.content-block\s+h2\s*\{[^}]*\bwhite-space:\s*nowrap\s*;",
            "single-line desktop NOW title",
        ),
        (
            r"@media\s*\(max-width:\s*880px\)(?:(?!@media).)*"
            r"\.vision-now-layout\s+\.content-block\s*\{[^}]*\bmargin-top:\s*0\s*;",
            "mobile NOW alignment reset",
        ),
        (
            r"@media\s*\(max-width:\s*880px\)(?:(?!@media).)*"
            r"\.vision-now-layout\s+\.content-block\s+h2\s*\{[^}]*\bwhite-space:\s*normal\s*;",
            "mobile NOW title wrap reset",
        ),
        (
            r"@media\s*\(max-width:\s*560px\)(?:(?!@media).)*"
            r"\.vision-roadmap\s+li\s*\{[^}]*\bpadding:\s*0\s+0\s+32px\s+46px\s*;"
            r"(?:(?!@media).)*\.vision-roadmap\s+\.timeline-number\s*\{[^}]*"
            r"\bleft:\s*-18px\s*;",
            "mobile roadmap width",
        ),
    )
    for pattern, label in vision_css_contracts:
        if not re.search(pattern, styles_text, re.DOTALL):
            errors.append(f"styles.css: missing {label}")
    goal_rule = re.search(
        r"\.vision-roadmap\s+\.timeline-goal\s+\.timeline-body\s*\{([^}]*)\}",
        styles_text,
        re.DOTALL,
    )
    if goal_rule is None or "box-shadow" in goal_rule.group(1):
        errors.append("styles.css: final Vision stage must use restrained emphasis without shadow")
    if not re.search(
        r"@media\s*\(max-width:\s*880px\)(?:(?!@media).)*\.continuity-layout,"
        r"(?:(?!@media).)*\bgrid-template-columns:\s*1fr\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: mobile continuity layout must use one column")

    about_intro = re.search(
        r'<div class="page-lede page-lede-wide page-intro">(.*?)</div>',
        about_text,
        re.DOTALL,
    )
    if about_intro is None:
        errors.append("about/index.html: About introduction is missing")
    elif re.search(r"<br\s*/?>", about_intro.group(1), re.IGNORECASE):
        errors.append("about/index.html: About introduction must wrap naturally without br")

    expected_origin_closing = (
        '<p class="about-origin-closing">ならば、気象データと実体験の両方を使って考えられる場所を作ろう。'
        'NatureWxLabは、そこから始まりました。</p>'
    )
    if about_text.count(expected_origin_closing) != 1:
        errors.append("about/index.html: ORIGIN closing sentences must share one paragraph")
    if (
        "<p>ならば、気象データと実体験の両方を使って考えられる場所を作ろう。</p>" in about_text
        or "<p>NatureWxLabは、そこから始まりました。</p>" in about_text
    ):
        errors.append("about/index.html: obsolete split ORIGIN closing paragraphs remain")

    required_wide_rules = (
        (
            r"\.page-lede\.page-lede-wide\s*\{[^}]*\bmax-width:\s*none\s*;",
            "three-page hero copy width override",
        ),
        (
            r"\.about-heading\s*,\s*\.about-prose\s*\{[^}]*\bmax-width:\s*none\s*;",
            "About section copy width override",
        ),
    )
    for pattern, label in required_wide_rules:
        if not re.search(pattern, styles_text, re.DOTALL):
            errors.append(f"styles.css: missing {label}")

    natural_wrap_selectors = {
        ".page-lede.page-lede-wide",
        ".page-intro",
        ".about-heading",
        ".about-prose",
        ".about-section h2 .heading-line",
    }
    for selector_text, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", styles_text):
        selectors = {item.strip() for item in selector_text.split(",")}
        if selectors & natural_wrap_selectors and re.search(
            r"\bwhite-space:\s*nowrap\b", declarations
        ):
            errors.append("styles.css: About/Vision/Policy copy must wrap naturally")
    if not re.search(
        r"\.about-origin-closing\s*\{[^}]*\bwhite-space:\s*nowrap\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: desktop ORIGIN closing line rule is missing")
    if not re.search(
        r"@media\s*\(max-width:\s*880px\)\s*\{[^{}]*"
        r"\.about-origin-closing\s*\{[^}]*\bwhite-space:\s*normal\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: mobile ORIGIN closing wrap rule is missing")

    expected_hero = '<img src="/assets/images/hero-family-garden-medaka-v2.png" width="1254" height="1254" alt="" decoding="async" fetchpriority="high">'
    if home_text.count(expected_hero) != 1:
        errors.append("index.html: supplied family garden hero image is missing or duplicated")
    if "hero-weather-nature-v2" in home_text or "hero-family-garden-medaka.jpg" in home_text:
        errors.append("index.html: obsolete hero image reference remains")
    expected_instagram = '<a href="https://www.instagram.com/nature_wx_lab/" data-track-destination="media_instagram">Instagramで写真・動画を見る</a>'
    if home_text.count(expected_instagram) != 1:
        errors.append("index.html: official Instagram link is missing or duplicated")
    expected_social_icons = {
        "note": '<span class="service-mark note" aria-hidden="true"><img src="/assets/icons/social-note.svg" width="42" height="42" alt=""></span>',
        "X": '<span class="service-mark x" aria-hidden="true"><img src="/assets/icons/social-x.svg" width="24" height="24" alt=""></span>',
        "Instagram": '<span class="service-mark instagram" aria-hidden="true"><img src="/assets/icons/social-instagram.svg" width="24" height="24" alt=""></span>',
        "YouTube": '<span class="service-mark youtube" aria-hidden="true"><img src="/assets/icons/social-youtube.svg" width="24" height="24" alt=""></span>',
    }
    for service, markup in expected_social_icons.items():
        if home_text.count(markup) != 1:
            errors.append(f"index.html: official {service} mark is missing or duplicated")
    expected_media_cards = (
        (
            "YouTube",
            expected_social_icons["YouTube"],
            "実演・ハウツー",
            "植物やメダカのお世話、イベント参加報告など、動画だからこそ伝わる動きや変化、魅力などを、実演・比較・観察などを交えて紹介します。",
            "https://www.youtube.com/@nature_wx_lab",
            "media_youtube",
            "YouTubeで動画を見る",
        ),
        (
            "note",
            expected_social_icons["note"],
            "深掘り・解説",
            "Xなどの短い投稿では伝えきれない、天気・園芸・メダカ・公開ツールの背景や仕組み、判断の根拠まで文章でじっくり掘り下げます。",
            "https://note.com/nature_wx_lab",
            "media_note",
            "noteで詳しく読む",
        ),
        (
            "X",
            expected_social_icons["X"],
            "速報・日々の更新",
            "いま伝えるべき、天気を味方につけたお世話のコツや各地のお花の見頃や各種イベント情報などを短くタイムリーに届けます。",
            "https://x.com/nature_wx_lab",
            "media_x",
            "Xで最新情報を見る",
        ),
        (
            "Instagram",
            expected_social_icons["Instagram"],
            "写真・短い動画",
            "私の庭で咲いた花や育てているメダカを、写真と短い動画で紹介します。販売するメダカは、泳ぎ方や体色を購入前に確認できる動画も掲載します。",
            "https://www.instagram.com/nature_wx_lab/",
            "media_instagram",
            "Instagramで写真・動画を見る",
        ),
    )
    media_positions: list[int] = []
    for service, icon_markup, role, description, link_url, destination, link_label in expected_media_cards:
        card_pattern = re.compile(
            rf'<article class="link-card">\s*{re.escape(icon_markup)}\s*<h3>{re.escape(service)}</h3>'
            rf'\s*<span class="media-role">{re.escape(role)}</span>\s*<p>{re.escape(description)}</p>\s*'
            rf'<a href="{re.escape(link_url)}" '
            rf'data-track-destination="{destination}">{re.escape(link_label)}</a>\s*</article>',
            re.DOTALL,
        )
        card_match = card_pattern.search(home_text)
        if card_match is None:
            errors.append(f"index.html: {service} mark, name, and link must share one card")
            media_positions.append(-1)
        else:
            media_positions.append(card_match.start())
    if any(position < 0 for position in media_positions) or media_positions != sorted(media_positions):
        errors.append("index.html: media cards must be ordered YouTube, note, X, Instagram")
    obsolete_social_icons = (
        '<span class="service-mark note" aria-hidden="true">note</span>',
        '<span class="service-mark" aria-hidden="true">X</span>',
        '<span class="service-mark instagram" aria-hidden="true">IG</span>',
        '<span class="service-mark youtube" aria-hidden="true">▶</span>',
    )
    if any(markup in home_text for markup in obsolete_social_icons):
        errors.append("index.html: obsolete text-only social mark remains")
    if '<div class="link-grid media-grid">' not in home_text:
        errors.append("index.html: media cards are not scoped to the responsive media grid")
    if not re.search(
        r"\.media-grid\s*\{[^}]*\bgrid-auto-rows:\s*1fr\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: equal-height media grid rows are missing")
    if not re.search(
        r"\.media-role\s*\{[^}]*\bdisplay:\s*inline-flex\s*;[^}]*\bborder-radius:\s*999px\s*;"
        r"[^}]*\bfont-weight:\s*800\s*;[^}]*\bwhite-space:\s*nowrap\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: media role pill styling is missing")
    if not re.search(
        r"\.service-mark\.note\s*\{[^}]*\bborder-color:\s*#e5e5e5\s*;"
        r"[^}]*\bbackground:\s*#fff\s*;[^}]*\}"
        r"\s*\.service-mark\.note\s+img\s*\{[^}]*\bwidth:\s*40px\s*;"
        r"[^}]*\bheight:\s*40px\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: note icon rounded frame styling is missing")
    if not re.search(
        r"@media\s*\(max-width:\s*1099px\)\s*\{\s*\.media-grid\s*\{[^}]*"
        r"grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: media grid tablet two-column rule is missing")
    if not re.search(
        r"\.link-card\s+a\s*\{[^}]*\bmargin-top:\s*auto\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: link-card CTA bottom alignment rule is missing")
    expected_mercari_icon = '<span class="service-mark mercari" aria-hidden="true"><img src="/assets/icons/service-mercari.png" width="42" height="42" alt=""></span>'
    if home_text.count(expected_mercari_icon) != 1:
        errors.append("index.html: official Mercari service icon is missing or duplicated")
    if '<span class="service-mark" aria-hidden="true">M</span>' in home_text:
        errors.append("index.html: obsolete text-only Mercari mark remains")
    expected_auction_icon = '<span class="service-mark auction" aria-hidden="true"><span class="auction-wordmark">ヤフオク!</span></span>'
    expected_auction_name = '<h3>Yahoo!オークション</h3>'
    expected_auction_description = '<p>メダカの出品情報をご覧いただけます。</p>'
    expected_auction_link = '>Yahoo!オークションの出品を見る</a>'
    if home_text.count(expected_auction_icon) != 1:
        errors.append("index.html: custom Yahoo! Auctions wordmark is missing or duplicated")
    if (
        home_text.count(expected_auction_name) != 1
        or home_text.count(expected_auction_description) != 1
        or home_text.count(expected_auction_link) != 1
    ):
        errors.append("index.html: current Yahoo! Auctions service name is missing or duplicated")
    if '<img src="/assets/icons/service-auction.svg"' in home_text:
        errors.append("index.html: obsolete neutral auction gavel remains")
    if "メダカや植物などの出品情報をご覧いただけます。" in home_text:
        errors.append("index.html: obsolete Yahoo! Auctions description remains")
    if not re.search(
        r"\.service-mark\.auction\s*\{[^}]*\bbackground:\s*#ffdc48\s*;[^}]*\bcolor:\s*#202020\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: yellow and black Yahoo! Auctions badge styling is missing")
    if not re.search(
        r"\.auction-wordmark\s*\{[^}]*-webkit-text-stroke:\s*0\.3px\s+currentColor\s*;"
        r"[^}]*transform:\s*translateX\(-0\.8px\)\s+skew\(-7deg\)\s*;",
        styles_text,
        re.DOTALL,
    ):
        errors.append("styles.css: Yahoo! Auctions wordmark centering and weight correction is missing")
    expected_sales_cards = (
        (expected_mercari_icon, "メルカリ", "植物などの出品情報をご覧いただけます。", "https://jp.mercari.com/user/profile/474428763", "sales_mercari", "メルカリの出品を見る"),
        (expected_auction_icon, "Yahoo!オークション", "メダカの出品情報をご覧いただけます。", "https://auctions.yahoo.co.jp/seller/2Nn3kZv4J22cbfTSoVYSVRRp2M6Ao?user_type=c", "sales_yahoo_auctions", "Yahoo!オークションの出品を見る"),
    )
    for icon_markup, service, description, link_url, destination, link_label in expected_sales_cards:
        card_pattern = re.compile(
            rf'<article class="link-card">\s*{re.escape(icon_markup)}\s*<h3>{re.escape(service)}</h3>'
            rf'\s*<p>{re.escape(description)}</p>\s*<a href="{re.escape(link_url)}" '
            rf'data-track-destination="{destination}">{re.escape(link_label)}</a>\s*</article>',
            re.DOTALL,
        )
        if card_pattern.search(home_text) is None:
            errors.append(f"index.html: {service} mark, name, and link must share one card")
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

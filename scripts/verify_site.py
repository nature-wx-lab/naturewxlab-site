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
    "assets/icons/service-auction.svg",
    "assets/icons/service-mercari.png",
    "assets/icons/social-instagram.svg",
    "assets/icons/social-note.svg",
    "assets/icons/social-x.svg",
    "assets/icons/social-youtube.svg",
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
        "assets/icons/service-auction.svg": "478d6b3dfd463b6d20e231196282f21dcf2c713c3ccfec46e37620b194d673d6",
        "assets/icons/service-mercari.png": "e10e59e32930d1ef264d9aca191f1cee9e868a2abc30188b97b14a7a89575ab7",
        "assets/icons/social-instagram.svg": "103ab72561b73436703a2129eaf77bb9357b008b8f97a344ba0389a3990c9d41",
        "assets/icons/social-note.svg": "aae7e7cf0b0e9af6ba7fad113d38ade534835b5235c5c0ba9ae74814c83a34c8",
        "assets/icons/social-x.svg": "30bd48f0082d513928f4a04e6df09a22bcfb045ca9a8c52ecbff721fb4017012",
        "assets/icons/social-youtube.svg": "0410b0414d8f8c5f413970592e0a11edb3e3293f0e8efdd20c7d74d16067dd8b",
        "assets/images/hero-family-garden-medaka-v2.png": "8e812c8d3e02afd15fa60fffcd65195940a1623c998e0ebc1a72842ae5462bc1",
        "assets/images/og-image.jpg": "9198c25cae29d01cdfaab1941c5095bad66627abd17003bedf6c04294e9ad35b",
    }
    for relative, expected_sha256 in expected_asset_sha256.items():
        asset = SITE_ROOT / relative
        if asset.is_file() and hashlib.sha256(asset.read_bytes()).hexdigest() != expected_sha256:
            errors.append(f"{relative}: pinned asset bytes changed unexpectedly")

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
    expected_stylesheet = '<link rel="stylesheet" href="/assets/css/styles.css?v=20260715-1">'
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
    about_text = (SITE_ROOT / "about/index.html").read_text(encoding="utf-8")
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
        '<h1>データと経験が交わり、<span>自然と暮らす知恵に変わる場所。</span></h1>',
        'NatureWxLabは、現役気象予報士の知識と実体験をもとに、<br>自然のある暮らしに役立つ情報を届ける、小さな研究拠点です。',
        '<h2 id="approach-title" class="home-section-title"><span class="heading-line">天気を読み、自然で確かめ、</span><span class="heading-line">知恵をひらく。</span></h2>',
        '<h3>気象データを読み解く</h3>',
        '<h3>自然の中で確かめる</h3>',
        '<h3>知恵をひらき、つなげる</h3>',
        '<h2 id="tools-title" class="home-section-title"><span class="heading-line">“天気を味方につけた管理術”を、</span><span class="heading-line">誰でも使えるカタチに。</span></h2>',
        '共通のものさしを目指しています。',
    )
    for markup in expected_home_copy:
        if home_text.count(markup) != 1:
            errors.append(f"index.html: required home copy is missing or duplicated: {markup}")
    for obsolete_copy in (
        "データを、使える手がかりへ",
        "天気と気候を調べる4つのツール",
        "自然の営みと結ぶ",
        "判断は利用者に残す",
    ):
        if obsolete_copy in home_text:
            errors.append(f"index.html: obsolete home copy remains: {obsolete_copy}")

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
        "個人で運営している小さな研究拠点です。",
        '<p class="eyebrow">ORIGIN</p>',
        '<p class="eyebrow">THE LAB CYCLE</p>',
        '<p class="eyebrow">SHARED LANGUAGE</p>',
        '<p class="eyebrow">HUMAN × AI</p>',
        '<p class="eyebrow">OUR PRINCIPLES</p>',
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

    expected_hero = '<img src="/assets/images/hero-family-garden-medaka-v2.png" width="1254" height="1254" alt="" decoding="async" fetchpriority="high">'
    if home_text.count(expected_hero) != 1:
        errors.append("index.html: supplied family garden hero image is missing or duplicated")
    if "hero-weather-nature-v2" in home_text or "hero-family-garden-medaka.jpg" in home_text:
        errors.append("index.html: obsolete hero image reference remains")
    expected_instagram = '<a href="https://www.instagram.com/nature_wx_lab/" data-track-destination="media_instagram">Instagramを見る</a>'
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
        ("YouTube", expected_social_icons["YouTube"], "https://www.youtube.com/@nature_wx_lab", "media_youtube", "YouTubeを見る"),
        ("note", expected_social_icons["note"], "https://note.com/nature_wx_lab", "media_note", "noteを読む"),
        ("X", expected_social_icons["X"], "https://x.com/nature_wx_lab", "media_x", "Xの投稿を見る"),
        ("Instagram", expected_social_icons["Instagram"], "https://www.instagram.com/nature_wx_lab/", "media_instagram", "Instagramを見る"),
    )
    media_positions: list[int] = []
    for service, icon_markup, link_url, destination, link_label in expected_media_cards:
        card_pattern = re.compile(
            rf'<article class="link-card">\s*{re.escape(icon_markup)}\s*<h3>{re.escape(service)}</h3>'
            rf'(?:(?!</article>).)*<a href="{re.escape(link_url)}" '
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
    expected_mercari_icon = '<span class="service-mark mercari" aria-hidden="true"><img src="/assets/icons/service-mercari.png" width="42" height="42" alt=""></span>'
    if home_text.count(expected_mercari_icon) != 1:
        errors.append("index.html: official Mercari service icon is missing or duplicated")
    if '<span class="service-mark" aria-hidden="true">M</span>' in home_text:
        errors.append("index.html: obsolete text-only Mercari mark remains")
    expected_auction_icon = '<span class="service-mark auction" aria-hidden="true"><img src="/assets/icons/service-auction.svg" width="24" height="24" alt=""></span>'
    expected_auction_name = '<h3>Yahoo!オークション</h3>'
    expected_auction_link = '>Yahoo!オークションの出品を見る</a>'
    if home_text.count(expected_auction_icon) != 1:
        errors.append("index.html: neutral auction mark is missing or duplicated")
    if home_text.count(expected_auction_name) != 1 or home_text.count(expected_auction_link) != 1:
        errors.append("index.html: current Yahoo! Auctions service name is missing or duplicated")
    if '<span class="service-mark" aria-hidden="true">Y!</span>' in home_text:
        errors.append("index.html: unauthorized text-only Yahoo brand mark remains")
    expected_sales_cards = (
        (expected_mercari_icon, "メルカリ", "https://jp.mercari.com/user/profile/474428763", "sales_mercari", "メルカリの出品を見る"),
        (expected_auction_icon, "Yahoo!オークション", "https://auctions.yahoo.co.jp/seller/2Nn3kZv4J22cbfTSoVYSVRRp2M6Ao?user_type=c", "sales_yahoo_auctions", "Yahoo!オークションの出品を見る"),
    )
    for icon_markup, service, link_url, destination, link_label in expected_sales_cards:
        card_pattern = re.compile(
            rf'<article class="link-card">\s*{re.escape(icon_markup)}\s*<h3>{re.escape(service)}</h3>'
            rf'(?:(?!</article>).)*<a href="{re.escape(link_url)}" '
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

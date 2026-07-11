"""Per-platform metadata scrapers extracted from social-listening-api."""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import logging
import os
import re
import socket
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx

from social_crawler.config import SOCIAL_PLATFORMS, TELEGRAM_DOMAINS, VIETNAM_PLATFORMS

logger = logging.getLogger(__name__)

_FETCH_TIMEOUT_SECONDS = float(os.environ.get("SOCIAL_SCRAPER_FETCH_TIMEOUT_SECONDS", "20"))
_BROWSER_TIMEOUT_SECONDS = float(os.environ.get("SOCIAL_SCRAPER_BROWSER_TIMEOUT_SECONDS", "35"))
_BROWSER_WAIT_SECONDS = float(os.environ.get("SOCIAL_SCRAPER_BROWSER_WAIT_SECONDS", "6"))
_BROWSER_ENABLED = os.environ.get("SOCIAL_SCRAPER_BROWSER_ENABLED", "false").lower() == "true"
_BROWSER_BINARY = os.environ.get("SOCIAL_SCRAPER_CHROME_BINARY", "")
_BROWSER_VERSION_MAIN = os.environ.get("SOCIAL_SCRAPER_CHROME_VERSION_MAIN", "")
_BROWSER_SEMAPHORE = asyncio.Semaphore(int(os.environ.get("SOCIAL_SCRAPER_BROWSER_CONCURRENCY", "1")))

_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/atom+xml;q=0.8,*/*;q=0.7",
    "accept-language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "no-cache",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
}

_FACEBOOK_METADATA_HEADERS = {
    **_HEADERS,
    # Facebook exposes useful Open Graph metadata to link preview crawlers for
    # many public page posts even when the browser-facing route is noisy.
    "user-agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
}

_TIKTOK_OEMBED_URL = "https://www.tiktok.com/oembed"
_MAX_REDIRECTS = 5
_ALLOWED_DOMAINS = tuple(
    dict.fromkeys(
        [
            *(domain for domains in SOCIAL_PLATFORMS.values() for domain in domains),
            *TELEGRAM_DOMAINS,
            *(domain for domains in VIETNAM_PLATFORMS.values() for domain in domains),
            "youtu.be",
        ]
    )
)


@dataclass
class ScrapedMention:
    title: str = ""
    description: str = ""
    source: str = ""


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.json_scripts: list[str] = []
        self._in_title = False
        self._in_json_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): v or "" for k, v in attrs}
        if tag.lower() == "title":
            self._in_title = True
            return
        if tag.lower() == "meta":
            key = (attr.get("property") or attr.get("name") or "").strip().lower()
            value = (attr.get("content") or "").strip()
            if key and value:
                self.meta[key] = html.unescape(value)
            return
        if tag.lower() == "script":
            script_type = attr.get("type", "").lower()
            self._in_json_script = "json" in script_type

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        elif tag.lower() == "script":
            self._in_json_script = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif self._in_json_script and data.strip():
            self.json_scripts.append(data)


def clean_text(value: str | None, limit: int | None = None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", html.unescape(value)).strip()
    return value[:limit] if limit is not None else value


def _is_useful_description(value: str | None) -> bool:
    text = clean_text(value)
    if len(text) < 30:
        return False
    bad_patterns = (
        r"^(log in|sign up|forgotten account|accept cookies|reject cookies)\b",
        r"\buse cookies to provide you with\b",
        r"share your videos with friends, family, and the world",
        r"xem bài viết, ảnh và nội dung khác trên facebook",
        r"see posts, photos and more on facebook",
        r"hiển thị tất cả bình luận",
        r"bình luận đã bị tắt",
        r"hiển thị bình luận của bạn bè",
        r"bình luận có nhiều lượt tương tác",
        r"bao gồm cả nội dung có thể là spam",
        r"bất kỳ ai cũng có thể nhìn thấy mọi người trong nhóm",
        r"những gì họ đăng",
        r"tải thông tin liên hệ lên",
        r"đối tượng không phải người dùng",
        r"by using meta ai",
        r"your interactions with ais",
        r"ai terms",
        r"вештачката интелигенција",
        r"интеракции со ви",
        r"to continue, log in to your reddit account",
        r"analyze telegram channel\b",
    )
    return not any(re.search(pattern, text, re.I) for pattern in bad_patterns)


def _walk_json_for_text(obj: Any) -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for key in (
            "description",
            "articleBody",
            "caption",
            "text",
            "share_desc",
            "subtitle",
        ):
            value = obj.get(key)
            if isinstance(value, str) and _is_useful_description(value):
                found.append(clean_text(value))
        for value in obj.values():
            found.extend(_walk_json_for_text(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_walk_json_for_text(item))
    return found


def _parse_metadata(body: str) -> ScrapedMention:
    parser = _MetadataParser()
    parser.feed(body[:2_000_000])
    title = clean_text(" ".join(parser.title_parts), limit=500)

    candidates = [
        parser.meta.get("og:description"),
        parser.meta.get("twitter:description"),
        parser.meta.get("description"),
    ]
    for raw in parser.json_scripts:
        try:
            candidates.extend(_walk_json_for_text(json.loads(raw)))
        except Exception:
            continue

    for candidate in candidates:
        if _is_useful_description(candidate):
            return ScrapedMention(title=title, description=clean_text(candidate), source="metadata")
    return ScrapedMention(title=title, source="metadata")


def _is_allowed_host(host: str) -> bool:
    normalized = host.lower().rstrip(".")
    return any(
        normalized == domain or normalized.endswith("." + domain)
        for domain in _ALLOWED_DOMAINS
    )


def _validate_social_url_sync(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only HTTP(S) social URLs are allowed")
    if parsed.username or parsed.password:
        raise ValueError("Credentials in social URLs are not allowed")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or not _is_allowed_host(host):
        raise ValueError("URL host is outside the configured social platforms")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL port") from exc
    if port not in {None, 80, 443}:
        raise ValueError("Only standard HTTP(S) ports are allowed")

    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        addresses = [
            item[4][0]
            for item in socket.getaddrinfo(
                host,
                port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        ]
    if not addresses:
        raise ValueError("URL host did not resolve")
    if any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("URL host resolves to a non-public address")


async def _validate_social_url(url: str) -> None:
    await asyncio.to_thread(_validate_social_url_sync, url)


async def _safe_get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        await _validate_social_url(current_url)
        response = await client.get(current_url)
        if response.has_redirect_location:
            location = response.headers.get("location")
            if not location:
                response.raise_for_status()
                return response
            current_url = urljoin(str(response.url), location)
            continue
        response.raise_for_status()
        await _validate_social_url(str(response.url))
        return response
    raise httpx.TooManyRedirects("Social URL exceeded the redirect limit")


async def _fetch(url: str, *, headers: dict[str, str] | None = None) -> tuple[str, str]:
    async with httpx.AsyncClient(
        headers=headers or _HEADERS,
        timeout=_FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
    ) as client:
        response = await _safe_get(client, url)
        return str(response.url), response.text


def _host(link: str) -> str:
    return urlparse(link or "").netloc.lower().removeprefix("www.")


def _platform_key(platform: str | None, link: str) -> str:
    raw = (platform or "").strip().lower()
    host = _host(link)
    if raw:
        return raw
    if "facebook.com" in host:
        return "facebook"
    if "instagram.com" in host:
        return "instagram"
    if "tiktok.com" in host:
        return "tiktok"
    if host in {"x.com", "twitter.com"}:
        return "twitter"
    if "reddit.com" in host:
        return "reddit"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "linkedin.com" in host:
        return "linkedin"
    if host in {"t.me", "telegram.me"} or "telemetr" in host or "tgstat" in host:
        return "telegram"
    if "zalo" in host:
        return "zalo"
    return raw or "other"


def _telegram_channel(link: str) -> str:
    parsed = urlparse(link)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    if host in {"t.me", "telegram.me"}:
        parts = [p for p in path.split("/") if p and p != "s"]
        return parts[0] if parts else ""
    match = re.search(r"(?:channels|channel|@)/?([A-Za-z0-9_]{4,})", path)
    if match:
        return match.group(1)
    match = re.search(r"@([A-Za-z0-9_]{4,})", link)
    return match.group(1) if match else ""


async def _scrape_reddit(link: str) -> ScrapedMention:
    rss_url = link.rstrip("/") + "/.rss"
    try:
        _, body = await _fetch(rss_url)
    except Exception as exc:
        logger.debug("reddit rss scrape failed for %s: %r", link, exc)
        return ScrapedMention()

    try:
        root = ET.fromstring(body)
    except Exception:
        return ScrapedMention()

    ns = {"a": "http://www.w3.org/2005/Atom"}
    title = clean_text(root.findtext("a:title", namespaces=ns), limit=500)
    entries = root.findall("a:entry", ns)
    for entry in entries:
        entry_title = clean_text(entry.findtext("a:title", namespaces=ns), limit=500)
        content = clean_text(entry.findtext("a:content", namespaces=ns))
        if entry_title.lower() == "[deleted]" or content.lower().startswith("[deleted]"):
            continue
        if _is_useful_description(content):
            return ScrapedMention(title=title, description=content, source="reddit_rss")
    return ScrapedMention(title=title, source="reddit_rss")


async def _scrape_telegram(link: str) -> ScrapedMention:
    channel = _telegram_channel(link)
    if not channel:
        return ScrapedMention()
    tme_url = f"https://t.me/s/{channel}"
    try:
        _, body = await _fetch(tme_url)
    except Exception as exc:
        logger.debug("telegram scrape failed for %s: %r", link, exc)
        return ScrapedMention()

    parsed = _parse_metadata(body)
    candidates = re.findall(
        r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
        body,
        flags=re.S,
    )
    for candidate in reversed(candidates):
        text = clean_text(candidate)
        if _is_useful_description(text):
            return ScrapedMention(title=parsed.title, description=text, source="telegram_tme")
    return parsed


async def _scrape_youtube(link: str) -> ScrapedMention:
    path = urlparse(link).path
    if not ("/watch" in path or "/shorts/" in path or "youtu.be" in _host(link)):
        return ScrapedMention()
    try:
        _, body = await _fetch(link)
    except Exception as exc:
        logger.debug("youtube scrape failed for %s: %r", link, exc)
        return ScrapedMention()
    return _parse_metadata(body)


async def _scrape_static_metadata(link: str) -> ScrapedMention:
    try:
        _, body = await _fetch(link)
    except Exception as exc:
        logger.debug("static metadata scrape failed for %s: %r", link, exc)
        return ScrapedMention()
    return _parse_metadata(body)


def _tiktok_rehydration_json(body: str) -> dict[str, Any]:
    match = re.search(
        r'<script[^>]+id=["\']__UNIVERSAL_DATA_FOR_REHYDRATION__["\'][^>]*>(.*?)</script>',
        body,
        flags=re.I | re.S,
    )
    if not match:
        return {}

    raw = match.group(1).strip()
    for candidate in (raw, html.unescape(raw)):
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _extract_tiktok_video_metadata(body: str) -> ScrapedMention:
    data = _tiktok_rehydration_json(body)
    item = (
        data.get("__DEFAULT_SCOPE__", {})
        .get("webapp.video-detail", {})
        .get("itemInfo", {})
        .get("itemStruct", {})
    )
    if not isinstance(item, dict):
        return ScrapedMention()

    description = clean_text(item.get("desc"))
    if not _is_useful_description(description):
        return ScrapedMention()

    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    nickname = clean_text(author.get("nickname"), limit=200)
    title = f"{nickname}: {description}" if nickname else description
    return ScrapedMention(title=clean_text(title, limit=500), description=description, source="tiktok_json")


async def _scrape_tiktok_oembed(link: str) -> ScrapedMention:
    try:
        request_url = str(httpx.URL(_TIKTOK_OEMBED_URL).copy_add_param("url", link))
        async with httpx.AsyncClient(
            headers=_HEADERS,
            timeout=_FETCH_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = await _safe_get(client, request_url)
            payload = response.json()
    except Exception as exc:
        logger.debug("tiktok oembed scrape failed for %s: %r", link, exc)
        return ScrapedMention()

    title = clean_text(payload.get("title"), limit=500)
    if _is_useful_description(title):
        author = clean_text(payload.get("author_name"), limit=200)
        page_title = f"{author}: {title}" if author else title
        return ScrapedMention(title=clean_text(page_title, limit=500), description=title, source="tiktok_oembed")
    return ScrapedMention(title=title, source="tiktok_oembed")


async def _scrape_tiktok(link: str) -> ScrapedMention:
    try:
        _, body = await _fetch(link)
    except Exception as exc:
        logger.debug("tiktok metadata scrape failed for %s: %r", link, exc)
    else:
        result = _extract_tiktok_video_metadata(body)
        if result.description:
            return result

        parsed = _parse_metadata(body)
        if parsed.description and not _is_generic_page_text(parsed.description):
            return ScrapedMention(title=parsed.title, description=parsed.description, source="tiktok_metadata")

    return await _scrape_tiktok_oembed(link)


def _facebook_slug_description(link: str) -> str:
    parsed = urlparse(link)
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if not parts:
        return ""

    candidate = ""
    for marker in ("posts", "photos", "videos", "reel"):
        if marker in parts:
            idx = parts.index(marker)
            if idx + 1 < len(parts):
                candidate = parts[idx + 1]
                break

    if not candidate:
        for part in reversed(parts):
            lowered = part.lower()
            if lowered in {"posts", "photos", "videos", "photo.php", "permalink.php", "d41d8cd9"}:
                continue
            if re.fullmatch(r"\d+", part):
                continue
            candidate = part
            break

    candidate = clean_text(candidate.replace("-", " "))
    if _is_useful_description(candidate) and not _is_generic_page_text(candidate):
        return candidate
    return ""


async def _scrape_facebook(link: str) -> ScrapedMention:
    try:
        _final_url, body = await _fetch(link, headers=_FACEBOOK_METADATA_HEADERS)
    except Exception as exc:
        logger.debug("facebook metadata scrape failed for %s: %r", link, exc)
    else:
        parsed = _parse_metadata(body)
        if parsed.description and not _is_generic_page_text(parsed.description):
            return ScrapedMention(
                title=parsed.title,
                description=parsed.description,
                source="facebook_metadata",
            )

    slug_description = _facebook_slug_description(link)
    if slug_description:
        return ScrapedMention(description=slug_description, source="facebook_url_slug")

    return ScrapedMention()


def _parse_x_title(title: str) -> str:
    # Example: Tradepass on X: "tweet body" / X
    match = re.search(r'on X:\s*"(.+)"\s*/\s*X$', title)
    if match:
        return clean_text(match.group(1))
    match = re.search(r'on Twitter:\s*"(.+)"\s*/\s*Twitter$', title)
    return clean_text(match.group(1)) if match else ""


def _is_generic_page_text(text: str) -> bool:
    normalized = clean_text(text).lower()
    bad_patterns = (
        r"available now! telegram research",
        r"telegram research 20\d{2}",
        r"get the research",
        r"don't get caught by a cheater",
        r"telemetrio finds and tags such channels",
        r"show all comments",
        r"including potential spam",
        r"scan the qr code",
        r"confirm (?:the )?codes match to log in",
        r"this content isn't available right now",
        r"when this happens, it's usually because",
        r"changed who can see it or it's been deleted",
        r"pc_web_explorepage",
        r"explorepage_topics",
        r"topics_singing_dancing",
        r"^\d{1,2} [a-z]+, \d{4} - \d+ years?",
        r"^\d{1,2} [a-z]+, \d{4} - \d+ months?",
    )
    return any(re.search(pattern, normalized, re.I) for pattern in bad_patterns)


def _extract_telemetr_result(title: str, body_text: str) -> ScrapedMention:
    page_title = clean_text(title, limit=500)
    channel_title = clean_text(page_title.split(" - Statistics", 1)[0], limit=500)
    lines = [clean_text(line) for line in body_text.splitlines()]
    lines = [line for line in lines if line]

    stop_lines = {
        "show more",
        "the country is not specified",
        "the category is not specified",
        "to the collection",
        "subscribers",
        "overview",
        "advertisers",
        "traffic sources",
        "posts",
        "about the channel",
    }
    skip_lines = {
        "open in telegram",
        "verify channel",
    }

    if channel_title in lines:
        start = lines.index(channel_title) + 1
        description_parts: list[str] = []
        for line in lines[start:]:
            lowered = line.lower()
            if lowered in stop_lines:
                break
            if lowered in skip_lines or _is_generic_page_text(line):
                continue
            description_parts.append(line)
        description = clean_text(" ".join(description_parts))
        if _is_useful_description(description):
            return ScrapedMention(title=page_title, description=description, source="telemetr_channel")

    if "Channel Posts" in lines:
        start = lines.index("Channel Posts") + 1
        for line in lines[start:]:
            if line in {"Latest", "Advertising", "Deleted", channel_title, "Repost from N/a", "Analytics"}:
                continue
            if (
                re.fullmatch(r"\d+", line)
                or re.search(r"\d{1,2} \w{3}, \d{2}:\d{2}", line)
                or re.search(r"\d{1,2} [A-Za-z]+, \d{4} - \d+", line)
            ):
                continue
            if _is_useful_description(line) and not _is_generic_page_text(line):
                return ScrapedMention(title=page_title, description=line, source="telemetr_post")

    return ScrapedMention(title=page_title, source="telemetr")


def _extract_browser_result(link: str, title: str, page: str, body_text: str, final_url: str) -> ScrapedMention:
    parsed = _parse_metadata(page)
    page_title = clean_text(title or parsed.title, limit=500)

    if "telemetr.io" in _host(final_url) or "telemetr.io" in _host(link):
        telemetr = _extract_telemetr_result(page_title or parsed.title, body_text)
        if telemetr.description:
            return telemetr

    if "x.com" in _host(final_url) or "twitter.com" in _host(final_url):
        x_text = _parse_x_title(page_title)
        if _is_useful_description(x_text):
            return ScrapedMention(title=page_title, description=x_text, source="browser_x_title")

    if parsed.description and not _is_generic_page_text(parsed.description):
        return ScrapedMention(title=page_title or parsed.title, description=parsed.description, source="browser_metadata")

    for line in body_text.splitlines():
        text = clean_text(line)
        if _is_useful_description(text) and not _is_generic_page_text(text):
            return ScrapedMention(title=page_title, description=text, source="browser_text")
    return ScrapedMention(title=page_title, source="browser")


class BrowserScraper:
    """Reusable headless browser for maintenance jobs.

    Request handlers use `_scrape_browser`, which creates and closes a browser
    per scrape. Long-running backfills should use this class to avoid paying
    Chrome startup cost for every URL.
    """

    def __init__(self) -> None:
        self._driver: Any | None = None
        self._by: Any | None = None

    def _ensure_driver(self) -> Any:
        if self._driver is not None:
            return self._driver
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By

        options = uc.ChromeOptions()
        if _BROWSER_BINARY:
            options.binary_location = _BROWSER_BINARY
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1365,1200")
        options.add_argument("--lang=vi-VN")
        options.add_argument(f"--user-agent={_HEADERS['user-agent']}")

        kwargs: dict[str, Any] = {
            "options": options,
            "use_subprocess": True,
        }
        if _BROWSER_BINARY:
            kwargs["browser_executable_path"] = _BROWSER_BINARY
        if _BROWSER_VERSION_MAIN.isdigit():
            kwargs["version_main"] = int(_BROWSER_VERSION_MAIN)

        self._driver = uc.Chrome(**kwargs)
        self._driver.set_page_load_timeout(_BROWSER_TIMEOUT_SECONDS)
        self._by = By
        return self._driver

    def scrape(self, link: str) -> ScrapedMention:
        try:
            _validate_social_url_sync(link)
            driver = self._ensure_driver()
            driver.get(link)
            time.sleep(_BROWSER_WAIT_SECONDS)
            final_url = driver.current_url or link
            _validate_social_url_sync(final_url)
            by = self._by
            body_text = driver.find_element(by.TAG_NAME, "body").text if by is not None else ""
            return _extract_browser_result(
                link,
                title=driver.title or "",
                page=driver.page_source,
                body_text=body_text,
                final_url=final_url,
            )
        except Exception as exc:
            logger.debug("browser scrape failed for %s: %r", link, exc)
            return ScrapedMention()

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
            self._by = None

    def __enter__(self) -> "BrowserScraper":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def _browser_scrape_sync(link: str) -> ScrapedMention:
    try:
        with BrowserScraper() as browser:
            return browser.scrape(link)
    except Exception as exc:
        logger.warning("browser scraper unavailable: %r", exc)
        return ScrapedMention()


async def _scrape_browser(link: str) -> ScrapedMention:
    if not _BROWSER_ENABLED:
        return ScrapedMention()
    async with _BROWSER_SEMAPHORE:
        return await asyncio.to_thread(_browser_scrape_sync, link)


async def scrape_social_description(
    *,
    platform: str | None,
    link: str,
    fallback_title: str = "",
    fallback_description: str = "",
    use_browser: bool = True,
) -> ScrapedMention:
    key = _platform_key(platform, link)

    platform_scrapers = {
        "facebook": _scrape_facebook,
        "tiktok": _scrape_tiktok,
        "reddit": _scrape_reddit,
        "telegram": _scrape_telegram,
        "youtube": _scrape_youtube,
        "linkedin": _scrape_static_metadata,
        "zalo": _scrape_static_metadata,
        "lotus": _scrape_static_metadata,
    }
    scraper = platform_scrapers.get(key)
    if scraper is not None:
        result = await scraper(link)
        if result.description:
            return result

    result = ScrapedMention()
    if use_browser:
        result = await _scrape_browser(link)
        if result.description:
            return result

    title = clean_text(result.title or fallback_title, limit=500)
    return ScrapedMention(
        title=title,
        description=clean_text(fallback_description),
        source="serpapi_fallback",
    )

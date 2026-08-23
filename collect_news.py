#!/usr/bin/env python3
"""
Collect semiconductor briefing candidates from public feeds/APIs and write articles.json.

The collector stores metadata, links, and short summaries only. It does not copy full
article bodies from third-party sites.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import base64
from html.parser import HTMLParser
from pathlib import Path
import socket

ROOT = Path(__file__).resolve().parent
SOURCES_PATH = ROOT / "sources.json"
ARTICLES_PATH = ROOT / "articles.json"
ARCHIVE_DIR = ROOT / "archive"
ARCHIVE_INDEX_PATH = ARCHIVE_DIR / "index.json"


def load_dotenv():
    env_path = ROOT / ".env"
    if env_path.is_file():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key and val and key not in os.environ:
                            os.environ[key] = val
        except Exception:
            pass


load_dotenv()

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
TIMEOUT = int(os.environ.get("CHIP_BRIEFING_TIMEOUT", "15"))
socket.setdefaulttimeout(TIMEOUT)

MAX_ITEMS = int(os.environ.get("CHIP_BRIEFING_MAX_ITEMS", "100"))
MAX_COMMUNITY_ITEMS = int(os.environ.get("CHIP_BRIEFING_MAX_COMMUNITY_ITEMS", "10"))
COMMUNITY_CANDIDATE_LIMIT = int(os.environ.get("CHIP_BRIEFING_COMMUNITY_CANDIDATE_LIMIT", "20"))
HF_TOKEN = (
    os.environ.get("HF_TOKEN")
    or os.environ.get("HUGGINGFACE_TOKEN")
    or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
    or ""
)
LLM_BASE_URL = os.environ.get("CHIP_BRIEFING_LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY_RAW = os.environ.get("CHIP_BRIEFING_LLM_API_KEY", "") or HF_TOKEN
LLM_API_KEYS = [k.strip() for k in LLM_API_KEY_RAW.split(",") if k.strip()]
_CURRENT_KEY_INDEX = 0

def get_current_llm_key() -> str:
    global _CURRENT_KEY_INDEX
    if not LLM_API_KEYS:
        return ""
    return LLM_API_KEYS[_CURRENT_KEY_INDEX % len(LLM_API_KEYS)]

def rotate_llm_key():
    global _CURRENT_KEY_INDEX
    if LLM_API_KEYS:
        _CURRENT_KEY_INDEX += 1

LLM_MODEL = os.environ.get("CHIP_BRIEFING_LLM_MODEL", "")
LLM_MAX_ITEMS = int(os.environ.get("CHIP_BRIEFING_LLM_MAX_ITEMS", str(MAX_ITEMS)))
LLM_TIMEOUT = int(os.environ.get("CHIP_BRIEFING_LLM_TIMEOUT", "45"))
DAILY_SUMMARY_MAX_ITEMS = int(os.environ.get("CHIP_BRIEFING_DAILY_SUMMARY_MAX_ITEMS", "10"))

EDITORIAL_PRIORITY_PROMPT = """
You are the semiconductor briefing editor. Read the article context and assign importance_score by editorial impact, not by simple keyword matching.

Ranking policy:
- 5: Top priority. Direct impact on AI acceleration or AI infrastructure bottlenecks: AI accelerators, GPU/NPU/TPU/ASIC, HBM/HBM4/HBM4E, CoWoS/SoIC/advanced packaging, high-bandwidth memory supply, AI server supply chain, rack-scale AI infrastructure, or Big Tech custom AI chips and major supplier partnerships.
- 4: Major semiconductor industry impact: leading-edge foundry competition, 2nm/1.4nm/GAA/backside power/High-NA EUV, meaningful yield/capacity/customer wins, memory cycle shifts outside HBM, major policy/export-control/supply-chain risk, or M&A.
- 3: Relevant but normal semiconductor news: design/process/materials/device/packaging/EDA/IP/standard updates, market trend notes, ordinary product or technical announcements.
- 2: Narrow company updates, minor product/tool announcements, routine financial or event coverage with limited industry impact.
- 1: Weak semiconductor relevance, promotional content, peripheral industries, awards, general interviews, or routine corporate activity.

Prioritize actual industry consequences: who is affected, which bottleneck moves, whether capacity/supply/demand changes, and whether the news changes AI compute availability or competitive position. If an article only mentions AI in passing, do not over-score it.
Return JSON only and include importance_score as an integer from 1 to 5.
""".strip()

if HF_TOKEN and not LLM_BASE_URL:
    LLM_BASE_URL = "https://router.huggingface.co/v1"
if HF_TOKEN and not LLM_MODEL:
    LLM_MODEL = "google/gemma-4-26B-A4B-it"

RSS_CANDIDATES = {
    "NVIDIA Developer Blog": ["https://developer.nvidia.com/blog/feed/"],
    "Semiconductor Engineering": ["https://semiengineering.com/feed/"],
    "SemiWiki": ["https://semiwiki.com/feed/"],
    "EE Times": ["https://www.eetimes.com/feed/"],
    "ServeTheHome": ["https://www.servethehome.com/feed/"],
    "IEEE Spectrum": ["https://spectrum.ieee.org/feeds/feed.rss"],
    "SIA": ["https://www.semiconductors.org/feed/"],
    "SEMI": ["https://www.semi.org/en/rss.xml"],
    "Samsung Newsroom": ["https://news.samsung.com/global/feed"],
    "SK hynix Newsroom": ["https://news.skhynix.com/feed/"],
    "Intel Newsroom": ["https://www.intel.com/content/www/us/en/newsroom/rss.xml"],
    "Micron Newsroom": ["https://www.micron.com/about/news-and-events/rss.xml"],
}

GOOGLE_NEWS_QUERIES = [
    "semiconductor HBM OR HBM4 OR HBM4E",
    "semiconductor CoWoS advanced packaging hybrid bonding",
    "semiconductor High NA EUV GAA 2nm",
    "AI accelerator ASIC GPU NPU semiconductor",
    "반도체 HBM OR 패키징 OR EUV OR 파운드리",
]

REDDIT_SUBREDDITS = [
    "hardware",
    "semiconductors",
    "chipdesign",
    "electronics",
    "ECE",
    "MachineLearning",
    "LocalLLaMA",
    "nvidia",
    "AMD_Stock",
    "intel",
]

COMMUNITY_USER_AGENT = os.environ.get(
    "CHIP_BRIEFING_COMMUNITY_USER_AGENT",
    "script:chip-briefing:v2.1 (contact: github.com/wlsalswo14)",
).strip()
COMMUNITY_HEADERS = {
    "User-Agent": COMMUNITY_USER_AGENT,
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
}
COMMUNITY_SEARCH_QUERIES = [
    "HBM HBM4",
    "반도체 패키징 CoWoS",
    "EUV GAA 2나노",
    "AI 반도체 GPU NPU",
    "삼성전자 파운드리",
    "SK하이닉스 HBM",
    "TSMC ASML",
]

def now_iso() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def request_json(url: str, headers: dict[str, str] | None = None) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return json.loads(res.read().decode("utf-8", errors="replace"))


def post_json(url: str, payload: dict, headers: dict[str, str] | None = None, timeout: int = TIMEOUT) -> object:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            **(headers or {}),
        },
        method="POST",
    )
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return json.loads(res.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                if len(LLM_API_KEYS) > 1:
                    raise exc
                if attempt < max_retries - 1:
                    # Try to get retry delay from headers or body
                    retry_after = exc.headers.get("Retry-After")
                    delay = 10.0
                    if retry_after:
                        try:
                            delay = float(retry_after)
                        except ValueError:
                            pass
                    else:
                        try:
                            # Try parsing response body for retry delay
                            body_text = exc.read().decode("utf-8", errors="replace")
                            err_data = json.loads(body_text)
                            msg = err_data.get("error", {}).get("message", "")
                            match = re.search(r"Please retry in (\d+\.?\d*)s", msg)
                            if match:
                                delay = float(match.group(1)) + 1.0
                        except Exception:
                            pass
                    print(f"Rate limited (429). Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    continue
            raise


def post_form(url: str, payload: dict, headers: dict[str, str] | None = None, timeout: int = TIMEOUT) -> object:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            **(headers or {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8", errors="replace"))


def request_text(url: str, headers: dict[str, str] | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        data = res.read()
        ctype = res.headers.get_content_charset() or "utf-8"
        return data.decode(ctype, errors="replace")


def extract_article_text(url: str) -> str:
    try:
        text = request_text(url)
    except Exception:
        return ""
    head = text[:300].lower()
    if "<html" not in head and "<!doctype" not in head:
        return clean_text(text)[:5000]
    text = re.sub(r"(?is)<(script|style|noscript|svg|iframe).*?</\1>", " ", text)
    text = re.sub(r"(?is)<(nav|footer|header|aside).*?</\1>", " ", text)
    paragraphs = re.findall(r"(?is)<p[^>]*>(.*?)</p>", text)
    cleaned = [clean_text(p) for p in paragraphs]
    cleaned = [p for p in cleaned if len(p) >= 45]
    joined = " ".join(cleaned)
    if not joined:
        joined = clean_text(text)
    return joined[:7000]


def parse_date(value: str | None) -> str:
    if not value:
      return now_iso()
    value = clean_text(value)
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")
    except Exception:
        pass
    # Naver Blog/Cafe Search returns date-only values such as 20260821.
    # Treat them as Seoul-local calendar dates instead of falling back to the
    # collector run time, which would place a 07:00 run outside its own window.
    if re.fullmatch(r"\d{8}", value):
        try:
            parsed = dt.datetime.strptime(value, "%Y%m%d")
            parsed = parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=9)))
            return parsed.isoformat(timespec="seconds")
        except Exception:
            pass
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")
    except Exception:
        return now_iso()


def parse_kst_datetime(value: str, *formats: str) -> str:
    value = clean_text(value)
    kst = dt.timezone(dt.timedelta(hours=9))
    for date_format in formats:
        try:
            return dt.datetime.strptime(value, date_format).replace(tzinfo=kst).isoformat(timespec="seconds")
        except ValueError:
            continue
    return ""


class DCInsideSearchParser(HTMLParser):
    """Parse public DCInside post-search result metadata without opening posts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.capture_field = ""
        self.capture_tag = ""
        self.capture_parts: list[str] = []

    @staticmethod
    def classes(attrs: dict[str, str]) -> set[str]:
        return set(attrs.get("class", "").split())

    def begin_capture(self, field: str, tag: str) -> None:
        self.capture_field = field
        self.capture_tag = tag
        self.capture_parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = self.classes(attr)
        if tag == "a" and "tit_txt" in classes:
            self.current = {"url": attr.get("href", "")}
            self.begin_capture("title", tag)
        elif self.current is not None and tag == "p" and "link_dsc_txt" in classes and "dsc_sub" not in classes:
            self.begin_capture("snippet", tag)
        elif self.current is not None and tag == "a" and "sub_txt" in classes:
            self.begin_capture("community", tag)
        elif self.current is not None and tag == "span" and "date_time" in classes:
            self.begin_capture("date", tag)

    def handle_data(self, data: str) -> None:
        if self.capture_field:
            self.capture_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.capture_field or tag != self.capture_tag or self.current is None:
            return
        field = self.capture_field
        self.current[field] = clean_text("".join(self.capture_parts))
        self.capture_field = ""
        self.capture_tag = ""
        self.capture_parts = []
        if field == "date":
            if self.current.get("title") and self.current.get("url"):
                self.items.append(self.current)
            self.current = None


class ClienBoardParser(HTMLParser):
    """Parse article rows from robots-allowed public Clien board pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.row_depth = 0
        self.capture_field = ""
        self.capture_tag = ""
        self.capture_parts: list[str] = []

    @staticmethod
    def classes(attrs: dict[str, str]) -> set[str]:
        return set(attrs.get("class", "").split())

    def begin_capture(self, field: str, tag: str) -> None:
        self.capture_field = field
        self.capture_tag = tag
        self.capture_parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = self.classes(attr)

        if tag == "div":
            if self.current is not None:
                self.row_depth += 1
            elif "list_item" in classes and "symph_row" in classes:
                self.current = {}
                self.row_depth = 1

        if self.current is None:
            return
        if tag == "a" and "list_subject" in classes:
            self.current["url"] = attr.get("href", "")
            self.begin_capture("title", tag)
        elif tag == "span" and "subject_fixed" in classes and attr.get("title"):
            self.current["title"] = clean_text(attr["title"])
        elif tag == "span" and "icon_pic" in classes:
            self.current["has_image"] = "true"
        elif tag == "span" and "timestamp" in classes:
            self.begin_capture("date", tag)

    def handle_data(self, data: str) -> None:
        if self.capture_field:
            self.capture_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.capture_field and tag == self.capture_tag and self.current is not None:
            field = self.capture_field
            value = clean_text("".join(self.capture_parts))
            if value and not self.current.get(field):
                self.current[field] = value
            self.capture_field = ""
            self.capture_tag = ""
            self.capture_parts = []

        if tag == "div" and self.current is not None:
            self.row_depth -= 1
            if self.row_depth == 0:
                if self.current.get("title") and self.current.get("url"):
                    self.items.append(self.current)
                self.current = None


def stable_id(url: str, title: str) -> str:
    raw = (url or title).encode("utf-8", errors="ignore")
    return "art-" + hashlib.sha1(raw).hexdigest()[:14]


def canonical_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query = [(k, v) for k, v in query if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(query), ""))
    except Exception:
        return url


def source_to_rss_urls(source: dict) -> list[str]:
    urls: list[str] = []
    name = source.get("name", "")
    if name in RSS_CANDIDATES:
        urls.extend(RSS_CANDIDATES[name])
    base = source.get("url")
    if base and source.get("type") in {"rss", "rss_or_html", "html_or_rss"}:
        base = base.rstrip("/")
        urls.extend([base + "/feed/", base + "/rss", base + "/rss.xml", base + "/feed.xml"])
    # Preserve order, remove dupes.
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url not in seen:
            out.append(url)
            seen.add(url)
    return out


def parse_feed(xml_text: str, source: dict, feed_url: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = root.findall(".//item")
    atom_ns = "{http://www.w3.org/2005/Atom}"
    if not items:
        items = root.findall(f".//{atom_ns}entry")
    out: list[dict] = []
    for item in items[:20]:
        title = clean_text((item.findtext("title") or item.findtext(f"{atom_ns}title") or ""))
        if not title:
            continue
        link = item.findtext("link") or ""
        if not link:
            atom_link = item.find(f"{atom_ns}link")
            if atom_link is not None:
                link = atom_link.attrib.get("href", "")
        desc = (
            item.findtext("description")
            or item.findtext("summary")
            or item.findtext(f"{atom_ns}summary")
            or item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
            or ""
        )
        pub = item.findtext("pubDate") or item.findtext("published") or item.findtext(f"{atom_ns}published")
        out.append(make_article(title, link, desc, source, "rss", parse_date(pub)))
    return out


def make_article(title: str, link: str, snippet: str, source: dict, raw_type: str, created_at: str) -> dict:
    title = clean_text(title)
    snippet = clean_text(snippet)
    if not snippet:
        snippet = title
    body = snippet[:320].rstrip()
    if len(snippet) > 320:
        body += "..."
    url = canonical_url(link)
    text_for_sector = f"{title} {snippet}"
    sector, matched = classify_sector(text_for_sector)
    category = source.get("category_default") or ("community" if raw_type in {"social", "community"} else "news")
    trust = source.get("trust_default") or ("low" if category in {"rumor", "community"} else "medium")
    return {
        "id": stable_id(url, title),
        "headline": title,
        "body": body,
        "sector": sector,
        "category": category,
        "trust": trust,
        "created_at": created_at,
        "placement": "side",
        "source_name": source.get("name", "Unknown"),
        "source_url": url,
        "source_note": source.get("notes") or source.get("type") or raw_type,
        "raw_source_type": raw_type,
        "matched_keywords": matched,
    }


_SECTOR_KEYWORDS: dict[str, list[str]] = {}


def classify_sector(text: str) -> tuple[str, list[str]]:
    text_l = text.lower()
    scores: dict[str, int] = {}
    matches: dict[str, list[str]] = {}
    for sector, keywords in _SECTOR_KEYWORDS.items():
        for keyword in keywords:
            if keyword_matches(text_l, keyword):
                scores[sector] = scores.get(sector, 0) + 1
                matches.setdefault(sector, []).append(keyword)
    if not scores:
        return "설계", []
    sector = sorted(scores, key=lambda s: (-scores[s], s))[0]
    return sector, matches.get(sector, [])


def keyword_matches(text_l: str, keyword: str) -> bool:
    key = keyword.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9.+-]*", key):
        return re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", text_l) is not None
    if re.fullmatch(r"[a-z0-9][a-z0-9.+-]*( [a-z0-9][a-z0-9.+-]*)+", key):
        return re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", text_l) is not None
    return key in text_l


def collect_rss(sources: list[dict]) -> tuple[list[dict], list[str]]:
    articles: list[dict] = []
    logs: list[str] = []
    for source in sources:
        for feed_url in source_to_rss_urls(source):
            try:
                xml_text = request_text(feed_url)
                if "<rss" not in xml_text[:500].lower() and "<feed" not in xml_text[:500].lower():
                    continue
                found = parse_feed(xml_text, source, feed_url)
                if found:
                    articles.extend(found)
                    logs.append(f"rss ok: {source.get('name')} ({len(found)}) {feed_url}")
                    break
            except Exception as exc:
                logs.append(f"rss skip: {source.get('name')} {feed_url} ({type(exc).__name__})")
    return articles, logs


def collect_google_news() -> tuple[list[dict], list[str]]:
    articles: list[dict] = []
    logs: list[str] = []
    source = {
        "name": "Google News RSS",
        "type": "rss",
        "trust_default": "medium",
        "category_default": "news",
        "notes": "Google News search RSS result; original publisher link is retained where available.",
    }
    for query in GOOGLE_NEWS_QUERIES:
        params = urllib.parse.urlencode({"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
        url = f"https://news.google.com/rss/search?{params}"
        try:
            found = parse_feed(request_text(url), source, url)
            articles.extend(found[:10])
            logs.append(f"google news ok: {query} ({len(found[:10])})")
            time.sleep(0.2)
        except Exception as exc:
            logs.append(f"google news skip: {query} ({type(exc).__name__})")
    return articles, logs


def collect_naver(sources: list[dict], queries: list[str]) -> tuple[list[dict], list[str]]:
    cid = os.environ.get("NAVER_CLIENT_ID")
    secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not cid or not secret:
        return [], ["naver skip: NAVER_CLIENT_ID/NAVER_CLIENT_SECRET not set"]
    articles: list[dict] = []
    logs: list[str] = []
    headers = {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret}
    for source in sources:
        endpoint = source.get("endpoint", "")
        if "naver.com" not in endpoint:
            continue
        for query in queries:
            params = urllib.parse.urlencode({"query": query, "display": 10, "sort": "date"})
            url = endpoint + "?" + params
            try:
                data = request_json(url, headers=headers)
                items = data.get("items", []) if isinstance(data, dict) else []
                for item in items:
                    link = item.get("originallink") or item.get("link") or ""
                    snippet = item.get("description") or ""
                    raw_type = "community" if source.get("category_default") == "community" else "api"
                    published = item.get("pubDate") or item.get("postdate")
                    article = make_article(item.get("title", ""), link, snippet, source, raw_type, parse_date(published))
                    if raw_type == "community":
                        community_name = clean_text(item.get("cafename", "")) or "Naver Cafe"
                        article["community_origin"] = "domestic"
                        article["community_name"] = community_name
                        article["source_name"] = f"Naver Cafe · {community_name}"
                        if not published:
                            # Naver Cafe Search deliberately omits a post timestamp.
                            # Preserve the collection time but bypass exact publication-window checks.
                            article["date_is_estimated"] = True
                            article["collected_at"] = article["created_at"]
                    articles.append(article)
                logs.append(f"naver ok: {source.get('name')} {query} ({len(items)})")
                time.sleep(0.15)
            except Exception as exc:
                logs.append(f"naver skip: {query} ({type(exc).__name__})")
    return articles, logs


def collect_hn(queries: list[str], source: dict) -> tuple[list[dict], list[str]]:
    articles: list[dict] = []
    logs: list[str] = []
    for query in queries[:4]:
        params = urllib.parse.urlencode({"query": query, "tags": "story", "hitsPerPage": 10})
        url = "https://hn.algolia.com/api/v1/search_by_date?" + params
        try:
            data = request_json(url)
            hits = data.get("hits", []) if isinstance(data, dict) else []
            for hit in hits:
                link = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
                snippet = hit.get("story_text") or hit.get("title") or ""
                articles.append(make_article(hit.get("title", ""), link, snippet, source, "community", parse_date(hit.get("created_at"))))
            logs.append(f"hn ok: {query} ({len(hits)})")
        except Exception as exc:
            logs.append(f"hn skip: {query} ({type(exc).__name__})")
    return articles, logs


def collect_dcinside(queries: list[str], source: dict) -> tuple[list[dict], list[str]]:
    articles: list[dict] = []
    logs: list[str] = []
    endpoint = str(source.get("endpoint", "https://search.dcinside.com/post")).rstrip("/")

    for query in queries:
        url = f"{endpoint}/sort/latest/q/{urllib.parse.quote(query, safe='')}"
        try:
            parser = DCInsideSearchParser()
            parser.feed(request_text(url, headers=COMMUNITY_HEADERS))
            found: list[dict] = []
            for row in parser.items:
                created_at = parse_kst_datetime(row.get("date", ""), "%Y.%m.%d %H:%M")
                if not created_at:
                    continue
                community = clean_text(row.get("community", "")) or "디시인사이드"
                dc_source = dict(source)
                dc_source["name"] = f"DCInside · {community}"
                article = make_article(
                    row.get("title", ""),
                    row.get("url", ""),
                    row.get("snippet", "") or row.get("title", ""),
                    dc_source,
                    "community",
                    created_at,
                )
                article.update({
                    "community_origin": "domestic",
                    "community_name": f"디시 · {community}",
                })
                found.append(article)
            articles.extend(found)
            logs.append(f"dcinside ok: {query} ({len(found)})")
            time.sleep(0.55)
        except Exception as exc:
            logs.append(f"dcinside skip: {query} ({type(exc).__name__})")
    return articles, logs


def collect_clien(source: dict) -> tuple[list[dict], list[str]]:
    articles: list[dict] = []
    logs: list[str] = []
    base_url = str(source.get("url", "https://www.clien.net/service/board/")).rstrip("/") + "/"
    boards = source.get("boards", [])
    max_pages = max(1, min(int(source.get("max_pages", 20)), 30))
    window_start, _ = briefing_window()

    for board in boards:
        board_id = clean_text(str(board.get("id", "")))
        board_name = clean_text(str(board.get("name", ""))) or board_id
        if not board_id:
            continue
        board_url = urllib.parse.urljoin(base_url, urllib.parse.quote(board_id, safe=""))
        found: list[dict] = []
        pages_fetched = 0
        try:
            for page_index in range(max_pages):
                query = urllib.parse.urlencode({"od": "T31", "category": 0, "po": page_index})
                page_url = f"{board_url}?{query}"
                parser = ClienBoardParser()
                parser.feed(request_text(page_url, headers=COMMUNITY_HEADERS))
                if not parser.items:
                    break

                page_dates: list[dt.datetime] = []
                for row in parser.items:
                    created_at = parse_kst_datetime(row.get("date", ""), "%Y-%m-%d %H:%M:%S")
                    if not created_at:
                        continue
                    page_dates.append(dt.datetime.fromisoformat(created_at))
                    link = urllib.parse.urljoin(base_url, row.get("url", ""))
                    parsed_link = urllib.parse.urlsplit(link)
                    link = urllib.parse.urlunsplit((parsed_link.scheme, parsed_link.netloc, parsed_link.path, "", ""))
                    clien_source = dict(source)
                    clien_source["name"] = f"Clien · {board_name}"
                    article = make_article(
                        row.get("title", ""),
                        link,
                        row.get("title", ""),
                        clien_source,
                        "community",
                        created_at,
                    )
                    article.update({
                        "community_origin": "domestic",
                        "community_name": f"클리앙 · {board_name}",
                        "has_image": row.get("has_image") == "true",
                    })
                    found.append(article)

                pages_fetched += 1
                # Busy boards can require several pages to reach the completed
                # 07:00-to-07:00 window during a later manual workflow run.
                if page_dates and min(page_dates) <= window_start:
                    break
                time.sleep(0.4)

            articles.extend(found)
            logs.append(f"clien ok: {board_name} ({len(found)} from {pages_fetched} pages)")
        except Exception as exc:
            if found:
                articles.extend(found)
                logs.append(
                    f"clien partial: {board_name} ({len(found)} from {pages_fetched} pages; "
                    f"{type(exc).__name__})"
                )
            else:
                logs.append(f"clien skip: {board_name} ({type(exc).__name__})")
    return articles, logs


def collect_naver_web_communities(
    sources: list[dict],
    queries: list[str],
) -> tuple[list[dict], list[str]]:
    """Discover community links through Naver Web Search when native search disallows bots."""
    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        return [], ["naver web community skip: NAVER_CLIENT_ID/NAVER_CLIENT_SECRET not set"]

    articles: list[dict] = []
    logs: list[str] = []
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    for source in sources:
        endpoint = str(source.get("endpoint", "https://openapi.naver.com/v1/search/webkr.json"))
        domain = str(source.get("site_domain", "")).lower().lstrip(".")
        community_name = clean_text(str(source.get("community_name", ""))) or source.get("name", "커뮤니티")
        for query in queries:
            params = urllib.parse.urlencode({
                "query": f"site:{domain} {query}",
                "display": 5,
                "start": 1,
            })
            try:
                data = request_json(endpoint + "?" + params, headers=headers)
                rows = data.get("items", []) if isinstance(data, dict) else []
                found: list[dict] = []
                for row in rows:
                    link = str(row.get("link", ""))
                    hostname = (urllib.parse.urlsplit(link).hostname or "").lower()
                    if not domain or not (hostname == domain or hostname.endswith("." + domain)):
                        continue
                    article = make_article(
                        row.get("title", ""),
                        link,
                        row.get("description", ""),
                        source,
                        "community",
                        now_iso(),
                    )
                    article.update({
                        "community_origin": "domestic",
                        "community_name": community_name,
                        "date_is_estimated": True,
                        "collected_at": article["created_at"],
                        "has_image": bool(row.get("thumbnail")),
                    })
                    found.append(article)
                articles.extend(found)
                logs.append(f"naver web community ok: {community_name} {query} ({len(found)})")
                time.sleep(0.2)
            except Exception as exc:
                logs.append(f"naver web community skip: {community_name} {query} ({type(exc).__name__})")
    return articles, logs


def collect_reddit(queries: list[str], source: dict) -> tuple[list[dict], list[str]]:
    articles: list[dict] = []
    logs: list[str] = []

    api_approved = os.environ.get("REDDIT_DATA_API_APPROVED", "").strip().lower() in {"1", "true", "yes"}
    if not api_approved:
        return [], ["reddit skip: REDDIT_DATA_API_APPROVED is not true"]

    client_id = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    user_agent = (
        os.environ.get("REDDIT_USER_AGENT")
        or "script:chip-briefing:v2.0 (contact: github.com/wlsalswo14)"
    ).strip()
    if not client_id or not client_secret:
        return [], ["reddit skip: REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET not set"]

    try:
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        token_data = post_form(
            "https://www.reddit.com/api/v1/access_token",
            {"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {credentials}",
                "User-Agent": user_agent,
            },
        )
        access_token = str(token_data.get("access_token", "")) if isinstance(token_data, dict) else ""
        if not access_token:
            return [], ["reddit oauth skip: access token missing"]
    except Exception as exc:
        return [], [f"reddit oauth skip: {type(exc).__name__}"]

    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": user_agent,
    }
    compact_queries = [
        "HBM OR HBM4 OR HBM4E",
        "CoWoS OR advanced packaging OR hybrid bonding",
        "High NA EUV OR GAA OR nanosheet OR 2nm",
        "AI accelerator OR ASIC OR GPU OR NPU",
        "semiconductor foundry TSMC Samsung ASML",
    ]

    # A multi-subreddit search keeps the request count small and uses Reddit's
    # authenticated JSON API. Anonymous RSS traffic is now routinely blocked.
    target = "+".join(REDDIT_SUBREDDITS)
    for query in compact_queries:
        params = urllib.parse.urlencode({
            "q": query,
            "sort": "new",
            "restrict_sr": "true",
            "t": "day",
            "limit": 25,
            "raw_json": 1,
        })
        url = f"https://oauth.reddit.com/r/{target}/search?{params}"
        try:
            data = request_json(url, headers=headers)
            children = data.get("data", {}).get("children", []) if isinstance(data, dict) else []
            found: list[dict] = []
            for child in children:
                row = child.get("data", {}) if isinstance(child, dict) else {}
                title = clean_text(row.get("title", ""))
                permalink = str(row.get("permalink", ""))
                if not title or not permalink:
                    continue
                subreddit = clean_text(row.get("subreddit", "")) or "Reddit"
                created = dt.datetime.fromtimestamp(
                    float(row.get("created_utc", 0) or 0),
                    tz=dt.timezone.utc,
                ).astimezone(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")
                reddit_source = dict(source)
                reddit_source["name"] = f"Reddit · r/{subreddit}"
                snippet = clean_text(row.get("selftext", "")) or title
                article = make_article(
                    title,
                    "https://www.reddit.com" + permalink,
                    snippet,
                    reddit_source,
                    "community",
                    created,
                )
                article.update({
                    "community_origin": "reddit",
                    "community_name": f"r/{subreddit}",
                    "score": int(row.get("score", 0) or 0),
                    "comment_count": int(row.get("num_comments", 0) or 0),
                    "upvote_ratio": float(row.get("upvote_ratio", 0) or 0),
                    "has_image": bool(row.get("is_gallery"))
                    or str(row.get("post_hint", "")).lower() == "image"
                    or str(row.get("url_overridden_by_dest", "")).lower().endswith(
                        (".jpg", ".jpeg", ".png", ".gif", ".webp")
                    ),
                })
                found.append(article)
            articles.extend(found)
            logs.append(f"reddit oauth ok: {query} ({len(found)})")
            time.sleep(0.65)
        except Exception as exc:
            logs.append(f"reddit oauth skip: {query} ({type(exc).__name__})")
    return articles, logs


def collect_x(queries: list[str], source: dict) -> tuple[list[dict], list[str]]:
    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        return [], ["x skip: X_BEARER_TOKEN not set"]
    articles: list[dict] = []
    logs: list[str] = []
    headers = {"Authorization": f"Bearer {token}"}
    for query in queries[:6]:
        params = urllib.parse.urlencode({
            "query": query + " -is:retweet",
            "max_results": 10,
            "tweet.fields": "created_at,author_id,public_metrics",
        })
        url = source["endpoint"] + "?" + params
        try:
            data = request_json(url, headers=headers)
            rows = data.get("data", []) if isinstance(data, dict) else []
            for row in rows:
                tweet_id = row.get("id", "")
                link = f"https://x.com/i/web/status/{tweet_id}"
                text = row.get("text", "")
                articles.append(make_article(text[:110], link, text, source, "social", parse_date(row.get("created_at"))))
            logs.append(f"x ok: {query} ({len(rows)})")
        except Exception as exc:
            logs.append(f"x skip: {query} ({type(exc).__name__})")
    return articles, logs


def flatten_sources(config: dict) -> list[dict]:
    out: list[dict] = []
    for group in config.get("source_groups", []):
        for source in group.get("sources", []):
            copy = dict(source)
            copy["group"] = group.get("group")
            out.append(copy)
    return out


def is_relevant(article: dict) -> bool:
    haystack = f"{article.get('headline', '')} {article.get('body', '')}".lower()
    strong_terms = [
        "semiconductor", "semiconductors", "chip", "chips", "chiplet", "chiplets",
        "hbm", "dram", "nand", "cxl", "foundry", "fab", "wafer", "lithography",
        "euv", "high na", "cowos", "interposer", "hybrid bonding", "advanced packaging",
        "transistor", "gaa", "nanosheet", "2nm", "3nm", "asic", "npu", "tpu", "eda",
        "반도체", "파운드리", "패키징", "웨이퍼", "노광", "식각", "증착", "소자",
        "메모리", "고대역폭", "하이브리드 본딩",
    ]
    if any(keyword_matches(haystack, term) for term in strong_terms):
        return True
    return bool(article.get("matched_keywords"))


def is_community_article(article: dict) -> bool:
    return (
        article.get("category") in {"community", "rumor"}
        or article.get("raw_source_type") in {"community", "social"}
        or article.get("trust") == "low" and article.get("source_name", "").lower().startswith(("reddit", "hacker news"))
    )


def clamp_importance_score(value: object, default: int = 2) -> int:
    try:
        score = int(value)
    except Exception:
        score = default
    return max(1, min(5, score))


def fallback_importance_score(article: dict, source_text: str = "") -> int:
    text = f"{article.get('headline', '')} {article.get('body', '')} {source_text}".lower()
    score = 2
    tier5 = [
        "ai accelerator", "gpu", "npu", "tpu", "asic", "hbm", "hbm4", "hbm4e",
        "cowos", "advanced packaging", "hybrid bonding", "nvidia", "tsmc",
        "sk hynix", "samsung", "amd", "intel", "google", "microsoft", "meta",
        "apple", "ai chip", "blackwell", "rubin", "mi350", "mi400",
        "ai 가속기", "엔비디아", "빅테크", "협업", "파트너십", "공동 개발",
        "제휴", "동맹", "mou",
    ]
    tier4 = [
        "2nm", "gaa", "high-na", "high na", "euv", "nanosheet", "gate-all-around",
        "yield", "foundry", "acquisition", "merger", "export control",
        "supply chain", "메모리", "수율", "인수", "합병", "공급망",
    ]
    tier3 = [
        "semiconductor", "chiplet", "eda", "dram", "nand", "lithography",
        "interposer", "substrate", "packaging", "process", "fab",
    ]
    if any(term in text for term in tier5):
        score = max(score, 5)
    elif any(term in text for term in tier4):
        score = max(score, 4)
    elif any(term in text for term in tier3):
        score = max(score, 3)
    if article.get("trust") == "high" and score < 5:
        score += 1
    if article.get("category") in {"community", "rumor"} and score > 4:
        score = 4
    return clamp_importance_score(score)


def sort_by_importance(articles: list[dict], limit: int | None = None, assign_placement: bool = True) -> list[dict]:
    for article in articles:
        article["importance_score"] = clamp_importance_score(
            article.get("importance_score"),
            fallback_importance_score(article),
        )
    sorted_articles = sorted(
        articles,
        key=lambda a: (a.get("importance_score", 0), a.get("created_at", "")),
        reverse=True,
    )
    if limit is not None:
        sorted_articles = sorted_articles[:limit]
    if assign_placement:
        for i, article in enumerate(sorted_articles):
            article["placement"] = "top" if i == 0 else ("main" if i < 7 else "side")
    return sorted_articles


COMMUNITY_DESIGN_TERMS = [
    "asic", "gpu", "npu", "tpu", "soc", "chiplet", "risc-v", "risc v", "arm",
    "cuda", "architecture", "interconnect", "nvlink", "ucie", "cxl", "serdes",
    "eda", "rtl", "verilog", "vhdl", "ip core", "inference chip", "ai accelerator",
    "fabless", "custom silicon", "설계", "아키텍처", "가속기", "칩렛", "인터커넥트",
    "팹리스", "반도체 ip", "커스텀 실리콘", "추론칩",
]

COMMUNITY_FRONTIER_COMPANIES = [
    "nvidia", "엔비디아", "amd", "broadcom", "브로드컴", "qualcomm", "퀄컴",
    "arm", "tsmc", "삼성전자", "samsung foundry", "sk hynix", "sk하이닉스",
    "intel", "인텔", "micron", "마이크론", "asml", "synopsys", "시놉시스",
    "cadence", "케이던스", "cerebras", "세레브라스", "groq", "tenstorrent",
    "텐스토렌트", "sifive", "rapidus", "라피더스", "rebelions", "리벨리온",
    "furiosa", "퓨리오사", "deepx", "딥엑스",
]

COMMUNITY_FRONTIER_TECH_TERMS = [
    "hbm4", "hbm4e", "2nm", "1.4nm", "gaa", "nanosheet", "high na", "high-na",
    "euv", "cowos", "soic", "hybrid bonding", "silicon photonics", "cpo",
    "첨단 패키징", "하이브리드 본딩", "실리콘 포토닉스", "유리기판",
]

COMMUNITY_PHOTO_TITLE_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in [
        r"(?:^|[\[\(\s])사진(?:[\]\)\s]|$)",
        r"(?:^|[\[\(\s])포토(?:[\]\)\s]|$)",
        r"(?:^|[\[\(\s])짤(?:방)?(?:[\]\)\s]|$)",
        r"(?:^|[\[\(\s])움짤(?:[\]\)\s]|$)",
        r"(?:^|[\[\(\s])스샷(?:[\]\)\s]|$)",
        r"스크린\s*샷|사진\s*有|사진\s*있음|이미지\s*첨부|사진\s*첨부",
        r"\.(?:jpe?g|png|gif|webp)(?:\s|$)",
        r"(?:^|[\[\(\s])photo(?:s)?(?:[\]\)\s]|$)",
        r"(?:^|[\[\(\s])image(?:s)?(?:[\]\)\s]|$)",
    ]
]


def community_text(item: dict) -> str:
    return clean_text(f"{item.get('headline', '')} {item.get('body', '')}").lower()


def matching_community_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if keyword_matches(text, term)]


def community_photo_reason(item: dict) -> str:
    if item.get("has_image"):
        return "source image flag"
    title = clean_text(str(item.get("headline", "")))
    if any(pattern.search(title) for pattern in COMMUNITY_PHOTO_TITLE_PATTERNS):
        return "photo marker in title"
    url = str(item.get("source_url", "")).lower().split("?", 1)[0]
    if url.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return "image URL"
    if (urllib.parse.urlsplit(url).hostname or "").lower() in {"i.redd.it", "imgur.com", "i.imgur.com"}:
        return "image host"
    return ""


def exclude_photo_community_items(items: list[dict], logs: list[str]) -> list[dict]:
    kept: list[dict] = []
    excluded = 0
    for item in items:
        reason = community_photo_reason(item)
        if reason:
            excluded += 1
            continue
        kept.append(item)
    if excluded:
        logs.append(f"community photo filter: excluded {excluded} items")
    return kept


def fallback_community_topic(item: dict) -> str:
    topic = re.sub(r"^\s*[\[\(][^\]\)]{1,18}[\]\)]\s*", "", clean_text(item.get("headline", "")))
    return topic[:70].rstrip() or "반도체 업계 이슈"


def fallback_reaction_summary(item: dict) -> str:
    topic = item.get("topic") or fallback_community_topic(item)
    body = clean_text(item.get("body", ""))
    headline = clean_text(item.get("headline", ""))
    if not body or body == headline or re.fullmatch(r"https?://\S+", body):
        return f"{topic} 관련 정보 공유가 중심이며, 제공된 문구에서는 뚜렷한 찬반 반응이 확인되지 않았다."
    if len(body) > 150:
        body = body[:149].rstrip() + "..."
    return f"{topic}에 대해 게시글은 ‘{body}’라는 관점이나 정보를 공유했다."


def fallback_community_score(item: dict) -> tuple[int, list[str]]:
    text = community_text(item)
    headline_text = clean_text(item.get("headline", "")).lower()
    design = matching_community_terms(text, COMMUNITY_DESIGN_TERMS)
    companies = matching_community_terms(text, COMMUNITY_FRONTIER_COMPANIES)
    frontier_tech = matching_community_terms(text, COMMUNITY_FRONTIER_TECH_TERMS)
    headline_design = matching_community_terms(headline_text, COMMUNITY_DESIGN_TERMS)
    headline_companies = matching_community_terms(headline_text, COMMUNITY_FRONTIER_COMPANIES)
    reasons: list[str] = []
    score = 2
    if headline_design or design:
        score = max(score, 4)
        reasons.append("설계 주제")
    if headline_companies or companies:
        score = max(score, 4)
        reasons.append("프론티어 기업")
    if headline_design and headline_companies:
        score = 5
    elif frontier_tech:
        score = max(score, 3)
        reasons.append("첨단 기술")

    body = clean_text(item.get("body", ""))
    headline = clean_text(item.get("headline", ""))
    if body and body != headline and len(body) >= 50 and score < 4:
        score += 1
        reasons.append("구체적 논점")
    engagement = int(item.get("comment_count", 0) or 0) + int(item.get("score", 0) or 0)
    if engagement >= 20 and score < 4:
        score += 1
        reasons.append("활발한 반응")
    return clamp_importance_score(score), reasons[:3]


def community_source_family(item: dict) -> str:
    source = str(item.get("source_name", "")).lower()
    if source.startswith("naver cafe"):
        return "naver_cafe"
    if source.startswith("dcinside"):
        return "dcinside"
    if source.startswith("clien"):
        return "clien"
    if source.startswith("fmkorea"):
        return "fmkorea"
    if source.startswith("reddit"):
        return "reddit"
    if source.startswith("hacker news"):
        return "hacker_news"
    return source or "other"


def rank_community_items(
    items: list[dict],
    limit: int = MAX_COMMUNITY_ITEMS,
    source_cap: int | None = None,
) -> list[dict]:
    for item in items:
        fallback_score, reasons = fallback_community_score(item)
        item["community_score"] = clamp_importance_score(item.get("community_score"), fallback_score)
        item["priority_reasons"] = item.get("priority_reasons") or reasons
        item["topic"] = item.get("topic") or fallback_community_topic(item)
        item["reaction_summary"] = item.get("reaction_summary") or fallback_reaction_summary(item)
        item.pop("importance_score", None)
        item.pop("importance", None)
        item.pop("placement", None)

    ordered = sorted(
        items,
        key=lambda item: (
            int(item.get("community_score", 0) or 0),
            int(item.get("comment_count", 0) or 0) + int(item.get("score", 0) or 0),
            item.get("created_at", ""),
        ),
        reverse=True,
    )
    source_cap = source_cap if source_cap is not None else max(1, (limit * 2 + 4) // 5)
    selected: list[dict] = []
    selected_ids: set[str] = set()
    family_counts: dict[str, int] = {}
    for item in ordered:
        family = community_source_family(item)
        if family_counts.get(family, 0) >= source_cap:
            continue
        selected.append(item)
        selected_ids.add(str(item.get("id", "")))
        family_counts[family] = family_counts.get(family, 0) + 1
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        for item in ordered:
            if str(item.get("id", "")) in selected_ids:
                continue
            selected.append(item)
            if len(selected) >= limit:
                break
    for rank, item in enumerate(selected, 1):
        item["community_rank"] = rank
    return selected


def prepare_community_items(items: list[dict], limit: int | None = None) -> list[dict]:
    """Backward-compatible entry point for ranked community preparation."""
    return rank_community_items(items, limit or len(items) or MAX_COMMUNITY_ITEMS)


def enrich_community_reactions(items: list[dict], logs: list[str]) -> tuple[list[dict], str]:
    items = exclude_photo_community_items(items, logs)
    items = rank_community_items(
        items,
        max(MAX_COMMUNITY_ITEMS, COMMUNITY_CANDIDATE_LIMIT),
        source_cap=max(4, COMMUNITY_CANDIDATE_LIMIT * 2 // 5),
    )
    if not items:
        return items, ""

    def finalize(rows: list[dict], summary: str = "") -> tuple[list[dict], str]:
        rows = [item for item in rows if not item.get("llm_image_post")]
        rows = rank_community_items(rows, MAX_COMMUNITY_ITEMS, source_cap=4)
        fallback_lines = [
            f"{item.get('topic')}: {item.get('reaction_summary')}"
            for item in rows[:3]
            if item.get("reaction_summary")
        ]
        return rows, summary or "\n".join(fallback_lines)

    if not llm_is_configured():
        return finalize(items)

    prompt_items = [
        {
            "id": item.get("id", ""),
            "title": item.get("headline", ""),
            "source": item.get("source_name", ""),
            "snippet": item.get("body", ""),
            "url": item.get("source_url", ""),
            "initial_score": item.get("community_score", 0),
            "priority_reasons": item.get("priority_reasons", []),
            "has_image": bool(item.get("has_image")),
        }
        for item in items
    ]
    instruction = (
        "Return JSON only. Evaluate semiconductor community posts using only the supplied title and snippet. "
        "A post is not a comment corpus: summarize the viewpoint or tone expressed by the post, and never claim "
        "community consensus. If it only shares a link or information without a stance, explicitly say in Korean "
        "that it is information-sharing and no clear positive/negative reaction is visible. Do not state rumors as facts. "
        "Set is_image_post=true when the metadata strongly indicates a photo, screenshot, image, meme, or gallery post; "
        "such an item must not affect the summary. Write topic in concise Korean and reaction_summary as one concrete "
        "Korean sentence explaining what reaction is shown toward that topic. Score 1-5: 5 only when both chip design "
        "and a frontier semiconductor company are central to the post rather than passing mentions; 4 for either chip "
        "design or a frontier semiconductor company; "
        "3 for frontier process, memory, or packaging; 2 for ordinary semiconductor discussion; 1 for low-information, "
        "promotional, or image-centric content. Frontier companies include NVIDIA, AMD, Broadcom, Qualcomm, Arm, TSMC, "
        "Samsung Electronics, SK hynix, Intel, Micron, ASML, Synopsys, Cadence, Cerebras, Groq, Tenstorrent, SiFive, "
        "Rapidus, Rebellions, FuriosaAI, and DeepX. community_summary_lines must contain 2-3 Korean lines describing "
        "the dominant high-ranked topics and the reactions shown, excluding image posts. "
        "Schema: {\"community_summary_lines\":[\"...\"],\"items\":[{\"id\":\"...\",\"topic\":\"...\","
        "\"reaction_summary\":\"...\",\"community_score\":5,\"is_image_post\":false}]}"
    )
    is_native_gemini = "generativelanguage.googleapis.com" in LLM_BASE_URL and "gemma" in LLM_MODEL.lower()

    try:
        current_key = get_current_llm_key()
        headers: dict[str, str] = {}
        user_text = instruction + "\n\n" + json.dumps(prompt_items, ensure_ascii=False)
        if is_native_gemini:
            base_path = LLM_BASE_URL.split("/openai")[0]
            endpoint = f"{base_path}/models/{LLM_MODEL}:generateContent?key={current_key}"
            payload = {
                "contents": [{"role": "user", "parts": [{"text": user_text}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 4000,
                    "responseMimeType": "application/json",
                },
            }
        else:
            endpoint = LLM_BASE_URL + "/chat/completions"
            if current_key:
                headers["Authorization"] = f"Bearer {current_key}"
            payload = {
                "model": LLM_MODEL,
                "temperature": 0.2,
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": user_text}],
            }
        data = post_json(endpoint, payload, headers=headers, timeout=LLM_TIMEOUT)
        if is_native_gemini:
            parts = data["candidates"][0]["content"]["parts"]
            content = "".join([p["text"] for p in parts if not p.get("thought")])
        else:
            content = data["choices"][0]["message"]["content"]
        parsed = parse_llm_json(content)
        by_id = {
            str(row.get("id")): row
            for row in parsed.get("items", [])
            if isinstance(row, dict) and row.get("id")
        }
        for item in items:
            row = by_id.get(str(item.get("id", "")), {})
            topic = clean_text(str(row.get("topic", "")))
            summary = clean_text(str(row.get("reaction_summary", "")))
            if topic:
                item["topic"] = topic[:90]
            if summary:
                item["reaction_summary"] = summary
            if row.get("community_score") is not None:
                item["community_score"] = clamp_importance_score(
                    row.get("community_score"),
                    int(item.get("community_score", 2) or 2),
                )
            item["llm_image_post"] = row.get("is_image_post") is True
        summary_lines = parsed.get("community_summary_lines", [])
        if isinstance(summary_lines, list):
            sentiment = "\n".join(clean_text(str(line)) for line in summary_lines if clean_text(str(line)))
        else:
            sentiment = clean_text(str(summary_lines))
        return finalize(items, sentiment)
    except Exception as exc:
        logs.append(f"community reaction summary skip: {type(exc).__name__}")
        return finalize(items)


def briefing_window(now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    kst = dt.timezone(dt.timedelta(hours=9))
    now = (now or dt.datetime.now(kst)).astimezone(kst)
    window_end = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if now < window_end:
        window_end -= dt.timedelta(days=1)
    return window_end - dt.timedelta(days=1), window_end


def recent_archived_community_urls(days: int = 7) -> set[str]:
    """Return URLs from earlier daily snapshots, excluding today's rerunnable snapshot."""
    kst = dt.timezone(dt.timedelta(hours=9))
    today = dt.datetime.now(kst).date()
    cutoff = today - dt.timedelta(days=days)
    seen: set[str] = set()
    for path in ARCHIVE_DIR.glob("*.json"):
        try:
            archive_date = dt.date.fromisoformat(path.stem)
        except ValueError:
            continue
        if not (cutoff <= archive_date < today):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in payload.get("community_items", []):
            url = canonical_url(str(item.get("source_url", "")))
            if url:
                seen.add(url)
    return seen


def suppress_seen_estimated_community(items: list[dict], logs: list[str]) -> list[dict]:
    seen = recent_archived_community_urls()
    if not seen:
        return items
    kept: list[dict] = []
    skipped = 0
    for item in items:
        url = canonical_url(str(item.get("source_url", "")))
        if item.get("date_is_estimated") and url in seen:
            skipped += 1
            continue
        kept.append(item)
    if skipped:
        logs.append(f"community history dedupe: skipped {skipped} estimated-date items seen in prior 7 days")
    return kept


def dedupe_rank(articles: list[dict], limit: int | None = MAX_ITEMS) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    kst = dt.timezone(dt.timedelta(hours=9))
    window_start, window_end = briefing_window()
    
    for article in articles:
        url = article.get("source_url") or ""
        key = canonical_url(url) or clean_text(article.get("headline", "")).lower()
        if key in seen or not article.get("headline") or not url:
            continue
        seen.add(key)
        
        # Keep only articles in the latest Seoul 07:00-to-07:00 briefing window.
        # Some official search APIs omit publication timestamps. Those items
        # use collection time and are deduplicated against recent archives.
        if not article.get("date_is_estimated"):
            try:
                created_at = dt.datetime.fromisoformat(article["created_at"].replace("Z", "+00:00"))
                created_at = created_at.astimezone(kst)
                if not (window_start <= created_at < window_end):
                    continue
            except Exception:
                pass
            
        if is_relevant(article):
            unique.append(article)
            
    trust_score = {"high": 3, "medium": 2, "low": 1}
    category_score = {"news": 3, "technology": 3, "analysis": 2, "community": 1, "rumor": 0}
    unique.sort(key=lambda a: (
        trust_score.get(a.get("trust"), 0),
        category_score.get(a.get("category"), 0),
        a.get("created_at", ""),
    ), reverse=True)
    selected = unique if limit is None else unique[:limit]
    for i, article in enumerate(selected):
        article["placement"] = "top" if i == 0 else ("main" if i < 7 else "side")
    return selected


def llm_is_configured() -> bool:
    return bool(LLM_BASE_URL and LLM_MODEL)


def summarize_with_llm(article: dict, source_text: str) -> tuple[str, str | None, list[str] | None, int | None]:
    system_prompt = (
        "너는 반도체 뉴스 팩트 에디터다. 독자는 평가나 배경 설명이 아니라 새로 나온 사실을 원한다. "
        "요약은 기사에서 확인되는 핵심 사실, 새 발표/변경점, 기술 세부사항, 수치, 기업명, 제품명, 공정명, 일정, 적용 대상을 중심으로 쓴다. "
        "'반도체의 중요성이 커지고 있습니다', '경쟁이 치열해지고 있습니다', '주목됩니다', '의미가 있습니다' 같은 범용 평가 문장은 금지한다. "
        "원문에 없는 전망, 투자 조언, 과장 표현은 쓰지 않는다. 원문을 베껴 쓰지 말고 한국어로 압축한다. "
        "반드시 JSON만 출력한다. summary_lines는 3~5개의 문자열 배열이며 각 줄은 서로 다른 핵심 사실을 담는다. "
        "sector는 설계, 공정, 소자, 패키징 중 하나다."
    )
    system_prompt = EDITORIAL_PRIORITY_PROMPT + "\n\n" + system_prompt
    prompt = {
        "title": article.get("headline", ""),
        "source": article.get("source_name", ""),
        "url": article.get("source_url", ""),
        "current_sector": article.get("sector", ""),
        "text": source_text[:6500],
    }
    user_prompt = (
        "다음 뉴스 후보를 칩 브리핑용으로 요약해줘.\n"
        "작성 규칙:\n"
        "- 3~5줄, 각 줄은 가능한 한 구체적인 팩트로 시작\n"
        "- 무엇이 새로 발표/공개/변경/출하/투자/지원됐는지 먼저 말하기\n"
        "- 기술명, 노드, 세대, 용량, 속도, 수율, 장비, 패키징 방식, 고객/적용처가 있으면 포함\n"
        "- 배경 평가나 산업 일반론은 제외\n"
        "- 기사에 근거가 약하면 '확인된 내용은 ...'처럼 제한적으로 쓰기\n"
        "JSON 형식: {\"summary_lines\":[\"팩트 중심 요약 1줄\",\"팩트 중심 요약 1줄\",\"팩트 중심 요약 1줄\"], "
        "\"sector\":\"설계|공정|소자|패키징\", "
        "\"keywords\":[\"핵심어1\",\"핵심어2\"]}\n\n"
        + json.dumps(prompt, ensure_ascii=False)
    )

    is_native_gemini = "generativelanguage.googleapis.com" in LLM_BASE_URL and "gemma" in LLM_MODEL.lower()
    
    max_attempts = max(1, len(LLM_API_KEYS))
    for attempt in range(max_attempts):
        headers: dict[str, str] = {}
        current_key = get_current_llm_key()
        
        if is_native_gemini:
            base_path = LLM_BASE_URL.split("/openai")[0]
            endpoint = f"{base_path}/models/{LLM_MODEL}:generateContent?key={current_key}"
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": user_prompt}]
                    }
                ],
                "systemInstruction": {
                    "parts": [{"text": system_prompt}]
                },
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 2048,
                    "responseMimeType": "application/json"
                }
            }
        else:
            endpoint = LLM_BASE_URL + "/chat/completions"
            if current_key:
                headers["Authorization"] = f"Bearer {current_key}"
            payload = {
                "model": LLM_MODEL,
                "temperature": 0.2,
                "max_tokens": 2048,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            }
            
        try:
            data = post_json(endpoint, payload, headers=headers, timeout=LLM_TIMEOUT)
            
            if is_native_gemini:
                parts = data["candidates"][0]["content"]["parts"]
                content = "".join([p["text"] for p in parts if not p.get("thought")])
            else:
                content = data["choices"][0]["message"]["content"]
                
            parsed = parse_llm_json(content)
            lines = parsed.get("summary_lines")
            if isinstance(lines, list):
                summary_lines = [clean_text(str(line)) for line in lines if clean_text(str(line))]
            else:
                raw_summary = str(parsed.get("summary", ""))
                summary_lines = [clean_text(line) for line in raw_summary.splitlines() if clean_text(line)]
                if not summary_lines and raw_summary:
                    summary_lines = [clean_text(raw_summary)]
            summary = "\n".join(summary_lines[:5])
            sector = parsed.get("sector")
            keywords = parsed.get("keywords")
            if sector not in {"설계", "공정", "소자", "패키징"}:
                sector = None
            if not isinstance(keywords, list):
                keywords = None
            keywords = [clean_text(str(k)) for k in keywords or [] if clean_text(str(k))][:6]
            importance_score = parsed.get("importance_score")
            if importance_score is None:
                importance_score = parsed.get("importance")
            return summary, sector, keywords, clamp_importance_score(importance_score) if importance_score is not None else None
        except Exception as exc:
            is_429 = False
            if hasattr(exc, "code") and exc.code == 429:
                is_429 = True
            elif "429" in str(exc):
                is_429 = True
                
            if is_429 and len(LLM_API_KEYS) > 1 and attempt < max_attempts - 1:
                print(f"LLM API key slot {attempt + 1} hit quota; rotating to the next configured key...")
                rotate_llm_key()
                time.sleep(1.0)
                continue
            raise


def parse_llm_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        return json.loads(content)
    except Exception:
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            return json.loads(match.group(0))
    return {}


def enrich_with_llm_summaries(articles: list[dict], logs: list[str]) -> list[dict]:
    if not llm_is_configured():
        logs.append("llm skip: CHIP_BRIEFING_LLM_BASE_URL/CHIP_BRIEFING_LLM_MODEL not set")
        for article in articles:
            article["importance_score"] = fallback_importance_score(article)
        return articles

    # Load cache of previous summaries from articles.json
    cache = {}
    if ARTICLES_PATH.exists():
        try:
            prev_data = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
            for art in prev_data.get("articles", []):
                if art.get("id") and art.get("summary_method") == "llm":
                    cache[art["id"]] = {
                        "body": art.get("body"),
                        "sector": art.get("sector"),
                        "llm_keywords": art.get("llm_keywords"),
                        "summary_model": art.get("summary_model"),
                        "importance_score": art.get("importance_score"),
                    }
            logs.append(f"cache load: loaded {len(cache)} existing summaries from articles.json")
        except Exception as exc:
            logs.append(f"cache load failed: {type(exc).__name__}: {exc}")

    enriched = 0
    cache_hits = 0
    total_to_process = len(articles[:LLM_MAX_ITEMS])
    for i, article in enumerate(articles[:LLM_MAX_ITEMS]):
        art_id = article.get("id")
        if art_id in cache:
            article["body"] = cache[art_id]["body"]
            article["summary_method"] = "llm"
            article["summary_model"] = cache[art_id]["summary_model"]
            if cache[art_id].get("sector"):
                article["sector"] = cache[art_id]["sector"]
            if cache[art_id].get("llm_keywords"):
                article["llm_keywords"] = cache[art_id]["llm_keywords"]
            article["importance_score"] = clamp_importance_score(
                cache[art_id].get("importance_score"),
                fallback_importance_score(article),
            )
            cache_hits += 1
            continue

        try:
            print(f"[{i+1}/{total_to_process}] 요약 중: {article.get('headline', '')[:55]}...", flush=True)
        except UnicodeEncodeError:
            try:
                safe_headline = article.get('headline', '')[:55].encode('ascii', errors='replace').decode('ascii')
                print(f"[{i+1}/{total_to_process}] 요약 중: {safe_headline}...", flush=True)
            except Exception:
                print(f"[{i+1}/{total_to_process}] 요약 중: (인코딩 에러 발생 기사)...", flush=True)
        source_text = extract_article_text(article.get("source_url", ""))
        if len(source_text) < 300:
            source_text = f"{article.get('headline', '')}\n\n{article.get('body', '')}"
        try:
            summary, sector, keywords, importance_score = summarize_with_llm(article, source_text)
            if summary:
                article["body"] = summary
                article["summary_method"] = "llm"
                article["summary_model"] = LLM_MODEL
                article["importance_score"] = clamp_importance_score(
                    importance_score,
                    fallback_importance_score(article, source_text),
                )
                if sector:
                    article["sector"] = sector
                if keywords:
                    article["llm_keywords"] = keywords
                enriched += 1
                time.sleep(4.0)
            else:
                article["summary_method"] = "snippet"
                article["importance_score"] = fallback_importance_score(article, source_text)
        except Exception as exc:
            article["summary_method"] = "snippet"
            article["importance_score"] = fallback_importance_score(article)
            err_msg = f"{type(exc).__name__}: {exc}"
            if hasattr(exc, "read"):
                try:
                    err_msg += f" - {exc.read().decode('utf-8', errors='replace')}"
                except Exception:
                    pass
            logs.append(f"llm skip article: {article.get('headline', '')[:60]} ({type(exc).__name__})")
            print(f"Error summarizing: {err_msg}", flush=True)
    for article in articles:
        if not article.get("importance_score"):
            article["importance_score"] = fallback_importance_score(article)
    logs.append(f"llm ok: summarized {enriched} articles, reused {cache_hits} cached summaries (total {min(len(articles), LLM_MAX_ITEMS)})")
    return articles


def select_daily_summary_items(items: list[dict], limit: int = DAILY_SUMMARY_MAX_ITEMS) -> list[dict]:
    """Return the canonical Daily Summary ranking used by JSON and every UI."""
    return sorted(
        items,
        key=lambda item: (
            clamp_importance_score(item.get("importance_score"), 1),
            item.get("created_at", ""),
        ),
        reverse=True,
    )[:limit]


def generate_collection_summary(items: list[dict], logs: list[str], kind: str) -> str:
    selected = select_daily_summary_items(items) if kind == "daily" else items[:DAILY_SUMMARY_MAX_ITEMS]
    if not selected:
        return ""

    fallback = " / ".join(clean_text(item.get("headline", "")) for item in selected if item.get("headline"))
    if not llm_is_configured():
        return fallback

    if kind == "community":
        instruction = (
            "Summarize today's semiconductor community sentiment in Korean in 2-3 concise lines. "
            "Focus on recurring topics, positive/negative/concern trends, and engineer or public reactions. "
            "Do not present community rumors as confirmed facts."
        )
    else:
        instruction = (
            "The input contains exactly the highest-importance semiconductor articles for today's briefing, "
            "ordered by importance_score and recency. Summarize all selected articles in Korean in 4-5 concise lines. "
            "Group overlapping stories, but do not omit a distinct topic. Lead with score-5 items and concrete facts."
        )

    prompt_items = [
        {
            "rank": rank,
            "title": item.get("headline", ""),
            "source": item.get("source_name", ""),
            "importance_score": item.get("importance_score", 0),
            "summary": item.get("body", ""),
        }
        for rank, item in enumerate(selected, 1)
    ]
    is_native_gemini = "generativelanguage.googleapis.com" in LLM_BASE_URL and "gemma" in LLM_MODEL.lower()

    try:
        current_key = get_current_llm_key()
        headers: dict[str, str] = {}
        user_text = instruction + "\n\n" + json.dumps(prompt_items, ensure_ascii=False)
        if is_native_gemini:
            base_path = LLM_BASE_URL.split("/openai")[0]
            endpoint = f"{base_path}/models/{LLM_MODEL}:generateContent?key={current_key}"
            payload = {
                "contents": [{"role": "user", "parts": [{"text": user_text}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700},
            }
        else:
            endpoint = LLM_BASE_URL + "/chat/completions"
            if current_key:
                headers["Authorization"] = f"Bearer {current_key}"
            payload = {
                "model": LLM_MODEL,
                "temperature": 0.2,
                "max_tokens": 700,
                "messages": [{"role": "user", "content": user_text}],
            }
        data = post_json(endpoint, payload, headers=headers, timeout=LLM_TIMEOUT)
        if is_native_gemini:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join([p["text"] for p in parts if not p.get("thought")])
        else:
            text = data["choices"][0]["message"]["content"]
        text = clean_text(text)
        return text or fallback
    except Exception as exc:
        logs.append(f"{kind} summary skip: {type(exc).__name__}")
        return fallback


def write_articles(
    articles: list[dict],
    logs: list[str],
    community_items: list[dict] | None = None,
    daily_summary: str = "",
    community_sentiment: str = "",
) -> None:
    summary_methods = sorted({a.get("summary_method", "snippet") for a in articles})
    community_items = community_items or []
    daily_summary_items = select_daily_summary_items(articles)
    payload = {
        "schema_version": 7,
        "generated_at": now_iso(),
        "daily_summary": daily_summary,
        "daily_summary_article_ids": [item.get("id", "") for item in daily_summary_items],
        "community_summary": community_sentiment,
        "community_sentiment": community_sentiment,
        "community_top10_ids": [item.get("id", "") for item in community_items[:MAX_COMMUNITY_ITEMS]],
        "briefing_title": "칩 브리핑",
        "sectors": ["설계", "공정", "소자", "패키징"],
        "collector": {
            "name": "collect_news.py",
            "source_count": len(articles),
            "community_count": len(community_items),
            "notes": "Metadata/link collection only; article full text is not stored. LLM summaries are generated transiently when configured.",
            "summary_methods": summary_methods,
            "summary_model": LLM_MODEL if llm_is_configured() else "",
            "logs": logs[-80:],
        },
        "articles": articles,
        "community_items": community_items,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    ARTICLES_PATH.write_text(text + "\n", encoding="utf-8")
    write_archive_snapshot(payload)


def write_archive_snapshot(payload: dict) -> None:
    ARCHIVE_DIR.mkdir(exist_ok=True)
    try:
        generated = dt.datetime.fromisoformat(str(payload.get("generated_at", "")).replace("Z", "+00:00"))
    except Exception:
        generated = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    date_key = generated.astimezone(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d")
    snapshot_path = ARCHIVE_DIR / f"{date_key}.json"
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    entry = {
        "date": date_key,
        "generated_at": payload.get("generated_at", ""),
        "file": f"archive/{date_key}.json",
        "article_count": len(payload.get("articles", [])),
        "top_headline": (payload.get("articles") or [{}])[0].get("headline", ""),
    }
    if ARCHIVE_INDEX_PATH.exists():
        try:
            index = json.loads(ARCHIVE_INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            index = {"items": []}
    else:
        index = {"items": []}
    items = [item for item in index.get("items", []) if item.get("date") != date_key]
    items.append(entry)
    items.sort(key=lambda item: item.get("date", ""), reverse=True)
    ARCHIVE_INDEX_PATH.write_text(
        json.dumps({"updated_at": payload.get("generated_at", ""), "items": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    config = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    global _SECTOR_KEYWORDS
    _SECTOR_KEYWORDS = config.get("sector_keywords", {})
    sources = flatten_sources(config)
    ko_queries = config.get("queries", {}).get("ko", [])
    en_queries = config.get("queries", {}).get("en", [])

    all_articles: list[dict] = []
    logs: list[str] = []

    rss_sources = [s for s in sources if s.get("group") in {"official", "specialized_media"}]
    found, new_logs = collect_rss(rss_sources)
    all_articles.extend(found)
    logs.extend(new_logs)

    found, new_logs = collect_google_news()
    all_articles.extend(found)
    logs.extend(new_logs)

    naver_sources = [s for s in sources if s.get("group") == "korean_search"]
    found, new_logs = collect_naver(naver_sources, ko_queries)
    all_articles.extend(found)
    logs.extend(new_logs)

    social_sources = {s.get("name"): s for s in sources if s.get("group") == "social_community"}
    if "DCInside" in social_sources:
        found, new_logs = collect_dcinside(COMMUNITY_SEARCH_QUERIES, social_sources["DCInside"])
        all_articles.extend(found)
        logs.extend(new_logs)
    if "Clien" in social_sources:
        found, new_logs = collect_clien(social_sources["Clien"])
        all_articles.extend(found)
        logs.extend(new_logs)
    naver_web_sources = [
        source for source in social_sources.values()
        if source.get("collection_method") == "naver_web_search"
    ]
    if naver_web_sources:
        found, new_logs = collect_naver_web_communities(naver_web_sources, COMMUNITY_SEARCH_QUERIES)
        all_articles.extend(found)
        logs.extend(new_logs)
    if "Hacker News Algolia" in social_sources:
        found, new_logs = collect_hn(en_queries, social_sources["Hacker News Algolia"])
        all_articles.extend(found)
        logs.extend(new_logs)
    if "Reddit" in social_sources:
        found, new_logs = collect_reddit(en_queries, social_sources["Reddit"])
        all_articles.extend(found)
        logs.extend(new_logs)
    logs.append("x skip: disabled by configuration; Reddit-only community mode")

    news_candidates = [article for article in all_articles if not is_community_article(article)]
    community_candidates = [article for article in all_articles if is_community_article(article)]
    community_candidates = suppress_seen_estimated_community(community_candidates, logs)

    ranked = dedupe_rank(news_candidates)
    community_items = dedupe_rank(community_candidates, limit=None)
    if not ranked:
        print("No relevant articles collected; articles.json not changed.", file=sys.stderr)
        for line in logs:
            print(line, file=sys.stderr)
        return 2
    ranked = enrich_with_llm_summaries(ranked, logs)
    ranked = sort_by_importance(ranked, MAX_ITEMS, assign_placement=True)
    community_items, community_sentiment = enrich_community_reactions(community_items, logs)
    logs.append(
        "community top 10: "
        + ", ".join(
            f"{item.get('community_rank')}:{item.get('community_score')}:{community_source_family(item)}"
            for item in community_items
        )
    )
    daily_summary = generate_collection_summary(ranked, logs, "daily")
    write_articles(ranked, logs, community_items, daily_summary, community_sentiment)
    print(f"Wrote {len(ranked)} articles to {ARTICLES_PATH}")
    print(f"Wrote archive snapshot to {ARCHIVE_DIR}")
    for line in logs[-20:]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

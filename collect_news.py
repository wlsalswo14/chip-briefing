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
from pathlib import Path
import socket

ROOT = Path(__file__).resolve().parent
SOURCES_PATH = ROOT / "sources.json"
ARTICLES_PATH = ROOT / "articles.json"
INDEX_PATH = ROOT / "index.html"
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

USER_AGENT = "ChipBriefingCollector/1.0 (+local personal briefing)"
TIMEOUT = int(os.environ.get("CHIP_BRIEFING_TIMEOUT", "15"))
socket.setdefaulttimeout(TIMEOUT)

MAX_ITEMS = int(os.environ.get("CHIP_BRIEFING_MAX_ITEMS", "100"))
MAX_JOBS = int(os.environ.get("CHIP_BRIEFING_MAX_JOBS", "24"))
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

JOB_KEYWORDS = [
    "semiconductor", "silicon", "asic", "soc", "rtl", "verification", "physical design",
    "sta", "dfx", "dfm", "eda", "compiler", "firmware", "gpu", "accelerator", "npu",
    "chiplet", "packaging", "substrate", "interposer", "hbm", "dram", "memory",
    "fabrication", "process", "yield", "device", "layout", "vlsi", "pcie", "serdes",
    "hardware", "fpga", "architecture",
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
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")
    except Exception:
        return now_iso()


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
                    articles.append(make_article(item.get("title", ""), link, snippet, source, "api", parse_date(item.get("pubDate"))))
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


def collect_reddit(queries: list[str], source: dict) -> tuple[list[dict], list[str]]:
    articles: list[dict] = []
    logs: list[str] = []
    
    # Browser-like User-Agent to avoid Reddit blocking python urllib
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    headers = {"User-Agent": user_agent}
    
    search_targets = ["all", "r/hardware", "r/semiconductors", "r/chipdesign"]
    compact_queries = [
        "HBM OR HBM4 OR HBM4E",
        "CoWoS OR advanced packaging OR hybrid bonding",
        "High NA EUV OR GAA OR nanosheet OR 2nm",
        "AI accelerator OR ASIC OR GPU OR NPU",
        "semiconductor foundry TSMC Samsung ASML",
    ]
    
    for target in search_targets:
        for query in compact_queries:
            params = urllib.parse.urlencode({
                "q": query,
                "sort": "new",
                "restrict_sr": "true" if target != "all" else "false",
                "t": "week"
            })
            url = f"https://www.reddit.com/{target}/search.rss?{params}"
            try:
                xml_text = request_text(url, headers=headers)
                found = parse_feed(xml_text, source, url)
                for article in found:
                    article["source_name"] = f"Reddit · {target}"
                    article["category"] = "community"
                    article["trust"] = "low"
                articles.extend(found)
                logs.append(f"reddit rss ok: {target} {query} ({len(found)})")
                time.sleep(0.3)
            except Exception as exc:
                logs.append(f"reddit rss skip: {target} {query} ({type(exc).__name__})")
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


def make_job(
    company: str,
    title: str,
    url: str,
    location: str,
    department: str,
    source_name: str,
    source_type: str,
    created_at: str | None = None,
) -> dict:
    text = f"{title} {department} {location}"
    sector, matched = classify_sector(text)
    return {
        "id": stable_id(url, f"{company}:{title}:{location}"),
        "company": clean_text(company),
        "title": clean_text(title),
        "location": clean_text(location),
        "department": clean_text(department),
        "sector": sector,
        "matched_keywords": matched,
        "created_at": created_at or now_iso(),
        "source_name": source_name,
        "source_url": canonical_url(url),
        "source_type": source_type,
    }


def is_relevant_job(job: dict) -> bool:
    haystack = f"{job.get('company','')} {job.get('title','')} {job.get('department','')} {job.get('location','')}".lower()
    if any(keyword_matches(haystack, kw) for kw in JOB_KEYWORDS):
        return True
    return bool(job.get("matched_keywords"))


def collect_greenhouse_jobs(source: dict) -> tuple[list[dict], str]:
    board = source["board"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=false"
    data = request_json(url)
    jobs = []
    for item in data.get("jobs", []):
        offices = item.get("offices") or []
        departments = item.get("departments") or []
        location = item.get("location", {}).get("name", "")
        if not location and offices:
            location = ", ".join(o.get("name", "") for o in offices if o.get("name"))
        department = ", ".join(d.get("name", "") for d in departments if d.get("name"))
        jobs.append(make_job(
            source["company"],
            item.get("title", ""),
            item.get("absolute_url", ""),
            location,
            department,
            source.get("name", source["company"]),
            "greenhouse",
            parse_date(item.get("updated_at")),
        ))
    return jobs, f"jobs greenhouse ok: {source['company']} ({len(jobs)})"


def collect_ashby_jobs(source: dict) -> tuple[list[dict], str]:
    board = source["board"]
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    data = request_json(url)
    jobs = []
    for item in data.get("jobs", []):
        location = item.get("locationName") or ""
        department = item.get("department") or ""
        jobs.append(make_job(
            source["company"],
            item.get("title", ""),
            item.get("jobUrl") or item.get("applyUrl") or "",
            location,
            department,
            source.get("name", source["company"]),
            "ashby",
            parse_date(item.get("publishedAt")),
        ))
    return jobs, f"jobs ashby ok: {source['company']} ({len(jobs)})"


def collect_lever_jobs(source: dict) -> tuple[list[dict], str]:
    board = source["board"]
    url = f"https://api.lever.co/v0/postings/{board}?mode=json"
    data = request_json(url)
    jobs = []
    for item in data if isinstance(data, list) else []:
        categories = item.get("categories") or {}
        location = categories.get("location", "")
        department = categories.get("team", "") or categories.get("department", "")
        jobs.append(make_job(
            source["company"],
            item.get("text", ""),
            item.get("hostedUrl") or item.get("applyUrl") or "",
            location,
            department,
            source.get("name", source["company"]),
            "lever",
            parse_date(item.get("createdAt")),
        ))
    return jobs, f"jobs lever ok: {source['company']} ({len(jobs)})"


def collect_jobs(config: dict) -> tuple[list[dict], list[str]]:
    job_sources = config.get("job_sources", [])
    jobs: list[dict] = []
    logs: list[str] = []
    for source in job_sources:
        try:
            if source.get("provider") == "greenhouse":
                found, msg = collect_greenhouse_jobs(source)
            elif source.get("provider") == "ashby":
                found, msg = collect_ashby_jobs(source)
            elif source.get("provider") == "lever":
                found, msg = collect_lever_jobs(source)
            else:
                logs.append(f"jobs skip: unknown provider {source.get('provider')} {source.get('company')}")
                continue
            jobs.extend(found)
            logs.append(msg)
            time.sleep(0.15)
        except Exception as exc:
            logs.append(f"jobs skip: {source.get('company')} ({type(exc).__name__})")

    seen: set[str] = set()
    unique: list[dict] = []
    for job in jobs:
        key = job.get("source_url") or f"{job.get('company')}:{job.get('title')}:{job.get('location')}"
        if not key or key in seen:
            continue
        seen.add(key)
        if is_relevant_job(job):
            unique.append(job)
    unique.sort(key=lambda j: (j.get("created_at", ""), j.get("company", "")), reverse=True)
    return unique[:MAX_JOBS], logs


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


def dedupe_rank(articles: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    kst = dt.timezone(dt.timedelta(hours=9))
    now = dt.datetime.now(kst)
    window_end = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if now < window_end:
        window_end -= dt.timedelta(days=1)
    window_start = window_end - dt.timedelta(days=1)
    
    for article in articles:
        url = article.get("source_url") or ""
        key = canonical_url(url) or clean_text(article.get("headline", "")).lower()
        if key in seen or not article.get("headline") or not url:
            continue
        seen.add(key)
        
        # Keep only articles in the latest Seoul 07:00-to-07:00 briefing window.
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
    for i, article in enumerate(unique[:MAX_ITEMS]):
        article["placement"] = "top" if i == 0 else ("main" if i < 7 else "side")
    return unique[:MAX_ITEMS]


def llm_is_configured() -> bool:
    return bool(LLM_BASE_URL and LLM_MODEL)


def summarize_with_llm(article: dict, source_text: str) -> tuple[str, str | None, list[str] | None]:
    system_prompt = (
        "너는 반도체 뉴스 팩트 에디터다. 독자는 평가나 배경 설명이 아니라 새로 나온 사실을 원한다. "
        "요약은 기사에서 확인되는 핵심 사실, 새 발표/변경점, 기술 세부사항, 수치, 기업명, 제품명, 공정명, 일정, 적용 대상을 중심으로 쓴다. "
        "'반도체의 중요성이 커지고 있습니다', '경쟁이 치열해지고 있습니다', '주목됩니다', '의미가 있습니다' 같은 범용 평가 문장은 금지한다. "
        "원문에 없는 전망, 투자 조언, 과장 표현은 쓰지 않는다. 원문을 베껴 쓰지 말고 한국어로 압축한다. "
        "반드시 JSON만 출력한다. summary_lines는 3~5개의 문자열 배열이며 각 줄은 서로 다른 핵심 사실을 담는다. "
        "sector는 설계, 공정, 소자, 패키징 중 하나다."
    )
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
            return summary, sector, keywords
        except Exception as exc:
            is_429 = False
            if hasattr(exc, "code") and exc.code == 429:
                is_429 = True
            elif "429" in str(exc):
                is_429 = True
                
            if is_429 and len(LLM_API_KEYS) > 1 and attempt < max_attempts - 1:
                print(f"Key {current_key[:8]}... got 429/quota exceeded. Rotating to next key...")
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
            summary, sector, keywords = summarize_with_llm(article, source_text)
            if summary:
                article["body"] = summary
                article["summary_method"] = "llm"
                article["summary_model"] = LLM_MODEL
                if sector:
                    article["sector"] = sector
                if keywords:
                    article["llm_keywords"] = keywords
                enriched += 1
                time.sleep(4.0)
            else:
                article["summary_method"] = "snippet"
        except Exception as exc:
            article["summary_method"] = "snippet"
            err_msg = f"{type(exc).__name__}: {exc}"
            if hasattr(exc, "read"):
                try:
                    err_msg += f" - {exc.read().decode('utf-8', errors='replace')}"
                except Exception:
                    pass
            logs.append(f"llm skip article: {article.get('headline', '')[:60]} ({type(exc).__name__})")
            print(f"Error summarizing: {err_msg}", flush=True)
    logs.append(f"llm ok: summarized {enriched} articles, reused {cache_hits} cached summaries (total {min(len(articles), LLM_MAX_ITEMS)})")
    return articles


def write_articles(articles: list[dict], jobs: list[dict], logs: list[str]) -> None:
    summary_methods = sorted({a.get("summary_method", "snippet") for a in articles})
    payload = {
        "schema_version": 4,
        "generated_at": now_iso(),
        "briefing_title": "칩 브리핑",
        "sectors": ["설계", "공정", "소자", "패키징"],
        "collector": {
            "name": "collect_news.py",
            "source_count": len(articles),
            "job_count": len(jobs),
            "notes": "Metadata/link collection only; article full text is not stored. LLM summaries are generated transiently when configured.",
            "summary_methods": summary_methods,
            "summary_model": LLM_MODEL if llm_is_configured() else "",
            "logs": logs[-80:],
        },
        "articles": articles,
        "jobs": jobs,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    ARTICLES_PATH.write_text(text + "\n", encoding="utf-8")
    write_archive_snapshot(payload)
    sync_inline_data(payload)


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
        "job_count": len(payload.get("jobs", [])),
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


def sync_inline_data(payload: dict) -> None:
    if not INDEX_PATH.exists():
        return
    current = INDEX_PATH.read_text(encoding="utf-8")
    replacement = '<script id="inline-data" type="application/json">\n'
    replacement += json.dumps(payload, ensure_ascii=False, indent=2)
    replacement += "\n</script>"
    pattern = re.compile(r'<script id="inline-data" type="application/json">.*?</script>', re.S)
    updated, count = pattern.subn(replacement, current)
    if count != 1:
        raise RuntimeError("Could not find exactly one inline-data script in index.html")
    INDEX_PATH.write_text(updated, encoding="utf-8")


def main() -> int:
    config = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    global _SECTOR_KEYWORDS
    _SECTOR_KEYWORDS = config.get("sector_keywords", {})
    sources = flatten_sources(config)
    ko_queries = config.get("queries", {}).get("ko", [])
    en_queries = config.get("queries", {}).get("en", [])

    all_articles: list[dict] = []
    all_jobs: list[dict] = []
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
    if "Hacker News Algolia" in social_sources:
        found, new_logs = collect_hn(en_queries, social_sources["Hacker News Algolia"])
        all_articles.extend(found)
        logs.extend(new_logs)
    if "Reddit" in social_sources:
        found, new_logs = collect_reddit(en_queries, social_sources["Reddit"])
        all_articles.extend(found)
        logs.extend(new_logs)
    logs.append("x skip: disabled by configuration; Reddit-only community mode")

    ranked = dedupe_rank(all_articles)
    if not ranked:
        print("No relevant articles collected; articles.json not changed.", file=sys.stderr)
        for line in logs:
            print(line, file=sys.stderr)
        return 2
    # Disabled job postings collection as requested
    found_jobs, job_logs = [], []
    all_jobs.extend(found_jobs)
    logs.extend(job_logs)
    ranked = enrich_with_llm_summaries(ranked, logs)
    write_articles(ranked, all_jobs, logs)
    print(f"Wrote {len(ranked)} articles to {ARTICLES_PATH}")
    print(f"Synced inline data in {INDEX_PATH}")
    for line in logs[-20:]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

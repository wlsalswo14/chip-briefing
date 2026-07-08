#!/usr/bin/env python3
"""Send the daily Chip Briefing run result to Telegram.

Required env:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ARTICLES_PATH = ROOT / "articles.json"
LOGS_DIR = ROOT / "logs"
TELEGRAM_TIMEOUT = int(os.environ.get("TELEGRAM_TIMEOUT", "20"))


def clean_html(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def telegram(method: str, payload: dict, token: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=TELEGRAM_TIMEOUT) as res:
        return json.loads(res.read().decode("utf-8", errors="replace"))


def latest_log_text() -> str:
    logs = sorted(LOGS_DIR.glob("daily-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return "No daily log file found."
    text = logs[0].read_text(encoding="utf-8", errors="replace")
    return f"{logs[0].name}\n{text[-2500:]}"


def build_archive_message() -> str:
    data = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
    generated = data.get("generated_at", "")
    model = data.get("collector", {}).get("summary_model", "")
    methods = ", ".join(data.get("collector", {}).get("summary_methods", []))
    articles = data.get("articles", [])
    jobs = data.get("jobs", [])
    by_sector: dict[str, int] = {}
    for article in articles:
        by_sector[article.get("sector", "기타")] = by_sector.get(article.get("sector", "기타"), 0) + 1

    sector_line = " · ".join(f"{k} {v}" for k, v in sorted(by_sector.items()))
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d")
    lines = [
        f"<b>칩 브리핑 아카이브 · {today}</b>",
        f"생성: <code>{clean_html(generated)}</code>",
        f"수집: 뉴스 {len(articles)}개 · 채용 {len(jobs)}개 · {clean_html(sector_line)}",
    ]
    if model:
        lines.append(f"요약: <code>{clean_html(model)}</code> ({clean_html(methods)})")
    lines.append("")

    for i, article in enumerate(articles[:8], 1):
        title = clean_html(trim(article.get("headline", ""), 120))
        sector = clean_html(article.get("sector", ""))
        source = clean_html(article.get("source_name", ""))
        summary = clean_html(trim(article.get("body", ""), 260))
        url = clean_html(article.get("source_url", ""))
        lines.append(f"<b>{i}. [{sector}] {title}</b>")
        lines.append(f"{summary}")
        lines.append(f"출처: <a href=\"{url}\">{source}</a>")
        lines.append("")

    if jobs:
        lines.append("<b>채용</b>")
        for i, job in enumerate(jobs[:6], 1):
            title = clean_html(trim(job.get("title", ""), 100))
            company = clean_html(job.get("company", ""))
            sector = clean_html(job.get("sector", ""))
            location = clean_html(trim(job.get("location", ""), 80))
            url = clean_html(job.get("source_url", ""))
            lines.append(f"{i}. [{sector}] <a href=\"{url}\">{company} · {title}</a>")
            if location:
                lines.append(f"   {location}")

    return "\n".join(lines).strip()


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("telegram skip: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set")
        return 0

    try:
        message = build_archive_message()
        telegram(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            },
            token,
        )
        if os.environ.get("TELEGRAM_SEND_RUN_LOG", "1") != "0":
            telegram(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": "<b>칩 브리핑 실행 로그</b>\n<pre>"
                    + clean_html(trim(latest_log_text(), 3000))
                    + "</pre>",
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "true",
                },
                token,
            )
    except Exception as exc:
        print(f"telegram failed: {type(exc).__name__}: {exc}")
        return 0
    print("telegram ok: archive message sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

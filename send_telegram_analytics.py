#!/usr/bin/env python3
"""Send private daily visitor analytics to Telegram."""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import sys
import urllib.parse
import urllib.request


KST = dt.timezone(dt.timedelta(hours=9))
DEFAULT_API_URL = "https://chip-briefing-analytics.wlsalswo14.workers.dev"
TELEGRAM_TIMEOUT = int(os.environ.get("TELEGRAM_TIMEOUT", "20"))
OIDC_AUDIENCE = "chip-briefing-analytics"


def github_oidc_token() -> str:
    request_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "").strip()
    request_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "").strip()
    if not request_url or not request_token:
        raise RuntimeError("GitHub Actions OIDC environment is unavailable")

    parsed = urllib.parse.urlsplit(request_url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key != "audience"]
    query.append(("audience", OIDC_AUDIENCE))
    oidc_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )
    req = urllib.request.Request(
        oidc_url,
        headers={
            "Authorization": f"Bearer {request_token}",
            "Accept": "application/json",
            "User-Agent": "chip-briefing-analytics/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=TELEGRAM_TIMEOUT) as res:
        payload = json.loads(res.read().decode("utf-8"))
    token = str(payload.get("value") or "").strip()
    if not token:
        raise RuntimeError("GitHub Actions OIDC token response was empty")
    return token


def request_json(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "chip-briefing-analytics/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=TELEGRAM_TIMEOUT) as res:
        return json.loads(res.read().decode("utf-8"))


def telegram(method: str, payload: dict, token: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=TELEGRAM_TIMEOUT) as res:
        return json.loads(res.read().decode("utf-8", errors="replace"))


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}시간 {minutes}분 {secs}초"
    if minutes:
        return f"{minutes}분 {secs}초"
    return f"{secs}초"


def format_seen(timestamp: int) -> str:
    if not timestamp:
        return "-"
    return dt.datetime.fromtimestamp(int(timestamp), tz=dt.timezone.utc).astimezone(KST).strftime("%H:%M:%S")


def report_day() -> str:
    override = os.environ.get("ANALYTICS_REPORT_DAY", "").strip()
    if override:
        dt.date.fromisoformat(override)
        return override
    return (dt.datetime.now(KST).date() - dt.timedelta(days=1)).isoformat()


def build_blocks(report: dict) -> list[str]:
    day = html.escape(str(report.get("day", "")))
    views = int(report.get("views", 0) or 0)
    unique = int(report.get("unique_visitors", 0) or 0)
    blocks = [
        (
            f"<b>칩 브리핑 방문 통계 · {day}</b>\n"
            f"환산 조회수: <b>{views:,}</b>\n"
            f"고유 IP: <b>{unique:,}</b>\n"
            f"계산식: IP당 10 + N (N=0~9, 하루 고정)"
        )
    ]

    visitors = report.get("visitors") or []
    if not visitors:
        blocks.append("방문 기록이 없습니다.")
        return blocks

    for index, visitor in enumerate(visitors, 1):
        ip = html.escape(str(visitor.get("ip") or "unknown"))
        bonus = int(visitor.get("bonus", 0) or 0)
        weighted = int(visitor.get("weighted_views", 10 + bonus) or 0)
        total = format_duration(int(visitor.get("total_seconds", 0) or 0))
        first_seen = format_seen(int(visitor.get("first_seen", 0) or 0))
        last_seen = format_seen(int(visitor.get("last_seen", 0) or 0))
        lines = [
            f"<b>{index}. {ip}</b>",
            f"조회 가중치: {weighted} (= 10 + {bonus})",
            f"체류 합계: {total}",
            f"첫 방문 {first_seen} · 마지막 활동 {last_seen}",
        ]
        categories = visitor.get("categories") or []
        if categories:
            lines.append("<b>카테고리별 체류</b>")
            for item in categories:
                category = html.escape(str(item.get("category") or "기타"))
                seconds = int(item.get("seconds", 0) or 0)
                lines.append(f"· {category}: {format_duration(seconds)}")
        else:
            lines.append("· 집계된 체류시간 없음")
        blocks.append("\n".join(lines))
    return blocks


def split_blocks(blocks: list[str], limit: int = 3900) -> list[str]:
    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(block) <= limit:
            current = block
        else:
            chunks.append(block[:limit])
            current = ""
    if current:
        chunks.append(current)
    return chunks


def main() -> int:
    api_url = os.environ.get("ANALYTICS_API_URL", DEFAULT_API_URL).rstrip("/")
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not telegram_token or not chat_id:
        print("analytics telegram failed: Telegram secrets are missing", file=sys.stderr)
        return 1

    day = report_day()
    query = urllib.parse.urlencode({"day": day})
    try:
        report_token = github_oidc_token()
        report = request_json(f"{api_url}/api/admin/report?{query}", report_token)
        chunks = split_blocks(build_blocks(report))
        for chunk in chunks:
            telegram(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "true",
                },
                telegram_token,
            )
    except Exception as exc:
        print(f"analytics telegram failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"analytics telegram ok: {day} ({len(chunks)} message(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

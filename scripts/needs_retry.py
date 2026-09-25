#!/usr/bin/env python3
"""Decide whether the daily briefing needs another attempt.

The workflow runs every hour. This guard asks for a real run only when today's
briefing is missing or came out degraded, so a bad hour on the model host is
retried instead of leaving the site broken until tomorrow.
"""

import datetime as dt
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles.json"
KST = dt.timezone(dt.timedelta(hours=9))


def decide(now: dt.datetime | None = None) -> tuple[str, str]:
    if os.environ.get("CHIP_BRIEFING_FORCE", "").strip().lower() in {"1", "true", "yes"}:
        return "yes", "수동 실행 (force)"
    # The briefing window ends at WINDOW_END_HOUR KST. Before that hour there is
    # no "today" to build yet: a run now would publish yesterday's window under
    # today's date, and the guard would then leave it alone all day.
    window_end_hour = int(os.environ.get("CHIP_BRIEFING_WINDOW_END_HOUR", "2") or "2")
    now = now or dt.datetime.now(KST)
    if now.hour < window_end_hour:
        return "no", f"브리핑 기준 시각({window_end_hour}시) 전이라 대기"
    try:
        data = json.loads(ARTICLES.read_text(encoding="utf-8"))
    except Exception as exc:
        return "yes", f"articles.json 읽기 실패 ({type(exc).__name__})"

    generated = str(data.get("generated_at") or "")
    today = now.strftime("%Y-%m-%d")
    collector = data.get("collector") or {}
    health = collector.get("health") or {}
    status = str(health.get("status") or "ok")
    summary_target = int(collector.get("summary_target") or 0)
    summary_count = int(collector.get("summary_count") or 0)

    if generated[:10] != today:
        return "yes", f"오늘 브리핑이 아직 없음 (마지막: {generated[:10] or '알 수 없음'})"
    if summary_target and summary_count < summary_target:
        return "yes", f"상세 요약 부족 ({summary_count}/{summary_target})"
    if not health:
        # 이전 버전이 만든 데이터: 로그에서 실패 흔적을 찾는다.
        logs = collector.get("logs") or []
        broken = [
            str(line)
            for line in logs
            if str(line).startswith(("daily summary skip", "community reaction summary skip"))
        ]
        if broken:
            return "yes", "요약 실패 기록 발견: " + broken[0]
    if status != "ok":
        reasons = health.get("reasons") or ["degraded"]
        return "yes", "요약 실패: " + ", ".join(str(reason) for reason in reasons)
    return "no", "오늘 브리핑 정상"


def main() -> int:
    retry, reason = decide()
    print(f"retry={retry} ({reason})")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"retry={retry}\n")
            handle.write(f"reason={reason}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

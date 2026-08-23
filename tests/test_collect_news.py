import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import collect_news as collector


class CommunityParserTests(unittest.TestCase):
    def test_dcinside_search_parser_keeps_nested_title_text(self):
        source = """
        <a href="https://gall.dcinside.com/mgallery/board/view/?id=chips&amp;no=1" class="tit_txt">
          HBM <b>공급</b> 전망
        </a>
        <a class="sub_txt">반도체산업</a>
        <span class="date_time">2026.08.22 09:30</span>
        """
        parser = collector.DCInsideSearchParser()
        parser.feed(source)
        self.assertEqual(
            parser.items,
            [{
                "url": "https://gall.dcinside.com/mgallery/board/view/?id=chips&no=1",
                "title": "HBM 공급 전망",
                "community": "반도체산업",
                "date": "2026.08.22 09:30",
            }],
        )

    def test_clien_parser_skips_notices(self):
        source = """
        <div class="list_item notice"><a class="list_subject" href="/notice">공지 HBM</a></div>
        <div class="list_item symph_row">
          <a class="list_subject" href="/service/board/cm_stock/1">
            <span class="subject_fixed" title="HBM 전망"></span>
          </a>
          <span class="timestamp">2026-08-22 10:11:12</span>
        </div>
        """
        parser = collector.ClienBoardParser()
        parser.feed(source)
        self.assertEqual(
            parser.items,
            [{
                "url": "/service/board/cm_stock/1",
                "title": "HBM 전망",
                "date": "2026-08-22 10:11:12",
            }],
        )


class CommunityWindowTests(unittest.TestCase):
    def test_briefing_window_ends_at_latest_seoul_0700(self):
        kst = dt.timezone(dt.timedelta(hours=9))
        start, end = collector.briefing_window(dt.datetime(2026, 8, 23, 7, 30, tzinfo=kst))
        self.assertEqual(start, dt.datetime(2026, 8, 22, 7, 0, tzinfo=kst))
        self.assertEqual(end, dt.datetime(2026, 8, 23, 7, 0, tzinfo=kst))

    def test_estimated_date_item_bypasses_exact_window(self):
        item = collector.make_article(
            "HBM test",
            "https://example.com/community/1",
            "HBM",
            {"name": "test", "category_default": "community", "trust_default": "low"},
            "community",
            collector.now_iso(),
        )
        item["date_is_estimated"] = True
        self.assertEqual(len(collector.dedupe_rank([item])), 1)

    def test_estimated_date_item_is_suppressed_when_seen_yesterday(self):
        kst = dt.timezone(dt.timedelta(hours=9))
        yesterday = (dt.datetime.now(kst).date() - dt.timedelta(days=1)).isoformat()
        url = "https://example.com/community/seen"
        item = {"source_url": url, "date_is_estimated": True}
        with tempfile.TemporaryDirectory() as directory:
            archive_dir = Path(directory)
            (archive_dir / f"{yesterday}.json").write_text(
                json.dumps({"community_items": [{"source_url": url}]}),
                encoding="utf-8",
            )
            with mock.patch.object(collector, "ARCHIVE_DIR", archive_dir):
                logs = []
                self.assertEqual(collector.suppress_seen_estimated_community([item], logs), [])
                self.assertTrue(logs)

    def test_community_limit_round_robins_source_families(self):
        items = []
        for index in range(5):
            items.append({"source_name": f"Naver Cafe · cafe {index}", "created_at": f"2026-08-23T07:0{index}:00+09:00"})
        for index in range(2):
            items.append({"source_name": f"DCInside · gallery {index}", "created_at": f"2026-08-22T12:0{index}:00+09:00"})
        selected = collector.prepare_community_items(items, 4)
        self.assertEqual(
            [collector.community_source_family(item) for item in selected],
            ["naver_cafe", "dcinside", "naver_cafe", "dcinside"],
        )


if __name__ == "__main__":
    unittest.main()

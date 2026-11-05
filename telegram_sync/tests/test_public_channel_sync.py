import sys
import unittest
import base64
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import public_channel_sync as sync


class PublicChannelParserTests(unittest.TestCase):
    def test_week_range_uses_current_year(self):
        start, end = sync.parse_week("30.10-05.11 gacha", date(2026, 11, 4))
        self.assertEqual(start, date(2026, 10, 30))
        self.assertEqual(end, date(2026, 11, 5))

    def test_invalid_week_range_is_rejected(self):
        with self.assertRaises(ValueError):
            sync.parse_week("30.10-04.11", date(2026, 11, 4))

    def test_photo_url_from_public_preview(self):
        from bs4 import BeautifulSoup
        html = '<div class="tgme_widget_message" data-post="namozvaqti365/123"><a class="tgme_widget_message_photo_wrap" style="background-image:url(\'https://cdn4.telesco.pe/file/poster.jpg\')"></a></div>'
        node = BeautifulSoup(html, "html.parser").select_one(".tgme_widget_message")
        self.assertEqual(sync.poster_photo(node), "https://cdn4.telesco.pe/file/poster.jpg")

    def test_ocr_reads_all_five_times_from_small_weekly_poster(self):
        image = Image.new("RGB", (300, 480), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", 32)
        draw.text((8, 0), "30.10-05.11 gacha", fill="black", font=font)
        for index, value in enumerate(("6-10", "13-00", "15-40", "17-20", "19-05")):
            draw.text((165, 45 + index * 80), value, fill="black", font=font)
        stream = BytesIO()
        image.save(stream, format="PNG")
        times, poster_text = sync.read_times(stream.getvalue())
        self.assertEqual(times, ["06:10", "13:00", "15:40", "17:20", "19:05"])
        start, end = sync.parse_week(poster_text, date(2026, 11, 4))
        self.assertEqual((start, end), (date(2026, 10, 30), date(2026, 11, 5)))

    def test_invalid_or_missing_header_is_rejected(self):
        with self.assertRaises(ValueError):
            sync.parse_week("Haftalik namoz vaqtlari", date(2026, 11, 4))


    def test_week_range_with_explicit_year(self):
        start, end = sync.parse_week("06.11.2026–12.11.2026", date(2026, 11, 5))
        self.assertEqual((start, end), (date(2026, 11, 6), date(2026, 11, 12)))

    def test_compact_same_month_week_range(self):
        start, end = sync.parse_week("06–12.11.2026", date(2026, 11, 5))
        self.assertEqual((start, end), (date(2026, 11, 6), date(2026, 11, 12)))

    def test_ocr_times_can_be_in_one_horizontal_row(self):
        text = "06.11.2026–12.11.2026\n06:10 | 13:00 | 15:40 | 17:20 | 19:05"
        self.assertEqual(
            sync._times_from_ocr_text(text),
            ["06:10", "13:00", "15:40", "17:20", "19:05"],
        )

    def test_single_date_is_not_misread_as_prayer_time(self):
        text = "06.11\n06:10\n13:00\n15:40\n17:20\n19:05"
        self.assertEqual(
            sync._times_from_ocr_text(text),
            ["06:10", "13:00", "15:40", "17:20", "19:05"],
        )


    def test_edited_same_telegram_post_can_update_changed_times(self):
        start = date(2026, 11, 6)
        end = date(2026, 11, 12)
        old_days = [
            {"date": (start.fromordinal(start.toordinal() + i)).isoformat(),
             "fajr": "06:11", "dhuhr": "13:00", "asr": "15:40",
             "maghrib": "17:20", "isha": "19:05"}
            for i in range(7)
        ]
        existing = {
            "weekStart": start.isoformat(),
            "sourcePostId": "1064",
            "days": old_days,
        }
        encoded = base64.b64encode(json.dumps(existing).encode()).decode()

        class Response:
            status_code = 200
            text = ""

            def json(self):
                return {"sha": "existing-blob-sha", "content": encoded}

        post = {"id": 1064, "photo": "https://example.test/poster.jpg", "caption": "", "published": ""}
        new_days = [
            {"date": (start.fromordinal(start.toordinal() + i)).isoformat(),
             "fajr": "06:10", "sunrise": "07:10", "dhuhr": "13:00",
             "asr": "15:40", "maghrib": "17:20", "isha": "19:05"}
            for i in range(7)
        ]
        with patch.object(sync, "REPO", "owner/repo"), \
             patch.object(sync, "TOKEN", "test-token"), \
             patch.object(sync.HTTP, "get", return_value=Response()), \
             patch.object(sync.HTTP, "put", return_value=Response()) as put:
            changed = sync.update_json(start, end, new_days, post)

        self.assertTrue(changed)
        put.assert_called_once()


    def test_repeated_poster_cells_are_combined_by_ocr_consensus(self):
        passes = [
            "6-15 6-15 17-10 13-00 18-55",
            "06-15 15-30 17-10 13-00 18-55",
            "06-15 13-00 15-30 17-10 18-55",
            "06-15 07-10 13-00 15-30 17-10 18-55",
            "06-15 07-10 13-00 15-30 17-10 18-55",
            "06-15 07-10 13-00 15-30 17-10 18-55 13-30",
        ]
        self.assertEqual(
            sync._consensus_times(passes),
            ["06:15", "07:10", "13:00", "15:30", "17:10", "18:55"],
        )

    def test_old_telegram_publication_cannot_become_current_year_schedule(self):
        with self.assertRaises(ValueError):
            sync.parse_week(
                "14.11-20.11",
                today=date(2026, 11, 5),
                published_date=date(2025, 11, 13),
            )


    def test_official_api_returns_distinct_day_by_day_values(self):
        start = date(2026, 11, 6)
        values = [
            ("05:28", "06:48", "11:55", "15:19", "17:05", "18:21"),
            ("05:29", "06:50", "11:55", "15:18", "17:03", "18:20"),
            ("05:30", "06:51", "11:55", "15:17", "17:02", "18:19"),
            ("05:31", "06:52", "11:55", "15:16", "17:01", "18:19"),
            ("05:32", "06:53", "11:55", "15:15", "17:00", "18:18"),
            ("05:33", "06:54", "11:55", "15:14", "16:59", "18:17"),
            ("05:34", "06:56", "11:55", "15:13", "16:58", "18:16"),
        ]
        fields = ("bomdod", "quyosh", "peshin", "asr", "shom", "xufton")
        body = {
            "meta": {"region": {"slug": "baliqchi", "name": "Baliqchi tumani"}},
            "period_table": [
                {
                    "date": f"{6+i:02d}.11.2026",
                    "times": dict(zip(fields, row)),
                }
                for i, row in enumerate(values)
            ],
        }

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return body

        with patch.object(sync.HTTP, "get", return_value=Response()) as get:
            days = sync.fetch_official_days(date(2026, 11, 6), date(2026, 11, 12))

        self.assertEqual(len(days), 7)
        self.assertEqual(days[0]["fajr"], "05:28")
        self.assertEqual(days[0]["sunrise"], "06:48")
        self.assertEqual(days[-1]["isha"], "18:16")
        get.assert_called_once()

    def test_official_api_rejects_wrong_region(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "meta": {"region": {"slug": "toshkent", "name": "Toshkent"}},
                    "period_table": [],
                }

        with patch.object(sync.HTTP, "get", return_value=Response()):
            with self.assertRaisesRegex(ValueError, "boshqa hududni qaytardi"):
                sync.fetch_official_days(date(2026, 11, 6), date(2026, 11, 12))

    def test_official_api_rejects_flat_week(self):
        fields = ("bomdod", "quyosh", "peshin", "asr", "shom", "xufton")
        same = ("05:28", "06:48", "11:55", "15:19", "17:05", "18:21")
        body = {
            "meta": {"region": {"slug": "baliqchi"}},
            "period_table": [
                {
                    "date": f"{6+i:02d}.11.2026",
                    "times": dict(zip(fields, same)),
                }
                for i in range(7)
            ],
        }

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return body

        with patch.object(sync.HTTP, "get", return_value=Response()):
            with self.assertRaisesRegex(ValueError, "aynan bir xil"):
                sync.fetch_official_days(date(2026, 11, 6), date(2026, 11, 12))


if __name__ == "__main__":
    unittest.main()

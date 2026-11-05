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
        with patch.object(sync, "REPO", "owner/repo"), \
             patch.object(sync, "TOKEN", "test-token"), \
             patch.object(sync.HTTP, "get", return_value=Response()), \
             patch.object(sync.HTTP, "put", return_value=Response()) as put:
            changed = sync.update_json(
                start, end, ["06:10", "13:00", "15:40", "17:20", "19:05"], post
            )

        self.assertTrue(changed)
        put.assert_called_once()


if __name__ == "__main__":
    unittest.main()

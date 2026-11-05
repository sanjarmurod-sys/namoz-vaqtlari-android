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
        start, end = sync.parse_week("06.11-12.11 gacha", date(2026, 11, 5))
        self.assertEqual((start, end), (date(2026, 11, 6), date(2026, 11, 12)))

    def test_invalid_week_range_is_rejected(self):
        with self.assertRaises(ValueError):
            sync.parse_week("06.11-11.11", date(2026, 11, 5))

    def test_week_range_with_explicit_year(self):
        start, end = sync.parse_week("06.11.2026–12.11.2026", date(2026, 11, 5))
        self.assertEqual((start, end), (date(2026, 11, 6), date(2026, 11, 12)))

    def test_compact_same_month_week_range(self):
        start, end = sync.parse_week("06–12.11.2026", date(2026, 11, 5))
        self.assertEqual((start, end), (date(2026, 11, 6), date(2026, 11, 12)))

    def test_invalid_or_missing_header_is_rejected(self):
        with self.assertRaises(ValueError):
            sync.parse_week("Haftalik namoz vaqtlari", date(2026, 11, 5))

    def test_old_telegram_publication_cannot_become_current_year_schedule(self):
        with self.assertRaises(ValueError):
            sync.parse_week(
                "14.11-20.11",
                today=date(2026, 11, 5),
                published_date=date(2025, 11, 13),
            )

    def test_photo_url_from_public_preview(self):
        from bs4 import BeautifulSoup
        html = '<div class="tgme_widget_message" data-post="namozvaqti365/123"><a class="tgme_widget_message_photo_wrap" style="background-image:url(\'https://cdn4.telesco.pe/file/poster.jpg\')"></a></div>'
        node = BeautifulSoup(html, "html.parser").select_one(".tgme_widget_message")
        self.assertEqual(sync.poster_photo(node), "https://cdn4.telesco.pe/file/poster.jpg")

    def test_date_tokens_are_not_misread_as_times(self):
        self.assertEqual(
            sync._time_values_from_ocr_text("06.11.2026 05:28 11:55 15:19 17:05 18:21"),
            ["05:28", "11:55", "15:19", "17:05", "18:21"],
        )

    def test_only_five_prayer_times_are_accepted(self):
        self.assertEqual(
            sync._times_from_ocr_text("05:28 11:55 15:19 17:05 18:21"),
            ["05:28", "11:55", "15:19", "17:05", "18:21"],
        )
        self.assertIsNone(
            sync._times_from_ocr_text("05:28 06:48 11:55 15:19 17:05 18:21")
        )

    def test_weekly_image_is_read_as_seven_rows_of_five_prayers(self):
        image = Image.new("RGB", (1350, 820), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 34)
        bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 30)
        draw.text((45, 20), "Sana     Bomdod     Peshin      Asr       Shom      Xufton", fill="black", font=bold)
        values = [
            ("05:28", "11:55", "15:19", "17:05", "18:21"),
            ("05:29", "11:55", "15:18", "17:03", "18:20"),
            ("05:30", "11:55", "15:17", "17:02", "18:19"),
            ("05:31", "11:55", "15:16", "17:01", "18:19"),
            ("05:32", "11:55", "15:15", "17:00", "18:18"),
            ("05:33", "11:55", "15:14", "16:59", "18:17"),
            ("05:34", "11:55", "15:13", "16:58", "18:16"),
        ]
        for i, row in enumerate(values):
            line = f"{6+i:02d}.11    " + "     ".join(row)
            draw.text((45, 90 + i * 95), line, fill="black", font=font)
        stream = BytesIO()
        image.save(stream, format="PNG")
        days = sync.read_week_schedule(
            stream.getvalue(), date(2026, 11, 6), date(2026, 11, 12)
        )
        self.assertEqual(len(days), 7)
        self.assertEqual(days[0]["fajr"], "05:28")
        self.assertEqual(days[0]["dhuhr"], "11:55")
        self.assertEqual(days[-1]["isha"], "18:16")
        self.assertNotIn("sunrise", days[0])

    def test_week_matrix_rejects_wrong_prayer_count_and_bad_order(self):
        bad_order = [["05:30", "06:30", "11:50", "15:10", "18:00"] for _ in range(7)]
        wrong_count = [["05:30", "11:50", "15:10", "18:00"] for _ in range(7)]
        self.assertFalse(sync._validate_week_matrix(bad_order))
        self.assertFalse(sync._validate_week_matrix(wrong_count))

    def test_json_update_writes_exactly_five_prayers_from_telegram(self):
        start = date(2026, 11, 6)
        end = date(2026, 11, 12)
        values = [
            ("05:28", "11:55", "15:19", "17:05", "18:21"),
            ("05:29", "11:55", "15:18", "17:03", "18:20"),
            ("05:30", "11:55", "15:17", "17:02", "18:19"),
            ("05:31", "11:55", "15:16", "17:01", "18:19"),
            ("05:32", "11:55", "15:15", "17:00", "18:18"),
            ("05:33", "11:55", "15:14", "16:59", "18:17"),
            ("05:34", "11:55", "15:13", "16:58", "18:16"),
        ]
        fields = ("fajr", "dhuhr", "asr", "maghrib", "isha")
        days = [
            {"date": (start.fromordinal(start.toordinal()+i)).isoformat(), **dict(zip(fields,row))}
            for i,row in enumerate(values)
        ]
        encoded = base64.b64encode(json.dumps({"weekStart":start.isoformat()}).encode()).decode()

        class GetResponse:
            status_code = 200
            def json(self):
                return {"sha":"blob-sha","content":encoded}

        class PutResponse:
            status_code = 200
            text = ""

        post = {"id":1065,"published":"2026-11-05T10:56:25+00:00"}
        with patch.object(sync, "REPO", "owner/repo"), \
             patch.object(sync, "TOKEN", "token"), \
             patch.object(sync.HTTP, "get", return_value=GetResponse()), \
             patch.object(sync.HTTP, "put", return_value=PutResponse()) as put:
            self.assertTrue(sync.update_json(start,end,days,post))
        payload = json.loads(base64.b64decode(put.call_args.kwargs["json"]["content"]))
        self.assertEqual(
            set(payload["days"][0]),
            {"date","fajr","dhuhr","asr","maghrib","isha"},
        )
        self.assertTrue(payload["source"].startswith("Telegram rasmi:"))
        self.assertNotIn("scheduleSource", payload)


if __name__ == "__main__":
    unittest.main()

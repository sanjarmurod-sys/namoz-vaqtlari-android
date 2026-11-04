import sys
import unittest
from datetime import date
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()

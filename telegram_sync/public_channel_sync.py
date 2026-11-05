#!/usr/bin/env python3
"""Poll Telegram's public web preview, OCR its weekly Baliqchi prayer poster,
and publish only validated schedules. No Telegram bot or channel admin access.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pytesseract
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from pytesseract import Output

LOG = logging.getLogger("namoz-public-sync")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s %(message)s")
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))
CHANNEL = os.getenv("TELEGRAM_CHANNEL_USERNAME", "namozvaqti365").lstrip("@")
REPO = os.getenv("GITHUB_REPOSITORY", "").strip()
TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
BRANCH = os.getenv("GITHUB_BRANCH", "main")
DATA_PATH = os.getenv("PRAYER_JSON_PATH", "data/prayer-times.json")
CITY_ID = os.getenv("CITY_ID", "baliqchi")
CITY_NAME = os.getenv("CITY_NAME", "Baliqchi tumani")
PREVIEW = f"https://t.me/s/{CHANNEL}"
API = f"https://api.github.com/repos/{REPO}/contents/{DATA_PATH}"
DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[.,/]\s*(\d{1,2})(?:[.,/]\s*\d{2,4})?\s*[-–—]\s*(\d{1,2})\s*[.,/]\s*(\d{1,2})(?:[.,/]\s*\d{2,4})?")
DATE_SAME_MONTH_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*[.,/]\s*(\d{1,2})(?:[.,/]\s*\d{2,4})?")
TIME_RE = re.compile(r"(?<!\d)(2[0-3]|[01]?\d)\s*[-:.,٫]\s*([0-5]\d)(?!\d)")
HTTP = requests.Session()
RETRY = Retry(
    total=4, connect=4, read=4, status=4, backoff_factor=0.6,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(("GET",)),
)
HTTP.mount("https://", HTTPAdapter(max_retries=RETRY))
HTTP.headers.update({"User-Agent": "Mozilla/5.0 (compatible; NamozVaqtlari/1.0)", "Accept": "text/html,*/*"})


def parse_week(
    text: str,
    today: date | None = None,
    published_date: date | None = None,
) -> tuple[date, date]:
    today = today or datetime.now(TZ).date()
    source = text or ""
    m = DATE_RE.search(source)
    if m:
        sd, sm, ed, em = map(int, m.groups())
    else:
        same_month = DATE_SAME_MONTH_RE.search(source)
        if not same_month:
            raise ValueError("Hafta sanasi topilmadi (masalan, 06.11-12.11 yoki 06-12.11).")
        sd, ed, sm = map(int, same_month.groups())
        em = sm

    # Use the Telegram publication date to infer the year. This prevents a 2025
    # poster for (say) 14–20 November from being mistaken for a 2026 schedule.
    anchor = published_date or today
    candidates = []
    for year in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            start = date(year, sm, sd)
            end = date(year + (1 if (em, ed) < (sm, sd) else 0), em, ed)
        except ValueError:
            continue
        if (end - start).days == 6:
            distance = 0 if start <= anchor <= end else min(abs((start-anchor).days), abs((end-anchor).days))
            candidates.append((distance, start, end))
    if not candidates:
        raise ValueError("Sana oralig‘i 7 kunlik haftaga mos kelmadi.")
    _, start, end = min(candidates, key=lambda x: x[0])

    if published_date:
        publication_gap = (start - published_date).days
        if not -7 <= publication_gap <= 14:
            raise ValueError("Telegram post sanasi afishadagi hafta bilan mos kelmadi.")
    if end < today - timedelta(days=2) or start > today + timedelta(days=14):
        raise ValueError("Afishadagi hafta eskirgan yoki juda uzoq kelajakda.")
    return start, end


def _normalise_ocr_time(value: str) -> str | None:
    """Parse one time cell from a Telegram poster; dates with dots are not times."""
    text = (value or "").strip().upper()
    text = text.translate(str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1"}))
    text = re.sub(r"[^0-9:\-]", "", text)
    match = re.fullmatch(r"([01]?\d|2[0-3])[:-]([0-5]\d)", text)
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _time_values_from_ocr_text(text: str) -> list[str]:
    """Extract HH:MM/HH-MM only; DD.MM dates are deliberately ignored."""
    found = []
    for token in re.findall(r"(?<!\d)(?:[01]?\d|2[0-3])[:-][0-5]\d(?!\d)", text or ""):
        value = _normalise_ocr_time(token)
        if value:
            found.append(value)
    return found


def _times_from_ocr_text(text: str) -> list[str] | None:
    """Return exactly five prayer times in printed order."""
    values = _time_values_from_ocr_text(text)
    if len(values) != 5:
        return None
    minutes = [int(x[:2]) * 60 + int(x[3:]) for x in values]
    return values if all(b > a for a, b in zip(minutes, minutes[1:])) else None


def _ocr_time_boxes(image: Image.Image, psm: int) -> list[dict]:
    """Read only complete, positioned time cells; do not guess split numbers."""
    data = pytesseract.image_to_data(
        image, lang="eng",
        config=f"--oem 1 --psm {psm} -c tessedit_char_whitelist=0123456789:-",
        output_type=Output.DICT,
    )
    boxes: list[dict] = []
    for i, raw in enumerate(data.get("text", [])):
        text = str(raw or "").strip()
        value = _normalise_ocr_time(text)
        if not value:
            continue
        try:
            confidence = float(data["conf"][i])
            left, top = int(data["left"][i]), int(data["top"][i])
            width, height = int(data["width"][i]), int(data["height"][i])
        except (ValueError, TypeError, KeyError):
            continue
        if confidence < 25 or width <= 0 or height <= 0:
            continue
        boxes.append({
            "text": text, "time": value,
            "left": left, "top": top, "width": width, "height": height,
            "cx": left + width / 2, "cy": top + height / 2,
            "confidence": confidence,
        })
    return boxes


def _cluster_boxes(boxes: list[dict], axis: str) -> list[list[dict]]:
    """Group cells by common horizontal rows (Y) or vertical columns (X)."""
    if not boxes:
        return []
    centre = "cy" if axis == "row" else "cx"
    typical_height = sorted(box["height"] for box in boxes)[len(boxes) // 2]
    tolerance = max(9.0, typical_height * 1.15)
    groups: list[list[dict]] = []
    for box in sorted(boxes, key=lambda item: item[centre]):
        if groups:
            average = sum(item[centre] for item in groups[-1]) / len(groups[-1])
            if abs(box[centre] - average) <= tolerance:
                groups[-1].append(box)
                continue
        groups.append([box])
    return groups


def _schedule_candidate(boxes: list[dict], axis: str) -> tuple[list[list[str]], float] | None:
    """Require seven day-groups with exactly five time cells in each group."""
    groups = [group for group in _cluster_boxes(boxes, axis) if len(group) == 5]
    if len(groups) != 7:
        return None
    if axis == "row":
        groups.sort(key=lambda group: sum(x["cy"] for x in group) / len(group))
        for group in groups:
            group.sort(key=lambda item: item["cx"])
    else:
        groups.sort(key=lambda group: sum(x["cx"] for x in group) / len(group))
        for group in groups:
            group.sort(key=lambda item: item["cy"])
    matrix = [[item["time"] for item in group] for group in groups]
    confidence = sum(item["confidence"] for group in groups for item in group) / 35
    return matrix, confidence


def _validate_week_matrix(matrix: list[list[str]]) -> bool:
    """Validate 7 days x 5 ordered prayers and smooth day-to-day changes."""
    if len(matrix) != 7 or any(len(row) != 5 for row in matrix):
        return False
    columns: list[list[int]] = [[] for _ in range(5)]
    bounds = ((180, 480), (600, 900), (720, 1110), (840, 1290), (900, 1410))
    for row in matrix:
        values = []
        for index, value in enumerate(row):
            match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value)
            if not match:
                return False
            minute = int(match.group(1)) * 60 + int(match.group(2))
            low, high = bounds[index]
            if not low <= minute <= high:
                return False
            values.append(minute)
            columns[index].append(minute)
        if any(b <= a for a, b in zip(values, values[1:])):
            return False
    return all(abs(b-a) <= 20 for column in columns for a,b in zip(column,column[1:]))


def read_week_schedule(image_bytes: bytes, start: date, end: date) -> list[dict]:
    """Read every prayer time straight from the Telegram poster: seven days, five values."""
    if (end - start).days != 6:
        raise ValueError("Telegram afishasi aynan 7 kunlik bo‘lishi kerak.")
    original = Image.open(io.BytesIO(image_bytes)).convert("L")
    base = ImageOps.autocontrast(original)
    variants = [
        base,
        ImageEnhance.Contrast(base).enhance(1.7),
        base.point(lambda pixel: 255 if pixel > 165 else 0),
    ]
    candidates: list[tuple[list[list[str]], float, str]] = []
    for variant in variants:
        scale = max(2, min(4, 1800 // max(variant.width, variant.height, 1)))
        enlarged = variant.resize(
            (variant.width * scale, variant.height * scale), Image.Resampling.LANCZOS
        )
        for psm in (6, 11):
            boxes = _ocr_time_boxes(enlarged, psm)
            for axis in ("row", "column"):
                candidate = _schedule_candidate(boxes, axis)
                if candidate and _validate_week_matrix(candidate[0]):
                    candidates.append((candidate[0], candidate[1], axis))
    if not candidates:
        raise ValueError(
            "Telegram rasmini o‘qishda 7 kunning har biri uchun 5 ta vaqt topilmadi. "
            "Rasm to‘liq tanilmadi; noto‘g‘ri jadval yozilmadi."
        )
    counts = Counter(tuple(tuple(row) for row in matrix) for matrix, _, _ in candidates)
    matrix, confidence, axis = max(
        candidates, key=lambda item: (counts[tuple(tuple(row) for row in item[0])], item[1])
    )
    if counts[tuple(tuple(row) for row in matrix)] == 1 and confidence < 65:
        raise ValueError("Telegram rasmidagi vaqtlar OCR ishonchliligi past; jadval yangilanmadi.")
    prayer_ids = ("fajr", "dhuhr", "asr", "maghrib", "isha")
    days = []
    for offset, row in enumerate(matrix):
        item = {"date": (start + timedelta(days=offset)).isoformat()}
        item.update(dict(zip(prayer_ids, row)))
        days.append(item)
    LOG.info(
        "Telegram rasmidan bevosita OCR: %s, 7 kun x 5 namoz; birinchi kun=%s; vaqtlar=%s",
        axis, days[0]["date"], ", ".join(days[0][key] for key in prayer_ids),
    )
    return days


def read_week_heading(image_bytes: bytes) -> str:
    """Read only the printed week/date heading; prayer times come from read_week_schedule."""
    original = Image.open(io.BytesIO(image_bytes)).convert("L")
    enlarged = ImageOps.autocontrast(
        original.resize((original.width * 5, original.height * 5), Image.Resampling.LANCZOS)
    )
    outputs = []
    for psm in (11, 6, 12):
        outputs.append(
            pytesseract.image_to_string(enlarged, lang="eng", config=f"--oem 1 --psm {psm}")
        )
    return "\n".join(outputs)


def poster_photo(node) -> str | None:
    # Telegram has used both CSS background images and lazy-loaded img tags.
    for el in node.select(
        ".tgme_widget_message_photo_wrap, .tgme_widget_message_video_thumb, "
        ".tgme_widget_message_photo"
    ):
        style = el.get("style", "")
        m = re.search(r"url\(['\"]?(.*?)['\"]?\)", style, re.I)
        if m:
            return urljoin("https://t.me", m.group(1).replace("&amp;", "&"))
    for img in node.select(".tgme_widget_message_photo img, .tgme_widget_message_photo_wrap img, .tgme_widget_message_video_thumb img"):
        candidate = img.get("data-src") or img.get("src") or ""
        if candidate and not candidate.startswith("data:"):
            return urljoin("https://t.me", candidate.replace("&amp;", "&"))
    return None


def get_posts(max_pages: int = 3) -> list[dict]:
    """Read several public-preview pages so a busy channel cannot hide the latest poster."""
    posts_by_id: dict[int, dict] = {}
    seen_page_oldest: set[int] = set()
    before: int | None = None

    for page_number in range(max_pages):
        params = {"before": before} if before is not None else None
        response = HTTP.get(PREVIEW, params=params, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        nodes = soup.select(".tgme_widget_message[data-post]")
        if not nodes:
            if page_number == 0:
                raise RuntimeError("Telegram public preview postlarni ko‘rsatmadi.")
            break

        page_ids: list[int] = []
        for node in nodes:
            reference = node.get("data-post", "")
            match = re.search(r"/(\d+)$", reference)
            if not match:
                continue
            post_id = int(match.group(1))
            page_ids.append(post_id)
            if post_id in posts_by_id:
                continue

            photo = poster_photo(node)
            caption_node = node.select_one(".tgme_widget_message_text")
            time_node = node.select_one("time[datetime]")
            posts_by_id[post_id] = {
                "id": post_id,
                "photo": photo,
                "caption": caption_node.get_text(" ", strip=True) if caption_node else "",
                "published": time_node.get("datetime", "") if time_node else "",
            }

        if not page_ids:
            break
        oldest_id = min(page_ids)
        if oldest_id in seen_page_oldest or (before is not None and oldest_id >= before):
            LOG.warning("Telegram pagination keyingi eski sahifaga o‘tmadi; takroriy sahifa to‘xtatildi.")
            break
        seen_page_oldest.add(oldest_id)
        if len(nodes) < 5:
            break
        before = oldest_id

    posts = sorted(posts_by_id.values(), key=lambda post: post["id"], reverse=True)
    photos = [post for post in posts if post["photo"]][:20]
    LOG.info(
        "Telegram preview tekshirildi: %d post, %d rasmli post; eng yangi ID=%s; rasmli IDlar=%s",
        len(posts), len(photos), posts[0]["id"] if posts else "yo‘q",
        ",".join(str(post["id"]) for post in photos[:15]) or "yo‘q",
    )
    return photos

def update_json(start: date, end: date, days: list[dict], post: dict) -> bool:
    if not REPO or not TOKEN:
        raise RuntimeError("GITHUB_REPOSITORY va GITHUB_TOKEN sozlamalari kerak.")
    if len(days) != 7 or (end - start).days != 6:
        raise ValueError("Telegram rasmida aynan 7 kunlik jadval bo‘lishi kerak.")
    prayer_ids = ("fajr", "dhuhr", "asr", "maghrib", "isha")
    for offset, day in enumerate(days):
        expected = (start + timedelta(days=offset)).isoformat()
        if day.get("date") != expected:
            raise ValueError(f"Telegram rasmidagi sana tartibi noto‘g‘ri: {day.get('date')}")
        values = []
        for prayer_id in prayer_ids:
            value = str(day.get(prayer_id, "")).strip()
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                raise ValueError(f"{expected}: {prayer_id} vaqti noto‘g‘ri: {value!r}")
            values.append(int(value[:2]) * 60 + int(value[3:]))
        if any(b <= a for a, b in zip(values, values[1:])):
            raise ValueError(f"{expected}: namoz vaqtlari ketma-ketligi noto‘g‘ri.")

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    get = HTTP.get(API, params={"ref": BRANCH}, headers=headers, timeout=25)
    sha, existing = None, {}
    if get.status_code == 200:
        body = get.json()
        sha = body.get("sha")
        try:
            existing = json.loads(base64.b64decode(body.get("content", "")).decode())
        except Exception:
            existing = {}
        try:
            old_week = date.fromisoformat(existing.get("weekStart", ""))
        except (TypeError, ValueError):
            old_week = None
        if old_week and old_week > start:
            LOG.warning("Eski Telegram posti yangi jadvalni almashtirmaydi.")
            return False
    elif get.status_code != 404:
        raise RuntimeError(f"GitHub jadvalini o‘qishda xato: {get.status_code}")

    if (
        existing.get("weekStart") == start.isoformat()
        and existing.get("days") == days
        and str(existing.get("sourcePostId", "")) == str(post["id"])
    ):
        LOG.info("Telegram rasmidagi haftalik jadval o‘zgarmagan.")
        return False

    first = days[0]
    payload = {
        "schemaVersion": 1,
        "cityId": CITY_ID,
        "cityName": CITY_NAME,
        "timezone": TZ.key,
        "weekStart": start.isoformat(),
        "weekEnd": end.isoformat(),
        "updatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "source": f"Telegram rasmi: @{CHANNEL}/{post['id']}",
        "sourcePostId": str(post["id"]),
        "sourcePublishedAt": post.get("published", ""),
        "sourceTimes": [first[key] for key in prayer_ids],
        "days": days,
    }
    data = base64.b64encode(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    ).decode()
    put = {
        "message": f"Telegram rasmidan namoz jadvali {start}–{end}",
        "content": data,
        "branch": BRANCH,
    }
    if sha:
        put["sha"] = sha
    res = HTTP.put(API, headers=headers, json=put, timeout=30)
    if res.status_code not in (200, 201):
        raise RuntimeError(f"GitHub JSON yangilashda xato: {res.status_code} {res.text[:300]}")
    LOG.info(
        "Telegram rasmidagi 5 vaqtli jadval GitHub’ga yozildi: %s–%s, post #%s",
        start, end, post["id"],
    )
    return True


def main() -> None:
    if not REPO or not TOKEN:
        raise SystemExit("GITHUB_REPOSITORY va GITHUB_TOKEN sozlamalari kiritilmagan.")
    today = datetime.now(TZ).date()
    failures = []
    posts = get_posts()
    if not posts:
        raise RuntimeError("Telegram preview sahifalarida rasmli post topilmadi.")

    for post in posts:
        try:
            published_raw = post.get("published", "")
            if not published_raw:
                raise ValueError("Telegram postining e’lon sanasi aniqlanmadi.")
            published_dt = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            if published_dt.tzinfo is None:
                published_dt = published_dt.replace(tzinfo=TZ)
            published_date = published_dt.astimezone(TZ).date()

            if published_date < today - timedelta(days=21):
                LOG.info("Eski arxiv posti tashlab ketildi: #%s (%s)", post["id"], published_date)
                continue

            image_response = HTTP.get(post["photo"], timeout=18)
            image_response.raise_for_status()
            poster_heading = read_week_heading(image_response.content)
            start, end = parse_week(
                post["caption"] + " " + poster_heading, today, published_date
            )
            LOG.info(
                "Telegram post #%s sanasi aniqlandi: %s–%s. Endi faqat rasmdagi 5 namoz vaqti OCR qilinadi.",
                post["id"], start, end,
            )

            days = read_week_schedule(image_response.content, start, end)
            changed = update_json(start, end, days, post)
            if changed:
                return
            LOG.info("Post #%s uchun rasmiy jadval allaqachon yangilangan.", post["id"])
        except Exception as error:
            detail = f"#{post['id']}: {error}"
            failures.append(detail)
            LOG.info("Post jadval manbasi sifatida qabul qilinmadi: %s", detail)

    details = " | ".join(failures[:12]) if failures else "Yangi tasdiqlangan jadval topilmadi."
    raise RuntimeError("Rasmiy jadval yangilanmadi; avvalgi ma’lumot saqlandi. " + details)

if __name__ == "__main__":
    main()

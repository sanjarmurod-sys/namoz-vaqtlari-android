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
OFFICIAL_PRAYER_API = "https://namoz-vaqti.uz/index.php"
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


def _time_values_from_ocr_text(text: str) -> list[str]:
    """Return distinct OCR time values, ordered chronologically."""
    found: set[str] = set()
    for line in (text or "").splitlines():
        cleaned = DATE_RE.sub(" ", line)
        cleaned = DATE_SAME_MONTH_RE.sub(" ", cleaned)
        # A lone date such as 06.11 must not be mistaken for the time 06:11.
        cleaned = re.sub(r"(?<!\d)\d{1,2}\s*[./]\s*\d{1,2}(?:[./]\s*\d{2,4})?", " ", cleaned)
        for match in TIME_RE.finditer(cleaned):
            found.add(f"{int(match.group(1)):02d}:{int(match.group(2)):02d}")
    return sorted(found, key=lambda value: int(value[:2]) * 60 + int(value[3:]))


def _times_from_ocr_text(text: str) -> list[str] | None:
    """Extract 5/6 distinct chronological prayer times from a weekly poster."""
    values = _time_values_from_ocr_text(text)
    return values if len(values) in (5, 6) else None

def _times_from_ocr_text(text: str) -> list[str] | None:
    """Extract 5/6 chronological prayer times from OCR output, including row/table layouts."""
    found: list[str] = []
    for line in (text or "").splitlines():
        cleaned = DATE_RE.sub(" ", line)
        cleaned = DATE_SAME_MONTH_RE.sub(" ", cleaned)
        # A lone date such as 06.11 must not be mistaken for the time 06:11.
        cleaned = re.sub(r"(?<!\d)\d{1,2}\s*[./]\s*\d{1,2}(?:[./]\s*\d{2,4})?(?!\d)", " ", cleaned)
        for match in TIME_RE.finditer(cleaned):
            found.append(f"{int(match.group(1)):02d}:{int(match.group(2)):02d}")

    if len(found) not in (5, 6):
        return None
    minutes = [int(value[:2]) * 60 + int(value[3:]) for value in found]
    if any(later <= earlier for earlier, later in zip(minutes, minutes[1:])):
        return None
    return found


def _consensus_times(ocr_texts: list[str]) -> list[str] | None:
    """Combine distinct values from independent OCR passes using majority voting."""
    consensus: Counter[str] = Counter()
    single_candidates: list[list[str]] = []
    for text in ocr_texts:
        values = _time_values_from_ocr_text(text)
        for value in values:
            consensus[value] += 1
        if len(values) in (5, 6):
            single_candidates.append(values)

    trusted = [value for value, votes in consensus.items() if votes >= 2]
    if len(trusted) > 6:
        trusted = sorted(
            trusted,
            key=lambda value: (-consensus[value], int(value[:2]) * 60 + int(value[3:])),
        )[:6]
    trusted.sort(key=lambda value: int(value[:2]) * 60 + int(value[3:]))
    if len(trusted) in (5, 6):
        return trusted
    if single_candidates:
        return max(
            single_candidates,
            key=lambda values: (len(values), sum(consensus[v] for v in values)),
        )
    return None


def read_times(image_bytes: bytes) -> tuple[list[str], str]:
    """OCR whole poster/columns and combine repeated time cells from independent passes."""
    original = Image.open(io.BytesIO(image_bytes)).convert("L")
    heading = ImageOps.autocontrast(
        original.resize((original.width * 4, original.height * 4), Image.Resampling.LANCZOS)
    )
    heading_text = pytesseract.image_to_string(heading, lang="eng", config="--oem 1 --psm 11")

    enhanced = ImageOps.autocontrast(original)
    enhanced = ImageEnhance.Contrast(enhanced).enhance(1.6)
    enhanced = enhanced.filter(ImageFilter.UnsharpMask(radius=1, percent=180, threshold=2))

    variants = [("whole", enhanced)]
    midpoint = max(1, enhanced.width // 2)
    variants.extend([
        ("left", enhanced.crop((0, 0, midpoint, enhanced.height))),
        ("right", enhanced.crop((midpoint, 0, enhanced.width, enhanced.height))),
    ])

    attempts: list[str] = []
    ocr_passes: list[str] = []
    for label, variant in variants:
        scale = max(2, min(5, 1900 // max(variant.width, 1)))
        enlarged = variant.resize(
            (variant.width * scale, variant.height * scale), Image.Resampling.LANCZOS
        )
        for psm in (6, 11):
            numeric_text = pytesseract.image_to_string(
                enlarged,
                lang="eng",
                config=f"--oem 1 --psm {psm} -c tessedit_char_whitelist=0123456789:.-/",
            )
            attempts.append(f"[{label}/psm{psm}]\n{numeric_text}")
            ocr_passes.append(numeric_text)

    # Weekly posters repeat the same values in several columns. Majority voting
    # across layouts rejects isolated OCR mistakes while recovering repeated cells.
    trusted = _consensus_times(ocr_passes)
    if trusted:
        return trusted, heading_text + "\n" + "\n".join(attempts)

    details = " | ".join(" ".join(x.split())[:180] for x in attempts[-6:])
    raise ValueError("5 yoki 6 ta turli vaqt tasdiqlanmadi. OCR: " + details)

def read_week_heading(image_bytes: bytes) -> str:
    """Read only the poster heading/date; prayer-time OCR is deliberately not trusted."""
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


def _api_clock(value: object, field: str) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?", text)
    if not match:
        raise ValueError(f"Rasmiy API’da {field} vaqti noto‘g‘ri: {text!r}")
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def fetch_official_days(start: date, end: date) -> list[dict]:
    """Fetch day-by-day Baliqchi values from the official Namoz Vaqti JSON API."""
    rows_by_date: dict[date, dict] = {}
    cursor = date(start.year, start.month, 1)
    months: list[tuple[int, int]] = []
    while cursor <= end:
        months.append((cursor.year, cursor.month))
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)

    field_map = (
        ("fajr", "bomdod"),
        ("sunrise", "quyosh"),
        ("dhuhr", "peshin"),
        ("asr", "asr"),
        ("maghrib", "shom"),
        ("isha", "xufton"),
    )
    for year, month in months:
        response = HTTP.get(
            OFFICIAL_PRAYER_API,
            params={
                "region": CITY_ID,
                "lang": "lotin",
                "period": f"{year:04d}-{month:02d}",
                "format": "json",
            },
            headers={"Accept": "application/json", "Cache-Control": "no-cache"},
            timeout=25,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Rasmiy API JSON obyekt qaytarmadi.")
        region = body.get("meta", {}).get("region", {})
        returned_slug = str(region.get("slug", "")).strip().lower()
        if returned_slug and returned_slug != CITY_ID.lower():
            raise ValueError(
                f"Rasmiy API boshqa hududni qaytardi: {region.get('name', returned_slug)}"
            )
        period_rows = body.get("period_table")
        if not isinstance(period_rows, list) or not period_rows:
            raise ValueError("Rasmiy API’da period_table topilmadi.")

        for row in period_rows:
            try:
                raw_date = str(row.get("date", "")).strip()
                try:
                    row_date = datetime.strptime(raw_date, "%d.%m.%Y").date()
                except ValueError:
                    row_date = date.fromisoformat(raw_date)
                raw_times = row.get("times") or {}
                mapped = {
                    target: _api_clock(raw_times.get(source), source)
                    for target, source in field_map
                }
            except Exception as error:
                raise ValueError(f"Rasmiy API jadval qatori noto‘g‘ri: {error}") from error

            numeric = [int(mapped[key][:2]) * 60 + int(mapped[key][3:]) for key, _ in field_map]
            if any(later <= earlier for earlier, later in zip(numeric, numeric[1:])):
                raise ValueError(f"{row_date} sanasida vaqtlar ketma-ketligi noto‘g‘ri.")
            rows_by_date[row_date] = {"date": row_date.isoformat(), **mapped}

    days = []
    for offset in range((end - start).days + 1):
        current = start + timedelta(days=offset)
        if current not in rows_by_date:
            raise ValueError(f"Rasmiy API’da {current.isoformat()} sanasi yo‘q.")
        days.append(rows_by_date[current])

    # A full weekly table with all six values identical is almost certainly a
    # mistaken OCR extraction or stale/incorrect API response; never publish it.
    signatures = {
        tuple(day[key] for key in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"))
        for day in days
    }
    if len(days) >= 5 and len(signatures) == 1:
        raise ValueError("Haftaning barcha kunlari aynan bir xil; jadval shubhali.")
    LOG.info(
        "Rasmiy API tekshirildi: region=%s, kunlar=%d, birinchi kun=%s, vaqtlar=%s",
        CITY_ID, len(days), days[0]["date"],
        ", ".join(days[0][key] for key in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")),
    )
    return days


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
    if len(days) != (end - start).days + 1:
        raise ValueError("Rasmiy jadvaldagi kunlar soni sana oralig‘iga mos emas.")

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    get = HTTP.get(API, params={"ref": BRANCH}, headers=headers, timeout=25)
    sha = None
    existing = {}
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
        LOG.info("Joriy rasmiy haftalik jadval va Telegram manbasi o‘zgarmagan.")
        return False

    first = days[0]
    source_times = [
        first[key] for key in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")
    ]
    payload = {
        "schemaVersion": 1,
        "cityId": CITY_ID,
        "cityName": CITY_NAME,
        "timezone": TZ.key,
        "weekStart": start.isoformat(),
        "weekEnd": end.isoformat(),
        "updatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "source": f"Rasmiy namoz-vaqti.uz JSON API; Telegram haftalik e’lon: @{CHANNEL}/{post['id']}",
        "scheduleSource": "https://namoz-vaqti.uz/",
        "sourcePostId": str(post["id"]),
        "sourcePublishedAt": post.get("published", ""),
        "sourceTimes": source_times,
        "days": days,
    }
    data = base64.b64encode(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    ).decode()
    put = {
        "message": f"Baliqchi rasmiy namoz jadvali {start}–{end}",
        "content": data,
        "branch": BRANCH,
    }
    if sha:
        put["sha"] = sha
    res = HTTP.put(API, headers=headers, json=put, timeout=30)
    if res.status_code not in (200, 201):
        raise RuntimeError(f"GitHub JSON yangilashda xato: {res.status_code} {res.text[:300]}")
    LOG.info(
        "Rasmiy kunlik jadval GitHub’ga yozildi: %s–%s, Telegram post #%s",
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
                "Telegram e’loni tasdiqlandi: post #%s, %s–%s. Vaqtlar OCR’dan olinmaydi.",
                post["id"], start, end,
            )

            days = fetch_official_days(start, end)
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

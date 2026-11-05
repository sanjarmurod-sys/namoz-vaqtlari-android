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
    consensus: Counter[str] = Counter()
    single_candidates: list[list[str]] = []
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
            values = _time_values_from_ocr_text(numeric_text)
            for value in values:
                consensus[value] += 1
            if len(values) in (5, 6):
                single_candidates.append(values)

    # A weekly poster often repeats one time in every day column. Vote across
    # independent OCR layouts so one noisy glyph (e.g. 13:30) cannot override
    # a value confirmed by the whole image and column crops.
    trusted = [value for value, votes in consensus.items() if votes >= 2]
    if len(trusted) > 6:
        trusted = sorted(
            trusted,
            key=lambda value: (-consensus[value], int(value[:2]) * 60 + int(value[3:])),
        )[:6]
    trusted.sort(key=lambda value: int(value[:2]) * 60 + int(value[3:]))
    if len(trusted) in (5, 6):
        return trusted, heading_text + "\n" + "\n".join(attempts)

    if single_candidates:
        best = max(single_candidates, key=lambda values: (len(values), sum(consensus[v] for v in values)))
        return best, heading_text + "\n" + "\n".join(attempts)

    details = " | ".join(" ".join(x.split())[:180] for x in attempts[-6:])
    raise ValueError("5 yoki 6 ta turli vaqt tasdiqlanmadi. OCR: " + details)

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

def update_json(start: date, end: date, times: list[str], post: dict) -> bool:
    if not REPO or not TOKEN:
        raise RuntimeError("GITHUB_REPOSITORY va GITHUB_TOKEN sozlamalari kerak.")
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
            LOG.warning("Eski post yangi jadvalni almashtirmaydi.")
            return False
    elif get.status_code != 404:
        raise RuntimeError(f"GitHub jadvalini o‘qishda xato: {get.status_code}")

    keys = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha") if len(times) == 6 else (
        "fajr", "dhuhr", "asr", "maghrib", "isha"
    )
    times_obj = dict(zip(keys, times))
    days = [{"date": (start+timedelta(days=i)).isoformat(), **times_obj} for i in range(7)]
    if (
        existing.get("weekStart") == start.isoformat()
        and existing.get("days") == days
        and str(existing.get("sourcePostId", "")) == str(post["id"])
    ):
        LOG.info("Joriy haftalik jadval va manba posti o‘zgarmagan.")
        return False
    payload = {
        "schemaVersion": 1, "cityId": CITY_ID, "cityName": CITY_NAME, "timezone": TZ.key,
        "weekStart": start.isoformat(), "weekEnd": end.isoformat(),
        "updatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "source": f"Ommaviy Telegram preview: @{CHANNEL}/{post['id']}",
        "sourcePostId": str(post["id"]), "sourcePublishedAt": post.get("published", ""),
        "sourceTimes": times, "days": days,
    }
    data = base64.b64encode((json.dumps(payload, ensure_ascii=False, indent=2)+"\n").encode()).decode()
    put = {"message": f"Baliqchi namoz jadvali {start}–{end}", "content": data, "branch": BRANCH}
    if sha:
        put["sha"] = sha
    res = HTTP.put(API, headers=headers, json=put, timeout=30)
    if res.status_code not in (200, 201):
        raise RuntimeError(f"GitHub JSON yangilashda xato: {res.status_code} {res.text[:300]}")
    LOG.info("Jadval yangilandi: %s–%s, Telegram post #%s", start, end, post["id"])
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

            # Avoid OCR'ing old archive posters. A weekly schedule is published
            # close to its effective week; the post date also anchors its year.
            if published_date < today - timedelta(days=21):
                LOG.info("Eski arxiv posti tashlab ketildi: #%s (%s)", post["id"], published_date)
                continue

            image_response = HTTP.get(post["photo"], timeout=18)
            image_response.raise_for_status()
            times, poster_text = read_times(image_response.content)
            start, end = parse_week(post["caption"] + " " + poster_text, today, published_date)
            LOG.info(
                "Yaroqli jadval: post #%s, e’lon=%s, %s–%s; vaqtlar=%s",
                post["id"], published_date, start, end, ", ".join(times),
            )
            changed = update_json(start, end, times, post)
            if changed:
                return
            LOG.info("Post #%s JSON’ni o‘zgartirmadi; keyingi nomzod tekshiriladi.", post["id"])
        except Exception as error:
            detail = f"#{post['id']}: {error}"
            failures.append(detail)
            LOG.info("Post jadval sifatida qabul qilinmadi: %s", detail)

    details = " | ".join(failures[:12]) if failures else "Yangi tasdiqlangan jadval topilmadi."
    raise RuntimeError("Yangi jadval tasdiqlanmadi; eski JSON saqlandi. " + details)

if __name__ == "__main__":
    main()

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
from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pytesseract
import requests
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
DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[.,/]\s*(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*[.,/]\s*(\d{1,2})(?!\d)")
TIME_RE = re.compile(r"(?<!\d)(2[0-3]|[01]?\d)\s*[-:.,٫]\s*([0-5]\d)(?!\d)")
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "Mozilla/5.0 (compatible; NamozVaqtlari/1.0)", "Accept": "text/html,*/*"})


def parse_week(text: str, today: date | None = None) -> tuple[date, date]:
    today = today or datetime.now(TZ).date()
    m = DATE_RE.search(text or "")
    if not m:
        raise ValueError("Hafta sanasi topilmadi (masalan, 30.10-05.11).")
    sd, sm, ed, em = map(int, m.groups())
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            start = date(year, sm, sd)
            end = date(year + (1 if (em, ed) < (sm, sd) else 0), em, ed)
        except ValueError:
            continue
        if (end - start).days == 6:
            distance = 0 if start <= today <= end else min(abs((start-today).days), abs((end-today).days))
            candidates.append((distance, start, end))
    if not candidates:
        raise ValueError("Sana oralig‘i 7 kunlik haftaga mos kelmadi.")
    _, start, end = min(candidates, key=lambda x: x[0])
    if end < today - timedelta(days=2) or start > today + timedelta(days=14):
        raise ValueError("Afishadagi hafta eskirgan yoki juda uzoq kelajakda.")
    return start, end


def read_times(image_bytes: bytes) -> tuple[list[str], str]:
    """Read the table-style poster with one sparse-text OCR pass.

    PSM 11 separates the prayer names and times into columns. We merge words
    on the same horizontal line, then keep only lines containing one valid time.
    """
    image = Image.open(io.BytesIO(image_bytes)).convert("L")
    scale = max(4, min(8, 1800 // max(image.width, 1)))
    image = image.resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image).enhance(1.6)
    image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=2))

    data = pytesseract.image_to_data(
        image, lang="eng", config="--oem 1 --psm 11", output_type=Output.DICT
    )
    words_by_y: list[dict] = []
    for i, raw in enumerate(data["text"]):
        token = (raw or "").strip()
        try:
            confidence = float(data["conf"][i])
        except (TypeError, ValueError):
            confidence = -1
        if not token or confidence < 20:
            continue
        center_y = int(data["top"][i]) + int(data["height"][i]) // 2
        row = next((item for item in words_by_y if abs(item["y"] - center_y) <= max(12, int(image.height * 0.025))), None)
        if row is None:
            row = {"y": center_y, "words": []}
            words_by_y.append(row)
        row["words"].append((int(data["left"][i]), token, confidence))

    words_by_y.sort(key=lambda item: item["y"])
    ocr_lines: list[str] = []
    times: list[str] = []
    for row in words_by_y:
        line = " ".join(word[1] for word in sorted(row["words"], key=lambda item: item[0]))
        ocr_lines.append(line)
        compact = re.sub(r"\s+", "", line)
        if DATE_RE.search(compact):
            continue
        matches = list(TIME_RE.finditer(line))
        if len(matches) != 1:
            continue
        match = matches[0]
        hour = int(match.group(1))
        minute = int(match.group(2))
        times.append(f"{hour:02d}:{minute:02d}")

    if len(times) not in (5, 6):
        raise ValueError(f"5 yoki 6 ta vaqt o‘qilmadi (topildi: {len(times)}): {' | '.join(ocr_lines[:12])}")
    minutes = [int(value[:2]) * 60 + int(value[3:]) for value in times]
    if any(later <= earlier for earlier, later in zip(minutes, minutes[1:])):
        raise ValueError("Vaqtlar ketma-ketligi shubhali.")
    return times, "\n".join(ocr_lines)


def poster_photo(node) -> str | None:
    for el in node.select(".tgme_widget_message_photo_wrap, .tgme_widget_message_video_thumb"):
        m = re.search(r"url\(['\"]?(.*?)['\"]?\)", el.get("style", ""), re.I)
        if m:
            return urljoin("https://t.me", m.group(1).replace("&amp;", "&"))
    img = node.select_one(".tgme_widget_message_photo img")
    if img:
        return urljoin("https://t.me", img.get("src") or img.get("data-src") or "")
    return None


def get_posts() -> list[dict]:
    r = HTTP.get(PREVIEW, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    nodes = soup.select(".tgme_widget_message[data-post]")
    if not nodes:
        raise RuntimeError("Telegram public preview postlarni ko‘rsatmadi.")
    posts = []
    for n in nodes:
        photo = poster_photo(n)
        ref = n.get("data-post", "")
        m = re.search(r"/(\d+)$", ref)
        if not photo or not m:
            continue
        cap = n.select_one(".tgme_widget_message_text")
        tm = n.select_one("time[datetime]")
        posts.append({
            "id": int(m.group(1)),
            "photo": photo,
            "caption": cap.get_text(" ", strip=True) if cap else "",
            "published": tm.get("datetime", "") if tm else "",
        })
    return sorted(posts, key=lambda p: p["id"], reverse=True)


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
        if str(existing.get("sourcePostId", "")) == str(post["id"]):
            LOG.info("Bu Telegram posti oldin qo‘llangan: #%s", post["id"])
            return False
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
    if existing.get("weekStart") == start.isoformat() and existing.get("days") == days:
        LOG.info("Joriy haftalik jadval o‘zgarmagan.")
        return False
    payload = {
        "schemaVersion": 1, "cityId": CITY_ID, "cityName": CITY_NAME, "timezone": TZ.key,
        "weekStart": start.isoformat(), "weekEnd": end.isoformat(),
        "updatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "source": f"Ommaviy Telegram preview: @{CHANNEL}/{post['id']}",
        "sourcePostId": str(post["id"]), "sourcePublishedAt": post["published"],
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
    for post in posts:
        try:
            img = HTTP.get(post["photo"], timeout=30)
            img.raise_for_status()
            times, poster_text = read_times(img.content)
            start, end = parse_week(post["caption"] + " " + poster_text, today)
            update_json(start, end, times, post)
            return
        except Exception as e:
            failures.append(f"#{post['id']}: {e}")
    details = " | ".join(failures[:4]) if failures else "Rasmli jadval yo‘q."
    raise RuntimeError("Yaroqli jadval topilmadi, eski JSON saqlandi. " + details)


if __name__ == "__main__":
    main()

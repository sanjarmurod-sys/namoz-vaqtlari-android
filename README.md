# Namoz Vaqtlari — Android

Baliqchi tumani uchun o‘zbek tilidagi namoz vaqtlari, azon eslatmalari, qibla kompassi va tasbeh ilovasi.

## Yuklab olish

- **Debug APK:** GitHub Actions → [Build Android APK](https://github.com/sanjarmurod-sys/namoz-vaqtlari-android/actions/workflows/build-apk.yml) → eng so‘nggi muvaffaqiyatli run → Artifacts → `Namoz-Vaqtlari-APK`.
- **Jadval JSON:** https://raw.githubusercontent.com/sanjarmurod-sys/namoz-vaqtlari-android/main/data/prayer-times.json
- **Telegram ommaviy manba:** https://t.me/namozvaqti365

## Ilova xususiyatlari

- O‘zbekcha interfeys va Baliqchi tumani uchun boshlang‘ich sozlama.
- Bomdod, Peshin, Asr, Shom, Xufton va quyosh chiqishi.
- Hisoblash usulini tanlash, Hanafi/standart Asr sozlamasi, joylashuv va qo‘lda vaqt tuzatish.
- Har namoz uchun azon yoqish/o‘chirish, audio fayl tanlash va sinovdan o‘tkazish.
- Qibla kompassi (telefon sensori va joylashuvdan foydalanadi).
- Tasbeh: Subhanalloh, Alhamdulillah, Allohu Akbar, shaxsiy zikrlar, hisoblagich, tovush va vibratsiya.
- Namoz jadvalini internet orqali yangilash va mahalliy xotirada saqlash.

## Telegram’dan avtomatik jadval yangilanishi

Kanal sizniki bo‘lishi yoki unga administrator bo‘lishingiz shart emas. Ilova jadvalni Telegram’ning ochiq web-preview sahifasi — `https://t.me/s/namozvaqti365` — orqali tekshiradigan GitHub Actions jarayonidan oladi.

- Workflow taxminan har 3 soatda ommaviy kanalni tekshiradi.
- Jadval rasmi topilsa, OCR orqali sana va namoz vaqtlarini ajratadi.
- Faqat 7 kunlik sana oralig‘i va 5/6 vaqt to‘g‘ri o‘qilganida JSON yangilanadi.
- Eskirgan jadval yangiroq jadvalni almashtira olmaydi.
- Rasm yoki sana noaniq bo‘lsa, avvalgi JSON saqlanadi.
- Android ilovasi jadvalni ochilganda yangilaydi va WorkManager orqali davriy ravishda tekshiradi.

**Tasdiqlangan manba posti:** `@namozvaqti365/1063`. Undagi 30.10–05.11 haftalik afishadan o‘qilgan vaqtlar: Bomdod 06:10, Peshin 13:00, Asr 15:40, Shom 17:20, Xufton 19:05.

Afishada hafta uchun bitta vaqtlar to‘plami ko‘rsatilgani sababli JSON’da ushbu qiymatlar 7 sanaga yozilgan. Bu har bir kun uchun alohida astronomik jadval ekanini anglatmaydi. Keyingi haftaning afishasi chiqqach, parser yangi sana oralig‘ini olishi kerak.

## APK’ni o‘rnatish

1. Actions sahifasidan `Namoz-Vaqtlari-APK` artefakt ZIP’ini yuklab oling.
2. ZIP’ni ochib, `app-debug.apk` faylini Android telefoniga ko‘chiring.
3. APK’ni oching va Android so‘rasa, ushbu manbadan ilova o‘rnatishga ruxsat bering.
4. Ilova ichida joylashuv, bildirishnoma va aniq signal ruxsatlarini bering.

Bu hozircha **debug APK**. Google Play uchun alohida release imzolash kaliti bilan signed release build kerak bo‘ladi. Agar shaxsiy azon MP3 fayli tanlanmagan bo‘lsa, ilova qurilmaning standart signal ohangidan foydalanishi mumkin; bu standart ohang haqiqiy azon bo‘lishi kafolatlanmaydi.

## Loyiha tuzilishi

- `app/` — Kotlin Android ilovasi va HTML/CSS/JS WebView interfeysi.
- `data/prayer-times.json` — barcha o‘rnatilgan ilovalar uchun markaziy jadval.
- `telegram_sync/public_channel_sync.py` — ommaviy Telegram preview va OCR parseri.
- `telegram_sync/tests/` — sana, preview va OCR sinovlari.
- `.github/workflows/sync-public-telegram.yml` — jadval yangilash workflow’i.
- `.github/workflows/build-apk.yml` — APK yig‘ish workflow’i.

## Joriy tekshiruv holati

- [x] Yangi `namoz-vaqtlari-android` repository yaratildi; oldingi `namoz-app` repository o‘zgartirilmagan.
- [x] Kotlin/HTML Android ilovasi manbalari joylandi.
- [x] Ommaviy Telegram kanalidan post #1063 muvaffaqiyatli o‘qildi.
- [x] OCR parser sinovlari GitHub Actions’da o‘tdi.
- [x] JSON’da jadval manbasi va post ID saqlandi.
- [x] Android debug APK GitHub Actions’da muvaffaqiyatli yig‘ildi va artefaktga yuklandi.
- [ ] Turli Android telefonlarda amaliy sinov va real azon audiosi/aniq signal ruxsatlarini tekshirish.


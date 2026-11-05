# Namoz Vaqtlari — Android

Baliqchi tumani uchun o‘zbek tilidagi namoz vaqtlari, azon eslatmalari, qibla kompassi va tasbeh ilovasi.

## Yuklab olish

- **Debug APK:** GitHub Actions → [Build Android APK](https://github.com/sanjarmurod-sys/namoz-vaqtlari-android/actions/workflows/build-apk.yml) → eng so‘nggi muvaffaqiyatli run → Artifacts → `Namoz-Vaqtlari-APK`.
- **Jadval JSON:** https://raw.githubusercontent.com/sanjarmurod-sys/namoz-vaqtlari-android/main/data/prayer-times.json
- **Telegram ommaviy manba:** https://t.me/namozvaqti365

## Ilova xususiyatlari

- O‘zbekcha interfeys va Baliqchi tumani uchun boshlang‘ich sozlama.
- Bomdod, Peshin, Asr, Shom va Xufton.
- Hisoblash usulini tanlash, Hanafi/standart Asr sozlamasi, joylashuv va qo‘lda vaqt tuzatish.
- Har namoz uchun azon yoqish/o‘chirish, audio fayl tanlash va sinovdan o‘tkazish.
- Premium Qibla kompassi: Ka’ba tasvirli yo‘nalish belgisi, telefon sensori va joylashuvdan foydalanadi.
- 33 ta marjonli interaktiv tasbeh, 10 xil ovoz va 10 xil vizual uslub, ovozni oldindan tinglash va vibratsiya.
- Qibla yo‘nalishi topilganda maxsus qisqa audio tasdiq.
- Kattaroq shriftlar, qulay namoz kartochkalari va silliq animatsiyalar.
- Ilova ichiga joylangan Manrope shrift oilasi — barcha sahifalarda internetga bog‘liq bo‘lmagan tipografika.
- Namoz jadvalini internet orqali yangilash va mahalliy xotirada saqlash.

## Telegram orqali haftalik jadvalni yangilash

GitHub Actions har 3 soatda `https://t.me/s/namozvaqti365` ochiq Telegram preview sahifasini tekshiradi.

- Hafta sanasi Telegram postidagi rasm sarlavhasidan aniqlanadi.
- 7 kunning har biri uchun **Bomdod, Peshin, Asr, Shom va Xufton** vaqtlari bevosita Telegram rasmining o‘zidan OCR orqali olinadi.
- OCR umumiy vaqtlar ro‘yxatini saralamaydi: jadvalning joylashuvi bo‘yicha 7 kun va har bir kun uchun 5 ta vaqt ajratiladi.
- Quyosh chiqishi qiymati olinmaydi va jadvalga yozilmaydi.
- Rasmda barcha 35 ta vaqt ishonchli aniqlanmasa, noto‘g‘ri jadval e’lon qilinmaydi; avvalgi ma’lumot saqlanadi.

**Vaqtlar uchun yagona manba:** `@namozvaqti365` Telegram kanalidagi haftalik rasm. Tashqi namoz API yoki boshqa saytlardan vaqt olinmaydi.
## APK’ni o‘rnatish

1. Actions sahifasidan `Namoz-Vaqtlari-APK` artefakt ZIP’ini yuklab oling.
2. ZIP’ni ochib, `app-debug.apk` faylini Android telefoniga ko‘chiring.
3. APK’ni oching va Android so‘rasa, ushbu manbadan ilova o‘rnatishga ruxsat bering.
4. Ilova ichida joylashuv, bildirishnoma va aniq signal ruxsatlarini bering.

Bu hozircha **debug APK**. Google Play uchun alohida release imzolash kaliti bilan signed release build kerak bo‘ladi. Agar shaxsiy azon MP3 fayli tanlanmagan bo‘lsa, ilova qurilmaning standart signal ohangidan foydalanishi mumkin; bu standart ohang haqiqiy azon bo‘lishi kafolatlanmaydi.

## Loyiha tuzilishi

- `app/` — Kotlin Android ilovasi va HTML/CSS/JS WebView interfeysi.
- `data/prayer-times.json` — barcha o‘rnatilgan ilovalar uchun markaziy jadval.
- `telegram_sync/public_channel_sync.py` — Telegram haftasini aniqlash va rasmiy Telegram rasmining OCR tahlili orqali jadval olish.
- `telegram_sync/tests/` — sana, preview va OCR sinovlari.
- `.github/workflows/sync-public-telegram.yml` — jadval yangilash workflow’i.
- `.github/workflows/build-apk.yml` — APK yig‘ish workflow’i.

## Joriy tekshiruv holati

- [x] Yangi `namoz-vaqtlari-android` repository yaratildi; oldingi `namoz-app` repository o‘zgartirilmagan.
- [x] Kotlin/HTML Android ilovasi manbalari joylandi.
- [x] Ommaviy Telegram kanalidan post #1065 orqali yangi hafta aniqlandi.
- [x] Kunlik jadval rasmiy JSON API’dan olindi va hudud/sana/vaqt tekshiruvlaridan o‘tdi.
- [x] JSON’da har bir kunning alohida vaqtlari va Telegram manba posti saqlandi.
- [x] Android debug APK GitHub Actions’da muvaffaqiyatli yig‘ildi va artefaktga yuklandi.
- [ ] Turli Android telefonlarda amaliy sinov va real azon audiosi/aniq signal ruxsatlarini tekshirish.


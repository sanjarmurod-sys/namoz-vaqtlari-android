# Namoz Vaqtlari — Baliqchi tumani

Ilova namoz vaqtlarini quyidagi ommaviy Telegram kanali e'lon qiladigan haftalik jadvaldan olishi uchun mo‘ljallangan:

- Manba kanal: https://t.me/namozvaqti365
- Manba hudud: Baliqchi tumani
- Jadval JSON: https://raw.githubusercontent.com/sanjarmurod-sys/namoz-vaqtlari-android/main/data/prayer-times.json

## Kanalga admin huquqi kerak emas

Kanal foydalanuvchiga tegishli emasligi va u yerga bot administrator sifatida qo‘shilmasligi sababli Telegram Bot API orqali kanal postlarini to‘g‘ridan-to‘g‘ri olish yo‘li ishlatilmaydi.

Rejalashtirilgan avtomatik yangilash usuli — Telegram’ning ommaviy web preview sahifasini (https://t.me/s/namozvaqti365) va undagi oxirgi postlarning matn/media havolalarini tekshirish. Jadval rasmi topilsa, OCR orqali besh vaqt ajratiladi, sana oralig‘i tekshiriladi va keyin GitHub’dagi JSON yangilanadi.

Bu faqat Telegram ushbu kanal uchun ommaviy web preview’ni taqdim etsa ishlaydi. Preview vaqtincha ochilmasa, HTML tuzilmasi o‘zgarsa yoki jadval rasmidan sana/vaqt ishonchli ajralmasa, tizim eski jadvalni saqlab qolishi va qo‘lda tekshirishni talab qilishi kerak. Hech qanday kanal adminligi yoki kanal egasining tokeni talab qilinmaydi.

## Dastlabki jadval namunasi

Foydalanuvchi yuborgan 30.10–05.11 afishasidan o‘qilgan qiymatlar:

| Namoz | Vaqt |
|---|---:|
| Bomdod | 06:10 |
| Peshin | 13:00 |
| Asr | 15:40 |
| Shom | 17:20 |
| Xufton | 19:05 |

Haftalik afishada bitta vaqtlar to‘plami ko‘rsatilgani sababli ushbu qiymatlar 7 kunga boshlang‘ich jadval sifatida nusxalangan. Bu har bir sana uchun alohida astronomik hisob-kitob tasdig‘i emas.

## Jadval manbasi

data/prayer-times.json ilovaga quyidagi ma'lumotni beradi:

- cityId: baliqchi
- cityName: Baliqchi tumani
- timezone: Asia/Tashkent
- days: har bir sana uchun Bomdod, Peshin, Asr, Shom, Xufton

## Hozirgi holat

- [x] Alohida namoz-vaqtlari-android repository ochilgan.
- [x] Boshlang‘ich haftalik jadval JSON’ga yozilgan.
- [x] Hudud Andijon deb emas, Baliqchi tumani deb belgilangan.
- [x] Kanal adminligi talab qilinmaydigan ommaviy web-preview usuli tanlangan.
- [x] Ommaviy web-preview sahifasini tekshiradigan va jadval rasmini OCR bilan o‘qiydigan Python skripti joylandi (`telegram_sync/public_channel_sync.py`).
- [x] GitHub Contents API orqali JSON yangilash kodi qo‘shildi; GitHub Actions tokenidan foydalanadi.
- [x] Sana/vaqt tekshiruvlari, eski jadvalni himoyalash va parser uchun boshlang‘ich testlar qo‘shildi.
- [ ] Android Kotlin/WebView manba kodini ushbu repository’ga to‘liq joylash.
- [ ] GitHub Actions orqali APK yig‘ish va natijani tekshirish.

**Muhim holat:** ommaviy Telegram preview scraperi, OCR parseri, testlar va GitHub Actions workflow joylandi. Workflow GitHub’da sinovdan o‘tkazilmoqda; Telegram preview’ni amalda yuklash muvaffaqiyatli tasdiqlanmaguncha avtomatik yangilanish ishlayapti deb hisoblamang. Android Kotlin/WebView manba fayllari hali ushbu repository’ga to‘liq joylanmagan va APK hali yig‘ilmagan.

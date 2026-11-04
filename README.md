# Namoz Vaqtlari — Andijon

Ushbu repository hozirda ilova olishi uchun namoz vaqtlarining JSON manba faylini saqlaydi.

## Manbalar

- Telegram jadval kanali: https://t.me/namozvaqti365
- Android ilova loyihasi uchun raw JSON: https://raw.githubusercontent.com/sanjarmurod-sys/namoz-vaqtlari-android/main/data/prayer-times.json

## Dastlabki jadval

Foydalanuvchi yuborgan 30.10–05.11 haftalik afishasidagi vaqtlar 7 kunga yozildi:

| Namoz | Vaqt |
|---|---:|
| Bomdod | 06:10 |
| Peshin | 13:00 |
| Asr | 15:40 |
| Shom | 17:20 |
| Xufton | 19:05 |

**Eslatma:** afishada haftalik bitta qiymatlar to‘plami berilgan. Shu sabab JSON’da ayni vaqtlar 7 sananing har biriga qo‘yilgan; bu har bir kun uchun alohida tasdiqlangan astronomik jadval degani emas. Keyingi kanal afishasi kelgach, yangi hafta ma’lumotlari yangilanishi kerak.

## JSON shakli

```json
{
  "schemaVersion": 1,
  "cityId": "andijan",
  "cityName": "Andijon",
  "timezone": "Asia/Tashkent",
  "weekStart": "2026-10-30",
  "weekEnd": "2026-11-05",
  "days": [
    {
      "date": "2026-10-30",
      "fajr": "06:10",
      "dhuhr": "13:00",
      "asr": "15:40",
      "maghrib": "17:20",
      "isha": "19:05"
    }
  ]
}
```

## Joriy holat

- [x] Yangi repository alohida yaratildi; eski `namoz-app` repository’ga o‘zgartirish kiritilmadi.
- [x] Boshlang‘ich JSON jadvali qo‘shildi.
- [ ] Android Kotlin/WebView manba fayllarini ushbu repository’ga joylash.
- [ ] GitHub Actions orqali debug APK yig‘ib tekshirish.
- [ ] Telegram bot yaratish, uni `@namozvaqti365` kanaliga administrator qilish.
- [ ] Render’da `TELEGRAM_BOT_TOKEN` va GitHub fine-grained tokenini maxfiy environment variable sifatida sozlash.

**Muhim:** Telegram avtomatik yangilanishi hozircha faol emas. Bot tokeni va kanal admin huquqi sozlanmaguncha GitHub JSON o‘z-o‘zidan yangilanmaydi. Android APK ham hozircha yig‘ilmagan.

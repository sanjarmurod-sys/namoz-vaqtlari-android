package uz.namozvaqtlari.app

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId

object AlarmScheduler {
    private const val PREFS = "namoz"
    private const val SCHEDULE_KEY = "scheduled_json"

    fun schedule(context: Context, json: String) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        cancelSaved(context, prefs.getString(SCHEDULE_KEY, null))
        prefs.edit().putString(SCHEDULE_KEY, json).apply()
        scheduleJson(context, json)
    }


    /**
     * A fresh Telegram/GitHub schedule replaces matching alarms but preserves the rest
     * of the locally calculated 30-day alarm list and each manually locked prayer time.
     */
    fun mergeRemoteSchedule(context: Context, remote: JSONObject) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val settings = try { JSONObject(prefs.getString("web_settings_json", "{}") ?: "{}") }
                       catch (_: Exception) { JSONObject() }
        if (!settings.optBoolean("telegramSyncEnabled", true)) return
        val remoteCity = remote.optString("cityId", "")
        val selectedCity = settings.optString("city", "")
        if (remoteCity != "all" && remoteCity != selectedCity) return

        val saved = prefs.getString(SCHEDULE_KEY, null) ?: return
        val current = try { JSONArray(saved) } catch (_: Exception) { return }
        val byId = LinkedHashMap<String, JSONObject>()
        for (i in 0 until current.length()) {
            val item = current.optJSONObject(i) ?: continue
            byId[item.optString("id")] = JSONObject(item.toString())
        }
        val manual = settings.optJSONObject("manual") ?: JSONObject()
        val days = remote.optJSONArray("days") ?: return
        val zone = try { ZoneId.of(remote.optString("timezone", "Asia/Tashkent")) }
                    catch (_: Exception) { ZoneId.systemDefault() }
        var changed = false
        val prayerKeys = listOf("fajr", "dhuhr", "asr", "maghrib", "isha")
        for (i in 0 until days.length()) {
            val day = days.optJSONObject(i) ?: continue
            val date = try { LocalDate.parse(day.optString("date")) } catch (_: Exception) { continue }
            for (prayer in prayerKeys) {
                if (manual.optBoolean(prayer, false)) continue
                val itemId = "${date.year}-${date.monthValue}-${date.dayOfMonth}-$prayer"
                val alarm = byId[itemId] ?: continue
                val clock = day.optString(prayer, "")
                val localTime = try { LocalTime.parse(clock) } catch (_: Exception) { continue }
                alarm.put("at", date.atTime(localTime).atZone(zone).toInstant().toEpochMilli())
                byId[itemId] = alarm
                changed = true
            }
        }
        if (changed) {
            val merged = JSONArray()
            byId.values.forEach { merged.put(it) }
            schedule(context, merged.toString())
        }
    }

    fun rescheduleSaved(context: Context) {
        val json = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(SCHEDULE_KEY, null) ?: return
        scheduleJson(context, json)
    }

    private fun cancelSaved(context: Context, json: String?) {
        if (json.isNullOrBlank()) return
        try {
            val array = JSONArray(json)
            val manager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            for (i in 0 until array.length()) {
                val item = array.getJSONObject(i)
                val id = item.optString("id")
                val pending = pendingIntent(context, id, null, null)
                manager.cancel(pending)
            }
        } catch (_: Exception) { }
    }

    private fun scheduleJson(context: Context, json: String) {
        val array = JSONArray(json)
        val manager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val now = System.currentTimeMillis()
        for (i in 0 until array.length()) {
            val item = array.getJSONObject(i)
            if (!item.optBoolean("enabled", true)) continue
            val at = item.optLong("at", 0L)
            if (at <= now) continue
            val id = item.optString("id", "namoz_$i")
            val name = item.optString("name", "Namoz vaqti")
            val voice = item.optString("voice", "1")
            val pending = pendingIntent(context, id, name, voice)
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && !manager.canScheduleExactAlarms()) {
                    manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pending)
                } else {
                    manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pending)
                }
            } catch (_: SecurityException) {
                manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pending)
            }
        }
    }

    private fun pendingIntent(context: Context, id: String, name: String?, voice: String?): PendingIntent {
        val intent = Intent(context, PrayerAlarmReceiver::class.java).apply {
            action = "uz.namozvaqtlari.PRAYER_ALARM.$id"
            if (name != null) putExtra(AzanPlaybackService.EXTRA_PRAYER_NAME, name)
            if (voice != null) putExtra(AzanPlaybackService.EXTRA_VOICE_SLOT, voice)
        }
        return PendingIntent.getBroadcast(
            context,
            id.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }
}

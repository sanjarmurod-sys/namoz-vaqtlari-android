package uz.namozvaqtlari.app

import android.content.Context
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class PrayerSyncWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        return try {
            PrayerSyncRepository.refresh(applicationContext)
            Result.success()
        } catch (_: Exception) {
            if (runAttemptCount < 3) Result.retry() else Result.failure()
        }
    }
}

object PrayerSyncRepository {
    private const val PREFS = "namoz"
    private const val REMOTE_KEY = "remote_prayer_json"
    private const val UPDATED_KEY = "remote_prayer_updated_ms"

    /** Downloads a validated schedule, stores it locally, and updates already scheduled alarms. */
    fun refresh(context: Context): String? {
        val endpoint = PrayerSyncConfig.JSON_URL
        if (endpoint.contains("USERNAME") || endpoint.contains("REPOSITORY")) return null

        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 12_000
            readTimeout = 18_000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Cache-Control", "no-cache")
            setRequestProperty("User-Agent", "NamozVaqtlari-Android")
        }
        val payload = try {
            val code = connection.responseCode
            if (code !in 200..299) throw IllegalStateException("Server javobi: $code")
            connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            connection.disconnect()
        }

        val root = JSONObject(payload)
        require(root.optInt("schemaVersion", 1) == 1) { "Jadval formati qo'llab-quvvatlanmaydi" }
        require(root.optString("cityId") == "baliqchi") { "Faqat Baliqchi tumani jadvali qabul qilinadi" }
        require(root.optString("source").startsWith("Telegram rasmi: @namozvaqti365/")) { "Jadval manbasi tasdiqlangan Telegram kanali emas" }
        require(root.optString("sourcePostId").isNotBlank()) { "Telegram post ID mavjud emas" }
        val days = root.optJSONArray("days") ?: throw IllegalArgumentException("Jadvalda days ro'yxati yo'q")
        require(days.length() == 7) { "Telegram jadvali aynan 7 kun bo'lishi kerak" }
        val prayerKeys = listOf("fajr", "dhuhr", "asr", "maghrib", "isha")
        var previousDate = ""
        for (i in 0 until days.length()) {
            val day = days.getJSONObject(i)
            val date = day.optString("date")
            require(date.matches(Regex("\\d{4}-\\d{2}-\\d{2}"))) { "Sana noto'g'ri" }
            require(previousDate.isEmpty() || date > previousDate) { "Jadval sanalari tartibi noto'g'ri" }
            previousDate = date
            var previousMinutes = -1
            prayerKeys.forEach { key ->
                val time = day.optString(key)
                require(time.matches(Regex("(?:[01]\\d|2[0-3]):[0-5]\\d"))) { "$key vaqti noto'g'ri" }
                val minutes = time.substring(0, 2).toInt() * 60 + time.substring(3, 5).toInt()
                require(minutes > previousMinutes) { "Namoz vaqtlari ketma-ketligi noto'g'ri" }
                previousMinutes = minutes
            }
        }

        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val previous = prefs.getString(REMOTE_KEY, null)
        if (previous != payload) {
            prefs.edit().putString(REMOTE_KEY, payload).putLong(UPDATED_KEY, System.currentTimeMillis()).apply()
            AlarmScheduler.mergeRemoteSchedule(context, root)
        }
        return payload
    }

    fun cached(context: Context): String? {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val payload = prefs.getString(REMOTE_KEY, null) ?: return null
        val trusted = try {
            val root = JSONObject(payload)
            root.optString("cityId") == "baliqchi" &&
                root.optString("source").startsWith("Telegram rasmi: @namozvaqti365/") &&
                root.optJSONArray("days")?.length() == 7
        } catch (_: Exception) {
            false
        }
        if (!trusted) {
            prefs.edit().remove(REMOTE_KEY).remove(UPDATED_KEY).apply()
            return null
        }
        return payload
    }

    fun lastUpdated(context: Context): Long =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getLong(UPDATED_KEY, 0L)
}

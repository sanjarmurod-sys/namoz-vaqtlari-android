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
        require(root.optString("cityId").isNotBlank()) { "Jadvalda cityId yo'q" }
        val days = root.optJSONArray("days") ?: throw IllegalArgumentException("Jadvalda days ro'yxati yo'q")
        require(days.length() in 1..10) { "Jadvaldagi kunlar soni noto'g'ri" }
        for (i in 0 until days.length()) {
            val day = days.getJSONObject(i)
            require(day.optString("date").matches(Regex("\\d{4}-\\d{2}-\\d{2}"))) { "Sana noto'g'ri" }
            listOf("fajr", "dhuhr", "asr", "maghrib", "isha").forEach { key ->
                val time = day.optString(key)
                require(time.matches(Regex("\\d{1,2}:\\d{2}"))) { "$key vaqti noto'g'ri" }
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

    fun cached(context: Context): String? =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(REMOTE_KEY, null)

    fun lastUpdated(context: Context): Long =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getLong(UPDATED_KEY, 0L)
}

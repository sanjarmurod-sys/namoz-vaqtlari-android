package uz.namozvaqtlari.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build

class PrayerAlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val serviceIntent = Intent(context, AzanPlaybackService::class.java).apply {
            putExtra(AzanPlaybackService.EXTRA_PRAYER_NAME, intent.getStringExtra(AzanPlaybackService.EXTRA_PRAYER_NAME) ?: "Namoz vaqti")
            putExtra(AzanPlaybackService.EXTRA_VOICE_SLOT, intent.getStringExtra(AzanPlaybackService.EXTRA_VOICE_SLOT) ?: "1")
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(serviceIntent)
            else context.startService(serviceIntent)
        } catch (_: Exception) {
            // Qurilma xizmatni boshlashga ruxsat bermasa, jadval ilova keyingi ochilganda qayta tiklanadi.
        }
    }
}

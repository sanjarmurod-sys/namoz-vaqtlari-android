package uz.namozvaqtlari.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.Build
import android.os.IBinder
import android.widget.Toast
import java.io.File

class AzanPlaybackService : Service() {
    companion object {
        const val EXTRA_PRAYER_NAME = "prayer_name"
        const val EXTRA_VOICE_SLOT = "voice_slot"
        private const val CHANNEL_ID = "namoz_azan_playback"
        private const val NOTIFICATION_ID = 7401
        private const val ACTION_STOP = "uz.namozvaqtlari.STOP_AZAN"
    }

    private var player: MediaPlayer? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopPlayback()
            stopSelf()
            return START_NOT_STICKY
        }

        val prayerName = intent?.getStringExtra(EXTRA_PRAYER_NAME) ?: "Namoz vaqti"
        val slot = intent?.getStringExtra(EXTRA_VOICE_SLOT) ?: "1"
        startForeground(NOTIFICATION_ID, buildNotification(prayerName))
        stopPlayback()
        playSelectedVoice(slot)
        return START_NOT_STICKY
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val channel = NotificationChannel(CHANNEL_ID, "Azon ovozi", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Namoz vaqti kelganda azon ovozini ijro etish xabarnomasi"
                setSound(null, null)
                enableVibration(false)
            }
            manager.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(prayerName: String): Notification {
        val openIntent = PendingIntent.getActivity(
            this, 7410, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val stopIntent = PendingIntent.getService(
            this, 7411, Intent(this, AzanPlaybackService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val builder = Notification.Builder(this, CHANNEL_ID)
        return builder
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Azon vaqti keldi")
            .setContentText("$prayerName namozi vaqti")
            .setContentIntent(openIntent)
            .setOngoing(true)
            .setCategory(Notification.CATEGORY_ALARM)
            .addAction(Notification.Action.Builder(null, "To‘xtatish", stopIntent).build())
            .build()
    }

    private fun playSelectedVoice(slot: String) {
        val prefs = getSharedPreferences("namoz", Context.MODE_PRIVATE)
        val filePath = prefs.getString("voice_$slot", null)
        val customFile = filePath?.let { File(it) }
        val sourceUri = if (customFile?.exists() == true) null else
            (RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
                ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION))

        try {
            val media = MediaPlayer()
            player = media
            media.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
            )
            if (customFile?.exists() == true) media.setDataSource(customFile.absolutePath)
            else if (sourceUri != null) media.setDataSource(this, sourceUri)
            else {
                Toast.makeText(this, "Azon ovozi topilmadi", Toast.LENGTH_LONG).show()
                stopSelf()
                return
            }
            media.setOnCompletionListener { stopSelf() }
            media.setOnErrorListener { _, _, _ -> stopSelf(); true }
            media.setOnPreparedListener { it.start() }
            media.prepareAsync()
        } catch (_: Exception) {
            stopPlayback()
            stopSelf()
        }
    }

    private fun stopPlayback() {
        try { player?.stop() } catch (_: Exception) { }
        try { player?.release() } catch (_: Exception) { }
        player = null
    }

    override fun onDestroy() {
        stopPlayback()
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}

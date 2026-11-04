package uz.namozvaqtlari.app

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.GeomagneticField
import android.hardware.SensorManager
import android.view.Surface
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import org.json.JSONArray
import java.io.File
import java.io.FileOutputStream

class MainActivity : Activity(), SensorEventListener {
    private lateinit var webView: WebView
    private lateinit var sensorManager: SensorManager
    private var rotationSensor: Sensor? = null
    private var locationWaiter = false
    private var waitingAudioSlot = "1"
    private var firstRunPermissionFlow = false
    @Volatile private var compassLatitude = 41.2995f
    @Volatile private var compassLongitude = 69.2401f

    companion object {
        private const val LOCATION_PERMISSION_REQUEST = 4101
        private const val NOTIFICATION_PERMISSION_REQUEST = 4102
        private const val AUDIO_PICK_REQUEST = 4103
        private const val EXACT_ALARM_REQUEST = 4104
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        sensorManager = getSystemService(Context.SENSOR_SERVICE) as SensorManager
        rotationSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)

        webView = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = true
            settings.allowContentAccess = false
            settings.setSupportMultipleWindows(false)
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    PrayerSyncManager.ensureScheduled(this@MainActivity)
                    val cached = PrayerSyncRepository.cached(this@MainActivity)
                    if (!cached.isNullOrBlank()) {
                        val safeJson = org.json.JSONObject.quote(cached)
                        view?.evaluateJavascript("window.onRemotePrayerTimes && window.onRemotePrayerTimes($safeJson)", null)
                    }
                    view?.evaluateJavascript("window.Android && Android.refreshPrayerTimes && Android.refreshPrayerTimes()", null)
                    view?.evaluateJavascript("window.Android && Android.runFirstStartSetup && Android.runFirstStartSetup()", null)
                }
            }
            webChromeClient = WebChromeClient()
            addJavascriptInterface(AndroidBridge(), "Android")
        }
        ViewCompat.setOnApplyWindowInsetsListener(webView) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        setContentView(webView)
        webView.loadUrl("file:///android_asset/index.html")
    }

    override fun onResume() {
        super.onResume()
        rotationSensor?.let { sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_UI) }
        if (::webView.isInitialized) {
            webView.evaluateJavascript("window.refreshTelegramQuietly && window.refreshTelegramQuietly(); window.scheduleAzan && window.scheduleAzan()", null)
        }
    }

    override fun onPause() {
        sensorManager.unregisterListener(this)
        super.onPause()
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type != Sensor.TYPE_ROTATION_VECTOR) return
        val matrix = FloatArray(9)
        SensorManager.getRotationMatrixFromVector(matrix, event.values)
        val remapped = FloatArray(9)
        val rotation = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) display?.rotation ?: Surface.ROTATION_0
                       else legacyDisplayRotation()
        val axisX: Int
        val axisY: Int
        when (rotation) {
            Surface.ROTATION_90 -> { axisX = SensorManager.AXIS_Y; axisY = SensorManager.AXIS_MINUS_X }
            Surface.ROTATION_180 -> { axisX = SensorManager.AXIS_MINUS_X; axisY = SensorManager.AXIS_MINUS_Y }
            Surface.ROTATION_270 -> { axisX = SensorManager.AXIS_MINUS_Y; axisY = SensorManager.AXIS_X }
            else -> { axisX = SensorManager.AXIS_X; axisY = SensorManager.AXIS_Y }
        }
        SensorManager.remapCoordinateSystem(matrix, axisX, axisY, remapped)
        val orientation = FloatArray(3)
        SensorManager.getOrientation(remapped, orientation)
        val magneticDegrees = Math.toDegrees(orientation[0].toDouble()).toFloat()
        val declination = try { GeomagneticField(compassLatitude, compassLongitude, 0f, System.currentTimeMillis()).declination } catch (_: Exception) { 0f }
        val degrees = ((magneticDegrees + declination + 360f) % 360f)
        runOnUiThread {
            if (::webView.isInitialized) webView.evaluateJavascript("window.onCompassUpdate && window.onCompassUpdate(${degrees})", null)
        }
    }

    @Suppress("DEPRECATION")
    private fun legacyDisplayRotation(): Int = windowManager.defaultDisplay.rotation

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    private fun beginFirstRunPermissionFlow() {
        val prefs = getSharedPreferences("namoz", MODE_PRIVATE)
        if (prefs.getBoolean("first_run_permissions_done", false) || firstRunPermissionFlow) return
        firstRunPermissionFlow = true
        if (!hasLocationPermission()) {
            requestPermissions(
                arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION),
                LOCATION_PERMISSION_REQUEST
            )
        } else {
            requestFirstRunNotifications()
        }
    }

    private fun requestFirstRunNotifications() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), NOTIFICATION_PERMISSION_REQUEST)
        } else {
            askForExactAlarmAccess()
        }
    }

    private fun askForExactAlarmAccess() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S || getSystemService(android.app.AlarmManager::class.java).canScheduleExactAlarms()) {
            finishFirstRunPermissionFlow()
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Azon vaqtida chalinishi uchun")
            .setMessage("Namoz vaqtida azon aniq vaqtda chalinishi uchun ‘Signallar va eslatmalar’ ruxsati kerak. Uni Android sozlamalarida o‘zingiz tasdiqlaysiz.")
            .setPositiveButton("Ruxsatni ochish") { _, _ ->
                try {
                    startActivityForResult(
                        Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:$packageName")),
                        EXACT_ALARM_REQUEST
                    )
                } catch (_: Exception) { finishFirstRunPermissionFlow() }
            }
            .setNegativeButton("Keyinroq") { _, _ -> finishFirstRunPermissionFlow() }
            .setOnCancelListener { finishFirstRunPermissionFlow() }
            .show()
    }

    private fun finishFirstRunPermissionFlow() {
        firstRunPermissionFlow = false
        getSharedPreferences("namoz", MODE_PRIVATE).edit().putBoolean("first_run_permissions_done", true).apply()
        if (::webView.isInitialized) {
            val exact = Build.VERSION.SDK_INT < Build.VERSION_CODES.S || getSystemService(android.app.AlarmManager::class.java).canScheduleExactAlarms()
            webView.evaluateJavascript("window.onInitialPermissionsFinished && window.onInitialPermissionsFinished($exact)", null)
        }
    }

    private fun hasLocationPermission(): Boolean {
        val fine = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val coarse = checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        return fine || coarse
    }

    private fun requestLocation() {
        if (!hasLocationPermission()) {
            requestPermissions(
                arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION),
                LOCATION_PERMISSION_REQUEST
            )
            return
        }
        findCurrentLocation()
    }

    @Suppress("MissingPermission")
    private fun findCurrentLocation() {
        val manager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val hasFine = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val provider = try {
            when {
                hasFine && manager.isProviderEnabled(LocationManager.GPS_PROVIDER) -> LocationManager.GPS_PROVIDER
                manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER) -> LocationManager.NETWORK_PROVIDER
                hasFine && manager.isProviderEnabled(LocationManager.GPS_PROVIDER) -> LocationManager.GPS_PROVIDER
                else -> null
            }
        } catch (_: Exception) { null }

        if (provider == null) {
            sendLocationError("Joylashuv xizmati o‘chiq. Telefon sozlamalaridan GPSni yoqing.")
            return
        }

        try {
            val last = manager.getLastKnownLocation(provider)
            if (last != null) {
                sendLocation(last)
                return
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                manager.getCurrentLocation(provider, null, mainExecutor) { location ->
                    if (location != null) sendLocation(location)
                    else sendLocationError("Joylashuv aniqlanmadi. Ochiq joyga chiqing yoki shaharni qo‘lda tanlang.")
                }
            } else {
                locationWaiter = true
                val listener = object : LocationListener {
                    override fun onLocationChanged(location: Location) {
                        if (locationWaiter) {
                            locationWaiter = false
                            manager.removeUpdates(this)
                            sendLocation(location)
                        }
                    }
                }
                manager.requestSingleUpdate(provider, listener, mainLooper)
                webView.postDelayed({
                    if (locationWaiter) {
                        locationWaiter = false
                        try { manager.removeUpdates(listener) } catch (_: Exception) { }
                        sendLocationError("Joylashuvni aniqlash vaqti tugadi. Shaharni qo‘lda tanlang.")
                    }
                }, 12000)
            }
        } catch (_: SecurityException) {
            sendLocationError("Joylashuv ruxsati berilmadi.")
        } catch (_: Exception) {
            sendLocationError("Joylashuvni aniqlab bo‘lmadi.")
        }
    }

    private fun sendLocation(location: Location) {
        runOnUiThread {
            webView.evaluateJavascript("window.onNativeLocation && window.onNativeLocation(${location.latitude},${location.longitude})", null)
        }
    }

    private fun sendLocationError(message: String) {
        val safe = org.json.JSONObject.quote(message)
        runOnUiThread { webView.evaluateJavascript("window.onNativeLocationError && window.onNativeLocationError($safe)", null) }
    }

    private fun startAudioPicker(slot: String) {
        waitingAudioSlot = slot
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "audio/*"
        }
        startActivityForResult(intent, AUDIO_PICK_REQUEST)
    }

    @Deprecated("Activity result is kept compatible with the minimal native project")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == EXACT_ALARM_REQUEST) {
            val allowed = Build.VERSION.SDK_INT < Build.VERSION_CODES.S || getSystemService(android.app.AlarmManager::class.java).canScheduleExactAlarms()
            webView.evaluateJavascript("window.onExactAlarmPermission && window.onExactAlarmPermission($allowed)", null)
            if (firstRunPermissionFlow) finishFirstRunPermissionFlow()
            return
        }
        if (requestCode != AUDIO_PICK_REQUEST || resultCode != RESULT_OK || data?.data == null) return
        val uri = data.data!!
        try {
            contentResolver.openInputStream(uri).use { input ->
                if (input == null) throw IllegalStateException("Fayl ochilmadi")
                val folder = File(filesDir, "azan").apply { mkdirs() }
                val target = File(folder, "voice$waitingAudioSlot.mp3")
                FileOutputStream(target).use { output -> input.copyTo(output) }
                getSharedPreferences("namoz", MODE_PRIVATE).edit()
                    .putString("voice_$waitingAudioSlot", target.absolutePath).apply()
                val name = uri.lastPathSegment?.substringAfterLast('/') ?: "Azon fayli"
                val safeName = org.json.JSONObject.quote(name)
                webView.evaluateJavascript("window.onAzanFilePicked && window.onAzanFilePicked('$waitingAudioSlot',$safeName)", null)
                Toast.makeText(this, "Azon ovozi saqlandi", Toast.LENGTH_SHORT).show()
            }
        } catch (_: Exception) {
            Toast.makeText(this, "Audio faylni saqlab bo‘lmadi", Toast.LENGTH_LONG).show()
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        when (requestCode) {
            LOCATION_PERMISSION_REQUEST -> {
                if (grantResults.any { it == PackageManager.PERMISSION_GRANTED }) findCurrentLocation()
                else sendLocationError("Joylashuv ruxsati berilmadi. Shaharni ro‘yxatdan tanlashingiz mumkin.")
                if (firstRunPermissionFlow) requestFirstRunNotifications()
            }
            NOTIFICATION_PERMISSION_REQUEST -> {
                val granted = grantResults.any { it == PackageManager.PERMISSION_GRANTED }
                val value = if (granted) "true" else "false"
                webView.evaluateJavascript("window.onNotificationPermission && window.onNotificationPermission($value)", null)
                if (firstRunPermissionFlow) askForExactAlarmAccess()
            }
        }
    }

    inner class AndroidBridge {
        @JavascriptInterface fun getCurrentLocation() { runOnUiThread { requestLocation() } }

        @JavascriptInterface fun runFirstStartSetup() {
            runOnUiThread { beginFirstRunPermissionFlow() }
        }

        @JavascriptInterface fun saveAppSettings(json: String) {
            if (json.length > 100_000) return
            try {
                org.json.JSONObject(json)
                getSharedPreferences("namoz", MODE_PRIVATE).edit().putString("web_settings_json", json).apply()
            } catch (_: Exception) { }
        }

        @JavascriptInterface fun getCachedPrayerTimes(): String = PrayerSyncRepository.cached(this@MainActivity) ?: ""

        @JavascriptInterface fun refreshPrayerTimes() {
            Thread {
                try {
                    val result = PrayerSyncRepository.refresh(this@MainActivity)
                    runOnUiThread {
                        if (!result.isNullOrBlank()) {
                            val safe = org.json.JSONObject.quote(result)
                            webView.evaluateJavascript("window.onRemotePrayerTimes && window.onRemotePrayerTimes($safe)", null)
                        } else {
                            webView.evaluateJavascript("window.onRemoteSyncError && window.onRemoteSyncError('Jadval manzili hali GitHub bilan sozlanmagan.')", null)
                        }
                    }
                } catch (error: Exception) {
                    val safe = org.json.JSONObject.quote("Yangilash amalga oshmadi: ${error.message ?: "tarmoq xatosi"}")
                    runOnUiThread { webView.evaluateJavascript("window.onRemoteSyncError && window.onRemoteSyncError($safe)", null) }
                }
            }.start()
        }

        @JavascriptInterface fun tasbihTick() {
            runOnUiThread {
                try {
                    val tone = ToneGenerator(AudioManager.STREAM_SYSTEM, 45)
                    tone.startTone(ToneGenerator.TONE_PROP_BEEP, 45)
                    Handler(Looper.getMainLooper()).postDelayed({ tone.release() }, 70)
                } catch (_: Exception) { }
            }
        }

        @JavascriptInterface fun tasbihVibrate() {
            runOnUiThread {
                try {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                        (getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager).defaultVibrator
                            .vibrate(VibrationEffect.createOneShot(14, VibrationEffect.DEFAULT_AMPLITUDE))
                    } else {
                        @Suppress("DEPRECATION")
                        (getSystemService(Context.VIBRATOR_SERVICE) as Vibrator)
                            .vibrate(VibrationEffect.createOneShot(14, VibrationEffect.DEFAULT_AMPLITUDE))
                    }
                } catch (_: Exception) { }
            }
        }

        @JavascriptInterface fun setCoordinates(latitude: Double, longitude: Double) {
            if (latitude in -90.0..90.0 && longitude in -180.0..180.0) {
                compassLatitude = latitude.toFloat()
                compassLongitude = longitude.toFloat()
            }
        }

        @JavascriptInterface fun schedulePrayerAlarms(json: String) {
            try {
                AlarmScheduler.schedule(this@MainActivity, json)
                runOnUiThread { webView.evaluateJavascript("window.onScheduleSaved && window.onScheduleSaved(true)", null) }
            } catch (_: Exception) {
                runOnUiThread { webView.evaluateJavascript("window.onScheduleSaved && window.onScheduleSaved(false)", null) }
            }
        }

        @JavascriptInterface fun requestNotificationPermission() {
            runOnUiThread {
                if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                    requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), NOTIFICATION_PERMISSION_REQUEST)
                } else webView.evaluateJavascript("window.onNotificationPermission && window.onNotificationPermission(true)", null)
            }
        }

        @JavascriptInterface fun requestExactAlarmPermission() {
            runOnUiThread {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && !getSystemService(android.app.AlarmManager::class.java).canScheduleExactAlarms()) {
                    try {
                        startActivityForResult(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:$packageName")), EXACT_ALARM_REQUEST)
                    } catch (_: Exception) {
                        Toast.makeText(this@MainActivity, "Sozlamalardan ‘Signallar va eslatmalar’ ruxsatini yoqing.", Toast.LENGTH_LONG).show()
                    }
                } else webView.evaluateJavascript("window.onExactAlarmPermission && window.onExactAlarmPermission(true)", null)
            }
        }

        @JavascriptInterface fun hasExactAlarmPermission(): Boolean {
            return Build.VERSION.SDK_INT < Build.VERSION_CODES.S || getSystemService(android.app.AlarmManager::class.java).canScheduleExactAlarms()
        }

        @JavascriptInterface fun pickAzanVoice(slot: String) { runOnUiThread { startAudioPicker(slot.take(1).ifBlank { "1" }) } }

        @JavascriptInterface fun testAzan(slot: String) {
            runOnUiThread {
                val intent = Intent(this@MainActivity, AzanPlaybackService::class.java).apply {
                    putExtra(AzanPlaybackService.EXTRA_PRAYER_NAME, "Azon sinovi")
                    putExtra(AzanPlaybackService.EXTRA_VOICE_SLOT, slot.take(1))
                }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent) else startService(intent)
            }
        }

        @JavascriptInterface fun stopAzan() { stopService(Intent(this@MainActivity, AzanPlaybackService::class.java)) }
    }
}

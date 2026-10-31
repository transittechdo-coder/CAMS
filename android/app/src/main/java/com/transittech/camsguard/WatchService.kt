package com.transittech.camsguard

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import org.json.JSONArray

/** Shared between the background service and the alarm screen. */
object Live {
    @Volatile var emergencies: JSONArray = JSONArray()
    @Volatile var reachable: Boolean = true
    var onChange: (() -> Unit)? = null
    fun changed() { onChange?.invoke() }
}

/**
 * Runs all the time (also when the phone is locked or after a restart) and asks the CAMS
 * computer every few seconds whether something is wrong. Fire, smoke or a person down:
 * full-screen alarm with sound and vibration. Other alerts: a normal notification.
 */
class WatchService : Service() {
    private lateinit var cams: Cams
    @Volatile private var running = false
    private var worker: Thread? = null
    private var wake: PowerManager.WakeLock? = null
    private var shown = setOf<Long>()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        cams = Cams(this)
        channels(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_MUTE) { Alarm.stop(); return START_STICKY }
        if (!cams.prefs.paired) { stopSelf(); return START_NOT_STICKY }
        val n = status("Watching ${cams.prefs.site.ifBlank { "the site" }}", "You will be alerted here at once.")
        if (Build.VERSION.SDK_INT >= 34) ServiceCompat.startForeground(this, ID_STATUS, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(ID_STATUS, n)
        if (!running) {
            running = true
            wake = (getSystemService(Context.POWER_SERVICE) as PowerManager)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "camsguard:watch").apply { setReferenceCounted(false); acquire() }
            worker = Thread({ loop() }, "cams-watch").apply { start() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        worker?.interrupt()
        Alarm.stop()
        try { wake?.release() } catch (e: Exception) {}
        super.onDestroy()
    }

    private fun loop() {
        var lastAlerts = 0L
        var failingSince = 0L
        var warned = false
        while (running) {
            try {
                val list = cams.emergencies()
                failingSince = 0
                if (warned) { warned = false; nm().cancel(ID_OFFLINE) }
                if (!Live.reachable) { Live.reachable = true; Live.changed() }
                handleEmergencies(list)
                val now = System.currentTimeMillis()
                if (now - lastAlerts > 15000) { lastAlerts = now; otherAlerts() }
            } catch (e: Unauthorized) {
                cams.prefs.forget()
                Alarm.stop()
                nm().notify(ID_OFFLINE, simple(CH_STATUS, "This phone was disconnected", "Ask for a new code on the CAMS computer to connect it again."))
                running = false
                stopSelf()
                return
            } catch (e: Exception) {
                val now = System.currentTimeMillis()
                if (failingSince == 0L) failingSince = now
                if (Live.reachable && now - failingSince > 20000) { Live.reachable = false; Live.changed() }
                if (!warned && now - failingSince > 90000) {
                    warned = true
                    nm().notify(ID_OFFLINE, simple(CH_STATUS, "Cannot reach the CAMS computer",
                        "Alerts cannot arrive. Make sure this phone is on the site's Wi-Fi and the CAMS computer is on."))
                }
            }
            try { Thread.sleep(if (Live.emergencies.length() > 0) 3000 else 4000) } catch (e: InterruptedException) { return }
        }
    }

    private fun handleEmergencies(list: JSONArray) {
        val ids = (0 until list.length()).map { list.getJSONObject(it).getLong("id") }.toSet()
        Live.emergencies = list
        if (ids.isEmpty()) {
            if (shown.isNotEmpty()) { Alarm.stop(); nm().cancel(ID_EMERGENCY); Live.changed() }
            shown = ids
            return
        }
        if (ids != shown) {
            val fresh = (ids - shown).isNotEmpty()
            shown = ids
            val first = list.getJSONObject(0)
            val title = if (list.length() > 1) "${list.length()} EMERGENCIES" else Kinds.title(first.optString("kind"))
            val open = PendingIntent.getActivity(this, 1, Intent(this, AlarmActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val n = NotificationCompat.Builder(this, CH_EMERGENCY)
                .setSmallIcon(R.drawable.ic_notify)
                .setColor(0xFFB3140F.toInt())
                .setContentTitle(title)
                .setContentText(first.optString("message"))
                .setStyle(NotificationCompat.BigTextStyle().bigText(first.optString("message")))
                .setPriority(NotificationCompat.PRIORITY_MAX)
                .setCategory(NotificationCompat.CATEGORY_ALARM)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setOngoing(true)
                .setFullScreenIntent(open, true)
                .setContentIntent(open)
                .addAction(0, "Mute", PendingIntent.getService(this, 2, Intent(this, WatchService::class.java).setAction(ACTION_MUTE), PendingIntent.FLAG_IMMUTABLE))
                .build()
            nm().notify(ID_EMERGENCY, n)
            if (fresh) Alarm.start(this)
            try { startActivity(Intent(this, AlarmActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)) } catch (e: Exception) {}
            Live.changed()
        }
    }

    private fun otherAlerts() {
        val list = cams.openAlerts()
        val last = cams.prefs.lastAlertId
        var newest = last
        var count = 0
        for (i in 0 until list.length()) {
            val a = list.getJSONObject(i)
            val id = a.getLong("id")
            if (id > newest) newest = id
            if (id <= last || Kinds.isEmergency(a.optString("kind")) || last == 0L) continue
            if (count++ >= 3) continue
            val n = NotificationCompat.Builder(this, CH_ALERTS)
                .setSmallIcon(R.drawable.ic_notify)
                .setColor(0xFF0F6E6A.toInt())
                .setContentTitle(Kinds.label(a.optString("kind")))
                .setContentText(a.optString("message"))
                .setStyle(NotificationCompat.BigTextStyle().bigText(a.optString("message")))
                .setAutoCancel(true)
                .setContentIntent(PendingIntent.getActivity(this, 3, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE))
                .build()
            nm().notify(1000 + (id % 1000).toInt(), n)
        }
        if (newest != last) cams.prefs.lastAlertId = newest
    }

    private fun nm() = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    private fun status(title: String, text: String): Notification = NotificationCompat.Builder(this, CH_WATCH)
        .setSmallIcon(R.drawable.ic_notify)
        .setColor(0xFF0F6E6A.toInt())
        .setContentTitle(title)
        .setContentText(text)
        .setOngoing(true)
        .setContentIntent(PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE))
        .build()

    private fun simple(ch: String, title: String, text: String): Notification = NotificationCompat.Builder(this, ch)
        .setSmallIcon(R.drawable.ic_notify)
        .setContentTitle(title).setContentText(text)
        .setStyle(NotificationCompat.BigTextStyle().bigText(text))
        .setContentIntent(PendingIntent.getActivity(this, 4, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE))
        .setAutoCancel(true).build()

    companion object {
        const val CH_WATCH = "watch"
        const val CH_EMERGENCY = "emergency"
        const val CH_ALERTS = "alerts"
        const val CH_STATUS = "status"
        const val ID_STATUS = 1
        const val ID_EMERGENCY = 2
        const val ID_OFFLINE = 3
        const val ACTION_MUTE = "com.transittech.camsguard.MUTE"

        fun start(context: Context) {
            if (!Prefs(context).paired) return
            ContextCompat.startForegroundService(context, Intent(context, WatchService::class.java))
        }

        fun mute(context: Context) {
            context.startService(Intent(context, WatchService::class.java).setAction(ACTION_MUTE))
        }

        fun channels(context: Context) {
            if (Build.VERSION.SDK_INT < 26) return
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(NotificationChannel(CH_WATCH, "Watching (always on)", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Shows that CAMS Guard is watching. Keep it on." })
            nm.createNotificationChannel(NotificationChannel(CH_EMERGENCY, "Emergencies (fire, smoke, person down)", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Full-screen alarm. The alarm sound is played by the app, even on silent."
                setSound(null, null)
                enableVibration(false)
                setBypassDnd(true)
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC })
            nm.createNotificationChannel(NotificationChannel(CH_ALERTS, "Other alerts", NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = "Visitors who stay too long, flagged vehicles, bags left behind..." })
            nm.createNotificationChannel(NotificationChannel(CH_STATUS, "Connection", NotificationManager.IMPORTANCE_DEFAULT))
        }
    }
}

object Kinds {
    private val EMERGENCY = mapOf("fire" to "FIRE", "smoke" to "HEAVY SMOKE", "person_down" to "PERSON DOWN", "emergency_test" to "ALARM TEST")
    private val LABELS = mapOf(
        "watchlist" to "Watch list", "access_violation" to "Not allowed here", "unknown_restricted" to "Restricted camera",
        "visitor_overstay" to "Visitor stayed too long", "bag_left" to "Bag left behind", "plate_flagged" to "Flagged vehicle",
        "plate_unknown" to "Unknown vehicle", "camera_offline" to "Camera offline", "tamper" to "Camera tampering",
        "downtime" to "CAMS was off", "power" to "Power", "loitering" to "Loitering", "crowd" to "Crowd",
        "running" to "Running", "after_hours" to "After hours")
    fun isEmergency(kind: String) = kind in EMERGENCY
    fun title(kind: String) = EMERGENCY[kind] ?: "EMERGENCY"
    fun label(kind: String) = LABELS[kind] ?: "CAMS alert"
}

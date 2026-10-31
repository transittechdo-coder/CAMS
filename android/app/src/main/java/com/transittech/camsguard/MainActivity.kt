package com.transittech.camsguard

import android.Manifest
import android.annotation.SuppressLint
import android.app.AlertDialog
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.Gravity
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions

/**
 * Not connected: one big button, "Scan the code".
 * Connected: a status line (all is well / emergency / cannot reach CAMS) and the guard screens.
 */
class MainActivity : AppCompatActivity() {
    private lateinit var cams: Cams
    private val ui = Handler(Looper.getMainLooper())
    private var web: WebView? = null
    private var strip: TextView? = null
    private var loadedBase: String? = null

    private val scan = registerForActivityResult(ScanContract()) { r -> r.contents?.let { connect(it) } }
    private val askNotify = registerForActivityResult(ActivityResultContracts.RequestPermission()) { nextPermission(1) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        cams = Cams(this)
        WatchService.channels(this)
    }

    override fun onResume() {
        super.onResume()
        if (!cams.prefs.paired) { showWelcome(); return }
        WatchService.start(this)
        if (web == null) showMain()
        Live.onChange = { ui.post { refreshStrip() } }
        refreshStrip()
    }

    override fun onPause() {
        super.onPause()
        Live.onChange = null
    }

    @Deprecated("Back closes the guard screens' extra pages first")
    override fun onBackPressed() {
        val w = web
        if (w != null && w.canGoBack()) w.goBack() else @Suppress("DEPRECATION") super.onBackPressed()
    }

    // ------------------------------------------------------------------ not connected
    private fun showWelcome(message: String? = null) {
        web = null; strip = null; loadedBase = null
        val box = column(Color.parseColor("#EEF2F0"))
        box.addView(big("CAMS Guard", 34f, "#10202B"))
        box.addView(small("Alarms from your CAMS cameras on this phone: fire, smoke, a person down, and other alerts.", "#556877"))
        box.addView(steps(listOf(
            "Connect this phone to the Wi-Fi of the place the cameras protect.",
            "On the CAMS computer, open Settings, then Phones, then press Add a phone.",
            "Press the green button below and point the phone at the code on the screen.")))
        if (message != null) box.addView(small(message, "#B3140F").apply { setTypeface(typeface, Typeface.BOLD) })
        box.addView(bigButton("Scan the code") {
            scan.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE).setPrompt("Point at the code on the CAMS computer")
                .setBeepEnabled(false).setOrientationLocked(true).setCaptureActivity(ScanActivity::class.java))
        })
        setContentView(box)
    }

    private fun connect(qr: String) {
        val box = column(Color.parseColor("#EEF2F0"))
        box.addView(big("Connecting...", 28f, "#10202B"))
        box.addView(ProgressBar(this))
        setContentView(box)
        Thread {
            try {
                cams.pair(qr)
                ui.post { permissions() }
            } catch (e: Exception) {
                ui.post { showWelcome(e.message ?: "Could not connect. Try again.") }
            }
        }.start()
    }

    // ------------------------------------------------------------------ after connecting: allow the alarm
    private fun permissions() {
        val box = column(Color.parseColor("#EEF2F0"))
        box.addView(big("Connected", 30f, "#1E8A4C"))
        box.addView(small("${cams.prefs.site.ifBlank { "CAMS" }} · ${cams.prefs.guard}", "#556877"))
        box.addView(small("One more step: the phone will ask a few questions. Press Allow each time, so the alarm can ring even when the phone is locked.", "#10202B"))
        box.addView(bigButton("Continue") { nextPermission(0) })
        setContentView(box)
    }

    private fun nextPermission(step: Int) {
        when {
            step <= 0 && Build.VERSION.SDK_INT >= 33 &&
                ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED ->
                askNotify.launch(Manifest.permission.POST_NOTIFICATIONS)
            step <= 1 && !(getSystemService(POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(packageName) -> {
                pendingStep = 2
                @SuppressLint("BatteryLife")
                val i = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))
                try { startActivity(i) } catch (e: Exception) { nextPermission(2) }
            }
            step <= 2 && Build.VERSION.SDK_INT >= 34 &&
                !(getSystemService(NOTIFICATION_SERVICE) as NotificationManager).canUseFullScreenIntent() -> {
                pendingStep = 3
                AlertDialog.Builder(this).setTitle("Show the alarm on the locked screen")
                    .setMessage("On the next screen, turn on CAMS Guard, then press Back.")
                    .setPositiveButton("OK") { _, _ ->
                        try { startActivity(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:$packageName"))) }
                        catch (e: Exception) { nextPermission(3) }
                    }.setCancelable(false).show()
            }
            else -> { pendingStep = -1; WatchService.start(this); showMain() }
        }
    }

    private var pendingStep = -1

    override fun onRestart() {
        super.onRestart()
        if (pendingStep >= 0) { val s = pendingStep; pendingStep = -1; ui.post { nextPermission(s) } }
    }

    // ------------------------------------------------------------------ connected
    @SuppressLint("SetJavaScriptEnabled")
    private fun showMain() {
        val root = column(Color.parseColor("#EEF2F0"), padded = false)
        val s = TextView(this).apply {
            textSize = 18f; setTypeface(typeface, Typeface.BOLD); setTextColor(Color.WHITE)
            setPadding(dp(16), dp(12), dp(16), dp(12))
            setOnLongClickListener { disconnect(); true }
        }
        strip = s
        root.addView(s, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        val w = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            settings.userAgentString = settings.userAgentString + " CAMSGuardApp"
            webViewClient = WebViewClient()
            webChromeClient = WebChromeClient()
        }
        web = w
        root.addView(w, LinearLayout.LayoutParams(MATCH_PARENT, 0, 1f))
        setContentView(root)
        loadGuard()
    }

    private fun loadGuard() {
        Thread {
            val base = cams.find()
            ui.post {
                val w = web ?: return@post
                if (base == null) {
                    loadedBase = null
                    w.loadDataWithBaseURL(null, OFFLINE, "text/html", "utf-8", null)
                    ui.postDelayed({ if (web != null && loadedBase == null) loadGuard() }, 5000)
                    return@post
                }
                if (base != loadedBase) {
                    loadedBase = base
                    CookieManager.getInstance().setCookie(base, "cams_session=${cams.prefs.token}; path=/")
                    w.loadUrl("$base/guard")
                }
            }
        }.start()
    }

    private fun refreshStrip() {
        if (!cams.prefs.paired) { showWelcome("This phone was disconnected from CAMS. Ask for a new code."); return }
        val s = strip ?: return
        val em = Live.emergencies.length()
        when {
            em > 0 -> { s.text = if (em > 1) "$em EMERGENCIES: open the alarm" else "EMERGENCY: open the alarm"; s.setBackgroundColor(Color.parseColor("#B3140F"))
                s.setOnClickListener { startActivity(Intent(this, AlarmActivity::class.java)) } }
            !Live.reachable -> { s.text = "Cannot reach the CAMS computer. Check the Wi-Fi."; s.setBackgroundColor(Color.parseColor("#6B7A86"))
                s.setOnClickListener { loadGuard() }; if (loadedBase != null) { loadedBase = null; loadGuard() } }
            else -> { s.text = "All is well · ${cams.prefs.site}"; s.setBackgroundColor(Color.parseColor("#1E8A4C")); s.setOnClickListener(null) }
        }
    }

    private fun disconnect() {
        AlertDialog.Builder(this).setTitle("Disconnect this phone?")
            .setMessage("This phone will stop getting CAMS alarms. To connect it again you need a new code from the CAMS computer.")
            .setPositiveButton("Disconnect") { _, _ ->
                stopService(Intent(this, WatchService::class.java))
                cams.prefs.forget(); showWelcome()
            }.setNegativeButton("Cancel", null).show()
    }

    // ------------------------------------------------------------------ simple big views
    private fun column(bg: Int, padded: Boolean = true) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL; setBackgroundColor(bg)
        if (padded) { setPadding(dp(24), dp(48), dp(24), dp(24)); gravity = Gravity.CENTER_HORIZONTAL }
    }
    private fun big(t: String, size: Float, color: String) = TextView(this).apply {
        text = t; textSize = size; setTypeface(typeface, Typeface.BOLD); setTextColor(Color.parseColor(color)); gravity = Gravity.CENTER
        setPadding(0, 0, 0, dp(12))
    }
    private fun small(t: String, color: String) = TextView(this).apply {
        text = t; textSize = 17f; setTextColor(Color.parseColor(color)); gravity = Gravity.CENTER; setPadding(0, dp(6), 0, dp(14))
    }
    private fun steps(lines: List<String>) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL; setBackgroundColor(Color.WHITE); setPadding(dp(16), dp(14), dp(16), dp(6))
        lines.forEachIndexed { i, l -> addView(TextView(this@MainActivity).apply {
            text = "${i + 1}.  $l"; textSize = 17f; setTextColor(Color.parseColor("#10202B")); setPadding(0, 0, 0, dp(10)) }) }
        layoutParams = LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { bottomMargin = dp(16) }
    }
    private fun bigButton(t: String, onClick: () -> Unit) = Button(this).apply {
        text = t; textSize = 22f; setTypeface(typeface, Typeface.BOLD); setTextColor(Color.WHITE)
        setBackgroundColor(Color.parseColor("#0F6E6A")); minHeight = dp(76); isAllCaps = false
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(8) }
    }
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    companion object {
        private const val OFFLINE = """<html><body style="font-family:sans-serif;padding:24px;color:#10202B;background:#EEF2F0">
            <h2>Cannot reach the CAMS computer</h2>
            <p style="font-size:18px">1. Make sure this phone is on the Wi-Fi of the place the cameras protect.</p>
            <p style="font-size:18px">2. Make sure the CAMS computer is on.</p>
            <p style="font-size:16px;color:#556877">CAMS Guard keeps trying by itself.</p></body></html>"""
    }
}

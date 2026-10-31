package com.transittech.camsguard

import android.app.Activity
import android.app.KeyguardManager
import android.content.Context
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONObject
import java.text.DateFormat
import java.util.Date

/** The red screen: shows over the lock screen with one huge button, "I'm handling it". */
class AlarmActivity : Activity() {
    private lateinit var cams: Cams
    private lateinit var box: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true); setTurnScreenOn(true)
            (getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager).requestDismissKeyguard(this, null)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                or WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD)
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        cams = Cams(this)
        box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), dp(24), dp(18), dp(24)) }
        setContentView(ScrollView(this).apply { setBackgroundColor(Color.parseColor("#B3140F")); addView(box) })
        draw()
    }

    override fun onResume() {
        super.onResume()
        Live.onChange = { runOnUiThread { if (Live.emergencies.length() == 0) finish() else draw() } }
        draw()
    }

    override fun onPause() {
        super.onPause()
        Live.onChange = null
    }

    private fun draw() {
        val list = Live.emergencies
        if (list.length() == 0) { finish(); return }
        box.removeAllViews()
        box.addView(text(if (list.length() > 1) "${list.length()} EMERGENCIES" else Kinds.title(list.getJSONObject(0).optString("kind")), 34f, bold = true))
        box.addView(Button(this).apply {
            text = "Mute the sound"
            setOnClickListener { WatchService.mute(this@AlarmActivity); Alarm.stop() }
        }, LinearLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT).apply { topMargin = dp(8); bottomMargin = dp(12) })
        for (i in 0 until list.length()) box.addView(item(list.getJSONObject(i)))
        box.addView(text("Check the camera and send help. Tanzania: 114 fire and rescue, 112 emergency.", 15f))
    }

    private fun item(a: JSONObject): LinearLayout {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            setPadding(dp(14), dp(14), dp(14), dp(14))
        }
        val pic = ImageView(this).apply { adjustViewBounds = true }
        card.addView(pic, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        val snap = a.optString("snapshot_path")
        if (snap.isNotBlank()) Thread {
            cams.picture(snap)?.let { bytes ->
                val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                runOnUiThread { pic.setImageBitmap(bmp) }
            }
        }.start()
        val kind = a.optString("kind")
        card.addView(TextView(this).apply {
            text = Kinds.title(kind); textSize = 22f; setTypeface(typeface, Typeface.BOLD)
            setTextColor(Color.parseColor("#B3140F")); setPadding(0, dp(10), 0, 0)
        })
        card.addView(TextView(this).apply { text = a.optString("message"); textSize = 18f; setTextColor(Color.parseColor("#1B1B1B")) })
        val cam = a.optString("camera_name")
        val time = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date((a.optDouble("created_at") * 1000).toLong()))
        card.addView(TextView(this).apply { text = (if (cam.isNotBlank()) "Camera: $cam · " else "") + time; textSize = 15f; setTextColor(Color.GRAY) })
        val id = a.getLong("id")
        card.addView(Button(this).apply {
            text = if (kind == "emergency_test") "Stop the test" else "I'm handling it"
            textSize = 22f
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.parseColor("#B3140F"))
            minHeight = dp(72)
            setOnClickListener {
                isEnabled = false
                text = "Sending..."
                Alarm.stop()
                Thread {
                    val ok = try { cams.ack(id); true } catch (e: Exception) { false }
                    runOnUiThread {
                        if (!ok) { isEnabled = true; text = "Not sent: press again" }
                        else text = "Thank you"
                    }
                }.start()
            }
        }, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(12) })
        return card.also {
            it.layoutParams = LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { bottomMargin = dp(14) }
        }
    }

    private fun text(s: String, size: Float, bold: Boolean = false) = TextView(this).apply {
        text = s; textSize = size; setTextColor(Color.WHITE); gravity = Gravity.START
        if (bold) setTypeface(typeface, Typeface.BOLD)
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()
}

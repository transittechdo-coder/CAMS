package com.transittech.camsguard

import android.app.Activity
import android.app.AlertDialog
import android.app.KeyguardManager
import android.content.Context
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.animation.ObjectAnimator
import android.animation.ValueAnimator
import android.widget.FrameLayout
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONObject
import java.text.DateFormat
import java.util.Date

/** The emergency screen: shows over the lock screen in a dark "command centre" look with one huge button, "I'm handling it". */
class AlarmActivity : Activity() {
    private lateinit var cams: Cams
    private lateinit var box: LinearLayout
    private lateinit var root: FrameLayout
    private var shownKind = ""

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
        box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(14), dp(22), dp(14), dp(22)) }
        root = FrameLayout(this).apply { setBackgroundColor(Hud.BG) }
        root.addView(ScrollView(this).apply { addView(box) }, FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT))
        setContentView(root)
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
        val first = list.getJSONObject(0).optString("kind")
        val kind = if ((0 until list.length()).all { list.getJSONObject(it).optString("kind") == first }) first else "fire"
        val color = Hud.accent(kind)
        if (kind != shownKind) {                     // the moving background, in this kind's colour
            if (root.childCount > 1) root.removeViewAt(0)
            root.addView(HudBackground(this, color), 0, FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT))
            shownKind = kind
        }
        box.removeAllViews()
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = GradientDrawable().apply { setColor(0xEE12040A.toInt()); setStroke(dp(1), Hud.alpha(color, 150)); cornerRadius = dp(4).toFloat() }
        }
        panel.addView(HudStripes(this, color), LinearLayout.LayoutParams(MATCH_PARENT, dp(10)))
        val head = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(dp(14), dp(14), dp(14), dp(12)) }
        head.addView(HudBadge(this, color), LinearLayout.LayoutParams(dp(58), dp(58)).apply { rightMargin = dp(12) })
        val titles = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        titles.addView(mono("CAMS EMERGENCY ALERT", 11f, color).apply { letterSpacing = 0.25f })
        val title = if (list.length() > 1) "${list.length()} EMERGENCIES" else Kinds.title(first)
        titles.addView(TextView(this).apply {
            text = title; textSize = if (title.length > 10) 26f else 34f; setTextColor(Color.WHITE)
            typeface = Typeface.create("sans-serif-condensed", Typeface.BOLD); letterSpacing = 0.1f
            setShadowLayer(dp(10).toFloat(), 0f, 0f, color)
        })
        head.addView(titles, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        head.addView(Button(this).apply {
            text = "Mute"; textSize = 13f; typeface = Typeface.MONOSPACE; setTextColor(Color.WHITE)
            background = outline(Hud.alpha(color, 170))
            setOnClickListener { WatchService.mute(this@AlarmActivity); Alarm.stop() }
        }, LinearLayout.LayoutParams(WRAP_CONTENT, dp(44)))
        panel.addView(head)
        for (i in 0 until list.length()) panel.addView(item(list.getJSONObject(i)))
        panel.addView(TextView(this).apply {
            text = "Check the camera and send help. Tanzania: 114 fire and rescue, 112 emergency."
            textSize = 14f; setTextColor(0xFFF3B8B2.toInt()); setPadding(dp(16), dp(4), dp(16), dp(18))
        })
        box.addView(panel)
    }

    private fun item(a: JSONObject): LinearLayout {
        val kind = a.optString("kind")
        val color = Hud.accent(kind)
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(10), dp(16), dp(16))
        }
        val frame = FrameLayout(this).apply {
            background = GradientDrawable().apply { setColor(Color.BLACK); setStroke(dp(1), Hud.alpha(color, 160)) }
            setPadding(dp(1), dp(1), dp(1), dp(1))
        }
        val pic = ImageView(this).apply { adjustViewBounds = true; minimumHeight = dp(160) }
        frame.addView(pic, FrameLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        frame.addView(HudScan(this, color), FrameLayout.LayoutParams(MATCH_PARENT, MATCH_PARENT))
        val cam = if (a.isNull("camera_name")) "" else a.optString("camera_name")
        frame.addView(mono("● " + (cam.ifBlank { "CAMERA" }).uppercase(), 12f, Color.WHITE).apply {
            setPadding(dp(8), dp(3), dp(8), dp(3))
            background = GradientDrawable().apply { setColor(0xB3000000.toInt()); setStroke(dp(1), Hud.alpha(color, 160)) }
        }, FrameLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT).apply { leftMargin = dp(12); topMargin = dp(12) })
        card.addView(frame, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        val snap = if (a.isNull("snapshot_path")) "" else a.optString("snapshot_path")
        if (snap.isNotBlank()) Thread {
            cams.picture(snap)?.let { bytes ->
                val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                runOnUiThread { pic.setImageBitmap(bmp) }
            }
        }.start()
        card.addView(TextView(this).apply {
            text = Kinds.title(kind); textSize = 22f; setTypeface(typeface, Typeface.BOLD); letterSpacing = 0.1f
            setTextColor(color); setShadowLayer(dp(8).toFloat(), 0f, 0f, Hud.alpha(color, 160)); setPadding(0, dp(14), 0, 0)
        })
        card.addView(TextView(this).apply { text = a.optString("message"); textSize = 18f; setTextColor(Color.WHITE); setPadding(0, dp(6), 0, dp(12)) })
        val time = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date((a.optDouble("created_at") * 1000).toLong()))
        val data = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dp(12), dp(10), dp(12), dp(10))
            background = GradientDrawable().apply { setColor(Hud.alpha(color, 36)) }
        }
        data.addView(row("CAMERA", cam.ifBlank { "-" }, color))
        data.addView(row("TIME", time, color))
        data.addView(row("STATUS", "WAITING FOR SOMEONE", color).also { r ->
            pulse(r.getChildAt(1), 0.35f, 700)
        })
        card.addView(FrameLayout(this).apply {
            addView(View(this@AlarmActivity).apply { setBackgroundColor(color) }, FrameLayout.LayoutParams(dp(2), MATCH_PARENT))
            addView(data)
        }, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        val id = a.getLong("id")
        card.addView(Button(this).apply {
            text = if (kind == "emergency_test") "Stop the test" else "I'm handling it"
            textSize = 21f
            typeface = Typeface.create("sans-serif-condensed", Typeface.BOLD); letterSpacing = 0.08f
            setTextColor(0xFF120203.toInt())
            background = GradientDrawable().apply { setColor(color); cornerRadius = dp(4).toFloat() }
            minHeight = dp(72)
            pulse(this, 0.82f, 600)
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
        }, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(16) })
        if (kind != "emergency_test") card.addView(Button(this).apply {
            text = "Wrong alarm"
            textSize = 16f
            isAllCaps = false
            setTextColor(Color.WHITE)
            background = outline(0x47FFFFFF)
            setOnClickListener {
                AlertDialog.Builder(this@AlarmActivity)
                    .setMessage("Wrong alarm? CAMS will learn not to ring for this again.")
                    .setPositiveButton("Yes, wrong alarm") { _, _ ->
                        isEnabled = false
                        Alarm.stop()
                        Thread {
                            val ok = try { cams.wrong(id); true } catch (e: Exception) { false }
                            runOnUiThread { text = if (ok) "Thank you: CAMS learned from this" else "Not sent: press again"; isEnabled = !ok }
                        }.start()
                    }.setNegativeButton("Cancel", null).show()
            }
        }, LinearLayout.LayoutParams(MATCH_PARENT, dp(52)).apply { topMargin = dp(10) })
        return card
    }

    private fun row(label: String, value: String, color: Int) = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; setPadding(0, dp(2), 0, dp(2))
        addView(mono(label, 13f, color), LinearLayout.LayoutParams(dp(78), WRAP_CONTENT))
        addView(mono(value, 13f, Color.WHITE), LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
    }

    /** Fade a view in and out while it is on screen. */
    private fun pulse(v: View, low: Float, ms: Long) {
        val anim = ObjectAnimator.ofFloat(v, "alpha", 1f, low).apply {
            duration = ms; repeatCount = ValueAnimator.INFINITE; repeatMode = ValueAnimator.REVERSE
        }
        v.addOnAttachStateChangeListener(object : View.OnAttachStateChangeListener {
            override fun onViewAttachedToWindow(view: View) { anim.start() }
            override fun onViewDetachedFromWindow(view: View) { anim.cancel() }
        })
    }

    private fun mono(s: String, size: Float, color: Int) = TextView(this).apply {
        text = s; textSize = size; setTextColor(color); typeface = Typeface.MONOSPACE
    }

    private fun outline(color: Int) = GradientDrawable().apply {
        setColor(0x0AFFFFFF); setStroke(dp(1), color); cornerRadius = dp(4).toFloat()
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()
}

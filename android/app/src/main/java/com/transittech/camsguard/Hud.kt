package com.transittech.camsguard

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RadialGradient
import android.graphics.Shader
import android.view.View
import android.view.animation.LinearInterpolator

/** The look of the emergency screen: a dark "command centre" with a glowing colour per kind.
 *  Everything is drawn in code, so it needs no pictures and works offline. */
object Hud {
    const val BG = 0xFF0B0203.toInt()
    fun accent(kind: String): Int = when (kind) {
        "smoke" -> 0xFFFFB020.toInt()
        "person_down" -> 0xFFFF3D7F.toInt()
        "emergency_test" -> 0xFF19D3C5.toInt()
        else -> 0xFFFF3B2F.toInt()
    }
    fun alpha(c: Int, a: Int) = Color.argb(a, Color.red(c), Color.green(c), Color.blue(c))
}

/** A view that redraws itself on every animation frame (stops when the phone's animations are off). */
abstract class Animated(context: Context, private val periodMs: Long) : View(context) {
    protected var t = 0f      // 0..1, repeating
    private val anim = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = periodMs; repeatCount = ValueAnimator.INFINITE; interpolator = LinearInterpolator()
        addUpdateListener { t = it.animatedValue as Float; invalidate() }
    }
    override fun onAttachedToWindow() { super.onAttachedToWindow(); anim.start() }
    override fun onDetachedFromWindow() { anim.cancel(); super.onDetachedFromWindow() }
    protected fun dp(v: Float) = v * resources.displayMetrics.density
}

/** Behind everything: a red glow, a moving floor grid, rings spreading out and a slow scan line. */
class HudBackground(context: Context, private val color: Int) : Animated(context, 2400) {
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    override fun onDraw(c: Canvas) {
        val w = width.toFloat(); val h = height.toFloat()
        c.drawColor(Hud.BG)
        p.style = Paint.Style.FILL
        p.shader = RadialGradient(w / 2, h * 0.4f, maxOf(w, h) * 0.75f, Hud.alpha(color, 70), Color.TRANSPARENT, Shader.TileMode.CLAMP)
        c.drawRect(0f, 0f, w, h, p); p.shader = null
        // floor grid: lines come towards the viewer
        p.style = Paint.Style.STROKE; p.strokeWidth = dp(1f); p.color = Hud.alpha(color, 45)
        val horizon = h * 0.55f
        for (i in 0 until 12) {
            val k = ((i + t) / 12f)
            val y = horizon + (h - horizon) * k * k
            c.drawLine(0f, y, w, y, p)
        }
        for (i in -8..8) c.drawLine(w / 2 + i * w * 0.04f, horizon, w / 2 + i * w * 0.25f, h, p)
        // two rings spreading out
        for (r in 0..1) {
            val k = (t + r * 0.5f) % 1f
            p.color = Hud.alpha(color, (150 * (1 - k)).toInt()); p.strokeWidth = dp(2f)
            c.drawCircle(w / 2, h * 0.4f, dp(40f) + k * maxOf(w, h) * 0.6f, p)
        }
        // scan line going down
        val y = (t * 1.6f % 1f) * (h + dp(120f)) - dp(60f)
        p.style = Paint.Style.FILL
        p.shader = LinearGradient(0f, y - dp(60f), 0f, y, Color.TRANSPARENT, Hud.alpha(color, 60), Shader.TileMode.CLAMP)
        c.drawRect(0f, y - dp(60f), w, y, p); p.shader = null
        // breathing edge
        val edge = (90 + 60 * kotlin.math.sin(t * 2 * Math.PI * 2)).toInt()
        p.style = Paint.Style.STROKE; p.strokeWidth = dp(10f); p.color = Hud.alpha(color, edge)
        c.drawRect(0f, 0f, w, h, p)
    }
}

/** Moving hazard stripes along the top of the panel. */
class HudStripes(context: Context, private val color: Int) : Animated(context, 800) {
    private val p = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    override fun onDraw(c: Canvas) {
        val h = height.toFloat(); val step = dp(28f); val shift = t * step
        p.color = color
        var x = -step * 2 + shift
        while (x < width + step) {
            val path = Path().apply { moveTo(x, h); lineTo(x + h, 0f); lineTo(x + h + step / 2, 0f); lineTo(x + step / 2, h); close() }
            c.drawPath(path, p); x += step
        }
    }
}

/** A warning sign inside two turning dashed rings. */
class HudBadge(context: Context, private val color: Int) : Animated(context, 4000) {
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    override fun onDraw(c: Canvas) {
        val s = minOf(width, height).toFloat(); val cx = width / 2f; val cy = height / 2f
        p.style = Paint.Style.STROKE; p.color = color
        p.strokeWidth = s * 0.03f; p.pathEffect = DashPathEffect(floatArrayOf(s * 0.4f, s * 0.14f, s * 0.08f, s * 0.14f), 0f)
        c.save(); c.rotate(t * 360f, cx, cy); c.drawCircle(cx, cy, s * 0.46f, p); c.restore()
        p.strokeWidth = s * 0.015f; p.pathEffect = DashPathEffect(floatArrayOf(s * 0.03f, s * 0.07f), 0f); p.alpha = 150
        c.save(); c.rotate(-t * 240f, cx, cy); c.drawCircle(cx, cy, s * 0.38f, p); c.restore()
        p.pathEffect = null; p.alpha = 255
        val tri = Path().apply { moveTo(cx, cy - s * 0.26f); lineTo(cx + s * 0.24f, cy + s * 0.18f); lineTo(cx - s * 0.24f, cy + s * 0.18f); close() }
        p.style = Paint.Style.FILL; p.color = if (t % 0.25f < 0.125f) color else Hud.alpha(color, 60)
        c.drawPath(tri, p)
        p.style = Paint.Style.STROKE; p.color = color; p.strokeWidth = s * 0.04f; p.strokeJoin = Paint.Join.ROUND
        c.drawPath(tri, p)
        p.color = Color.WHITE; p.strokeWidth = s * 0.06f; p.strokeCap = Paint.Cap.ROUND
        c.drawLine(cx, cy - s * 0.11f, cx, cy + s * 0.04f, p)
        c.drawPoint(cx, cy + s * 0.11f, p)
    }
}

/** Over the camera picture: corner brackets and a glowing line sweeping up and down. */
class HudScan(context: Context, private val color: Int) : Animated(context, 4400) {
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    override fun onDraw(c: Canvas) {
        val w = width.toFloat(); val h = height.toFloat(); val m = dp(8f); val l = dp(18f)
        p.style = Paint.Style.STROKE; p.strokeWidth = dp(2f); p.color = color
        for ((x, y, dx, dy) in listOf(floatArrayOf(m, m, 1f, 1f), floatArrayOf(w - m, m, -1f, 1f), floatArrayOf(m, h - m, 1f, -1f), floatArrayOf(w - m, h - m, -1f, -1f))) {
            c.drawLine(x, y, x + dx * l, y, p); c.drawLine(x, y, x, y + dy * l, p)
        }
        val k = if (t < 0.5f) t * 2 else 2 - t * 2
        val y = k * (h - dp(3f))
        p.style = Paint.Style.FILL
        p.shader = LinearGradient(0f, y - dp(16f), 0f, y, Color.TRANSPARENT, Hud.alpha(color, 110), Shader.TileMode.CLAMP)
        c.drawRect(0f, y - dp(16f), w, y, p); p.shader = null
        p.color = color; c.drawRect(0f, y, w, y + dp(3f), p)
    }
}


package com.transittech.camsguard

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

/** The loud part: alarm sound (rings even when the phone is on silent) and strong vibration. */
object Alarm {
    private var player: MediaPlayer? = null
    private var vibrator: Vibrator? = null
    @Volatile var ringing = false
        private set

    fun start(context: Context) {
        if (ringing) return
        ringing = true
        try {
            val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
                ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
            player = MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                setDataSource(context, uri)
                isLooping = true
                prepare()
                start()
            }
            // make sure the alarm can be heard
            val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            val max = am.getStreamMaxVolume(AudioManager.STREAM_ALARM)
            if (am.getStreamVolume(AudioManager.STREAM_ALARM) < max * 3 / 4) {
                am.setStreamVolume(AudioManager.STREAM_ALARM, max * 3 / 4, 0)
            }
        } catch (e: Exception) { player = null }
        try {
            val v = if (Build.VERSION.SDK_INT >= 31)
                (context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager).defaultVibrator
            else @Suppress("DEPRECATION") context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
            val pattern = longArrayOf(0, 700, 300, 700, 300, 700, 1000)
            if (Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createWaveform(pattern, 0))
            else @Suppress("DEPRECATION") v.vibrate(pattern, 0)
            vibrator = v
        } catch (e: Exception) { vibrator = null }
    }

    fun stop() {
        ringing = false
        try { player?.stop(); player?.release() } catch (e: Exception) {}
        player = null
        try { vibrator?.cancel() } catch (e: Exception) {}
        vibrator = null
    }
}

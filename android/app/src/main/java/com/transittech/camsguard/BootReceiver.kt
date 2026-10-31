package com.transittech.camsguard

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Start watching again after the phone restarts or the app is updated. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED || intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            try { WatchService.start(context) } catch (e: Exception) { /* Android may refuse; the app starts it when opened */ }
        }
    }
}

package com.transittech.camsguard

import android.content.Context
import android.net.Uri
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.URL

/** What this phone remembers: the CAMS computer's addresses and the phone's sign-in. */
class Prefs(context: Context) {
    private val p = context.getSharedPreferences("cams", Context.MODE_PRIVATE)

    var token: String? get() = p.getString("token", null); set(v) = p.edit().putString("token", v).apply()
    var hosts: List<String>
        get() = (p.getString("hosts", "") ?: "").split(",").filter { it.isNotBlank() }
        set(v) = p.edit().putString("hosts", v.distinct().joinToString(",")).apply()
    var port: Int get() = p.getInt("port", 8765); set(v) = p.edit().putInt("port", v).apply()
    var site: String get() = p.getString("site", "") ?: ""; set(v) = p.edit().putString("site", v).apply()
    var guard: String get() = p.getString("guard", "") ?: ""; set(v) = p.edit().putString("guard", v).apply()
    /** Newest alert already shown (-1 = not known yet: alerts older than this phone are not shown). */
    var lastAlertId: Long get() = p.getLong("last_alert", -1); set(v) = p.edit().putLong("last_alert", v).apply()

    val paired: Boolean get() = !token.isNullOrBlank() && hosts.isNotEmpty()

    fun forget() = p.edit().clear().apply()
}

class Unauthorized : IOException("This phone was disconnected from CAMS.")

/** Talks to the CAMS computer over the site's Wi-Fi. */
class Cams(private val context: Context) {
    val prefs = Prefs(context)
    @Volatile private var base: String? = null

    fun baseUrl(): String? = base

    /** The CAMS computer's address: the last one that worked, the ones from the QR code, or found on the Wi-Fi. */
    fun find(): String? {
        base?.let { if (alive(it)) return it }
        for (h in prefs.hosts) {
            val b = "http://$h:${prefs.port}"
            if (alive(b)) { base = b; return b }
        }
        discover()?.let { (host, port) ->
            prefs.hosts = listOf(host) + prefs.hosts
            prefs.port = port
            val b = "http://$host:$port"
            if (alive(b)) { base = b; return b }
        }
        base = null
        return null
    }

    private fun alive(b: String): Boolean = try {
        val c = open("$b/api/status", "GET", 2500)
        c.responseCode == 200 && JSONObject(c.inputStream.bufferedReader().readText()).optString("app") == "CAMS"
    } catch (e: Exception) { false }

    /** Ask the Wi-Fi "is CAMS here?"; the CAMS computer answers with its address. */
    private fun discover(): Pair<String, Int>? = try {
        DatagramSocket().use { s ->
            s.broadcast = true
            s.soTimeout = 1500
            val ask = "CAMS?".toByteArray()
            s.send(DatagramPacket(ask, ask.size, InetAddress.getByName("255.255.255.255"), 8766))
            val buf = ByteArray(512)
            val pkt = DatagramPacket(buf, buf.size)
            s.receive(pkt)
            val j = JSONObject(String(pkt.data, 0, pkt.length))
            Pair(pkt.address.hostAddress ?: return null, j.optInt("port", 8765))
        }
    } catch (e: Exception) { null }

    private fun open(url: String, method: String, timeout: Int = 6000): HttpURLConnection {
        val c = URL(url).openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = timeout
        c.readTimeout = timeout
        prefs.token?.let { c.setRequestProperty("Authorization", "Bearer $it") }
        return c
    }

    private fun call(path: String, method: String = "GET", body: JSONObject? = null): String {
        val b = base ?: find() ?: throw IOException("Cannot reach the CAMS computer.")
        val c = open("$b$path", method)
        if (body != null) {
            c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            c.outputStream.use { it.write(body.toString().toByteArray()) }
        }
        val code = try { c.responseCode } catch (e: IOException) { base = null; throw e }
        if (code == 401) throw Unauthorized()
        val text = (if (code < 400) c.inputStream else c.errorStream)?.bufferedReader()?.readText() ?: ""
        if (code >= 400) {
            val msg = try { JSONObject(text).optString("detail") } catch (e: Exception) { "" }
            throw IOException(msg.ifBlank { "CAMS answered with error $code." })
        }
        return text
    }

    fun emergencies(): JSONArray = JSONArray(call("/api/alerts/emergencies"))
    fun openAlerts(): JSONArray = JSONArray(call("/api/alerts?open_only=true&limit=20"))
    fun ack(id: Long) { call("/api/alerts/$id/ack", "POST") }

    fun picture(path: String): ByteArray? = try {
        val b = base ?: find()
        val c = open("$b/api/snapshots/$path", "GET")
        if (c.responseCode == 200) c.inputStream.readBytes() else null
    } catch (e: Exception) { null }

    /** Connect this phone with the code from the QR code shown on the CAMS computer. */
    fun pair(qr: String): JSONObject {
        val uri = Uri.parse(qr.trim())
        val frag = uri.fragment ?: ""
        val args = frag.split("&").mapNotNull { kv -> kv.split("=", limit = 2).takeIf { it.size == 2 }?.let { it[0] to Uri.decode(it[1]) } }.toMap()
        val code = args["pair"] ?: throw IOException("This is not a CAMS code. Scan the code shown on the CAMS computer in Settings, Phones, Add a phone.")
        val port = args["p"]?.toIntOrNull() ?: uri.port.takeIf { it > 0 } ?: 8765
        val hosts = (listOfNotNull(uri.host) + (args["h"] ?: "").split(",")).filter { it.isNotBlank() }
        prefs.hosts = hosts
        prefs.port = port
        prefs.token = null
        base = null
        find() ?: throw IOException("Cannot reach the CAMS computer. Connect this phone to the same Wi-Fi as the CAMS computer and try again.")
        val device = "${Build.MANUFACTURER.replaceFirstChar { it.uppercase() }} ${Build.MODEL}".take(60)
        val r = JSONObject(call("/api/phones/pair", "POST", JSONObject().put("code", code).put("device", device)))
        prefs.token = r.getString("token")
        prefs.site = r.optString("site_name")
        val u = r.optJSONObject("user")
        prefs.guard = u?.optString("full_name")?.ifBlank { u.optString("username") } ?: ""
        return r
    }
}

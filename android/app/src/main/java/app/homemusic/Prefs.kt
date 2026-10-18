package app.homemusic

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import java.util.UUID

object Prefs {
    private lateinit var sp: SharedPreferences

    fun init(ctx: Context) {
        sp = ctx.getSharedPreferences("hm", Context.MODE_PRIVATE)
        if (sp.getString("device_id", null) == null) sp.edit().putString("device_id", UUID.randomUUID().toString()).apply()
    }

    var server: String
        get() = sp.getString("server", "") ?: ""
        set(v) = sp.edit().putString("server", v.trim().trimEnd('/')).apply()
    var token: String
        get() = sp.getString("token", "") ?: ""
        set(v) = sp.edit().putString("token", v).apply()
    val deviceId: String get() = sp.getString("device_id", "") ?: ""
    var deviceName: String
        get() = sp.getString("device_name", null) ?: (Build.MODEL ?: "Telefon")
        set(v) = sp.edit().putString("device_name", v).apply()
    var dlIndex: String
        get() = sp.getString("dl_index", "[]") ?: "[]"
        set(v) = sp.edit().putString("dl_index", v).apply()
    var lastQueue: String
        get() = sp.getString("last_queue", "") ?: ""
        set(v) = sp.edit().putString("last_queue", v).apply()
}

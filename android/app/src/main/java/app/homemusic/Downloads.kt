package app.homemusic

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Offline hallgatás: a számok a telefon tárolójába kerülnek, a szerver nélkül is lejátszhatók. */
object Downloads {
    private lateinit var dir: File
    private val _index = MutableStateFlow<Map<String, Track>>(emptyMap())
    val index = _index.asStateFlow()
    private val _busy = MutableStateFlow<Set<String>>(emptySet())
    val busy = _busy.asStateFlow()

    fun init(ctx: Context) {
        dir = File(ctx.filesDir, "offline").apply { mkdirs() }
        val m = LinkedHashMap<String, Track>()
        try {
            val a = JSONArray(Prefs.dlIndex)
            for (o in a.objs()) {
                val t = Track.from(o)
                if (file(t.id).exists()) m[t.id] = t
            }
        } catch (e: Exception) { /* üres index */ }
        _index.value = m
    }

    fun file(vid: String) = File(dir, "$vid.audio")
    private fun lyrFile(vid: String) = File(dir, "$vid.lyr")
    fun has(vid: String) = _index.value.containsKey(vid)
    fun tracks(): List<Track> = _index.value.values.toList()
    fun totalBytes(): Long = dir.listFiles()?.sumOf { it.length() } ?: 0L

    private fun persist() {
        Prefs.dlIndex = JSONArray(_index.value.values.map { it.toJson() }).toString()
    }

    fun cachedLyrics(vid: String): Lyrics? = try { if (lyrFile(vid).exists()) Lyrics.from(JSONObject(lyrFile(vid).readText())) else null } catch (e: Exception) { null }

    suspend fun download(t: Track) {
        if (has(t.id) || _busy.value.contains(t.id)) return
        _busy.value = _busy.value + t.id
        try {
            withContext(Dispatchers.IO) {
                val tmp = File(dir, "${t.id}.part")
                val req = Request.Builder().url(Api.audioUrl(t.id)).build()
                Api.client.newCall(req).execute().use { r ->
                    if (!r.isSuccessful) throw ApiException("Letöltési hiba (HTTP ${r.code})", r.code)
                    r.body!!.byteStream().use { input -> tmp.outputStream().use { out -> input.copyTo(out) } }
                }
                if (!tmp.renameTo(file(t.id))) throw ApiException("Nem sikerült elmenteni a fájlt")
                try {
                    val ly = Api.obj("/api/lyrics/${t.id}")
                    lyrFile(t.id).writeText(ly.toString())
                } catch (e: Exception) { /* nincs szöveg */ }
            }
            _index.value = _index.value + (t.id to t)
            persist()
        } finally {
            _busy.value = _busy.value - t.id
        }
    }

    fun remove(vid: String) {
        file(vid).delete(); lyrFile(vid).delete()
        _index.value = _index.value - vid
        persist()
    }
}

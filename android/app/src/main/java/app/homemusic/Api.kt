package app.homemusic

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

class ApiException(msg: String, val code: Int = 0) : Exception(msg)

object Api {
    val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(180, TimeUnit.SECONDS)     // az első lejátszás letöltést vár ki a szerveren
        .pingInterval(25, TimeUnit.SECONDS)
        .build()

    @Volatile var onUnauthorized: () -> Unit = {}

    fun enc(s: String): String = URLEncoder.encode(s, "UTF-8").replace("+", "%20")
    fun base(): String = Prefs.server.trimEnd('/')
    fun audioUrl(vid: String): String = "${base()}/api/audio/$vid?token=${enc(Prefs.token)}"
    fun wsUrl(): String {
        val b = base().replaceFirst("https://", "wss://").replaceFirst("http://", "ws://")
        return "$b/ws?token=${enc(Prefs.token)}&device_id=${Prefs.deviceId}&name=${enc(Prefs.deviceName)}&kind=android"
    }

    private fun send(path: String, method: String, body: JSONObject?, auth: Boolean = true): String {
        val rb = body?.toString()?.toRequestBody("application/json".toMediaType())
        val b = Request.Builder().url(base() + path)
        if (auth && Prefs.token.isNotEmpty()) b.header("Authorization", "Bearer ${Prefs.token}")
        when (method) {
            "GET" -> b.get()
            "DELETE" -> if (rb != null) b.delete(rb) else b.delete()
            else -> b.method(method, rb ?: "{}".toRequestBody("application/json".toMediaType()))
        }
        return try {
            client.newCall(b.build()).execute().use { r ->
                val txt = r.body?.string() ?: ""
                if (!r.isSuccessful) {
                    if (r.code == 401 && auth) onUnauthorized()
                    val detail = try { JSONObject(txt).optString("detail", txt) } catch (e: Exception) { txt }
                    throw ApiException(detail.ifBlank { "HTTP ${r.code}" }, r.code)
                }
                txt
            }
        } catch (e: ApiException) {
            throw e
        } catch (e: Exception) {
            throw ApiException("Nem érem el a szervert: ${e.message ?: e.javaClass.simpleName}")
        }
    }

    suspend fun obj(path: String, method: String = "GET", body: JSONObject? = null): JSONObject =
        withContext(Dispatchers.IO) { JSONObject(send(path, method, body)) }

    suspend fun arr(path: String, method: String = "GET", body: JSONObject? = null): JSONArray =
        withContext(Dispatchers.IO) { JSONArray(send(path, method, body)) }

    suspend fun login(server: String, password: String): String = withContext(Dispatchers.IO) {
        Prefs.server = server
        val o = JSONObject(send("/api/login", "POST", JSONObject().put("password", password), auth = false))
        o.getString("token")
    }

    // ---- böngészés
    suspend fun search(q: String, filter: String? = null): List<Item> =
        arr("/api/search?q=${enc(q)}" + (if (filter != null) "&filter=$filter" else "")).items()

    suspend fun home(): List<Shelf> = arr("/api/home").objs().map { Shelf(it.optString("title"), it.optJSONArray("items")?.items() ?: emptyList()) }
    suspend fun radio(vid: String): List<Track> = arr("/api/radio/$vid").tracks()
    suspend fun mix(kind: String): List<Track> = arr("/api/mix/$kind").tracks()
    suspend fun library(kind: String): List<Track> = arr("/api/library/$kind").tracks()

    class Page(val title: String, val subtitle: String, val thumb: String?, val tracks: List<Track>, val shelves: List<Shelf>, val fallback: Boolean = false)

    suspend fun album(id: String): Page {
        val o = obj("/api/album/${enc(id)}")
        val artists = o.optJSONArray("artists")?.let { a -> (0 until a.length()).joinToString(", ") { a.optString(it) } } ?: ""
        return Page(o.optString("title"), "Album · $artists ${o.optString("year", "")}".trim(), o.s("thumbnail"), o.optJSONArray("tracks")?.tracks() ?: emptyList(), emptyList())
    }

    suspend fun ytmPlaylist(id: String): Page {
        val o = obj("/api/ytm/playlist/${enc(id)}")
        return Page(o.optString("title"), "Lejátszási lista", o.s("thumbnail"), o.optJSONArray("tracks")?.tracks() ?: emptyList(), emptyList())
    }

    suspend fun localPlaylist(id: Int): Page {
        val o = obj("/api/playlists/$id")
        return Page(o.optString("title"), "Saját lista", o.s("thumbnail"), o.optJSONArray("tracks")?.tracks() ?: emptyList(), emptyList())
    }

    suspend fun artist(id: String, name: String?): Page {
        val o = obj("/api/artist/${enc(id.ifEmpty { "_" })}" + (if (!name.isNullOrBlank()) "?name=${enc(name)}" else ""))
        val sec = o.optJSONObject("sections") ?: JSONObject()
        val songs = sec.optJSONArray("songs")?.items()?.mapNotNull { it.track } ?: emptyList()
        val names = mapOf("albums" to "Albumok", "singles" to "Kislemezek", "videos" to "Videók", "related" to "Hasonló előadók")
        val shelves = names.mapNotNull { (k, t) -> sec.optJSONArray(k)?.items()?.takeIf { it.isNotEmpty() }?.let { Shelf(t, it) } }
        return Page(o.optString("name", name ?: ""), "Előadó", o.s("thumbnail"), songs, shelves, o.optBoolean("fallback"))
    }

    // ---- saját könyvtár
    class PlaylistInfo(val id: Int, val title: String, val count: Int, val thumb: String?)
    suspend fun playlists(): List<PlaylistInfo> = arr("/api/playlists").objs().map { PlaylistInfo(it.optInt("id"), it.optString("title"), it.optInt("count"), it.s("thumbnail")) }
    suspend fun createPlaylist(title: String, vids: List<String>) = obj("/api/playlists", "POST", JSONObject().put("title", title).put("video_ids", JSONArray(vids)))
    suspend fun addToPlaylist(pid: Int, vids: List<String>) = obj("/api/playlists/$pid/items", "POST", JSONObject().put("video_ids", JSONArray(vids)))
    suspend fun like(vid: String, liked: Boolean) = obj("/api/like/$vid", "POST", JSONObject().put("liked", liked))

    // ---- lejátszás / szöveg / beállítások
    suspend fun playStart(vid: String): Int = obj("/api/play/start", "POST", JSONObject().put("video_id", vid).put("device_id", Prefs.deviceId)).optInt("event_id")
    suspend fun playProgress(event: Int, sec: Double) = obj("/api/play/progress", "POST", JSONObject().put("event_id", event).put("listened_sec", sec))
    suspend fun lyrics(vid: String): Lyrics? = try { Lyrics.from(obj("/api/lyrics/$vid")) } catch (e: ApiException) { if (e.code == 404) null else throw e }
    suspend fun lyricsLine(vid: String, idx: Int, t: Long) = obj("/api/lyrics/$vid/line", "PATCH", JSONObject().put("idx", idx).put("t", t))
    suspend fun settings(): Settings = Settings.from(obj("/api/settings"))
    suspend fun saveSettings(changes: JSONObject): Settings = Settings.from(obj("/api/settings", "PUT", changes))
    suspend fun prefetch(ids: List<String>) = obj("/api/prefetch", "POST", JSONObject().put("ids", JSONArray(ids)))
    suspend fun status(): JSONObject = obj("/api/status")
}

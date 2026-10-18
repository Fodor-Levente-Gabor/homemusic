package app.homemusic

import org.json.JSONArray
import org.json.JSONObject

fun JSONObject.s(k: String): String? = if (has(k) && !isNull(k)) optString(k).ifEmpty { null } else null
fun JSONArray.objs(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }

data class Track(
    val id: String,
    val title: String,
    val artist: String,
    val artists: List<String> = emptyList(),
    val album: String = "",
    val albumId: String? = null,
    val durationSec: Int = 0,
    val thumb: String? = null,
    val gainDb: Double = 0.0,
    val liked: Boolean = false,
    val cached: Boolean = false,
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("video_id", id); put("title", title); put("artist", artist)
        put("artists", JSONArray(artists)); put("album", album); put("album_id", albumId ?: JSONObject.NULL)
        put("duration_sec", durationSec); put("thumbnail", thumb ?: JSONObject.NULL)
        put("gain_db", gainDb); put("liked", liked); put("cached", cached)
    }

    companion object {
        fun from(o: JSONObject): Track {
            val names = ArrayList<String>()
            o.optJSONArray("artists")?.let { a -> for (i in 0 until a.length()) names.add(a.optString(i)) }
            return Track(
                id = o.optString("video_id"),
                title = o.optString("title"),
                artist = o.optString("artist"),
                artists = names,
                album = o.optString("album", ""),
                albumId = o.s("album_id"),
                durationSec = o.optInt("duration_sec", 0),
                thumb = o.s("thumbnail"),
                gainDb = o.optDouble("gain_db", 0.0).let { if (it.isNaN()) 0.0 else it },
                liked = o.optBoolean("liked", false),
                cached = o.optBoolean("cached", false),
            )
        }
    }
}

/** Egy találat/kártya: szám, album, előadó vagy lejátszási lista. */
data class Item(val type: String, val id: String, val title: String, val subtitle: String, val thumb: String?, val track: Track?) {
    companion object {
        fun from(o: JSONObject): Item? {
            return when (o.optString("type")) {
                "track" -> Track.from(o).let { t -> if (t.id.isEmpty()) null else Item("track", t.id, t.title, t.artist, t.thumb, t) }
                "album", "artist", "playlist" -> Item(o.optString("type"), o.optString("id"), o.optString("title"), o.optString("subtitle", ""), o.s("thumbnail"), null)
                else -> null
            }
        }
    }
}

fun JSONArray.items(): List<Item> = objs().mapNotNull { Item.from(it) }
fun JSONArray.tracks(): List<Track> = objs().map { Track.from(it) }.filter { it.id.isNotEmpty() }

data class Shelf(val title: String, val items: List<Item>)
data class Device(val id: String, val name: String, val kind: String, val playing: Boolean, val title: String?, val artist: String?)
data class LyricLine(val t: Long?, val text: String)
data class Lyrics(val lines: List<LyricLine>, val synced: Boolean, val source: String) {
    companion object {
        fun from(o: JSONObject): Lyrics {
            val ls = o.optJSONArray("lines")?.objs()?.map { LyricLine(if (it.isNull("t")) null else it.optLong("t"), it.optString("text")) } ?: emptyList()
            return Lyrics(ls, o.optBoolean("synced"), o.optString("source", ""))
        }
    }
}
data class Settings(
    val cacheLimitGb: Double = 100.0, val crossfadeMs: Int = 0, val gapless: Boolean = true, val normalize: Boolean = true,
    val targetLufs: Double = -14.0, val eqEnabled: Boolean = false, val eqGains: List<Double> = List(10) { 0.0 }, val preampDb: Double = 0.0,
) {
    companion object {
        fun from(o: JSONObject): Settings {
            val g = ArrayList<Double>()
            o.optJSONArray("eq_gains")?.let { a -> for (i in 0 until a.length()) g.add(a.optDouble(i, 0.0)) }
            while (g.size < 10) g.add(0.0)
            return Settings(
                o.optDouble("cache_limit_gb", 100.0), o.optInt("crossfade_ms", 0), o.optBoolean("gapless", true), o.optBoolean("normalize", true),
                o.optDouble("target_lufs", -14.0), o.optBoolean("eq_enabled", false), g.take(10), o.optDouble("preamp_db", 0.0),
            )
        }
    }
}

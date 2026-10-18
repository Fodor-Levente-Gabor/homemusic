package app.homemusic

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.os.SystemClock
import androidx.core.content.ContextCompat
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject

data class PState(
    val queue: List<Track> = emptyList(),
    val index: Int = -1,
    val playing: Boolean = false,
    val loading: Boolean = false,
    val shuffle: Boolean = false,
    val repeat: Int = 0,          // 0 ki, 1 összes, 2 egy
    val error: String? = null,
) {
    val track: Track? get() = queue.getOrNull(index)
}

/**
 * A lejátszás és a távirányítás közös pontja (a felület csak ezt használja).
 * Helyi lejátszás: MediaController -> PlaybackService. Távirányítás: WebSocket (ugyanaz a protokoll, mint a webes kliensé).
 */
object PlayerHub {
    private lateinit var app: Context
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var ctl: MediaController? = null
    private val pending = ArrayList<(MediaController) -> Unit>()
    private val trackCache = HashMap<String, Track>()

    private val local = MutableStateFlow(PState())
    private val remote = MutableStateFlow(PState())
    val settings = MutableStateFlow(Settings())
    private val _devices = MutableStateFlow<List<Device>>(emptyList())
    val devices: StateFlow<List<Device>> = _devices.asStateFlow()
    private val _target = MutableStateFlow<String?>(null)
    val target: StateFlow<String?> = _target.asStateFlow()
    private val _online = MutableStateFlow(false)
    val wsOnline: StateFlow<Boolean> = _online.asStateFlow()
    private val _toast = MutableSharedFlow<String>(extraBufferCapacity = 8)
    val toasts: SharedFlow<String> = _toast.asSharedFlow()

    /** Amit a felület mutat: a helyi lejátszó, vagy a vezérelt eszköz. */
    val view: StateFlow<PState> by lazy {
        combine(local, remote, _target) { l, r, t -> if (t == null) l else r }.stateIn(scope, SharingStarted.Eagerly, PState())
    }
    private val _pos = MutableStateFlow(0L)
    val posMs: StateFlow<Long> = _pos.asStateFlow()
    private val _dur = MutableStateFlow(0L)
    val durMs: StateFlow<Long> = _dur.asStateFlow()

    // ---- távoli állapot
    private var remoteJson = JSONObject()
    private var remotePos = 0L
    private var remoteDur = 0L
    private var remoteRecv = 0L

    // ---- hallgatási statisztika a szervernek
    private var eventId: Int? = null
    private var eventVid: String? = null
    private var listened = 0.0
    private var lastSent = 0.0

    private var ws: WebSocket? = null
    private var retry = 0
    private var wantWs = false
    private var reportJob: Job? = null
    private var lastReport = 0L

    fun init(ctx: Context) {
        app = ctx.applicationContext
        val token = SessionToken(app, ComponentName(app, PlaybackService::class.java))
        val f = MediaController.Builder(app, token).buildAsync()
        f.addListener({
            try {
                val c = f.get()
                ctl = c
                c.addListener(listener)
                pending.forEach { it(c) }
                pending.clear()
                pull()
            } catch (e: Exception) {
                _toast.tryEmit("A lejátszó nem indult el: ${e.message}")
            }
        }, ContextCompat.getMainExecutor(app))
        scope.launch { ticker() }
    }

    private fun onCtl(block: (MediaController) -> Unit) {
        val c = ctl
        if (c != null) block(c) else pending.add(block)
    }

    // ------------------------------------------------------------------ helyi állapot
    private val listener = object : Player.Listener {
        override fun onEvents(player: Player, events: Player.Events) {
            pull()
            if (events.contains(Player.EVENT_MEDIA_ITEM_TRANSITION)) onTrackChanged()
            scheduleReport()
        }
    }

    fun mediaItem(t: Track): MediaItem {
        trackCache[t.id] = t
        val uri = if (Downloads.has(t.id)) Uri.fromFile(Downloads.file(t.id)) else Uri.parse(Api.audioUrl(t.id))
        val extras = Bundle().apply { putDouble("gain", t.gainDb); putString("vid", t.id) }
        val md = MediaMetadata.Builder().setTitle(t.title).setArtist(t.artist).setAlbumTitle(t.album).setExtras(extras)
        t.thumb?.let { md.setArtworkUri(Uri.parse(it)) }
        return MediaItem.Builder().setMediaId(t.id).setUri(uri).setMediaMetadata(md.build()).build()
    }

    private fun trackOf(item: MediaItem): Track {
        val id = item.mediaId
        return trackCache[id] ?: Track(id, item.mediaMetadata.title?.toString() ?: id, item.mediaMetadata.artist?.toString() ?: "")
    }

    private fun pull() {
        val c = ctl ?: return
        val q = ArrayList<Track>(c.mediaItemCount)
        for (i in 0 until c.mediaItemCount) q.add(trackOf(c.getMediaItemAt(i)))
        val st = c.playbackState
        local.value = PState(
            queue = q, index = if (c.mediaItemCount == 0) -1 else c.currentMediaItemIndex,
            playing = c.playWhenReady && st != Player.STATE_ENDED && st != Player.STATE_IDLE,
            loading = st == Player.STATE_BUFFERING,
            shuffle = c.shuffleModeEnabled,
            repeat = when (c.repeatMode) { Player.REPEAT_MODE_ALL -> 1; Player.REPEAT_MODE_ONE -> 2; else -> 0 },
            error = c.playerError?.let { "Lejátszási hiba: ${it.errorCodeName}" },
        )
    }

    private suspend fun ticker() {
        var n = 0
        while (true) {
            delay(500)
            n++
            val c = ctl
            if (_target.value == null) {
                if (c != null) {
                    _pos.value = c.currentPosition.coerceAtLeast(0)
                    val d = c.duration
                    _dur.value = if (d == C.TIME_UNSET || d <= 0) (local.value.track?.durationSec ?: 0) * 1000L else d
                    if (local.value.playing && !local.value.loading) {
                        listened += 0.5
                        if (listened - lastSent >= 10) sendProgress()
                        if (n % 6 == 0) report(false)
                    }
                }
            } else {
                val extra = if (remote.value.playing) SystemClock.elapsedRealtime() - remoteRecv else 0L
                _pos.value = (remotePos + extra).coerceAtMost(if (remoteDur > 0) remoteDur else Long.MAX_VALUE)
                _dur.value = remoteDur
            }
        }
    }

    private fun onTrackChanged() {
        sendProgress()
        val t = local.value.track
        eventId = null; eventVid = t?.id; listened = 0.0; lastSent = 0.0
        if (t != null) {
            scope.launch { try { eventId = Api.playStart(t.id) } catch (e: Exception) { /* offline */ } }
            val c = ctl
            if (c != null) {
                val ids = ArrayList<String>()
                for (i in c.currentMediaItemIndex + 1..minOf(c.mediaItemCount - 1, c.currentMediaItemIndex + 2)) {
                    val id = c.getMediaItemAt(i).mediaId
                    if (!Downloads.has(id)) ids.add(id)
                }
                if (ids.isNotEmpty()) scope.launch { try { Api.prefetch(ids) } catch (e: Exception) { /* */ } }
            }
        }
    }

    private fun sendProgress() {
        val ev = eventId ?: return
        lastSent = listened
        val l = listened
        scope.launch { try { Api.playProgress(ev, l) } catch (e: Exception) { /* */ } }
    }

    // ------------------------------------------------------------------ parancsok
    /** A felület hívja: vezérelt eszköz esetén odaküldi, különben helyben végrehajtja. */
    fun cmd(name: String, args: JSONObject = JSONObject()) {
        val t = _target.value
        if (t != null) send(JSONObject().put("type", "command").put("target", t).put("cmd", name).put("args", args))
        else exec(name, args)
    }

    private fun tracksOf(a: JSONArray?): List<Track> = a?.objs()?.map { Track.from(it) }?.filter { it.id.isNotEmpty() } ?: emptyList()

    fun exec(name: String, a: JSONObject) {
        onCtl { c ->
            when (name) {
                "playQueue" -> {
                    val ts = tracksOf(a.optJSONArray("tracks"))
                    if (ts.isNotEmpty()) {
                        c.setMediaItems(ts.map { mediaItem(it) }, a.optInt("index", 0).coerceIn(0, ts.size - 1), a.optLong("start_ms", 0))
                        c.prepare()
                        if (a.optBoolean("autoplay", true)) c.play()
                    }
                }
                "play" -> { if (c.playbackState == Player.STATE_IDLE) c.prepare(); c.play() }
                "pause" -> c.pause()
                "toggle" -> if (c.playWhenReady && c.playbackState != Player.STATE_ENDED) c.pause() else { if (c.playbackState == Player.STATE_IDLE) c.prepare(); c.play() }
                "next" -> c.seekToNextMediaItem()
                "prev" -> c.seekToPrevious()
                "seek" -> c.seekTo(a.optLong("position_ms", 0))
                "shuffle" -> c.shuffleModeEnabled = a.optBoolean("on")
                "repeat" -> c.repeatMode = when (a.optString("mode")) { "all" -> Player.REPEAT_MODE_ALL; "one" -> Player.REPEAT_MODE_ONE; else -> Player.REPEAT_MODE_OFF }
                "playIndex" -> { c.seekTo(a.optInt("index"), 0); c.play() }
                "enqueue" -> {
                    val items = tracksOf(a.optJSONArray("tracks")).map { mediaItem(it) }
                    if (a.optBoolean("next") && c.mediaItemCount > 0) c.addMediaItems(c.currentMediaItemIndex + 1, items) else c.addMediaItems(items)
                    if (c.mediaItemCount == items.size) { c.prepare(); c.play() }
                }
                "removeAt" -> if (a.optInt("index") in 0 until c.mediaItemCount) c.removeMediaItem(a.optInt("index"))
                "moveQueue" -> {
                    val f = a.optInt("from"); val t = a.optInt("to")
                    if (f in 0 until c.mediaItemCount && t in 0 until c.mediaItemCount) c.moveMediaItem(f, t)
                }
                "insertAt" -> c.addMediaItems(a.optInt("at").coerceIn(0, c.mediaItemCount), tracksOf(a.optJSONArray("tracks")).map { mediaItem(it) })
            }
            pull()
        }
    }

    // kényelmi hívások a felületnek
    private fun slim(ts: List<Track>) = JSONArray(ts.map { it.toJson() })
    fun playTracks(ts: List<Track>, index: Int = 0) = cmd("playQueue", JSONObject().put("tracks", slim(ts)).put("index", index))
    fun enqueue(ts: List<Track>, next: Boolean = false) = cmd("enqueue", JSONObject().put("tracks", slim(ts)).put("next", next))
    fun toggle() = cmd("toggle")
    fun next() = cmd("next")
    fun prev() = cmd("prev")
    fun seek(ms: Long) = cmd("seek", JSONObject().put("position_ms", ms))
    fun playIndex(i: Int) = cmd("playIndex", JSONObject().put("index", i))
    fun removeAt(i: Int) = cmd("removeAt", JSONObject().put("index", i))
    fun move(from: Int, to: Int) = cmd("moveQueue", JSONObject().put("from", from).put("to", to))
    fun setShuffle(on: Boolean) = cmd("shuffle", JSONObject().put("on", on))
    fun cycleRepeat() {
        val next = when (view.value.repeat) { 0 -> "all"; 1 -> "one"; else -> "off" }
        cmd("repeat", JSONObject().put("mode", next))
    }

    /** Mint a YouTube Music: egy számra kattintva az adott szám + hasonló számok (rádió) szólnak. */
    fun playRadio(t: Track) {
        playTracks(listOf(t), 0)
        scope.launch {
            try {
                val rest = Api.radio(t.id).filter { it.id != t.id }.shuffled()
                if (rest.isNotEmpty()) enqueue(rest)
            } catch (e: Exception) { /* a szám rádió nélkül is szól */ }
        }
    }

    fun toast(msg: String) { _toast.tryEmit(msg) }

    // ------------------------------------------------------------------ távirányítás
    fun setTarget(id: String?) {
        _target.value = id
        if (id != null) devices.value.firstOrNull { it.id == id }?.let { adoptRemote(JSONObject(rawStates[id] ?: "{}"), true) }
    }

    /** A helyi lejátszás átvitele a másik eszközre. */
    fun transferTo(id: String) {
        val s = local.value
        val c = ctl
        if (s.queue.isNotEmpty() && c != null) {
            send(JSONObject().put("type", "command").put("target", id).put("cmd", "playQueue").put("args",
                JSONObject().put("tracks", slim(s.queue)).put("index", s.index).put("start_ms", c.currentPosition).put("autoplay", true)))
            c.pause()
        }
        setTarget(id)
    }

    /** A vezérelt távoli eszköz lejátszásának áthozása ide. */
    fun pullHere() {
        val id = _target.value ?: return
        val r = remote.value
        val pos = _pos.value
        send(JSONObject().put("type", "command").put("target", id).put("cmd", "pause").put("args", JSONObject()))
        _target.value = null
        if (r.queue.isNotEmpty()) exec("playQueue", JSONObject().put("tracks", slim(r.queue)).put("index", r.index).put("start_ms", pos).put("autoplay", true))
    }

    private val rawStates = HashMap<String, String>()

    private fun adoptRemote(s: JSONObject, full: Boolean) {
        if (full) remoteJson = JSONObject()
        val keys = s.keys()
        while (keys.hasNext()) {
            val k = keys.next()
            when (k) {
                "position_ms" -> { remotePos = s.optLong(k); remoteRecv = SystemClock.elapsedRealtime() }
                "duration_ms" -> remoteDur = s.optLong(k)
                else -> remoteJson.put(k, s.get(k))
            }
        }
        remote.value = PState(
            queue = tracksOf(remoteJson.optJSONArray("queue")),
            index = remoteJson.optInt("index", -1),
            playing = remoteJson.optBoolean("playing"),
            loading = remoteJson.optBoolean("loading"),
            shuffle = remoteJson.optBoolean("shuffle"),
            repeat = when (remoteJson.optString("repeat")) { "all" -> 1; "one" -> 2; else -> 0 },
            error = remoteJson.s("error"),
        )
    }

    // ------------------------------------------------------------------ WebSocket
    fun connect() {
        wantWs = true
        if (ws != null || Prefs.server.isEmpty() || Prefs.token.isEmpty()) return
        val req = try { Request.Builder().url(Api.wsUrl()).build() } catch (e: Exception) { return }
        ws = Api.client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                scope.launch { retry = 0; _online.value = true; report(true) }
                scope.launch { try { settings.value = Api.settings() } catch (e: Exception) { /* */ } }
            }
            override fun onMessage(webSocket: WebSocket, text: String) {
                scope.launch { try { handleMessage(JSONObject(text)) } catch (e: Exception) { /* hibás üzenet */ } }
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { lost(webSocket) }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { lost(webSocket) }
        })
    }

    private fun lost(w: WebSocket) {
        scope.launch {
            if (ws !== w) return@launch
            ws = null
            _online.value = false
            if (wantWs) {
                retry++
                delay(minOf(15000L, 500L * (1 shl minOf(retry, 5))))
                if (wantWs && ws == null) connect()
            }
        }
    }

    fun disconnect() {
        wantWs = false
        ws?.close(1000, null); ws = null
        _online.value = false
        _devices.value = emptyList()
        _target.value = null
    }

    private fun send(m: JSONObject) { ws?.send(m.toString()) }

    private fun handleMessage(m: JSONObject) {
        when (m.optString("type")) {
            "devices" -> {
                val arr = m.optJSONArray("devices")?.objs() ?: emptyList()
                val list = ArrayList<Device>()
                rawStates.clear()
                for (d in arr) {
                    if (d.optString("id") == Prefs.deviceId) continue
                    val st = d.optJSONObject("state") ?: JSONObject()
                    rawStates[d.optString("id")] = st.toString()
                    list.add(toDevice(d.optString("id"), d.optString("name"), d.optString("kind"), st))
                }
                _devices.value = list
                val t = _target.value
                if (t != null) {
                    if (list.none { it.id == t }) { _target.value = null; toast("A vezérelt eszköz lecsatlakozott") }
                    else adoptRemote(JSONObject(rawStates[t] ?: "{}"), true)
                }
            }
            "state" -> {
                val id = m.optString("device_id")
                val st = m.optJSONObject("state") ?: return
                val merged = JSONObject(rawStates[id] ?: "{}")
                val ks = st.keys(); while (ks.hasNext()) { val k = ks.next(); merged.put(k, st.get(k)) }
                rawStates[id] = merged.toString()
                _devices.value = _devices.value.map { if (it.id == id) toDevice(it.id, it.name, it.kind, merged) else it }
                if (id == _target.value) adoptRemote(st, false)
            }
            "command" -> exec(m.optString("cmd"), m.optJSONObject("args") ?: JSONObject())
            "settings" -> m.optJSONObject("settings")?.let { settings.value = Settings.from(it) }
            "error" -> toast(m.optString("error", "Hiba"))
        }
    }

    private fun toDevice(id: String, name: String, kind: String, st: JSONObject): Device {
        val q = st.optJSONArray("queue")
        val t = q?.optJSONObject(st.optInt("index", -1))
        return Device(id, name, kind, st.optBoolean("playing"), t?.optString("title"), t?.optString("artist"))
    }

    private fun scheduleReport() {
        reportJob?.cancel()
        reportJob = scope.launch { delay(150); report(true) }
    }

    private fun report(full: Boolean) {
        if (ws == null || _target.value != null) return
        val s = local.value
        val st = JSONObject().put("playing", s.playing).put("position_ms", _pos.value).put("duration_ms", _dur.value)
        if (full) {
            st.put("queue", slim(s.queue)).put("index", s.index).put("volume", 1.0).put("shuffle", s.shuffle)
                .put("repeat", when (s.repeat) { 1 -> "all"; 2 -> "one"; else -> "off" }).put("loading", s.loading)
                .put("error", s.error ?: JSONObject.NULL)
        }
        lastReport = SystemClock.elapsedRealtime()
        send(JSONObject().put("type", "state").put("state", st))
    }

    fun rename(name: String) {
        Prefs.deviceName = name
        send(JSONObject().put("type", "rename").put("name", name))
    }
}

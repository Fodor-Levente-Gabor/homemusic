package app.homemusic

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.DownloadDone
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.PlaylistAdd
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.RepeatOne
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

fun fmt(ms: Long): String {
    val s = (ms / 1000).coerceAtLeast(0)
    return "%d:%02d".format(s / 60, s % 60)
}

// ---------------------------------------------------------------- mini lejátszó
@Composable
fun MiniPlayer() {
    val v by PlayerHub.view.collectAsState()
    val target by PlayerHub.target.collectAsState()
    val devices by PlayerHub.devices.collectAsState()
    val t = v.track ?: return
    Column(Modifier.fillMaxWidth().background(Surface2).clickable { Nav.playerOpen.value = true }) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Cover(t.thumb, 44.dp)
            Column(Modifier.weight(1f).padding(horizontal = 10.dp)) {
                Text(t.title, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium)
                val tn = devices.firstOrNull { it.id == target }?.name
                Text(if (tn != null) "▶ $tn · ${t.artist}" else t.artist, maxLines = 1, overflow = TextOverflow.Ellipsis, color = Muted, fontSize = 13.sp)
            }
            IconButton(onClick = { PlayerHub.toggle() }) {
                if (v.loading && v.playing) CircularProgressIndicator(Modifier.size(24.dp), color = Color.White, strokeWidth = 2.dp)
                else Icon(if (v.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, contentDescription = "Lejátszás/szünet", modifier = Modifier.size(30.dp))
            }
            IconButton(onClick = { PlayerHub.next() }) { Icon(Icons.Filled.SkipNext, contentDescription = "Következő") }
        }
        val pos by PlayerHub.posMs.collectAsState()
        val dur by PlayerHub.durMs.collectAsState()
        LinearProgressIndicator(progress = { if (dur > 0) (pos.toFloat() / dur).coerceIn(0f, 1f) else 0f }, modifier = Modifier.fillMaxWidth().height(2.dp), color = Accent, trackColor = Color.Transparent)
    }
}

// ---------------------------------------------------------------- teljes képernyős lejátszó
@Composable
fun FullPlayer() {
    var tab by remember { mutableStateOf("now") }
    val v by PlayerHub.view.collectAsState()
    Column(Modifier.fillMaxSize().background(Bg).pointerInput(Unit) { detectTapGestures { } }) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { Nav.playerOpen.value = false }) { Icon(Icons.Filled.KeyboardArrowDown, contentDescription = "Bezár", modifier = Modifier.size(32.dp)) }
            Row(Modifier.weight(1f), horizontalArrangement = Arrangement.Center) {
                Chip("Most", tab == "now") { tab = "now" }
                Spacer(Modifier.size(6.dp))
                Chip("Következők", tab == "queue") { tab = "queue" }
                Spacer(Modifier.size(6.dp))
                Chip("Szöveg", tab == "lyrics") { tab = "lyrics" }
            }
            IconButton(onClick = { Nav.devicesOpen.value = true }) { Icon(Icons.Filled.Devices, contentDescription = "Eszközök") }
        }
        val t = v.track
        if (t == null) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("Nincs lejátszás", color = Muted) }
        } else when (tab) {
            "queue" -> QueueTab(v)
            "lyrics" -> LyricsTab(t)
            else -> NowTab(t, v)
        }
    }
}

@Composable
fun NowTab(t: Track, v: PState) {
    val scope = rememberCoroutineScope()
    var liked by remember(t.id) { mutableStateOf(t.liked) }
    val dl by Downloads.index.collectAsState()
    val busy by Downloads.busy.collectAsState()
    Column(Modifier.fillMaxSize().padding(horizontal = 24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Box(Modifier.weight(1f).fillMaxWidth().padding(vertical = 8.dp), contentAlignment = Alignment.Center) {
            Cover(t.thumb, 300.dp)
        }
        Text(t.title, fontSize = 22.sp, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center)
        Text(t.artist, color = Muted, fontSize = 16.sp, modifier = Modifier.clickable { Nav.artist(t.artists.firstOrNull() ?: t.artist) })
        if (v.error != null) Text(v.error, color = Accent, fontSize = 12.sp)
        SeekBar()
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { PlayerHub.setShuffle(!v.shuffle) }) { Icon(Icons.Filled.Shuffle, contentDescription = "Keverés", tint = if (v.shuffle) Accent else Color.White) }
            IconButton(onClick = { PlayerHub.prev() }, modifier = Modifier.size(56.dp)) { Icon(Icons.Filled.SkipPrevious, contentDescription = "Előző", modifier = Modifier.size(36.dp)) }
            Box(Modifier.size(72.dp).clip(CircleShape).background(Color.White).clickable { PlayerHub.toggle() }, contentAlignment = Alignment.Center) {
                if (v.loading && v.playing) CircularProgressIndicator(Modifier.size(30.dp), color = Color.Black, strokeWidth = 3.dp)
                else Icon(if (v.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, contentDescription = "Lejátszás/szünet", tint = Color.Black, modifier = Modifier.size(44.dp))
            }
            IconButton(onClick = { PlayerHub.next() }, modifier = Modifier.size(56.dp)) { Icon(Icons.Filled.SkipNext, contentDescription = "Következő", modifier = Modifier.size(36.dp)) }
            IconButton(onClick = { PlayerHub.cycleRepeat() }) {
                Icon(if (v.repeat == 2) Icons.Filled.RepeatOne else Icons.Filled.Repeat, contentDescription = "Ismétlés", tint = if (v.repeat != 0) Accent else Color.White)
            }
        }
        Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), horizontalArrangement = Arrangement.SpaceEvenly) {
            IconButton(onClick = {
                val n = !liked; liked = n
                scope.launch { try { Api.like(t.id, n) } catch (e: Exception) { liked = !n; PlayerHub.toast(e.message ?: "Hiba") } }
            }) { Icon(if (liked) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder, contentDescription = "Kedvelés", tint = if (liked) Accent else Color.White) }
            IconButton(onClick = { Nav.pickPlaylistFor.value = t }) { Icon(Icons.Filled.PlaylistAdd, contentDescription = "Listához") }
            IconButton(onClick = {
                scope.launch {
                    if (dl.containsKey(t.id)) Downloads.remove(t.id)
                    else try { Downloads.download(t); PlayerHub.toast("Letöltve offline hallgatáshoz") } catch (e: Exception) { PlayerHub.toast(e.message ?: "Letöltési hiba") }
                }
            }) {
                if (busy.contains(t.id)) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp, color = Color.White)
                else Icon(if (dl.containsKey(t.id)) Icons.Filled.DownloadDone else Icons.Filled.Download, contentDescription = "Offline")
            }
        }
    }
}

@Composable
fun SeekBar() {
    val pos by PlayerHub.posMs.collectAsState()
    val dur by PlayerHub.durMs.collectAsState()
    var drag by remember { mutableStateOf<Float?>(null) }
    val frac = drag ?: if (dur > 0) (pos.toFloat() / dur).coerceIn(0f, 1f) else 0f
    Column(Modifier.fillMaxWidth()) {
        Slider(
            value = frac, onValueChange = { drag = it },
            onValueChangeFinished = { drag?.let { PlayerHub.seek((it * dur).toLong()) }; drag = null },
            colors = SliderDefaults.colors(thumbColor = Color.White, activeTrackColor = Color.White, inactiveTrackColor = Surface2),
        )
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(fmt(if (drag != null) (drag!! * dur).toLong() else pos), color = Muted, fontSize = 12.sp)
            Text(fmt(dur), color = Muted, fontSize = 12.sp)
        }
    }
}

@Composable
fun QueueTab(v: PState) {
    val state = rememberLazyListState()
    LaunchedEffect(v.index) { if (v.index > 0) state.scrollToItem(maxOf(0, v.index - 1)) }
    LazyColumn(Modifier.fillMaxSize(), state = state, contentPadding = PaddingValues(bottom = 24.dp)) {
        itemsIndexed(v.queue) { i, t ->
            Row(Modifier.fillMaxWidth().clickable { PlayerHub.playIndex(i) }.padding(start = 16.dp, end = 4.dp, top = 4.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Cover(t.thumb, 44.dp)
                Column(Modifier.weight(1f).padding(horizontal = 10.dp)) {
                    Text(t.title, maxLines = 1, overflow = TextOverflow.Ellipsis, color = if (i == v.index) Accent else Color.White, fontWeight = FontWeight.Medium)
                    Text(t.artist, maxLines = 1, overflow = TextOverflow.Ellipsis, color = Muted, fontSize = 13.sp)
                }
                IconButton(onClick = { if (i > 0) PlayerHub.move(i, i - 1) }, enabled = i > 0) { Icon(Icons.Filled.KeyboardArrowUp, contentDescription = "Fel") }
                IconButton(onClick = { if (i < v.queue.size - 1) PlayerHub.move(i, i + 1) }, enabled = i < v.queue.size - 1) { Icon(Icons.Filled.KeyboardArrowDown, contentDescription = "Le") }
                IconButton(onClick = { PlayerHub.removeAt(i) }) { Icon(Icons.Filled.Close, contentDescription = "Eltávolít", tint = Muted) }
            }
        }
    }
}

// ---------------------------------------------------------------- szöveg + kézi szinkron
@Composable
fun LyricsTab(t: Track) {
    val scope = rememberCoroutineScope()
    var retry by remember { mutableIntStateOf(0) }
    var lyr by remember(t.id) { mutableStateOf<Lyrics?>(null) }
    var status by remember(t.id) { mutableStateOf("loading") }
    var sync by remember(t.id) { mutableStateOf(false) }
    var ptr by remember(t.id) { mutableIntStateOf(0) }
    val pos by PlayerHub.posMs.collectAsState()
    val target by PlayerHub.target.collectAsState()

    LaunchedEffect(t.id, retry) {
        status = "loading"
        try {
            val l = if (Downloads.has(t.id)) (Downloads.cachedLyrics(t.id) ?: Api.lyrics(t.id)) else Api.lyrics(t.id)
            lyr = l; status = if (l == null) "none" else "ok"
        } catch (e: Exception) {
            val c = Downloads.cachedLyrics(t.id)
            if (c != null) { lyr = c; status = "ok" } else status = "err"
        }
    }

    val lines = lyr?.lines ?: emptyList()
    var active = -1
    if (!sync && lyr?.synced == true) for (i in lines.indices) { val lt = lines[i].t; if (lt != null && lt <= pos) active = i }
    val shown = if (sync) ptr - 1 else active
    val listState = rememberLazyListState()
    LaunchedEffect(shown) { if (shown >= 0) listState.animateScrollToItem(maxOf(0, shown - 2)) }

    Column(Modifier.fillMaxSize()) {
        when (status) {
            "loading" -> Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Accent) }
            "none" -> Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) { Text("Ehhez a számhoz még nincs szöveg.\nA webes felületen tudod beilleszteni.", color = Muted, textAlign = TextAlign.Center) }
            "err" -> Column(Modifier.weight(1f).fillMaxWidth(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                Text("A szöveg most nem érhető el.", color = Muted); TextButton(onClick = { retry++ }) { Text("Újra") }
            }
            else -> LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = listState, contentPadding = PaddingValues(horizontal = 24.dp, vertical = 16.dp)) {
                itemsIndexed(lines) { i, l ->
                    val c = when {
                        i == shown -> Color.White
                        lyr?.synced != true && !sync -> Color(0xCCFFFFFF)
                        sync && i == ptr -> Color(0xCCFFFFFF)
                        else -> Color(0x66FFFFFF)
                    }
                    Text(
                        l.text, fontSize = 24.sp, fontWeight = FontWeight.Bold, color = c, lineHeight = 32.sp,
                        modifier = Modifier.padding(vertical = 8.dp).clickable(enabled = !sync && l.t != null) { PlayerHub.seek(l.t ?: 0L) },
                    )
                }
            }
        }
        if (status == "ok" && lyr != null) {
            if (!sync) {
                Row(Modifier.fillMaxWidth().padding(8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedButton(onClick = { ptr = 0; sync = true; PlayerHub.seek(0); PlayerHub.cmd("play") }, enabled = target == null) { Text("Szinkronizálás") }
                    Text(if (lyr?.synced == true) "szinkronizált · ${lyr?.source}" else "nincs időzítve", color = Muted, fontSize = 12.sp)
                }
            } else {
                Column(Modifier.fillMaxWidth().background(Surface1).padding(12.dp)) {
                    Button(
                        onClick = {
                            val cur = lyr ?: return@Button
                            if (ptr >= cur.lines.size) return@Button
                            val ts = maxOf(0L, PlayerHub.posMs.value - 120)
                            val idx = ptr
                            lyr = cur.copy(lines = cur.lines.mapIndexed { i, l -> if (i == idx) l.copy(t = ts) else l }, synced = cur.lines.indices.all { i -> i == idx || cur.lines[i].t != null })
                            scope.launch { try { Api.lyricsLine(t.id, idx, ts) } catch (e: Exception) { PlayerHub.toast("Mentési hiba: ${e.message}") } }
                            ptr = idx + 1
                            if (ptr >= cur.lines.size) { sync = false; PlayerHub.toast("Szinkron kész, elmentve") }
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = Accent), modifier = Modifier.fillMaxWidth().height(64.dp),
                    ) {
                        Text(
                            if (ptr == 0) "Az 1. sor MOST kezdődik" else "A következő sor MOST kezdődik (${ptr + 1}/${lines.size})",
                            fontSize = 16.sp, fontWeight = FontWeight.Bold,
                        )
                    }
                    Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = {
                            val n = maxOf(0, ptr - 1)
                            val prevT = lyr?.lines?.getOrNull(n - 1)?.t
                            ptr = n
                            PlayerHub.seek(maxOf(0L, (prevT ?: 0L) - 500))
                        }) { Text("Vissza") }
                        OutlinedButton(onClick = { ptr = 0; PlayerHub.seek(0) }) { Text("Újrakezdés") }
                        OutlinedButton(onClick = { PlayerHub.toggle() }) { Text("Szünet") }
                        OutlinedButton(onClick = { sync = false }) { Text("Kilépés") }
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- szám menü, lista választó, eszközök
@Composable
fun MenuRow(label: String, onClick: () -> Unit) {
    Text(label, modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 12.dp, horizontal = 4.dp), fontSize = 16.sp)
}

@Composable
fun TrackMenu() {
    val t = Nav.menuTrack.value ?: return
    val scope = rememberCoroutineScope()
    val dl by Downloads.index.collectAsState()
    val close = { Nav.menuTrack.value = null }
    AlertDialog(
        onDismissRequest = { close() },
        confirmButton = {},
        title = { Text(t.title, maxLines = 1, overflow = TextOverflow.Ellipsis) },
        text = {
            Column {
                MenuRow("Lejátszás most (+ hasonló számok)") { PlayerHub.playRadio(t); close() }
                MenuRow("Következő lesz") { PlayerHub.enqueue(listOf(t), next = true); PlayerHub.toast("Hozzáadva: következő"); close() }
                MenuRow("Hozzáadás a sorhoz") { PlayerHub.enqueue(listOf(t)); PlayerHub.toast("Hozzáadva a sorhoz"); close() }
                MenuRow(if (t.liked) "Kedvelés törlése" else "Kedvelés") {
                    scope.launch { try { Api.like(t.id, !t.liked); PlayerHub.toast(if (t.liked) "Kedvelés törölve" else "Kedvelve") } catch (e: Exception) { PlayerHub.toast(e.message ?: "Hiba") } }
                    close()
                }
                MenuRow("Hozzáadás lejátszási listához") { Nav.pickPlaylistFor.value = t; close() }
                if (dl.containsKey(t.id)) MenuRow("Törlés a telefonról (offline)") { Downloads.remove(t.id); close() }
                else MenuRow("Letöltés offline hallgatáshoz") {
                    scope.launch { try { Downloads.download(t); PlayerHub.toast("Letöltve: ${t.title}") } catch (e: Exception) { PlayerHub.toast(e.message ?: "Letöltési hiba") } }
                    close()
                }
                MenuRow("Előadó megnyitása") { Nav.artist(t.artists.firstOrNull() ?: t.artist); close() }
                if (!t.albumId.isNullOrEmpty()) MenuRow("Album megnyitása") { Nav.playerOpen.value = false; Nav.push(Route("album", t.albumId, t.album)); close() }
            }
        },
    )
}

@Composable
fun PlaylistPicker() {
    val t = Nav.pickPlaylistFor.value ?: return
    val scope = rememberCoroutineScope()
    var retry by remember { mutableIntStateOf(0) }
    var newName by remember { mutableStateOf("") }
    val ld = rememberLoad("pick", retry) { Api.playlists() }
    AlertDialog(
        onDismissRequest = { Nav.pickPlaylistFor.value = null },
        confirmButton = { TextButton(onClick = { Nav.pickPlaylistFor.value = null }) { Text("Mégse") } },
        title = { Text("Lejátszási lista") },
        text = {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextField(value = newName, onValueChange = { newName = it }, placeholder = { Text("Új lista neve") }, singleLine = true, modifier = Modifier.weight(1f))
                    IconButton(onClick = {
                        if (newName.isNotBlank()) scope.launch {
                            try { Api.createPlaylist(newName.trim(), listOf(t.id)); PlayerHub.toast("Lista létrehozva"); Nav.pickPlaylistFor.value = null } catch (e: Exception) { PlayerHub.toast(e.message ?: "Hiba") }
                        }
                    }) { Icon(Icons.Filled.Check, contentDescription = "Létrehoz") }
                }
                when (ld) {
                    is Ld.Ok -> LazyColumn(Modifier.height(260.dp)) {
                        items(ld.v) { p ->
                            MenuRow("${p.title} (${p.count})") {
                                scope.launch { try { Api.addToPlaylist(p.id, listOf(t.id)); PlayerHub.toast("Hozzáadva: ${p.title}") } catch (e: Exception) { PlayerHub.toast(e.message ?: "Hiba") } }
                                Nav.pickPlaylistFor.value = null
                            }
                        }
                    }
                    is Ld.Err -> Text(ld.msg, color = Muted)
                    else -> CircularProgressIndicator(color = Accent)
                }
            }
        },
    )
}

@Composable
fun DevicesDialog() {
    if (!Nav.devicesOpen.value) return
    val devices by PlayerHub.devices.collectAsState()
    val target by PlayerHub.target.collectAsState()
    val online by PlayerHub.wsOnline.collectAsState()
    AlertDialog(
        onDismissRequest = { Nav.devicesOpen.value = false },
        confirmButton = { TextButton(onClick = { Nav.devicesOpen.value = false }) { Text("Kész") } },
        title = { Text("Eszközök") },
        text = {
            Column {
                if (!online) Text("Nincs kapcsolat a szerverrel – a távirányító nem érhető el.", color = Muted)
                Text(if (target == null) "✔ Ez a telefon (helyi lejátszás)" else "Ez a telefon", fontWeight = FontWeight.Bold, modifier = Modifier.padding(vertical = 6.dp))
                if (target != null) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { PlayerHub.setTarget(null); Nav.devicesOpen.value = false }) { Text("Vissza ide") }
                        OutlinedButton(onClick = { PlayerHub.pullHere(); Nav.devicesOpen.value = false }) { Text("Lejátszás áthozása ide") }
                    }
                }
                if (devices.isEmpty()) Text("Nincs másik csatlakozott eszköz (nyisd meg a webes klienst a gépen).", color = Muted, modifier = Modifier.padding(top = 8.dp))
                devices.forEach { d ->
                    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                        Text((if (target == d.id) "✔ " else "") + d.name + " · " + d.kind, fontWeight = FontWeight.Bold)
                        Text(if (d.title != null) "${if (d.playing) "▶" else "⏸"} ${d.title} – ${d.artist}" else "Nem játszik", color = Muted, fontSize = 13.sp)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 4.dp)) {
                            Button(onClick = { PlayerHub.setTarget(d.id); Nav.devicesOpen.value = false }, colors = ButtonDefaults.buttonColors(containerColor = Accent)) { Text("Távirányító") }
                            OutlinedButton(onClick = { PlayerHub.transferTo(d.id); Nav.devicesOpen.value = false }) { Text("Átvitel oda") }
                        }
                    }
                }
            }
        },
    )
}

package app.homemusic

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.Download
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

@Composable
fun Chip(text: String, selected: Boolean, onClick: () -> Unit) {
    Box(
        Modifier.clip(RoundedCornerShape(50)).background(if (selected) Color.White else Surface2).clickable(onClick = onClick).padding(horizontal = 14.dp, vertical = 8.dp)
    ) { Text(text, color = if (selected) Color.Black else Color.White, fontSize = 14.sp) }
}

@Composable
fun TopBar(title: String, back: Boolean = false, content: @Composable () -> Unit = {}) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        if (back) IconButton(onClick = { Nav.back() }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Vissza") }
        Text(title, fontSize = 22.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f).padding(start = if (back) 0.dp else 8.dp), maxLines = 1, overflow = TextOverflow.Ellipsis)
        content()
    }
}

// ---------------------------------------------------------------- bejelentkezés
@Composable
fun LoginScreen() {
    var server by rememberSaveable { mutableStateOf(Prefs.server.ifEmpty { "http://" }) }
    var pw by rememberSaveable { mutableStateOf("") }
    var err by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize().padding(28.dp), verticalArrangement = Arrangement.Center) {
        Text("HomeMusic", fontSize = 34.sp, fontWeight = FontWeight.Bold)
        Text("Csatlakozás az otthoni szerverhez (VPN-en át)", color = Muted, modifier = Modifier.padding(bottom = 24.dp))
        TextField(
            value = server, onValueChange = { server = it }, label = { Text("Szerver címe, pl. http://192.168.1.10:8080") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth(),
        )
        TextField(
            value = pw, onValueChange = { pw = it }, label = { Text("Jelszó") }, singleLine = true, visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
        )
        if (err != null) Text(err!!, color = Accent, modifier = Modifier.padding(top = 12.dp))
        Button(
            onClick = {
                busy = true; err = null
                scope.launch {
                    try {
                        val tok = Api.login(server, pw)
                        Session.login(server, tok)
                    } catch (e: Exception) { err = e.message ?: "Hiba" }
                    busy = false
                }
            },
            enabled = !busy, colors = ButtonDefaults.buttonColors(containerColor = Accent), modifier = Modifier.fillMaxWidth().padding(top = 20.dp),
        ) { Text(if (busy) "Csatlakozás…" else "Belépés") }
    }
}

// ---------------------------------------------------------------- főoldal
@Composable
fun HomeScreen() {
    var retry by remember { mutableIntStateOf(0) }
    val ld = rememberLoad("home", retry) { Api.home() }
    Column(Modifier.fillMaxSize()) {
        TopBar("HomeMusic") {
            IconButton(onClick = { Nav.devicesOpen.value = true }) { Icon(Icons.Filled.Devices, contentDescription = "Eszközök") }
            IconButton(onClick = { Nav.push(Route("settings")) }) { Icon(Icons.Filled.Settings, contentDescription = "Beállítások") }
        }
        Row(Modifier.padding(horizontal = 16.dp).padding(bottom = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Chip("Véletlen mix", false) { Nav.push(Route("mix", "random", "Véletlen mix")) }
            Chip("Ismerős mix", false) { Nav.push(Route("mix", "familiar", "Ismerős mix")) }
        }
        Loaded(ld, onRetry = { retry++ }) { shelves ->
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                items(shelves) { sh -> if (sh.items.isNotEmpty()) ShelfRow(sh, ::openItem) }
            }
        }
    }
}

// ---------------------------------------------------------------- keresés
@Composable
fun SearchScreen() {
    var q by rememberSaveable { mutableStateOf("") }
    var submitted by rememberSaveable { mutableStateOf("") }
    var filter by rememberSaveable { mutableStateOf("") }
    Column(Modifier.fillMaxSize()) {
        TextField(
            value = q, onValueChange = { q = it }, singleLine = true, placeholder = { Text("Dalok, előadók, albumok") },
            leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search), keyboardActions = KeyboardActions(onSearch = { submitted = q.trim() }),
            colors = TextFieldDefaults.colors(focusedContainerColor = Surface2, unfocusedContainerColor = Surface2),
            modifier = Modifier.fillMaxWidth().padding(12.dp),
        )
        LazyRow(contentPadding = PaddingValues(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val fs = listOf("" to "Összes", "songs" to "Dalok", "albums" to "Albumok", "artists" to "Előadók", "playlists" to "Listák")
            items(fs) { (k, l) -> Chip(l, filter == k) { filter = k } }
        }
        if (submitted.isBlank()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("Írd be, mit keresel", color = Muted) }
        } else {
            var retry by remember { mutableIntStateOf(0) }
            val ld = rememberLoad(submitted + "|" + filter, retry) { Api.search(submitted, filter.ifEmpty { null }) }
            Loaded(ld, onRetry = { retry++ }) { res ->
                val cur = PlayerHub.view.collectAsState().value.track?.id
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                    items(res) { it ->
                        val t = it.track
                        if (t != null) TrackRow(t, current = t.id == cur) { PlayerHub.playRadio(t) }
                        else ItemRow(it)
                    }
                }
            }
        }
    }
}

@Composable
fun ItemRow(it: Item) {
    val label = when (it.type) { "artist" -> "Előadó"; "album" -> "Album"; "playlist" -> "Lista"; else -> "" }
    Row(Modifier.fillMaxWidth().clickable { openItem(it) }.padding(horizontal = 16.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Cover(it.thumb, 48.dp, round = it.type == "artist")
        Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
            Text(it.title, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium)
            Text(listOf(label, it.subtitle).filter { s -> s.isNotBlank() }.joinToString(" · "), maxLines = 1, overflow = TextOverflow.Ellipsis, color = Muted, fontSize = 13.sp)
        }
    }
}

// ---------------------------------------------------------------- könyvtár
@Composable
fun LibraryScreen() {
    var tab by rememberSaveable { mutableStateOf("liked") }
    Column(Modifier.fillMaxSize()) {
        TopBar("Könyvtár")
        LazyRow(contentPadding = PaddingValues(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val ts = listOf("liked" to "Kedvelt", "playlists" to "Listák", "top" to "Legtöbbet játszott", "recent" to "Legutóbbi")
            items(ts) { (k, l) -> Chip(l, tab == k) { tab = k } }
        }
        if (tab == "playlists") {
            var retry by remember { mutableIntStateOf(0) }
            val ld = rememberLoad("pls", retry) { Api.playlists() }
            Loaded(ld, onRetry = { retry++ }) { pls ->
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                    items(pls) { p ->
                        Row(Modifier.fillMaxWidth().clickable { Nav.push(Route("local", p.id.toString(), p.title)) }.padding(horizontal = 16.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Cover(p.thumb, 52.dp)
                            Column(Modifier.padding(start = 12.dp)) { Text(p.title, fontWeight = FontWeight.Medium); Text("${p.count} szám", color = Muted, fontSize = 13.sp) }
                        }
                    }
                }
            }
        } else {
            var retry by remember { mutableIntStateOf(0) }
            val ld = rememberLoad(tab, retry) { Api.library(tab) }
            Loaded(ld, onRetry = { retry++ }) { ts -> TrackList(ts, header = null) }
        }
    }
}

// ---------------------------------------------------------------- offline
@Composable
fun OfflineScreen() {
    val idx by Downloads.index.collectAsState()
    val ts = idx.values.toList()
    Column(Modifier.fillMaxSize()) {
        TopBar("Offline")
        Text("${ts.size} szám · ${"%.0f".format(Downloads.totalBytes() / 1048576.0)} MB a telefonon", color = Muted, modifier = Modifier.padding(horizontal = 16.dp))
        if (ts.isEmpty()) Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("Nincs letöltött szám. A szám menüjében (⋮) tudsz letölteni.", color = Muted, modifier = Modifier.padding(24.dp)) }
        else TrackList(ts, header = null)
    }
}

// ---------------------------------------------------------------- számlista + részletoldalak
@Composable
fun TrackActions(ts: List<Track>) {
    val scope = rememberCoroutineScope()
    Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = { PlayerHub.playTracks(ts, 0) }, enabled = ts.isNotEmpty(), colors = ButtonDefaults.buttonColors(containerColor = Accent)) {
            Icon(Icons.Filled.PlayArrow, contentDescription = null); Text("Lejátszás")
        }
        OutlinedButton(onClick = { PlayerHub.playTracks(ts.shuffled(), 0) }, enabled = ts.isNotEmpty()) { Icon(Icons.Filled.Shuffle, contentDescription = null); Text(" Keverés") }
        OutlinedButton(
            onClick = { scope.launch { PlayerHub.toast("Letöltés indul: ${ts.size} szám"); ts.forEach { t -> try { Downloads.download(t) } catch (e: Exception) { PlayerHub.toast("${t.title}: ${e.message}") } } } },
            enabled = ts.isNotEmpty(),
        ) { Icon(Icons.Filled.Download, contentDescription = null) }
    }
}

@Composable
fun TrackList(ts: List<Track>, header: (@Composable () -> Unit)?) {
    val cur = PlayerHub.view.collectAsState().value.track?.id
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        if (header != null) item { header() }
        item { if (ts.isNotEmpty()) TrackActions(ts) }
        itemsIndexed(ts) { i, t -> TrackRow(t, current = t.id == cur) { PlayerHub.playTracks(ts, i) } }
    }
}

@Composable
fun DetailScreen(r: Route) {
    var retry by remember { mutableIntStateOf(0) }
    val ld = rememberLoad(r, retry) {
        when (r.kind) {
            "album" -> Api.album(r.id)
            "ytm" -> Api.ytmPlaylist(r.id)
            "local" -> Api.localPlaylist(r.id.toInt())
            "artist" -> Api.artist(r.id, r.name)
            else -> Api.Page(r.name, "Keverék", null, Api.mix(r.id), emptyList())
        }
    }
    Column(Modifier.fillMaxSize()) {
        TopBar(r.name, back = true)
        Loaded(ld, onRetry = { retry++ }) { p ->
            val cur = PlayerHub.view.collectAsState().value.track?.id
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                item {
                    Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                        Cover(p.thumb, 110.dp, round = r.kind == "artist")
                        Column(Modifier.padding(start = 16.dp)) {
                            Text(p.title.ifBlank { r.name }, fontSize = 20.sp, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            Text(p.subtitle, color = Muted)
                            if (p.fallback) Text("A YouTube nem adta ki az előadó oldalát, keresési találatok láthatók.", color = Muted, fontSize = 12.sp)
                        }
                    }
                }
                item { if (p.tracks.isNotEmpty()) TrackActions(p.tracks) }
                itemsIndexed(p.tracks) { i, t -> TrackRow(t, current = t.id == cur) { PlayerHub.playTracks(p.tracks, i) } }
                items(p.shelves) { sh -> ShelfRow(sh, ::openItem) }
            }
        }
    }
}

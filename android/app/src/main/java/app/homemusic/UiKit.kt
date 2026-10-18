package app.homemusic

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.CancellationException

sealed class Ld<out T> {
    object Loading : Ld<Nothing>()
    class Ok<T>(val v: T) : Ld<T>()
    class Err(val msg: String) : Ld<Nothing>()
}

@Composable
fun <T> rememberLoad(key: Any?, retry: Int = 0, f: suspend () -> T): Ld<T> {
    val st: State<Ld<T>> = produceState<Ld<T>>(Ld.Loading, key, retry) {
        value = Ld.Loading
        value = try {
            Ld.Ok(f())
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Ld.Err(e.message ?: "Hiba")
        }
    }
    return st.value
}

/** Betöltés / hiba / tartalom egyben. */
@Composable
fun <T> Loaded(ld: Ld<T>, onRetry: (() -> Unit)? = null, content: @Composable (T) -> Unit) {
    when (ld) {
        is Ld.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Accent) }
        is Ld.Err -> Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
            Text(ld.msg, color = Muted, textAlign = TextAlign.Center)
            if (onRetry != null) Button(onClick = onRetry, modifier = Modifier.padding(top = 12.dp)) { Text("Újra") }
        }
        is Ld.Ok -> content(ld.v)
    }
}

@Composable
fun Cover(url: String?, size: Dp, round: Boolean = false, modifier: Modifier = Modifier) {
    val shape = if (round) CircleShape else RoundedCornerShape(6.dp)
    Box(modifier.size(size).clip(shape).background(Surface2)) {
        if (url != null) AsyncImage(model = url, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
    }
}

@Composable
fun SectionTitle(text: String) {
    Text(text, fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 8.dp))
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun TrackRow(t: Track, current: Boolean = false, onClick: () -> Unit) {
    val dl = Downloads.index.collectAsState().value
    Row(
        Modifier.fillMaxWidth().combinedClickable(onClick = onClick, onLongClick = { Nav.menuTrack.value = t }).padding(horizontal = 16.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Cover(t.thumb, 48.dp)
        Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
            Text(t.title, maxLines = 1, overflow = TextOverflow.Ellipsis, color = if (current) Accent else MaterialTheme.colorScheme.onSurface, fontWeight = FontWeight.Medium)
            Text(
                t.artist, maxLines = 1, overflow = TextOverflow.Ellipsis, color = Muted, fontSize = 13.sp,
                modifier = Modifier.clickable { Nav.artist(t.artists.firstOrNull() ?: t.artist) },
            )
        }
        if (dl.containsKey(t.id)) Icon(Icons.Filled.CheckCircle, contentDescription = "Letöltve", tint = Muted, modifier = Modifier.size(16.dp))
        IconButton(onClick = { Nav.menuTrack.value = t }) { Icon(Icons.Filled.MoreVert, contentDescription = "Menü", tint = Muted) }
    }
}

@Composable
fun ItemCard(item: Item, size: Dp = 140.dp, onOpen: (Item) -> Unit) {
    Column(Modifier.width(size).clickable { onOpen(item) }, horizontalAlignment = if (item.type == "artist") Alignment.CenterHorizontally else Alignment.Start) {
        Cover(item.thumb, size, round = item.type == "artist")
        Text(item.title, maxLines = 2, overflow = TextOverflow.Ellipsis, fontSize = 14.sp, fontWeight = FontWeight.Medium, modifier = Modifier.padding(top = 6.dp))
        if (item.subtitle.isNotBlank()) Text(item.subtitle, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 12.sp, color = Muted)
    }
}

@Composable
fun ShelfRow(s: Shelf, onOpen: (Item) -> Unit) {
    SectionTitle(s.title)
    LazyRow(contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        items(s.items) { ItemCard(it, onOpen = onOpen) }
    }
}

/** Kártya/találat megnyitása: szám -> rádió, egyéb -> oldal. */
fun openItem(it: Item) {
    when (it.type) {
        "track" -> it.track?.let { t -> PlayerHub.playRadio(t) }
        "album" -> Nav.push(Route("album", it.id, it.title))
        "artist" -> Nav.push(Route("artist", it.id, it.title))
        "playlist" -> Nav.push(Route("ytm", it.id, it.title))
    }
}
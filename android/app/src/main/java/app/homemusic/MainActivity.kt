package app.homemusic

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LibraryMusic
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.OfflinePin
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext

class MainActivity : ComponentActivity() {
    private val askNotif = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            askNotif.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent { HomeMusicTheme { Root() } }
    }
}

@Composable
fun Root() {
    val ctx = LocalContext.current
    LaunchedEffect(Unit) { PlayerHub.toasts.collect { Toast.makeText(ctx, it, Toast.LENGTH_SHORT).show() } }
    LaunchedEffect(Session.loggedIn.value) {
        if (Session.loggedIn.value) try { PlayerHub.settings.value = Api.settings() } catch (e: Exception) { /* offline */ }
    }
    if (!Session.loggedIn.value) {
        Box(Modifier.fillMaxSize()) { LoginScreen() }
        return
    }
    BackHandler(enabled = Nav.playerOpen.value || Nav.stack.isNotEmpty()) { Nav.back() }

    Box(Modifier.fillMaxSize()) {
        Scaffold(
            containerColor = Bg,
            bottomBar = { Column { MiniPlayer(); BottomNav() } },
        ) { pad ->
            Box(Modifier.padding(pad).fillMaxSize()) {
                val top = Nav.stack.lastOrNull()
                if (top != null) {
                    key(Nav.stack.size, top) {
                        if (top.kind == "settings") SettingsScreen() else DetailScreen(top)
                    }
                } else when (Nav.tab.value) {
                    "search" -> SearchScreen()
                    "library" -> LibraryScreen()
                    "offline" -> OfflineScreen()
                    else -> HomeScreen()
                }
            }
        }
        if (Nav.playerOpen.value) FullPlayer()
        TrackMenu()
        PlaylistPicker()
        DevicesDialog()
    }
}

@Composable
fun BottomNav() {
    NavigationBar(containerColor = Bg) {
        val items: List<Triple<String, String, ImageVector>> = listOf(
            Triple("home", "Főoldal", Icons.Filled.Home),
            Triple("search", "Keresés", Icons.Filled.Search),
            Triple("library", "Könyvtár", Icons.Filled.LibraryMusic),
            Triple("offline", "Offline", Icons.Filled.OfflinePin),
        )
        for ((id, label, icon) in items) {
            NavigationBarItem(
                selected = Nav.tab.value == id && Nav.stack.isEmpty(),
                onClick = { Nav.tab.value = id; Nav.stack.clear() },
                icon = { Icon(icon, contentDescription = label) },
                label = { Text(label) },
                colors = NavigationBarItemDefaults.colors(indicatorColor = Surface2),
            )
        }
    }
}

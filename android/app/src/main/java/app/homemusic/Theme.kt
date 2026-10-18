package app.homemusic

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Bg = Color(0xFF000000)
val Surface1 = Color(0xFF121212)
val Surface2 = Color(0xFF212121)
val Accent = Color(0xFFFF0000)
val Muted = Color(0xFFAAAAAA)

private val scheme = darkColorScheme(
    primary = Accent, onPrimary = Color.White,
    background = Bg, onBackground = Color.White,
    surface = Surface1, onSurface = Color.White,
    surfaceVariant = Surface2, onSurfaceVariant = Muted,
    secondaryContainer = Surface2, onSecondaryContainer = Color.White,
)

@Composable
fun HomeMusicTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = scheme, content = content)
}

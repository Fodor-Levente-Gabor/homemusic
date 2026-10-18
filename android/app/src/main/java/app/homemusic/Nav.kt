package app.homemusic

import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf

object Session {
    val loggedIn = mutableStateOf(false)

    fun logout() {
        Prefs.token = ""
        PlayerHub.disconnect()
        loggedIn.value = false
    }

    fun login(server: String, token: String) {
        Prefs.server = server
        Prefs.token = token
        loggedIn.value = true
        PlayerHub.connect()
    }
}

/** kind: album, artist, ytm (YT Music lista), local (saját lista), mix, settings */
data class Route(val kind: String, val id: String = "", val name: String = "")

object Nav {
    val tab = mutableStateOf("home")                 // home, search, library, offline
    val stack = mutableStateListOf<Route>()
    val playerOpen = mutableStateOf(false)
    val menuTrack = mutableStateOf<Track?>(null)
    val pickPlaylistFor = mutableStateOf<Track?>(null)
    val devicesOpen = mutableStateOf(false)

    fun push(r: Route) { stack.add(r) }
    fun back(): Boolean {
        if (playerOpen.value) { playerOpen.value = false; return true }
        if (stack.isNotEmpty()) { stack.removeAt(stack.size - 1); return true }
        return false
    }
    fun artist(name: String, id: String = "_") { playerOpen.value = false; push(Route("artist", id, name)) }
}

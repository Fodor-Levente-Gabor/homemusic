package app.homemusic

import android.app.Application
import kotlinx.coroutines.launch

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        Prefs.init(this)
        Downloads.init(this)
        Session.loggedIn.value = Prefs.token.isNotEmpty() && Prefs.server.isNotEmpty()
        PlayerHub.init(this)
        Api.onUnauthorized = { PlayerHub.scope.launch { Session.logout() } }
        if (Session.loggedIn.value) PlayerHub.connect()
    }
}

package app.homemusic

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

@Composable
fun SettingSlider(label: String, value: Float, range: ClosedFloatingPointRange<Float>, show: (Float) -> String, onDone: (Float) -> Unit) {
    var v by remember(value) { mutableFloatStateOf(value) }
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text(label); Text(show(v), color = Muted) }
        Slider(
            value = v, onValueChange = { v = it }, valueRange = range, onValueChangeFinished = { onDone(v) },
            colors = SliderDefaults.colors(thumbColor = Accent, activeTrackColor = Accent, inactiveTrackColor = Surface2),
        )
    }
}

@Composable
fun SwitchRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label)
        Switch(checked = checked, onCheckedChange = onChange, colors = SwitchDefaults.colors(checkedTrackColor = Accent))
    }
}

@Composable
fun SettingsScreen() {
    val s by PlayerHub.settings.collectAsState()
    val online by PlayerHub.wsOnline.collectAsState()
    val scope = rememberCoroutineScope()
    var name by remember { mutableStateOf(Prefs.deviceName) }
    val status = rememberLoad("status") { Api.status() }
    val dlCount by Downloads.index.collectAsState()

    fun save(ch: JSONObject) {
        scope.launch { try { PlayerHub.settings.value = Api.saveSettings(ch) } catch (e: Exception) { PlayerHub.toast(e.message ?: "Mentési hiba") } }
    }

    Column(Modifier.fillMaxSize()) {
        TopBar("Beállítások", back = true)
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 32.dp)) {
            SectionTitle("Kapcsolat")
            Text("Szerver: ${Prefs.server}", color = Muted, modifier = Modifier.padding(horizontal = 16.dp))
            Text(if (online) "Távirányító: kapcsolódva" else "Távirányító: nincs kapcsolat", color = Muted, modifier = Modifier.padding(horizontal = 16.dp))
            (status as? Ld.Ok<JSONObject>)?.v?.let { st ->
                val c = st.optJSONObject("cache")
                if (c != null) Text(
                    "Szerver gyorsítótár: ${"%.1f".format(c.optLong("used_bytes") / 1073741824.0)} / ${"%.0f".format(c.optLong("limit_bytes") / 1073741824.0)} GB · ${c.optInt("files")} fájl",
                    color = Muted, modifier = Modifier.padding(horizontal = 16.dp),
                )
                Text(if (st.optBoolean("ytm_connected")) "YouTube-fiók: összekötve" else "YouTube-fiók: nincs összekötve (a webes felületen add meg a sütiket)", color = Muted, modifier = Modifier.padding(horizontal = 16.dp))
            }
            Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextField(value = name, onValueChange = { name = it }, label = { Text("Eszköz neve") }, singleLine = true, modifier = Modifier.weight(1f))
                OutlinedButton(onClick = { if (name.isNotBlank()) PlayerHub.rename(name.trim()) }) { Text("Mentés") }
            }

            SectionTitle("Hang")
            SwitchRow("Hangerő-normalizálás", s.normalize) { save(JSONObject().put("normalize", it)) }
            SettingSlider("Célhangerő", s.targetLufs.toFloat(), -23f..-9f, { "%.0f LUFS".format(it) }) { save(JSONObject().put("target_lufs", it.toDouble())) }
            SettingSlider("Átúsztatás (crossfade)", s.crossfadeMs / 1000f, 0f..12f, { if (it < 0.1f) "ki" else "%.1f s".format(it) }) { save(JSONObject().put("crossfade_ms", (it * 1000).toInt())) }
            Text("A számok között hézagmentes az átmenet; az átúsztatás be/kifadeli a végét és az elejét.", color = Muted, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 16.dp))

            SectionTitle("Hangszínszabályzó")
            SwitchRow("EQ bekapcsolása", s.eqEnabled) { save(JSONObject().put("eq_enabled", it)) }
            SettingSlider("Előerősítés", s.preampDb.toFloat(), -12f..12f, { "%+.0f dB".format(it) }) { save(JSONObject().put("preamp_db", it.toDouble())) }
            val labels = listOf("31 Hz", "62 Hz", "125 Hz", "250 Hz", "500 Hz", "1 kHz", "2 kHz", "4 kHz", "8 kHz", "16 kHz")
            for (i in 0 until 10) {
                SettingSlider(labels[i], s.eqGains.getOrElse(i) { 0.0 }.toFloat(), -12f..12f, { "%+.0f dB".format(it) }) {
                    val g = s.eqGains.toMutableList()
                    while (g.size < 10) g.add(0.0)
                    g[i] = it.toDouble()
                    save(JSONObject().put("eq_gains", JSONArray(g)))
                }
            }

            SectionTitle("Tárhely")
            SettingSlider("Szerver gyorsítótár limit", s.cacheLimitGb.toFloat().coerceIn(5f, 250f), 5f..250f, { "%.0f GB".format(it) }) { save(JSONObject().put("cache_limit_gb", it.toDouble())) }
            Text("Offline letöltések a telefonon: ${dlCount.size} szám · ${"%.0f".format(Downloads.totalBytes() / 1048576.0)} MB", color = Muted, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))

            Button(
                onClick = { Session.logout() }, colors = ButtonDefaults.buttonColors(containerColor = Surface2, contentColor = Color.White),
                modifier = Modifier.padding(16.dp).fillMaxWidth(),
            ) { Text("Kijelentkezés", fontWeight = FontWeight.Bold) }
        }
    }
}

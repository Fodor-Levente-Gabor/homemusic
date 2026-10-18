package app.homemusic

import android.media.audiofx.Equalizer
import android.media.audiofx.LoudnessEnhancer
import android.os.Handler
import android.os.Looper
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import kotlin.math.abs
import kotlin.math.ln
import kotlin.math.pow

/** Hangerő-normalizálás (szerver által mért gain), EQ és "átúsztatás" (kifaded/befaded a számváltásnál). A szolgáltatás főszálán fut. */
object Fx {
    private var player: ExoPlayer? = null
    private var eq: Equalizer? = null
    private var loud: LoudnessEnhancer? = null
    private var sessionId = 0
    private var gainDb = 0.0
    private var fade = 1.0
    var settings = Settings()
    private val handler = Handler(Looper.getMainLooper())
    private val bandFreqs = doubleArrayOf(31.0, 62.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0)

    private val ticker = object : Runnable {
        override fun run() {
            val p = player ?: return
            updateFade(p)
            handler.postDelayed(this, 100)
        }
    }

    fun attach(p: ExoPlayer) {
        player = p
        p.addListener(object : Player.Listener {
            override fun onAudioSessionIdChanged(audioSessionId: Int) { rebuild(audioSessionId) }
            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                gainDb = mediaItem?.mediaMetadata?.extras?.getDouble("gain", 0.0) ?: 0.0
                apply()
            }
        })
        gainDb = p.currentMediaItem?.mediaMetadata?.extras?.getDouble("gain", 0.0) ?: 0.0
        if (p.audioSessionId != C.AUDIO_SESSION_ID_UNSET) rebuild(p.audioSessionId)
        handler.post(ticker)
    }

    fun release() {
        handler.removeCallbacks(ticker)
        try { eq?.release() } catch (e: Exception) { /* */ }
        try { loud?.release() } catch (e: Exception) { /* */ }
        eq = null; loud = null; player = null
    }

    fun update(s: Settings) { settings = s; apply() }

    private fun rebuild(id: Int) {
        if (id == 0 || id == C.AUDIO_SESSION_ID_UNSET) return
        sessionId = id
        try { eq?.release() } catch (e: Exception) { /* */ }
        try { loud?.release() } catch (e: Exception) { /* */ }
        eq = try { Equalizer(0, id) } catch (e: Exception) { null }
        loud = try { LoudnessEnhancer(id) } catch (e: Exception) { null }
        apply()
    }

    private fun apply() {
        val p = player ?: return
        val g = (if (settings.normalize) gainDb else 0.0) + settings.preampDb
        val vol = if (g < 0) 10.0.pow(g / 20.0) else 1.0
        baseVolume = vol.coerceIn(0.0, 1.0)
        p.volume = (baseVolume * fade).toFloat()
        try {
            val l = loud
            if (l != null) {
                if (g > 0.05) { l.setTargetGain((g * 100).toInt().coerceAtMost(1500)); l.enabled = true } else l.enabled = false
            }
        } catch (e: Exception) { /* */ }
        try {
            val e = eq
            if (e != null) {
                e.enabled = settings.eqEnabled
                if (settings.eqEnabled) {
                    val range = e.bandLevelRange
                    for (b in 0 until e.numberOfBands) {
                        val centerHz = e.getCenterFreq(b.toShort()) / 1000.0
                        val nearest = bandFreqs.indices.minByOrNull { abs(ln(bandFreqs[it]) - ln(centerHz.coerceAtLeast(1.0))) } ?: 0
                        val mb = (settings.eqGains.getOrElse(nearest) { 0.0 } * 100).toInt().coerceIn(range[0].toInt(), range[1].toInt())
                        e.setBandLevel(b.toShort(), mb.toShort())
                    }
                }
            }
        } catch (e: Exception) { /* nem minden eszköz támogatja */ }
    }

    private var baseVolume = 1.0

    private fun updateFade(p: ExoPlayer) {
        val cf = settings.crossfadeMs
        var f = 1.0
        if (cf > 0 && p.isPlaying) {
            val dur = p.duration
            val pos = p.currentPosition
            if (dur != C.TIME_UNSET && dur > cf * 2L) {
                if (pos < cf) f = minOf(f, 0.15 + 0.85 * pos.toDouble() / cf)
                val remaining = dur - pos
                if (p.hasNextMediaItem() && remaining < cf) f = minOf(f, (remaining.toDouble() / cf).coerceIn(0.0, 1.0))
            }
        }
        if (abs(f - fade) > 0.01) {
            fade = f
            p.volume = (baseVolume * fade).toFloat()
        }
    }
}

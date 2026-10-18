"""Hangosság mérés ffmpeg ebur128 szűrővel. A kliensek a visszaadott gain_db-t alkalmazzák."""
import re
import subprocess

_I = re.compile(r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", re.M)
_PEAK = re.compile(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", re.M)


def measure(path: str, timeout: int = 180) -> tuple[float, float] | None:
    """(integrált LUFS, true peak dBTP) vagy None, ha nem sikerült."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    summary = r.stderr.rsplit("Summary:", 1)
    if len(summary) < 2:
        return None
    mi = _I.search(summary[1])
    mp = _PEAK.search(summary[1])
    if not mi:
        return None
    return float(mi.group(1)), float(mp.group(1)) if mp else 0.0


def gain_for(lufs: float, true_peak: float, target: float = -14.0) -> float:
    """Szükséges erősítés dB-ben: a célhangosságig, de nem vág (peak <= -1 dBTP), és korlátos."""
    gain = target - lufs
    gain = min(gain, -1.0 - true_peak)     # ne legyen clipping
    return round(max(-15.0, min(gain, 9.0)), 2)

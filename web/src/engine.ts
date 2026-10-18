import { api } from "./api";
import type { PlayerState, Position, Repeat, Settings, Track } from "./types";

const EQ_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];

interface Deck {
  el: HTMLAudioElement;
  src: MediaElementAudioSourceNode;
  norm: GainNode;
  fade: GainNode;
  id: string | null;
}

const SILENT = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";

/** A böngészős lejátszó: két "deck" (crossfade/gapless), WebAudio lánc (normalizálás, EQ), várólista. */
export class PlayerEngine {
  private ctx: AudioContext | null = null;
  private decks: Deck[] = [];
  private cur = 0;
  private master!: GainNode;
  private preamp!: GainNode;
  private filters: BiquadFilterNode[] = [];
  private settings: Settings | null = null;
  private fading = false;
  private preloadedFor: string | null = null;
  private loadToken = 0;
  private eventId: number | null = null;
  private listened = 0;
  private lastProgressSent = 0;
  private lastTick = 0;
  private timer: number | undefined;
  deviceId = "";

  state: PlayerState = { queue: [], index: -1, playing: false, loading: false, error: null, volume: 1, shuffle: false, repeat: "off" };
  pos: Position = { position_ms: 0, duration_ms: 0 };
  onState: (s: PlayerState) => void = () => {};
  onPos: (p: Position) => void = () => {};
  onStructural: () => void = () => {};   // a várólista/aktuális szám változott (távirányító jelentéshez)

  constructor() {
    try { this.state.volume = parseFloat(localStorage.getItem("hm_volume") || "1"); } catch { /* */ }
  }

  // ---------- inicializálás ----------
  private ensureCtx(): AudioContext {
    if (this.ctx) return this.ctx;
    const ctx = new AudioContext({ latencyHint: "playback" });
    this.ctx = ctx;
    this.preamp = ctx.createGain();
    this.master = ctx.createGain();
    this.master.gain.value = this.state.volume;
    this.filters = EQ_FREQS.map((f, i) => {
      const b = ctx.createBiquadFilter();
      b.type = i === 0 ? "lowshelf" : i === EQ_FREQS.length - 1 ? "highshelf" : "peaking";
      b.frequency.value = f;
      b.Q.value = 1.0;
      return b;
    });
    this.preamp.connect(this.filters[0]);
    this.filters.forEach((f, i) => i < this.filters.length - 1 && f.connect(this.filters[i + 1]));
    this.filters[this.filters.length - 1].connect(this.master);
    this.master.connect(ctx.destination);
    for (let i = 0; i < 2; i++) {
      const el = new Audio();
      el.preload = "auto";
      el.crossOrigin = "anonymous";
      const src = ctx.createMediaElementSource(el);
      const norm = ctx.createGain();
      const fade = ctx.createGain();
      src.connect(norm); norm.connect(fade); fade.connect(this.preamp);
      el.addEventListener("ended", () => this.onEnded(i));
      el.addEventListener("error", () => { if (i === this.cur && el.src) this.fail("A lejátszás nem sikerült"); });
      el.addEventListener("pause", () => { if (!this.unlocking && i === this.cur && !this.fading && !el.ended) this.setPlaying(false); });
      el.addEventListener("play", () => { if (!this.unlocking && i === this.cur) this.setPlaying(true); });
      this.decks.push({ el, src, norm, fade, id: null });
    }
    this.timer = window.setInterval(() => this.tick(), 100);
    this.applySettings();
    this.setupMediaSession();
    return ctx;
  }

  /** Felhasználói kattintásra hívandó: feloldja a böngésző automatikus lejátszás tiltását. */
  private unlocking = false;
  async unlock(): Promise<void> {
    const ctx = this.ensureCtx();
    if (ctx.state === "suspended") await ctx.resume();
    this.unlocking = true;
    try {
      for (const d of this.decks) {
        if (!d.el.src) {
          d.el.src = SILENT;
          try { await d.el.play(); } catch { /* */ }
          d.el.pause();
          d.el.removeAttribute("src");
          d.el.load();
        }
      }
    } finally {
      await new Promise((r) => setTimeout(r, 50));   // a késve érkező play/pause eseményeket is elnyeljük
      this.unlocking = false;
      this.state.playing = false;
      this.emit();
    }
  }
  get unlocked(): boolean { return !!this.ctx && this.ctx.state === "running"; }

  setSettings(s: Settings) { this.settings = s; if (this.ctx) this.applySettings(); }
  private applySettings() {
    const s = this.settings; if (!s || !this.ctx) return;
    const t = this.ctx.currentTime;
    this.preamp.gain.setTargetAtTime(s.eq_enabled ? Math.pow(10, s.preamp_db / 20) : 1, t, 0.02);
    this.filters.forEach((f, i) => f.gain.setTargetAtTime(s.eq_enabled ? (s.eq_gains[i] ?? 0) : 0, t, 0.02));
    for (const d of this.decks) if (d.id) d.norm.gain.setTargetAtTime(this.normGain(d.id), t, 0.02);
  }
  private gains = new Map<string, number>();
  private normGain(id: string): number {
    if (!this.settings?.normalize) return 1;
    return Math.pow(10, (this.gains.get(id) ?? 0) / 20);
  }

  // ---------- állapot ----------
  private emit() { this.onState({ ...this.state }); }
  private setPlaying(p: boolean) {
    if (this.state.playing === p) return;
    this.state.playing = p;
    this.emit();
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = p ? "playing" : "paused";
    this.onStructural();
  }
  private fail(msg: string) {
    this.state.error = msg; this.state.loading = false; this.state.playing = false;
    this.emit(); this.onStructural();
  }
  get track(): Track | null { return this.state.queue[this.state.index] ?? null; }
  private get deck() { return this.decks[this.cur]; }
  private get other() { return this.decks[1 - this.cur]; }

  // ---------- parancsok ----------
  async playQueue(tracks: Track[], index = 0, startMs = 0, autoplay = true) {
    this.ensureCtx();
    this.state.queue = tracks.slice();
    this.state.index = index;
    if (this.state.shuffle && autoplay) this.shuffleUpcoming();
    this.onStructural();
    await this.load(index, startMs, autoplay);
  }
  async playIndex(index: number) {
    if (index < 0 || index >= this.state.queue.length) return;
    this.state.index = index;
    this.onStructural();
    await this.load(index, 0, true);
  }
  enqueue(tracks: Track[], next = false) {
    const q = this.state.queue;
    if (next) q.splice(this.state.index + 1, 0, ...tracks); else q.push(...tracks);
    this.preloadedFor = null;
    this.emit(); this.onStructural();
    if (q.length === tracks.length) void this.load(0, 0, true);
  }
  /** Átrendezés: a várólista from. elemét a to. helyre teszi (a jelenlegi szám követi a mozgatást). */
  moveItem(from: number, to: number) {
    const q = this.state.queue;
    if (from === to || from < 0 || to < 0 || from >= q.length || to >= q.length) return;
    let idx = this.state.index;
    const [x] = q.splice(from, 1);
    q.splice(to, 0, x);
    if (from === idx) idx = to;
    else if (from < idx && to >= idx) idx--;
    else if (from > idx && to <= idx) idx++;
    this.state.index = idx;
    this.preloadedFor = null;
    this.emit(); this.onStructural();
  }
  /** Beszúrás egy adott helyre (húzással a keresési találatból a várólistába). */
  insertAt(tracks: Track[], at: number) {
    const q = this.state.queue;
    at = Math.max(0, Math.min(q.length, at));
    q.splice(at, 0, ...tracks);
    if (at <= this.state.index && q.length > tracks.length) this.state.index += tracks.length;
    this.preloadedFor = null;
    this.emit(); this.onStructural();
    if (q.length === tracks.length) void this.load(0, 0, true);
  }
  removeAt(i: number) {
    const q = this.state.queue;
    if (i < 0 || i >= q.length) return;
    if (i === this.state.index) return;
    q.splice(i, 1);
    if (i < this.state.index) this.state.index--;
    this.preloadedFor = null;
    this.emit(); this.onStructural();
  }
  async play() {
    this.ensureCtx();
    if (this.ctx!.state === "suspended") await this.ctx!.resume().catch(() => {});
    if (!this.deck.id && this.track) { await this.load(this.state.index, 0, true); return; }
    try { await this.deck.el.play(); } catch (e) { this.fail("A böngésző blokkolta a lejátszást – kattints a lapra"); }
  }
  pause() { this.deck?.el.pause(); }
  toggle() { return this.state.playing ? this.pause() : this.play(); }
  seek(ms: number) {
    if (!this.deck?.id) return;
    this.deck.el.currentTime = Math.max(0, ms / 1000);
    this.tick(true);
    this.onStructural();
  }
  setVolume(v: number) {
    v = Math.max(0, Math.min(1, v));
    this.state.volume = v;
    try { localStorage.setItem("hm_volume", String(v)); } catch { /* */ }
    if (this.ctx) this.master.gain.setTargetAtTime(v, this.ctx.currentTime, 0.015);
    this.emit(); this.onStructural();
  }
  setShuffle(on: boolean) {
    this.state.shuffle = on;
    if (on) this.shuffleUpcoming();
    this.preloadedFor = null;
    this.emit(); this.onStructural();
  }
  setRepeat(r: Repeat) { this.state.repeat = r; this.preloadedFor = null; this.emit(); this.onStructural(); }
  private shuffleUpcoming() {
    const q = this.state.queue, i = this.state.index;
    const head = q.slice(0, i + 1), tail = q.slice(i + 1);
    for (let k = tail.length - 1; k > 0; k--) {
      const j = Math.floor(Math.random() * (k + 1));
      [tail[k], tail[j]] = [tail[j], tail[k]];
    }
    this.state.queue = [...head, ...tail];
  }
  async next(auto = false) {
    const { queue, index, repeat } = this.state;
    if (!queue.length) return;
    if (auto && repeat === "one") { this.seek(0); void this.deck.el.play(); return; }
    let n = index + 1;
    if (n >= queue.length) {
      if (repeat === "all") n = 0;
      else { this.pause(); this.seek(0); return; }
    }
    await this.playIndex(n);
  }
  async prev() {
    if (this.deck.el.currentTime > 3 || this.state.index <= 0) { this.seek(0); return; }
    await this.playIndex(this.state.index - 1);
  }

  // ---------- betöltés ----------
  private async load(index: number, startMs: number, autoplay: boolean) {
    const track = this.state.queue[index];
    if (!track) return;
    const myToken = ++this.loadToken;
    this.fading = false;
    this.finishPlayEvent();
    this.state.loading = true; this.state.error = null; this.state.playing = autoplay ? this.state.playing : false;
    this.emit();
    this.updateMediaSession();
    let info: Track;
    try { info = await api.ensure(track.video_id); }
    catch (e: any) { if (myToken === this.loadToken) this.fail(e?.message || "Letöltési hiba"); return; }
    if (myToken !== this.loadToken) return;
    Object.assign(track, { gain_db: info.gain_db, duration_sec: info.duration_sec ?? track.duration_sec, cached: true });
    this.gains.set(track.video_id, info.gain_db ?? 0);
    // az előző deck leállítása, az új indítása a (másik) decken
    const d = this.deck, o = this.other;
    const t = this.ctx!.currentTime;
    let use = d;
    if (o.id === track.video_id && o.el.src) { this.cur = 1 - this.cur; use = o; }  // előtöltött
    else { use = d; }
    for (const x of this.decks) if (x !== use) { x.el.pause(); x.fade.gain.cancelScheduledValues(t); x.fade.gain.value = 0; }
    use.fade.gain.cancelScheduledValues(t); use.fade.gain.value = 1;
    use.norm.gain.value = this.normGain(track.video_id);
    if (use.id !== track.video_id || !use.el.src) { use.el.src = api.audioUrl(track.video_id); use.id = track.video_id; }
    use.el.currentTime = startMs / 1000;
    this.preloadedFor = null;
    this.state.loading = false;
    this.emit();
    if (autoplay) {
      try { await use.el.play(); } catch { this.fail("A böngésző blokkolta a lejátszást – kattints a lapra"); return; }
    }
    this.beginPlayEvent(track.video_id);
    this.updateMediaSession();
    this.prefetchUpcoming();
    this.tick(true);
  }

  private upcomingTrack(): Track | null {
    const { queue, index, repeat } = this.state;
    if (repeat === "one") return null;
    if (index + 1 < queue.length) return queue[index + 1];
    return repeat === "all" && queue.length > 1 ? queue[0] : null;
  }
  private prefetchUpcoming() {
    const n = this.settings?.prefetch_count ?? 3;
    const ids = this.state.queue.slice(this.state.index + 1, this.state.index + 1 + n).filter((t) => !t.cached).map((t) => t.video_id);
    if (ids.length) api.prefetch(ids).catch(() => {});
  }
  /** A következő számot a másik deckre töltjük, hogy a váltás (gapless/crossfade) azonnali legyen. */
  private async preloadNext() {
    const nt = this.upcomingTrack();
    if (!nt || this.preloadedFor === nt.video_id) return;
    this.preloadedFor = nt.video_id;
    try {
      const info = await api.ensure(nt.video_id);
      if (this.preloadedFor !== nt.video_id) return;
      this.gains.set(nt.video_id, info.gain_db ?? 0);
      const o = this.other;
      o.el.src = api.audioUrl(nt.video_id);
      o.id = nt.video_id;
      o.norm.gain.value = this.normGain(nt.video_id);
      o.el.load();
    } catch { this.preloadedFor = null; }
  }

  // ---------- átúsztatás / gapless ----------
  private tick(force = false) {
    if (!this.ctx || !this.decks.length) return;
    const d = this.deck, el = d.el;
    const dur = isFinite(el.duration) ? el.duration : (this.track?.duration_sec ?? 0);
    const now = performance.now();
    if (this.state.playing && this.lastTick) this.listened += (now - this.lastTick) / 1000;
    this.lastTick = now;
    this.pos = { position_ms: Math.round(el.currentTime * 1000), duration_ms: Math.round(dur * 1000) };
    this.onPos(this.pos);
    if (this.state.playing && now - this.lastProgressSent > 10000) this.sendProgress();
    if (!this.state.playing || this.fading || !dur) return;
    const remaining = dur - el.currentTime;
    const cf = (this.settings?.crossfade_ms ?? 0) / 1000;
    if (remaining < 20 && !this.preloadedFor) void this.preloadNext();
    const nt = this.upcomingTrack();
    if (!nt || this.other.id !== nt.video_id || this.other.el.readyState < 3) return;
    if (cf > 0 && remaining <= cf + 0.05 && remaining > 0.2) this.startCrossfade(cf);
    else if (cf === 0 && (this.settings?.gapless ?? true) && remaining <= 0.12) this.startCrossfade(0.02);
    void force;
  }
  private startCrossfade(seconds: number) {
    const nt = this.upcomingTrack(); if (!nt || !this.ctx) return;
    this.fading = true;
    this.finishPlayEvent();
    const from = this.deck, to = this.other, t = this.ctx.currentTime;
    to.fade.gain.cancelScheduledValues(t); from.fade.gain.cancelScheduledValues(t);
    // egyenlő teljesítményű átúsztatás
    const n = 32, up = new Float32Array(n), down = new Float32Array(n);
    for (let i = 0; i < n; i++) { const x = i / (n - 1); up[i] = Math.sin(x * Math.PI / 2); down[i] = Math.cos(x * Math.PI / 2); }
    to.fade.gain.setValueCurveAtTime(up, t, seconds);
    from.fade.gain.setValueCurveAtTime(down, t, seconds);
    to.el.currentTime = 0;
    void to.el.play();
    const nextIndex = this.state.index + 1 >= this.state.queue.length ? 0 : this.state.index + 1;
    this.cur = 1 - this.cur;
    this.state.index = nextIndex;
    this.preloadedFor = null;
    this.emit(); this.onStructural();
    this.beginPlayEvent(nt.video_id);
    this.updateMediaSession();
    this.prefetchUpcoming();
    window.setTimeout(() => {
      from.el.pause();
      from.fade.gain.cancelScheduledValues(0); from.fade.gain.value = 0;
      to.fade.gain.cancelScheduledValues(0); to.fade.gain.value = 1;
      this.fading = false;
    }, seconds * 1000 + 100);
  }
  private onEnded(i: number) {
    if (i !== this.cur || this.fading) return;
    void this.next(true);
  }

  // ---------- statisztika a szerver felé ----------
  private beginPlayEvent(videoId: string) {
    this.eventId = null; this.listened = 0; this.lastProgressSent = performance.now(); this.lastTick = performance.now();
    api.playStart(videoId, this.deviceId).then((r) => { this.eventId = r.event_id; }).catch(() => {});
  }
  private sendProgress() {
    this.lastProgressSent = performance.now();
    if (this.eventId != null) api.playProgress(this.eventId, this.listened).catch(() => {});
  }
  private finishPlayEvent() { if (this.eventId != null) this.sendProgress(); this.eventId = null; }

  // ---------- operációs rendszer média vezérlés ----------
  private setupMediaSession() {
    if (!("mediaSession" in navigator)) return;
    const ms = navigator.mediaSession;
    ms.setActionHandler("play", () => void this.play());
    ms.setActionHandler("pause", () => this.pause());
    ms.setActionHandler("previoustrack", () => void this.prev());
    ms.setActionHandler("nexttrack", () => void this.next());
    ms.setActionHandler("seekto", (d) => { if (d.seekTime != null) this.seek(d.seekTime * 1000); });
  }
  private updateMediaSession() {
    const t = this.track;
    if (!t || !("mediaSession" in navigator)) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: t.title, artist: t.artist, album: t.album || "",
      artwork: t.thumbnail ? [{ src: t.thumbnail, sizes: "544x544", type: "image/jpeg" }] : [],
    });
  }
  destroy() { if (this.timer) clearInterval(this.timer); }
}

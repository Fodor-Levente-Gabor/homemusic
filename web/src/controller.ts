import { useSyncExternalStore } from "react";
import { api, getToken } from "./api";
import { PlayerEngine } from "./engine";
import type { DeviceInfo, PlayerState, Position, Repeat, Settings, Track } from "./types";

type Cmd = "moveQueue" | "insertAt" | "play" | "pause" | "toggle" | "next" | "prev" | "seek" | "volume" | "shuffle" | "repeat"
  | "playQueue" | "playIndex" | "enqueue" | "removeAt";

/** crypto.randomUUID() only exists on HTTPS/localhost; over plain http://LAN-IP it is undefined. */
function uuid(): string {
  const c: any = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID();
  const b = new Uint8Array(16);
  if (c?.getRandomValues) c.getRandomValues(b); else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export interface View {
  state: PlayerState;
  track: Track | null;
  isRemote: boolean;
  targetName: string;
}

const emptyState: PlayerState = { queue: [], index: -1, playing: false, loading: false, error: null, volume: 1, shuffle: false, repeat: "off" };

function slim(t: Track): Track {
  return { video_id: t.video_id, title: t.title, artist: t.artist, album: t.album, thumbnail: t.thumbnail, duration_sec: t.duration_sec, gain_db: t.gain_db, liked: t.liked, cached: t.cached };
}

/** Összefogja a helyi lejátszót és a távirányítót: a UI mindig a "view"-t látja, ami vagy a helyi, vagy a vezérelt eszköz. */
class Controller {
  engine = new PlayerEngine();
  deviceId: string;
  deviceName: string;
  settings: Settings | null = null;
  devices: DeviceInfo[] = [];
  target: string | null = null;
  wsOnline = false;
  view: View;
  pos: Position = { position_ms: 0, duration_ms: 0 };
  private remoteRecv = 0;           // mikor jött az utolsó távoli pozíció (helyi óra szerint)
  private remotePos: Position = { position_ms: 0, duration_ms: 0 };
  private remoteState: Partial<PlayerState> = {};
  private listeners = new Set<() => void>();
  private posListeners = new Set<() => void>();
  private ws: WebSocket | null = null;
  private retry = 0;
  private reportTimer: number | undefined;
  private tickTimer: number | undefined;
  private lastTickSent = 0;
  toastMsg: string | null = null;

  constructor() {
    let id = localStorage.getItem("hm_device_id");
    if (!id) { id = uuid(); localStorage.setItem("hm_device_id", id); }
    this.deviceId = id;
    this.engine.deviceId = id;
    this.deviceName = localStorage.getItem("hm_device_name") || guessName();
    this.view = this.computeView();

    this.engine.onState = () => { if (!this.target) this.refreshView(); };
    this.engine.onPos = (p) => { if (!this.target) { this.pos = p; this.posListeners.forEach((l) => l()); } };
    this.engine.onStructural = () => this.scheduleReport();
  }

  // ---------- feliratkozás ----------
  subscribe = (l: () => void) => { this.listeners.add(l); return () => this.listeners.delete(l); };
  subscribePos = (l: () => void) => { this.posListeners.add(l); return () => this.posListeners.delete(l); };
  getView = () => this.view;
  getPos = () => this.pos;
  ver = 0;
  private notify() { this.ver++; this.listeners.forEach((l) => l()); }
  private refreshView() { this.view = this.computeView(); this.notify(); }
  private computeView(): View {
    if (!this.target) {
      const s = { ...this.engine.state };
      return { state: s, track: this.engine.track, isRemote: false, targetName: this.deviceName };
    }
    const dev = this.devices.find((d) => d.id === this.target);
    const s: PlayerState = { ...emptyState, ...this.remoteState } as PlayerState;
    return { state: s, track: s.queue[s.index] ?? null, isRemote: true, targetName: dev?.name || "Távoli eszköz" };
  }
  toast(m: string) { this.toastMsg = m; this.notify(); window.setTimeout(() => { if (this.toastMsg === m) { this.toastMsg = null; this.notify(); } }, 3000); }

  // ---------- indulás ----------
  async start() {
    this.settings = await api.settings();
    this.engine.setSettings(this.settings);
    this.connect();
    this.tickTimer = window.setInterval(() => this.remoteTick(), 250);
    this.notify();
  }
  stop() {
    this.ws?.close(); this.ws = null;
    clearInterval(this.tickTimer);
  }
  async saveSettings(v: Partial<Settings>) {
    this.settings = await api.saveSettings(v);
    this.engine.setSettings(this.settings);
    this.notify();
  }
  setDeviceName(n: string) {
    this.deviceName = n; localStorage.setItem("hm_device_name", n);
    this.send({ type: "rename", name: n }); this.refreshView();
  }

  // ---------- WebSocket ----------
  private connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws?token=${encodeURIComponent(getToken())}&device_id=${this.deviceId}&name=${encodeURIComponent(this.deviceName)}&kind=web`;
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.onopen = () => { this.wsOnline = true; this.retry = 0; this.report(true); this.notify(); };
    ws.onclose = () => {
      this.wsOnline = false; this.notify();
      if (this.ws === ws) { this.retry++; window.setTimeout(() => this.ws === ws && this.connect(), Math.min(15000, 500 * 2 ** this.retry)); }
    };
    ws.onmessage = (e) => this.onMessage(JSON.parse(e.data));
  }
  private send(m: unknown) { if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(m)); }

  private onMessage(m: any) {
    switch (m.type) {
      case "devices": {
        this.devices = (m.devices as DeviceInfo[]).filter((d) => d.id !== this.deviceId);
        if (this.target && !this.devices.some((d) => d.id === this.target)) { this.target = null; this.toast("A vezérelt eszköz lecsatlakozott"); }
        if (this.target) this.adoptRemote(this.devices.find((d) => d.id === this.target)!.state, true);
        this.refreshView();
        break;
      }
      case "state": {
        const d = this.devices.find((x) => x.id === m.device_id);
        if (d) d.state = { ...d.state, ...m.state };
        if (m.device_id === this.target) this.adoptRemote(m.state, false);
        this.notify();
        break;
      }
      case "command": void this.exec(m.cmd, m.args || {}); break;
      case "settings": this.settings = m.settings; this.engine.setSettings(m.settings); this.notify(); break;
      case "error": this.toast(m.error || "Hiba"); break;
    }
  }
  private adoptRemote(s: any, full: boolean) {
    if (full) this.remoteState = {};
    const { position_ms, duration_ms, ...rest } = s;
    Object.assign(this.remoteState, rest);
    if (position_ms !== undefined) { this.remotePos.position_ms = position_ms; this.remoteRecv = performance.now(); }
    if (duration_ms !== undefined) this.remotePos.duration_ms = duration_ms;
    if (this.target) this.view = this.computeView();
  }
  private remoteTick() {
    if (!this.target) {
      if (this.engine.state.playing && performance.now() - this.lastTickSent > 3000) this.report(false);
      return;
    }
    const playing = !!this.remoteState.playing;
    const extra = playing ? performance.now() - this.remoteRecv : 0;
    const dur = this.remotePos.duration_ms;
    this.pos = { position_ms: Math.min(dur || Infinity, this.remotePos.position_ms + extra), duration_ms: dur };
    this.posListeners.forEach((l) => l());
  }

  // ---------- jelentés a szervernek ----------
  private scheduleReport() {
    window.clearTimeout(this.reportTimer);
    this.reportTimer = window.setTimeout(() => this.report(true), 120);
  }
  private report(full: boolean) {
    this.lastTickSent = performance.now();
    const e = this.engine, s = e.state;
    const base = { playing: s.playing, position_ms: e.pos.position_ms, duration_ms: e.pos.duration_ms };
    this.send({ type: "state", state: full ? { ...base, queue: s.queue.map(slim), index: s.index, volume: s.volume, shuffle: s.shuffle, repeat: s.repeat, loading: s.loading, error: s.error } : base });
  }

  // ---------- parancsok ----------
  /** UI hívja: a vezérelt eszközre (vagy helyben) hajtja végre. */
  act(cmd: Cmd, args: any = {}) {
    if (this.target) this.send({ type: "command", target: this.target, cmd, args });
    else void this.exec(cmd, args);
  }
  /** A lejátszó eszközön fut le (helyi UI-ból vagy távoli parancsból). */
  async exec(cmd: string, a: any) {
    const e = this.engine;
    switch (cmd) {
      case "play": await e.play(); break;
      case "pause": e.pause(); break;
      case "toggle": await e.toggle(); break;
      case "next": await e.next(); break;
      case "prev": await e.prev(); break;
      case "seek": e.seek(a.position_ms); break;
      case "volume": e.setVolume(a.volume); break;
      case "shuffle": e.setShuffle(!!a.on); break;
      case "repeat": e.setRepeat(a.mode as Repeat); break;
      case "playQueue": await e.playQueue(a.tracks, a.index ?? 0, a.start_ms ?? 0, a.autoplay !== false); break;
      case "playIndex": await e.playIndex(a.index); break;
      case "enqueue": e.enqueue(a.tracks, !!a.next); break;
      case "removeAt": e.removeAt(a.index); break;
      case "moveQueue": e.moveItem(a.from, a.to); break;
      case "insertAt": e.insertAt(a.tracks, a.at); break;
    }
  }
  playTracks(tracks: Track[], index = 0) { this.act("playQueue", { tracks: tracks.map(slim), index }); }
  /** Mint a YouTube Music: egy számra kattintva az adott szám + hasonló számok (rádió) szólnak, nem a találati lista sorrendje. */
  async playRadio(t: Track) {
    this.playTracks([t], 0);
    try {
      const r = await api.radio(t.video_id);
      const rest = r.filter((x) => x.video_id !== t.video_id);
      for (let i = rest.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [rest[i], rest[j]] = [rest[j], rest[i]]; }
      if (rest.length) this.enqueue(rest);
    } catch { /* ha a rádió nem elérhető, a szám akkor is szól */ }
  }
  insertAt(tracks: Track[], at: number) { this.act("insertAt", { tracks: tracks.map(slim), at }); }
  enqueue(tracks: Track[], next = false) { this.act("enqueue", { tracks: tracks.map(slim), next }); }

  // ---------- eszközök közti irányítás ----------
  setTarget(id: string | null) {
    this.target = id;
    if (id) { const d = this.devices.find((x) => x.id === id); if (d) this.adoptRemote(d.state, true); }
    this.refreshView(); this.remoteTick();
  }
  /** A helyi lejátszás átvitele a másik eszközre (a helyi megáll, a másik onnan folytatja). */
  transferTo(id: string) {
    const e = this.engine, s = e.state;
    if (!s.queue.length) { this.setTarget(id); return; }
    this.send({ type: "command", target: id, cmd: "playQueue", args: { tracks: s.queue.map(slim), index: s.index, start_ms: e.pos.position_ms, autoplay: true } });
    e.pause();
    this.setTarget(id);
  }
  /** A vezérelt távoli eszköz lejátszásának áthozása ide. */
  pullHere() {
    if (!this.target) return;
    const s = this.remoteState, id = this.target;
    const tracks = (s.queue || []) as Track[];
    if (tracks.length) void this.engine.playQueue(tracks, s.index ?? 0, this.pos.position_ms, true);
    this.send({ type: "command", target: id, cmd: "pause", args: {} });
    this.setTarget(null);
  }
}

function guessName(): string {
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "Böngésző";
  const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /Mac/.test(ua) ? "Mac" : /Linux/.test(ua) ? "Linux" : "";
  return `${browser}${os ? " – " + os : ""}`;
}

export const ctl = new Controller();
export const useView = () => useSyncExternalStore(ctl.subscribe, ctl.getView);
export const usePos = () => useSyncExternalStore(ctl.subscribePos, ctl.getPos);
export const useCtl = () => {
  useSyncExternalStore(ctl.subscribe, () => ctl.ver);
  return ctl;
};

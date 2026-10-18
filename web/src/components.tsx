import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ctl, useCtl, usePos, useView } from "./controller";
import { Ic } from "./icons";
import { fmt, go, ui } from "./ui";
import type { Item, LocalPlaylist, Track } from "./types";

export const bg = (u?: string | null) => (u ? { backgroundImage: `url("${u}")` } : undefined);

/** Jobb gombos menü (ugyanaz, mint a három pötty): a kurzor helyén nyílik meg. */
export function openTrackMenu(e: React.MouseEvent, t: Track) {
  e.preventDefault(); e.stopPropagation();
  ui.set({ menu: { track: t, x: Math.max(4, Math.min(e.clientX, innerWidth - 270)), y: Math.max(4, Math.min(e.clientY, innerHeight - 330)) } });
}
const dragTrack = (e: React.DragEvent, t: Track) => { e.dataTransfer.setData("application/x-hm-track", JSON.stringify(t)); e.dataTransfer.effectAllowed = "copyMove"; };

// ---------- kártyák ----------
export function ItemCard({ it, onPlay }: { it: Item; onPlay?: () => void }) {
  const open = () => {
    if (it.type === "track") { void ctl.playRadio(it); return; }
    go(`/${it.type === "playlist" ? "ytm" : it.type}/${encodeURIComponent(it.type === "artist" ? `${it.id}|${it.title}` : it.id)}`);
  };
  const title = it.title, sub = it.type === "track" ? it.artist : it.subtitle;
  return (
    <div className={`card ${it.type === "artist" ? "round" : ""}`} onClick={open} onContextMenu={it.type === "track" ? (e) => openTrackMenu(e, it) : undefined} draggable={it.type === "track"} onDragStart={it.type === "track" ? (e) => dragTrack(e, it) : undefined}>
      <div className="cv" style={bg(it.thumbnail)}>
        <button className="play" onClick={(e) => { e.stopPropagation(); (onPlay || open)(); }}><Ic n="play" /></button>
      </div>
      <div className="t ellip" title={title}>{title}</div>
      <div className="s ellip">{sub}</div>
    </div>
  );
}

export function Shelf({ title, items, action }: { title: string; items: Item[]; action?: React.ReactNode }) {
  if (!items.length) return null;
  return (
    <section>
      <h2 style={{ display: "flex", alignItems: "center", gap: 12 }}>{title}{action}</h2>
      <div className="shelf">{items.map((it, i) => <ItemCard key={i} it={it} />)}</div>
    </section>
  );
}

// ---------- számlista ----------
export function TrackList({ tracks, onPlay, extra, radio }: { tracks: Track[]; radio?: boolean; onPlay?: (i: number) => void; extra?: (t: Track, i: number) => React.ReactNode }) {
  const v = useView();
  const cur = v.track?.video_id;
  if (!tracks.length) return <div className="empty">Nincs találat</div>;
  return (
    <div className="rows">
      {tracks.map((t, i) => (
        <TrackRow key={t.video_id + i} t={t} playing={cur === t.video_id} isPlayingNow={cur === t.video_id && v.state.playing}
          onPlay={() => (onPlay ? onPlay(i) : radio ? void ctl.playRadio(t) : ctl.playTracks(tracks, i))} extra={extra?.(t, i)} />
      ))}
    </div>
  );
}

export function ArtistLink({ t }: { t: { artist: string; artists?: string[] } }) {
  const names = t.artists && t.artists.length ? t.artists : t.artist ? [t.artist] : [];
  return <>{names.map((n, i) => (
    <span key={i}>{i > 0 && ", "}<a className="alink" href={`#/artist/${encodeURIComponent(`_|${n}`)}`} onClick={(e) => e.stopPropagation()}>{n}</a></span>
  ))}</>;
}

function TrackRow({ t, playing, isPlayingNow, onPlay, extra }: { t: Track; playing: boolean; isPlayingNow: boolean; onPlay: () => void; extra?: React.ReactNode }) {
  const [liked, setLiked] = useState(!!t.liked);
  useEffect(() => setLiked(!!t.liked), [t.liked]);
  const toggleLike = () => { const n = !liked; setLiked(n); t.liked = n; api.like(t.video_id, n).catch(() => setLiked(!n)); };
  return (
    <div className={`row ${playing ? "cur" : ""}`} onDoubleClick={onPlay} onContextMenu={(e) => openTrackMenu(e, t)} draggable onDragStart={(e) => dragTrack(e, t)}>
      <div className="cv" style={bg(t.thumbnail)} onClick={() => (playing ? ctl.act("toggle") : onPlay())}>
        <div className="ov"><Ic n={isPlayingNow ? "pause" : "play"} /></div>
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="tt ellip">{t.title || t.video_id}</div>
        <div className="muted ellip"><ArtistLink t={t} /></div>
      </div>
      <div className="al ellip">{t.album}</div>
      <div className="du">
        {t.cached && <span className="badge" title="A szerveren letöltve">●</span>}
        <button className={`icon ${liked ? "on" : ""}`} onClick={toggleLike}><Ic n={liked ? "heart" : "heart0"} s={18} /></button>
        <span className="t">{t.duration_sec ? fmt(t.duration_sec * 1000) : ""}</span>
      </div>
      <div style={{ display: "flex" }}>
        {extra}
        <button className="icon" onClick={(e) => { const r = (e.currentTarget as HTMLElement).getBoundingClientRect(); ui.set({ menu: { track: t, x: Math.min(r.left, innerWidth - 260), y: Math.min(r.bottom, innerHeight - 320) } }); }}><Ic n="more" s={20} /></button>
      </div>
    </div>
  );
}

// ---------- kontextmenü és listaválasztó ----------
export function TrackMenu() {
  const { menu, picker } = ui.use();
  return (
    <>
      {menu && <MenuPop {...menu} />}
      {picker && <ListPicker tracks={picker} />}
    </>
  );
}
function MenuPop({ track: t, x, y }: { track: Track; x: number; y: number }) {
  const close = () => ui.set({ menu: null });
  const item = (icon: string, label: string, fn: () => void) => (
    <button onClick={() => { close(); fn(); }}><Ic n={icon} s={20} />{label}</button>
  );
  return (
    <>
      <div className="backdrop" onClick={close} onContextMenu={(e) => { e.preventDefault(); close(); }} />
      <div className="pop" style={{ left: x, top: y }}>
        {item("play", "Lejátszás most", () => void ctl.playRadio(t))}
        {item("play", "Lejátszás következőként", () => ctl.enqueue([t], true))}
        {item("queue", "Hozzáadás a várólistához", () => ctl.enqueue([t], false))}
        {item("radio", "Rádió indítása", async () => { try { const r = await api.radio(t.video_id); ctl.playTracks([t, ...r.filter((x) => x.video_id !== t.video_id)], 0); } catch (e: any) { ctl.toast(e.message); } })}
        {item("add", "Hozzáadás listához…", () => ui.set({ picker: [t] }))}
        {t.cached && item("trash", "Letöltött fájl törlése a szerverről", async () => { await api.cacheDelete(t.video_id); t.cached = false; ctl.toast("Fájl törölve, szükség esetén újra letöltődik"); })}
      </div>
    </>
  );
}
function ListPicker({ tracks }: { tracks: Track[] }) {
  const [lists, setLists] = useState<LocalPlaylist[]>([]);
  const [name, setName] = useState("");
  useEffect(() => { api.playlists().then((l) => setLists(l.filter((x) => x.kind === "user"))); }, []);
  const close = () => ui.set({ picker: null });
  const ids = tracks.map((t) => t.video_id);
  return (
    <>
      <div className="backdrop" onClick={close} />
      <div className="pop" style={{ left: "50%", top: "20%", transform: "translateX(-50%)", width: 340 }}>
        <h5>Hozzáadás listához</h5>
        {lists.map((l) => (
          <button key={l.id} onClick={async () => { await api.playlistAdd(l.id, ids); ctl.toast(`Hozzáadva: ${l.title}`); close(); }}>{l.title}</button>
        ))}
        <div style={{ display: "flex", gap: 8, padding: "8px 12px" }}>
          <input style={{ flex: 1 }} placeholder="Új lista neve" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn" disabled={!name.trim()} onClick={async () => { await api.playlistCreate(name.trim(), ids); ctl.toast("Lista létrehozva"); close(); }}>Új</button>
        </div>
      </div>
    </>
  );
}

// ---------- alsó lejátszósáv ----------
export function PlayerBar() {
  const v = useView();
  const c = useCtl();
  const { state: s, track: t } = v;
  const pos = usePos();
  const barRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const pct = drag ?? (pos.duration_ms ? (pos.position_ms / pos.duration_ms) * 100 : 0);
  const seekFromEvent = (e: React.PointerEvent) => {
    const r = barRef.current!.getBoundingClientRect();
    return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  };
  const [liked, setLiked] = useState(false);
  useEffect(() => setLiked(!!t?.liked), [t?.video_id, t?.liked]);

  return (
    <div className="bar">
      <div className={`prog ${drag !== null ? "drag" : ""}`} ref={barRef}
        onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); setDrag(seekFromEvent(e) * 100); }}
        onPointerMove={(e) => { if (drag !== null) setDrag(seekFromEvent(e) * 100); }}
        onPointerUp={(e) => { const f = seekFromEvent(e); setDrag(null); c.act("seek", { position_ms: f * pos.duration_ms }); }}>
        <div className="track"><div className="fill" style={{ width: `${pct}%` }} /></div>
      </div>

      <div className="now" onClick={() => ui.set({ nowPlaying: !ui.get().nowPlaying })}>
        <div className="cv" style={bg(t?.thumbnail)} />
        <div style={{ minWidth: 0 }}>
          <div className="ellip" style={{ fontWeight: 500 }}>{s.loading ? "Letöltés / betöltés…" : t?.title || "Nincs lejátszás"}</div>
          <div className="muted ellip">{s.error ? <span className="err">{s.error}</span> : t?.artist}</div>
          {v.isRemote && <div className="remote-tag">▶ {v.targetName}</div>}
        </div>
      </div>

      <div className="ctrl">
        <button className={`icon hide-sm ${s.shuffle ? "on" : ""}`} onClick={() => c.act("shuffle", { on: !s.shuffle })} title="Keverés"><Ic n="shuffle" /></button>
        <button className="icon" onClick={() => c.act("prev")}><Ic n="prev" /></button>
        <button className="icon big" onClick={() => c.act("toggle")}>{s.loading ? <span className="spin" /> : <Ic n={s.playing ? "pause" : "play"} s={28} />}</button>
        <button className="icon" onClick={() => c.act("next")}><Ic n="next" /></button>
        <button className={`icon hide-sm ${s.repeat !== "off" ? "on" : ""}`} title="Ismétlés"
          onClick={() => c.act("repeat", { mode: s.repeat === "off" ? "all" : s.repeat === "all" ? "one" : "off" })}><Ic n={s.repeat === "one" ? "repeat1" : "repeat"} /></button>
        <span className="muted hide-sm" style={{ marginLeft: 10, fontSize: 12, minWidth: 90 }}>{fmt(pos.position_ms)} / {fmt(pos.duration_ms)}</span>
      </div>

      <div className="right">
        {t && <button className={`icon ${liked ? "on" : ""}`} onClick={() => { const n = !liked; setLiked(n); t.liked = n; api.like(t.video_id, n).catch(() => setLiked(!n)); }}><Ic n={liked ? "heart" : "heart0"} /></button>}
        <input className="vol" type="range" min={0} max={1} step={0.01} value={s.volume} onChange={(e) => c.act("volume", { volume: +e.target.value })} />
        <button className="icon" title="Szöveg" onClick={() => ui.set({ nowPlaying: true, npTab: "lyrics" })}><Ic n="lyrics" /></button>
        <button className="icon" title="Várólista" onClick={() => ui.set({ nowPlaying: true, npTab: "queue" })}><Ic n="queue" /></button>
        <button className={`icon ${v.isRemote ? "on" : ""}`} title="Eszközök / távirányító" onClick={() => ui.set({ devices: !ui.get().devices })}><Ic n="devices" /></button>
      </div>
    </div>
  );
}

// ---------- eszközök / remote control ----------
export function DevicesPopup() {
  const { devices } = ui.use();
  const c = useCtl();
  if (!devices) return null;
  const close = () => ui.set({ devices: false });
  const now = (d: any) => { const s = d.state || {}; const t = s.queue?.[s.index]; return t ? `${s.playing ? "▶" : "⏸"} ${t.title} – ${t.artist}` : "Nincs lejátszás"; };
  return (
    <>
      <div className="backdrop" onClick={close} />
      <div className="pop devpop">
        <h5>Lejátszás és vezérlés</h5>
        <button onClick={() => { c.setTarget(null); close(); }}>
          <span className={`dot`} /><div style={{ flex: 1 }}><div>{c.deviceName} <span className="muted">(ez az eszköz)</span></div><div className="muted ellip" style={{ fontSize: 12 }}>{!c.target ? "Itt vezérelsz" : "Visszalépés az ehhez az eszközhöz"}</div></div>{!c.target && "✓"}
        </button>
        {c.devices.length === 0 && <div className="it muted">Nincs másik csatlakozott eszköz. Nyisd meg az appot a telefonodon is.</div>}
        {c.devices.map((d) => (
          <div key={d.id} className="it" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span className="dot" /><div style={{ flex: 1, minWidth: 0 }}><div>{d.name}</div><div className="muted ellip" style={{ fontSize: 12 }}>{now(d)}</div></div>
              {c.target === d.id && <span className="remote-tag">irányítod</span>}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn ghost" style={{ padding: "5px 12px", width: "auto" }} onClick={() => { c.setTarget(d.id); close(); }}>Távirányító</button>
              <button className="btn ghost" style={{ padding: "5px 12px", width: "auto" }} onClick={() => { c.transferTo(d.id); close(); }}>Lejátszás átvitele oda</button>
              {c.target === d.id && <button className="btn ghost" style={{ padding: "5px 12px", width: "auto" }} onClick={() => { c.pullHere(); close(); }}>Áthozás ide</button>}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

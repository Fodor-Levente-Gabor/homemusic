import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ctl, useCtl } from "./controller";
import { bg, ItemCard, Shelf, TrackList } from "./components";
import { Ic } from "./icons";
import { go, ui } from "./ui";
import type { Item, LocalPlaylist, Settings, Track } from "./types";

function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true); setErr(null);
    fn().then((d) => { setData(d); setLoading(false); }).catch((e) => { setErr(e.message); setLoading(false); });
  }, deps); // eslint-disable-line
  useEffect(() => { setData(null); reload(); }, [reload]);
  return { data, err, loading, reload, set: setData };
}
const Status = ({ loading, err }: { loading: boolean; err: string | null }) =>
  err ? <div className="empty err">{err}</div> : loading ? <div className="empty"><span className="spin" /></div> : null;

function PlayAllBar({ tracks, title }: { tracks: Track[]; title?: string }) {
  return (
    <div className="hero-acts" style={{ display: "flex", gap: 10, margin: "12px 0" }}>
      <button className="btn" disabled={!tracks.length} onClick={() => ctl.playTracks(tracks, 0)}><Ic n="play" s={20} />Lejátszás</button>
      <button className="btn ghost" disabled={!tracks.length} onClick={() => { const t = tracks.slice(); for (let i = t.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [t[i], t[j]] = [t[j], t[i]]; } ctl.playTracks(t, 0); ctl.act("shuffle", { on: true }); }}><Ic n="shuffle" s={20} />Keverés</button>
      <button className="btn ghost" disabled={!tracks.length} onClick={() => ctl.enqueue(tracks)}><Ic n="queue" s={20} />Sorba</button>
      <button className="btn ghost" disabled={!tracks.length} onClick={() => ui.set({ picker: tracks })}><Ic n="add" s={20} />Listához</button>
      {title && <span />}
    </div>
  );
}

// ---------- főoldal ----------
export function Home() {
  const c = useCtl();
  const { data, err, loading } = useLoad(() => api.home(), []);
  const mix = async (kind: "random" | "familiar") => {
    try {
      const t = await (kind === "random" ? api.mixRandom() : api.mixFamiliar());
      if (!t.length) { c.toast(kind === "familiar" ? "Még nincs elég hallgatási előzmény – hallgass pár számot, vagy kedvelj meg néhányat" : "Nem sikerült mixet építeni"); return; }
      ctl.playTracks(t, 0); ctl.act("shuffle", { on: false });
    } catch (e: any) { c.toast(e.message); }
  };
  return (
    <>
      <h1>Főoldal</h1>
      <div className="chips">
        <button className="chip" onClick={() => mix("random")}><Ic n="shuffle" s={16} /> Véletlen mix (felfedezés)</button>
        <button className="chip" onClick={() => mix("familiar")}><Ic n="radio" s={16} /> Ismerős mix</button>
        <button className="chip" onClick={() => go("/liked")}>Kedvelt számok</button>
        <button className="chip" onClick={() => go("/recent")}>Legutóbb hallgatott</button>
        <button className="chip" onClick={() => go("/top")}>Legtöbbet hallgatott</button>
      </div>
      <Status loading={loading} err={err} />
      {data?.map((s, i) => <Shelf key={i} title={s.title} items={s.items} />)}
    </>
  );
}

// ---------- felfedezés ----------
export function Explore() {
  const moods = useLoad(() => api.mood(), []);
  const charts = useLoad(() => api.charts(), []);
  const [sel, setSel] = useState<string | null>(null);
  const pls = useLoad(() => (sel ? api.moodPlaylists(sel) : Promise.resolve([] as Item[])), [sel]);
  const sections = Array.from(new Set(moods.data?.map((m) => m.section)));
  return (
    <>
      <h1>Felfedezés</h1>
      <Status loading={moods.loading} err={moods.err} />
      {sections.map((sec) => (
        <div key={sec}>
          <h2>{sec}</h2>
          <div className="chips">{moods.data!.filter((m) => m.section === sec).map((m) => (
            <button key={m.params} className={`chip ${sel === m.params ? "on" : ""}`} onClick={() => setSel(sel === m.params ? null : m.params)}>{m.title}</button>
          ))}</div>
        </div>
      ))}
      {sel && <><Status loading={pls.loading} err={pls.err} /><div className="grid" style={{ marginTop: 12 }}>{pls.data?.map((it, i) => <ItemCard key={i} it={it} />)}</div></>}
      {charts.data && Object.entries(charts.data).map(([k, items]) => <Shelf key={k} title={{ songs: "Slágerlista – dalok", videos: "Slágerlista – videók", artists: "Slágerlista – előadók", trending: "Felkapott" }[k] || k} items={items} />)}
    </>
  );
}

// ---------- keresés ----------
export function Search({ q }: { q: string }) {
  const [filter, setFilter] = useState<string | undefined>(undefined);
  const { data, err, loading } = useLoad(() => api.search(q, filter), [q, filter]);
  const tracks = (data?.filter((i) => i.type === "track") ?? []) as Track[];
  const group = (t: string, title: string) => { const it = data?.filter((i) => i.type === t) ?? []; return it.length ? <Shelf title={title} items={it} /> : null; };
  const filters: [string | undefined, string][] = [[undefined, "Összes"], ["songs", "Dalok"], ["albums", "Albumok"], ["artists", "Előadók"], ["playlists", "Listák"], ["videos", "Videók"]];
  return (
    <>
      <h1>„{q}”</h1>
      <div className="chips">{filters.map(([f, l]) => <button key={l} className={`chip ${filter === f ? "on" : ""}`} onClick={() => setFilter(f)}>{l}</button>)}</div>
      <Status loading={loading} err={err} />
      {tracks.length > 0 && <><h2>Dalok</h2><TrackList tracks={tracks} radio /></>}
      {group("artist", "Előadók")}{group("album", "Albumok")}{group("playlist", "Listák")}
      {!loading && !err && data?.length === 0 && <div className="empty">Nincs találat</div>}
    </>
  );
}

// ---------- részletes oldalak ----------
function Hero({ title, sub, thumb, children }: { title: string; sub?: string; thumb?: string | null; children?: React.ReactNode }) {
  return <div className="hero"><div className="cv" style={bg(thumb)} /><div><div className="muted">{sub}</div><h1>{title}</h1>{children}</div></div>;
}
export function YtmPlaylist({ id }: { id: string }) {
  const { data, err, loading } = useLoad(() => api.ytmPlaylist(id), [id]);
  return <><Status loading={loading} err={err} />{data && <><Hero title={data.title} sub="Lejátszási lista" thumb={data.thumbnail || data.tracks[0]?.thumbnail}><PlayAllBar tracks={data.tracks} /></Hero><TrackList tracks={data.tracks} /></>}</>;
}
export function Album({ id }: { id: string }) {
  const { data, err, loading } = useLoad(() => api.album(id), [id]);
  return <><Status loading={loading} err={err} />{data && <><Hero title={data.title} sub={`Album · ${data.artists.join(", ")} ${data.year ?? ""}`} thumb={data.thumbnail}><PlayAllBar tracks={data.tracks} /></Hero><TrackList tracks={data.tracks} /></>}</>;
}
export function Artist({ id: raw }: { id: string }) {
  const [id, name] = [raw.split("|")[0], raw.includes("|") ? raw.slice(raw.indexOf("|") + 1) : undefined];
  const { data, err, loading } = useLoad(() => api.artist(id, name), [id, name]);
  const songs = (data?.sections.songs ?? []).filter((i) => i.type === "track") as Track[];
  const names: Record<string, string> = { albums: "Albumok", singles: "Kislemezek", videos: "Videók", related: "Hasonló előadók" };
  return (
    <>
      <Status loading={loading} err={err} />
      {data && <>
        {(data as any).fallback && <p className="muted">A YouTube nem adta ki az előadó oldalát, ezért keresési találatokat mutatok.</p>}
        <Hero title={data.name} sub="Előadó" thumb={data.thumbnail}>
          <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
            <button className="btn" disabled={!songs.length} onClick={() => ctl.playTracks(songs, 0)}><Ic n="play" s={20} />Lejátszás</button>
            {songs[0] && <button className="btn ghost" onClick={async () => { const r = await api.radio(songs[0].video_id); ctl.playTracks([songs[0], ...r], 0); }}><Ic n="radio" s={20} />Rádió</button>}
          </div>
        </Hero>
        {songs.length > 0 && <><h2>Népszerű dalok</h2><TrackList tracks={songs} /></>}
        {Object.entries(names).map(([k, t]) => <Shelf key={k} title={t} items={(data.sections[k] ?? []) as Item[]} />)}
        {data.description && <p className="muted" style={{ maxWidth: 800 }}>{data.description}</p>}
      </>}
    </>
  );
}

// ---------- könyvtár ----------
export function Library() {
  const { data, err, loading, reload } = useLoad(() => api.playlists(), []);
  const [name, setName] = useState("");
  const c = useCtl();
  return (
    <>
      <h1>Könyvtár</h1>
      <div className="chips">
        <button className="chip" onClick={() => go("/liked")}>♥ Kedvelt számok</button>
        <button className="chip" onClick={() => go("/recent")}>Legutóbb hallgatott</button>
        <button className="chip" onClick={() => go("/top")}>Legtöbbet hallgatott</button>
      </div>
      <h2>Lejátszási listák</h2>
      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <input placeholder="Új lista neve" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && name.trim() && api.playlistCreate(name.trim()).then(() => { setName(""); reload(); })} />
        <button className="btn" disabled={!name.trim()} onClick={() => api.playlistCreate(name.trim()).then(() => { setName(""); reload(); c.toast("Lista létrehozva, a YT Musicba is feltöltődik"); })}>Létrehozás</button>
      </div>
      <Status loading={loading} err={err} />
      <div className="grid">{data?.map((p: LocalPlaylist) => (
        <div key={p.id} className="card" onClick={() => go(`/playlist/${p.id}`)}>
          <div className="cv" style={bg(p.thumbnail)} />
          <div className="t ellip">{p.title}</div><div className="s">{p.count} szám{p.kind === "saved" ? " · mentett" : ""}</div>
        </div>
      ))}</div>
      {data?.length === 0 && <div className="empty">Még nincs lista. Ha be van állítva a YT Music belépés (Beállítások), a listáid automatikusan megjelennek.</div>}
    </>
  );
}
export function LocalPlaylistPage({ id }: { id: number }) {
  const { data, err, loading, reload } = useLoad(() => api.playlist(id), [id]);
  const writable = data?.kind === "user";
  return (
    <>
      <Status loading={loading} err={err} />
      {data && <>
        <Hero title={data.title} sub={writable ? "Lejátszási lista" : "Mentett lista (csak olvasható)"} thumb={data.tracks[0]?.thumbnail}>
          <PlayAllBar tracks={data.tracks} />
          {writable && <div style={{ display: "flex", gap: 8 }}>
            <button className="btn ghost" onClick={async () => { const n = prompt("Új név", data.title); if (n) { await api.playlistRename(id, n); reload(); } }}>Átnevezés</button>
            <button className="btn ghost" onClick={async () => { if (confirm("Törlöd a listát? A YT Musicból is törlődik.")) { await api.playlistDelete(id); go("/library"); } }}>Törlés</button>
          </div>}
        </Hero>
        <TrackList tracks={data.tracks} extra={writable ? (t) => <button className="icon" title="Eltávolítás a listából" onClick={async () => { await api.playlistRemove(id, [t.video_id]); reload(); }}><Ic n="close" s={18} /></button> : undefined} />
      </>}
    </>
  );
}
export function SimpleList({ kind, title }: { kind: "liked" | "top" | "recent"; title: string }) {
  const { data, err, loading } = useLoad(() => api.library(kind), [kind]);
  return <><h1>{title}</h1><Status loading={loading} err={err} />{data && <><PlayAllBar tracks={data} /><TrackList tracks={data} /></>}</>;
}

// ---------- beállítások ----------
const PRESETS: Record<string, number[]> = {
  "Lapos": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0], "Basszus+": [6, 5, 4, 2, 0, 0, 0, 0, 0, 0], "Magas+": [0, 0, 0, 0, 0, 1, 2, 4, 5, 6],
  "Vokál": [-2, -1, 0, 2, 4, 4, 3, 1, 0, -1], "Rock": [4, 3, 1, -1, -2, 0, 2, 3, 4, 4], "Pop": [-1, 1, 3, 4, 3, 0, -1, -1, 1, 2], "Klasszikus": [0, 0, 0, 0, 0, 0, -2, -2, -2, -4],
};
const FREQ = ["32", "64", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"];

export function SettingsPage({ onLogout }: { onLogout: () => void }) {
  const c = useCtl();
  const s = c.settings;
  const status = useLoad(() => api.status(), []);
  const [hdr, setHdr] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState(c.deviceName);
  if (!s) return <div className="empty"><span className="spin" /></div>;
  const save = (v: Partial<Settings>) => c.saveSettings(v).catch((e) => c.toast(e.message));
  const st = status.data;
  const used = st ? st.cache.used_bytes / 1024 ** 3 : 0;
  const gb = (n: number) => n.toFixed(n < 10 ? 1 : 0);
  const Toggle = ({ k, label }: { k: keyof Settings; label: string }) => (
    <div className="field"><label>{label}</label><input className="switch" type="checkbox" checked={!!s[k]} onChange={(e) => save({ [k]: e.target.checked } as any)} /></div>
  );
  return (
    <>
      <h1>Beállítások</h1>

      <div className="panel"><h3>Hangzás</h3>
        <Toggle k="normalize" label="Hangerő-normalizálás" />
        <div className="field"><label>Crossfade</label>
          <input type="range" min={0} max={12000} step={500} value={s.crossfade_ms} onChange={(e) => save({ crossfade_ms: +e.target.value })} />
          <span style={{ width: 70 }}>{s.crossfade_ms ? `${s.crossfade_ms / 1000} mp` : "ki"}</span></div>
        <Toggle k="gapless" label="Gapless lejátszás (ha nincs crossfade)" />
        <Toggle k="eq_enabled" label="Equalizer" />
        <div style={{ opacity: s.eq_enabled ? 1 : 0.5 }}>
          <div className="chips">{Object.keys(PRESETS).map((p) => <button key={p} className="chip" onClick={() => save({ eq_gains: PRESETS[p] })}>{p}</button>)}</div>
          <div className="eq">
            <div><input type="range" min={-12} max={12} step={0.5} value={s.preamp_db} onChange={(e) => save({ preamp_db: +e.target.value })} {...{ orient: "vertical" }} /><span>Előerősítés</span></div>
            <span style={{ width: 20 }} />
            {FREQ.map((f, i) => (
              <div key={f}><input type="range" min={-12} max={12} step={0.5} value={s.eq_gains[i] ?? 0}
                onChange={(e) => { const g = s.eq_gains.slice(); g[i] = +e.target.value; save({ eq_gains: g }); }} /><span>{f}</span></div>
            ))}
          </div>
        </div>
      </div>

      <div className="panel"><h3>Szerver tárhely (letöltött zenék)</h3>
        <div className="field"><label>Tárhely limit</label>
          <input type="range" min={5} max={250} step={5} value={s.cache_limit_gb} onChange={(e) => save({ cache_limit_gb: +e.target.value })} />
          <input type="number" style={{ width: 80 }} min={1} value={s.cache_limit_gb} onChange={(e) => +e.target.value > 0 && save({ cache_limit_gb: +e.target.value })} /> GB</div>
        {st && <><div className="meter"><i style={{ width: `${Math.min(100, (used / s.cache_limit_gb) * 100)}%` }} /></div>
          <p className="muted">{gb(used)} GB / {s.cache_limit_gb} GB · {st.stats.cached_tracks} letöltött szám · {st.stats.tracks} ismert szám · {st.stats.total_plays} lejátszás · {st.stats.listened_hours} óra</p></>}
        <p className="muted">Ha betelik, a szerver a legkevesebbet játszott számok fájljait törli (a szöveg és a statisztika megmarad, lejátszáskor újra letöltődik). Az újonnan letöltött számok 14 napig védettek.</p>
        <div className="field"><label>Előre letöltés (következő számok)</label><input type="number" min={0} max={10} style={{ width: 70 }} value={s.prefetch_count} onChange={(e) => save({ prefetch_count: +e.target.value })} /></div>
        <Toggle k="lyrics_prefill" label="Szöveg automatikus előtöltése (LRCLIB / YT Music)" />
      </div>

      <div className="panel"><h3>YouTube Music fiók</h3>
        {st && <p>{st.ytm_connected ? <><span className="dot" /> Csatlakoztatva · {st.sync.pending} függő változtatás{st.sync.last_result?.at ? ` · utolsó szinkron: ${new Date(st.sync.last_result.at * 1000).toLocaleTimeString()}` : ""}</> : <><span className="dot off" /> Nincs csatlakoztatva</>}</p>}
        <div className="field"><label>Szinkron időköz (perc)</label><input type="number" min={1} style={{ width: 70 }} value={s.sync_interval_min} onChange={(e) => +e.target.value > 0 && save({ sync_interval_min: +e.target.value })} />
          <button className="btn ghost" disabled={busy || !st?.ytm_connected} onClick={async () => { setBusy(true); try { await api.syncRun(); c.toast("Szinkron kész"); status.reload(); } catch (e: any) { c.toast(e.message); } setBusy(false); }}>Szinkronizálás most</button></div>
        <details open={st ? !st.ytm_connected : false}><summary style={{ cursor: "pointer", fontWeight: 600 }}>{st?.ytm_connected ? "Bejelentkezés megújítása" : "Fiók csatlakoztatása (ide másold be a cookie-t)"}</summary>
          <ol className="muted">
            <li>Nyisd meg a <b>music.youtube.com</b>-ot a böngésződben, és jelentkezz be.</li>
            <li>F12 → Network (Hálózat) fül, szűrés: <code>browse</code>, majd kattints bármire az oldalon (vagy frissítsd az oldalt).</li>
            <li>Válassz ki egy kérést a music.youtube.com felé, és a <b>Request Headers</b> között keresd a <code>cookie:</code> sort.</li>
            <li>Elég a <b>cookie értékét</b> kimásolni (a <code>SID=…; __Secure-3PAPISID=…</code> hosszú szöveget). A teljes Request Headers blokk is jó.</li>
            <li>Illeszd be ide:</li>
          </ol>
          <textarea style={{ width: "100%", height: 130 }} value={hdr} onChange={(e) => setHdr(e.target.value)} placeholder="SID=...; __Secure-3PAPISID=...; (vagy a teljes Request Headers)" />
          <button className="btn" disabled={busy || !hdr.trim()} onClick={async () => { setBusy(true); try { await api.ytmAuth(hdr); setHdr(""); c.toast("Sikeres bejelentkezés"); status.reload(); } catch (e: any) { c.toast(e.message); } setBusy(false); }}>Mentés és kipróbálás</button>
        </details>
      </div>

      <div className="panel"><h3>Ez az eszköz</h3>
        <p className="muted" style={{ fontSize: 12 }}>Webes kliens build: {__BUILD__} · szerver: {st?.version ?? "…"}</p>
        <div className="field"><label>Eszköz neve (a távirányítóban)</label><input value={name} onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && c.setDeviceName(name.trim())} /></div>
        <button className="btn ghost" onClick={onLogout}>Kijelentkezés</button>
      </div>
    </>
  );
}

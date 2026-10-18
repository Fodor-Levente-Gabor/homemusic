import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ctl, useCtl, usePos, useView } from "./controller";
import { ArtistLink, bg, openTrackMenu } from "./components";
import { Ic } from "./icons";
import { ui, useWide } from "./ui";
import type { Lyrics, Track } from "./types";

export function NowPlaying() {
  const { nowPlaying, npTab, npFull } = ui.use();
  const wide = useWide();
  const v = useView();
  if (!nowPlaying) return null;
  const t = v.track;
  const docked = wide && !npFull;       // széles képernyőn alapból oldalpanel: a bal oldalon tovább lehet keresni
  return (
    <div className={`np ${docked ? "dock" : ""}`}>
      <div className="art" style={bg(t?.thumbnail)} />
      <div className="side2">
        <div className="tabs">
          <button className={npTab === "queue" ? "on" : ""} onClick={() => ui.set({ npTab: "queue" })}>Következik</button>
          <button className={npTab === "lyrics" ? "on" : ""} onClick={() => ui.set({ npTab: "lyrics" })}>Szöveg</button>
          <span style={{ flex: 1 }} />
          {wide && <button onClick={() => ui.set({ npFull: !npFull })} title={npFull ? "Oldalpanel" : "Teljes képernyő"}>{npFull ? "⇥" : "⤢"}</button>}
          <button onClick={() => ui.set({ nowPlaying: false })} title="Bezárás"><Ic n="down" /></button>
        </div>
        {npTab === "queue" ? <QueuePanel /> : t ? <LyricsPanel key={t.video_id} track={t} /> : <div className="empty">Nincs lejátszás</div>}
      </div>
    </div>
  );
}

function QueuePanel() {
  const v = useView();
  const c = useCtl();
  const { queue, index } = v.state;
  const cur = useRef<HTMLDivElement>(null);
  const [from, setFrom] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  useEffect(() => { cur.current?.scrollIntoView({ block: "center" }); }, [index]);
  const reset = () => { setFrom(null); setOver(null); };
  // átrendezés (húzással a listán belül) vagy beszúrás (a keresési találatból áthúzott szám)
  const drop = (e: React.DragEvent, at: number) => {
    e.preventDefault(); e.stopPropagation();
    const ext = e.dataTransfer.getData("application/x-hm-track");
    if (ext) { try { c.insertAt([JSON.parse(ext)], at); } catch { /* */ } }
    else if (from !== null) c.act("moveQueue", { from, to: Math.min(at, queue.length - 1) });
    reset();
  };
  return (
    <div className="scroll" onDragOver={(e) => e.preventDefault()} onDrop={(e) => drop(e, queue.length)}>
      <div className="lyr-tools">
        <button className="btn ghost" disabled={!v.track} onClick={async () => {
          try { const r = await api.radio(v.track!.video_id); c.enqueue(r.filter((x) => !queue.some((q) => q.video_id === x.video_id))); c.toast("Hasonló számok hozzáadva"); } catch (e: any) { c.toast(e.message); }
        }}>Hasonló számok hozzáadása</button>
        <button className="btn ghost" disabled={queue.length <= index + 1} onClick={() => { for (let i = queue.length - 1; i > index; i--) c.act("removeAt", { index: i }); }}>Következők törlése</button>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: "2px 0 8px" }}>Húzással átrendezheted a sorrendet; a keresési találatokat is ide húzhatod. Jobb klikk: további lehetőségek.</p>
      <div className="rows">
        {queue.map((t, i) => (
          <div key={t.video_id + i} ref={i === index ? cur : undefined} className={`row ${i === index ? "cur" : ""} ${over === i && from !== i ? "over" : ""}`} style={{ gridTemplateColumns: "44px 1fr 44px" }}
            draggable onDragStart={(e) => { setFrom(i); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(i)); }}
            onDragOver={(e) => { e.preventDefault(); setOver(i); }} onDrop={(e) => drop(e, i)} onDragEnd={reset}
            onContextMenu={(e) => openTrackMenu(e, t)} onClick={() => c.act("playIndex", { index: i })}>
            <div className="cv" style={bg(t.thumbnail)} />
            <div style={{ minWidth: 0 }}><div className="tt ellip">{t.title}</div><div className="muted ellip"><ArtistLink t={t} /></div></div>
            {i !== index && <button className="icon" onClick={(e) => { e.stopPropagation(); c.act("removeAt", { index: i }); }}><Ic n="close" s={18} /></button>}
          </div>
        ))}
        {!queue.length && <div className="empty">A várólista üres – húzz ide számokat, vagy használd a jobb klikk menüt</div>}
      </div>
    </div>
  );
}

const REACT_KEY = "hm_react_ms";

function LyricsPanel({ track }: { track: Track }) {
  const c = useCtl();
  const pos = usePos();
  const v = useView();
  const [lyr, setLyr] = useState<Lyrics | null | undefined>(undefined);
  const [mode, setMode] = useState<"view" | "sync" | "edit" | "lrc">("view");
  const [text, setText] = useState("");
  const [ptr, setPtr] = useState(0);
  const ptrRef = useRef(0);
  const movePtr = (n: number) => { ptrRef.current = n; setPtr(n); };
  const [react, setReact] = useState(() => { try { return +(localStorage.getItem(REACT_KEY) ?? 120); } catch { return 120; } });
  const lyrRef = useRef<Lyrics | null | undefined>(undefined);
  lyrRef.current = lyr;
  const activeRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => { api.lyrics(track.video_id).then(setLyr).catch(() => setLyr(null)); }, [track.video_id]);

  const lines = lyr?.lines ?? [];
  let active = -1;
  if (lyr?.synced && mode !== "sync") for (let i = 0; i < lines.length; i++) if (lines[i].t != null && lines[i].t! <= pos.position_ms) active = i;
  const shown = mode === "sync" ? ptr - 1 : active;      // szinkronnál: az utoljára időzített sor = most éneklett sor
  useEffect(() => { if (mode !== "edit" && mode !== "lrc") activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [shown, mode]);

  // ---- kézi szinkron ----
  const startSync = () => {
    if (lyr?.synced && !confirm("A szöveghez már van időzítés. Felülírod?")) return;
    movePtr(0); setMode("sync");
    c.act("seek", { position_ms: 0 }); c.act("play");
  };
  const nextLine = () => {
    const cur = lyrRef.current; if (!cur) return;
    const p = ptrRef.current;
    if (p >= cur.lines.length) return;
    const t = Math.max(0, Math.round(ctl.pos.position_ms - react));
    const nl = cur.lines.map((l, i) => (i === p ? { ...l, t } : l));
    const next = { ...cur, lines: nl, synced: nl.every((l) => l.t != null) };
    lyrRef.current = next; setLyr(next);
    api.lyricsLine(track.video_id, p, t).catch(() => ctl.toast("Mentési hiba – ellenőrizd a kapcsolatot"));
    movePtr(p + 1);
    if (p + 1 >= cur.lines.length) window.setTimeout(() => { setMode("view"); ctl.toast("Szinkron kész, elmentve"); }, 400);
  };
  const prevLine = () => {
    const n = Math.max(0, ptrRef.current - 1);
    const prevT = lyrRef.current?.lines[n - 1]?.t;
    movePtr(n);
    ctl.act("seek", { position_ms: Math.max(0, (prevT ?? 0) - 500) });
  };
  useEffect(() => {
    if (mode !== "sync") return;
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "TEXTAREA" || (e.target as HTMLElement).tagName === "INPUT") return;
      if (e.code === "Space" || e.code === "Enter" || e.code === "ArrowRight") { e.preventDefault(); nextLine(); }
      if (e.code === "ArrowLeft" || e.code === "Backspace") { e.preventDefault(); prevLine(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  const shift = async (d: number) => { try { setLyr(await api.lyricsShift(track.video_id, d)); } catch (e: any) { ctl.toast(e.message); } };
  const download = async () => {
    const lrc = await api.lyricsLrc(track.video_id);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lrc], { type: "text/plain" }));
    a.download = `${track.artist} - ${track.title}.lrc`; a.click();
  };

  if (lyr === undefined) return <div className="empty"><span className="spin" /></div>;

  if (mode === "edit" || mode === "lrc" || (lyr === null && mode === "view")) {
    const isLrc = mode === "lrc";
    return (
      <div className="scroll">
        {lyr === null && mode === "view" && <p className="muted">Ehhez a számhoz még nincs szöveg. Illeszd be, utána szinkronizálhatod.</p>}
        <textarea style={{ width: "100%", height: "46vh" }} value={text} onChange={(e) => setText(e.target.value)}
          placeholder={isLrc ? "[00:12.30]Első sor\n[00:15.80]Második sor" : "Szöveg, soronként"} />
        <div className="lyr-tools">
          <button className="btn" disabled={!text.trim()} onClick={async () => {
            try { setLyr(isLrc ? await api.lyricsImportLrc(track.video_id, text) : await api.lyricsPlain(track.video_id, text)); setMode("view"); } catch (e: any) { ctl.toast(e.message); }
          }}>Mentés</button>
          {lyr && <button className="btn ghost" onClick={() => setMode("view")}>Mégse</button>}
          {lyr === null && <button className="btn ghost" onClick={() => { setMode("lrc"); setText(""); }}>LRC beillesztése</button>}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="lyr-tools">
        {mode === "view" && (
          <>
            <button className="btn red" onClick={startSync}>Sync</button>
            <button className="btn ghost" onClick={() => { setText(lines.map((l) => l.text).join("\n")); setMode("edit"); }}>Szöveg szerkesztése</button>
            <button className="btn ghost" onClick={() => { setText(""); setMode("lrc"); }}>LRC import</button>
            {lyr?.synced && <>
              <button className="btn ghost" onClick={() => shift(-200)}>−0,2 s</button>
              <button className="btn ghost" onClick={() => shift(200)}>+0,2 s</button>
              <button className="btn ghost" onClick={download}>.lrc</button>
            </>}
            <button className="icon" title="Szöveg törlése" onClick={async () => { if (confirm("Törlöd a szöveget és az időzítést?")) { await api.lyricsDelete(track.video_id); setLyr(null); } }}><Ic n="trash" s={18} /></button>
            <span className="muted" style={{ fontSize: 12 }}>{lyr?.synced ? "szinkronizált" : "nincs időzítve"} · forrás: {lyr?.source}</span>
          </>
        )}
      </div>
      <div className="scroll">
        <div className={`lyr ${lyr?.synced ? "" : "plain"}`}>
          {lines.map((l, i) => (
            <p key={i} ref={i === shown ? activeRef : undefined}
              className={`${i === shown ? "act" : mode !== "sync" && l.t != null && l.t < pos.position_ms ? "past" : ""} ${mode === "sync" && i === ptr ? "syncnext" : ""} ${mode === "sync" && i < ptr - 1 ? "past" : ""}`}
              onClick={() => { if (mode === "view" && l.t != null) c.act("seek", { position_ms: l.t }); }}>{l.text}</p>
          ))}
        </div>
      </div>
      {mode === "sync" && (
        <div className="syncbar">
          <button className="next" onClick={nextLine}>{ptr >= lines.length ? "Kész" : ptr === 0 ? "Az 1. sor MOST kezdődik (szóköz)" : `A következő sor MOST kezdődik (szóköz) – ${ptr + 1}/${lines.length}`}</button>
          <button className="btn ghost" onClick={prevLine}>Vissza</button>
          <button className="btn ghost" onClick={() => { movePtr(0); c.act("seek", { position_ms: 0 }); }}>Újrakezdés</button>
          <button className="btn ghost" onClick={() => c.act("toggle")}>{v.state.playing ? "Szünet" : "Lejátszás"}</button>
          <label className="muted" style={{ fontSize: 12 }}>Reakcióidő korrekció
            <input type="number" style={{ width: 70, marginLeft: 6 }} value={react} step={20} onChange={(e) => { const n = +e.target.value; setReact(n); try { localStorage.setItem(REACT_KEY, String(n)); } catch { /* */ } }} /> ms</label>
          <button className="btn ghost" onClick={() => setMode("view")}>Kilépés</button>
        </div>
      )}
    </>
  );
}

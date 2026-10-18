import { useEffect, useRef, useState } from "react";
import { api, clearToken, getToken, setToken, setUnauthorizedHandler } from "./api";
import { DevicesPopup, PlayerBar, TrackMenu } from "./components";
import { ctl, useCtl } from "./controller";
import { Ic } from "./icons";
import { NowPlaying } from "./NowPlaying";
import { Album, Artist, Explore, Home, Library, LocalPlaylistPage, Search, SettingsPage, SimpleList, YtmPlaylist } from "./pages";
import { go, isWide, ui, useHash, useWide } from "./ui";

type Phase = "checking" | "login" | "splash" | "app";

export default function App() {
  const [phase, setPhase] = useState<Phase>("checking");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");

  const logout = () => { clearToken(); ctl.stop(); setPhase("login"); };
  useEffect(() => { setUnauthorizedHandler(() => { clearToken(); setPhase("login"); }); }, []);
  useEffect(() => {
    (async () => {
      try {
        const p = await api.ping();
        if (!p.auth_required && !getToken()) { const r = await api.login(""); setToken(r.token); }
        if (getToken()) { await api.status(); setPhase("splash"); } else setPhase("login");
      } catch { setPhase("login"); }
    })();
  }, []);

  const begin = async () => { await ctl.engine.unlock(); await ctl.start(); setPhase("app"); };

  if (phase === "checking") return <div className="splash"><span className="spin" /></div>;
  if (phase === "login") return (
    <div className="login"><form onSubmit={async (e) => { e.preventDefault(); try { const r = await api.login(pw); setToken(r.token); setErr(""); setPhase("splash"); } catch { setErr("Hibás jelszó"); } }}>
      <h1 style={{ margin: 0 }}>HomeMusic</h1>
      <input type="password" placeholder="Jelszó" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} />
      <button className="btn red" style={{ justifyContent: "center" }}>Belépés</button>
      {err && <div className="err">{err}</div>}
    </form></div>
  );
  if (phase === "splash") return (
    <div className="splash"><div>
      <h1 style={{ margin: 0 }}>HomeMusic</h1>
      <p className="muted">A böngészők csak kattintás után engedik a hanglejátszást. Ezután a telefonról is tudod irányítani ezt a lejátszót.</p>
      <button className="btn red" style={{ justifyContent: "center", fontSize: 16 }} onClick={begin}><Ic n="play" /> Lejátszó indítása</button>
    </div></div>
  );
  return <Shell onLogout={logout} />;
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const hash = useHash();
  const c = useCtl();
  const [q, setQ] = useState("");
  const [sugg, setSugg] = useState<string[]>([]);
  const main = useRef<HTMLDivElement>(null);
  const wide = useWide();
  const { nowPlaying, npFull } = ui.use();
  const docked = nowPlaying && wide && !npFull;
  const [ytmOk, setYtmOk] = useState<boolean | null>(null);
  useEffect(() => { api.status().then((s) => setYtmOk(!!s.ytm_connected)).catch(() => {}); }, [hash === "/settings"]);
  const [route, arg] = (() => { const m = hash.match(/^\/([^/]*)\/?(.*)$/); return [m?.[1] || "home", decodeURIComponent(m?.[2] || "")]; })();

  useEffect(() => { main.current?.scrollTo(0, 0); if (!isWide() || ui.get().npFull) ui.set({ nowPlaying: false }); }, [hash]);
  useEffect(() => {
    if (q.length < 2) { setSugg([]); return; }
    const t = setTimeout(() => api.suggest(q).then(setSugg).catch(() => {}), 200);
    return () => clearTimeout(t);
  }, [q]);
  // billentyűzet: szóköz = lejátszás/szünet (ha nem beviteli mezőben vagyunk és nincs sync mód)
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || e.code !== "Space" || ui.get().nowPlaying && ui.get().npTab === "lyrics") return;
      e.preventDefault(); c.act("toggle");
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [c]);

  const doSearch = (s: string) => { if (s.trim()) { setSugg([]); go(`/search/${encodeURIComponent(s.trim())}`); } };
  const nav = (p: string, icon: string, label: string) => <a href={`#${p}`} className={route === p.slice(1) ? "on" : ""}><Ic n={icon} />{label}</a>;

  let page: React.ReactNode;
  switch (route) {
    case "explore": page = <Explore />; break;
    case "search": page = <Search q={arg} />; break;
    case "library": page = <Library />; break;
    case "playlist": page = <LocalPlaylistPage id={+arg} />; break;
    case "ytm": page = <YtmPlaylist id={arg} />; break;
    case "album": page = <Album id={arg} />; break;
    case "artist": page = <Artist id={arg} />; break;
    case "liked": page = <SimpleList kind="liked" title="Kedvelt számok" />; break;
    case "recent": page = <SimpleList kind="recent" title="Legutóbb hallgatott" />; break;
    case "top": page = <SimpleList kind="top" title="Legtöbbet hallgatott" />; break;
    case "settings": page = <SettingsPage onLogout={onLogout} />; break;
    default: page = <Home />;
  }

  return (
    <div className={`layout ${docked ? "docked" : ""}`}>
      <div className="top">
        <div className="logo"><i>▶</i> HomeMusic</div>
        <div className="search">
          <Ic n="search" s={20} />
          <input placeholder="Keresés dalok, albumok, előadók között" value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doSearch(q)} onBlur={() => setTimeout(() => setSugg([]), 150)} />
          {sugg.length > 0 && <div className="suggest">{sugg.map((s) => <div key={s} onMouseDown={() => { setQ(s); doSearch(s); }}>{s}</div>)}</div>}
        </div>
        <div className="spacer" />
        <span className="pill" title={c.wsOnline ? "A távirányító kapcsolat él" : "A távirányító kapcsolat megszakadt, újracsatlakozás…"}><span className={`dot ${c.wsOnline ? "" : "off"}`} />{c.wsOnline ? `${c.devices.length + 1} eszköz` : "offline"}</span>
      </div>
      <nav className="side">
        {nav("/home", "home", "Főoldal")}{nav("/explore", "explore", "Felfedezés")}{nav("/library", "lib", "Könyvtár")}
        <hr />
        {nav("/liked", "heart", "Kedvelt számok")}
        <hr />
        {nav("/settings", "gear", "Beállítások")}
      </nav>
      <div className="main" ref={main}>
        {ytmOk === false && route !== "settings" && (
          <div className="banner">Nincs YouTube Music fiók csatlakoztatva, ezért a saját listáid, kedvelt számaid és az ajánlók nem látszanak.
            <a href="#/settings">Fiók csatlakoztatása →</a></div>
        )}
        {page}
      </div>
      <NowPlaying />
      <PlayerBar />
      <TrackMenu />
      <DevicesPopup />
      {c.toastMsg && <div className="toast">{c.toastMsg}</div>}
    </div>
  );
}

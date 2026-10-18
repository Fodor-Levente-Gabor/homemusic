import type { Item, Lyrics, LocalPlaylist, Settings, Track } from "./types";

const TOKEN_KEY = "hm_token";
export const getToken = () => localStorage.getItem(TOKEN_KEY) || "";
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
let onUnauthorized: () => void = () => {};
export const setUnauthorizedHandler = (f: () => void) => { onUnauthorized = f; };

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) { onUnauthorized(); throw new ApiError(401, "Bejelentkezés szükséges"); }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* nem JSON */ }
    throw new ApiError(r.status, String(msg));
  }
  const ct = r.headers.get("content-type") || "";
  return (ct.includes("json") ? r.json() : r.text()) as Promise<T>;
}
const get = <T,>(u: string) => req<T>("GET", u);
const post = <T,>(u: string, b?: unknown) => req<T>("POST", u, b ?? {});
const put = <T,>(u: string, b: unknown) => req<T>("PUT", u, b);
const patch = <T,>(u: string, b: unknown) => req<T>("PATCH", u, b);
const del = <T,>(u: string) => req<T>("DELETE", u);
const q = encodeURIComponent;

export const api = {
  ping: () => fetch("/api/ping").then((r) => r.json() as Promise<{ auth_required: boolean }>),
  login: (password: string) =>
    fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) })
      .then(async (r) => { if (!r.ok) throw new ApiError(r.status, "Hibás jelszó"); return r.json() as Promise<{ token: string }>; }),
  status: () => get<any>("/api/status"),
  settings: () => get<Settings>("/api/settings"),
  saveSettings: (v: Partial<Settings>) => put<Settings>("/api/settings", v),
  ytmAuth: (headers_raw: string) => post<{ ok: boolean }>("/api/ytm/auth", { headers_raw }),
  syncRun: () => post<any>("/api/sync/run"),

  search: (s: string, filter?: string) => get<Item[]>(`/api/search?q=${q(s)}${filter ? `&filter=${filter}` : ""}`),
  suggest: (s: string) => get<string[]>(`/api/suggest?q=${q(s)}`),
  home: () => get<{ title: string; items: Item[] }[]>("/api/home"),
  mood: () => get<{ section: string; title: string; params: string }[]>("/api/mood"),
  moodPlaylists: (params: string) => get<Item[]>(`/api/mood/playlists?params=${q(params)}`),
  charts: () => get<Record<string, Item[]>>("/api/charts"),
  ytmPlaylist: (id: string) => get<{ id: string; title: string; tracks: Track[]; thumbnail?: string }>(`/api/ytm/playlist/${q(id)}`),
  album: (id: string) => get<{ title: string; year?: string; artists: string[]; thumbnail?: string; tracks: Track[] }>(`/api/album/${q(id)}`),
  artist: (id: string, name?: string) => get<{ name: string; description: string; thumbnail?: string; sections: Record<string, Item[]>; radio_id?: string }>(`/api/artist/${q(id)}${name ? `?name=${q(name)}` : ""}`),
  radio: (vid: string) => get<Track[]>(`/api/radio/${q(vid)}`),
  mixRandom: () => get<Track[]>("/api/mix/random"),
  mixFamiliar: () => get<Track[]>("/api/mix/familiar"),

  ensure: (vid: string) => get<Track>(`/api/ensure/${q(vid)}`),
  audioUrl: (vid: string) => `/api/audio/${q(vid)}?token=${q(getToken())}`,
  prefetch: (ids: string[]) => post("/api/prefetch", { ids }),
  playStart: (video_id: string, device_id: string) => post<{ event_id: number }>("/api/play/start", { video_id, device_id }),
  playProgress: (event_id: number, listened_sec: number) => post("/api/play/progress", { event_id, listened_sec }),
  like: (vid: string, liked: boolean) => post(`/api/like/${q(vid)}`, { liked }),

  lyrics: (vid: string) => get<Lyrics>(`/api/lyrics/${q(vid)}`),
  lyricsSave: (vid: string, lines: Lyrics["lines"]) => put<Lyrics>(`/api/lyrics/${q(vid)}`, { lines }),
  lyricsPlain: (vid: string, text: string) => put<Lyrics>(`/api/lyrics/${q(vid)}/plain`, { text }),
  lyricsLine: (vid: string, idx: number, t: number | null) => patch<Lyrics>(`/api/lyrics/${q(vid)}/line`, { idx, t }),
  lyricsShift: (vid: string, delta_ms: number) => post<Lyrics>(`/api/lyrics/${q(vid)}/shift`, { delta_ms }),
  lyricsLrc: (vid: string) => get<string>(`/api/lyrics/${q(vid)}/lrc`),
  lyricsImportLrc: (vid: string, text: string) => post<Lyrics>(`/api/lyrics/${q(vid)}/lrc`, { text }),
  lyricsDelete: (vid: string) => del(`/api/lyrics/${q(vid)}`),

  library: (kind: "liked" | "top" | "recent") => get<Track[]>(`/api/library/${kind}`),
  playlists: () => get<LocalPlaylist[]>("/api/playlists"),
  playlist: (id: number) => get<{ id: number; title: string; kind: string; tracks: Track[] }>(`/api/playlists/${id}`),
  playlistCreate: (title: string, video_ids: string[] = []) => post<LocalPlaylist>("/api/playlists", { title, video_ids }),
  playlistAdd: (id: number, video_ids: string[]) => post(`/api/playlists/${id}/items`, { video_ids }),
  playlistRemove: (id: number, video_ids: string[]) => post(`/api/playlists/${id}/items/remove`, { video_ids }),
  playlistRename: (id: number, title: string) => patch(`/api/playlists/${id}`, { title }),
  playlistDelete: (id: number) => del(`/api/playlists/${id}`),

  cacheDelete: (vid: string) => del(`/api/cache/${q(vid)}`),
  cachePin: (vid: string, pinned: boolean) => post(`/api/cache/${q(vid)}/pin`, { pinned }),
};

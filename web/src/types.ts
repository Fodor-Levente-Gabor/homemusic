export interface Track {
  video_id: string;
  title: string;
  artist: string;
  artists?: string[];
  album?: string;
  album_id?: string | null;
  duration_sec?: number | null;
  thumbnail?: string | null;
  gain_db?: number;
  liked?: boolean;
  cached?: boolean;
  play_count?: number;
}
export type Repeat = "off" | "all" | "one";

export interface PlayerState {
  queue: Track[];
  index: number;
  playing: boolean;
  loading: boolean;
  error: string | null;
  volume: number;
  shuffle: boolean;
  repeat: Repeat;
}
export interface Position {
  position_ms: number;
  duration_ms: number;
}
export interface Settings {
  cache_limit_gb: number;
  crossfade_ms: number;
  gapless: boolean;
  normalize: boolean;
  target_lufs: number;
  eq_enabled: boolean;
  eq_gains: number[];
  preamp_db: number;
  sync_interval_min: number;
  lyrics_prefill: boolean;
  prefetch_count: number;
}
export interface DeviceInfo {
  id: string;
  name: string;
  kind: string;
  state: Partial<PlayerState & Position> & { track?: Track | null };
}
export interface LyricLine { t: number | null; text: string }
export interface Lyrics { video_id: string; lines: LyricLine[]; synced: boolean; source: string }
export type Item =
  | ({ type: "track" } & Track)
  | { type: "album" | "artist" | "playlist"; id: string; title: string; subtitle?: string; thumbnail?: string | null };
export interface LocalPlaylist { id: number; ytm_id: string | null; title: string; thumbnail?: string | null; kind: string; count: number }

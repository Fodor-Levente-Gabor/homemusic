import { useSyncExternalStore } from "react";
import type { Track } from "./types";

function createStore<T extends object>(init: T) {
  let state = init;
  const ls = new Set<() => void>();
  return {
    get: () => state,
    set: (p: Partial<T>) => { state = { ...state, ...p }; ls.forEach((l) => l()); },
    use: () => useSyncExternalStore((l) => { ls.add(l); return () => ls.delete(l); }, () => state),
  };
}

export const ui = createStore({
  nowPlaying: false,
  npFull: false,                      // teljes képernyős lejátszó nézet (alapból széles képernyőn oldalpanel)
  npTab: "queue" as "queue" | "lyrics",
  devices: false,
  menu: null as null | { track: Track; x: number; y: number },
  picker: null as null | Track[],     // lista-választó (hozzáadás listához)
});

export const fmt = (ms: number) => {
  if (!isFinite(ms) || ms < 0) ms = 0;
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
};

export function useHash(): string {
  return useSyncExternalStore(
    (l) => { window.addEventListener("hashchange", l); return () => window.removeEventListener("hashchange", l); },
    () => location.hash.slice(1) || "/home",
  );
}
export const go = (path: string) => { location.hash = path; };

/** Széles képernyő: a lejátszó oldalpanelként nyílik, a keresés mellette használható marad. */
const wideMq = typeof window !== "undefined" ? window.matchMedia("(min-width: 1100px)") : null;
export const isWide = () => !!wideMq?.matches;
export function useWide(): boolean {
  return useSyncExternalStore((l) => { wideMq?.addEventListener("change", l); return () => wideMq?.removeEventListener("change", l); }, isWide);
}

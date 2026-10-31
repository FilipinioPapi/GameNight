// What the Windows side tells the in-game menu (src-tauri/src/ingame.rs MenuInfo), and sample answers so
// the menu can be looked at in a plain browser: /menu.html (Couch Play host), ?solo, ?friend, ?paused.
import type { Lobby } from "../lib/couch.svelte";

export interface PausedBy { by: { id: string; name: string } | null; seconds: number }
export interface MenuInfo {
  open: boolean;
  mode: "solo" | "couch";
  title: string;
  console: string;
  look: string;
  host: boolean;
  watching: boolean;
  fullscreen: boolean;
  lobby: (Lobby & { paused?: PausedBy | null }) | null;
}

export function sampleInfo(): MenuInfo {
  const q = new URLSearchParams(location.search);
  if (q.has("solo"))
    return { open: true, mode: "solo", title: "Super Mario World", console: "snes", look: "royale", host: true, watching: false, fullscreen: true, lobby: null };
  const friend = q.has("friend");
  const J = { id: "jayden", name: "Jayden" }, S = { id: "sam", name: "Sam" }, R = { id: "rio", name: "Rio" };
  const lobby = {
    code: "K7QM2X", open: true, started: true, players: 3,
    game: { id: "snes-bomberman", title: "Super Bomberman", console: "snes" as const },
    host: J,
    you: friend ? { id: "sam", role: "play" as const, seat: 2 } : { id: "jayden", role: "host" as const, seat: 1 },
    seats: [
      { n: 1, user: J, status: "playing" as const, held_left: null },
      { n: 2, user: S, status: "playing" as const, held_left: null },
      { n: 3, user: R, status: "playing" as const, held_left: null },
      { n: 4, user: null, status: "empty" as const, held_left: null },
    ],
    watchers: [{ id: "alex", name: "Alex" }, { id: "mo", name: "Mo" }],
    relay: null, ended: null,
    paused: q.has("paused") ? { by: J, seconds: 24 } : null,
  };
  return { open: !q.has("paused"), mode: "couch", title: "Super Bomberman", console: "snes", look: "royale", host: !friend, watching: false, fullscreen: true, lobby };
}

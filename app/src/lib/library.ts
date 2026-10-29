// Where the game list comes from: the Game Night server (which reads Jayden's RomM library),
// or a built-in sample list in the screen preview. Screens only ever talk to this file.

import type { ConsoleId } from "./consoles";
import { inTauri } from "./settings";

export interface Game {
  id: string;
  title: string;
  console: ConsoleId;
  players: string;          // e.g. "1-2"
  sizeBytes: number;
  description?: string;
  cover?: string;           // box art address, once RomM is connected
}

export interface LocalInfo {
  onPC: boolean;
  downloading?: number;     // 0..1 while downloading
}

const g = (id: string, title: string, console: ConsoleId, players: string, mb: number, description?: string): Game =>
  ({ id, title, console, players, sizeBytes: Math.round(mb * 1024 * 1024), description });

const SAMPLE: Game[] = [
  g("nes-castlevania", "Castlevania", "nes", "1", 0.13, "Simon Belmont climbs Dracula's castle, whip in hand."),
  g("nes-smb", "Super Mario Bros.", "nes", "1-2", 0.04, "The one that started it all. Take turns as Mario and Luigi."),
  g("nes-megaman2", "Mega Man 2", "nes", "1", 0.25, "Beat eight Robot Masters and take their weapons."),
  g("nes-contra", "Contra", "nes", "1-2", 0.13, "Two-player run-and-gun. Up, up, down, down..."),
  g("nes-zelda", "The Legend of Zelda", "nes", "1", 0.13),
  g("nes-dr-mario", "Dr. Mario", "nes", "1-2", 0.06),
  g("snes-smw", "Super Mario World", "snes", "1-2", 0.5, "Mario and Yoshi explore Dinosaur Land. 96 exits to find."),
  g("snes-alttp", "Zelda: A Link to the Past", "snes", "1", 1.0, "Link crosses the Light and Dark Worlds to save Hyrule."),
  g("snes-metroid", "Super Metroid", "snes", "1", 3.0),
  g("snes-dkc", "Donkey Kong Country", "snes", "1-2", 4.0),
  g("snes-chrono", "Chrono Trigger", "snes", "1", 4.0),
  g("snes-sf2t", "Street Fighter II Turbo", "snes", "1-2", 2.5),
  g("gen-sonic2", "Sonic the Hedgehog 2", "gen", "1-2", 1.0),
  g("gen-sor2", "Streets of Rage 2", "gen", "1-2", 2.0),
  g("gb-pokemon-red", "Pokemon Red", "gb", "1", 1.0),
  g("gba-minish", "Zelda: The Minish Cap", "gba", "1", 16),
  g("arc-sf2", "Street Fighter II", "arc", "1-2", 3.2),
  g("ps1-crash", "Crash Bandicoot", "ps1", "1", 480),
  g("ps1-spyro", "Spyro the Dragon", "ps1", "1", 520),
  g("n64-mk64", "Mario Kart 64", "n64", "1-4", 12),
  g("gc-melee", "Super Smash Bros. Melee", "gc", "1-4", 1400),
  g("ps2-ratchet", "Ratchet & Clank", "ps2", "1", 4200),
];

// Pretend a few are already downloaded, so the screens show both states.
const SAMPLE_LOCAL: Record<string, LocalInfo> = {
  "snes-smw": { onPC: true },
  "snes-alttp": { onPC: true },
  "nes-castlevania": { onPC: true },
  "snes-chrono": { onPC: false, downloading: 0.6 },
};

export type Source = "sample" | "server" | "offline";
export interface Library { games: Game[]; source: Source; error?: string; }

let cached: { at: number; lib: Promise<Library> } | null = null;

async function fromServer(): Promise<Library> {
  const { invoke, convertFileSrc } = await import("@tauri-apps/api/core");
  try {
    const r = await invoke<{ games: (Game & { hasCover?: boolean; coverVersion?: string | null })[]; offline: boolean }>("fetch_games");
    // The cover address carries its version, so a cover saved on this PC is replaced when it changes in RomM.
    const games = (r.games ?? []).map(({ hasCover, coverVersion, ...g }) => ({
      ...g,
      cover: hasCover ? convertFileSrc(`${g.id}-${coverVersion || "0"}`, "gncover") : undefined,
    }));
    return { games, source: r.offline ? "offline" : "server" };
  } catch (e) {
    cached = null;
    const msg = String(e);
    return { games: [], source: "offline", error: msg.startsWith("server-") ? "The game library is offline right now." : "Couldn't reach the Game Night server." };
  }
}

/** The whole library. Asked for again at most once a minute. */
export function loadLibrary(): Promise<Library> {
  if (!inTauri) return Promise.resolve({ games: SAMPLE, source: "sample" });
  if (!cached || Date.now() - cached.at > 60_000) cached = { at: Date.now(), lib: fromServer() };
  return cached.lib;
}

export async function listGames(): Promise<Game[]> {
  return (await loadLibrary()).games;
}

/** Downloaded or not. Real downloads arrive in milestone 4; the preview pretends a few are. */
export function localInfo(id: string): LocalInfo {
  return (inTauri ? undefined : SAMPLE_LOCAL[id]) ?? { onPC: false };
}

export function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${Math.round(bytes / 1024 / 1024)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export const isCoop = (g: Game) => g.players !== "1";

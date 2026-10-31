// Couch Play online: hosting a game, joining with a code, the lobby and its seats.
// The Windows side does the real work (src-tauri/src/couch.rs: the server, the relay and the game box);
// this file keeps the latest copy of the lobby for the screens and passes on what you press.
// The shapes below follow docs/COUCH_PLAY_SPEC.md exactly.
// In a plain browser (building the screens) it answers with sample lobbies instead, so every screen
// can be looked at. Add ?couch=guest, ?couch=dropped, ?couch=lost, ?couch=closed or ?couch=waiting
// to the address to see the other situations.

import type { ConsoleId } from "./consoles";
import type { Game } from "./library";
import { listGames } from "./library";
import { play } from "./play.svelte";
import { inTauri } from "./settings";
import { app } from "./state.svelte";

export interface CouchUser { id: string; name: string; avatar?: string | null; }
export interface LobbyGame { id: string; title: string; console: ConsoleId; }
export interface LobbySummary {
  code: string;
  open: boolean;
  game: LobbyGame;
  host: CouchUser;
  players: number;
  watchers: number;
  started: boolean;
}
export type Role = "host" | "play" | "watch";
export interface Seat { n: number; user: CouchUser | null; status: "playing" | "held" | "empty"; held_left: number | null; }
export interface Lobby extends Omit<LobbySummary, "watchers"> {
  you: { id: string; role: Role; seat: number | null };
  seats: Seat[];
  watchers: CouchUser[];
  relay: { server: string; port: number; session: string } | null;
  ended: null | "host-left" | "host-ended";
}

/** The letters a code can use: no O / 0 / I / 1, so nothing gets mixed up. */
export const CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
export const CODE_LENGTH = 6;
/** Only these consoles can be played online for now. */
export const ONLINE_CONSOLES: ConsoleId[] = ["nes", "snes"];

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}

/** "1-4" -> 4. Up to 4 people can play in a lobby. */
export function maxPlayersOf(players: string | undefined): number {
  const n = Number(String(players ?? "").split("-").pop());
  return n >= 1 ? Math.min(4, n) : 4;
}

/** "3:05" from seconds. */
export function clockOf(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// ---------------------------------------------------------------- sample answers (browser only)

const SAMPLE_PLAYERS: Record<string, string> = { "snes-contra3": "1-2", "snes-smk": "1-2", "snes-bomberman": "1-4" };
const SAM: CouchUser = { id: "sam", name: "Sam" };
const RIO: CouchUser = { id: "rio", name: "Rio" };
const ALEX: CouchUser = { id: "alex", name: "Alex" };
const MO: CouchUser = { id: "mo", name: "Mo" };
const JAYDEN: CouchUser = { id: "jayden", name: "Jayden" };
const BOMBERMAN: LobbyGame = { id: "snes-bomberman", title: "Super Bomberman", console: "snes" };

const SAMPLE_LIST: LobbySummary[] = [
  { code: "H4TRWN", open: true, game: { id: "snes-contra3", title: "Contra III", console: "snes" }, host: SAM, players: 2, watchers: 1, started: true },
  { code: "P9MXCE", open: true, game: { id: "nes-smb", title: "Super Mario Bros.", console: "nes" }, host: ALEX, players: 1, watchers: 0, started: false },
  { code: "ZB7KQD", open: true, game: { id: "snes-smk", title: "Super Mario Kart", console: "snes" }, host: RIO, players: 2, watchers: 3, started: true },
];

function sampleView(): string {
  if (typeof location === "undefined") return "host";
  return new URLSearchParams(location.search).get("couch") ?? "host";
}

function me(): CouchUser {
  return app.user ? { id: app.user.id, name: app.user.name, avatar: app.user.avatar ?? null } : { id: "preview", name: "Player 1" };
}

function seat(n: number, user: CouchUser | null, status: Seat["status"] = user ? "playing" : "empty", held: number | null = null): Seat {
  return { n, user, status, held_left: held };
}

function summarise(l: Lobby): LobbySummary {
  return { code: l.code, open: l.open, game: l.game, host: l.host, players: l.seats.filter((s) => s.user).length, watchers: l.watchers.length, started: l.started };
}

/** A pretend lobby like the approved boards (CQ4 / CQ6). */
function sampleLobby(view: string, game: LobbyGame = BOMBERMAN, as: "play" | "watch" = "watch"): Lobby {
  const you = me();
  const base = { code: "K7QM2X", open: true, game, players: 3, started: view !== "waiting", relay: null, ended: null } as const;
  if (view === "host" || view === "dropped" || view === "waiting") {
    return {
      ...base, host: you, you: { id: you.id, role: "host", seat: 1 },
      seats: [seat(1, you), view === "dropped" ? seat(2, SAM, "held", 102) : seat(2, SAM), seat(3, RIO), seat(4, null)],
      watchers: [ALEX, MO],
    };
  }
  if (view === "lost") {
    return {
      ...base, host: JAYDEN, you: { id: you.id, role: "play", seat: 2 },
      seats: [seat(1, JAYDEN), seat(2, you, "held", 102), seat(3, RIO), seat(4, null)], watchers: [ALEX, MO],
    };
  }
  // A friend's lobby: you joined to watch (or to play, in the free seat).
  return {
    ...base, host: JAYDEN, you: { id: you.id, role: as, seat: as === "play" ? 4 : null },
    seats: [seat(1, JAYDEN), seat(2, SAM), seat(3, RIO), seat(4, as === "play" ? you : null)],
    watchers: as === "play" ? [MO] : [you, MO],
  };
}

// ---------------------------------------------------------------- the state the screens show

class Couch {
  /** The lobby you're in (latest copy from the Windows side), or null. */
  lobby = $state<Lobby | null>(null);
  /** When that copy arrived, for counting down held seats between updates. */
  lobbyAt = $state(0);
  /** Open lobbies for the main menu and the Couch Play screen. */
  list = $state<LobbySummary[]>([]);
  listLoaded = $state(false);
  /** The lobby ended: "host-left", "host-ended", or another reason (your link dropped). */
  ended = $state<{ reason: string } | null>(null);
  /** Game box full screen. */
  fullscreen = $state(false);
  /** What's happening right now, for the screens to say ("Downloading Contra… 45%"). */
  busy = $state("");
  error = $state("");
  /** The code and choice you last joined with, so you can get back in with the same code. */
  lastCode = "";
  lastAs: "play" | "watch" = "watch";
  private listening = false;
  private lastBox = "";

  private async listen() {
    if (this.listening || !inTauri) return;
    this.listening = true;
    const { listen } = await import("@tauri-apps/api/event");
    await listen<Lobby>("couch-update", (e) => this.got(e.payload));
    await listen<{ reason: string }>("couch-ended", (e) => {
      this.ended = { reason: e.payload?.reason || "ended" };
      this.fullscreen = false;
    });
  }

  private got(l: Lobby | null) {
    this.lobby = l;
    this.lobbyAt = Date.now();
    if (l) {
      this.lastCode = l.code;
      if (l.ended) this.ended = { reason: l.ended };
    }
  }

  /** Plain-English error, and back to the sign-in screen if the pass expired. */
  private fail(e: unknown): string {
    const msg = String(e).replace(/^Error:\s*/, "");
    if (msg === "signed-out") app.signedOut();
    this.error = msg;
    return msg;
  }

  /** Seconds left on a held seat, counting down between updates. */
  heldLeft(s: Seat, now: number): number {
    if (s.held_left == null) return 0;
    return Math.max(0, s.held_left - (now - this.lobbyAt) / 1000);
  }

  // ---- Open lobbies ----
  async refreshList() {
    if (!inTauri) {
      this.list = SAMPLE_LIST;
      this.listLoaded = true;
      return;
    }
    await this.listen();
    try {
      this.list = await invoke<LobbySummary[]>("couch_list");
    } catch (e) {
      const msg = String(e);
      if (msg === "signed-out") app.signedOut();
      console.warn("Couldn't load open lobbies", e);
    }
    this.listLoaded = true;
  }

  async lookup(code: string): Promise<LobbySummary> {
    const c = code.toUpperCase();
    if (!inTauri) {
      const found = SAMPLE_LIST.find((l) => l.code === c);
      if (found) return found;
      if (c === "K7QM2X") return summarise(sampleLobby("guest"));
      throw "No lobby has that code. Check it with your friend and try again.";
    }
    await this.listen();
    return invoke<LobbySummary>("couch_lookup", { code: c });
  }

  /** The latest copy of your lobby (when the lobby screen opens). */
  async refresh() {
    if (!inTauri) {
      if (!this.lobby && !this.ended) {
        const view = sampleView();
        this.got(sampleLobby(view === "closed" ? "guest" : view));
        if (view === "closed") this.ended = { reason: "host-ended" };
      }
      return;
    }
    await this.listen();
    try {
      this.got(await invoke<Lobby | null>("couch_state"));
    } catch (e) {
      this.fail(e);
    }
  }

  // ---- Getting the game onto this PC first ----
  /** Downloads the game if it isn't on this PC yet. True when it's ready. */
  private async ready(id: string): Promise<boolean> {
    if (!inTauri) return true;
    await play.refresh();
    if (play.onPC(id)) return true;
    const g = (await listGames()).find((x) => x.id === id);
    if (!g) {
      this.error = "That game isn't in your library list. Try again in a minute.";
      return false;
    }
    this.busy = `Downloading ${g.title}…`;
    const ok = await play.download(g);
    if (!ok) this.error = play.errors[g.id] || "The download didn't finish. Try again.";
    return ok;
  }

  // ---- Hosting and joining ----
  /** Opens a lobby for a game (downloading it first if needed). True when you're in it. */
  async host(g: Game, open = true): Promise<boolean> {
    this.error = "";
    this.ended = null;
    if (!inTauri) {
      const v = sampleView();
      this.got(sampleLobby(v === "waiting" || v === "dropped" ? v : "host", { id: g.id, title: g.title, console: g.console }));
      return true;
    }
    await this.listen();
    try {
      if (!(await this.ready(g.id))) return false;
      this.busy = "Opening your lobby…";
      // Tauri passes Rust's game_id as gameId; both are sent so either spelling is understood.
      const l = await invoke<Lobby>("couch_host", { root: app.settings.romsFolder, gameId: g.id, game_id: g.id, open, settings: app.consoleSettings(g.console) });
      this.got(l);
      return true;
    } catch (e) {
      this.fail(e);
      return false;
    } finally {
      this.busy = "";
    }
  }

  /** Joins a friend's lobby to play or watch (downloading the game first if needed). */
  async join(code: string, as: "play" | "watch", game: LobbyGame): Promise<boolean> {
    this.error = "";
    this.ended = null;
    this.lastCode = code.toUpperCase();
    this.lastAs = as;
    if (!inTauri) {
      const v = sampleView();
      this.got(v === "lost" ? sampleLobby("lost") : sampleLobby("guest", game, as));
      if (v === "closed") this.ended = { reason: "host-ended" };
      return true;
    }
    await this.listen();
    try {
      if (!(await this.ready(game.id))) return false;
      this.busy = as === "play" ? "Joining as a player…" : "Joining to watch…";
      const l = await invoke<Lobby>("couch_join", { root: app.settings.romsFolder, code: this.lastCode, as, settings: app.consoleSettings(game.console) });
      this.got(l);
      return true;
    } catch (e) {
      this.fail(e);
      return false;
    } finally {
      this.busy = "";
    }
  }

  /** Your link dropped: get back in with the same code (your seat is held for you). */
  async rejoin(): Promise<boolean> {
    const l = this.lobby;
    if (!l || !this.lastCode) return false;
    const as = l.you.role === "watch" ? "watch" : "play";
    if (!inTauri) {
      this.ended = null;
      this.got(sampleLobby("guest", l.game, as === "play" ? "play" : "watch"));
      return true;
    }
    return this.join(this.lastCode, as, l.game);
  }

  // ---- In the lobby ----
  async switchTo(as: "play" | "watch") {
    this.error = "";
    if (!inTauri) return this.sampleSwitch(as);
    try {
      this.got(await invoke<Lobby>("couch_switch", { as }));
    } catch (e) {
      this.fail(e);
    }
  }

  async setOpen(open: boolean) {
    if (!this.lobby) return;
    if (!inTauri) {
      this.lobby.open = open;
      return;
    }
    try {
      this.got(await invoke<Lobby>("couch_set_open", { open }));
    } catch (e) {
      this.fail(e);
    }
  }

  /** Host only: keep holding a dropped player's seat, give it to a watcher, or leave it empty. */
  async seat(n: number, action: "hold" | "give" | "empty", user?: string) {
    if (!inTauri) return this.sampleSeat(n, action, user);
    try {
      this.got(await invoke<Lobby>("couch_seat", { seat: n, action, user: user ?? null }));
    } catch (e) {
      this.fail(e);
    }
  }

  async leave() {
    if (inTauri) {
      try {
        await invoke("couch_leave");
      } catch (e) {
        console.warn("Leaving the lobby", e);
      }
    }
    this.lobby = null;
    this.ended = null;
    this.fullscreen = false;
    this.lastBox = "";
  }

  /** Where the live game box is on screen (CSS pixels of the main window). */
  box(r: { x: number; y: number; width: number; height: number }, force = false) {
    const b = { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
    const key = `${b.x},${b.y},${b.w},${b.h}`;
    if ((key === this.lastBox && !force) || !inTauri) return;
    this.lastBox = key;
    invoke("couch_box", b).catch((e) => console.warn("couch_box", e));
  }

  async setFullscreen(on: boolean) {
    this.fullscreen = on;
    if (!inTauri) return;
    try {
      await invoke("couch_fullscreen", { on });
    } catch (e) {
      this.fullscreen = !on;
      this.fail(e);
    }
  }

  // ---- Sample lobby changes (browser only), so the screens can be tried with a pretend controller ----
  private sampleSwitch(as: "play" | "watch") {
    const l = this.lobby;
    if (!l || l.you.role === "host") return;
    const you = me();
    if (as === "play") {
      const free = l.seats.find((s) => !s.user);
      if (!free) {
        this.error = "All 4 seats are taken. You can watch.";
        return;
      }
      free.user = you;
      free.status = "playing";
      l.watchers = l.watchers.filter((w) => w.id !== you.id);
      l.you = { ...l.you, role: "play", seat: free.n };
    } else {
      const mine = l.seats.find((s) => s.user?.id === you.id);
      if (mine) Object.assign(mine, { user: null, status: "empty", held_left: null });
      l.watchers = [...l.watchers, you];
      l.you = { ...l.you, role: "watch", seat: null };
    }
  }

  private sampleSeat(n: number, action: "hold" | "give" | "empty", user?: string) {
    const l = this.lobby;
    const s = l?.seats.find((x) => x.n === n);
    if (!l || !s) return;
    if (action === "hold") {
      s.held_left = 120;
      this.lobbyAt = Date.now();
    } else if (action === "empty") Object.assign(s, { user: null, status: "empty", held_left: null });
    else {
      const w = l.watchers.find((x) => x.id === user);
      if (!w) return;
      l.watchers = l.watchers.filter((x) => x.id !== user);
      Object.assign(s, { user: w, status: "playing", held_left: null });
    }
  }
}

export const couch = new Couch();

/** Players for sample-only games (Contra III, Super Mario Kart, Super Bomberman) in the browser preview. */
export function playersFor(id: string, games: Game[]): number {
  const g = games.find((x) => x.id === id);
  return maxPlayersOf(g?.players ?? (inTauri ? undefined : SAMPLE_PLAYERS[id]));
}

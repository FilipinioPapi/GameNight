// Downloading and playing games. The Windows side does the work (src-tauri/src/games.rs);
// this file keeps track of what to show: what's on this PC, download progress, what's running.

import type { ConsoleId } from "./consoles";
import type { Game } from "./library";
import { inTauri } from "./settings";
import { app } from "./state.svelte";

interface Entry { console: ConsoleId; file: string; size: number; }

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}

class Play {
  installed = $state<Record<string, Entry>>({});
  progress = $state<Record<string, { done: number; total: number }>>({});
  errors = $state<Record<string, string>>({});
  playing = $state<string | null>(null);
  private listening = false;

  private async listen() {
    if (this.listening || !inTauri) return;
    this.listening = true;
    const { listen } = await import("@tauri-apps/api/event");
    await listen<{ id: string; done: number; total: number }>("download-progress", (e) => {
      if (this.progress[e.payload.id]) this.progress[e.payload.id] = { done: e.payload.done, total: e.payload.total };
    });
    await listen<{ id: string; ok: boolean; silent?: boolean }>("game-closed", (e) => {
      this.playing = null;
      app.stoppedPlaying(e.payload.id);
      if (e.payload.silent) {
        this.errors[e.payload.id] = "The game's sound didn't start on this PC. Game Night will try another way next time you play.";
      }
    });
  }

  /** What's on this PC. Call when a screen that shows it opens. */
  async refresh() {
    if (!inTauri || !app.settings.romsFolder) return;
    await this.listen();
    try {
      this.installed = await invoke<Record<string, Entry>>("installed_games", { root: app.settings.romsFolder });
    } catch (e) {
      console.warn("Couldn't read the games folder", e);
    }
  }

  onPC(id: string) {
    return id in this.installed;
  }

  /** Downloads a game. True when it's ready to play. */
  async download(g: Game): Promise<boolean> {
    if (!inTauri || this.progress[g.id]) return false;
    await this.listen();
    delete this.errors[g.id];
    this.progress[g.id] = { done: 0, total: g.sizeBytes };
    try {
      const entry = await invoke<Entry>("download_game", {
        root: app.settings.romsFolder,
        game: { id: g.id, console: g.console, sizeBytes: g.sizeBytes },
      });
      this.installed[g.id] = entry;
      return true;
    } catch (e) {
      const msg = String(e);
      if (msg === "signed-out") app.signedOut();
      else if (msg !== "stopped") this.errors[g.id] = msg;
      return false;
    } finally {
      delete this.progress[g.id];
    }
  }

  cancel(id: string) {
    if (inTauri) invoke("cancel_download", { id });
  }

  async play(g: Game) {
    delete this.errors[g.id];
    try {
      await invoke("play_game", { root: app.settings.romsFolder, id: g.id, settings: app.consoleSettings(g.console) });
      this.playing = g.id;
      app.startedPlaying(g.id);
    } catch (e) {
      this.errors[g.id] = String(e);
    }
  }

  async remove(id: string) {
    try {
      await invoke("remove_game", { root: app.settings.romsFolder, id });
      delete this.installed[id];
    } catch (e) {
      this.errors[id] = String(e);
    }
  }
}

export const play = new Play();

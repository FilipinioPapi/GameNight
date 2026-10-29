// Settings saved on this PC only (never sent to other players).
// Inside the Windows app they live in Game Night's own settings file; in a plain browser
// (used while building the screens) they fall back to the browser's storage.

import type { ConsoleId } from "./consoles";
import type { PadInput, PadType } from "./pads";

export interface ConsoleSettings {
  screen: "4:3" | "pixel" | "stretch";
  picture: "scanlines" | "sharp" | "smooth";
  rewind: boolean;
  fastForward: boolean;
  showFps: boolean;
}

export interface Settings {
  firstRunDone: boolean;
  romsFolder: string;
  /** Your buttons: console -> pad type -> console button -> your pad's input */
  mappings: Partial<Record<ConsoleId, Partial<Record<PadType, Record<string, PadInput>>>>>;
  presets: Partial<Record<ConsoleId, Partial<Record<PadType, string>>>>;
  consoles: Partial<Record<ConsoleId, ConsoleSettings>>;
}

export const DEFAULT_CONSOLE: ConsoleSettings = { screen: "4:3", picture: "scanlines", rewind: true, fastForward: true, showFps: false };

export const DEFAULTS: Settings = { firstRunDone: false, romsFolder: "", mappings: {}, presets: {}, consoles: {} };

const KEY = "settings";
export const inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

type StoreLike = { get<T>(k: string): Promise<T | undefined>; set(k: string, v: unknown): Promise<void>; save(): Promise<void> };
let store: StoreLike | null = null;

async function tauriStore(): Promise<StoreLike> {
  if (!store) {
    const { load } = await import("@tauri-apps/plugin-store");
    store = (await load("settings.json", { defaults: {}, autoSave: false })) as unknown as StoreLike;
  }
  return store;
}

export async function loadSettings(): Promise<Settings> {
  try {
    const raw = inTauri ? await (await tauriStore()).get<Partial<Settings>>(KEY) : JSON.parse(localStorage.getItem("gn." + KEY) ?? "null");
    return { ...DEFAULTS, ...(raw ?? {}) };
  } catch {
    return { ...DEFAULTS };
  }
}

export async function saveSettings(s: Settings): Promise<void> {
  const plain = JSON.parse(JSON.stringify(s));
  try {
    if (inTauri) {
      const st = await tauriStore();
      await st.set(KEY, plain);
      await st.save();
    } else {
      localStorage.setItem("gn." + KEY, JSON.stringify(plain));
    }
  } catch (e) {
    console.error("Couldn't save settings", e);
  }
}

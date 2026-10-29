// The app's shared state: who's signed in, which screen is showing, saved settings,
// and which controller is plugged in.

import type { ConsoleId } from "./consoles";
import { LAYOUTS } from "./controllers";
import type { PadInput, PadType } from "./pads";
import * as account from "./account";
import { DEFAULT_CONSOLE, DEFAULTS, loadSettings, saveSettings, type ConsoleSettings, type Settings } from "./settings";

export type Route =
  | { name: "login" }
  | { name: "firstrun"; step: 2 | 3 }
  | { name: "menu" }
  | { name: "library"; console: ConsoleId | "all" }
  | { name: "game"; id: string }
  | { name: "settings"; tab: "controllers" | "screen" | "consoles" | "storage" | "account"; console: ConsoleId };

export type { User } from "./account";
type User = account.User;

class AppState {
  route = $state<Route>({ name: "login" });
  history: Route[] = [];
  user = $state<User | null>(null);
  settings = $state<Settings>({ ...DEFAULTS });
  ready = $state(false);
  pad = $state<{ connected: boolean; type: PadType; name: string }>({ connected: false, type: "xbox", name: "" });
  /** The pad type the controller screen is showing (follows the plugged-in pad unless changed). */
  viewPad = $state<PadType>("xbox");

  server = $state("");
  /** Sign-in in progress: "waiting" while the browser is open, or a message if it went wrong. */
  signIn = $state<{ waiting: boolean; error: string }>({ waiting: false, error: "" });

  async init() {
    this.settings = await loadSettings();
    try {
      const st = await account.status();
      this.server = st.server;
      if (st.user) this.signedIn(st.user);
      await account.listen({
        signedIn: (u) => this.signedIn(u),
        failed: (msg) => (this.signIn = { waiting: false, error: msg }),
        signedOut: () => this.signedOut(),
      });
    } catch (e) {
      console.error("Couldn't check sign-in", e);
    }
    this.ready = true;
  }

  /** After Discord says yes (or on start-up, if you signed in before). */
  signedIn(u: User) {
    this.user = u;
    this.signIn = { waiting: false, error: "" };
    this.history = [];
    this.route = this.settings.firstRunDone ? { name: "menu" } : { name: "firstrun", step: 2 };
  }

  signedOut() {
    this.user = null;
    this.history = [];
    this.route = { name: "login" };
  }

  async startSignIn() {
    this.signIn = { waiting: true, error: "" };
    try {
      await account.signIn();
    } catch (e) {
      this.signIn = { waiting: false, error: String(e) };
    }
  }

  async signOut() {
    await account.signOut();
    this.signedOut();
  }

  go(r: Route) {
    this.history.push(this.route);
    this.route = r;
  }
  back() {
    const prev = this.history.pop();
    if (prev) this.route = prev;
    else if (this.user) this.route = { name: "menu" };
  }
  home() {
    this.history = [];
    this.route = { name: "menu" };
  }

  save() {
    void saveSettings(this.settings);
  }

  consoleSettings(id: ConsoleId): ConsoleSettings {
    return { ...DEFAULT_CONSOLE, ...(this.settings.consoles[id] ?? {}) };
  }
  setConsoleSettings(id: ConsoleId, patch: Partial<ConsoleSettings>) {
    this.settings.consoles[id] = { ...this.consoleSettings(id), ...patch };
    this.save();
  }

  presetId(id: ConsoleId, pad: PadType): string {
    return this.settings.presets[id]?.[pad] ?? LAYOUTS[id].presets[0].id;
  }

  /** Your current buttons for a console on a pad type: the chosen preset plus any changes you made. */
  mapping(id: ConsoleId, pad: PadType): Record<string, PadInput> {
    const layout = LAYOUTS[id];
    const preset = layout.presets.find((p) => p.id === this.presetId(id, pad)) ?? layout.presets[0];
    return { ...preset.map, ...(this.settings.mappings[id]?.[pad] ?? {}) };
  }

  setButton(id: ConsoleId, pad: PadType, key: string, input: PadInput) {
    const byPad = (this.settings.mappings[id] ??= {});
    const map = { ...(byPad[pad] ?? {}) };
    // If that input was already used by another button, swap them so nothing is lost.
    const current = this.mapping(id, pad);
    const clash = Object.keys(current).find((k) => k !== key && current[k] === input);
    if (clash) map[clash] = current[key];
    map[key] = input;
    byPad[pad] = map;
    this.save();
  }

  choosePreset(id: ConsoleId, pad: PadType, presetId: string) {
    (this.settings.presets[id] ??= {})[pad] = presetId;
    if (this.settings.mappings[id]) delete this.settings.mappings[id]![pad];
    this.save();
  }

  resetConsole(id: ConsoleId, pad: PadType) {
    if (this.settings.presets[id]) delete this.settings.presets[id]![pad];
    if (this.settings.mappings[id]) delete this.settings.mappings[id]![pad];
    this.save();
  }
}

export const app = new AppState();

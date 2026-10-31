// Every console Game Night knows about, in menu order.
// "coop" = couch co-op with anytime controller handoff (step 2). The rest are solo only for now.

export type ConsoleId =
  | "nes" | "snes" | "gen" | "gb" | "gba" | "arc" | "ps1"
  | "n64" | "gc" | "wii" | "ps2";

export interface ConsoleInfo {
  id: ConsoleId;
  name: string;        // full name, e.g. "Super Nintendo"
  short: string;       // tab / chip label, e.g. "SNES"
  font: string;        // CSS class for the console-styled title font
  navSize: number;     // font size for the short label in side menus
  coop: boolean;
  emulator: string;    // shown to players on the game page
  thumb: string;       // controller diagram (settings pages)
  art: string;         // Jayden's console picture for the Library tab bar (public/consoles/<art>.png)
  icon: string;        // inner SVG for a 24x24 outline icon
}

export const CONSOLES: ConsoleInfo[] = [
  { id: "nes", name: "Nintendo Entertainment System", short: "NES", font: "f-nes", navSize: 10, coop: true,
    emulator: "FCEUmm", thumb: "nes-front", art: "nes",
    icon: '<rect x="2" y="7" width="20" height="10" rx="1.5"/><path d="M6 10v4M4 12h4"/><circle cx="15" cy="12.5" r="1.3"/><circle cx="18.5" cy="12.5" r="1.3"/>' },
  { id: "snes", name: "Super Nintendo", short: "SNES", font: "f-snes", navSize: 17, coop: true,
    emulator: "Snes9x", thumb: "snes-front", art: "snes",
    icon: '<rect x="2" y="7" width="20" height="10" rx="5"/><path d="M7 10v4M5 12h4"/><circle cx="16.5" cy="10.5" r="1"/><circle cx="18.5" cy="12.5" r="1"/><circle cx="16.5" cy="14.5" r="1"/><circle cx="14.5" cy="12.5" r="1"/>' },
  { id: "gen", name: "Sega Genesis", short: "GENESIS", font: "f-gen", navSize: 13, coop: true,
    emulator: "Genesis Plus GX", thumb: "sega-genesis-6button-front", art: "genesis",
    icon: '<path d="M3 10c0-2 1.5-3.5 4-3.5h10c2.5 0 4 1.5 4 3.5v2c0 3.5-2.5 6-5 6-1.5 0-2.5-1.2-4-1.2S9.5 18 8 18c-2.5 0-5-2.5-5-6z"/><path d="M7.5 10v3M6 11.5h3"/><circle cx="14" cy="13" r="1"/><circle cx="16.5" cy="12" r="1"/><circle cx="19" cy="11" r="1"/>' },
  { id: "gb", name: "Game Boy / Game Boy Color", short: "GB / GBC", font: "f-gb", navSize: 14, coop: true,
    emulator: "Gambatte", thumb: "game-boy-color-shared-gb-gbc-front", art: "gb-gbc",
    icon: '<rect x="6" y="2" width="12" height="20" rx="2"/><rect x="8" y="4.5" width="8" height="6.5" rx="0.5"/><path d="M10 14.5v3M8.5 16h3"/><circle cx="15.5" cy="15" r="1"/><circle cx="14" cy="17" r="1"/>' },
  { id: "gba", name: "Game Boy Advance", short: "GBA", font: "f-gb", navSize: 14, coop: true,
    emulator: "mGBA", thumb: "game-boy-advance-front", art: "gba",
    icon: '<rect x="2" y="6" width="20" height="12" rx="4"/><rect x="7.5" y="8" width="9" height="8" rx="0.5"/><path d="M4.5 11v2.5M3.3 12.2h2.4"/><circle cx="19" cy="11" r="0.9"/><circle cx="20" cy="13.2" r="0.9"/>' },
  { id: "arc", name: "Arcade", short: "Arcade", font: "f-arc", navSize: 15, coop: true,
    emulator: "FinalBurn Neo", thumb: "arcade-8button-panel", art: "arcade",
    icon: '<circle cx="12" cy="6" r="3"/><path d="M12 9v6"/><rect x="4" y="15" width="16" height="6" rx="1.5"/><circle cx="16.5" cy="18" r="0.8"/>' },
  { id: "ps1", name: "PlayStation", short: "PS1", font: "f-ps", navSize: 15, coop: true,
    emulator: "PCSX ReARMed", thumb: "ps1-dualshock-front", art: "ps1",
    icon: '<path d="M5 8h14c1.7 0 2.8 1.2 2.6 2.8l-.8 6c-.3 1.9-2.6 2.4-3.6.8L16 15.5H8l-1.2 2.1c-1 1.6-3.3 1.1-3.6-.8l-.8-6C2.2 9.2 3.3 8 5 8z"/><path d="M7 10.5v3M5.5 12h3"/><circle cx="17" cy="10.8" r=".8"/><circle cx="18.8" cy="12.3" r=".8"/><circle cx="17" cy="13.8" r=".8"/><circle cx="15.2" cy="12.3" r=".8"/>' },
  { id: "n64", name: "Nintendo 64", short: "N64", font: "f-n64", navSize: 15, coop: false,
    emulator: "gopher64", thumb: "n64-front", art: "n64",
    icon: '<path d="M3 8h18l-1.5 5H16l-2 8h-4l-2-8H4.5z"/><circle cx="12" cy="11" r="1.2"/>' },
  { id: "gc", name: "GameCube", short: "GameCube", font: "f-gc", navSize: 15, coop: false,
    emulator: "Dolphin", thumb: "gamecube-front", art: "gamecube",
    icon: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>' },
  { id: "wii", name: "Wii", short: "Wii", font: "f-gc", navSize: 15, coop: false,
    emulator: "Dolphin", thumb: "wii-remote-nunchuk-front", art: "wii",
    icon: '<rect x="9" y="2" width="6" height="20" rx="2"/><circle cx="12" cy="6" r="1.2"/><path d="M12 10v2M11 11h2"/>' },
  { id: "ps2", name: "PlayStation 2", short: "PS2", font: "f-ps2", navSize: 12, coop: false,
    emulator: "PCSX2", thumb: "ps2-dualshock2-front", art: "ps2",
    icon: '<path d="M5 8h14c1.7 0 2.8 1.2 2.6 2.8l-.8 6c-.3 1.9-2.6 2.4-3.6.8L16 15.5H8l-1.2 2.1c-1 1.6-3.3 1.1-3.6-.8l-.8-6C2.2 9.2 3.3 8 5 8z"/><path d="M7 10.5v3M5.5 12h3"/><circle cx="17" cy="12.3" r="1.2"/>' },
];

export const consoleById = (id: ConsoleId): ConsoleInfo => {
  const c = CONSOLES.find((x) => x.id === id);
  if (!c) throw new Error(`Unknown console ${id}`);
  return c;
};

/** Pictures for the two tabs that aren't consoles. */
export const TAB_ART = { fav: "favourites", all: "all-games" } as const;

// Which consoles can be played in step 1 (solo). The rest show "coming soon".
export const PLAYABLE_NOW: ConsoleId[] = ["nes", "snes"];

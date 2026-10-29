// Things only the Windows app can do (folders, disk space, quitting).
// In a plain browser these return harmless sample answers so the screens can be built and checked.

import { inTauri } from "./settings";

export interface FolderChoice { path: string; drive: string; label: string; free: number; total: number; recommended: boolean; }

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}

export async function suggestFolders(): Promise<FolderChoice[]> {
  if (inTauri) return invoke<FolderChoice[]>("suggest_folders");
  const GB = 1024 ** 3;
  return [
    { path: "D:\\Games\\Game Night", drive: "D:", label: "Games drive", free: 812 * GB, total: 2048 * GB, recommended: true },
    { path: "C:\\Users\\You\\Game Night", drive: "C:", label: "Windows drive", free: 64 * GB, total: 500 * GB, recommended: false },
  ];
}

/** Opens Windows' folder picker. Returns the chosen folder, or null if cancelled. */
export async function pickFolder(): Promise<string | null> {
  if (!inTauri) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const picked = await open({ directory: true, multiple: false, title: "Where should Game Night keep games?" });
  return typeof picked === "string" ? picked : null;
}

/** The folder Game Night actually uses: always its own "Game Night" folder inside the one you picked. */
export async function gamesFolder(picked: string): Promise<string> {
  if (inTauri) return invoke<string>("games_folder", { picked });
  return /game night$/i.test(picked) ? picked : picked.replace(/[\\/]+$/, "") + "\\Game Night";
}

export async function folderSize(path: string): Promise<number> {
  if (!inTauri || !path) return 0;
  return invoke<number>("folder_size", { path });
}

/** Deletes downloaded games (only Game Night's own console folders). Saves are not stored there. */
export async function clearGames(path: string): Promise<void> {
  if (!inTauri || !path) return;
  await invoke("clear_games", { path });
}

export async function quitApp(): Promise<void> {
  if (!inTauri) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().close();
}

export function formatGB(bytes: number): string {
  const gb = bytes / 1024 ** 3;
  return gb >= 1000 ? `${(gb / 1024).toFixed(gb >= 10240 ? 0 : 1)} TB` : `${Math.round(gb)} GB`;
}

// Updates: the Windows side checks Jayden's update server, verifies the signature and installs.
// This file only keeps track of what to show.

import { inTauri } from "./settings";

export interface UpdateInfo { version: string; notes: string[]; size: number; }
// Steps: asking -> downloading (0-100%) -> checking (100%, signature OK) -> installing (Game Night closes,
// the installer shows its own progress bar and opens Game Night again) -> updated (shown by the new version).
type Phase = "none" | "available" | "asking" | "downloading" | "checking" | "installing" | "updated" | "failed";

const RECHECK_MS = 30 * 60 * 1000;

class Updates {
  info = $state<UpdateInfo | null>(null);
  phase = $state<Phase>("none");
  done = $state(0);
  total = $state(0);
  error = $state("");
  private lastCheck = 0;
  private listening = false;

  /** When the main menu opens. Asks at most every half hour, never while playing. */
  async check() {
    if (!inTauri || this.phase !== "none" || Date.now() - this.lastCheck < RECHECK_MS) return;
    this.lastCheck = Date.now();
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const info = await invoke<UpdateInfo | null>("check_update");
      if (info) {
        this.info = info;
        this.phase = "available";
        // CI's Windows update test only: press Update through this same box, like a person would.
        if (await invoke<boolean>("update_test_mode").catch(() => false)) {
          this.open();
          setTimeout(() => void this.install(), 1500);
        }
      }
    } catch (e) {
      console.warn("Update check failed", e);
    }
  }

  open() {
    if (this.info) this.phase = "asking";
  }
  later() {
    this.phase = "available";
  }

  async install() {
    if (!this.info) return;
    this.phase = "downloading";
    this.done = 0;
    this.total = this.info.size;
    this.error = "";
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      if (!this.listening) {
        const { listen } = await import("@tauri-apps/api/event");
        await listen<{ done: number; total: number }>("update-progress", (e) => {
          this.done = e.payload.done;
          this.total = e.payload.total;
        });
        this.listening = true;
      }
      await invoke("download_update");
      // The download is complete and matches Jayden's signature: show the full bar before moving on.
      this.done = this.total;
      this.phase = "checking";
      await new Promise((r) => setTimeout(r, 1500));
      this.phase = "installing";
      await new Promise((r) => setTimeout(r, 300)); // let the box show the new step first
      await invoke("start_install"); // Game Night closes once the installer is on its way
    } catch (e) {
      this.error = String(e);
      this.phase = "failed";
    }
  }

  /** On start-up: did this start finish an update? Then say so. */
  async cameBack() {
    if (!inTauri) return;
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const v = await invoke<string | null>("just_updated");
      if (v) {
        this.info = { version: v, notes: [], size: 0 };
        this.phase = "updated";
      }
    } catch (e) {
      console.warn("Update check failed", e);
    }
  }

  dismiss() {
    this.phase = "none";
    this.info = null;
  }
}

export const updates = new Updates();

let lastSeen = "";
/** Notes in the update log what the box is showing (step and percent, in tenths), to compare with the download. */
export function reportSeen(step: string, percent: number) {
  if (!inTauri) return;
  const key = `${step} ${Math.floor(percent / 10) * 10}`;
  if (key === lastSeen) return;
  lastSeen = key;
  void import("@tauri-apps/api/core").then(({ invoke }) => invoke("update_seen", { step, percent: Math.round(percent) }).catch(() => {}));
}

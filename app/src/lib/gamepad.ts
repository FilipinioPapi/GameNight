// Watches the plugged-in controller: tells the app what kind it is, lets the menus be
// driven with it (D-pad moves, A picks, B goes back), and catches the next button press
// when you're changing a button.

import { app } from "./state.svelte";
import { play } from "./play.svelte";
import { BUTTON_INDEX, padTypeFromId, type PadInput } from "./pads";
import { inTauri } from "./settings";

/** One controller reading: the same shape whether it came from Windows or the browser. */
type Reading = { id: string; usb?: string; buttons: boolean[]; axes: number[] };

// In the app, Windows tells us about the controller (the web page can't see it there). The app sends a
// "pad" event when it changes, and the menus also ask for it every frame, so a missed event can't
// leave the menus deaf.
type NativePad = { connected: boolean; name: string; id: string; buttons: boolean[]; axes: number[] };
let native: Reading | null = null;
function useNative(p: NativePad) {
  native = p.connected ? { id: p.name || "Controller", usb: p.id, buttons: p.buttons, axes: p.axes } : null;
}

/** A line for Game Night's pads.txt log (the first few only), to see what the menus got. */
let notes = 0;
async function note(text: string) {
  if (!inTauri || notes >= 60) return;
  notes++;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("pad_note", { text });
  } catch {
    // Logging is best-effort.
  }
}

let events = 0;
async function listenNative() {
  const { listen } = await import("@tauri-apps/api/event");
  await listen<NativePad>("pad", (e) => {
    if (events++ === 0) void note("first pad event arrived");
    useNative(e.payload);
  });
  void note("listening for pad events");
}

let asking = false;
let answers = 0;
async function askNative() {
  if (asking) return;
  asking = true;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const p = await invoke<NativePad>("pad_state");
    if (answers++ === 0) void note(`first pad_state answer: ${p.connected ? p.name + " " + p.id : "no controller"}`);
    useNative(p);
  } catch (e) {
    if (answers++ === 0) void note(`pad_state failed: ${String(e).slice(0, 120)}`);
  } finally {
    asking = false;
  }
}

function readPad(): Reading | null {
  if (native) return native;
  const pads = navigator.getGamepads?.() ?? [];
  const pad = pads.find((p) => p && p.connected) ?? null;
  return pad ? { id: pad.id, buttons: pad.buttons.map((b) => b.pressed), axes: [...pad.axes] } : null;
}

type Capture = (input: PadInput) => void;
let capture: Capture | null = null;
let prevButtons: boolean[] = [];
let prevAxes: number[] = [];

/** The next button or stick push goes to this function instead of the menus. */
export function captureNext(fn: Capture | null) {
  capture = fn;
}

type Dir = "up" | "down" | "left" | "right";

/** What the controller can move to: everything clickable that's showing, only inside an open pop-up. */
function focusables(): HTMLElement[] {
  const dialogs = document.querySelectorAll<HTMLElement>("[aria-modal='true']");
  const scope: ParentNode = dialogs.length ? dialogs[dialogs.length - 1] : document;
  return Array.from(scope.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], [tabindex='0'], input:not(:disabled), select:not(:disabled)"))
    .filter((el) => el.offsetParent !== null && el.getClientRects().length > 0);
}

function center(r: DOMRect) {
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}

/** Moves to the nearest thing on screen in that direction (like a games console menu). */
function moveFocus(dir: Dir) {
  const list = focusables();
  if (!list.length) return;
  const current = document.activeElement as HTMLElement | null;
  if (!current || !list.includes(current)) {
    (list.find((el) => el.hasAttribute("data-autofocus")) ?? list[0]).focus();
    return;
  }
  // Left and right on a drop-down list change its choice.
  if (current instanceof HTMLSelectElement && (dir === "left" || dir === "right")) {
    const i = current.selectedIndex + (dir === "right" ? 1 : -1);
    if (i >= 0 && i < current.options.length) {
      current.selectedIndex = i;
      current.dispatchEvent(new Event("change", { bubbles: true }));
    }
    return;
  }
  const from = current.getBoundingClientRect();
  const c = center(from);
  let best: HTMLElement | null = null;
  let bestScore = Infinity;
  for (const el of list) {
    if (el === current) continue;
    const r = el.getBoundingClientRect();
    const t = center(r);
    // Distance along the direction (must be ahead of us) and how far off to the side.
    let along: number, side: number;
    if (dir === "right") { along = r.left - from.right; side = Math.abs(t.y - c.y); if (t.x <= c.x) continue; }
    else if (dir === "left") { along = from.left - r.right; side = Math.abs(t.y - c.y); if (t.x >= c.x) continue; }
    else if (dir === "down") { along = r.top - from.bottom; side = Math.abs(t.x - c.x); if (t.y <= c.y) continue; }
    else { along = from.top - r.bottom; side = Math.abs(t.x - c.x); if (t.y >= c.y) continue; }
    // Only things roughly in that direction: side by side with us, or within a cone ahead.
    const overlaps = dir === "left" || dir === "right"
      ? r.top < from.bottom && r.bottom > from.top
      : r.left < from.right && r.right > from.left;
    if (!overlaps && side > Math.max(along, 0) * 1.5) continue;
    const score = Math.max(along, 0) + side * 2;
    if (score < bestScore) {
      bestScore = score;
      best = el;
    }
  }
  if (best) {
    best.focus();
    best.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
}

/** LB / RB: step through a row of tabs (consoles, settings pages) and open it. */
function switchTab(step: 1 | -1) {
  const tabs = Array.from(document.querySelectorAll<HTMLElement>("[data-tab]")).filter((el) => el.offsetParent !== null);
  if (!tabs.length) return;
  let i = tabs.findIndex((el) => el.classList.contains("on"));
  if (i < 0) i = 0;
  const next = tabs[(i + step + tabs.length) % tabs.length];
  next.click();
  next.focus();
  next.scrollIntoView({ block: "nearest", inline: "nearest" });
}

/** The right stick scrolls whatever list you're in. */
function scrollBy(dy: number) {
  let el: HTMLElement | null = document.activeElement as HTMLElement | null;
  while (el && el !== document.body) {
    const st = getComputedStyle(el);
    if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight) break;
    el = el.parentElement;
  }
  (el && el !== document.body ? el : document.querySelector<HTMLElement>(".scroll, main"))?.scrollBy({ top: dy });
}

const DIRS: Record<number, Dir> = { 12: "up", 13: "down", 14: "left", 15: "right" };

function usePadLook() {
  document.body.classList.add("pad-mode");
}

function describe(el: Element | null) {
  if (!el) return "nothing";
  const text = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 30);
  return `${el.tagName.toLowerCase()} "${text}"`;
}

function onPress(index: number) {
  usePadLook();
  void note(`button ${index} pressed; focused: ${describe(document.activeElement)}; page has focus: ${document.hasFocus()}`);
  const input = BUTTON_INDEX[index] ?? (index >= 12 && index <= 15 ? "dpad" : undefined);
  if (capture && input) {
    const fn = capture;
    capture = null;
    fn(input);
    return;
  }
  if (DIRS[index]) moveFocus(DIRS[index]);
  else if (index === 0) {
    const el = document.activeElement as HTMLElement | null;
    if (el instanceof HTMLInputElement && el.type !== "checkbox") el.select();
    else el?.click();
  } else if (index === 1) {
    const el = document.activeElement as HTMLElement | null;
    if (el instanceof HTMLInputElement) el.blur();
    else app.back();
  } else if (index === 3) document.querySelector<HTMLElement>("[data-search]")?.focus();
  else if (index === 4) switchTab(-1);
  else if (index === 5) switchTab(1);
}

// Holding a direction repeats it, like a console menu.
let held: { key: string; since: number; last: number } | null = null;
function repeat(key: string, active: boolean, now: number, fire: () => void) {
  if (!active) {
    if (held?.key === key) held = null;
    return;
  }
  if (!held || held.key !== key) {
    held = { key, since: now, last: now };
    return; // the first press is handled as a normal press
  }
  if (now - held.since > 380 && now - held.last > 110) {
    held.last = now;
    fire();
  }
}

function tick() {
  if (inTauri) void askNative();
  const pad = readPad();
  // While a game is running, the controller belongs to the game.
  if (!pad || play.playing) {
    if (!pad && app.pad.connected) app.pad = { ...app.pad, connected: false };
    requestAnimationFrame(tick);
    return;
  }
  if (!app.pad.connected || app.pad.name !== pad.id || app.pad.usb !== (pad.usb ?? "")) {
    const type = padTypeFromId(`${pad.id} ${pad.usb ?? ""}`);
    app.pad = { connected: true, type, name: pad.id, usb: pad.usb ?? "" };
    app.viewPad = type;
  }
  const now = performance.now();
  pad.buttons.forEach((down, i) => {
    if (down && !prevButtons[i]) onPress(i);
    if (DIRS[i] && !capture) repeat("b" + i, down, now, () => moveFocus(DIRS[i]));
    prevButtons[i] = down;
  });
  // Left stick: a strong push counts as a direction press (for changing a stick row, and menus).
  const [lx = 0, ly = 0, , ry = 0] = pad.axes;
  const stickDir: Dir | null = Math.abs(lx) > 0.7 || Math.abs(ly) > 0.7
    ? (Math.abs(lx) > Math.abs(ly) ? (lx > 0 ? "right" : "left") : ly > 0 ? "down" : "up")
    : null;
  const wasStrong = Math.abs(prevAxes[0] ?? 0) > 0.7 || Math.abs(prevAxes[1] ?? 0) > 0.7;
  if (stickDir && !wasStrong) {
    usePadLook();
    if (capture) {
      const fn = capture;
      capture = null;
      fn("ls");
    } else moveFocus(stickDir);
  } else if (stickDir && !capture) {
    repeat("ls", true, now, () => moveFocus(stickDir));
  } else repeat("ls", false, now, () => {});
  if (capture && pad.axes.slice(2, 4).some((a, j) => Math.abs(a) > 0.7 && Math.abs(prevAxes[j + 2] ?? 0) <= 0.7)) {
    const fn = capture;
    capture = null;
    fn("rs");
  } else if (Math.abs(ry) > 0.3) {
    scrollBy(ry * 18);
  }
  prevAxes = [...pad.axes];
  requestAnimationFrame(tick);
}

// Using the mouse hides the controller highlight again.
if (typeof window !== "undefined") {
  window.addEventListener("mousemove", () => document.body.classList.remove("pad-mode"), { passive: true });
}

export function startGamepad() {
  if (inTauri) {
    void note(`menus started (${navigator.userAgent.slice(0, 80)})`);
    listenNative().catch((e) => void note(`couldn't listen for pad events: ${String(e).slice(0, 120)}`));
  }
  requestAnimationFrame(tick);
  // If the screen stops drawing frames, this shows it in the log.
  if (inTauri) setTimeout(() => void note(`frames after 5 s: ${frames}`), 5000);
}

let frames = 0;
function countFrame() {
  frames++;
  requestAnimationFrame(countFrame);
}
if (typeof window !== "undefined") requestAnimationFrame(countFrame);

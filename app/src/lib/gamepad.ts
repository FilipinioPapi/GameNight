// Watches the plugged-in controller: tells the app what kind it is, lets the menus be
// driven with it (D-pad moves, A picks, B goes back), and catches the next button press
// when you're changing a button.

import { app } from "./state.svelte";
import { play } from "./play.svelte";
import { BUTTON_INDEX, padTypeFromId, type PadInput } from "./pads";
import { inTauri } from "./settings";
import { bumpRing, keepInView, startFocusRing } from "./focusring";

/** One controller reading: the same shape whether it came from Windows or the browser. */
type Reading = { id: string; usb?: string; buttons: boolean[]; axes: number[] };

// In the app, Windows tells us about the controller (the web page can't see it there). The app sends a
// "pad" event when it changes, and the menus also ask for it every frame, so a missed event can't
// leave the menus deaf.
// Each reading is numbered, so an older one arriving late (the event and the every-frame answer travel
// separately) can't undo a newer one and make a single press count twice.
type NativePad = { connected: boolean; name: string; id: string; buttons: boolean[]; axes: number[]; seq?: number };
let native: Reading | null = null;
let newest = 0;
let stale = 0;
function useNative(p: NativePad) {
  if (typeof p.seq === "number") {
    if (p.seq < newest) {
      if (stale++ < 5) void note(`ignored an older pad reading (${p.seq} after ${newest})`);
      return;
    }
    newest = p.seq;
  }
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
let stickHeld: Dir | null = null;

/** The next button or stick push goes to this function instead of the menus. */
export function captureNext(fn: Capture | null) {
  capture = fn;
}

/** A screen can take some buttons for itself (the Library: Y favourites, X searches). True = handled. */
type ScreenButtons = (input: PadInput) => boolean;
let screenButtons: ScreenButtons | null = null;
export function useScreenButtons(fn: ScreenButtons | null) {
  screenButtons = fn;
}

export type Dir = "up" | "down" | "left" | "right";

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

/**
 * Which part of the screen an element belongs to: a pop-up, a scrolling list (the games, the console
 * tabs, a settings page) or the screen itself. Left / right stay inside it, so the end of a row of games
 * doesn't jump up to a console tab.
 */
function navGroup(el: HTMLElement): Element {
  let p = el.parentElement;
  while (p && p !== document.body) {
    if (p.hasAttribute("data-nav-group") || p.getAttribute("aria-modal") === "true") return p;
    const st = getComputedStyle(p);
    if (/(auto|scroll)/.test(st.overflowY) || /(auto|scroll)/.test(st.overflowX)) return p;
    p = p.parentElement;
  }
  return document.body;
}

// Going up and down keeps your column, like a console menu (from the 5th game in a row you land on the 5th).
let column: { x: number; from: HTMLElement } | null = null;

/** Moves to the next thing in that direction, like a games console menu. The arrow keys use it too. */
export function moveFocus(dir: Dir) {
  const list = focusables();
  if (!list.length) return;
  const current = document.activeElement as HTMLElement | null;
  if (!current || !list.includes(current)) {
    goTo(list.find((el) => el.hasAttribute("data-autofocus")) ?? list[0]);
    return;
  }
  // Left and right on a drop-down list change its choice.
  if (current instanceof HTMLSelectElement && (dir === "left" || dir === "right")) {
    const i = current.selectedIndex + (dir === "right" ? 1 : -1);
    if (i >= 0 && i < current.options.length) {
      current.selectedIndex = i;
      current.dispatchEvent(new Event("change", { bubbles: true }));
    } else bumpRing(dir);
    return;
  }
  const from = current.getBoundingClientRect();
  const c = center(from);
  const ahead = (r: DOMRect) => {
    const t = center(r);
    return dir === "right" ? t.x > c.x : dir === "left" ? t.x < c.x : dir === "down" ? t.y > c.y : t.y < c.y;
  };
  const others = list.filter((el) => el !== current).map((el) => ({ el, r: el.getBoundingClientRect() })).filter((o) => ahead(o.r));
  const best = dir === "left" || dir === "right" ? sideways(dir, current, from, others) : upDown(dir, current, from, others);
  if (!best) {
    bumpRing(dir);
    return;
  }
  void note(`move ${dir}: ${describe(current)} -> ${describe(best)}`);
  // Moving along a row of tabs (consoles) shows that tab straight away, like a console's tab bar.
  const tabRow = (dir === "left" || dir === "right") && current.hasAttribute("data-tab") && best.hasAttribute("data-tab");
  goTo(best);
  if (tabRow && !best.classList.contains("on")) {
    best.click();
    slideContent(dir === "right" ? 1 : -1);
  }
}

function sideways(dir: Dir, current: HTMLElement, from: DOMRect, others: { el: HTMLElement; r: DOMRect }[]) {
  column = null;
  const c = center(from);
  const sameRow = (r: DOMRect) => r.top < from.bottom && r.bottom > from.top;
  const group = navGroup(current);
  // Same list, same row: the nearest one.
  const inRow = others.filter((o) => navGroup(o.el) === group && sameRow(o.r));
  if (inRow.length) return nearestBy(inRow, (o) => Math.abs(center(o.r).x - c.x));
  // Nothing more in this row of this list: only step across to a list that sits beside it (a settings
  // page's side menu), never up or down to another row.
  const clearlyAhead = (r: DOMRect) => (dir === "right" ? r.left >= from.right - 1 : r.right <= from.left + 1);
  const body = document.body;
  if (group !== body && others.some((o) => navGroup(o.el) === group && clearlyAhead(o.r))) return null;
  const beside = others.filter((o) => {
    const g = navGroup(o.el);
    if ((g === group && g !== body) || !clearlyAhead(o.r)) return false;
    const gr = g === body ? o.r : g.getBoundingClientRect();
    return gr.top < from.bottom && gr.bottom > from.top;
  });
  return nearestBy(beside, (o) => {
    const along = dir === "right" ? o.r.left - from.right : from.left - o.r.right;
    return Math.max(along, 0) + Math.abs(center(o.r).y - c.y) * 2;
  });
}

function upDown(dir: Dir, current: HTMLElement, from: DOMRect, others: { el: HTMLElement; r: DOMRect }[]) {
  const c = center(from);
  const along = (r: DOMRect) => (dir === "down" ? r.top - from.bottom : from.top - r.bottom);
  // Only things roughly below / above: overlapping our column, or within a cone ahead.
  const inCone = others.filter((o) => {
    const overlaps = o.r.left < from.right && o.r.right > from.left;
    return overlaps || Math.abs(center(o.r).x - c.x) <= Math.max(along(o.r), 0) * 1.5;
  });
  // Nothing straight ahead, but the list carries on (a short last row of games): go to that row anyway.
  const group = navGroup(current);
  const pool = inCone.length ? inCone : others.filter((o) => navGroup(o.el) === group);
  const first = nearestBy(pool, (o) => Math.max(along(o.r), 0) + Math.abs(center(o.r).x - c.x) * 0.01);
  if (!first) return null;
  // That's the next row: everything level with it.
  const f = first.getBoundingClientRect();
  const row = others.filter((o) => o.r.top < f.bottom && o.r.bottom > f.top);
  // Up into a row of tabs lands on the one that's showing.
  const shown = row.find((o) => o.el.hasAttribute("data-tab") && o.el.classList.contains("on"));
  if (shown && row.every((o) => o.el.hasAttribute("data-tab"))) return shown.el;
  const x = column && column.from === current ? column.x : c.x;
  const best = nearestBy(row, (o) => Math.abs(center(o.r).x - x));
  if (best) column = { x, from: best };
  return best;
}

function nearestBy<T extends { el: HTMLElement }>(items: T[], score: (o: T) => number): HTMLElement | null {
  let best: HTMLElement | null = null;
  let bestScore = Infinity;
  for (const o of items) {
    const s = score(o);
    if (s < bestScore) {
      bestScore = s;
      best = o.el;
    }
  }
  return best;
}

/** Highlights an element without the page jumping; the list then eases along to show it. */
function goTo(el: HTMLElement) {
  el.focus({ preventScroll: true });
  keepInView(el);
}

/** The games for a new console slide in from the side they're on. */
function slideContent(step: 1 | -1) {
  if (typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      const box = document.querySelector<HTMLElement>(".content");
      box?.animate(
        [{ opacity: 0, transform: `translateX(${step * 32}px)` }, { opacity: 1, transform: "none" }],
        { duration: 200, easing: "cubic-bezier(.2,.8,.2,1)" },
      );
    }),
  );
}

/** LB / RB: step through a row of tabs (consoles, settings pages) and open it. */
function switchTab(step: 1 | -1) {
  const tabs = Array.from(document.querySelectorAll<HTMLElement>("[data-tab]")).filter((el) => el.offsetParent !== null);
  if (!tabs.length) return;
  let i = tabs.findIndex((el) => el.classList.contains("on"));
  if (i < 0) i = 0;
  const next = tabs[(i + step + tabs.length) % tabs.length];
  const wasInList = !(document.activeElement instanceof HTMLElement && document.activeElement.hasAttribute("data-tab"));
  next.click();
  goTo(next);
  slideContent(step);
  // If you were in the games, stay in the games (on the first one of the new console).
  if (wasInList) {
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        const first = document.querySelector<HTMLElement>("[data-game]");
        if (first) goTo(first);
      }),
    );
  }
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
  if (input && input !== "dpad" && screenButtons?.(input)) return;
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

// Holding a direction repeats it, like a console menu: a short pause, then a steady repeat that
// speeds up a little.
let held: { key: string; since: number; last: number; count: number } | null = null;
function repeat(key: string, active: boolean, now: number, fire: () => void) {
  if (!active) {
    if (held?.key === key) held = null;
    return;
  }
  if (!held || held.key !== key) {
    held = { key, since: now, last: now, count: 0 };
    return; // the first press is handled as a normal press
  }
  const gap = Math.max(85, 140 - held.count * 9);
  if (now - held.since > 340 && now - held.last > gap) {
    held.last = now;
    held.count++;
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
  // Left stick: a strong push counts as a direction press (for changing a stick row, and menus). It has
  // to come back near the middle before it counts again, so a stick resting near the edge can't flicker.
  const [lx = 0, ly = 0, , ry = 0] = pad.axes;
  const push = Math.max(Math.abs(lx), Math.abs(ly));
  let stickDir: Dir | null = stickHeld;
  if (push > 0.7) stickDir = Math.abs(lx) > Math.abs(ly) ? (lx > 0 ? "right" : "left") : ly > 0 ? "down" : "up";
  else if (push < 0.45) stickDir = null;
  if (stickDir && stickDir !== stickHeld) {
    usePadLook();
    if (capture) {
      const fn = capture;
      capture = null;
      fn("ls");
    } else moveFocus(stickDir);
    repeat("ls", false, now, () => {});
    repeat("ls", true, now, () => {});
  } else if (stickDir && !capture) {
    const d = stickDir;
    repeat("ls", true, now, () => moveFocus(d));
  } else repeat("ls", false, now, () => {});
  stickHeld = stickDir;
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
  startFocusRing();
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

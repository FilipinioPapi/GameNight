// Watches the plugged-in controller: tells the app what kind it is, lets the menus be
// driven with it (D-pad moves, A picks, B goes back), and catches the next button press
// when you're changing a button.

import { app } from "./state.svelte";
import { BUTTON_INDEX, padTypeFromId, type PadInput } from "./pads";

type Capture = (input: PadInput) => void;
let capture: Capture | null = null;
let prevButtons: boolean[] = [];
let prevAxes: number[] = [];
let lastMove = 0;

/** The next button or stick push goes to this function instead of the menus. */
export function captureNext(fn: Capture | null) {
  capture = fn;
}

const focusables = () =>
  Array.from(document.querySelectorAll<HTMLElement>("button:not(:disabled), [tabindex='0'], input, select"))
    .filter((el) => el.offsetParent !== null);

function moveFocus(dir: 1 | -1) {
  const list = focusables();
  if (!list.length) return;
  const i = list.indexOf(document.activeElement as HTMLElement);
  const next = list[(i + dir + list.length) % list.length] ?? list[0];
  next.focus();
  next.scrollIntoView({ block: "nearest" });
}

function onPress(index: number) {
  const input = BUTTON_INDEX[index] ?? (index >= 12 && index <= 15 ? "dpad" : undefined);
  if (capture && input) {
    const fn = capture;
    capture = null;
    fn(input);
    return;
  }
  if (index === 0) (document.activeElement as HTMLElement | null)?.click();
  else if (index === 1) app.back();
  else if (index === 12 || index === 14) moveFocus(-1);
  else if (index === 13 || index === 15) moveFocus(1);
}

function tick() {
  const pads = navigator.getGamepads?.() ?? [];
  const pad = pads.find((p) => p && p.connected) ?? null;
  if (!pad) {
    if (app.pad.connected) app.pad = { ...app.pad, connected: false };
  } else {
    if (!app.pad.connected || app.pad.name !== pad.id) {
      const type = padTypeFromId(pad.id);
      app.pad = { connected: true, type, name: pad.id };
      app.viewPad = type;
    }
    pad.buttons.forEach((b, i) => {
      const down = b.pressed;
      if (down && !prevButtons[i]) onPress(i);
      prevButtons[i] = down;
    });
    // Sticks: a strong push counts as a direction press (for changing a stick row, and menus).
    const now = performance.now();
    pad.axes.forEach((a, i) => {
      const strong = Math.abs(a) > 0.7;
      if (strong && Math.abs(prevAxes[i] ?? 0) <= 0.7) {
        if (capture) {
          const fn = capture;
          capture = null;
          fn(i < 2 ? "ls" : "rs");
        } else if (now - lastMove > 180) {
          moveFocus(a > 0 ? 1 : -1);
          lastMove = now;
        }
      }
      prevAxes[i] = a;
    });
  }
  requestAnimationFrame(tick);
}

export function startGamepad() {
  requestAnimationFrame(tick);
}

// Controller setup data for each console: which diagrams to show, where each label tag sits
// on them (for the hover glow), the console's buttons, and the default layouts.
//
// Diagrams come from Jayden's approved pack. Never recolour, crop, mirror or redraw them:
// the glow is a separate box drawn on top, at the measured position of each label tag.

import type { ConsoleId } from "./consoles";
import type { PadInput } from "./pads";

/** A label tag on a diagram, in percent of the image: left, top, width, height. */
export interface Spot { key: string; l: number; t: number; w: number; h: number; }

export interface DiagramView {
  img: string;             // file name in /ctl without extension
  label: string;           // small caption, e.g. "FRONT"
  width: number;           // percent of the left column the picture takes
  ratio: string;           // image width / height
  tag: "rounded" | "pill"; // shape of the label tags in this picture
  spots: Spot[];
}

export interface ConsoleButton {
  key: string;
  label: string;
  hint?: string;           // small grey note, e.g. "(jump)"
  alsoStick?: boolean;     // directions: the left stick also works
}

export interface ControllerLayout {
  above: DiagramView[];    // top / shoulder / mode views
  front: DiagramView;
  below: DiagramView[];    // back views
  buttons: ConsoleButton[];
  extras: ConsoleButton[]; // Game Night extras (turbo, rewind, fast forward)
  presets: { id: string; name: string; map: Record<string, PadInput> }[];
  note?: string;
}

const v = (img: string, label: string, width: number, ratio: string, tag: DiagramView["tag"], spots: [string, number, number, number, number][] = []): DiagramView =>
  ({ img, label, width, ratio, tag, spots: spots.map(([key, l, t, w, h]) => ({ key, l, t, w, h })) });

const b = (key: string, label: string, hint?: string, alsoStick = false): ConsoleButton => ({ key, label, hint, alsoStick });

const REWIND = [b("rewind", "Rewind", "(solo)"), b("ff", "Fast forward", "(solo)")];
const REWIND_MAP: Record<string, PadInput> = { rewind: "lt", ff: "rt" };

export const LAYOUTS: Record<ConsoleId, ControllerLayout> = {
  nes: {
    above: [],
    front: v("nes-front", "FRONT", 100, "1200/600", "rounded", [
      ["dpad", 20.17, 28.33, 6.92, 8.0], ["dpad", 19.83, 77.67, 8.0, 8.0], ["dpad", 4.83, 53.5, 7.42, 8.0], ["dpad", 32.0, 53.5, 6.75, 8.0],
      ["select", 38.0, 77.67, 8.67, 8.0], ["start", 50.58, 77.67, 8.0, 8.0], ["b", 65.08, 78.0, 6.08, 7.83], ["a", 76.25, 78.0, 6.0, 7.83],
    ]),
    below: [],
    buttons: [b("dpad", "D-pad", undefined, true), b("b", "B", "(run, shoot)"), b("a", "A", "(jump)"), b("select", "Select"), b("start", "Start")],
    extras: [b("turbo_b", "Turbo B", "holds B down fast"), ...REWIND],
    presets: [
      { id: "spot", name: "Same spot as original", map: { dpad: "dpad", b: "a", a: "b", select: "view", start: "menu", turbo_b: "y", ...REWIND_MAP } },
      { id: "letter", name: "Same letter", map: { dpad: "dpad", b: "b", a: "a", select: "view", start: "menu", turbo_b: "y", ...REWIND_MAP } },
    ],
  },
  snes: {
    above: [v("snes-shoulders", "TOP", 78, "1200/400", "rounded", [["l", 10.92, 1.25, 9.33, 15.0], ["r", 79.83, 1.25, 9.33, 15.0]])],
    front: v("snes-front", "FRONT", 100, "1200/600", "rounded", [
      ["dpad", 17.0, 18.5, 11.0, 7.33], ["dpad", 1.08, 45.33, 11.5, 7.17], ["dpad", 33.08, 45.17, 12.25, 7.17], ["dpad", 16.42, 71.83, 13.08, 7.0],
      ["x", 76.08, 17.67, 5.67, 7.17], ["y", 63.92, 36.67, 5.67, 7.17], ["a", 93.42, 47.0, 5.58, 7.17], ["b", 76.08, 75.0, 5.67, 7.17],
      ["select", 37.92, 78.67, 8.5, 6.67], ["start", 52.58, 78.67, 8.33, 6.67],
    ]),
    below: [],
    buttons: [b("dpad", "D-pad", undefined, true), b("b", "B"), b("a", "A"), b("y", "Y"), b("x", "X"), b("l", "L"), b("r", "R"), b("select", "Select"), b("start", "Start")],
    extras: REWIND,
    presets: [
      { id: "spot", name: "Same spot as original", map: { dpad: "dpad", b: "a", a: "b", y: "x", x: "y", l: "lb", r: "rb", select: "view", start: "menu", ...REWIND_MAP } },
      { id: "letter", name: "Same letter", map: { dpad: "dpad", b: "b", a: "a", y: "y", x: "x", l: "lb", r: "rb", select: "view", start: "menu", ...REWIND_MAP } },
    ],
  },
  gen: {
    above: [v("sega-genesis-6button-mode", "TOP", 78, "1200/400", "rounded")],
    front: v("sega-genesis-6button-front", "FRONT", 92, "1200/800", "rounded"),
    below: [],
    buttons: [b("dpad", "D-pad", undefined, true), b("a", "A"), b("b", "B"), b("c", "C"), b("x", "X"), b("y", "Y"), b("z", "Z"), b("start", "Start"), b("mode", "Mode")],
    extras: REWIND,
    presets: [{ id: "spot", name: "Same spot as original", map: { dpad: "dpad", a: "x", b: "a", c: "b", x: "lb", y: "y", z: "rb", start: "menu", mode: "view", ...REWIND_MAP } }],
  },
  gb: {
    above: [],
    front: v("game-boy-color-shared-gb-gbc-front", "FRONT", 52, "800/1200", "rounded"),
    below: [],
    buttons: [b("dpad", "D-pad", undefined, true), b("b", "B"), b("a", "A"), b("select", "Select"), b("start", "Start")],
    extras: REWIND,
    presets: [
      { id: "spot", name: "Same spot as original", map: { dpad: "dpad", b: "a", a: "b", select: "view", start: "menu", ...REWIND_MAP } },
      { id: "letter", name: "Same letter", map: { dpad: "dpad", b: "b", a: "a", select: "view", start: "menu", ...REWIND_MAP } },
    ],
  },
  gba: {
    above: [],
    front: v("game-boy-advance-front", "FRONT", 92, "1200/800", "rounded"),
    below: [],
    buttons: [b("dpad", "D-pad", undefined, true), b("b", "B"), b("a", "A"), b("l", "L"), b("r", "R"), b("select", "Select"), b("start", "Start")],
    extras: REWIND,
    presets: [
      { id: "spot", name: "Same spot as original", map: { dpad: "dpad", b: "a", a: "b", l: "lb", r: "rb", select: "view", start: "menu", ...REWIND_MAP } },
      { id: "letter", name: "Same letter", map: { dpad: "dpad", b: "b", a: "a", l: "lb", r: "rb", select: "view", start: "menu", ...REWIND_MAP } },
    ],
  },
  arc: {
    above: [],
    front: v("arcade-8button-panel", "PANEL", 100, "1200/600", "rounded"),
    below: [],
    buttons: [b("stick", "Joystick", undefined, true), b("1", "Button 1"), b("2", "Button 2"), b("3", "Button 3"), b("4", "Button 4"),
      b("5", "Button 5"), b("6", "Button 6"), b("7", "Button 7"), b("8", "Button 8"), b("coin", "Insert coin"), b("start", "Start")],
    extras: REWIND,
    presets: [{ id: "spot", name: "Same spot as original", map: { stick: "dpad", 1: "x", 2: "y", 3: "rb", 4: "lb", 5: "a", 6: "b", 7: "rt", 8: "lt", coin: "view", start: "menu", rewind: "l3", ff: "r3" } }],
    note: "Button numbers are the panel's, not fixed game controls. Each game uses them its own way.",
  },
  ps1: {
    above: [v("ps1-dualshock-shoulders", "TOP", 78, "1200/400", "rounded")],
    front: v("ps1-dualshock-front", "FRONT", 92, "1200/800", "rounded"),
    below: [],
    buttons: [b("dpad", "D-pad"), b("ls", "Left stick"), b("rs", "Right stick"), b("cross", "Cross"), b("circle", "Circle"), b("square", "Square"), b("triangle", "Triangle"),
      b("l1", "L1"), b("r1", "R1"), b("l2", "L2"), b("r2", "R2"), b("select", "Select"), b("start", "Start")],
    extras: [b("rewind", "Rewind", "(solo)"), b("ff", "Fast forward", "(solo)")],
    presets: [{ id: "spot", name: "Same spot as original", map: { dpad: "dpad", ls: "ls", rs: "rs", cross: "a", circle: "b", square: "x", triangle: "y", l1: "lb", r1: "rb", l2: "lt", r2: "rt", select: "view", start: "menu", rewind: "l3", ff: "r3" } }],
  },
  n64: {
    above: [],
    front: v("n64-front", "FRONT", 92, "1200/800", "pill", [
      ["l", 13.92, 4.5, 10.17, 6.12], ["r", 76.0, 4.5, 10.25, 6.12], ["dpad", 4.42, 35.5, 11.17, 6.12], ["start", 40.0, 27.0, 10.58, 6.12],
      ["b", 56.25, 30.75, 8.58, 5.88], ["c", 85.0, 31.12, 14.25, 6.12], ["a", 80.0, 52.5, 10.08, 6.12], ["stick", 27.33, 72.75, 17.83, 6.12],
    ]),
    below: [v("n64-rear-z", "BACK", 62, "1200/800", "pill", [["z", 62.33, 34.62, 9.83, 6.88]])],
    buttons: [b("stick", "Control stick"), b("dpad", "D-pad"), b("a", "A"), b("b", "B"), b("c", "C buttons"), b("z", "Z", "(on the back)"), b("l", "L"), b("r", "R"), b("start", "Start")],
    extras: [],
    presets: [
      { id: "spot", name: "Same spot as original", map: { stick: "ls", dpad: "dpad", a: "a", b: "x", c: "rs", z: "lt", l: "lb", r: "rb", start: "menu" } },
      { id: "letter", name: "Same letter", map: { stick: "ls", dpad: "dpad", a: "a", b: "b", c: "rs", z: "lt", l: "lb", r: "rb", start: "menu" } },
    ],
  },
  gc: {
    above: [v("gamecube-shoulders", "TOP", 78, "1200/600", "rounded")],
    front: v("gamecube-front", "FRONT", 92, "1200/800", "rounded"),
    below: [],
    buttons: [b("stick", "Control stick"), b("cstick", "C stick"), b("dpad", "D-pad"), b("a", "A"), b("b", "B"), b("x", "X"), b("y", "Y"), b("z", "Z"), b("l", "L"), b("r", "R"), b("start", "Start / Pause")],
    extras: [],
    presets: [{ id: "spot", name: "Same spot as original", map: { stick: "ls", cstick: "rs", dpad: "dpad", a: "a", b: "x", x: "b", y: "y", z: "rb", l: "lt", r: "rt", start: "menu" } }],
  },
  wii: {
    above: [],
    front: v("wii-remote-nunchuk-front", "FRONT", 60, "1125/1200", "rounded"),
    below: [v("wii-remote-nunchuk-rear", "BACK", 70, "1200/800", "rounded")],
    buttons: [b("stick", "Nunchuk stick"), b("dpad", "D-pad"), b("a", "A"), b("b", "B", "(trigger)"), b("c", "C"), b("z", "Z"), b("1", "1"), b("2", "2"), b("plus", "+"), b("minus", "−"), b("shake", "Shake")],
    extras: [],
    presets: [{ id: "spot", name: "Same spot as original", map: { stick: "ls", dpad: "dpad", a: "a", b: "rt", c: "lb", z: "lt", 1: "x", 2: "y", plus: "menu", minus: "view", shake: "rb" } }],
    note: "This is the Wii Remote + Nunchuk setup. Games that use the Classic Controller Pro get their own setup later.",
  },
  ps2: {
    above: [v("ps2-dualshock2-shoulders", "TOP", 78, "1200/480", "rounded")],
    front: v("ps2-dualshock2-front", "FRONT", 92, "1200/800", "rounded"),
    below: [],
    buttons: [b("dpad", "D-pad"), b("ls", "Left stick"), b("rs", "Right stick"), b("cross", "Cross"), b("circle", "Circle"), b("square", "Square"), b("triangle", "Triangle"),
      b("l1", "L1"), b("r1", "R1"), b("l2", "L2"), b("r2", "R2"), b("l3", "L3"), b("r3", "R3"), b("select", "Select"), b("start", "Start")],
    extras: [],
    presets: [{ id: "spot", name: "Same spot as original", map: { dpad: "dpad", ls: "ls", rs: "rs", cross: "a", circle: "b", square: "x", triangle: "y", l1: "lb", r1: "rb", l2: "lt", r2: "rt", l3: "l3", r3: "r3", select: "view", start: "menu" } }],
  },
};

/** Inputs that are directions rather than buttons: only these can be given to a d-pad or stick row. */
export const DIRECTION_INPUTS: PadInput[] = ["dpad", "ls", "rs"];
export const isDirectionRow = (key: string) => ["dpad", "stick", "ls", "rs", "cstick", "c"].includes(key);

// The player's own controller (Xbox or DualSense) and its buttons.
// Button numbers follow the browser's "standard gamepad" layout, which both pads use on Windows.

export type PadType = "xbox" | "dualsense";

export type PadInput =
  | "a" | "b" | "x" | "y"          // face buttons (Xbox letters; DualSense cross/circle/square/triangle)
  | "lb" | "rb" | "lt" | "rt"
  | "view" | "menu" | "l3" | "r3" | "home"
  | "dpad" | "ls" | "rs";          // whole d-pad / sticks (used for directions)

export const PAD_NAME: Record<PadType, string> = { xbox: "Xbox", dualsense: "DualSense" };

// Standard gamepad button index -> our name. Directions are handled separately.
export const BUTTON_INDEX: Partial<Record<number, PadInput>> = {
  0: "a", 1: "b", 2: "x", 3: "y", 4: "lb", 5: "rb", 6: "lt", 7: "rt",
  8: "view", 9: "menu", 10: "l3", 11: "r3", 16: "home",
};

// How each button is labelled on each pad. "kind" picks the glyph style.
export interface Glyph { kind: "face" | "plate" | "dpad"; text?: string; color?: string; ps?: "cross" | "circle" | "square" | "tri"; }

export function glyph(pad: PadType, input: PadInput): Glyph {
  const xb = pad === "xbox";
  switch (input) {
    case "a": return xb ? { kind: "face", text: "A", color: "#4CD964" } : { kind: "face", ps: "cross" };
    case "b": return xb ? { kind: "face", text: "B", color: "#FF5A5A" } : { kind: "face", ps: "circle" };
    case "x": return xb ? { kind: "face", text: "X", color: "#3D8BFF" } : { kind: "face", ps: "square" };
    case "y": return xb ? { kind: "face", text: "Y", color: "#F2C230" } : { kind: "face", ps: "tri" };
    case "dpad": return { kind: "dpad" };
    case "ls": return { kind: "plate", text: "L stick" };
    case "rs": return { kind: "plate", text: "R stick" };
    case "lb": return { kind: "plate", text: xb ? "LB" : "L1" };
    case "rb": return { kind: "plate", text: xb ? "RB" : "R1" };
    case "lt": return { kind: "plate", text: xb ? "LT" : "L2" };
    case "rt": return { kind: "plate", text: xb ? "RT" : "R2" };
    case "l3": return { kind: "plate", text: xb ? "L stick click" : "L3" };
    case "r3": return { kind: "plate", text: xb ? "R stick click" : "R3" };
    case "view": return { kind: "plate", text: xb ? "View" : "Create" };
    case "menu": return { kind: "plate", text: xb ? "Menu" : "Options" };
    case "home": return { kind: "plate", text: xb ? "Xbox button" : "PS button" };
  }
}

/** Guess the pad type from the name Windows gives it. */
export function padTypeFromId(id: string): PadType {
  const s = id.toLowerCase();
  if (/xbox|xinput|045e/.test(s)) return "xbox";
  return /dualsense|dualshock|wireless controller|054c|sony|playstation|ps5|ps4/.test(s) ? "dualsense" : "xbox";
}

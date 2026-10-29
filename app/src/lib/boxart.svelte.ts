// Box art keeps its real shape, like RomM shows it. Each cover tells us its shape once it loads,
// and the shapes are remembered on this PC so the grid doesn't jump around next time.

const KEY = "gamenight.coverShapes";

function load(): Record<string, number> {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "{}");
    return saved && typeof saved === "object" ? saved : {};
  } catch {
    return {};
  }
}

const shapes = $state<Record<string, number>>(load());
let saveTimer: ReturnType<typeof setTimeout> | undefined;

/** Width divided by height. Until a cover loads (or when there is none) cards use a standard box shape. */
export function shapeOf(id: string): number {
  const r = shapes[id];
  return typeof r === "number" && r >= 0.5 && r <= 1.6 ? r : 3 / 4;
}

/** Call from an <img onload>. Very odd sizes are kept in a sensible range so the grid stays tidy. */
export function remember(id: string, target: EventTarget | null) {
  if (!(target instanceof HTMLImageElement)) return;
  const r = target.naturalWidth / target.naturalHeight;
  if (!Number.isFinite(r) || r <= 0) return;
  const shape = Math.round(Math.min(1.6, Math.max(0.5, r)) * 1000) / 1000;
  if (shapes[id] === shape) return;
  shapes[id] = shape;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try { localStorage.setItem(KEY, JSON.stringify(shapes)); } catch { /* fine: shapes are worked out again */ }
  }, 1000);
}

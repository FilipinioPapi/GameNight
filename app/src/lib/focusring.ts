// The controller highlight: one glowing frame that glides from one thing to the next (like a games
// console menu), plus gentle scrolling that keeps the highlighted thing in view.
// It only shows while the controller is in use (the page is marked "pad-mode").

const reduced = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

let ring: HTMLDivElement | null = null;
const cur = { x: 0, y: 0, w: 0, h: 0, shown: false };
let lastTarget: HTMLElement | null = null;
let bump: { dx: number; dy: number; at: number } | null = null;

/** What the frame hugs: a game card's picture rather than the whole card (title and badges sit below it). */
function shapeOf(el: HTMLElement): HTMLElement {
  if (el.classList.contains("card")) return el.querySelector<HTMLElement>(":scope > .art") ?? el;
  return el;
}

/** The nearest scrolling box around an element (the list it lives in), if any. */
export function scrollParent(el: HTMLElement, axis: "x" | "y"): HTMLElement | null {
  let p = el.parentElement;
  while (p && p !== document.body) {
    const st = getComputedStyle(p);
    const ov = axis === "y" ? st.overflowY : st.overflowX;
    const room = axis === "y" ? p.scrollHeight > p.clientHeight : p.scrollWidth > p.clientWidth;
    if (/(auto|scroll)/.test(ov) && room) return p;
    p = p.parentElement;
  }
  return null;
}

// ---- Gentle scrolling ----
type Glide = { x: number; y: number };
const glides = new Map<HTMLElement, Glide>();

/** Scrolls the lists around an element, easing, so it sits comfortably in view with a bit of the next row showing. */
export function keepInView(el: HTMLElement) {
  const target = shapeOf(el);
  for (const axis of ["y", "x"] as const) {
    const box = scrollParent(target, axis);
    if (!box) continue;
    const g = glides.get(box) ?? { x: box.scrollLeft, y: box.scrollTop };
    const b = box.getBoundingClientRect();
    const r = target.getBoundingClientRect();
    if (axis === "y") {
      const margin = Math.min(72, box.clientHeight / 5);
      const top = r.top - b.top + box.scrollTop; // position inside the list
      let y = g.y;
      if (top - y < margin) y = top - margin;
      if (top + r.height - y > box.clientHeight - margin) y = top + r.height - box.clientHeight + margin;
      g.y = Math.max(0, Math.min(box.scrollHeight - box.clientHeight, y));
    } else {
      const margin = Math.min(r.width, box.clientWidth / 5);
      const left = r.left - b.left + box.scrollLeft;
      let x = g.x;
      if (left - x < margin) x = left - margin;
      if (left + r.width - x > box.clientWidth - margin) x = left + r.width - box.clientWidth + margin;
      g.x = Math.max(0, Math.min(box.scrollWidth - box.clientWidth, x));
    }
    glides.set(box, g);
  }
}

/** A little nudge when there's nowhere further to go, instead of jumping somewhere else. */
export function bumpRing(dir: "up" | "down" | "left" | "right") {
  const d = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] }[dir];
  bump = { dx: d[0], dy: d[1], at: performance.now() };
}

let last = 0;
function frame(now: number) {
  const dt = Math.min(64, now - (last || now));
  last = now;
  const ease = (tau: number) => (reduced() ? 1 : 1 - Math.exp(-dt / tau));

  // Scrolling lists ease toward where they need to be.
  for (const [box, g] of glides) {
    if (!box.isConnected) {
      glides.delete(box);
      continue;
    }
    const k = ease(70);
    const y = box.scrollTop + (g.y - box.scrollTop) * k;
    const x = box.scrollLeft + (g.x - box.scrollLeft) * k;
    box.scrollTop = Math.abs(g.y - y) < 0.5 ? g.y : y;
    box.scrollLeft = Math.abs(g.x - x) < 0.5 ? g.x : x;
    if (Math.abs(box.scrollTop - g.y) < 1 && Math.abs(box.scrollLeft - g.x) < 1) glides.delete(box);
  }

  const on = document.body.classList.contains("pad-mode");
  const el = document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null;
  const typing = el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement;
  if (ring) {
    if (on && el && !typing && el.isConnected) {
      document.body.classList.add("glide");
      const shape = shapeOf(el);
      const r = shape.getBoundingClientRect();
      // A new screen (or the first press): appear in place rather than flying across.
      const jump = !cur.shown || (lastTarget && !lastTarget.isConnected);
      if (jump) Object.assign(cur, { x: r.left, y: r.top, w: r.width, h: r.height });
      const k = ease(45);
      cur.x += (r.left - cur.x) * k;
      cur.y += (r.top - cur.y) * k;
      cur.w += (r.width - cur.w) * k;
      cur.h += (r.height - cur.h) * k;
      let ox = 0, oy = 0;
      if (bump) {
        const t = (now - bump.at) / 160;
        if (t >= 1 || reduced()) bump = null;
        else {
          const push = Math.sin(t * Math.PI) * 6;
          ox = bump.dx * push;
          oy = bump.dy * push;
        }
      }
      ring.style.transform = `translate(${cur.x + ox}px, ${cur.y + oy}px)`;
      ring.style.width = `${cur.w}px`;
      ring.style.height = `${cur.h}px`;
      ring.style.borderRadius = getComputedStyle(shape).borderRadius || "12px";
      // Don't draw over the header while a list scrolls underneath it.
      const box = scrollParent(shape, "y");
      if (box) {
        const b = box.getBoundingClientRect();
        const pad = 24;
        const top = Math.max(0, b.top - pad - (cur.y + oy));
        const bottom = Math.max(0, cur.y + oy + cur.h - (b.bottom + pad));
        ring.style.clipPath = top || bottom ? `inset(${top}px -40px ${bottom}px -40px)` : "";
      } else ring.style.clipPath = "";
      ring.classList.add("show");
      cur.shown = true;
      lastTarget = el;
    } else {
      document.body.classList.remove("glide");
      ring.classList.remove("show");
      cur.shown = false;
      lastTarget = null;
    }
  }
  requestAnimationFrame(frame);
}

export function startFocusRing() {
  if (ring || typeof document === "undefined") return;
  ring = document.createElement("div");
  ring.className = "focus-ring";
  ring.setAttribute("aria-hidden", "true");
  document.body.appendChild(ring);
  requestAnimationFrame(frame);
}

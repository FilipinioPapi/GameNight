<script lang="ts" module>
  // The button pictures are Jayden's pixel prompts (public/prompts), named by button position,
  // so PlayStation uses the Xbox letters for its file names (ps_a is Cross, ps_y is Triangle).
  export type Prompt = "a" | "b" | "x" | "y" | "lb" | "rb" | "lt" | "rt" | "start" | "back";
  export interface GuideItem {
    buttons: Prompt[];
    label: string;
    /** Pushes this one (and anything after it) to the right end, like "B Back". */
    right?: boolean;
  }
</script>

<script lang="ts">
  // The bar along the bottom of a screen that says what each controller button does there.
  // It shows Xbox or PlayStation buttons to match the controller in use.
  import { app } from "../lib/state.svelte";
  import { PAD_NAME } from "../lib/pads";

  let { items }: { items: GuideItem[] } = $props();
  const ps = $derived(app.pad.type === "dualsense");
  const NAMES: Record<Prompt, [string, string]> = {
    a: ["A", "Cross"], b: ["B", "Circle"], x: ["X", "Square"], y: ["Y", "Triangle"],
    lb: ["LB", "L1"], rb: ["RB", "R1"], lt: ["LT", "L2"], rt: ["RT", "R2"],
    start: ["Menu", "Options"], back: ["View", "Create"],
  };
  const src = (b: Prompt) => (ps ? `/prompts/ps/ps_${b}.png` : `/prompts/xbox/xbox_${b}.png`);
  const face = (b: Prompt) => b === "a" || b === "b" || b === "x" || b === "y";
</script>

<footer class="guide" aria-label="{PAD_NAME[app.pad.type]} controller buttons">
  {#each items as it (it.label + it.buttons.join())}
    <span class="item" class:right={it.right}>
      {#each it.buttons as b (b)}
        <img class:face={face(b)} src={src(b)} alt={NAMES[b][ps ? 1 : 0]} draggable="false" />
      {/each}
      <span>{it.label}</span>
    </span>
  {/each}
</footer>

<style>
  .guide {
    height: 60px; flex-shrink: 0; display: flex; align-items: center; gap: 26px; padding: 0 24px;
    border-top: 1px solid #5a2225; background: #0e0909; font-size: 14px; color: var(--text-2);
    box-shadow: 0 -1px 12px rgba(236, 40, 46, 0.22);
  }
  .item { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
  .item.right { margin-left: auto; }
  /* Pixel art: twice its real size, with sharp pixels. */
  img { height: 18px; width: auto; image-rendering: pixelated; }
  img.face { height: 26px; }
</style>

<script lang="ts">
  // Shows a button the way it's printed on the player's own pad (Xbox letters or PlayStation shapes).
  import { glyph, type PadInput, type PadType } from "../lib/pads";
  let { pad, input }: { pad: PadType; input: PadInput } = $props();
  const g = $derived(glyph(pad, input));
</script>

{#if g.kind === "face" && g.ps}
  <span class="g">
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke-width="2" stroke-linecap="round" aria-label={g.ps}>
      {#if g.ps === "cross"}<path d="M3 3l8 8M11 3l-8 8" stroke="#7FA8FF" />
      {:else if g.ps === "circle"}<circle cx="7" cy="7" r="4.5" stroke="#FF6E6E" />
      {:else if g.ps === "square"}<rect x="2.5" y="2.5" width="9" height="9" stroke="#E58BD9" />
      {:else}<path d="M7 2.5l5 8.5H2z" stroke="#4CD3A6" />{/if}
    </svg>
  </span>
{:else if g.kind === "face"}
  <span class="g" style="color:{g.color}">{g.text}</span>
{:else if g.kind === "dpad"}
  <span class="g"><svg width="16" height="16" viewBox="0 0 16 16" fill="#E8E8EE" aria-label="D-pad"><path d="M6 1h4v5h5v4h-5v5H6v-5H1V6h5z" /></svg></span>
{:else}
  <span class="g gp">{g.text}</span>
{/if}

<style>
  .g {
    width: 30px; height: 30px; border-radius: 50%; background: #18181b; border: 1px solid #3e3e46;
    display: inline-flex; align-items: center; justify-content: center; font-weight: 800; font-size: 14px; flex-shrink: 0; color: #e8e8ee;
  }
  .gp { width: auto; min-width: 38px; padding: 0 9px; border-radius: 9px; font-size: 12px; font-weight: 700; white-space: nowrap; }
</style>

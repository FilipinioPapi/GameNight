<script lang="ts">
  // A small outline icon. Pass the inside of a 24x24 SVG.
  let { svg, size = 22, stroke = 1.8 }: { svg: string; size?: number; stroke?: number } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width={stroke}
  stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html svg}</svg>

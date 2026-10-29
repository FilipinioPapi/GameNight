<script lang="ts">
  let { name, src, size = 32, color = "#5865F2" }: { name: string; src?: string; size?: number; color?: string } = $props();
</script>

{#if src}
  <img {src} alt="" style="width:{size}px;height:{size}px;border-radius:50%" />
{:else}
  <span class="av" style="width:{size}px;height:{size}px;background:{color};font-size:{Math.round(size * 0.42)}px">{name.slice(0, 1).toUpperCase()}</span>
{/if}

<style>
  .av { border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; color: #fff; flex-shrink: 0; }
</style>

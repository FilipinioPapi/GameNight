<script lang="ts">
  let { on, label, onchange }: { on: boolean; label: string; onchange: (v: boolean) => void } = $props();
</script>

<button class="tog" class:on role="switch" aria-checked={on} aria-label={label} onclick={() => onchange(!on)}><span></span></button>

<style>
  .tog { width: 44px; height: 26px; border-radius: 13px; position: relative; flex-shrink: 0; border: 0; background: var(--btn); }
  .tog.on { background: var(--red-2); }
  .tog span { position: absolute; top: 3px; left: 3px; width: 20px; height: 20px; border-radius: 50%; background: #fff; transition: left 0.12s; }
  .tog.on span { left: 21px; }
</style>

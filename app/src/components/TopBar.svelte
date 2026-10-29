<script lang="ts">
  // Header for inner screens: logo, "back" link, where you are, and who's signed in.
  import type { Snippet } from "svelte";
  import Brand from "./Brand.svelte";
  import Avatar from "./Avatar.svelte";
  import { app } from "../lib/state.svelte";

  let { backLabel, where, compact = false, right }: { backLabel: string; where: string; compact?: boolean; right?: Snippet } = $props();
</script>

<header class:compact>
  {#if compact}
    <Brand size="md" words={false} />
  {:else}
    <Brand size="md" />
    <div class="sep"></div>
  {/if}
  <button class="back" onclick={() => app.back()}>← {backLabel}</button>
  <span class="where">/ {where}</span>
  <div class="right">
    {#if right}{@render right()}{/if}
    {#if app.user}
      <span class="who"><Avatar name={app.user.name} src={app.user.avatar} />{app.user.name}</span>
    {/if}
  </div>
</header>

<style>
  header { height: 76px; flex-shrink: 0; display: flex; align-items: center; gap: 20px; padding: 0 28px; border-bottom: 1px solid var(--line-soft); }
  header.compact { height: 64px; gap: 16px; }
  .sep { width: 1px; height: 28px; background: var(--line); }
  .back { border: 0; background: none; padding: 0; font-size: 14px; color: var(--muted); }
  .back:hover { color: var(--text); }
  .where { font-size: 14px; color: var(--text-2); }
  .right { margin-left: auto; display: flex; align-items: center; gap: 16px; }
  .who { display: flex; align-items: center; gap: 10px; font-size: 14px; color: var(--muted); }
</style>

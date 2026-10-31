<script lang="ts">
  import { updates, reportSeen } from "../lib/update.svelte";
  import { formatSize } from "../lib/library";
  import { VERSION } from "../lib/version";

  const pct = $derived(updates.total ? Math.min(100, Math.round((updates.done / updates.total) * 100)) : 0);
  $effect(() => {
    if (updates.info && updates.phase !== "none" && updates.phase !== "available") reportSeen(updates.phase, pct);
  });
  let first: HTMLButtonElement | undefined = $state();
  $effect(() => {
    first?.focus();
  });
</script>

{#if updates.info && updates.phase !== "none" && updates.phase !== "available"}
  <div class="scrim" role="presentation">
    <div class="box" role="dialog" aria-modal="true" aria-labelledby="upd-title">
      {#if updates.phase === "asking"}
        <div class="kicker">UPDATE AVAILABLE</div>
        <h2 id="upd-title" class="lucky">UPDATE TO V{updates.info.version}?</h2>
        <p class="muted">You have v{VERSION}. It's a {formatSize(updates.info.size)} download.</p>
        {#if updates.info.notes.length}
          <div class="label">WHAT'S NEW</div>
          <ul>{#each updates.info.notes as n}<li>{n}</li>{/each}</ul>
        {/if}
        <p class="muted small">Game Night closes, updates itself and opens again. Your settings and games stay.</p>
        <div class="row">
          <button class="btn" bind:this={first} onclick={() => updates.later()}>Not now</button>
          <button class="btn primary" onclick={() => updates.install()}>Update now</button>
        </div>
      {:else if updates.phase === "downloading"}
        <div class="kicker">UPDATING TO V{updates.info.version}</div>
        <h2 id="upd-title" class="lucky">DOWNLOADING…</h2>
        <div class="bar" role="progressbar" aria-valuenow={pct} aria-valuemin="0" aria-valuemax="100"><div style="width:{pct}%"></div></div>
        <p class="muted">{formatSize(updates.done)} of {formatSize(updates.total)} · checked against Jayden's signature before installing</p>
      {:else if updates.phase === "restarting"}
        <div class="kicker">UPDATE READY</div>
        <h2 id="upd-title" class="lucky">RESTARTING…</h2>
        <p class="muted">Game Night opens again by itself in a few seconds.</p>
      {:else if updates.phase === "failed"}
        <div class="kicker bad">UPDATE DIDN'T WORK</div>
        <h2 id="upd-title" class="lucky">NOTHING CHANGED</h2>
        <p class="muted">{updates.error}</p>
        <div class="row">
          <button class="btn" bind:this={first} onclick={() => updates.later()}>Later</button>
          <button class="btn primary" onclick={() => updates.install()}>Try again</button>
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .scrim { position: fixed; inset: 0; background: rgba(8, 5, 5, 0.72); display: flex; align-items: center; justify-content: center; z-index: 50; }
  .box { width: 480px; border-radius: 16px; background: var(--panel); border: 2px solid var(--amber); padding: 26px 28px; display: flex; flex-direction: column; gap: 12px; box-shadow: 0 24px 60px rgba(0, 0, 0, 0.6); }
  .kicker { font-size: 12px; font-weight: 700; letter-spacing: 0.12em; color: var(--amber); }
  .kicker.bad { color: var(--link); }
  h2 { margin: 0; font-size: 34px; line-height: 1.05; color: #fff; }
  p { margin: 0; font-size: 14px; line-height: 1.5; }
  .small { font-size: 13px; }
  ul { margin: 0; padding-left: 18px; color: var(--text-2); font-size: 14px; line-height: 1.6; }
  .row { display: flex; justify-content: flex-end; gap: 10px; margin-top: 6px; }
  .bar { height: 14px; border-radius: 7px; background: var(--bg); border: 1px solid var(--line-2); overflow: hidden; }
  .bar div { height: 100%; background: var(--amber); transition: width 0.2s; }
</style>

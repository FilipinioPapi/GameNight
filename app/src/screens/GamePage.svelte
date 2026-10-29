<script lang="ts">
  import TopBar from "../components/TopBar.svelte";
  import { app } from "../lib/state.svelte";
  import { consoleById, PLAYABLE_NOW } from "../lib/consoles";
  import { formatSize, isCoop, listGames, localInfo, type Game } from "../lib/library";

  let { id }: { id: string } = $props();
  let game = $state<Game | null>(null);
  let notice = $state("");
  $effect(() => {
    listGames().then((all) => (game = all.find((g) => g.id === id) ?? null));
  });

  const c = $derived(game ? consoleById(game.console) : null);
  const local = $derived(localInfo(id));
  const playable = $derived(!!game && PLAYABLE_NOW.includes(game.console));

  function play() {
    notice = "Playing switches on in milestone 4, once games come from your RomM library. This build is a preview of the screens.";
  }
  let broken = $state(false);
</script>

<div class="page">
  <TopBar compact backLabel="Library" where={c?.short ?? ""} />
  {#if game && c}
    <main>
      <div class="col-art">
        <div class="art cover">
          {#if game.cover && !broken}<img class="cover" src={game.cover} alt="" onerror={() => (broken = true)} />{:else}<span class={c.font} style="font-size:{c.id === 'nes' ? 14 : 22}px;line-height:1.3">{game.title}</span>{/if}
        </div>
        <dl>
          <dt>Console</dt><dd>{c.name}</dd>
          <dt>Players</dt><dd>{game.players.replace("-", " to ")}</dd>
          <dt>Size</dt><dd>{formatSize(game.sizeBytes)}</dd>
          <dt>Emulator</dt><dd>{c.emulator}</dd>
        </dl>
      </div>

      <div class="col-main">
        <div class="badges">
          <span class="badge">{c.short}</span>
          {#if isCoop(game) && c.coop}<span class="badge coop">Couch co-op ready</span>{/if}
          {#if !c.coop}<span class="badge">Solo only for now</span>{/if}
          {#if local.onPC}<span class="badge coop">✓ On this PC</span>{/if}
        </div>
        <h1 class={c.font} style="font-size:{c.id === 'nes' ? 30 : 56}px">{game.title}</h1>
        <p class="desc">{game.description ?? "No description yet. It will come from RomM's game info."}</p>

        <div class="actions">
          <button class="btn primary big" onclick={play} disabled={!playable}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4l13 8-13 8z" /></svg>
            {local.onPC ? "Play solo" : `Download and play · ${formatSize(game.sizeBytes)}`}
          </button>
          {#if isCoop(game) && c.coop}
            <button class="btn big" disabled title="Coming in step 2">Start couch co-op</button>
          {/if}
          {#if local.onPC}
            <button class="btn big icon" title="Remove from this PC" aria-label="Remove from this PC" onclick={() => (notice = "Removing games switches on in milestone 4.")}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" /></svg>
            </button>
          {/if}
        </div>
        {#if !playable}<p class="soon">{c.name} games can't be played yet. NES and SNES come first, then the other consoles.</p>{/if}
        {#if notice}<p class="notice">{notice}</p>{/if}

        <div class="label sect">YOUR SOLO SAVE</div>
        <div class="box">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#FF8A8F" stroke-width="2" aria-hidden="true"><path d="M5 3h11l3 3v15H5z" /><path d="M8 3v6h8V3M8 21v-7h8v7" /></svg>
          <div class="box-text"><b>No save yet</b><span>Your progress saves automatically and is backed up to the Game Night server.</span></div>
        </div>
      </div>
    </main>
  {/if}
</div>

<style>
  .page { height: 100%; display: flex; flex-direction: column; background: radial-gradient(ellipse at 0% 0%, #4a1c1e 0%, var(--bg) 45%); }
  main { flex: 1; display: flex; gap: 40px; padding: 28px 48px; min-height: 0; overflow-y: auto; }
  .col-art { width: 260px; flex-shrink: 0; display: flex; flex-direction: column; gap: 20px; }
  .cover { height: 342px; padding: 16px; border-radius: 14px; }
  dl { display: grid; grid-template-columns: 68px 1fr; gap: 8px 12px; margin: 0; font-size: 13px; }
  dt { color: var(--muted-2); }
  dd { margin: 0; color: var(--text-2); }
  .col-main { flex: 1; min-width: 0; max-width: 780px; }
  .badges { display: flex; gap: 8px; }
  .badges .badge { height: 26px; padding: 0 12px; font-size: 12px; }
  h1 { font-weight: 400; margin: 18px 0 14px; line-height: 1.15; }
  .desc { font-size: 15px; color: var(--text-2); line-height: 1.6; margin: 0 0 24px; }
  .actions { display: flex; gap: 10px; }
  .big { height: 52px; padding: 0 24px; font-size: 16px; }
  .icon { width: 52px; padding: 0; }
  .soon, .notice { font-size: 13px; color: var(--muted); margin: 12px 0 0; }
  .notice { color: var(--amber); }
  .sect { margin: 28px 0 10px; }
  .box { display: flex; align-items: center; gap: 14px; padding: 14px 18px; border-radius: 12px; border: 1px solid var(--line); background: var(--panel); }
  .box-text { display: flex; flex-direction: column; gap: 3px; }
  .box-text b { font-size: 15px; }
  .box-text span { font-size: 12px; color: var(--muted); }
</style>

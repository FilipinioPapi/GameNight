<script lang="ts">
  import TopBar from "../components/TopBar.svelte";
  import { app } from "../lib/state.svelte";
  import { consoleById, PLAYABLE_NOW } from "../lib/consoles";
  import { formatSize, isCoop, listGames, localInfo, type Game } from "../lib/library";
  import { play } from "../lib/play.svelte";
  import { inTauri } from "../lib/settings";
  import { remember, shapeOf } from "../lib/boxart.svelte";

  let { id }: { id: string } = $props();
  let game = $state<Game | null>(null);
  let notice = $state("");
  // Removing asks first, so one stray click or controller press can't delete a game.
  let confirmRemove = $state(false);
  let cancelBtn = $state<HTMLButtonElement | null>(null);
  $effect(() => {
    if (confirmRemove) cancelBtn?.focus();
  });
  async function remove() {
    confirmRemove = false;
    await play.remove(game!.id);
  }
  $effect(() => {
    listGames().then((all) => (game = all.find((g) => g.id === id) ?? null));
  });

  const c = $derived(game ? consoleById(game.console) : null);
  const local = $derived(localInfo(id));
  const playable = $derived(!!game && PLAYABLE_NOW.includes(game.console));

  $effect(() => {
    play.refresh();
  });
  const error = $derived(play.errors[id] ?? "");
  const running = $derived(play.playing === id);

  async function start() {
    notice = "";
    if (!game) return;
    if (!inTauri) {
      notice = "This is the screen preview. Downloading and playing work in the Windows app.";
      return;
    }
    if (!app.settings.romsFolder) {
      notice = "Pick a folder for your games in Settings, Storage first.";
      return;
    }
    if (!local.onPC && !(await play.download(game))) return;
    await play.play(game);
  }
  let broken = $state(false);
</script>

<div class="page">
  <TopBar compact backLabel="Library" where={c?.short ?? ""} />
  {#if game && c}
    <main>
      <div class="col-art">
        <div class="art big-art" style="aspect-ratio:{shapeOf(game.id)}">
          {#if game.cover && !broken}<img class="cover" src={game.cover} alt="" onload={(e) => remember(game!.id, e.currentTarget)} onerror={() => (broken = true)} />{:else}<span class={c.font} style="font-size:{c.id === 'nes' ? 14 : 22}px;line-height:1.3">{game.title}</span>{/if}
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
          {#if local.downloading !== undefined}
            <div class="dlbox">
              <div class="dltext">Downloading… {Math.round(local.downloading * 100)}%</div>
              <div class="dlbar"><div style="width:{local.downloading * 100}%"></div></div>
            </div>
            <button class="btn big" onclick={() => play.cancel(game!.id)}>Stop</button>
          {:else}
            <button class="btn primary big" onclick={start} disabled={!playable || !!play.playing}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4l13 8-13 8z" /></svg>
              {running ? "Playing now" : local.onPC ? "Play solo" : `Download and play · ${formatSize(game.sizeBytes)}`}
            </button>
            {#if isCoop(game) && c.coop}
              <button class="btn big" disabled title="Coming in step 2">Start couch co-op</button>
            {/if}
            {#if local.onPC && !running}
              {#if confirmRemove}
                <span class="ask">Remove from this PC?</span>
                <button class="btn big" bind:this={cancelBtn} onclick={() => (confirmRemove = false)}>Keep it</button>
                <button class="btn big danger" onclick={remove}>Yes, remove</button>
              {:else}
                <button class="btn big icon" title="Remove from this PC" aria-label="Remove from this PC" onclick={() => (confirmRemove = true)}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" /></svg>
                </button>
              {/if}
            {/if}
          {/if}
        </div>
        {#if !playable}<p class="soon">{c.name} games can't be played yet. NES and SNES come first, then the other consoles.</p>{/if}
        {#if running}<p class="playing">Playing now. To come back, press <b>Esc</b>, or press both sticks in together (<b>L3 + R3</b>) on your controller.</p>{/if}
        {#if error}<p class="notice">{error}</p>{/if}
        {#if notice}<p class="notice">{notice}</p>{/if}

        <div class="label sect">YOUR SOLO SAVE</div>
        <div class="box">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#FF8A8F" stroke-width="2" aria-hidden="true"><path d="M5 3h11l3 3v15H5z" /><path d="M8 3v6h8V3M8 21v-7h8v7" /></svg>
          <div class="box-text"><b>Saves on this PC</b><span>Your progress saves automatically in your Game Night folder. Backing it up to the Game Night server comes with couch co-op.</span></div>
        </div>
      </div>
    </main>
  {/if}
</div>

<style>
  .ask { align-self: center; font-weight: 600; color: var(--text); }
  .danger { border-color: var(--red-2); color: var(--link); }
  .page { height: 100%; display: flex; flex-direction: column; background: radial-gradient(ellipse at 0% 0%, #4a1c1e 0%, var(--bg) 45%); }
  main { flex: 1; display: flex; gap: 40px; padding: 28px 48px; min-height: 0; overflow-y: auto; }
  .col-art { width: 260px; flex-shrink: 0; display: flex; flex-direction: column; gap: 20px; }
  .big-art { width: 100%; padding: 16px; border-radius: 14px; }
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
  .playing { font-size: 13px; color: var(--text-2); margin: 12px 0 0; }
  .dlbox { display: flex; flex-direction: column; justify-content: center; gap: 8px; width: 320px; }
  .dltext { font-size: 14px; color: var(--amber); font-weight: 600; }
  .dlbar { height: 8px; border-radius: 4px; background: var(--btn); overflow: hidden; }
  .dlbar div { height: 100%; background: var(--amber); transition: width 0.15s; }
  .sect { margin: 28px 0 10px; }
  .box { display: flex; align-items: center; gap: 14px; padding: 14px 18px; border-radius: 12px; border: 1px solid var(--line); background: var(--panel); }
  .box-text { display: flex; flex-direction: column; gap: 3px; }
  .box-text b { font-size: 15px; }
  .box-text span { font-size: 12px; color: var(--muted); }
</style>

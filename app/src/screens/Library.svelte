<script lang="ts">
  import TopBar from "../components/TopBar.svelte";
  import Icon from "../components/Icon.svelte";
  import { app } from "../lib/state.svelte";
  import { CONSOLES, consoleById, type ConsoleId } from "../lib/consoles";
  import { formatSize, isCoop, listGames, localInfo, type Game } from "../lib/library";

  let { console: current }: { console: ConsoleId | "all" } = $props();

  let games = $state<Game[]>([]);
  let search = $state("");
  let sort = $state<"az" | "coop">("az");
  $effect(() => {
    listGames().then((g) => (games = g));
  });

  const count = (id: ConsoleId) => games.filter((g) => g.console === id).length;
  const shown = $derived(
    games
      .filter((g) => current === "all" || g.console === current)
      .filter((g) => !search || g.title.toLowerCase().includes(search.toLowerCase()))
      .filter((g) => sort !== "coop" || (isCoop(g) && consoleById(g.console).coop))
      .sort((a, b) => a.title.localeCompare(b.title)),
  );
  const heading = $derived(current === "all" ? null : consoleById(current));
  const featured = $derived(shown.find((g) => localInfo(g.id).onPC) ?? shown[0]);

  const pick = (c: ConsoleId | "all") => (app.route = { name: "library", console: c });
  const open = (g: Game) => app.go({ name: "game", id: g.id });
</script>

<div class="page">
  <TopBar backLabel="Main menu" where="Play">
    {#snippet right()}
      <div class="search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#8F7A7C" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>
        <input type="text" placeholder="Search {games.length} games…" bind:value={search} aria-label="Search games" />
      </div>
    {/snippet}
  </TopBar>

  <main>
    <aside class="scroll">
      <div class="label side-label">CONSOLES</div>
      <button class="side" class:on={current === "all"} onclick={() => pick("all")}>
        <Icon svg='<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>' />
        <span class="all">All games</span><span class="n">{games.length}</span>
      </button>
      {#each CONSOLES.filter((c) => c.coop) as c (c.id)}
        <button class="side" class:on={current === c.id} onclick={() => pick(c.id)}>
          <Icon svg={c.icon} /><span class={c.font} style="font-size:{c.navSize}px">{c.short}</span><span class="n">{count(c.id)}</span>
        </button>
      {/each}
      <div class="rule"></div>
      <div class="label side-label">SOLO ONLY FOR NOW</div>
      {#each CONSOLES.filter((c) => !c.coop) as c (c.id)}
        <button class="side" class:on={current === c.id} onclick={() => pick(c.id)}>
          <Icon svg={c.icon} /><span class={c.font} style="font-size:{c.navSize}px">{c.short}</span><span class="n">{count(c.id)}</span>
        </button>
      {/each}
    </aside>

    <section class="scroll">
      {#if featured && !search}
        {@const fc = consoleById(featured.console)}
        <div class="hero">
          <div class="art hero-art"><span class={fc.font} style="font-size:{fc.id === 'nes' ? 8 : 12}px;line-height:1.3">{featured.title}</span></div>
          <div class="hero-text">
            <div class="kicker">{localInfo(featured.id).onPC ? "READY ON THIS PC" : "IN THE LIBRARY"}</div>
            <div class={fc.font} style="font-size:{fc.id === 'nes' ? 24 : 36}px;line-height:1.1">{featured.title}</div>
            <div class="badges">
              <span class="badge">{fc.short}</span><span class="badge">{featured.players} player{featured.players === "1" ? "" : "s"}</span>
              {#if isCoop(featured) && fc.coop}<span class="badge coop">Co-op ready</span>{/if}
            </div>
          </div>
          <div class="hero-btns">
            <button class="btn primary" onclick={() => open(featured)}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4l13 8-13 8z" /></svg>Open game
            </button>
          </div>
        </div>
      {/if}

      <div class="head">
        {#if heading}
          <Icon svg={heading.icon} size={26} />
          <span class={heading.font} style="font-size:{heading.id === 'nes' ? 16 : 26}px">{heading.name}</span>
        {:else}
          <span class="lucky" style="font-size:26px;-webkit-text-stroke:4px #000">ALL GAMES</span>
        {/if}
        <span class="count">{shown.length} games · {shown.filter((g) => localInfo(g.id).onPC).length} on this PC</span>
        <span class="sorts">
          <button class="pill" class:on={sort === "az"} onclick={() => (sort = "az")}>A–Z</button>
          <button class="pill" class:on={sort === "coop"} onclick={() => (sort = "coop")}>Co-op only</button>
        </span>
      </div>

      {#if shown.length === 0}
        <p class="empty">No games here yet.</p>
      {/if}
      <div class="grid">
        {#each shown as g (g.id)}
          {@const c = consoleById(g.console)}
          {@const local = localInfo(g.id)}
          <button class="card" onclick={() => open(g)}>
            <div class="art">
              {#if g.cover}<img class="cover" src={g.cover} alt="" />{/if}
              {#if local.downloading !== undefined}
                <div class="dl"><div style="width:{local.downloading * 100}%"></div></div>
              {:else if local.onPC}
                <span class="state ok" title="On this PC"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" aria-hidden="true"><path d="M5 12l5 5 9-10" /></svg></span>
              {:else}
                <span class="state" title="Download to play"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#E3D2D3" stroke-width="2.5" aria-hidden="true"><path d="M12 4v12M6 11l6 6 6-6M5 20h14" /></svg></span>
              {/if}
              <span class={c.font} style="font-size:{c.id === 'nes' ? 10 : 15}px;line-height:1.2;position:relative">{g.title}</span>
            </div>
            <div class="meta">
              {#if isCoop(g) && c.coop}<span class="badge coop">Co-op</span>{/if}
              <span class="badge">{g.players === "1" ? "1P" : g.players + "P"}</span>
              {#if current === "all"}<span class="badge">{c.short}</span>{/if}
              {#if local.downloading !== undefined}<span class="note amber">Downloading {Math.round(local.downloading * 100)}%</span>
              {:else if !local.onPC}<span class="note">{formatSize(g.sizeBytes)}</span>{/if}
            </div>
          </button>
        {/each}
      </div>
    </section>
  </main>
</div>

<style>
  .page { height: 100%; display: flex; flex-direction: column; }
  .search { position: relative; }
  .search svg { position: absolute; left: 13px; top: 12px; }
  .search input { width: 320px; height: 40px; border-radius: 10px; border: 1px solid var(--line-2); background: var(--panel); color: var(--text); padding: 0 12px 0 38px; font-size: 14px; }
  main { flex: 1; display: flex; min-height: 0; }
  aside { width: 248px; flex-shrink: 0; border-right: 1px solid var(--line-soft); padding: 16px 12px; display: flex; flex-direction: column; gap: 2px; background: var(--bg-side); }
  .side-label { margin: 4px 0 8px 12px; }
  .side { display: flex; align-items: center; gap: 12px; height: 44px; padding: 0 12px; border-radius: 10px; border: 0; background: transparent; color: var(--text); text-align: left; width: 100%; flex-shrink: 0; }
  .side:hover { background: var(--panel); }
  .side.on { background: var(--red-2); color: #fff; }
  .side :global(svg) { color: var(--link); flex-shrink: 0; }
  .side.on :global(svg) { color: #fff; }
  .side .all { font-weight: 600; font-size: 15px; }
  .n { margin-left: auto; font-size: 12px; color: var(--muted-2); }
  .side.on .n { color: #fff; }
  .rule { height: 1px; background: var(--line-soft); margin: 8px 12px; flex-shrink: 0; }

  section { flex: 1; min-width: 0; padding: 20px 28px 28px; display: flex; flex-direction: column; gap: 18px; }
  .hero { min-height: 168px; flex-shrink: 0; border-radius: 16px; border: 1px solid var(--line); background: linear-gradient(110deg, #3a1416 0%, #1e1415 60%, #120c0c 100%); display: flex; align-items: center; gap: 24px; padding: 20px 24px; }
  .hero-art { width: 96px; height: 128px; flex-shrink: 0; padding: 8px; border-radius: 8px; background: linear-gradient(160deg, #5a2224, #2c1c1d); }
  .hero-text { display: flex; flex-direction: column; gap: 8px; flex: 1; min-width: 0; }
  .kicker { font-size: 11px; font-weight: 700; letter-spacing: 0.1em; color: var(--link); }
  .badges { display: flex; gap: 8px; align-items: center; }
  .hero-btns { width: 200px; display: flex; flex-direction: column; }
  .hero-btns .btn { height: 46px; }
  .head { display: flex; align-items: center; gap: 12px; }
  .head :global(svg) { color: var(--link); }
  .count { font-size: 13px; color: var(--muted-2); }
  .sorts { margin-left: auto; display: flex; gap: 6px; }
  .empty { color: var(--muted); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 16px; }
  .card { display: flex; flex-direction: column; gap: 8px; border: 0; background: none; padding: 0; text-align: left; }
  .card .art { height: 178px; border: 2px solid transparent; outline: 1px solid var(--line); outline-offset: -1px; }
  .card:hover .art, .card:focus-visible .art { border-color: var(--red); outline-color: transparent; }
  .card:focus-visible { outline: none; }
  .state { position: absolute; top: 8px; right: 8px; width: 26px; height: 26px; border-radius: 50%; display: flex; align-items: center; justify-content: center; background: var(--btn); border: 1px solid var(--line-2); }
  .state.ok { background: var(--green-bg); border-color: var(--green-bg); }
  .dl { position: absolute; left: 0; right: 0; bottom: 0; height: 4px; background: var(--btn); }
  .dl div { height: 100%; background: var(--amber); }
  .meta { display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }
  .note { font-size: 12px; color: var(--muted); margin-left: 2px; }
  .note.amber { color: var(--amber); }
</style>

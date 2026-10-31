<script lang="ts" module>
  // Remembered while the app is open, so coming back from a game page lands on the same game and sort.
  let lastFocus: string | null = null;
  let lastSort: "az" | "recent" | "coop" = "az";
</script>

<script lang="ts">
  // The Library: every game, by console, with your favourites first.
  // Two looks (Settings › Layout): the controller layout (consoles across the top, big tiles,
  // a button guide along the bottom) and the mouse and keyboard layout (consoles in a list on the left).
  import { tick } from "svelte";
  import { play } from "../lib/play.svelte";
  import Icon from "../components/Icon.svelte";
  import ButtonGuide, { type GuideItem } from "../components/ButtonGuide.svelte";
  import { app, type LibraryTab } from "../lib/state.svelte";
  import { CONSOLES, PLAYABLE_NOW, TAB_ART, consoleById } from "../lib/consoles";
  import { formatSize, isCoop, listGames, localInfo, type Game } from "../lib/library";
  import { remember, shapeOf } from "../lib/boxart.svelte";
  import { moveFocus, useScreenButtons, type Dir } from "../lib/gamepad";
  import { inTauri, type RecentPlay } from "../lib/settings";

  let { console: current }: { console: LibraryTab } = $props();

  let games = $state<Game[]>([]);
  let loaded = $state(false);
  let search = $state("");
  let sort = $state<"az" | "recent" | "coop">(lastSort);
  $effect(() => {
    lastSort = sort;
  });
  $effect(() => {
    listGames().then((g) => {
      games = g;
      loaded = true;
    });
  });
  $effect(() => {
    play.refresh();
  });

  // Which layout. "Automatic" follows the last thing you touched: a controller press turns on the
  // controller look (the menus mark the page with "pad-mode"), moving the mouse turns it off.
  let padLook = $state(typeof document !== "undefined" && document.body.classList.contains("pad-mode"));
  $effect(() => {
    const watch = new MutationObserver(() => (padLook = document.body.classList.contains("pad-mode")));
    watch.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    return () => watch.disconnect();
  });
  const layout = $derived(app.settings.autoLayout ? (padLook ? "controller" : "mouse") : app.settings.layout);

  // ---- What's showing ----
  const byId = $derived(new Map(games.map((g) => [g.id, g])));
  const onPCCount = $derived(games.filter((g) => localInfo(g.id).onPC).length);
  const recentRank = $derived(new Map(app.settings.recent.map((r, i) => [r.id, i])));
  function sorted(list: Game[]): Game[] {
    const out = sort === "coop" ? list.filter((g) => isCoop(g) && consoleById(g.console).coop) : [...list];
    if (sort === "recent") {
      const rank = (g: Game) => recentRank.get(g.id) ?? Infinity;
      return out.sort((a, b) => rank(a) - rank(b) || a.title.localeCompare(b.title));
    }
    return out.sort((a, b) => a.title.localeCompare(b.title));
  }
  const favGames = $derived(app.settings.favourites.map((id) => byId.get(id)).filter((g): g is Game => !!g));
  const recent = $derived(
    app.settings.recent
      .map((r) => ({ r, g: byId.get(r.id) }))
      .filter((x): x is { r: RecentPlay; g: Game } => !!x.g)
      .slice(0, 3),
  );
  const searching = $derived(search.trim().length > 0);
  const tabGames = $derived(current === "fav" ? favGames : current === "all" ? games : games.filter((g) => g.console === current));
  const shown = $derived(
    searching ? sorted(games.filter((g) => g.title.toLowerCase().includes(search.trim().toLowerCase()))) : sorted(tabGames),
  );
  const heading = $derived(current === "fav" || current === "all" ? null : consoleById(current));

  // size: label size on the controller tab bar; listSize: in the mouse layout's list.
  type Tab = { id: LibraryTab; name: string; art: string; font: string; size: number; listSize: number; count: number; icon?: string };
  const tabs = $derived<Tab[]>([
    { id: "fav", name: "Favourites", art: TAB_ART.fav, font: "", size: 13, listSize: 14, count: favGames.length },
    { id: "all", name: "All games", art: TAB_ART.all, font: "", size: 13, listSize: 14, count: games.length },
    ...CONSOLES.map((c) => ({
      id: c.id, name: c.short, art: c.art, font: c.font, icon: c.icon,
      size: Math.round(c.navSize * 0.85), listSize: c.navSize, count: games.filter((g) => g.console === c.id).length,
    })),
  ]);

  const pick = (t: LibraryTab) => {
    search = "";
    app.route = { name: "library", console: t };
  };
  /** Q / E on the keyboard step through the tabs, like LB / RB. */
  function stepTab(step: 1 | -1) {
    const i = tabs.findIndex((t) => t.id === current);
    const next = tabs[(i + step + tabs.length) % tabs.length];
    pick(next.id);
    void tick().then(() => document.querySelector<HTMLElement>("[data-tab].on")?.scrollIntoView({ block: "nearest", inline: "nearest" }));
  }
  const open = (g: Game) => app.go({ name: "game", id: g.id });
  /** The mouse layout's Play button: start it if it's ready on this PC, otherwise open its page. */
  async function quickPlay(g: Game) {
    const ready = inTauri && localInfo(g.id).onPC && PLAYABLE_NOW.includes(g.console) && !play.playing && !!app.settings.romsFolder;
    if (ready) await play.play(g);
    else open(g);
  }

  // Covers that failed to load fall back to the title.
  let broken = $state<Record<string, boolean>>({});

  // ---- Favourites (Y on a controller, F on the keyboard, or the star with the mouse) ----
  let focusedId = $state<string | null>(null);
  let hoveredId = $state<string | null>(null);
  const gameAt = (t: EventTarget | null) => (t instanceof Element ? t.closest<HTMLElement>("[data-game]")?.dataset.game ?? null : null);

  let toast = $state<{ text: string; title: string; added: boolean } | null>(null);
  let toastTimer: ReturnType<typeof setTimeout> | undefined;
  async function toggleFav(id: string | null) {
    if (!id) return;
    const g = byId.get(id);
    if (!g) return;
    // If the game leaves the screen (un-starring on the Favourites tab), keep the highlight in the same spot.
    const cards = Array.from(document.querySelectorAll<HTMLElement>("[data-game]"));
    const had = document.activeElement instanceof HTMLElement ? cards.indexOf(document.activeElement) : -1;
    const added = app.toggleFavourite(id);
    toast = { text: added ? "Added" : "Removed", title: g.title, added };
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = null), 2200);
    await tick();
    if (had >= 0 && !document.activeElement?.closest("[data-game]")) {
      const now = Array.from(document.querySelectorAll<HTMLElement>("[data-game]"));
      (now[Math.min(had, now.length - 1)] ?? document.querySelector<HTMLElement>("[data-tab].on"))?.focus();
    }
  }

  // ---- Controller buttons this screen uses ----
  let searchEl = $state<HTMLInputElement | null>(null);
  const focusSearch = () => {
    searchEl?.focus();
    searchEl?.select();
  };
  $effect(() => {
    useScreenButtons((input) => {
      if (input === "y") {
        void toggleFav(focusedId);
        return true;
      }
      if (input === "x") {
        focusSearch();
        return true;
      }
      // B in the search box: back to the games, not out of the Library.
      if (input === "b" && searchEl && document.activeElement === searchEl) {
        searchEl.blur();
        (document.querySelector<HTMLElement>("[data-game]") ?? document.querySelector<HTMLElement>("[data-tab].on"))?.focus();
        return true;
      }
      if (input === "menu" && current !== "fav") {
        sort = sort === "coop" ? "az" : "coop";
        return true;
      }
      return false;
    });
    return () => useScreenButtons(null);
  });

  // ---- Keyboard ----
  const ARROWS: Record<string, Dir> = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
  function onKey(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
      e.preventDefault();
      focusSearch();
      return;
    }
    const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement;
    if (typing) {
      // Enter or Down from the search box goes to the results.
      if ((e.key === "Enter" || e.key === "ArrowDown") && e.target === searchEl) {
        e.preventDefault();
        document.querySelector<HTMLElement>("[data-game]")?.focus();
      }
      return;
    }
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    const k = e.key.toLowerCase();
    if (k === "f") {
      e.preventDefault();
      void toggleFav(focusedId ?? hoveredId);
    } else if (k === "q" || k === "e") {
      e.preventDefault();
      stepTab(k === "e" ? 1 : -1);
    } else if (ARROWS[e.key]) {
      e.preventDefault();
      moveFocus(ARROWS[e.key]);
    }
  }

  // Controller layout: start with the first game highlighted, so a controller can go straight away.
  let started = false;
  $effect(() => {
    if (!loaded || started || layout !== "controller") return;
    started = true;
    void tick().then(() => {
      document.querySelector<HTMLElement>("[data-tab].on")?.scrollIntoView({ block: "nearest", inline: "nearest" });
      const back = lastFocus ? document.querySelector<HTMLElement>(`[data-game="${CSS.escape(lastFocus)}"]`) : null;
      const first = back ?? document.querySelector<HTMLElement>("[data-game]") ?? document.querySelector<HTMLElement>("[data-tab].on");
      first?.focus({ preventScroll: !back });
      if (back) back.scrollIntoView({ block: "nearest" });
    });
  });

  // ---- Words ----
  function when(r: RecentPlay): string {
    const d = new Date(r.at);
    const now = new Date();
    const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const ago = Math.round((day(now) - day(d)) / 86400000);
    const base = ago <= 0 ? (d.getHours() >= 17 ? "Played tonight" : "Played today")
      : ago === 1 ? "Played yesterday"
      : ago < 7 ? `Played on ${d.toLocaleDateString("en-GB", { weekday: "long" })}`
      : `Played on ${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`;
    if (!r.minutes) return base;
    const h = Math.floor(r.minutes / 60);
    const m = r.minutes % 60;
    return `${base} · ${h ? `${h} h ${m ? m + " min" : ""}`.trim() : `${m} min`}`;
  }
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

  const guide = $derived<GuideItem[]>([
    { buttons: ["a"], label: "Open" },
    ...(focusedId ? [{ buttons: ["y"], label: app.isFavourite(focusedId) ? "Unfavourite" : "Favourite" } satisfies GuideItem] : []),
    { buttons: ["x"], label: "Search" },
    { buttons: ["lb", "rb"], label: "Change console" },
    ...(current !== "fav" && !searching ? [{ buttons: ["start"], label: sort === "coop" ? "Show all" : "Co-op only" } satisfies GuideItem] : []),
    { buttons: ["b"], label: "Main menu", right: true },
  ]);
  const STAR = "M12 2l3 6.6 7 .8-5.2 4.8 1.4 7L12 17.8 5.8 21.2l1.4-7L2 9.4l7-.8z";
</script>

<svelte:window onkeydown={onKey} />

{#snippet star(size: number)}
  <svg width={size} height={size} viewBox="0 0 24 24" fill="var(--amber)" aria-hidden="true"><path d={STAR} /></svg>
{/snippet}

{#snippet cover(g: Game, fontPx: [number, number])}
  {@const c = consoleById(g.console)}
  {#if g.cover && !broken[g.id]}
    <img class="cover" src={g.cover} alt="" loading="lazy" decoding="async" onload={(e) => remember(g.id, e.currentTarget)} onerror={() => (broken[g.id] = true)} />
  {:else}
    <span class={c.font} style="font-size:{c.id === 'nes' ? fontPx[0] : fontPx[1]}px;line-height:1.2;position:relative">{g.title}</span>
  {/if}
{/snippet}

<!-- One game tile. The mouse layout adds a star button and an "Open" cover on hover. -->
{#snippet card(g: Game, mouse: boolean)}
  {@const c = consoleById(g.console)}
  {@const local = localInfo(g.id)}
  {@const fav = app.isFavourite(g.id)}
  <div class="cardwrap" class:mouse>
    <button class="card" data-game={g.id} onclick={() => open(g)} onmouseenter={() => (hoveredId = g.id)} onmouseleave={() => (hoveredId = null)}>
      <div class="art" style="aspect-ratio:{shapeOf(g.id)}">
        {@render cover(g, [10, 15])}
        {#if fav && !mouse}<span class="favdot" title="Favourite">{@render star(12)}</span>{/if}
        {#if local.downloading !== undefined}
          <div class="dl"><div style="width:{local.downloading * 100}%"></div></div>
        {:else if local.onPC}
          <span class="state ok" title="On this PC"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" aria-hidden="true"><path d="M5 12l5 5 9-10" /></svg></span>
        {:else if !mouse}
          <span class="state" title="Download to play"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#E3D2D3" stroke-width="2.5" aria-hidden="true"><path d="M12 4v12M6 11l6 6 6-6M5 20h14" /></svg></span>
        {/if}
        {#if mouse}<span class="hover-open"><span class="btn primary small"><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4l13 8-13 8z" /></svg>Open</span></span>{/if}
      </div>
      <div class="meta">
        <!-- Lists that mix consoles say which console; a console's own tab says players and size. -->
        {#if isCoop(g) && c.coop}<span class="badge coop">Co-op</span>{/if}
        {#if current === "all" || current === "fav" || searching}
          <span class="badge">{c.short}</span>
          {#if local.downloading !== undefined}<span class="note amber">{Math.round(local.downloading * 100)}%</span>{/if}
        {:else}
          <span class="badge">{g.players === "1" ? "1P" : g.players + "P"}</span>
          {#if local.downloading !== undefined}<span class="note amber">Downloading {Math.round(local.downloading * 100)}%</span>
          {:else if !local.onPC}<span class="note">{formatSize(g.sizeBytes)}</span>{/if}
        {/if}
      </div>
    </button>
    {#if mouse}
      <button class="starbtn" class:on={fav} title={fav ? "Unfavourite (F)" : "Favourite (F)"} aria-label={fav ? `Remove ${g.title} from favourites` : `Add ${g.title} to favourites`} onclick={() => toggleFav(g.id)}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill={fav ? "var(--amber)" : "none"} stroke="var(--amber)" stroke-width="2" aria-hidden="true"><path d={STAR} /></svg>
      </button>
    {/if}
  </div>
{/snippet}

{#snippet grid(list: Game[], mouse: boolean)}
  <div class="grid">
    {#each list as g (g.id)}{@render card(g, mouse)}{/each}
  </div>
{/snippet}

{#snippet sorts(withRecent: boolean)}
  <span class="sorts">
    <button class="pill" class:on={sort === "az"} onclick={() => (sort = "az")}>A–Z</button>
    {#if withRecent}<button class="pill" class:on={sort === "recent"} onclick={() => (sort = "recent")}>Recently played</button>{/if}
    <button class="pill" class:on={sort === "coop"} onclick={() => (sort = "coop")}>Co-op only</button>
  </span>
{/snippet}

{#snippet searchBox(hint: string)}
  <label class="search">
    <span class="vh">Search games</span>
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#8F7A7C" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>
    <input type="text" data-search bind:this={searchEl} placeholder="Search {games.length} games…{hint}" bind:value={search} />
  </label>
{/snippet}

<!-- The game list under the tabs: search results, a console, all games, or favourites. -->
{#snippet body(mouse: boolean)}
  {#if searching}
    <div class="head">
      <span class="lucky h">RESULTS</span>
      <span class="count">{plural(shown.length, "game")} for “{search.trim()}”</span>
      {#if mouse}{@render sorts(true)}{/if}
    </div>
    {#if shown.length === 0}<p class="empty">No games match “{search.trim()}”.</p>{/if}
    {@render grid(shown, mouse)}
  {:else if current === "fav"}
    {#if mouse}
      <div class="head">
        {@render star(24)}
        <span class="lucky h">FAVOURITES</span>
        <span class="count">{plural(favGames.length, "game")}</span>
        {@render sorts(true)}
      </div>
    {/if}
    {#if recent.length}
      <div class="label">RECENTLY PLAYED</div>
      <div class="recent">
        {#each recent as { r, g } (g.id)}
          {@const c = consoleById(g.console)}
          {#if mouse}
            <div class="rcard mouse">
              <button class="rbody" data-game={g.id} onclick={() => open(g)} onmouseenter={() => (hoveredId = g.id)} onmouseleave={() => (hoveredId = null)}>
                <span class="art rart">{@render cover(g, [6, 9])}</span>
                <span class="rtext"><b>{g.title}</b><span>{c.short} · {when(r).replace("Played ", "")}</span></span>
              </button>
              <button class="btn primary small rplay" onclick={() => quickPlay(g)}><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4l13 8-13 8z" /></svg>Play</button>
            </div>
          {:else}
            <button class="rcard" data-game={g.id} onclick={() => open(g)}>
              <span class="art rart">{@render cover(g, [6, 9])}</span>
              <span class="rtext"><b>{g.title}</b><span>{when(r)}</span><span class="badges"><span class="badge">{c.short}</span></span></span>
            </button>
          {/if}
        {/each}
      </div>
    {/if}
    <div class="label favlabel">{#if !mouse}{@render star(12)}ALL YOUR FAVOURITES · {favGames.length}{:else}ALL FAVOURITES{/if}</div>
    {#if favGames.length === 0}
      <div class="nofav">
        {@render star(28)}
        <div>
          <b>No favourites yet</b>
          {#if mouse}<span>Click the star on any game, or hover it and press F. Your favourites show up here.</span>
          {:else}<span>Highlight any game and press <img class="inline" src={app.pad.type === "dualsense" ? "/prompts/ps/ps_y.png" : "/prompts/xbox/xbox_y.png"} alt={app.pad.type === "dualsense" ? "Triangle" : "Y"} /> to add it here.</span>{/if}
        </div>
        <button class="btn small" onclick={() => pick("all")}>Browse all games</button>
      </div>
    {/if}
    {@render grid(sorted(favGames), mouse)}
  {:else}
    <div class="head">
      {#if heading}
        {#if mouse}<Icon svg={heading.icon} size={26} />{/if}
        <span class={heading.font} style="font-size:{heading.id === 'nes' ? 16 : 26}px">{heading.name}</span>
      {:else}
        <span class="lucky h">ALL GAMES</span>
      {/if}
      <span class="count">{plural(shown.length, "game")} · {shown.filter((g) => localInfo(g.id).onPC).length} on this PC</span>
      {@render sorts(mouse)}
    </div>
    {#if loaded && shown.length === 0}<p class="empty">No games here yet.</p>{/if}
    {@render grid(shown, mouse)}
  {/if}
{/snippet}

<div class="page" onfocusin={(e) => (focusedId = lastFocus = gameAt(e.target))}>
  {#if layout === "controller"}
    <header class="pad-head">
      <span class="lucky title glow">LIBRARY</span>
      <span class="count">{plural(games.length, "game")} · {onPCCount} on this PC</span>
      <div class="right">{@render searchBox("")}</div>
    </header>

    <nav class="tabbar" aria-label="Consoles">
      <img class="shoulder" src={app.pad.type === "dualsense" ? "/prompts/ps/ps_lb.png" : "/prompts/xbox/xbox_lb.png"} alt="" />
      <div class="tabs">
        {#each tabs as t (t.id)}
          <button class="tab" data-tab class:on={current === t.id} onclick={() => pick(t.id)}>
            <img src="/consoles/{t.art}.png" alt="" draggable="false" />
            <span class={t.font} style="font-size:{t.size}px">{t.name}</span>
          </button>
        {/each}
      </div>
      <img class="shoulder" src={app.pad.type === "dualsense" ? "/prompts/ps/ps_rb.png" : "/prompts/xbox/xbox_rb.png"} alt="" />
    </nav>

    <section class="scroll content">{@render body(false)}</section>
    <ButtonGuide items={guide} />
  {:else}
    <header class="mk-head">
      <button class="back" onclick={() => app.back()}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M15 18l-6-6 6-6" /></svg>Main menu</button>
      <span class="lucky title glow">LIBRARY</span>
      <div class="right">{@render searchBox("   Ctrl+F")}</div>
    </header>
    <main class="mk">
      <aside class="scroll">
        {#each tabs as t, i (t.id)}
          {#if i === 2}<div class="rule"></div>{/if}
          <button class="side" data-tab class:on={current === t.id} onclick={() => pick(t.id)}>
            {#if t.id === "fav"}
              <svg width="18" height="18" viewBox="0 0 24 24" fill={current === "fav" ? "#fff" : "var(--amber)"} aria-hidden="true"><path d={STAR} /></svg>
            {:else if t.id === "all"}
              <Icon size={18} svg='<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>' />
            {:else}
              <Icon size={18} svg={t.icon ?? ""} />
            {/if}
            <span class={t.font || "strong"} style="font-size:{t.listSize}px">{t.name}</span>
            <span class="n">{t.count}</span>
          </button>
        {/each}
      </aside>
      <section class="scroll content">{@render body(true)}</section>
    </main>
    <footer class="keys">
      <span>Keys:</span>
      <span><b>Arrows</b> move</span>
      <span><b>Enter</b> open</span>
      <span><b>F</b> favourite</span>
      <span><b>Ctrl+F</b> search</span>
      <span><b>Q · E</b> change console</span>
      <span><b>Esc</b> back</span>
      <span class="push">A controller still works here too</span>
    </footer>
  {/if}

  {#if toast}
    <div class="toast" role="status">
      {@render star(16)}
      <span>{toast.text} <b>{toast.title}</b> {toast.added ? "to" : "from"} Favourites</span>
    </div>
  {/if}
</div>

<style>
  .page { height: 100%; display: flex; flex-direction: column; position: relative; }
  .vh { position: absolute; left: -9999px; }
  .right { margin-left: auto; display: flex; align-items: center; gap: 16px; }
  .count { font-size: 13px; color: var(--muted-2); }

  /* Title: Luckiest Guy with a soft red neon glow (the subtle retro touch). */
  .title { font-size: 26px; -webkit-text-stroke: 4px #000; }
  .glow { text-shadow: 0 3px 0 #000, 0 0 14px rgba(255, 70, 70, 0.6), 0 0 28px rgba(236, 40, 46, 0.3); }

  .search { position: relative; display: flex; align-items: center; }
  .search svg { position: absolute; left: 13px; }
  .search input { width: 320px; height: 40px; border-radius: 10px; border: 1px solid var(--line-2); background: var(--panel); color: var(--text); padding: 0 12px 0 38px; font-size: 14px; }

  /* ---------- Controller layout ---------- */
  .pad-head { height: 64px; flex-shrink: 0; display: flex; align-items: center; gap: 16px; padding: 0 24px; }
  .tabbar {
    flex-shrink: 0; display: flex; align-items: center; gap: 10px; padding: 4px 16px 14px;
    border-bottom: 1px solid #5a2225; box-shadow: 0 1px 12px rgba(236, 40, 46, 0.2);
  }
  .shoulder { height: 18px; width: auto; image-rendering: pixelated; flex-shrink: 0; }
  .tabs { flex: 1; min-width: 0; display: flex; gap: 8px; overflow-x: auto; padding: 6px 4px; scrollbar-width: thin; scrollbar-color: var(--line) transparent; }
  .tab {
    width: 118px; height: 100px; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
    border-radius: 12px; border: 1px solid var(--line); background: var(--panel); color: var(--text-2); padding: 0 4px;
    box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.6);
  }
  .tab img { width: 88px; height: 50px; object-fit: contain; }
  .tab span { white-space: nowrap; }
  .tab:hover { border-color: var(--line-2); }
  .tab.on {
    border: 2px solid #ff5a60; color: #fff; background: linear-gradient(180deg, #e3242c 0%, #a3121a 100%);
    box-shadow: 0 0 0 1px #ffd0d2, 0 0 8px 2px #ff2a33, 0 0 20px 3px rgba(255, 30, 40, 0.45), inset 0 0 14px rgba(255, 190, 190, 0.35);
  }

  .content { flex: 1; min-height: 0; padding: 18px 28px 28px; display: flex; flex-direction: column; gap: 14px; }
  .head { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
  .head :global(svg) { color: var(--link); flex-shrink: 0; }
  .h { font-size: 26px; -webkit-text-stroke: 4px #000; }
  .sorts { margin-left: auto; display: flex; gap: 6px; }
  .label { flex-shrink: 0; }
  .favlabel { display: flex; align-items: center; gap: 6px; margin-top: 6px; }
  .empty { color: var(--muted); margin: 0; }

  .recent { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; flex-shrink: 0; }
  .rcard {
    display: flex; align-items: center; gap: 16px; height: 112px; padding: 12px; border-radius: 14px; border: 1px solid var(--line);
    background: var(--panel); color: var(--text); text-align: left; min-width: 0;
  }
  .rart { width: 66px; height: 88px; flex-shrink: 0; padding: 4px; border-radius: 6px; }
  .rtext { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .rtext b { font-size: 16px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rtext > span { font-size: 12px; color: var(--muted); }
  .badges { display: flex; gap: 4px; }

  .nofav { display: flex; align-items: center; gap: 16px; padding: 16px 18px; border-radius: 12px; border: 1px dashed var(--line-2); background: var(--panel); flex-shrink: 0; }
  .nofav div { display: flex; flex-direction: column; gap: 4px; flex: 1; }
  .nofav b { font-size: 15px; }
  .nofav span { font-size: 13px; color: var(--muted); }
  .inline { height: 18px; width: auto; image-rendering: pixelated; vertical-align: -4px; margin: 0 2px; }

  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 20px 16px; align-items: end; }
  .cardwrap { position: relative; min-width: 0; }
  .card { display: flex; flex-direction: column; gap: 8px; border: 0; background: none; padding: 0; text-align: left; width: 100%; }
  .card .art { width: 100%; border: 2px solid transparent; outline: 1px solid var(--line); outline-offset: -1px; box-shadow: 0 8px 20px rgba(0, 0, 0, 0.45); }
  .card:hover .art, .card:focus-visible .art { border-color: var(--red); outline-color: transparent; }
  .card:focus-visible { outline: none; }
  /* Controller in use: the highlighted game gets a warm neon glow. */
  :global(.pad-mode) .card:focus { outline: none; }
  :global(.pad-mode) .card:focus .art, :global(.pad-mode) .rcard:focus {
    border-color: #ffc84a; outline-color: transparent;
    box-shadow: 0 0 0 1px #fff3c4, 0 0 8px 2px #ffb21e, 0 0 20px 3px rgba(255, 150, 0, 0.5);
  }
  :global(.pad-mode) .rcard:focus { outline: none; border: 2px solid #ffc84a; padding: 11px; }
  .favdot {
    position: absolute; top: 8px; left: 8px; width: 24px; height: 24px; border-radius: 50%; background: var(--btn);
    border: 1px solid var(--amber); display: flex; align-items: center; justify-content: center; box-shadow: 0 0 8px rgba(242, 180, 90, 0.5);
  }
  .state { position: absolute; top: 8px; right: 8px; width: 26px; height: 26px; border-radius: 50%; display: flex; align-items: center; justify-content: center; background: var(--btn); border: 1px solid var(--line-2); }
  .state.ok { background: var(--green-bg); border-color: var(--green-bg); }
  .dl { position: absolute; left: 0; right: 0; bottom: 0; height: 4px; background: var(--btn); }
  .dl div { height: 100%; background: var(--amber); }
  /* One line, so tiles in a row line up. */
  .meta { display: flex; gap: 4px; align-items: center; flex-wrap: nowrap; overflow: hidden; }
  .note { font-size: 12px; color: var(--muted); margin-left: 2px; white-space: nowrap; }
  .note.amber { color: var(--amber); }

  /* ---------- Mouse and keyboard layout ---------- */
  .mk-head { height: 64px; flex-shrink: 0; display: flex; align-items: center; gap: 16px; padding: 0 24px; border-bottom: 1px solid var(--line-soft); }
  .back { display: flex; align-items: center; gap: 8px; border: 0; background: none; padding: 0; font-size: 14px; color: var(--muted); }
  .back:hover { color: var(--text); }
  .mk { flex: 1; display: flex; min-height: 0; }
  .mk .grid { grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); }
  aside { width: 240px; flex-shrink: 0; border-right: 1px solid var(--line-soft); padding: 14px 12px; display: flex; flex-direction: column; gap: 2px; background: var(--bg-side); }
  .side { display: flex; align-items: center; gap: 12px; height: 38px; padding: 0 12px; border-radius: 10px; border: 0; background: transparent; color: var(--text); text-align: left; width: 100%; flex-shrink: 0; }
  .side:hover { background: var(--panel); }
  .side.on { background: var(--red-2); color: #fff; box-shadow: 0 0 10px rgba(255, 30, 40, 0.35); }
  .side :global(svg) { color: var(--link); flex-shrink: 0; }
  .side.on :global(svg) { color: #fff; }
  .strong { font-weight: 600; }
  .n { margin-left: auto; font-size: 12px; color: var(--muted-2); }
  .side.on .n { color: #fff; }
  .rule { height: 1px; background: var(--line-soft); margin: 6px 12px; flex-shrink: 0; }

  .rcard.mouse { height: 96px; padding: 10px; gap: 14px; }
  .rbody { flex: 1; min-width: 0; display: flex; align-items: center; gap: 14px; border: 0; background: none; padding: 0; text-align: left; color: inherit; }
  .rcard.mouse .rart { width: 56px; height: 76px; }
  .rcard.mouse .rtext b { font-size: 15px; }
  .rplay { height: 36px; flex-shrink: 0; }

  .starbtn {
    position: absolute; top: 6px; right: 6px; width: 30px; height: 30px; border-radius: 50%; padding: 0;
    background: rgba(18, 12, 12, 0.85); border: 1px solid var(--amber); display: flex; align-items: center; justify-content: center;
    opacity: 0; transition: opacity 0.1s;
  }
  .starbtn.on, .cardwrap:hover .starbtn, .starbtn:focus-visible, :global(.pad-mode) .starbtn:focus { opacity: 1; }
  .hover-open { position: absolute; inset: 0; display: none; align-items: center; justify-content: center; background: rgba(0, 0, 0, 0.45); }
  .cardwrap.mouse:hover .hover-open { display: flex; }
  .cardwrap.mouse .card:hover .art { outline: 2px solid var(--red); outline-offset: 2px; }

  .keys { height: 40px; flex-shrink: 0; display: flex; align-items: center; gap: 22px; padding: 0 24px; border-top: 1px solid var(--line-soft); background: #0e0909; font-size: 12px; color: var(--muted-2); white-space: nowrap; overflow: hidden; }
  .keys b { color: var(--text-2); }
  .keys .push { margin-left: auto; }

  .toast {
    position: absolute; right: 28px; bottom: 76px; display: flex; align-items: center; gap: 10px; padding: 10px 16px; border-radius: 12px;
    background: var(--panel); border: 1px solid var(--amber); font-size: 14px; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5); pointer-events: none;
  }
</style>

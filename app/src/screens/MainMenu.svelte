<script lang="ts" module>
  // Which card was picked last, so coming back from the Library lands on the same one.
  let lastPick = 0;
</script>

<script lang="ts">
  // The main menu, as approved by Jayden on 2026-10-31 (mockup "A21", card icons left out for now):
  // a row of four big cards where the picked one grows, a line saying what it does, the last three
  // games played, and the last game's box art glowing softly behind everything.
  import { tick } from "svelte";
  import { play } from "../lib/play.svelte";
  import Avatar from "../components/Avatar.svelte";
  import ButtonGuide, { type GuideItem } from "../components/ButtonGuide.svelte";
  import { app } from "../lib/state.svelte";
  import { consoleById } from "../lib/consoles";
  import { loadLibrary, localInfo, playedWhen, type Game, type Library } from "../lib/library";
  import { moveFocus, type Dir } from "../lib/gamepad";
  import { quitApp, steamRunning } from "../lib/native";
  import { VERSION } from "../lib/version";
  import { updates } from "../lib/update.svelte";

  let games = $state<Game[]>([]);
  let lib = $state<Library | null>(null);
  $effect(() => {
    loadLibrary().then((l) => {
      lib = l;
      games = l.games;
    });
  });
  const onPC = $derived(games.filter((g) => localInfo(g.id).onPC).length);
  const byId = $derived(new Map(games.map((g) => [g.id, g])));
  const recent = $derived(
    app.settings.recent
      .map((r) => ({ r, g: byId.get(r.id) }))
      .filter((x): x is { r: (typeof app.settings.recent)[number]; g: Game } => !!x.g)
      .slice(0, 3),
  );
  // The last game played: its box art glows behind the menu.
  const lastGame = $derived(recent[0]?.g ?? null);
  let brokenArt = $state<Record<string, boolean>>({});
  const glowArt = $derived(lastGame?.cover && !brokenArt[lastGame.id] ? lastGame.cover : null);

  $effect(() => {
    void updates.check();
  });
  $effect(() => {
    play.refresh();
  });

  // One-time tip: Steam grabs the Xbox / PS button unless that's turned off in Steam.
  let steamTip = $state(false);
  $effect(() => {
    if (!app.settings.steamTipSeen) steamRunning().then((on) => (steamTip = on));
  });
  function closeSteamTip() {
    steamTip = false;
    app.settings.steamTipSeen = true;
    app.save();
    void tick().then(() => cards[sel]?.focus({ preventScroll: true }));
  }

  // The clock, like a console's home screen.
  const clockText = (d: Date) => {
    const h = d.getHours() % 12 || 12;
    return `${h}:${String(d.getMinutes()).padStart(2, "0")} ${d.getHours() < 12 ? "AM" : "PM"}`;
  };
  let clock = $state(clockText(new Date()));
  $effect(() => {
    const t = setInterval(() => (clock = clockText(new Date())), 5000);
    return () => clearInterval(t);
  });

  // ---- The four cards ----
  type Card = { id: string; label: string; more: string; desc: string; halo: string; soon?: boolean; go: () => void };
  const items = $derived<Card[]>([
    {
      id: "library", label: "LIBRARY", more: `${games.length} games · ${onPC} on this PC`, desc: "BROWSE AND PLAY YOUR GAMES",
      halo: "rgba(236,40,46,.35)", go: () => app.go({ name: "library", console: "fav" }),
    },
    {
      id: "couch", label: "COUCH PLAY", more: "Play online with friends", desc: "PLAY ONLINE WITH FRIENDS (COMING NEXT)",
      halo: "rgba(58,110,232,.4)", soon: true, go: () => {},
    },
    {
      id: "settings", label: "SETTINGS", more: "Controllers, consoles, layout", desc: "CONTROLLERS, CONSOLES AND LAYOUT",
      halo: "rgba(242,180,90,.3)", go: () => app.go({ name: "settings", tab: "consoles", console: "nes" }),
    },
    { id: "quit", label: "QUIT", more: "Close Game Night", desc: "CLOSE GAME NIGHT", halo: "rgba(120,110,255,.35)", go: quitApp },
  ]);

  let sel = $state(lastPick);
  const pick = (i: number) => {
    sel = i;
    lastPick = i;
  };
  const cards: HTMLButtonElement[] = [];
  $effect(() => {
    cards[lastPick]?.focus({ preventScroll: true });
  });

  // Arrow keys work like the D-pad (keyboard backup).
  const ARROWS: Record<string, Dir> = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
  function onKey(e: KeyboardEvent) {
    if (e.ctrlKey || e.altKey || e.metaKey || !ARROWS[e.key]) return;
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
    e.preventDefault();
    moveFocus(ARROWS[e.key]);
  }

  const guide = $derived<GuideItem[]>([
    { buttons: ["a"], label: "Select" },
    { buttons: [], glyph: "◄ ►", label: "Move" },
    ...(recent.length ? [{ buttons: [], glyph: "▼", label: "Jump back in" } satisfies GuideItem] : []),
  ]);
</script>

<svelte:window onkeydown={onKey} />

<div class="page">
  {#if glowArt}
    <div class="glow" aria-hidden="true">
      <img class="scene" src={glowArt} alt="" decoding="async" onerror={() => lastGame && (brokenArt[lastGame.id] = true)} />
    </div>
  {/if}
  <div class="tint" aria-hidden="true"></div>

  <header>
    <img class="tvlogo" src="/brand/crt-logo.gif" alt="Game Night logo" />
    <div class="wordmark">
      <span class="gnw">GAME NIGHT</span>
      <span class="gnp">POWERED BY<span class="gnj">JAYDENATER</span><span class="gnb">[BOT]</span></span>
    </div>
    <div class="right">
      {#if updates.info && updates.phase !== "none"}<button class="chip-pill update" onclick={() => updates.open()}><span class="dot"></span>Update ready: v{updates.info.version}</button>{/if}
      {#if lib?.source === "sample"}<span class="chip-pill"><span class="dot"></span>Preview: sample games</span>
      {:else if lib?.error}<span class="chip-pill"><span class="dot"></span>{lib.error}</span>
      {:else if lib?.source === "offline"}<span class="chip-pill"><span class="dot"></span>Offline: showing the last list</span>{/if}
      <span class="vt glowtxt clock">{clock}</span>
      {#if app.user}<span class="pill"><Avatar name={app.user.name} src={app.user.avatar} size={30} />{app.user.name}</span>{/if}
    </div>
  </header>

  <nav aria-label="Main menu">
    {#each items as it, i (it.id)}
      <button
        class="card"
        class:on={sel === i}
        data-autofocus={i === 0 ? "" : undefined}
        aria-disabled={it.soon ? "true" : undefined}
        bind:this={cards[i]}
        onfocus={() => pick(i)}
        onmouseenter={() => pick(i)}
        onclick={it.go}
      >
        <span class="full"><span class="bgp"></span><span class="halo" style="--h: {it.halo}"></span></span>
        <span class="fade"></span>
        <span class="tx">
          <span class="lbl">{it.label}</span>
          {#if it.soon}<span class="soon">COMING NEXT</span>{/if}
          <span class="more">{it.more}</span>
        </span>
      </button>
    {/each}
  </nav>

  <div class="vt desc" aria-live="polite">&gt; {items[sel].desc}<span class="cursor">_</span></div>

  {#if recent.length}
    <section aria-label="Jump back in">
      <span class="vt glowtxt jlabel">&gt; JUMP BACK IN</span>
      <div class="recs">
        {#each recent as { r, g } (g.id)}
          {@const c = consoleById(g.console)}
          <button class="rec" onclick={() => app.go({ name: "game", id: g.id })}>
            <span class="art">
              {#if g.cover && !brokenArt[g.id]}
                <img src={g.cover} alt="" decoding="async" onerror={() => (brokenArt[g.id] = true)} />
              {:else}
                <span class={c.font}>{g.title}</span>
              {/if}
            </span>
            <span class="rtext"><b>{g.title}</b><span class="when">{playedWhen(r)}</span><span><span class="chip">{c.short.toUpperCase()}</span></span></span>
          </button>
        {/each}
      </div>
    </section>
  {/if}

  {#if steamTip}
    <div class="tip" role="note">
      <b>Tip: stop the Xbox button opening Steam</b>
      <span>Steam is open. In Steam, go to <b>Settings</b>, then <b>Controller</b>, and turn off <b>"Guide Button Focuses Steam"</b>. Then the Xbox / PS button only opens Game Night.</span>
      <button class="btn small" onclick={closeSteamTip}>Got it</button>
    </div>
  {/if}

  <div class="foot"><ButtonGuide items={guide} retro note="v{VERSION}" /></div>
</div>

<style>
  /* Sizes and colours follow the approved mockup (project files: main-menu/A21-approved.dc.html). */
  .page {
    height: 100%; position: relative; overflow: hidden; isolation: isolate; color: var(--text);
    background: radial-gradient(ellipse at 50% 38%, #3b1417 0% 12%, #2d1012 12% 24%, #210c0e 24% 38%, #170a0b 38% 54%, #0e0707 54% 72%, #070404 72% 100%);
  }
  .vt { font-family: VT323, monospace; letter-spacing: 0.06em; }
  .glowtxt { color: var(--link); text-shadow: 0 0 6px rgba(255, 90, 90, 0.8); }

  /* The last game's box art, blurred and drifting slowly behind everything. */
  .glow {
    position: absolute; inset: 0; z-index: -2; overflow: hidden; pointer-events: none;
    -webkit-mask-image: linear-gradient(180deg, #000 0%, #000 40%, transparent 78%);
    mask-image: linear-gradient(180deg, #000 0%, #000 40%, transparent 78%);
  }
  .scene {
    position: absolute; inset: -80px; width: calc(100% + 160px); height: calc(100% + 160px); object-fit: cover;
    opacity: 0.5; filter: blur(16px) saturate(1.15); animation: drift 40s ease-in-out infinite alternate;
  }
  @keyframes drift { from { transform: scale(1.02) translateX(0); } to { transform: scale(1.08) translateX(-30px); } }
  .tint { position: absolute; inset: 0; z-index: -1; pointer-events: none; background: radial-gradient(ellipse at 50% 30%, rgba(59, 20, 23, 0.35) 0%, rgba(14, 7, 7, 0.55) 75%); }

  /* ---- Header: Jayden's CRT logo and the neon wordmark ---- */
  header { position: absolute; left: 48px; right: 48px; top: 32px; display: flex; align-items: center; gap: 16px; }
  .tvlogo { display: block; flex-shrink: 0; width: 66px; height: 80px; margin: -6px 2px -6px 0; filter: drop-shadow(0 0 10px rgba(236, 40, 46, 0.35)) drop-shadow(0 4px 0 #000); }
  .wordmark { display: flex; flex-direction: column; gap: 8px; }
  .gnw {
    font-family: "Press Start 2P", monospace; font-size: 24px; line-height: 1.1; letter-spacing: 0.02em; white-space: nowrap; color: #ff2a32;
    text-shadow: 0 0 3px #ff5a60, 0 0 12px #ec282e, 0 0 26px rgba(236, 40, 46, 0.85), 3px 3px 0 #000; animation: flick 7s linear infinite;
  }
  /* The neon sign flickers now and then. */
  @keyframes flick {
    0%, 15.9%, 17.1%, 18.9%, 20.1%, 61.9%, 63.1%, 100% { color: #ff2a32; text-shadow: 0 0 3px #ff5a60, 0 0 12px #ec282e, 0 0 26px rgba(236, 40, 46, 0.85), 3px 3px 0 #000; }
    16%, 17%, 19%, 20%, 62%, 63% { color: #8a1218; text-shadow: 3px 3px 0 #000; }
  }
  .gnp { font-family: VT323, monospace; font-size: 18px; letter-spacing: 0.12em; color: var(--muted); display: flex; align-items: baseline; white-space: nowrap; }
  .gnj { color: var(--red); margin-left: 8px; text-shadow: 0 0 8px rgba(236, 40, 46, 0.8); }
  .gnb { font-family: "Press Start 2P", monospace; font-size: 7px; letter-spacing: 0; color: #fff; }
  .right { margin-left: auto; display: flex; align-items: center; gap: 18px; }
  .clock { font-size: 26px; }
  .pill { display: flex; align-items: center; gap: 10px; padding: 5px 14px 5px 5px; border-radius: 999px; background: rgba(30, 20, 21, 0.92); border: 1px solid var(--line); font-size: 14px; }
  .chip-pill { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); padding: 8px 14px; border-radius: 999px; background: rgba(30, 20, 21, 0.92); border: 1px solid var(--line); }
  .update { cursor: pointer; border-color: var(--amber); color: #fff; font-weight: 600; animation: glow 1.6s ease-in-out infinite; }
  .update:hover, .update:focus-visible { background: #2a1f14; }
  @keyframes glow { 50% { box-shadow: 0 0 12px 1px rgba(242, 180, 90, 0.45); } }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--amber); }

  /* ---- The four cards: the picked one grows ---- */
  nav { position: absolute; left: 48px; right: 48px; top: 150px; display: flex; gap: 24px; align-items: flex-end; }
  .card {
    /* 460 px picked and 217 px for the rest in the 1280-wide window, sharing the room the same way if it's wider. */
    position: relative; flex: none; width: calc((100% - 72px) * 217 / 1111); height: 340px; box-sizing: border-box; overflow: hidden; padding: 0;
    border-radius: 10px; border: 3px solid #000; background: #120c0c; color: var(--text); font: inherit; text-align: left; cursor: pointer;
    box-shadow: 0 8px 0 rgba(0, 0, 0, 0.5); outline: none; container-type: inline-size;
    transition: width 0.42s cubic-bezier(0.2, 0.8, 0.2, 1), transform 0.28s cubic-bezier(0.2, 0.8, 0.2, 1), border-color 0.28s ease, background 0.28s ease;
  }
  .card::after { content: ""; position: absolute; inset: 6px; border: 2px solid rgba(255, 255, 255, 0.07); border-radius: 5px; pointer-events: none; }
  .card.on { width: calc((100% - 72px) * 460 / 1111); transform: translateY(-12px) scale(1.03); border-color: #ffd36b; background: rgba(44, 24, 25, 0.95); animation: neonGold 2.6s ease-in-out infinite; }
  .card:focus-visible { outline: none; }
  @keyframes neonGold {
    0%, 100% { box-shadow: 0 0 0 1px #fff3c4, 0 0 8px 2px #ffb21e, 0 0 22px 4px rgba(255, 150, 0, 0.65), 0 0 44px 8px rgba(255, 120, 0, 0.25), inset 0 0 12px rgba(255, 170, 40, 0.45); }
    50% { box-shadow: 0 0 0 1px #fff3c4, 0 0 10px 3px #ffc23e, 0 0 28px 6px rgba(255, 160, 0, 0.8), 0 0 56px 12px rgba(255, 130, 0, 0.35), inset 0 0 16px rgba(255, 180, 60, 0.55); }
  }
  /* With a controller, the gliding gold frame is the highlight, so the card's own glow steps aside. */
  :global(body.glide.pad-mode) .card.on:focus { animation: none; border-color: #000; }
  .full { position: absolute; inset: 0; }
  .bgp { position: absolute; inset: 0; background: linear-gradient(180deg, #0a0606 0 18%, #1e0d0f 18% 44%, #2d1012 44% 72%, #1e0d0f 72%); }
  .halo { position: absolute; left: 50%; top: 40%; width: 240px; height: 240px; margin: -120px 0 0 -120px; border-radius: 50%; background: radial-gradient(circle, var(--h) 0%, transparent 65%); transition: opacity 0.3s ease; }
  .card:not(.on) .halo { opacity: 0.45; }
  .fade { position: absolute; left: 0; right: 0; bottom: 0; height: 58%; background: linear-gradient(180deg, rgba(10, 6, 6, 0) 0%, rgba(10, 6, 6, 0.78) 55%, rgba(10, 6, 6, 0.95) 100%); }
  .tx { position: absolute; left: 24px; right: 16px; top: 226px; z-index: 1; display: flex; flex-direction: column; align-items: flex-start; gap: 10px; }
  .lbl {
    font-family: "Press Start 2P", monospace; white-space: nowrap; letter-spacing: 0.02em; line-height: 1.15; color: #fff;
    text-shadow: 0 0 4px #ff6a70, 0 0 12px #ec282e, 0 0 26px rgba(236, 40, 46, 0.7), 3px 3px 0 #000; transition: font-size 0.3s ease;
    /* In a narrower window the titles shrink to fit their card (same size as the mockup at 1280 wide). */
    font-size: min(17px, 8cqw);
  }
  .card.on .lbl { font-size: min(30px, 6.6cqw); color: #fff6d8; text-shadow: 0 0 4px #ffd36b, 0 0 14px #ffb21e, 0 0 30px rgba(255, 140, 0, 0.7), 4px 4px 0 #000; }
  .more { font-family: VT323, monospace; font-size: 21px; letter-spacing: 0.05em; color: #ffe0e0; font-weight: 500; white-space: nowrap; opacity: 0; transition: opacity 0.3s ease 0.12s; }
  .card.on .more { opacity: 1; }
  .soon {
    font-family: VT323, monospace; font-size: 18px; letter-spacing: 0.08em; line-height: 1; color: var(--link); white-space: nowrap;
    border: 1px solid var(--red); border-radius: 4px; padding: 3px 7px 2px; background: rgba(10, 6, 6, 0.8); text-shadow: 0 0 6px rgba(236, 40, 46, 0.7);
  }

  /* ---- What the picked card does ---- */
  .desc { position: absolute; left: 50px; top: 516px; font-size: 26px; color: #ffd6d6; text-shadow: 0 0 6px rgba(255, 120, 120, 0.6); }
  .cursor { animation: blink 1.1s steps(1) infinite; }
  @keyframes blink { 50% { opacity: 0; } }

  /* ---- Jump back in: the last three games ---- */
  section { position: absolute; left: 48px; right: 48px; top: 576px; display: flex; flex-direction: column; gap: 12px; }
  .jlabel { font-size: 22px; }
  .recs { display: flex; gap: 20px; }
  .rec {
    display: flex; align-items: center; gap: 14px; flex: 1 1 0; min-width: 0; height: 88px; box-sizing: border-box; padding: 12px;
    border-radius: 14px; border: 1px solid #4a2427; background: rgba(30, 20, 21, 0.85); color: var(--text); text-align: left; font: inherit; cursor: pointer;
  }
  .rec { transition: transform 0.18s cubic-bezier(0.2, 0.8, 0.2, 1), border-color 0.18s; }
  .rec:hover { border-color: var(--red); }
  /* The gliding frame shows which one is picked; the card lifts a little under it. */
  :global(body.glide.pad-mode) .rec:focus { transform: scale(1.02); border-color: transparent; }
  .art {
    width: 64px; height: 64px; border-radius: 8px; flex-shrink: 0; overflow: hidden; display: flex; align-items: flex-end; padding: 5px; box-sizing: border-box;
    font-size: 7px; line-height: 1.3; color: #fff; background: linear-gradient(160deg, #4a2f31, #1e1415);
  }
  /* Box art keeps its own shape (never cropped). */
  .art:has(img) { padding: 0; align-items: center; justify-content: center; background: rgba(10, 6, 6, 0.6); }
  .art img { width: 100%; height: 100%; object-fit: contain; }
  .rtext { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .rtext b { font-family: "Press Start 2P", monospace; font-weight: 400; font-size: 12px; letter-spacing: 0.02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .when { font-family: VT323, monospace; font-size: 18px; letter-spacing: 0.04em; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .chip { display: inline-block; font-family: VT323, monospace; font-size: 15px; letter-spacing: 0.08em; color: var(--text-2); border: 1px solid var(--line-2); border-radius: 999px; padding: 2px 9px; }

  .tip {
    position: absolute; right: 48px; top: 124px; width: 380px; z-index: 5; border-radius: 14px; border: 1px solid var(--amber); background: rgba(30, 20, 21, 0.97);
    padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; font-size: 13px; color: var(--text-2); align-items: flex-start; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6);
  }
  .tip > b { color: #fff; font-size: 14px; }

  .foot { position: absolute; left: 0; right: 0; bottom: 0; }
  .foot :global(.guide) { height: 64px; }

  /* A shorter window (down to the smallest the app allows): everything moves up a little so
     Jump back in stays clear of the button guide. */
  @media (max-height: 799px) {
    header { top: 22px; }
    nav { top: 112px; }
    .card { height: 290px; }
    .tx { top: 186px; }
    .desc { top: 424px; }
    section { top: 470px; }
  }

  @media (prefers-reduced-motion: reduce) {
    .scene, .gnw, .card.on, .cursor { animation: none; }
    .card, .lbl, .more, .halo, .rec { transition: none; }
  }
</style>

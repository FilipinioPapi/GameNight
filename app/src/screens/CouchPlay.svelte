<script lang="ts" module>
  // Which card was picked last, so coming back lands on the same one.
  let lastPick = 0;
</script>

<script lang="ts">
  // Couch Play (approved board CQ2): host a game or join with a code, and the open lobbies below.
  import Avatar from "../components/Avatar.svelte";
  import ButtonGuide, { type GuideItem } from "../components/ButtonGuide.svelte";
  import { app } from "../lib/state.svelte";
  import { couch, type LobbySummary } from "../lib/couch.svelte";
  import { listGames, type Game } from "../lib/library";
  import { moveFocus, type Dir } from "../lib/gamepad";

  let games = $state<Game[]>([]);
  $effect(() => {
    listGames().then((g) => (games = g));
  });
  const cover = (id: string) => games.find((g) => g.id === id)?.cover;
  let broken = $state<Record<string, boolean>>({});

  // The open lobbies, checked again every 10 seconds while this screen shows.
  $effect(() => {
    void couch.refreshList();
    const t = setInterval(() => void couch.refreshList(), 10_000);
    return () => clearInterval(t);
  });

  const clockText = (d: Date) => {
    const h = d.getHours() % 12 || 12;
    return `${h}:${String(d.getMinutes()).padStart(2, "0")} ${d.getHours() < 12 ? "AM" : "PM"}`;
  };
  let clock = $state(clockText(new Date()));
  $effect(() => {
    const t = setInterval(() => (clock = clockText(new Date())), 5000);
    return () => clearInterval(t);
  });

  const items = [
    { label: "HOST A GAME", sub: "Opens your Library. Pick a game, get a code", desc: "PICK A GAME FROM YOUR LIBRARY", halo: "rgba(236,40,46,.38)", go: () => app.go({ name: "library", console: "nes", host: true }) },
    { label: "JOIN WITH A CODE", sub: "Type the 6-letter code your friend gives you", desc: "GOT A CODE? TYPE IT IN", halo: "rgba(58,110,232,.42)", go: () => app.go({ name: "join" }) },
  ];
  let sel = $state(lastPick);
  const pick = (i: number) => {
    sel = i;
    lastPick = i;
  };
  const cards: HTMLButtonElement[] = [];
  $effect(() => {
    cards[lastPick]?.focus({ preventScroll: true });
  });

  /** "Contra III · 1 watching", "Super Mario Bros. · seat free". */
  function line(l: LobbySummary) {
    const extra = l.watchers > 0 ? `${l.watchers} watching` : l.players < 4 ? "seat free" : "all seats taken";
    return `${l.game.title} · ${extra}`;
  }
  const owner = (l: LobbySummary) => (l.host.id === app.user?.id ? "Your lobby" : `${l.host.name}'s lobby`);

  const ARROWS: Record<string, Dir> = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
  function onKey(e: KeyboardEvent) {
    if (e.ctrlKey || e.altKey || e.metaKey || !ARROWS[e.key]) return;
    e.preventDefault();
    moveFocus(ARROWS[e.key]);
  }

  const guide: GuideItem[] = [
    { buttons: ["a"], label: "Select" },
    { buttons: [], glyph: "◄ ►", label: "Move" },
    { buttons: [], glyph: "▼", label: "Open lobbies" },
    { buttons: ["b"], label: "Main menu" },
  ];
</script>

<svelte:window onkeydown={onKey} />

<div class="page">
  <header>
    <img class="tvlogo" src="/brand/crt-logo.gif" alt="Game Night logo" />
    <div class="hcol"><span class="crumb">GAME NIGHT ›</span><span class="ttl">COUCH PLAY</span></div>
    <div class="right">
      <span class="vt glowtxt clock">{clock}</span>
      {#if app.user}<span class="pill"><Avatar name={app.user.name} src={app.user.avatar} size={30} />{app.user.name}</span>{/if}
    </div>
  </header>

  <nav aria-label="Couch Play">
    {#each items as it, i (it.label)}
      <button class="card" class:on={sel === i} data-autofocus={i === 0 ? "" : undefined} bind:this={cards[i]} onfocus={() => pick(i)} onmouseenter={() => pick(i)} onclick={it.go}>
        <span class="full"><span class="halo" style="--h: {it.halo}"></span></span>
        <span class="tx"><span class="lbl">{it.label}</span><span class="sub">{it.sub}</span></span>
      </button>
    {/each}
  </nav>

  <div class="vt desc" aria-live="polite">&gt; {items[sel].desc}<span class="cursor">_</span></div>

  <section aria-label="Open lobbies">
    <div class="shead"><span class="vt glowtxt slabel">&gt; OPEN LOBBIES</span><span class="hint">Closed lobbies never show here. Only people in your Discord see these.</span></div>
    <div class="rows" data-nav-group>
      {#each couch.list as l (l.code)}
        {@const art = cover(l.game.id)}
        <button class="fr" onclick={() => app.go({ name: "join", code: l.code })}>
          <span class="mini">{#if art && !broken[l.game.id]}<img src={art} alt="" decoding="async" onerror={() => (broken[l.game.id] = true)} />{/if}</span>
          <span class="ftext">
            <b>{owner(l)}</b>
            <span class="fs">{#if l.started}<span class="live"><i></i>LIVE</span>{:else}<span class="wait">WAITING</span>{/if}{line(l)}</span>
          </span>
        </button>
      {:else}
        <div class="fr none">{couch.listLoaded ? "No open lobbies right now. Host one, or ask a friend for their code." : "Looking for open lobbies…"}</div>
      {/each}
    </div>
  </section>

  <div class="foot"><ButtonGuide items={guide} retro note="Nothing is ever listed in public" /></div>
</div>

<style>
  /* Sizes and colours follow the approved board CQ2 (canvas "Couch Play round 2"). */
  .page {
    height: 100%; position: relative; overflow: hidden; isolation: isolate; color: var(--text);
    background: radial-gradient(ellipse at 50% 38%, #3b1417 0% 12%, #2d1012 12% 24%, #210c0e 24% 38%, #170a0b 38% 54%, #0e0707 54% 72%, #070404 72% 100%);
  }
  .vt { font-family: VT323, monospace; letter-spacing: 0.06em; }
  .glowtxt { color: var(--link); text-shadow: 0 0 6px rgba(255, 90, 90, 0.8); }

  header { position: absolute; left: 48px; right: 48px; top: 32px; display: flex; align-items: center; gap: 16px; }
  .tvlogo { display: block; flex-shrink: 0; width: 66px; height: 80px; margin: -6px 2px -6px 0; filter: drop-shadow(0 0 10px rgba(236, 40, 46, 0.35)) drop-shadow(0 4px 0 #000); }
  .hcol { display: flex; flex-direction: column; gap: 8px; }
  .crumb { font-family: VT323, monospace; font-size: 18px; letter-spacing: 0.12em; color: var(--muted); }
  .ttl { font-family: "Press Start 2P", monospace; font-size: 24px; line-height: 1.1; white-space: nowrap; color: #ff2a32; text-shadow: 0 0 3px #ff5a60, 0 0 12px #ec282e, 0 0 26px rgba(236, 40, 46, 0.85), 3px 3px 0 #000; }
  .right { margin-left: auto; display: flex; align-items: center; gap: 18px; }
  .clock { font-size: 26px; }
  .pill { display: flex; align-items: center; gap: 10px; padding: 5px 14px 5px 5px; border-radius: 999px; background: rgba(30, 20, 21, 0.92); border: 1px solid var(--line); font-size: 14px; }

  /* ---- The two cards: the picked one grows (680 / 480 px in the 1280-wide window) ---- */
  nav { position: absolute; left: 48px; right: 48px; top: 150px; display: flex; gap: 24px; align-items: flex-end; }
  .card {
    position: relative; flex: none; width: calc((100% - 24px) * 480 / 1160); height: 340px; box-sizing: border-box; overflow: hidden; padding: 0;
    border-radius: 10px; border: 3px solid #000; background: #120c0c; color: var(--text); font: inherit; text-align: left; cursor: pointer;
    box-shadow: 0 8px 0 rgba(0, 0, 0, 0.5); outline: none;
    transition: width 0.42s cubic-bezier(0.2, 0.8, 0.2, 1), transform 0.28s cubic-bezier(0.2, 0.8, 0.2, 1), border-color 0.28s ease;
  }
  .card::after { content: ""; position: absolute; inset: 6px; border: 2px solid rgba(255, 255, 255, 0.07); border-radius: 5px; pointer-events: none; }
  .card.on { width: calc((100% - 24px) * 680 / 1160); transform: translateY(-12px) scale(1.03); border-color: #ffd36b; animation: neonGold 2.6s ease-in-out infinite; }
  .card:focus-visible { outline: none; }
  :global(body.glide.pad-mode) .card.on:focus { animation: none; border-color: #000; }
  @keyframes neonGold {
    0%, 100% { box-shadow: 0 0 0 1px #fff3c4, 0 0 8px 2px #ffb21e, 0 0 22px 4px rgba(255, 150, 0, 0.65), 0 0 44px 8px rgba(255, 120, 0, 0.25), inset 0 0 12px rgba(255, 170, 40, 0.45); }
    50% { box-shadow: 0 0 0 1px #fff3c4, 0 0 10px 3px #ffc23e, 0 0 28px 6px rgba(255, 160, 0, 0.8), 0 0 56px 12px rgba(255, 130, 0, 0.35), inset 0 0 16px rgba(255, 180, 60, 0.55); }
  }
  /* One smooth colour, like the main menu's cards (Jayden, 2026-10-31: no colour bands). */
  .full { position: absolute; inset: 0; background: #1e0d0f; }
  .halo { position: absolute; left: 50%; top: 40%; width: 240px; height: 240px; margin: -120px 0 0 -120px; border-radius: 50%; background: radial-gradient(circle, var(--h) 0%, transparent 65%); transition: opacity 0.3s ease; }
  .card:not(.on) .halo { opacity: 0.45; }
  .tx { position: absolute; left: 24px; right: 16px; top: 226px; z-index: 1; display: flex; flex-direction: column; align-items: flex-start; gap: 10px; }
  .lbl { font-family: "Press Start 2P", monospace; white-space: nowrap; letter-spacing: 0.02em; line-height: 1.15; color: #fff; font-size: 17px; text-shadow: 0 0 4px #ff6a70, 0 0 12px #ec282e, 0 0 26px rgba(236, 40, 46, 0.7), 3px 3px 0 #000; transition: font-size 0.3s ease; }
  .card.on .lbl { font-size: 30px; color: #fff6d8; text-shadow: 0 0 4px #ffd36b, 0 0 14px #ffb21e, 0 0 30px rgba(255, 140, 0, 0.7), 4px 4px 0 #000; }
  .sub { font-family: VT323, monospace; font-size: 21px; letter-spacing: 0.05em; color: #ffe0e0; white-space: nowrap; opacity: 0; transition: opacity 0.3s ease 0.12s; }
  .card.on .sub { opacity: 1; }

  .desc { position: absolute; left: 50px; top: 516px; font-size: 26px; color: #ffd6d6; text-shadow: 0 0 6px rgba(255, 120, 120, 0.6); }
  .cursor { animation: blink 1.1s steps(1) infinite; }
  @keyframes blink { 50% { opacity: 0; } }

  /* ---- Open lobbies ---- */
  section { position: absolute; left: 48px; right: 48px; top: 568px; display: flex; flex-direction: column; gap: 12px; }
  .shead { display: flex; align-items: center; }
  .slabel { font-size: 22px; }
  .hint { margin-left: auto; font-family: VT323, monospace; font-size: 17px; letter-spacing: 0.05em; color: var(--muted-2); }
  .rows { display: flex; gap: 16px; overflow-x: auto; scrollbar-width: none; padding: 6px; margin: -6px; }
  .fr {
    display: flex; align-items: center; gap: 12px; flex: 1 0 calc((100% - 32px) / 3); min-width: 0; height: 76px; border-radius: 14px; border: 1px solid #4a2427;
    background: rgba(30, 20, 21, 0.85); padding: 12px 14px; box-sizing: border-box; color: var(--text); font: inherit; text-align: left;
    transition: transform 0.18s cubic-bezier(0.2, 0.8, 0.2, 1), border-color 0.18s;
  }
  .fr:hover { border-color: var(--red); }
  :global(body.glide.pad-mode) .fr:focus { transform: scale(1.02); border-color: transparent; }
  .fr.none { border-style: dashed; color: var(--muted-2); font-family: VT323, monospace; font-size: 19px; letter-spacing: 0.04em; }
  .ftext { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .ftext b { font-family: "Press Start 2P", monospace; font-weight: 400; font-size: 12px; letter-spacing: 0.02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .fs { font-family: VT323, monospace; font-size: 18px; letter-spacing: 0.04em; color: var(--muted); display: flex; align-items: center; gap: 7px; white-space: nowrap; overflow: hidden; }
  .mini { width: 52px; height: 52px; border-radius: 6px; border: 2px solid #000; flex-shrink: 0; overflow: hidden; display: flex; align-items: center; justify-content: center; background: linear-gradient(160deg, #4a2f31, #1e1415); }
  .mini img { width: 100%; height: 100%; object-fit: contain; }
  .live { display: inline-flex; align-items: center; gap: 5px; font-size: 15px; letter-spacing: 0.1em; color: var(--link); border: 1px solid var(--red); border-radius: 999px; padding: 0 8px; text-shadow: 0 0 6px rgba(236, 40, 46, 0.8); }
  .live i { width: 7px; height: 7px; border-radius: 50%; background: #ff2a32; box-shadow: 0 0 6px #ff2a32; animation: blink 1.4s steps(1) infinite; }
  .wait { display: inline-flex; align-items: center; font-size: 15px; letter-spacing: 0.1em; color: #ffd36b; border: 1px solid var(--amber); border-radius: 999px; padding: 0 8px; }

  .foot { position: absolute; left: 0; right: 0; bottom: 0; }
  .foot :global(.guide) { height: 64px; gap: 30px; }

  @media (max-height: 799px) {
    header { top: 22px; }
    nav { top: 112px; }
    .card { height: 290px; }
    .tx { top: 186px; }
    .desc { top: 424px; }
    section { top: 470px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .card, .card.on, .cursor, .lbl, .sub, .live i, .fr { animation: none; transition: none; }
  }
</style>

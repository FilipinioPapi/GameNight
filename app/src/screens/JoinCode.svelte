<script lang="ts">
  // Join with a code (approved board CQ5): type the 6-letter code on the pad keyboard (or the real
  // keyboard), see the lobby, then PLAY or WATCH. If the game isn't on this PC it downloads first.
  import { tick } from "svelte";
  import Avatar from "../components/Avatar.svelte";
  import ButtonGuide, { type GuideItem } from "../components/ButtonGuide.svelte";
  import { app } from "../lib/state.svelte";
  import { play } from "../lib/play.svelte";
  import { CODE_LENGTH, CODE_LETTERS, couch, playersFor, type LobbySummary } from "../lib/couch.svelte";
  import { consoleById } from "../lib/consoles";
  import { listGames, type Game } from "../lib/library";
  import { moveFocus, useScreenButtons, type Dir } from "../lib/gamepad";

  let { code: startCode = "" }: { code?: string } = $props();

  let games = $state<Game[]>([]);
  $effect(() => {
    listGames().then((g) => (games = g));
  });

  let code = $state("");
  let found = $state<LobbySummary | null>(null);
  let lookError = $state("");
  let looking = $state(false);
  let choice = $state<0 | 1>(0);
  let picked = $state("");
  let joining = $state(false);
  let broken = $state(false);

  const keys = [...CODE_LETTERS.split(""), "DELETE", "CLEAR"];
  const keyEls: HTMLButtonElement[] = [];
  let playBtn = $state<HTMLButtonElement | null>(null);
  let watchBtn = $state<HTMLButtonElement | null>(null);

  // Coming from the open lobbies list: the code is already filled in.
  let started = false;
  $effect(() => {
    if (started) return;
    started = true;
    const c = startCode.toUpperCase().split("").filter((ch) => CODE_LETTERS.includes(ch)).join("").slice(0, CODE_LENGTH);
    code = c;
    if (c.length === CODE_LENGTH) void find();
    else void tick().then(() => keyEls[0]?.focus({ preventScroll: true }));
  });

  async function find() {
    const c = code;
    looking = true;
    lookError = "";
    found = null;
    picked = "";
    try {
      const l = await couch.lookup(c);
      if (code !== c) return; // typed on meanwhile
      found = l;
      broken = false;
      choice = l.players >= 4 ? 1 : 0;
      await tick();
      (choice === 0 ? playBtn : watchBtn)?.focus({ preventScroll: true });
    } catch (e) {
      const msg = String(e).replace(/^Error:\s*/, "");
      if (msg === "signed-out") app.signedOut();
      if (code === c) lookError = msg;
    } finally {
      looking = false;
    }
  }

  function type(ch: string) {
    if (joining || code.length >= CODE_LENGTH) return;
    code += ch;
    if (code.length === CODE_LENGTH) void find();
  }
  function del() {
    if (joining || !code) return;
    code = code.slice(0, -1);
    found = null;
    lookError = "";
    picked = "";
  }
  function clear() {
    if (joining) return;
    code = "";
    found = null;
    lookError = "";
    picked = "";
  }
  function press(k: string) {
    if (k === "DELETE") del();
    else if (k === "CLEAR") clear();
    else type(k);
  }

  const max = $derived(found ? playersFor(found.game.id, games) : 4);
  const full = $derived(!!found && found.players >= 4);
  const freeSeat = $derived(found ? Math.min(4, found.players + 1) : 4);
  const art = $derived(found ? games.find((g) => g.id === found!.game.id)?.cover : undefined);
  const dl = $derived(found ? play.progress[found.game.id] : undefined);
  const dlPct = $derived(dl && dl.total ? Math.round((dl.done / dl.total) * 100) : 0);

  async function join(as: "play" | "watch") {
    if (!found || joining) return;
    choice = as === "play" ? 0 : 1;
    if (as === "play" && full) {
      picked = "All 4 seats are taken. You can watch.";
      return;
    }
    picked = as === "play" ? `You chose PLAY. Joining as P${freeSeat}…` : "You chose WATCH. Joining as a watcher…";
    joining = true;
    const ok = await couch.join(found.code, as, found.game);
    joining = false;
    if (ok) app.route = { name: "lobby" };
    else picked = couch.error || "That didn't work. Try again.";
  }

  // ---- Controller: X deletes, Start joins ----
  $effect(() => {
    useScreenButtons((input) => {
      if (input === "x") {
        del();
        return true;
      }
      if (input === "menu") {
        void join(choice === 0 ? "play" : "watch");
        return true;
      }
      return false;
    });
    return () => useScreenButtons(null);
  });

  // ---- Keyboard: typing works too ----
  const ARROWS: Record<string, Dir> = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
  function onKey(e: KeyboardEvent) {
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    if (ARROWS[e.key]) {
      e.preventDefault();
      moveFocus(ARROWS[e.key]);
      return;
    }
    if (e.key === "Backspace" || e.key === "Delete") {
      e.preventDefault();
      del();
      return;
    }
    if (e.key === "Enter" && found && !(document.activeElement instanceof HTMLButtonElement)) {
      e.preventDefault();
      void join(choice === 0 ? "play" : "watch");
      return;
    }
    const ch = e.key.length === 1 ? e.key.toUpperCase() : "";
    if (ch && CODE_LETTERS.includes(ch)) {
      e.preventDefault();
      type(ch);
    }
  }

  const guide: GuideItem[] = [
    { buttons: ["a"], label: "Type / choose" },
    { buttons: ["x"], label: "Delete" },
    { buttons: ["start"], label: "Join" },
    { buttons: ["b"], label: "Back" },
  ];
</script>

<svelte:window onkeydown={onKey} />

<div class="page">
  <header>
    <img class="tvlogo" src="/brand/crt-logo.gif" alt="Game Night logo" />
    <div class="hcol"><span class="crumb">GAME NIGHT › COUCH PLAY ›</span><span class="ttl">JOIN WITH A CODE</span></div>
    <div class="right">{#if app.user}<span class="pill"><Avatar name={app.user.name} src={app.user.avatar} size={30} />{app.user.name}</span>{/if}</div>
  </header>

  <section class="left" aria-label="Type the code">
    <span class="vt glowtxt" style="font-size: 22px">&gt; TYPE THE 6-LETTER CODE</span>
    <div class="boxes" aria-live="polite" aria-label="Code so far: {code.split('').join(' ') || 'empty'}">
      {#each Array(CODE_LENGTH) as _, i (i)}
        <span class="cb" class:now={i === code.length}>{code[i] ?? ""}</span>
      {/each}
    </div>
    <div class="keys" data-nav-group>
      {#each keys as k, i (k)}
        <button class="key" class:wide={k.length > 1} bind:this={keyEls[i]} data-autofocus={i === 0 ? "" : undefined} onclick={() => press(k)}>{k}</button>
      {/each}
    </div>
    <span class="note">Codes never use O, 0, I or 1, so nothing gets mixed up. 6 letters means codes are very hard to guess. Keyboard typing works too.</span>
  </section>

  <section class="panel" aria-label="Lobby">
    {#if found}
      {@const c = consoleById(found.game.console)}
      <span class="pt">{found.host.id === app.user?.id ? "YOUR LOBBY" : `${found.host.name.toUpperCase()}'S LOBBY`}</span>
      <div class="mini">
        {#if art && !broken}<img src={art} alt="" decoding="async" onerror={() => (broken = true)} />{:else}<span class="mtitle {c.font}">{found.game.title}</span>{/if}
        {#if found.started}<span class="ov"><i></i>LIVE</span>{:else}<span class="ov wait">WAITING</span>{/if}
      </div>
      <div class="facts">
        <span>{found.game.title} · {c.short} · {max === 1 ? "1 player" : `up to ${max} players`}</span>
        <span>{found.players} playing · {found.watchers} watching · {full ? "all 4 seats are taken" : `P${freeSeat} is free`}</span>
      </div>
      <span class="picked" class:bad={!!couch.error && !joining && picked === couch.error}>{dl ? `Downloading ${found.game.title}… ${dlPct}%` : joining && couch.busy ? couch.busy : picked}</span>
      {#if dl}<div class="bar" role="progressbar" aria-valuenow={dlPct} aria-valuemin="0" aria-valuemax="100"><div style="width:{dlPct}%"></div></div>{/if}
      <div class="choices" data-nav-group>
        <button class="ch play" class:full bind:this={playBtn} onfocus={() => (choice = 0)} onclick={() => join("play")}><b>PLAY</b><span>{full ? "All 4 seats are taken" : `Take seat P${freeSeat}`}</span></button>
        <button class="ch watch" bind:this={watchBtn} onfocus={() => (choice = 1)} onclick={() => join("watch")}><b>WATCH</b><span>Switch to playing any time</span></button>
      </div>
    {:else}
      <div class="ph">
        {#if looking}Looking for that lobby…
        {:else if lookError}<span>{lookError}<br /><span class="phs">Press X to fix a letter.</span></span>
        {:else}Type the code to see the lobby{/if}
      </div>
    {/if}
  </section>

  <div class="foot"><ButtonGuide items={guide} retro /></div>
</div>

<style>
  /* Sizes and colours follow the approved board CQ5 (canvas "Couch Play round 2"). */
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
  .pill { display: flex; align-items: center; gap: 10px; padding: 5px 14px 5px 5px; border-radius: 999px; background: rgba(30, 20, 21, 0.92); border: 1px solid var(--line); font-size: 14px; }
  @keyframes neonGold {
    0%, 100% { box-shadow: 0 0 0 1px #fff3c4, 0 0 8px 2px #ffb21e, 0 0 22px 4px rgba(255, 150, 0, 0.65), 0 0 44px 8px rgba(255, 120, 0, 0.25), inset 0 0 12px rgba(255, 170, 40, 0.45); }
    50% { box-shadow: 0 0 0 1px #fff3c4, 0 0 10px 3px #ffc23e, 0 0 28px 6px rgba(255, 160, 0, 0.8), 0 0 56px 12px rgba(255, 130, 0, 0.35), inset 0 0 16px rgba(255, 180, 60, 0.55); }
  }
  @keyframes blink { 50% { opacity: 0; } }

  /* ---- The code and the pad keyboard ---- */
  .left { position: absolute; left: 48px; top: 146px; width: 604px; display: flex; flex-direction: column; gap: 18px; }
  .boxes { display: flex; gap: 15px; }
  .cb { width: 88px; height: 100px; border-radius: 10px; border: 2px solid var(--line-2); background: rgba(10, 6, 6, 0.8); display: flex; align-items: center; justify-content: center; font-family: "Press Start 2P", monospace; font-size: 34px; color: #fff6d8; text-shadow: 0 0 4px #ffd36b, 0 0 14px #ffb21e, 3px 3px 0 #000; }
  .cb.now { border-color: #ffd36b; animation: neonGold 2.6s ease-in-out infinite; }
  .cb.now::after { content: "_"; color: #ffd36b; animation: blink 1.1s steps(1) infinite; }
  .keys { display: grid; grid-template-columns: repeat(9, minmax(0, 1fr)); gap: 8px; }
  .key { height: 56px; border-radius: 8px; border: 1px solid #4a2427; background: rgba(30, 20, 21, 0.9); box-shadow: 0 4px 0 rgba(0, 0, 0, 0.5); color: var(--text); font-family: "Press Start 2P", monospace; font-size: 14px; padding: 0; transition: transform 0.12s; }
  .key.wide { grid-column: span 2; font-size: 9px; color: #ffd6d6; }
  .key:hover { border-color: #ffd36b; }
  :global(body.glide.pad-mode) .key:focus { border-color: transparent; }
  .key:active { transform: translateY(2px); }
  .note { font-family: VT323, monospace; font-size: 19px; letter-spacing: 0.04em; color: var(--muted); }

  /* ---- The lobby the code belongs to ---- */
  .panel { position: absolute; left: 700px; right: 48px; top: 146px; height: 530px; border-radius: 14px; border: 2px solid var(--line-2); background: rgba(30, 20, 21, 0.92); box-shadow: 0 8px 0 rgba(0, 0, 0, 0.5); padding: 24px; box-sizing: border-box; display: flex; flex-direction: column; gap: 14px; }
  .ph { flex: 1; display: flex; align-items: center; justify-content: center; text-align: center; font-family: VT323, monospace; font-size: 24px; letter-spacing: 0.05em; color: var(--muted-2); }
  .phs { font-size: 19px; }
  .pt { font-family: "Press Start 2P", monospace; font-size: 15px; color: #fff6d8; text-shadow: 0 0 4px #ffd36b, 0 0 14px #ffb21e, 3px 3px 0 #000; }
  .mini { height: 150px; flex-shrink: 0; border-radius: 8px; border: 3px solid #000; position: relative; overflow: hidden; display: flex; align-items: center; justify-content: center; background: linear-gradient(160deg, #4a2f31, #1e1415); }
  .mini img { height: 100%; width: 100%; object-fit: contain; }
  .mtitle { font-size: 18px; padding: 0 20px; text-align: center; color: #fff; }
  .ov { position: absolute; left: 8px; top: 8px; display: flex; align-items: center; gap: 6px; font-family: VT323, monospace; font-size: 17px; letter-spacing: 0.08em; background: rgba(10, 6, 6, 0.82); border-radius: 6px; padding: 1px 8px; color: #ffe0e0; }
  .ov i { width: 8px; height: 8px; border-radius: 50%; background: #ff2a32; box-shadow: 0 0 6px #ff2a32; animation: blink 1.4s steps(1) infinite; }
  .ov.wait { color: #ffd36b; }
  .facts { display: flex; flex-direction: column; gap: 6px; font-family: VT323, monospace; font-size: 20px; letter-spacing: 0.04em; color: #ffe0e0; }
  .picked { font-family: VT323, monospace; font-size: 20px; letter-spacing: 0.05em; color: #9fdcb0; text-shadow: 0 0 6px rgba(127, 214, 154, 0.5); min-height: 22px; }
  .picked.bad { color: #ffd36b; text-shadow: 0 0 6px rgba(242, 180, 90, 0.5); }
  .bar { height: 8px; border-radius: 4px; background: var(--btn); overflow: hidden; flex-shrink: 0; }
  .bar div { height: 100%; background: var(--amber); transition: width 0.2s; }
  .choices { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: auto; }
  .ch { height: 96px; border-radius: 12px; border: 2px solid #000; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: #fff; font: inherit; padding: 0; }
  .ch b { font-family: "Press Start 2P", monospace; font-weight: 400; font-size: 16px; text-shadow: 2px 2px 0 #000; }
  .ch span { font-family: VT323, monospace; font-size: 18px; letter-spacing: 0.04em; }
  .ch.play { background: linear-gradient(180deg, #ce1a22, #8a1016); }
  .ch.play.full { opacity: 0.6; }
  .ch.watch { background: linear-gradient(180deg, #2c1c1d, #1a1011); border-color: var(--line-2); }
  .ch:hover { border-color: #ffd36b; }
  :global(body.glide.pad-mode) .ch:focus { border-color: #000; }

  .foot { position: absolute; left: 0; right: 0; bottom: 0; }
  .foot :global(.guide) { height: 64px; gap: 30px; }

  @media (max-height: 799px) {
    header { top: 22px; }
    .left, .panel { top: 120px; }
    .panel { height: 500px; }
    .cb { height: 84px; }
    .key { height: 50px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .cb.now, .cb.now::after, .ov i { animation: none; }
  }
</style>

<script lang="ts">
  import { play } from "../lib/play.svelte";
  import Brand from "../components/Brand.svelte";
  import Avatar from "../components/Avatar.svelte";
  import PadGlyph from "../components/PadGlyph.svelte";
  import { app } from "../lib/state.svelte";
  import { consoleById } from "../lib/consoles";
  import { loadLibrary, localInfo, type Game, type Library } from "../lib/library";
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
  // A wall of game tiles behind the menu, like the mockup.
  const wall = $derived(games.slice(0, 12));

  $effect(() => {
    void updates.check();
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
  }

  let playBtn: HTMLButtonElement;
  $effect(() => playBtn?.focus());
  $effect(() => {
    play.refresh();
  });
</script>

<div class="page">
  <div class="wall" aria-hidden="true">
    {#each wall as g (g.id)}
      {@const c = consoleById(g.console)}
      <div class="tile"><span class="chip">{c.short.toUpperCase()}</span><span class={c.font} style="font-size:{c.id === 'nes' ? 12 : 20}px;line-height:1.3">{g.title}</span></div>
    {/each}
  </div>
  <div class="fade" aria-hidden="true"></div>

  <div class="left">
    <Brand size="lg" />
    <nav aria-label="Main menu">
      <button class="mi play" data-autofocus bind:this={playBtn} onclick={() => app.go({ name: "library", console: "fav" })}>
        <span class="ico"><svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4l13 8-13 8z" /></svg></span>
        <span class="words"><span class="lucky big">PLAY</span><span class="sub">{games.length} games in the library · {onPC} on this PC</span></span>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
      </button>
      <button class="mi" disabled title="Coming in step 2">
        <span class="ico"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="2" y="8" width="20" height="10" rx="5" /><path d="M7 11v4M5 13h4" /><circle cx="16" cy="12" r="1" /><circle cx="18.5" cy="14" r="1" /></svg></span>
        <span class="words"><span class="lucky big">COUCH CO-OP</span><span class="sub">Play online with friends · <span class="soon">coming next</span></span></span>
      </button>
      <button class="mi" onclick={() => app.go({ name: "settings", tab: "consoles", console: "nes" })}>
        <span class="ico"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" /></svg></span>
        <span class="lucky mid">SETTINGS</span>
      </button>
      <button class="mi" onclick={quitApp}>
        <span class="ico"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3v9" /><path d="M6.3 7.5a8 8 0 1 0 11.4 0" /></svg></span>
        <span class="lucky mid">QUIT</span>
      </button>
    </nav>
    {#if steamTip}
      <div class="tip" role="note">
        <b>Tip: stop the Xbox button opening Steam</b>
        <span>Steam is open. In Steam, go to <b>Settings</b>, then <b>Controller</b>, and turn off <b>"Guide Button Focuses Steam"</b>. Then the Xbox / PS button only opens Game Night.</span>
        <button class="btn small" onclick={closeSteamTip}>Got it</button>
      </div>
    {/if}
  </div>

  <div class="top-right">
    {#if updates.offered && updates.info}<button class="chip-pill update" onclick={() => updates.open()}><span class="dot"></span>Update ready: v{updates.info.version}</button>{/if}
    {#if lib?.source === "sample"}<span class="chip-pill"><span class="dot"></span>Preview: sample games</span>
    {:else if lib?.error}<span class="chip-pill"><span class="dot"></span>{lib.error}</span>
    {:else if lib?.source === "offline"}<span class="chip-pill"><span class="dot"></span>Offline: showing the last list</span>{/if}
    {#if app.user}<span class="chip-pill user"><Avatar name={app.user.name} src={app.user.avatar} />{app.user.name}</span>{/if}
  </div>

  <footer>
    <span class="hint"><PadGlyph pad={app.viewPad} input="a" />Select</span>
    <span class="hint"><PadGlyph pad={app.viewPad} input="b" />Back</span>
    <span class="ver">v{VERSION}</span>
  </footer>
</div>

<style>
  .page { height: 100%; position: relative; overflow: hidden; }
  .wall { position: absolute; right: -60px; top: -70px; width: 860px; height: 960px; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; transform: rotate(-6deg); opacity: 0.55; }
  .tile { border-radius: 12px; border: 1px solid var(--line); display: flex; flex-direction: column; justify-content: flex-end; gap: 6px; padding: 14px; height: 230px; background: linear-gradient(160deg, #4a2f31, #1e1415); }
  .tile:nth-child(3n) { background: linear-gradient(160deg, #5a2224, #2c1c1d); }
  .tile:nth-child(3n + 1) { background: linear-gradient(160deg, #3a2526, #120c0c); }
  .chip { font-size: 11px; font-weight: 700; letter-spacing: 0.08em; color: var(--muted); }
  .fade { position: absolute; inset: 0; background: linear-gradient(90deg, var(--bg) 0%, var(--bg) 46%, rgba(18, 12, 12, 0.6) 72%, rgba(18, 12, 12, 0.2) 100%), linear-gradient(0deg, var(--bg), rgba(18, 12, 12, 0) 160px); }

  .left { position: absolute; left: 80px; top: 56px; width: 560px; display: flex; flex-direction: column; }
  nav { margin-top: 44px; display: flex; flex-direction: column; gap: 8px; }
  .mi { display: flex; align-items: center; gap: 18px; border: 2px solid transparent; border-radius: 14px; background: transparent; color: var(--text); text-align: left; height: 64px; padding: 0 20px; }
  .mi:hover:not(:disabled), .mi:focus-visible { border-color: var(--line-2); background: rgba(44, 28, 29, 0.6); outline: none; }
  .mi:disabled { opacity: 0.6; }
  .mi.play, .mi:has(.big) { height: 84px; }
  .mi.play { background: var(--red-2); border-color: #000; box-shadow: 0 4px 0 #000; }
  .mi.play:hover, .mi.play:focus-visible { background: var(--red); border-color: #000; }
  .ico { width: 44px; height: 44px; border-radius: 12px; background: var(--btn); border: 1px solid var(--line-2); display: flex; align-items: center; justify-content: center; flex-shrink: 0; color: var(--link); }
  .play .ico { background: var(--bg); border-color: #000; color: #fff; }
  .words { display: flex; flex-direction: column; gap: 4px; flex: 1; }
  .big { font-size: 38px; line-height: 1; }
  .mid { font-size: 30px; }
  .play .big { color: #fff; }
  .sub { font-size: 14px; color: var(--muted); }
  .play .sub { color: #fff; font-weight: 500; }
  .soon { color: var(--amber); }

  .tip { margin-top: 20px; border-radius: 14px; border: 1px solid var(--amber); background: rgba(30, 20, 21, 0.95); padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; font-size: 13px; color: var(--text-2); align-items: flex-start; }
  .tip > b { color: #fff; font-size: 14px; }
  .top-right { position: absolute; right: 44px; top: 36px; display: flex; align-items: center; gap: 12px; }
  .chip-pill { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); padding: 8px 14px; border-radius: 999px; background: rgba(30, 20, 21, 0.92); border: 1px solid var(--line); }
  .chip-pill.user { padding: 5px 14px 5px 5px; font-size: 14px; gap: 10px; }
  .update { cursor: pointer; border-color: var(--amber); color: #fff; font-weight: 600; animation: glow 1.6s ease-in-out infinite; }
  .update:hover, .update:focus-visible { background: #2a1f14; }
  @keyframes glow { 50% { box-shadow: 0 0 12px 1px rgba(242, 180, 90, 0.45); } }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--amber); }

  footer { position: absolute; left: 0; right: 0; bottom: 0; height: 64px; display: flex; align-items: center; gap: 28px; padding: 0 80px; border-top: 1px solid var(--line-soft); background: rgba(18, 12, 12, 0.92); font-size: 13px; color: var(--muted); }
  .hint { display: inline-flex; align-items: center; gap: 8px; }
  .ver { margin-left: auto; color: var(--muted-2); }
</style>

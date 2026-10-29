<script lang="ts">
  import Brand from "../components/Brand.svelte";
  import PadGlyph from "../components/PadGlyph.svelte";
  import { app } from "../lib/state.svelte";
  import { formatGB, gamesFolder, pickFolder, suggestFolders, type FolderChoice } from "../lib/native";
  import { PAD_NAME } from "../lib/pads";

  let { step }: { step: 2 | 3 } = $props();

  let choices = $state<FolderChoice[]>([]);
  let custom = $state<string | null>(null);
  let selected = $state<string>("");

  $effect(() => {
    suggestFolders().then((c) => {
      choices = c;
      if (!selected) selected = app.settings.romsFolder || c.find((x) => x.recommended)?.path || c[0]?.path || "";
    });
  });

  async function chooseOther() {
    const p = await pickFolder();
    if (p) {
      custom = await gamesFolder(p);
      selected = custom;
    }
  }

  function next() {
    app.settings.romsFolder = selected;
    app.save();
    app.route = { name: "firstrun", step: 3 };
  }

  function finish() {
    app.settings.firstRunDone = true;
    app.save();
    app.home();
  }

  const used = (c: FolderChoice) => (c.total ? (c.total - c.free) / c.total : 0);
</script>

<div class="page">
  <aside>
    <Brand size="md" />
    <p class="welcome">Welcome, {app.user?.name}. Three quick steps and you're playing.</p>
    <ol>
      <li class="done"><span class="dot">✓</span>Signed in with Discord</li>
      <li class:now={step === 2} class:done={step > 2}><span class="dot">{step > 2 ? "✓" : "2"}</span>Where to keep games</li>
      <li class:now={step === 3}><span class="dot">3</span>Set up your controller</li>
    </ol>
    <p class="later">You can change all of this later in Settings.</p>
  </aside>

  <main>
    {#if step === 2}
      <div class="kicker">STEP 2 OF 3</div>
      <h1 class="lucky">WHERE SHOULD GAMES GO?</h1>
      <p class="lead">Every game you download goes into one folder. Pick a drive with some room: old games are tiny, but GameCube and PS2 games can be a few GB each.</p>

      <div class="opts">
        {#each choices as c (c.path)}
          <button class="opt" class:sel={selected === c.path} onclick={() => (selected = c.path)}>
            <span class="radio"></span>
            <span class="txt">
              <b>{c.drive} {c.label}{#if c.recommended}<span class="rec">&nbsp;· recommended</span>{/if}</b>
              <span>{c.path}</span>
            </span>
            <span class="space">
              <span class:low={c.free < 100 * 1024 ** 3}>{formatGB(c.free)} free of {formatGB(c.total)}</span>
              <span class="bar"><span style="width:{used(c) * 100}%" class:low={c.free < 100 * 1024 ** 3}></span></span>
            </span>
          </button>
        {/each}
        {#if custom}
          <button class="opt" class:sel={selected === custom} onclick={() => (selected = custom!)}>
            <span class="radio"></span>
            <span class="txt"><b>Your folder</b><span>{custom}</span></span>
          </button>
        {/if}
        <button class="opt other" onclick={chooseOther}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#FF8A8F" stroke-width="1.8" aria-hidden="true"><path d="M3 6h6l2 2h10v11H3z" /></svg>
          <b>Choose a different folder…</b>
        </button>
      </div>
      <p class="safe">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#7FD69A" stroke-width="2" aria-hidden="true"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /></svg>
        Your saves are backed up to the Game Night server, not this folder, so you can wipe it any time.
      </p>
      <div class="actions">
        <button class="btn" onclick={() => app.back()} disabled={app.history.length === 0}>Back</button>
        <button class="btn primary" onclick={next} disabled={!selected}>Next: controller</button>
      </div>
    {:else}
      <div class="kicker">STEP 3 OF 3</div>
      <h1 class="lucky">PLUG IN YOUR CONTROLLER</h1>
      <p class="lead">Game Night is built for Xbox and PlayStation 5 (DualSense) controllers. Plug yours in with a cable or connect it over Bluetooth.</p>
      <div class="padbox" class:found={app.pad.connected}>
        {#if app.pad.connected}
          <div class="found-line"><span class="ok">●</span> {PAD_NAME[app.pad.type]} controller found</div>
          <div class="glyphs">
            <PadGlyph pad={app.pad.type} input="a" /><PadGlyph pad={app.pad.type} input="b" /><PadGlyph pad={app.pad.type} input="x" /><PadGlyph pad={app.pad.type} input="y" />
          </div>
          <p>Every button prompt in Game Night will match this controller. Each console starts with the buttons in the same spots as the original, and you can change them any time in Settings.</p>
        {:else}
          <div class="found-line"><span class="wait">●</span> Waiting for a controller…</div>
          <p>Press any button on it if it's already plugged in. No controller? You can still carry on and set one up later.</p>
        {/if}
      </div>
      <div class="actions">
        <button class="btn" onclick={() => (app.route = { name: "firstrun", step: 2 })}>Back</button>
        <button class="btn primary" onclick={finish}>Let's play</button>
      </div>
    {/if}
  </main>
</div>

<style>
  .page { height: 100%; display: flex; }
  aside { width: 340px; flex-shrink: 0; background: var(--bg-side); border-right: 1px solid var(--line-soft); padding: 40px 32px; display: flex; flex-direction: column; }
  .welcome { font-size: 15px; line-height: 1.5; color: var(--muted); margin: 24px 0 20px; }
  ol { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 14px; }
  li { display: flex; align-items: center; gap: 12px; font-size: 14px; color: var(--muted-2); }
  li.done { color: var(--green); }
  li.now { color: var(--text); font-weight: 600; }
  .dot { width: 30px; height: 30px; border-radius: 50%; border: 1px solid var(--line-2); display: inline-flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; }
  li.done .dot { background: var(--green-bg); border-color: var(--green-bg); color: #fff; }
  li.now .dot { background: var(--red-2); border-color: var(--red-2); color: #fff; }
  .later { margin-top: auto; font-size: 12px; color: var(--muted-2); }

  main { flex: 1; padding: 56px 64px 56px; display: flex; flex-direction: column; min-width: 0; }
  .kicker { font-size: 12px; font-weight: 700; letter-spacing: 0.1em; color: var(--link); }
  h1 { font-size: 40px; font-weight: 400; margin: 14px 0 18px; }
  .lead { font-size: 15px; line-height: 1.6; color: var(--muted); max-width: 640px; margin: 0 0 24px; }
  .opts { display: flex; flex-direction: column; gap: 10px; max-width: 700px; }
  .opt { display: flex; align-items: center; gap: 16px; padding: 16px 18px; border-radius: 12px; border: 1px solid var(--line); background: var(--panel); text-align: left; }
  .opt.sel { border: 2px solid var(--red); background: #2a1718; padding: 15px 17px; }
  .opt.other { border-style: dashed; }
  .radio { width: 20px; height: 20px; border-radius: 50%; border: 2px solid var(--line-2); flex-shrink: 0; }
  .opt.sel .radio { border-color: #fff; background: radial-gradient(circle, #fff 0 4px, var(--red-2) 5px); }
  .txt { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0; }
  .txt b { font-size: 15px; }
  .txt span { font-size: 13px; color: var(--muted); }
  .rec { color: var(--green) !important; font-weight: 400; font-size: 13px; }
  .space { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; font-size: 13px; color: var(--text-2); }
  .space .low { color: var(--amber); }
  .bar { width: 180px; height: 6px; border-radius: 3px; background: var(--btn); overflow: hidden; }
  .bar span { display: block; height: 100%; background: var(--red); }
  .bar span.low { background: var(--amber); }
  .safe { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--muted); margin: 18px 0 0; }
  .actions { margin-top: auto; display: flex; gap: 12px; }
  .actions .btn { height: 48px; padding: 0 22px; font-size: 15px; }
  .padbox { max-width: 640px; border-radius: 14px; border: 1px solid var(--line); background: var(--panel); padding: 22px; }
  .padbox.found { border-color: var(--green-bg); }
  .found-line { font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 10px; }
  .ok { color: #3ba55d; }
  .wait { color: var(--amber); }
  .glyphs { display: flex; gap: 8px; margin: 16px 0 4px; }
  .padbox p { font-size: 14px; line-height: 1.6; color: var(--muted); margin: 12px 0 0; }
</style>

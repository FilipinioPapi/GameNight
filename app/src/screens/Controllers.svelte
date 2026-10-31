<script lang="ts">
  // Controller setup: the original console's controller on the left, your buttons on the right.
  // Hovering (or changing) a row lights up that button's label tag on the diagram.
  import TopBar from "../components/TopBar.svelte";
  import PadGlyph from "../components/PadGlyph.svelte";
  import { app } from "../lib/state.svelte";
  import { CONSOLES, consoleById, type ConsoleId } from "../lib/consoles";
  import { LAYOUTS, DIRECTION_INPUTS, isDirectionRow, type DiagramView } from "../lib/controllers";
  import { PAD_NAME, type PadInput, type PadType } from "../lib/pads";
  import { captureNext } from "../lib/gamepad";

  let { console: cid }: { console: ConsoleId } = $props();

  const info = $derived(consoleById(cid));
  const layout = $derived(LAYOUTS[cid]);
  const pad = $derived(app.viewPad);
  const map = $derived(app.mapping(cid, pad));
  const presetId = $derived(app.presetId(cid, pad));

  let hover = $state<string | null>(null);
  let listening = $state<string | null>(null);
  let problem = $state("");
  const lit = $derived(listening ?? hover);

  const pickConsole = (id: ConsoleId) => {
    stopListening();
    app.route = { name: "settings", tab: "controllers", console: id };
  };
  const setPad = (p: PadType) => (app.viewPad = p);

  function startListening(key: string) {
    problem = "";
    listening = key;
    const wantDirection = isDirectionRow(key);
    const accept = (input: PadInput) => {
      if (listening !== key) return;
      if (input === "home") {
        problem = "That button always opens the Game Night menu. Pick another one.";
        captureNext(accept);
        return;
      }
      if (wantDirection !== DIRECTION_INPUTS.includes(input)) {
        problem = wantDirection ? "This one needs a stick or the D-pad." : "This one needs a button, not a stick or the D-pad.";
        captureNext(accept);
        return;
      }
      app.setButton(cid, pad, key, input);
      listening = null;
      problem = "";
    };
    captureNext(accept);
  }
  function stopListening() {
    listening = null;
    problem = "";
    captureNext(null);
  }
  $effect(() => () => captureNext(null));

  const shortName = $derived(info.short === "Arcade" ? "ARCADE" : info.short.toUpperCase());
</script>

{#snippet diagram(v: DiagramView)}
  <div class="view">
    <span class="vlab">{v.label}</span>
    <div class="dg" style="width:{v.width}%;aspect-ratio:{v.ratio}">
      <img src="/ctl/{v.img}.webp" alt="{info.name} controller, {v.label.toLowerCase()} view" draggable="false" />
      {#each v.spots as s, i (i)}
        <span class="hs" class:pill={v.tag === "pill"} class:on={lit === s.key} style="left:{s.l}%;top:{s.t}%;width:{s.w}%;height:{s.h}%"></span>
      {/each}
    </div>
  </div>
{/snippet}

{#snippet row(key: string, label: string, hint: string | undefined, alsoStick: boolean | undefined)}
  {@const input = map[key]}
  <div class="map" class:listen={listening === key} role="group" aria-label={label}
    onmouseenter={() => (hover = key)} onmouseleave={() => (hover = null)}>
    <span class="from">{label}{#if hint}<span class="hint">{hint}</span>{/if}</span>
    <span class="arrow">→</span>
    {#if listening === key}
      <span class="press">Press a button…</span>
      <span class="now">now {#if input}<PadGlyph {pad} {input} />{/if}</span>
      <button class="chg" onclick={stopListening}>Cancel</button>
    {:else}
      {#if input}<PadGlyph {pad} {input} />{/if}
      {#if alsoStick && input === "dpad"}<span class="or">or</span><PadGlyph {pad} input="ls" />{/if}
      <button class="chg" onclick={() => startListening(key)} disabled={!app.pad.connected || app.pad.type !== pad}
        title={!app.pad.connected ? "Plug in a controller to change buttons" : app.pad.type !== pad ? `Plug in a ${PAD_NAME[pad]} controller to change these` : ""}>Change</button>
    {/if}
  </div>
{/snippet}

<div class="page">
  <TopBar compact backLabel="Settings" where="Controllers">
    {#snippet right()}
      <span class="status">
        {#if app.pad.connected}<span class="dot ok"></span>{PAD_NAME[app.pad.type]} controller plugged in
        {:else}<span class="dot"></span>No controller plugged in{/if}
      </span>
      <div class="seg" role="group" aria-label="Button icons">
        <button class:on={pad === "xbox"} onclick={() => setPad("xbox")}>Xbox</button>
        <button class:on={pad === "dualsense"} onclick={() => setPad("dualsense")}>DualSense</button>
      </div>
    {/snippet}
  </TopBar>

  <div class="tiles">
    {#each CONSOLES as c (c.id)}
      <button class="tile" class:sel={c.id === cid} onclick={() => pickConsole(c.id)}>
        <span class="ph"><img src="/ctl/clean/{c.thumb}.webp" alt="" /></span>
        <span class={c.font} style="font-size:{Math.min(c.navSize, 13)}px;line-height:1.1">{c.short}</span>
      </button>
    {/each}
  </div>

  <main>
    <section class="left scroll">
      <div class="title"><span class={info.font} style="font-size:{info.id === 'nes' ? 15 : 20}px">{shortName} CONTROLLER</span><span class="tip">hover a button on the right to find it here</span></div>
      {#each layout.above as v (v.img)}{@render diagram(v)}{/each}
      {@render diagram(layout.front)}
      {#each layout.below as v (v.img)}{@render diagram(v)}{/each}
      {#if layout.note}<p class="note">{layout.note}</p>{/if}
    </section>

    <section class="right scroll">
      {#if layout.presets.length > 1}
        <div class="presets">
          <span class="label">BUTTON LAYOUT</span>
          <span class="seg small">
            {#each layout.presets as p (p.id)}
              <button class:on={presetId === p.id} onclick={() => app.choosePreset(cid, pad, p.id)}>{p.name}</button>
            {/each}
          </span>
        </div>
      {/if}
      <div class="label">{shortName} BUTTON → YOUR {PAD_NAME[pad].toUpperCase()} BUTTON</div>
      {#each layout.buttons as b (b.key)}{@render row(b.key, b.label, b.hint, b.alsoStick)}{/each}
      {#if problem}<p class="problem">{problem}</p>{/if}

      <div class="label extras">GAME NIGHT EXTRAS</div>
      {#each layout.extras as b (b.key)}{@render row(b.key, b.label, b.hint, false)}{/each}
      <div class="map fixed">
        <span class="from">Game Night menu</span><span class="arrow">→</span><PadGlyph {pad} input="home" /><span class="or">can't be changed</span>
      </div>

      <div class="foot">
        <div class="foot-text">
          <span>{info.short} games, with a{pad === "xbox" ? "n" : ""} <b>{PAD_NAME[pad]}</b> controller</span>
          <span class="tip">Each console remembers its own buttons for Xbox and for DualSense. They only apply on this PC, so handing over a controller in co-op just works.</span>
        </div>
        <button class="btn" onclick={() => app.resetConsole(cid, pad)}>Reset to defaults</button>
      </div>
    </section>
  </main>
</div>

<style>
  .page { height: 100%; display: flex; flex-direction: column; }
  .status { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--amber); }
  .dot.ok { background: #3ba55d; }
  .seg { display: inline-flex; padding: 3px; border-radius: 10px; background: var(--panel); border: 1px solid var(--line); }
  .seg button { height: 34px; padding: 0 14px; border-radius: 8px; border: 0; background: transparent; color: var(--muted); font-size: 13px; font-weight: 600; }
  .seg button.on { background: var(--red-2); color: #fff; font-weight: 700; }
  .seg.small { border-radius: 9px; }
  .seg.small button { height: 28px; padding: 0 12px; border-radius: 7px; font-size: 12px; }

  .tiles { flex-shrink: 0; display: flex; gap: 6px; padding: 14px 28px 0; overflow-x: auto; }
  .tile { display: inline-flex; flex-direction: column; align-items: center; gap: 5px; padding: 5px 5px 7px; border-radius: 10px; border: 1px solid var(--line); background: var(--panel); width: 92px; flex-shrink: 0; color: var(--text); }
  .tile.sel { border: 2px solid var(--red); background: #2a1718; }
  .ph { width: 80px; height: 46px; display: flex; align-items: center; justify-content: center; }
  .ph img { max-width: 76px; max-height: 42px; object-fit: contain; }

  main { flex: 1; display: flex; gap: 22px; padding: 14px 28px 22px; min-height: 0; }
  .left { width: 46%; max-width: 640px; flex-shrink: 0; display: flex; flex-direction: column; gap: 10px; padding-right: 6px; }
  .right { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 7px; padding-right: 6px; }
  .title { display: flex; align-items: baseline; gap: 12px; }
  .tip { font-size: 12px; color: var(--muted-2); }
  .view { position: relative; padding: 6px 0; flex-shrink: 0; }
  .vlab { position: absolute; left: 0; top: 0; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; color: var(--muted-2); }
  .dg { position: relative; margin: 0 auto; }
  .dg img { display: block; width: 100%; height: 100%; object-fit: contain; }
  .hs { position: absolute; border-radius: 5px; background: rgba(242, 180, 90, 0.16); box-shadow: 0 0 0 3px var(--amber), 0 0 16px 3px rgba(242, 180, 90, 0.75); opacity: 0; transition: opacity 0.12s; pointer-events: none; }
  .hs.pill { border-radius: 999px; }
  .hs.on { opacity: 1; }
  .note { font-size: 12px; color: var(--muted); margin: 4px 0 0; }

  .presets { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
  .label.extras { margin: 8px 0 2px; }
  .map { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--line-soft); background: var(--panel); transition: border-color 0.12s, background 0.12s; flex-shrink: 0; }
  .map:hover:not(.fixed) { border-color: var(--amber); background: #2a1f14; }
  .map.listen { border: 2px solid var(--amber); background: #2a1f14; padding: 9px 11px; }
  .from { width: 170px; font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
  .hint { font-weight: 400; color: var(--muted); font-size: 12px; }
  .arrow { color: var(--muted-2); }
  .or { font-size: 12px; color: var(--muted-2); }
  .press { font-size: 13px; color: var(--amber); font-weight: 600; }
  .now { margin-left: 8px; display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted-2); }
  .chg { margin-left: auto; height: 32px; padding: 0 12px; border-radius: 8px; border: 1px solid var(--line-2); background: transparent; color: var(--text-2); font-size: 12px; }
  .chg:hover:not(:disabled) { background: var(--btn); }
  .problem { font-size: 13px; color: var(--amber); margin: 2px 0; }
  .foot { margin-top: auto; display: flex; align-items: center; gap: 12px; padding-top: 14px; }
  .foot-text { display: flex; flex-direction: column; gap: 3px; flex: 1; font-size: 14px; }
</style>

<script lang="ts">
  import TopBar from "../components/TopBar.svelte";
  import Icon from "../components/Icon.svelte";
  import Toggle from "../components/Toggle.svelte";
  import PadGlyph from "../components/PadGlyph.svelte";
  import Avatar from "../components/Avatar.svelte";
  import Controllers from "./Controllers.svelte";
  import { app, type Route } from "../lib/state.svelte";
  import { shortAddress } from "../lib/account";
  import { CONSOLES, consoleById, type ConsoleId } from "../lib/consoles";
  import { LAYOUTS } from "../lib/controllers";
  import { PAD_NAME } from "../lib/pads";
  import { clearCoverCache, clearGames, coverCacheSize, folderSize, formatGB, gamesFolder, pickFolder } from "../lib/native";
  import { formatSize } from "../lib/library";

  type Tab = Extract<Route, { name: "settings" }>["tab"];
  let { tab, console: cid }: { tab: Tab; console: ConsoleId } = $props();

  const NAV: { tab: Tab; name: string; icon: string }[] = [
    { tab: "controllers", name: "Controllers", icon: '<rect x="2" y="8" width="20" height="10" rx="5"/><path d="M7 11v4M5 13h4"/><circle cx="16" cy="12" r="1"/><circle cx="18.5" cy="14" r="1"/>' },
    { tab: "consoles", name: "Consoles", icon: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>' },
    { tab: "storage", name: "Storage", icon: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>' },
    { tab: "account", name: "Account", icon: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>' },
  ];
  const go = (t: Tab, c: ConsoleId = cid) => {
    // The controller screen is its own page, so "back" returns here.
    if (t === "controllers") app.go({ name: "settings", tab: t, console: c });
    else app.route = { name: "settings", tab: t, console: c };
  };

  let used = $state(0);
  let confirmClear = $state(false);
  let artUsed = $state(0);
  let artCleared = $state(false);
  $effect(() => {
    folderSize(app.settings.romsFolder).then((n) => (used = n));
  });
  $effect(() => {
    if (tab === "storage") coverCacheSize().then((n) => (artUsed = n));
  });
  async function clearArt() {
    await clearCoverCache();
    artUsed = await coverCacheSize();
    artCleared = true;
  }

  const info = $derived(consoleById(cid));
  const cs = $derived(app.consoleSettings(cid));
  const pad = $derived(app.viewPad);
  const map = $derived(app.mapping(cid, pad));

  async function moveFolder() {
    const p = await pickFolder();
    if (p) {
      app.settings.romsFolder = await gamesFolder(p);
      app.save();
    }
  }
  async function doClear() {
    await clearGames(app.settings.romsFolder);
    used = await folderSize(app.settings.romsFolder);
    confirmClear = false;
  }
  const signOut = () => app.signOut();
</script>

{#if tab === "controllers"}
  <Controllers console={cid} />
{:else}
  <div class="page">
    <TopBar backLabel="Main menu" where="Settings / {NAV.find((n) => n.tab === tab)?.name}" />
    <main>
      <aside>
        {#each NAV as n (n.tab)}
          <button class="nav" class:on={tab === n.tab} onclick={() => go(n.tab)}><Icon svg={n.icon} />{n.name}</button>
        {/each}
        <div class="storage-card">
          <div class="label">STORAGE</div>
          <div class="gb">{#if used}<b>{formatSize(used)}</b> of games{:else}<b>No games</b> on this PC yet{/if}</div>
          <button class="btn small danger" onclick={() => { go("storage"); confirmClear = true; }}>Clear all games</button>
        </div>
      </aside>

      <section class="scroll">
        {#if tab === "consoles"}
          <div class="ctabs">
            {#each CONSOLES as c (c.id)}
              <button class="ctab" class:on={c.id === cid} onclick={() => go("consoles", c.id)}>
                <Icon svg={c.icon} /><span class={c.font} style="font-size:{Math.min(c.navSize, 12)}px">{c.short}</span>
              </button>
            {/each}
          </div>
          <div class="cols">
            <div class="panel grow">
              <div class="phead">
                <span class={info.font} style="font-size:{info.id === 'nes' ? 14 : 24}px">{info.name}</span>
                {#if info.coop}<span class="badge coop">Couch co-op ready</span>{:else}<span class="badge">Solo only for now</span>{/if}
                <span class="emu">Emulator: {info.emulator}</span>
              </div>
              <div class="row">
                <div class="t"><b>Screen shape</b><span>How the picture fits your monitor</span></div>
                <select value={cs.screen} onchange={(e) => app.setConsoleSettings(cid, { screen: e.currentTarget.value as typeof cs.screen })}>
                  <option value="4:3">Like an old TV (4:3)</option>
                  <option value="pixel">Perfect pixels (smaller)</option>
                  <option value="stretch">Fill the screen (stretched)</option>
                </select>
              </div>
              <div class="row">
                <div class="t"><b>Picture style</b><span>Old TV lines, sharp pixels or smooth</span></div>
                <select value={cs.picture} onchange={(e) => app.setConsoleSettings(cid, { picture: e.currentTarget.value as typeof cs.picture })}>
                  <option value="scanlines">Old TV scanlines</option>
                  <option value="sharp">Sharp pixels</option>
                  <option value="smooth">Smooth</option>
                </select>
              </div>
              {#if LAYOUTS[cid].extras.some((e) => e.key === "rewind")}
                <div class="row">
                  <div class="t"><b>Rewind</b><span>Hold a button to go back a few seconds. Solo only.</span></div>
                  <Toggle label="Rewind" on={cs.rewind} onchange={(v) => app.setConsoleSettings(cid, { rewind: v })} />
                </div>
                <div class="row">
                  <div class="t"><b>Fast forward</b><span>Speed through slow parts. Solo only.</span></div>
                  <Toggle label="Fast forward" on={cs.fastForward} onchange={(v) => app.setConsoleSettings(cid, { fastForward: v })} />
                </div>
              {/if}
              <div class="row">
                <div class="t"><b>Show FPS</b><span>Small numbers in the corner while you play</span></div>
                <Toggle label="Show FPS" on={cs.showFps} onchange={(v) => app.setConsoleSettings(cid, { showFps: v })} />
              </div>
              <div class="pfoot">
                <span>In couch co-op, the game itself uses Game Night's settings so everyone stays in sync. Picture settings only change your screen.</span>
                <button class="btn small" onclick={() => { app.settings.consoles[cid] = undefined; app.save(); }}>Reset defaults</button>
              </div>
            </div>
            <div class="panel side">
              <div class="phead small">
                <b>Your controller for {info.short}</b>
                <span class="found" class:none={!app.pad.connected}>{app.pad.connected ? `${PAD_NAME[app.pad.type]} controller found` : "No controller plugged in"}</span>
              </div>
              <img class="thumb" src="/ctl/{LAYOUTS[cid].front.img}.webp" alt="" />
              <div class="maplist">
                {#each LAYOUTS[cid].buttons.slice(0, 8) as b (b.key)}
                  <div class="ml"><span>{info.short} {b.label}</span>{#if map[b.key]}<PadGlyph {pad} input={map[b.key]} />{/if}</div>
                {/each}
              </div>
              <button class="btn primary wide" onclick={() => go("controllers")}>Change buttons</button>
            </div>
          </div>
        {:else if tab === "storage"}
          <div class="panel">
            <div class="phead"><b class="h">Where games are kept</b></div>
            <div class="row">
              <div class="t"><b>{app.settings.romsFolder || "Not chosen yet"}</b><span>Every game you download goes here. {used ? formatSize(used) + " used." : "Nothing downloaded yet."}</span></div>
              <button class="btn small" onclick={moveFolder}>Change folder</button>
            </div>
            <div class="row">
              <div class="t"><b>Clear my games</b><span>Deletes every downloaded game from this PC. Your saves are safe on the Game Night server, and you can download games again any time.</span></div>
              {#if confirmClear}
                <button class="btn small" onclick={() => (confirmClear = false)}>Cancel</button>
                <button class="btn small danger" onclick={doClear}>Yes, delete them</button>
              {:else}
                <button class="btn small danger" onclick={() => (confirmClear = true)}>Clear all games</button>
              {/if}
            </div>
            <div class="row">
              <div class="t"><b>Saved box art</b><span>Covers are kept on this PC so the library opens fast, even offline. {artCleared ? "Cleared. Covers download again as you browse." : artUsed ? formatSize(artUsed) + " used." : "Nothing saved yet."}</span></div>
              <button class="btn small" onclick={clearArt} disabled={!artUsed}>Clear box art</button>
            </div>
          </div>
        {:else if tab === "account"}
          <div class="panel">
            <div class="phead"><b class="h">Account</b></div>
            <div class="row">
              {#if app.user}<Avatar name={app.user.name} src={app.user.avatar} size={44} />{/if}
              <div class="t"><b>{app.user?.name}</b><span>Signed in with Discord. Game Night only sees your Discord name and picture.</span></div>
              <button class="btn small" onclick={signOut}>Sign out</button>
            </div>
            {#if app.server && app.server !== "preview"}<div class="row"><div class="t"><b>Game Night server</b><span>{shortAddress(app.server)}</span></div></div>{/if}
          </div>
        {/if}
      </section>
    </main>
  </div>
{/if}

<style>
  .page { height: 100%; display: flex; flex-direction: column; }
  main { flex: 1; display: flex; min-height: 0; }
  aside { width: 230px; flex-shrink: 0; border-right: 1px solid var(--line-soft); padding: 16px 12px; display: flex; flex-direction: column; gap: 2px; }
  .nav { display: flex; align-items: center; gap: 12px; height: 44px; padding: 0 12px; border-radius: 10px; border: 0; background: transparent; color: var(--text); font-size: 15px; text-align: left; width: 100%; }
  .nav :global(svg) { color: var(--link); }
  .nav:hover { background: var(--panel); }
  .nav.on { background: var(--red-2); color: #fff; }
  .nav.on :global(svg) { color: #fff; }
  .storage-card { margin-top: auto; border-radius: 12px; border: 1px solid var(--line); background: var(--panel); padding: 14px 12px; display: flex; flex-direction: column; gap: 10px; }
  .gb { font-size: 13px; color: var(--muted); }
  .gb b { font-size: 20px; color: var(--text); }
  .danger { border-color: var(--red-2); color: var(--link); }
  .danger:hover { background: #3a1416 !important; }

  section { flex: 1; min-width: 0; padding: 20px 28px; display: flex; flex-direction: column; gap: 18px; }
  .ctabs { display: grid; grid-template-columns: repeat(11, minmax(0, 1fr)); gap: 8px; }
  .ctab { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; height: 72px; border-radius: 12px; border: 1px solid var(--line); background: var(--panel); color: var(--text); padding: 0 4px; }
  .ctab :global(svg) { color: var(--link); }
  .ctab.on { border: 2px solid var(--red); background: #2a1718; }
  .cols { display: flex; gap: 24px; min-height: 0; }
  .panel { border-radius: 14px; border: 1px solid var(--line); background: var(--panel); display: flex; flex-direction: column; }
  .grow { flex: 1; min-width: 0; }
  .side { width: 360px; flex-shrink: 0; padding: 16px; gap: 14px; }
  .phead { display: flex; align-items: center; gap: 14px; padding: 18px 16px; border-bottom: 1px solid var(--line-soft); }
  .phead.small { padding: 0; border: 0; justify-content: space-between; font-size: 14px; }
  .phead .h { font-size: 17px; }
  .emu { margin-left: auto; font-size: 12px; color: var(--muted-2); }
  .found { font-size: 12px; color: var(--green); }
  .found.none { color: var(--amber); }
  .row { display: flex; align-items: center; gap: 16px; padding: 14px 16px; border-bottom: 1px solid var(--line-soft); }
  .t { display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0; }
  .t b { font-size: 14px; font-weight: 600; word-break: break-all; }
  .t span { font-size: 12px; color: var(--muted); }
  select { background: var(--bg); color: var(--text); border: 1px solid var(--line-2); border-radius: 8px; height: 40px; padding: 0 12px; font-size: 14px; }
  .pfoot { display: flex; align-items: center; gap: 16px; padding: 14px 16px; font-size: 12px; color: var(--muted-2); margin-top: auto; }
  .thumb { width: 100%; max-height: 180px; object-fit: contain; }
  .maplist { display: flex; flex-direction: column; gap: 6px; }
  .ml { display: flex; align-items: center; justify-content: space-between; font-size: 13px; color: var(--text-2); }
  .wide { width: 100%; height: 46px; margin-top: auto; }
</style>

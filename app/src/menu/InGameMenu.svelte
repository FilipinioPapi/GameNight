<script lang="ts">
  // Game Night's in-game menu (board IG2) and the "Paused by" screen (board IG3), both approved 2026-10-31.
  // This page lives in a see-through window of its own over the game (src-tauri/src/ingame.rs).
  // Controller first: D-pad or left stick moves, A picks, left / right changes a value, LB / RB change tab,
  // B goes back to the game (the Xbox / PS button closes it too, on the Windows side). Mouse and keyboard work too.
  import { onMount, tick } from "svelte";
  import { padTypeFromId, type PadType } from "../lib/pads";
  import { inTauri } from "../lib/settings";
  import { sampleInfo, type MenuInfo } from "./sample";

  async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<T>(cmd, args);
  }
  function note(text: string) {
    if (inTauri) void invoke("ingame_note", { text }).catch(() => {});
  }

  let info = $state<MenuInfo | null>(inTauri ? null : sampleInfo());
  let tab = $state(0);
  let sel = $state(0);
  let confirm = $state<null | { title: string; sub: string; yes: string; act: () => void }>(null);
  let confirmSel = $state(1);
  let busy = $state("");
  let toast = $state("");
  let pad = $state<PadType>("xbox");

  const open = $derived(!!info?.open);
  const couch = $derived(info?.mode === "couch");
  const lobby = $derived(info?.lobby ?? null);
  const paused = $derived(lobby?.paused ?? null);
  const you = $derived(lobby?.you ?? null);
  const pausedByYou = $derived(!!paused && !!you && paused.by?.id === you.id);
  const canResumeAll = $derived(!!paused && (pausedByYou || !!info?.host));
  const playingSeat = $derived(!!you && (you.role === "host" || you.role === "play"));

  // ---- the looks (the same names as Settings › Consoles; each runs on this PC only)
  const LOOKS: [string, string][] = [
    ["sharp", "SHARP PIXELS"], ["scanlines", "OLD TV SCANLINES"], ["easymode", "CRT: EASYMODE"],
    ["lottesfast", "CRT: LOTTES FAST"], ["hyllian", "CRT: HYLLIAN"], ["lottes", "CRT: LOTTES"],
    ["geom", "CRT: CURVED GLASS"], ["royale", "CRT: ROYALE"], ["sharpsmooth", "SMOOTH: SHARP BILINEAR"],
    ["xbr", "SMOOTH: XBR"], ["scalefx", "SMOOTH: SCALEFX"], ["hq4x", "SMOOTH: HQ4X"],
  ];
  const lookName = (l: string) => LOOKS.find((x) => x[0] === l)?.[1] ?? (l === "smooth" ? "SMOOTH: SOFT BLUR" : l.toUpperCase());

  type Item = { name: string; sub: string; val?: string; danger?: boolean; dis?: boolean; act?: () => void; step?: (d: 1 | -1) => void };

  function ask(title: string, sub: string, yes: string, act: () => void) {
    confirm = { title, sub, yes, act };
    confirmSel = 1; // "Keep playing" first, so a quick double press never quits by mistake
  }

  async function run(action: string, value?: string, done?: string) {
    if (busy) return;
    busy = action;
    note(`picked ${action}${value ? " " + value : ""}`);
    try {
      if (!inTauri) {
        if (action === "resume" || action === "lobby" || action === "fullscreen") info = info && { ...info, open: false };
        return;
      }
      const next = await invoke<MenuInfo | null>("ingame_do", { action, value: value ?? null });
      if (next) info = next;
      if (done) flash(done);
    } catch (e) {
      flash(String(e));
    } finally {
      busy = "";
    }
  }
  let toastTimer: ReturnType<typeof setTimeout> | undefined;
  function flash(t: string) {
    toast = t;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = ""), 2500);
  }

  function stepLook(d: 1 | -1) {
    const now = info?.look ?? "scanlines";
    let i = LOOKS.findIndex((x) => x[0] === now);
    if (i < 0) i = 0;
    const next = LOOKS[(i + d + LOOKS.length) % LOOKS.length][0];
    if (info) info = { ...info, look: next };
    void run("look", next);
  }

  const tabs = ["HOME", "MY SCREEN"];
  const items = $derived.by<Item[]>(() => {
    if (!info) return [];
    if (tab === 1)
      return [
        { name: "LOOK", sub: couch ? "Your screen only. Friends keep their own look" : "Changes straight away behind the menu", val: lookName(info.look), step: stepLook, act: () => stepLook(1) },
      ];
    if (!couch)
      return [
        { name: "RESUME", sub: "Back into the game", act: () => void run("resume") },
        { name: "SAVE STATE", sub: "Save right here", act: () => void run("save_state", undefined, "Saved") },
        { name: "LOAD STATE", sub: "Go back to your last save", act: () => void run("load_state") },
        { name: "RESTART GAME", sub: "Asks first", act: () => ask("RESTART THE GAME?", "Anything not saved in the game is lost.", "YES, RESTART", () => void run("restart")) },
        { name: "QUIT TO LIBRARY", sub: "Your game saves are kept", danger: true, act: () => ask("QUIT TO THE LIBRARY?", "Your game's own saves are kept.", "YES, QUIT", () => void run("quit")) },
      ];
    const list: Item[] = [{ name: "RESUME", sub: paused && canResumeAll ? "Back into the game, for everyone" : "Back into the game", act: () => void (paused && canResumeAll ? run("unpause_all").then(() => run("resume")) : run("resume")) }];
    if (paused) {
      list.push(canResumeAll
        ? { name: "RESUME FOR EVERYONE", sub: `Paused by ${pausedByYou ? "you" : paused.by?.name ?? "a friend"}`, act: () => void run("unpause_all") }
        : { name: "RESUME FOR EVERYONE", sub: `Only ${paused.by?.name ?? "they"} or the host can`, dis: true });
    } else if (playingSeat) {
      list.push({ name: "PAUSE FOR EVERYONE", sub: `Everyone sees "Paused by ${you?.id ? nameOf(you.id) : "you"}"`, act: () => void run("pause_all") });
    }
    list.push(info.fullscreen
      ? { name: "BACK TO LOBBY", sub: "Keeps your seat. Game shows in the small box", act: () => void run("lobby") }
      : { name: "FULL SCREEN", sub: "The game fills the screen", act: () => void run("fullscreen") });
    if (you?.role === "play") list.push({ name: "SWITCH TO WATCHING", sub: `Frees P${you.seat ?? ""} for someone else`, act: () => void run("watch") });
    else if (you?.role === "watch") list.push({ name: "SWITCH TO PLAYING", sub: "Takes a free seat", act: () => void run("play") });
    list.push({ name: "REFRESH GAME", sub: info.host ? "Saves the spot, restarts, carries on" : "Restarts your game. You keep your seat", act: () => void run("refresh") });
    list.push(info.host
      ? { name: "END GAME FOR EVERYONE", sub: "Host only. Asks first", danger: true, act: () => ask("END THE GAME FOR EVERYONE?", "The lobby closes for all your friends.", "YES, END IT", () => void run("leave")) }
      : { name: "LEAVE LOBBY", sub: "Asks first", danger: true, act: () => ask("LEAVE THE LOBBY?", "Your seat is freed for someone else.", "YES, LEAVE", () => void run("leave")) });
    return list;
  });
  function nameOf(id: string): string {
    const seat = lobby?.seats?.find((s) => s.user?.id === id);
    return seat?.user?.name ?? lobby?.watchers?.find((w) => w.id === id)?.name ?? "you";
  }
  const notes = $derived(couch
    ? ["Only you see this menu. Your friends keep playing.", "Only your screen changes. Bezel, pixels and screen shape are in Settings › Consoles (from the next game). CRT Royale needs a strong graphics card."]
    : ["The game is paused while this menu is open.", "Bezel, pixels and screen shape are in Settings › Consoles (from the next game)."]);
  const s = $derived(Math.min(sel, Math.max(0, items.length - 1)));

  // ---- seats on the right (Couch Play)
  const COLORS = ["#5865f2", "#2a5ab8", "#2a8a6a", "#b8762a", "#c0662a", "#7a3a8a", "#3a7a8a", "#8a3a4a"];
  const seats = $derived.by(() => {
    if (!lobby) return [];
    const out: { lab: string; name: string; init: string; col: string; sub: string; me: boolean; empty: boolean; watch: boolean }[] = [];
    let c = 0;
    for (const st of lobby.seats ?? []) {
      const u = st.user;
      const me = !!u && u.id === you?.id;
      out.push({ lab: `P${st.n}`, name: u ? u.name.toUpperCase() + (me ? " (YOU)" : "") : "", init: u ? u.name.slice(0, 1).toUpperCase() : "", col: COLORS[c++ % COLORS.length], sub: u ? (me ? "in menu" : st.status === "held" ? "dropped out" : "playing") : "free seat", me, empty: !u, watch: false });
    }
    for (const w of lobby.watchers ?? []) {
      const me = w.id === you?.id;
      out.push({ lab: "WATCH", name: w.name.toUpperCase() + (me ? " (YOU)" : ""), init: w.name.slice(0, 1).toUpperCase(), col: COLORS[c++ % COLORS.length], sub: me ? "in menu" : "watching", me, empty: false, watch: true });
    }
    return out;
  });
  const crumb = $derived(info ? (couch ? `COUCH PLAY › ${info.title.toUpperCase()}` : `${(info.console || "").toUpperCase()} › ${info.title.toUpperCase()}`) : "");

  // ---- "Paused by" timer
  let pausedFor = $state(0);
  $effect(() => {
    if (!paused) return;
    const start = performance.now() - (paused.seconds ?? 0) * 1000;
    pausedFor = paused.seconds ?? 0;
    const t = setInterval(() => (pausedFor = Math.floor((performance.now() - start) / 1000)), 500);
    return () => clearInterval(t);
  });
  const clock = (n: number) => `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;

  // ---- moving around
  let listEl = $state<HTMLDivElement | null>(null);
  function focusSel() {
    void tick().then(() => {
      if (confirm) document.querySelectorAll<HTMLButtonElement>(".confirm button")[confirmSel]?.focus({ preventScroll: true });
      else listEl?.querySelectorAll<HTMLButtonElement>("button.it")[s]?.focus({ preventScroll: true });
    });
  }
  function move(d: "up" | "down" | "left" | "right") {
    if (confirm) {
      if (d === "left" || d === "right") confirmSel = confirmSel ? 0 : 1;
    } else if (d === "up" || d === "down") {
      const n = items.length;
      if (!n) return;
      let i = s;
      for (let k = 0; k < n; k++) {
        i = (i + (d === "down" ? 1 : -1) + n) % n;
        if (!items[i].dis) break;
      }
      sel = i;
    } else items[s]?.step?.(d === "right" ? 1 : -1);
    focusSel();
  }
  function pick() {
    if (confirm) {
      const c = confirm;
      confirm = null;
      if (confirmSel === 0) c.act();
      focusSel();
      return;
    }
    const it = items[s];
    if (it && !it.dis) it.act?.();
  }
  function back() {
    if (confirm) {
      confirm = null;
      focusSel();
      return;
    }
    void run("resume");
  }
  function switchTab(d: 1 | -1) {
    if (confirm) return;
    tab = (tab + d + tabs.length) % tabs.length;
    sel = 0;
    focusSel();
  }

  // ---- the controller (Game Night's Windows side reads it: "pad" events, and asked every frame)
  type NativePad = { connected: boolean; name: string; id: string; buttons: boolean[]; axes: number[]; seq?: number };
  let latest: NativePad | null = null;
  let newest = 0;
  let prev: boolean[] = [];
  let stick: string | null = null;
  let heldDir: { key: number; since: number; last: number } | null = null;
  function take(p: NativePad) {
    if (typeof p.seq === "number") {
      if (p.seq < newest) return;
      newest = p.seq;
    }
    latest = p;
  }
  /** Buttons already down when the menu opens (the press that opened it) aren't new presses. */
  function forgetHeld() {
    prev = latest?.buttons ? [...latest.buttons] : [];
    stick = "held";
    heldDir = null;
  }
  function press(i: number) {
    if (i >= 12 && i <= 15) return move((["up", "down", "left", "right"] as const)[i - 12]);
    if (i === 0) pick();
    else if (i === 1) back();
    else if (i === 4) switchTab(-1);
    else if (i === 5) switchTab(1);
  }
  let asking = false;
  async function frame() {
    if (inTauri && !asking) {
      asking = true;
      invoke<NativePad>("pad_state").then(take, () => {}).finally(() => (asking = false));
    }
    const p = latest;
    if (p?.connected) {
      const t = padTypeFromId(`${p.name} ${p.id}`);
      if (t !== pad) pad = t;
    }
    if (open && !busy && p?.connected) {
      const now = performance.now();
      p.buttons.forEach((down, i) => {
        if (down && !prev[i]) press(i);
        if (i >= 12 && i <= 15) {
          if (!down) {
            if (heldDir?.key === i) heldDir = null;
          } else if (!heldDir || heldDir.key !== i) heldDir = { key: i, since: now, last: now };
          else if (now - heldDir.since > 340 && now - heldDir.last > 110 && i <= 13) {
            heldDir.last = now;
            press(i);
          }
        }
      });
      prev = [...p.buttons];
      const [lx = 0, ly = 0] = p.axes;
      const push = Math.max(Math.abs(lx), Math.abs(ly));
      let dir: string | null = stick;
      if (push > 0.7) dir = Math.abs(lx) > Math.abs(ly) ? (lx > 0 ? "right" : "left") : ly > 0 ? "down" : "up";
      else if (push < 0.45) dir = null;
      if (dir && dir !== stick && stick !== "held") move(dir as "up");
      if (!(stick === "held" && dir)) stick = dir;
    } else if (p) prev = [...p.buttons];
    requestAnimationFrame(frame);
  }

  // ---- keyboard backup (once the menu window is in front)
  function onKey(e: KeyboardEvent) {
    if (!open) return;
    const k = e.key;
    const map: Record<string, () => void> = {
      ArrowUp: () => move("up"), ArrowDown: () => move("down"), ArrowLeft: () => move("left"), ArrowRight: () => move("right"),
      Enter: pick, " ": pick, Escape: back, Backspace: back, q: () => switchTab(-1), e: () => switchTab(1), PageUp: () => switchTab(-1), PageDown: () => switchTab(1),
    };
    if (map[k]) {
      e.preventDefault();
      map[k]();
    }
  }

  // A fresh start every time the menu opens: HOME tab, first item.
  let wasOpen = false;
  $effect(() => {
    const o = open;
    if (o && !wasOpen) {
      tab = 0;
      sel = 0;
      confirm = null;
      toast = "";
      forgetHeld();
      focusSel();
      note(`showing: ${info?.mode} menu, ${items.length} items on HOME (${items.map((x) => x.name).join(", ")})`);
    }
    wasOpen = o;
  });

  onMount(() => {
    requestAnimationFrame(frame);
    if (!inTauri) return;
    let un: (() => void)[] = [];
    void (async () => {
      const { listen } = await import("@tauri-apps/api/event");
      un.push(await listen<NativePad>("pad", (e) => take(e.payload)));
      un.push(await listen<MenuInfo>("ingame-menu", (e) => (info = e.payload?.mode ? e.payload : null)));
      try {
        info = await invoke<MenuInfo | null>("ingame_info");
      } catch {
        // Asked again with the next "ingame-menu" event.
      }
      note("menu page ready");
    })();
    return () => un.forEach((f) => f());
  });

  const prompt = (b: string) => (pad === "dualsense" ? `/prompts/ps/ps_${b}.png` : `/prompts/xbox/xbox_${b}.png`);
  const homeName = $derived(pad === "dualsense" ? "PS button" : "Xbox button");
</script>

<svelte:window onkeydown={onKey} />

{#if info && open}
  <div class="root" class:solo={!couch}>
    <div class="dim" aria-hidden="true"></div>
    {#if couch}
      <span class="pill" class:p={!!paused}><i></i>{paused ? `PAUSED FOR EVERYONE · BY ${(pausedByYou ? "YOU" : paused.by?.name ?? "").toUpperCase()}` : "GAME STILL RUNNING · YOUR PLAYER STANDS STILL"}</span>
      {#if lobby}
        <aside class="lob" aria-label="Who is in the lobby">
          <span class="lh">&gt; LOBBY <b>{lobby.code}</b></span>
          {#each seats as st, i (i)}
            <div class="st" class:e={st.empty}>
              <span class="sl" class:w={st.watch}>{st.lab}</span>
              {#if !st.empty}<span class="av" style="background:{st.col}">{st.init}</span><span class="sn" class:me={st.me}>{st.name}</span>{/if}
              <span class="ss">{st.sub}</span>
            </div>
          {/each}
        </aside>
      {/if}
    {:else}
      <span class="pill p"><i></i>PAUSED</span>
    {/if}

    <section class="panel" aria-label="Game menu">
      <div class="hd">
        <img class="tvlogo" src="/brand/crt-logo.gif" alt="Game Night logo" />
        <div class="hcol"><span class="crumb">{crumb}</span><span class="ttl">GAME MENU</span></div>
      </div>
      <nav class="tabs" aria-label="Menu tabs">
        <img src={prompt("lb")} alt={pad === "dualsense" ? "L1" : "LB"} />
        {#each tabs as t, i (t)}
          <button class="tab" class:on={i === tab} tabindex="-1" onclick={() => { tab = i; sel = 0; focusSel(); }}>{t}</button>
        {/each}
        <img src={prompt("rb")} alt={pad === "dualsense" ? "R1" : "RB"} />
      </nav>
      <div class="list" bind:this={listEl}>
        <span class="glide" style="transform: translateY({s * 62}px)"></span>
        {#each items as x, i (tab + x.name)}
          <button class="it" class:danger={x.danger} class:dis={x.dis} disabled={x.dis}
            onclick={() => { sel = i; pick(); }} onmouseenter={() => { if (!x.dis) sel = i; }}>
            <span class="col"><b>{x.name}</b><span class="sub">{x.sub}</span></span>
            {#if x.val}<span class="val"><i>◀</i>{x.val}<i>▶</i></span>{/if}
          </button>
        {/each}
      </div>
      <p class="note">{notes[tab]}</p>
      {#if toast}<p class="toast" role="status">{toast}</p>{/if}
    </section>

    {#if confirm}
      <div class="confirm" role="dialog" aria-modal="true" aria-label={confirm.title}>
        <b>{confirm.title}</b>
        <span>{confirm.sub}</span>
        <div class="cb">
          <button class:on={confirmSel === 0} class="danger" onclick={() => { confirmSel = 0; pick(); }}>{confirm.yes}</button>
          <button class:on={confirmSel === 1} onclick={() => { confirmSel = 1; pick(); }}>KEEP PLAYING</button>
        </div>
      </div>
    {/if}

    <footer class="guide" aria-label="Controller buttons">
      <span class="gi"><img class="px" src={prompt("a")} alt="A" />{confirm ? "Pick" : tab === 1 ? "Change" : "Pick"}</span>
      {#if !confirm}<span class="gi"><img class="px wide" src={prompt("lb")} alt="LB" /><img class="px wide" src={prompt("rb")} alt="RB" />Tabs</span>{/if}
      <span class="gi"><img class="px" src={prompt("b")} alt="B" />{confirm ? "Cancel" : "Back to game"}</span>
      <span class="gi"><span class="gb" aria-hidden="true"></span>{homeName}: close menu</span>
    </footer>
  </div>
{:else if info && couch && paused}
  <!-- Board IG3: someone paused the game for everyone. -->
  <div class="root">
    <div class="dim full" aria-hidden="true"></div>
    <section class="box" aria-label="Game paused">
      <div class="who"><span class="avbig">{(pausedByYou ? "Y" : paused.by?.name ?? "?").slice(0, 1).toUpperCase()}</span><span class="big">PAUSED BY<br />{pausedByYou ? "YOU" : (paused.by?.name ?? "A FRIEND").toUpperCase()}</span></div>
      <span class="ln">{pausedByYou ? "The game carries on when you press Resume in your menu." : `The game carries on when ${paused.by?.name ?? "they"} presses Resume.`}</span>
      <span class="tm">PAUSED {clock(pausedFor)}</span>
      <span class="mut">{info.host && !pausedByYou ? "You are the host: open your menu to resume for everyone if it goes on too long." : "Good moment to hand the pad over or grab a drink."}</span>
    </section>
    <footer class="guide" aria-label="Controller buttons">
      <span class="gi"><span class="gb" aria-hidden="true"></span>{homeName}: your own menu{info.host || pausedByYou ? " (Resume for everyone is in it)" : " (your screen settings)"}</span>
    </footer>
  </div>
{/if}

<style>
  :global(html), :global(body), :global(#menu) { margin: 0; height: 100%; background: transparent; overflow: hidden; user-select: none; }
  :global(body) { font-family: Inter, system-ui, sans-serif; color: #f6e9e9; -webkit-font-smoothing: antialiased; }
  .root { position: fixed; inset: 0; overflow: hidden; isolation: isolate; }
  .dim { position: absolute; inset: 0; background: linear-gradient(90deg, rgba(8,4,4,.94) 0, rgba(8,4,4,.9) 560px, rgba(8,4,4,.45) 760px, rgba(8,4,4,.35) 100%); }
  .solo .dim { background: linear-gradient(90deg, rgba(8,4,4,.94) 0, rgba(8,4,4,.9) 560px, rgba(8,4,4,.6) 760px, rgba(8,4,4,.55) 100%); }
  .dim.full { background: rgba(8,4,4,.62); }
  .panel { position: absolute; left: 0; top: 0; bottom: 64px; width: 560px; padding: 30px 36px 0 40px; box-sizing: border-box; display: flex; flex-direction: column; gap: 14px; border-right: 1px solid #5a2225; box-shadow: 1px 0 18px rgba(236,40,46,.25); }
  .hd { display: flex; align-items: center; gap: 14px; }
  .tvlogo { width: 44px; height: 54px; object-fit: contain; filter: drop-shadow(0 0 8px rgba(236,40,46,.35)) drop-shadow(0 3px 0 #000); }
  .hcol { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .crumb { font-family: VT323, monospace; font-size: 17px; letter-spacing: .12em; color: #bfa7a8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ttl { font-family: "Press Start 2P", monospace; font-size: 20px; color: #ff2a32; text-shadow: 0 0 3px #ff5a60, 0 0 12px #ec282e, 0 0 26px rgba(236,40,46,.85), 3px 3px 0 #000; }
  .tabs { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
  .tabs img { image-rendering: pixelated; height: 18px; width: auto; }
  .tab { font-family: "Press Start 2P", monospace; font-size: 10px; padding: 9px 10px; border-radius: 8px; border: 1px solid transparent; background: none; color: #bfa7a8; cursor: pointer; }
  .tab.on { color: #fff6d8; border-color: #f2b45a; background: rgba(242,180,90,.1); text-shadow: 0 0 6px #ffb21e; }
  .list { position: relative; display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
  .it { position: relative; z-index: 1; display: flex; align-items: center; gap: 12px; height: 56px; padding: 0 16px; box-sizing: border-box; border-radius: 12px; border: 1px solid #4a2427; background: rgba(30,20,21,.88); color: #f6e9e9; font: inherit; text-align: left; width: 100%; cursor: pointer; outline: none; }
  .it.dis { opacity: .5; cursor: default; }
  .col { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .it b { font-family: "Press Start 2P", monospace; font-weight: 400; font-size: 12px; }
  .sub { font-family: VT323, monospace; font-size: 17px; letter-spacing: .03em; color: #bfa7a8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .val { margin-left: auto; display: flex; align-items: center; gap: 8px; font-family: VT323, monospace; font-size: 20px; letter-spacing: .05em; color: #ffd36b; white-space: nowrap; }
  .val i { font-style: normal; color: #8f7a7c; }
  .danger b { color: #ff8a8f; }
  @keyframes neonGold { 0%, 100% { box-shadow: 0 0 0 1px #fff3c4, 0 0 8px 2px #ffb21e, 0 0 22px 4px rgba(255,150,0,.65), inset 0 0 12px rgba(255,170,40,.45); } 50% { box-shadow: 0 0 0 1px #fff3c4, 0 0 10px 3px #ffc23e, 0 0 28px 6px rgba(255,160,0,.8), inset 0 0 16px rgba(255,180,60,.55); } }
  .glide { position: absolute; left: 0; top: 0; right: 0; height: 56px; border-radius: 12px; border: 2px solid #ffd36b; box-sizing: border-box; animation: neonGold 2.6s ease-in-out infinite; transition: transform .3s cubic-bezier(.2,.8,.2,1); pointer-events: none; z-index: 2; }
  .note { margin: 0; font-family: VT323, monospace; font-size: 19px; letter-spacing: .04em; color: #ffd6d6; line-height: 1.25; }
  .toast { margin: 0; font-family: "Press Start 2P", monospace; font-size: 11px; color: #9fdcb0; text-shadow: 0 0 6px rgba(127,214,154,.6); }
  .pill { position: absolute; top: 24px; right: 28px; display: flex; align-items: center; gap: 8px; font-family: VT323, monospace; font-size: 20px; letter-spacing: .08em; background: rgba(10,6,6,.85); border-radius: 8px; padding: 4px 12px; border: 1px solid #3f7a52; color: #9fdcb0; }
  .pill i { width: 9px; height: 9px; border-radius: 50%; background: #7fd69a; box-shadow: 0 0 6px #7fd69a; }
  .pill.p { border-color: #f2b45a; color: #ffd36b; }
  .pill.p i { background: #ffd36b; box-shadow: 0 0 6px #ffd36b; border-radius: 2px; }
  .lob { position: absolute; right: 28px; top: 76px; width: 340px; padding: 16px; box-sizing: border-box; border-radius: 14px; border: 1px solid #4a2427; background: rgba(14,9,9,.9); display: flex; flex-direction: column; gap: 6px; }
  .lh { display: flex; align-items: baseline; gap: 10px; font-family: VT323, monospace; font-size: 20px; letter-spacing: .06em; color: #ff8a8f; text-shadow: 0 0 6px rgba(255,90,90,.8); }
  .lh b { margin-left: auto; font-family: "Press Start 2P", monospace; font-weight: 400; font-size: 12px; letter-spacing: .14em; color: #fff6d8; text-shadow: 0 0 6px #ffb21e; }
  .st { display: flex; align-items: center; gap: 10px; height: 38px; padding: 0 10px; border-radius: 9px; border: 1px solid #3a2526; background: rgba(30,20,21,.8); }
  .st.e { border-style: dashed; background: none; color: #8f7a7c; }
  .sl { font-family: "Press Start 2P", monospace; font-size: 10px; width: 44px; color: #ff8a8f; }
  .sl.w { font-family: VT323, monospace; font-size: 15px; color: #bfa7a8; }
  .av { width: 24px; height: 24px; border-radius: 50%; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 11px; }
  .sn { font-family: "Press Start 2P", monospace; font-size: 9px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 150px; }
  .ss { margin-left: auto; font-family: VT323, monospace; font-size: 15px; color: #bfa7a8; white-space: nowrap; }
  .me { color: #ffd36b; }
  .confirm { position: absolute; left: 50%; top: 44%; transform: translate(-50%, -50%); width: 560px; padding: 28px 30px; box-sizing: border-box; border-radius: 16px; border: 2px solid #f2b45a; background: rgba(10,6,6,.96); box-shadow: 0 0 24px rgba(242,180,90,.35); display: flex; flex-direction: column; align-items: center; gap: 14px; text-align: center; z-index: 5; }
  .confirm b { font-family: "Press Start 2P", monospace; font-weight: 400; font-size: 15px; color: #fff6d8; text-shadow: 0 0 6px #ffb21e; line-height: 1.4; }
  .confirm span { font-family: VT323, monospace; font-size: 21px; color: #ffd6d6; }
  .cb { display: flex; gap: 14px; margin-top: 6px; }
  .cb button { font-family: "Press Start 2P", monospace; font-size: 11px; padding: 14px 16px; border-radius: 10px; border: 1px solid #4a2427; background: rgba(30,20,21,.9); color: #f6e9e9; outline: none; }
  .cb button.danger { color: #ff8a8f; }
  .cb button.on { border: 2px solid #ffd36b; animation: neonGold 2.6s ease-in-out infinite; }
  .guide { position: absolute; left: 0; right: 0; bottom: 0; height: 64px; display: flex; align-items: center; gap: 26px; padding: 0 40px; border-top: 1px solid #5a2225; background: rgba(10,6,6,.95); box-shadow: 0 -1px 12px rgba(236,40,46,.3); font-family: VT323, monospace; font-size: 20px; letter-spacing: .05em; color: #ffd6d6; text-shadow: 0 0 6px rgba(255,120,120,.6); }
  .gi { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
  .px { image-rendering: pixelated; height: 26px; width: auto; }
  .px.wide { height: 18px; }
  .gb { width: 26px; height: 26px; border-radius: 50%; background: #1f1f1f; border: 2px solid #9fdcb0; box-sizing: border-box; box-shadow: 0 0 6px rgba(127,214,154,.6); }
  .box { position: absolute; left: 50%; top: 44%; transform: translate(-50%, -50%); width: 620px; padding: 30px 34px; box-sizing: border-box; border-radius: 16px; border: 2px solid #f2b45a; background: rgba(10,6,6,.92); box-shadow: 0 0 24px rgba(242,180,90,.35); display: flex; flex-direction: column; align-items: center; gap: 16px; text-align: center; }
  .who { display: flex; align-items: center; gap: 14px; }
  .avbig { width: 48px; height: 48px; border-radius: 50%; background: #5865f2; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 20px; box-shadow: 0 0 12px rgba(88,101,242,.6); }
  .big { font-family: "Press Start 2P", monospace; font-size: 22px; line-height: 1.3; color: #fff6d8; text-shadow: 0 0 4px #ffd36b, 0 0 14px #ffb21e, 3px 3px 0 #000; }
  .ln { font-family: VT323, monospace; font-size: 23px; letter-spacing: .04em; color: #ffd6d6; }
  .mut { font-family: VT323, monospace; font-size: 19px; letter-spacing: .04em; color: #bfa7a8; }
  .tm { font-family: "Press Start 2P", monospace; font-size: 12px; color: #ff8a8f; }
  @media (prefers-reduced-motion: reduce) { .glide, .cb button.on { animation: none; transition: none; } }
</style>
